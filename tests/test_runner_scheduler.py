from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from account_automation_lab.jobs import runner as runner_module
from account_automation_lab.jobs.runner import JobRunner
from account_automation_lab.models import (
    JobCreate,
    JobStatus,
    SiteSpec,
)
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


@pytest.mark.asyncio
async def test_scheduler_callback_can_claim_from_non_loop_thread() -> None:
    runner = JobRunner(
        repository=MemoryRepository(),
        settings=Settings(max_global_concurrency=1),
    )
    await runner.start()

    errors: list[BaseException] = []

    def call_scheduler() -> None:
        try:
            runner._schedule_claim()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=call_scheduler)
    thread.start()
    thread.join(timeout=2)

    await asyncio.sleep(0.1)
    await runner.stop()

    assert thread.is_alive() is False
    assert errors == []


@pytest.mark.asyncio
async def test_memory_repo_claim_excludes_given_sites() -> None:
    repo = MemoryRepository()
    await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    second = await repo.create_job(JobCreate(site_key="site_02", sim_id="sim-a"))

    claimed = await repo.claim_next_queued(exclude_sites={"site_01"})

    assert claimed is not None
    assert claimed.id == second.id
    assert claimed.site_key == "site_02"
    assert claimed.status == JobStatus.RUNNING


@pytest.mark.asyncio
async def test_memory_repo_claim_returns_none_when_all_sites_excluded() -> None:
    repo = MemoryRepository()
    await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))

    assert await repo.claim_next_queued(exclude_sites={"site_01"}) is None


class _BlockingAdapter:
    def __init__(self, site_key: str, release: asyncio.Event) -> None:
        self.spec = SiteSpec(
            key=site_key,
            display_name=site_key,
            base_url="http://localhost:8080/mock",
        )
        self._release = release

    def workflow(self, ctx: object) -> list[Any]:
        release = self._release

        async def _block(_ctx: object) -> None:
            await release.wait()

        return [_block]


@pytest.mark.asyncio
async def test_runner_respects_max_site_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = MemoryRepository()
    release = asyncio.Event()

    def fake_adapter_for(site_key: str, spec: object | None = None) -> _BlockingAdapter:
        return _BlockingAdapter(site_key, release)

    monkeypatch.setattr(runner_module, "adapter_for", fake_adapter_for)

    runner = JobRunner(
        repository=repo,
        settings=Settings(max_global_concurrency=4, max_site_concurrency=1),
    )

    first = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a", profile_id="p1"))
    second = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-b", profile_id="p2"))

    await runner.start()
    try:
        await asyncio.sleep(0.2)

        first_job = await repo.get_job(first.id)
        second_job = await repo.get_job(second.id)
        assert first_job is not None and second_job is not None
        running = {first_job.status, second_job.status}
        # Only one site_01 job may run at a time; the other stays queued.
        assert running == {JobStatus.RUNNING, JobStatus.QUEUED}

        release.set()
        await asyncio.sleep(1.5)

        first_done = await repo.get_job(first.id)
        second_done = await repo.get_job(second.id)
        assert first_done is not None and second_done is not None
        assert first_done.status == JobStatus.SUCCEEDED
        assert second_done.status == JobStatus.SUCCEEDED
    finally:
        await runner.stop()


@pytest.mark.asyncio
async def test_runner_runs_workflow_to_success() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(
        JobCreate(site_key="example", sim_id="sim-a", profile_id="p1")
    )

    runner = JobRunner(repository=repo, settings=Settings(max_global_concurrency=1))
    await runner.start()
    try:
        await asyncio.sleep(0.5)
        job = await repo.get_job(created.id)
        if job is not None and job.status == JobStatus.RUNNING:
            await asyncio.sleep(1.0)
    finally:
        await runner.stop()

    job = await repo.get_job(created.id)
    assert job is not None
    assert job.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_runner_resume_is_noop_when_nothing_waits() -> None:
    repo = MemoryRepository()
    runner = JobRunner(repository=repo, settings=Settings(max_global_concurrency=1))

    runner.resume("nope")
    assert runner.checkpoints.current("nope") is None
