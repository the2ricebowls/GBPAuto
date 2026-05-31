from __future__ import annotations

import asyncio

import pytest

from account_automation_lab.models import JobCreate, JobStatus
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.engine import WorkflowEngine


def _ctx(repo: MemoryRepository, job_id: str, checkpoints: CheckpointRegistry) -> WorkflowContext:
    return WorkflowContext(
        job_id=job_id, profile_id="p1", page=object(), repo=repo, checkpoints=checkpoints
    )


@pytest.mark.asyncio
async def test_engine_runs_all_steps_then_succeeds() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)
    calls: list[str] = []

    async def step_a(ctx: WorkflowContext) -> None:
        calls.append("a")

    async def step_b(ctx: WorkflowContext) -> None:
        calls.append("b")

    engine = WorkflowEngine()
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [step_a, step_b])

    assert calls == ["a", "b"]
    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_engine_error_goes_to_waiting_human_by_default() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)

    async def boom(ctx: WorkflowContext) -> None:
        raise ValueError("kaboom")

    engine = WorkflowEngine()
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [boom])

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.WAITING_HUMAN
    events = await repo.get_job_events(created.id)
    assert any(e.event_type == "job.error" and "kaboom" in e.message for e in events)


@pytest.mark.asyncio
async def test_engine_error_fail_fast_goes_to_failed() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)

    async def boom(ctx: WorkflowContext) -> None:
        raise ValueError("kaboom")

    engine = WorkflowEngine(fail_fast=True)
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [boom])

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.FAILED


@pytest.mark.asyncio
async def test_engine_checkpoint_cancel_goes_to_cancelled() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)
    checkpoints = CheckpointRegistry()

    async def pause(ctx: WorkflowContext) -> None:
        await ctx.checkpoints.wait(ctx.job_id, "manual", "hold")

    engine = WorkflowEngine()
    ctx = _ctx(repo, created.id, checkpoints)
    task = asyncio.create_task(engine.run(ctx, [pause]))
    await asyncio.sleep(0.01)
    checkpoints.cancel(created.id)
    await task

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.CANCELLED
