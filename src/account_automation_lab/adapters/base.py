from __future__ import annotations

from typing import Protocol

from account_automation_lab.models import (
    JobStatus,
    RegistrationContext,
    RegistrationResult,
    SiteSpec,
)
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import Step, click, emit, fill, goto


class SiteAdapter(Protocol):
    spec: SiteSpec

    async def run(self, context: RegistrationContext) -> RegistrationResult: ...

    def workflow(self, ctx: WorkflowContext) -> list[Step]: ...


class MockRegistrationAdapter:
    def __init__(self, spec: SiteSpec) -> None:
        self.spec = spec

    async def run(self, context: RegistrationContext) -> RegistrationResult:
        identifier = f"{context.job.sim_id}@{self.spec.key}.test"
        return RegistrationResult(
            status=JobStatus.SUCCEEDED,
            account_identifier=identifier,
            message=f"Mock registration completed for {self.spec.key}",
        )

    def workflow(self, ctx: WorkflowContext) -> list[Step]:
        return [
            goto(self.spec.base_url),
            fill("#username", f"{ctx.profile_id}@{self.spec.key}.test"),
            click("#submit"),
            emit("adapter.mock", f"Mock registration completed for {self.spec.key}"),
        ]


def make_mock_adapter(site_number: int) -> MockRegistrationAdapter:
    key = f"site_{site_number:02d}"
    spec = SiteSpec(
        key=key,
        display_name=f"Mock Site {site_number:02d}",
        base_url=f"http://localhost:8080/mock/{key}",
        otp_sender_hints=(f"SITE{site_number:02d}",),
    )
    return MockRegistrationAdapter(spec)
