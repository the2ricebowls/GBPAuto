from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class ProfileLockHandle:
    profile_id: str
    _lock: asyncio.Lock

    async def release(self) -> None:
        if self._lock.locked():
            self._lock.release()


class ProfileLockRegistry:
    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    async def try_acquire(self, profile_id: str) -> ProfileLockHandle | None:
        async with self._guard:
            lock = self._locks.setdefault(profile_id, asyncio.Lock())
            if lock.locked():
                return None
            await lock.acquire()
            return ProfileLockHandle(profile_id=profile_id, _lock=lock)
