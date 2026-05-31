from __future__ import annotations

import asyncio
from typing import Any

import pytest

from account_automation_lab.models import JobCreate, JobStatus
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import (
    click,
    emit,
    fill,
    goto,
    wait_for_human,
)


class FakePage:
    def __init__(self) -> None:
        self.actions: list[tuple[str, Any]] = []

    async def goto(self, url: str) -> None:
        self.actions.append(("goto", url))

    async def fill(self, selector: str, value: str) -> None:
        self.actions.append(("fill", (selector, value)))

    async def click(self, selector: str) -> None:
        self.actions.append(("click", selector))


def _ctx(page: FakePage, repo: MemoryRepository, job_id: str) -> WorkflowContext:
    return WorkflowContext(
        job_id=job_id,
        profile_id="p1",
        page=page,
        repo=repo,
        checkpoints=CheckpointRegistry(),
    )


def _make_job_create() -> JobCreate:
    return JobCreate(site_key="site_01", sim_id="sim-a")


@pytest.mark.asyncio
async def test_goto_fill_click_drive_the_page() -> None:
    page = FakePage()
    repo = MemoryRepository()
    ctx = _ctx(page, repo, "job1")

    await goto("https://localhost/x")(ctx)
    await fill("#email", "a@b.c")(ctx)
    await click("#submit")(ctx)

    assert page.actions == [
        ("goto", "https://localhost/x"),
        ("fill", ("#email", "a@b.c")),
        ("click", "#submit"),
    ]


@pytest.mark.asyncio
async def test_emit_records_a_job_event() -> None:
    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())
    ctx = _ctx(page, repo, created.id)

    await emit("note", "hello", {"k": "v"})(ctx)

    events = await repo.get_job_events(created.id)
    assert any(e.event_type == "note" and e.message == "hello" for e in events)


@pytest.mark.asyncio
async def test_wait_for_human_sets_waiting_state_then_resumes() -> None:
    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())
    await repo.update_job_status(created.id, JobStatus.RUNNING)
    checkpoints = CheckpointRegistry()
    ctx = WorkflowContext(
        job_id=created.id, profile_id="p1", page=page, repo=repo, checkpoints=checkpoints
    )

    task = asyncio.create_task(wait_for_human("manual", "Please confirm")(ctx))
    await asyncio.sleep(0.01)

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.WAITING_HUMAN
    assert checkpoints.current(created.id) is not None

    checkpoints.resume(created.id)
    await task
    job2 = await repo.get_job(created.id)
    assert job2 is not None and job2.status == JobStatus.RUNNING
