from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from account_automation_lab.browser.runtime import BrowserProfileConfig, runtime_for
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserSession,
    BrowserSessionStatus,
    utc_now,
)
from account_automation_lab.profiles import ProfileLockHandle, ProfileLockRegistry
from account_automation_lab.proxy import ProfileProxyManager
from account_automation_lab.settings import Settings


class BrowserRuntime(Protocol):
    async def launch_context(self, config: BrowserProfileConfig) -> Any: ...


class BrowserProfileExistsError(RuntimeError):
    pass


class BrowserSessionError(RuntimeError):
    pass


class BrowserProfileStore:
    def __init__(self, *, storage_root: Path, site_keys: tuple[str, ...]) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self._profiles: dict[str, BrowserProfile] = {}
        for site_key in site_keys:
            profile_id = f"sim-a:{site_key}"
            self._profiles[profile_id] = self._build_profile(
                BrowserProfileCreate(
                    id=profile_id,
                    name=f"SIM A / {site_key}",
                    sim_id="sim-a",
                    site_key=site_key,
                )
            )

    async def list_profiles(self) -> list[BrowserProfile]:
        return sorted(self._profiles.values(), key=lambda profile: profile.id)

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return self._profiles.get(profile_id)

    async def create_profile(self, payload: BrowserProfileCreate) -> BrowserProfile:
        profile = self._build_profile(payload)
        if profile.id in self._profiles:
            raise BrowserProfileExistsError(f"Browser profile {profile.id} already exists")
        self._profiles[profile.id] = profile
        return profile

    def _build_profile(self, payload: BrowserProfileCreate) -> BrowserProfile:
        profile_id = payload.id or f"{payload.sim_id}:{payload.site_key}"
        storage_dir = self._storage_dir_for(profile_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        return BrowserProfile(
            id=profile_id,
            name=payload.name or f"{payload.sim_id} / {payload.site_key}",
            sim_id=payload.sim_id,
            site_key=payload.site_key,
            runtime=payload.runtime,
            storage_dir=str(storage_dir),
            tags=payload.tags,
            notes=payload.notes,
        )

    def _storage_dir_for(self, profile_id: str) -> Path:
        base_name = _path_safe_profile_id(profile_id)
        storage_dir = self.storage_root / base_name
        if not self._storage_dir_is_used_by_other_profile(storage_dir, profile_id):
            return storage_dir
        suffix = sha256(profile_id.encode("utf-8")).hexdigest()[:12]
        return self.storage_root / f"{base_name}-{suffix}"

    def _storage_dir_is_used_by_other_profile(self, storage_dir: Path, profile_id: str) -> bool:
        return any(
            Path(profile.storage_dir) == storage_dir and profile.id != profile_id
            for profile in self._profiles.values()
        )


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
