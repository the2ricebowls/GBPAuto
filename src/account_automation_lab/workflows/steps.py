from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from account_automation_lab.models import JobStatus, OtpRequest, utc_now
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


def wait_for(seconds: float) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await asyncio.sleep(seconds)

    return _step


def get_otp(
    sim_id: str,
    site_key: str,
    sender_hints: tuple[str, ...] = (),
    timeout_seconds: float = 120.0,
    store_as: str = "otp",
) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        if ctx.otp_provider is None:
            raise RuntimeError("No OTP provider configured for this workflow")
        request = OtpRequest(
            sim_id=sim_id,
            site_key=site_key,
            sender_hints=sender_hints,
            requested_after=utc_now(),
            timeout_seconds=timeout_seconds,
        )
        otp = await ctx.otp_provider.wait_for_otp(request)
        ctx.data[store_as] = otp
        await ctx.repo.add_event(
            ctx.job_id, "step.get_otp", "OTP received" if otp else "OTP timeout"
        )

    return _step


def read_from(
    profile_id: str,
    reader: Callable[[Any], Awaitable[Any]],
    store_as: str = "read",
) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        if ctx.session_manager is None:
            raise RuntimeError("No session manager configured for this workflow")
        other_page = await ctx.session_manager.get_page(profile_id)
        value = await reader(other_page)
        ctx.data[store_as] = value
        await ctx.repo.add_event(ctx.job_id, "step.read_from", f"Read from {profile_id}")

    return _step
