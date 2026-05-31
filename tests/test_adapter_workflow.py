from __future__ import annotations

import pytest

from account_automation_lab.adapters.registry import adapter_for
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext


class FakePage:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def goto(self, url: str) -> None:
        self.actions.append("goto")

    async def fill(self, selector: str, value: str) -> None:
        self.actions.append("fill")

    async def click(self, selector: str) -> None:
        self.actions.append("click")


@pytest.mark.asyncio
async def test_mock_adapter_workflow_returns_runnable_steps() -> None:
    adapter = adapter_for("example")
    repo = MemoryRepository()
    ctx = WorkflowContext(
        job_id="job1",
        profile_id="p1",
        page=FakePage(),
        repo=repo,
        checkpoints=CheckpointRegistry(),
    )

    steps = adapter.workflow(ctx)
    for step in steps:
        await step(ctx)

    assert ctx.page.actions[:3] == ["goto", "fill", "click"]
