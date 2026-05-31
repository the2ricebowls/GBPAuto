from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

from account_automation_lab.models import JobStatus
from account_automation_lab.workflows.context import WorkflowContext

Step = Callable[[WorkflowContext], Coroutine[Any, Any, None]]


def goto(url: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.goto(url)
        await ctx.repo.add_event(ctx.job_id, "step.goto", url)

    return _step


def fill(selector: str, value: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.fill(selector, value)
        await ctx.repo.add_event(ctx.job_id, "step.fill", selector)

    return _step


def click(selector: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.click(selector)
        await ctx.repo.add_event(ctx.job_id, "step.click", selector)

    return _step


def emit(event_type: str, message: str, payload: dict[str, Any] | None = None) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.repo.add_event(ctx.job_id, event_type, message, payload)

    return _step


def wait_for_human(kind: str, message: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.repo.update_job_status(
            ctx.job_id,
            JobStatus.WAITING_HUMAN,
            event_type="job.waiting_human",
            message=message,
        )
        await ctx.checkpoints.wait(ctx.job_id, kind, message)
        await ctx.repo.update_job_status(
            ctx.job_id,
            JobStatus.RUNNING,
            event_type="job.resumed",
            message="Resumed by operator",
        )

    return _step
