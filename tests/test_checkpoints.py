from __future__ import annotations

import asyncio

import pytest

from account_automation_lab.workflows.checkpoints import (
    CheckpointCancelled,
    CheckpointRegistry,
)


@pytest.mark.asyncio
async def test_resume_unblocks_waiter() -> None:
    registry = CheckpointRegistry()

    async def waiter() -> str:
        await registry.wait("job1", "captcha", "Solve the captcha")
        return "resumed"

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    current = registry.current("job1")
    assert current is not None
    assert current.message == "Solve the captcha"

    registry.resume("job1")
    assert await task == "resumed"
    assert registry.current("job1") is None


@pytest.mark.asyncio
async def test_cancel_raises_in_waiter() -> None:
    registry = CheckpointRegistry()

    async def waiter() -> None:
        await registry.wait("job1", "manual", "Do thing")

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    registry.cancel("job1")

    with pytest.raises(CheckpointCancelled):
        await task


@pytest.mark.asyncio
async def test_resume_without_waiter_is_noop() -> None:
    registry = CheckpointRegistry()
    registry.resume("nope")  # must not raise
    assert registry.current("nope") is None
