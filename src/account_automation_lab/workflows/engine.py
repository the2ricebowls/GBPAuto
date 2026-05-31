from __future__ import annotations

from collections.abc import Sequence

from account_automation_lab.models import JobStatus
from account_automation_lab.workflows.checkpoints import CheckpointCancelled
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import Step


class WorkflowEngine:
    def __init__(self, *, fail_fast: bool = False) -> None:
        self.fail_fast = fail_fast

    async def run(self, ctx: WorkflowContext, steps: Sequence[Step]) -> None:
        try:
            for step in steps:
                await step(ctx)
        except CheckpointCancelled:
            await self._safe_status(ctx, JobStatus.CANCELLED, "job.cancelled", "Cancelled")
            return
        except Exception as exc:
            await ctx.repo.add_event(ctx.job_id, "job.error", str(exc))
            target = JobStatus.FAILED if self.fail_fast else JobStatus.WAITING_HUMAN
            message = "Failed" if self.fail_fast else f"Paused after error: {exc}"
            await self._safe_status(ctx, target, "job.error_paused", message)
            return
        await self._safe_status(ctx, JobStatus.SUCCEEDED, "job.succeeded", "Workflow completed")

    async def _safe_status(
        self, ctx: WorkflowContext, status: JobStatus, event_type: str, message: str
    ) -> None:
        from account_automation_lab.repositories.memory import InvalidJobTransitionError

        try:
            await ctx.repo.update_job_status(
                ctx.job_id, status, event_type=event_type, message=message
            )
        except InvalidJobTransitionError:
            await ctx.repo.add_event(
                ctx.job_id,
                "job.status_conflict",
                f"Skipped transition to {status.value}; job already terminal.",
            )
