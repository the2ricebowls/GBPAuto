from __future__ import annotations

import asyncio
import re
import shutil
import uuid as _uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from account_automation_lab.browser.runtime import BrowserProfileConfig, runtime_for
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserSession,
    BrowserSessionStatus,
    utc_now,
)
from account_automation_lab.profiles import ProfileLockHandle, ProfileLockRegistry
from account_automation_lab.proxy import ProfileProxyManager
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


class BrowserRuntime(Protocol):
    async def launch_context(self, config: BrowserProfileConfig) -> Any: ...


class BrowserProfileExistsError(RuntimeError):
    pass


class BrowserSessionError(RuntimeError):
    pass


class BrowserProfileStore:
    def __init__(
        self,
        *,
        storage_root: Path,
        repository: AutomationRepository | None = None,
        site_keys: tuple[str, ...] = (),
    ) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.repository: AutomationRepository = repository or MemoryRepository()
        for site_key in site_keys:
            self._seed_default(site_key)

    def _seed_default(self, site_key: str) -> None:
        profile_id = f"sim-a:{site_key}"
        storage_dir = self._ensure_storage_dir(profile_id)
        profile = BrowserProfile(
            id=profile_id,
            name=f"SIM A / {site_key}",
            sim_id="sim-a",
            site_key=site_key,
            storage_dir=str(storage_dir),
        )
        if isinstance(self.repository, MemoryRepository):
            self.repository._profiles[profile_id] = profile  # noqa: SLF001

    async def list_profiles(self) -> list[BrowserProfile]:
        return await self.repository.list_profiles()

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return await self.repository.get_profile(profile_id)

    async def create_profile(self, payload: BrowserProfileCreate) -> BrowserProfile:
        profile_id = payload.id or str(_uuid.uuid4())
        if await self.repository.get_profile(profile_id) is not None:
            raise BrowserProfileExistsError(f"Browser profile {profile_id} already exists")
        storage_dir = self._ensure_storage_dir(profile_id)
        profile = BrowserProfile(
            id=profile_id,
            name=payload.name,
            group_id=payload.group_id,
            tags=payload.tags,
            notes=payload.notes,
            sim_id=payload.sim_id,
            site_key=payload.site_key,
            runtime=payload.runtime,
            storage_dir=str(storage_dir),
            startup_url=payload.startup_url,
            fingerprint=payload.fingerprint,
        )
        return await self.repository.create_profile(profile)

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        return await self.repository.update_profile(profile_id, update)

    async def clone_profile(self, profile_id: str) -> BrowserProfile:
        source = await self.repository.get_profile(profile_id)
        if source is None:
            raise KeyError(profile_id)
        new_id = str(_uuid.uuid4())
        storage_dir = self._ensure_storage_dir(new_id)
        cloned_fp = source.fingerprint.model_copy(update={"seed": None})
        profile = BrowserProfile(
            id=new_id,
            name=f"{source.name} (copy)",
            group_id=source.group_id,
            tags=list(source.tags),
            notes=source.notes,
            sim_id=source.sim_id,
            site_key=source.site_key,
            runtime=source.runtime,
            storage_dir=str(storage_dir),
            startup_url=source.startup_url,
            fingerprint=cloned_fp,
        )
        return await self.repository.create_profile(profile)

    async def delete_profile(self, profile_id: str, *, remove_storage: bool = False) -> None:
        profile = await self.repository.get_profile(profile_id)
        await self.repository.delete_profile(profile_id)
        if remove_storage and profile is not None:
            shutil.rmtree(Path(profile.storage_dir), ignore_errors=True)

    def _ensure_storage_dir(self, profile_id: str) -> Path:
        storage_dir = self.storage_root / _path_safe_profile_id(profile_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir


@dataclass
class ActiveBrowserSession:
    session: BrowserSession
    context: Any
    lock: ProfileLockHandle


class BrowserSessionManager:
    def __init__(
        self,
        *,
        store: BrowserProfileStore,
        settings: Settings,
        proxy_manager: ProfileProxyManager,
        runtime_factory: Any = runtime_for,
    ) -> None:
        self.store = store
        self.settings = settings
        self.proxy_manager = proxy_manager
        self.runtime_factory = runtime_factory
        self._active: dict[str, ActiveBrowserSession] = {}
        self._opening: dict[str, asyncio.Task[BrowserSession]] = {}
        self._open_guard = asyncio.Lock()
        self._locks = ProfileLockRegistry()

    async def list_sessions(self) -> list[BrowserSession]:
        return sorted(
            (active.session for active in self._active.values()),
            key=lambda session: session.started_at,
            reverse=True,
        )

    async def get_session(self, profile_id: str) -> BrowserSession | None:
        active = self._active.get(profile_id)
        return active.session if active is not None else None

    async def open_profile(self, profile_id: str, start_url: str | None = None) -> BrowserSession:
        async with self._open_guard:
            existing = await self.get_session(profile_id)
            if existing is not None:
                return existing
            opening = self._opening.get(profile_id)
            if opening is None:
                profile = await self.store.get_profile(profile_id)
                if profile is None:
                    raise KeyError(profile_id)
                opening = asyncio.create_task(self._launch_profile(profile, start_url))
                self._opening[profile_id] = opening
                opening.add_done_callback(self._opening_cleanup_callback(profile_id))
        return await asyncio.shield(opening)

    async def _launch_profile(
        self,
        profile: BrowserProfile,
        start_url: str | None,
    ) -> BrowserSession:
        lock = await self._locks.try_acquire(profile.id)
        if lock is None:
            raise BrowserSessionError(f"Browser profile {profile.id} is already opening")
        try:
            assignment = await self.proxy_manager.get(profile.id)
            config = BrowserProfileConfig(
                profile_id=profile.id,
                storage_dir=Path(profile.storage_dir),
                proxy=assignment.proxy.playwright_proxy if assignment is not None else None,
            )
            runtime: BrowserRuntime = self.runtime_factory(profile.runtime, self.settings)
            context = await runtime.launch_context(config)
            session = BrowserSession(
                profile_id=profile.id,
                runtime=profile.runtime,
                status=BrowserSessionStatus.RUNNING,
                started_at=utc_now(),
                start_url=start_url,
            )
            self._active[profile.id] = ActiveBrowserSession(
                session=session,
                context=context,
                lock=lock,
            )
            return session
        except Exception:
            await lock.release()
            raise

    def _remove_opening_task(
        self,
        profile_id: str,
        task: asyncio.Task[BrowserSession],
    ) -> None:
        if self._opening.get(profile_id) is task:
            self._opening.pop(profile_id, None)

    def _opening_cleanup_callback(
        self,
        profile_id: str,
    ) -> Callable[[asyncio.Task[BrowserSession]], None]:
        def cleanup(task: asyncio.Task[BrowserSession]) -> None:
            self._remove_opening_task(profile_id, task)

        return cleanup

    async def close_profile(self, profile_id: str) -> BrowserSession:
        active = self._active.pop(profile_id, None)
        if active is None:
            raise KeyError(profile_id)
        close = getattr(active.context, "close", None)
        if close is not None:
            try:
                await close()
            finally:
                await active.lock.release()
        else:
            await active.lock.release()
        return active.session

    async def close_all(self) -> None:
        for profile_id in list(self._active):
            await self.close_profile(profile_id)


def _path_safe_profile_id(profile_id: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "_", profile_id).strip("_") or "profile"
