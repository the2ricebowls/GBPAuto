from __future__ import annotations

import asyncio
import importlib
from collections.abc import Awaitable, Callable
from contextlib import suppress
from typing import Any

from account_automation_lab.adapters.registry import adapter_for
from account_automation_lab.models import JobStatus
from account_automation_lab.profiles import ProfileLockRegistry
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import InvalidJobTransitionError
from account_automation_lab.settings import Settings
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.engine import WorkflowEngine


class JobRunner:
    def __init__(self, *, repository: AutomationRepository, settings: Settings) -> None:
        self.repository = repository
        self.settings = settings
        self.profile_locks = ProfileLockRegistry()
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._poller: asyncio.Task[None] | None = None
        self._workers: list[asyncio.Task[None]] = []
        self._scheduler: object | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop = asyncio.Event()
        self._site_active: dict[str, int] = {}
        self._claimed_site: dict[str, str] = {}
        self._claim_guard = asyncio.Lock()
        self.checkpoints = CheckpointRegistry()
        self.engine = WorkflowEngine()
        self._page_provider: Callable[[str], Awaitable[Any]] = _null_page_provider

    @property
    def is_started(self) -> bool:
        return bool(self._workers) and any(not worker.done() for worker in self._workers)

    def set_page_provider(self, provider: Callable[[str], Awaitable[Any]]) -> None:
        self._page_provider = provider

    def resume(self, job_id: str) -> None:
        self.checkpoints.resume(job_id)

    def cancel_checkpoint(self, job_id: str) -> None:
        self.checkpoints.cancel(job_id)

    async def start(self) -> None:
        if self.is_started:
            return
        self._stop.clear()
        self._loop = asyncio.get_running_loop()
        self._workers = [
            asyncio.create_task(self._worker_loop(index), name=f"account-automation-worker-{index}")
            for index in range(self.settings.max_global_concurrency)
        ]
        self._start_scheduler()
        self._poller = asyncio.create_task(self._poll_loop(), name="account-automation-poller")

    async def stop(self) -> None:
        self._stop.set()
        if self._scheduler is not None:
            shutdown = getattr(self._scheduler, "shutdown", None)
            if shutdown is not None:
                shutdown(wait=False)
        if self._poller is not None:
            self._poller.cancel()
            with suppress(asyncio.CancelledError):
                await self._poller
        for worker in self._workers:
            worker.cancel()
        for worker in self._workers:
            with suppress(asyncio.CancelledError):
                await worker
        self._workers = []

    def _start_scheduler(self) -> bool:
        try:
            module = importlib.import_module("apscheduler.schedulers.asyncio")
        except ImportError:
            return False
        scheduler_cls: Any = module.AsyncIOScheduler
        scheduler = scheduler_cls()
        scheduler.add_job(
            self._schedule_claim,
            "interval",
            seconds=1,
            max_instances=1,
            coalesce=True,
        )
        scheduler.start()
        self._scheduler = scheduler
        return True

    def _schedule_claim(self) -> None:
        if self._loop is None or self._loop.is_closed():
            return
        self._loop.call_soon_threadsafe(self._create_claim_task)

    def _create_claim_task(self) -> None:
        if self._loop is not None and not self._loop.is_closed():
            self._loop.create_task(self._claim_one())

    async def _poll_loop(self) -> None:
        while not self._stop.is_set():
            await self._claim_one()
            await asyncio.sleep(1)

    async def _claim_one(self) -> None:
        async with self._claim_guard:
            excluded = self._sites_at_capacity()
            job = await self.repository.claim_next_queued(exclude_sites=excluded)
            if job is not None:
                self._site_active[job.site_key] = self._site_active.get(job.site_key, 0) + 1
                self._claimed_site[job.id] = job.site_key
                await self._queue.put(job.id)

    def _sites_at_capacity(self) -> set[str]:
        limit = self.settings.max_site_concurrency
        return {site for site, count in self._site_active.items() if count >= limit}

    def _release_site(self, job_id: str) -> None:
        site_key = self._claimed_site.pop(job_id, None)
        if site_key is None:
            return
        remaining = self._site_active.get(site_key, 0) - 1
        if remaining > 0:
            self._site_active[site_key] = remaining
        else:
            self._site_active.pop(site_key, None)

    async def _worker_loop(self, index: int) -> None:
        while not self._stop.is_set():
            job_id = await self._queue.get()
            try:
                await self.repository.add_event(
                    job_id,
                    "job.worker_assigned",
                    f"Worker {index} assigned",
                )
                await self._run_job(job_id)
            finally:
                self._release_site(job_id)
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        job = await self.repository.get_job(job_id)
        if job is None:
            return
        site = await self.repository.get_site(job.site_key)
        try:
            adapter = adapter_for(job.site_key, site)
        except KeyError:
            await self.repository.add_event(
                job_id,
                "job.error",
                f"Unknown site '{job.site_key}' with no code adapter.",
            )
            await self._safe_update_status(job_id, JobStatus.FAILED)
            return
        profile_id = job.profile_id or f"{job.sim_id}:{job.site_key}"
        lock = await self.profile_locks.try_acquire(profile_id)
        if lock is None:
            await self.repository.add_event(
                job_id,
                "job.profile_locked",
                f"Profile {profile_id} is already in use; returning job to failed state.",
            )
            await self.repository.update_job_status(job_id, JobStatus.FAILED)
            return
        try:
            page = await self._page_provider(profile_id)
            ctx = WorkflowContext(
                job_id=job_id,
                profile_id=profile_id,
                page=page,
                repo=self.repository,
                checkpoints=self.checkpoints,
            )
            steps = adapter.workflow(ctx)
            await self.engine.run(ctx, steps)
        except Exception as exc:
            await self.repository.add_event(job_id, "job.error", str(exc))
            await self._safe_update_status(job_id, JobStatus.FAILED)
        finally:
            await lock.release()

    async def _safe_update_status(self, job_id: str, status: JobStatus) -> None:
        """Update job status, tolerating jobs that reached a terminal state mid-run.

        A job can be cancelled (a terminal state) by an operator while a worker is
        still running it. In that case the transition to SUCCEEDED/FAILED is no longer
        valid; we record the conflict as an event instead of crashing the worker.
        """
        try:
            await self.repository.update_job_status(job_id, status)
        except InvalidJobTransitionError:
            await self.repository.add_event(
                job_id,
                "job.status_conflict",
                f"Skipped transition to {status.value}; job already reached a terminal state.",
            )


async def _null_page_provider(_profile_id: str) -> Any:
    class _NoOpPage:
        async def goto(self, *_a: Any, **_k: Any) -> None: ...
        async def fill(self, *_a: Any, **_k: Any) -> None: ...
        async def click(self, *_a: Any, **_k: Any) -> None: ...

    return _NoOpPage()
