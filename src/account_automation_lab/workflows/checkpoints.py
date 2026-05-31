from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


class CheckpointCancelled(RuntimeError):
    """Raised inside a waiting step when the operator cancels the checkpoint."""


@dataclass
class Checkpoint:
    job_id: str
    kind: str
    message: str
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _cancelled: bool = False


class CheckpointRegistry:
    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def current(self, job_id: str) -> Checkpoint | None:
        return self._checkpoints.get(job_id)

    async def wait(self, job_id: str, kind: str, message: str) -> None:
        checkpoint = Checkpoint(job_id=job_id, kind=kind, message=message)
        self._checkpoints[job_id] = checkpoint
        try:
            await checkpoint._event.wait()  # noqa: SLF001
            if checkpoint._cancelled:  # noqa: SLF001
                raise CheckpointCancelled(job_id)
        finally:
            if self._checkpoints.get(job_id) is checkpoint:
                del self._checkpoints[job_id]

    def resume(self, job_id: str) -> None:
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint._event.set()  # noqa: SLF001

    def cancel(self, job_id: str) -> None:
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint._cancelled = True  # noqa: SLF001
            checkpoint._event.set()  # noqa: SLF001
