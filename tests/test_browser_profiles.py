from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from account_automation_lab.browser.profiles import (
    BrowserProfileStore,
    BrowserSessionManager,
)
from account_automation_lab.models import BrowserProfileCreate, ProxyPolicy, RuntimeKind
from account_automation_lab.proxy import ProfileProxyManager, ProxyVNLease
from account_automation_lab.settings import Settings


class FakeContext:
    def __init__(self, *, close_error: Exception | None = None) -> None:
        self.is_closed = False
        self.pages: list[Any] = []
        self.close_error = close_error

    async def close(self) -> None:
        self.is_closed = True
        if self.close_error is not None:
            raise self.close_error


class FakeRuntime:
    def __init__(self, *, close_error: Exception | None = None, launch_delay: float = 0) -> None:
        self.launches: list[Any] = []
        self.contexts: list[FakeContext] = []
        self.close_error = close_error
        self.launch_delay = launch_delay

    async def launch_context(self, config: Any) -> FakeContext:
        if self.launch_delay:
            await asyncio.sleep(self.launch_delay)
        context = FakeContext(close_error=self.close_error)
        self.launches.append(config)
        self.contexts.append(context)
        return context


@pytest.mark.asyncio
async def test_browser_profile_store_creates_default_path_safe_profiles(tmp_path: Path) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=("site_01", "site_02"))

    profiles = await store.list_profiles()

    assert [profile.id for profile in profiles] == ["sim-a:site_01", "sim-a:site_02"]
    assert profiles[0].name == "SIM A / site_01"
    assert Path(profiles[0].storage_dir).name == "sim-a_site_01"
    assert ":" not in Path(profiles[0].storage_dir).name


@pytest.mark.asyncio
async def test_browser_profile_store_creates_custom_profile(tmp_path: Path) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=())

    profile = await store.create_profile(
        BrowserProfileCreate(
            name="SIM B internal site",
            sim_id="sim-b",
            site_key="site_03",
            tags=["qa", "otp"],
        )
    )

    assert profile.id == "sim-b:site_03"
    assert profile.name == "SIM B internal site"
    assert profile.runtime == RuntimeKind.CLOAKBROWSER
    assert profile.tags == ["qa", "otp"]


@pytest.mark.asyncio
async def test_browser_profile_store_uses_distinct_path_safe_dirs_for_sanitized_collisions(
    tmp_path: Path,
) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=())

    colon_profile = await store.create_profile(
        BrowserProfileCreate(id="a:b", name="Colon", sim_id="a", site_key="b")
    )
    slash_profile = await store.create_profile(
        BrowserProfileCreate(id="a/b", name="Slash", sim_id="a", site_key="b")
    )

    colon_dir = Path(colon_profile.storage_dir)
    slash_dir = Path(slash_profile.storage_dir)
    assert colon_dir != slash_dir
    assert colon_dir.parent == tmp_path
    assert slash_dir.parent == tmp_path
    assert ":" not in colon_dir.name
    assert "/" not in slash_dir.name


@pytest.mark.asyncio
async def test_browser_session_manager_opens_reuses_and_closes_profile(
    tmp_path: Path,
) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=("site_01",))
    proxy_manager = ProfileProxyManager()
    await proxy_manager.assign(
        "sim-a:site_01",
        ProxyVNLease(
            idproxy=308,
            loaiproxy="4Gvinaphone",
            ip="160.250.166.88",
            port=20308,
            user="secret-user",
            password="secret-pass",
            type="HTTPS",
            expires_at=1779906500,
        ),
        ProxyPolicy.STICKY_PROFILE,
    )
    fake_runtime = FakeRuntime()
    manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=proxy_manager,
        runtime_factory=lambda _kind, _settings: fake_runtime,
    )

    first = await manager.open_profile("sim-a:site_01")
    second = await manager.open_profile("sim-a:site_01")
    sessions = await manager.list_sessions()
    closed = await manager.close_profile("sim-a:site_01")

    assert first.profile_id == "sim-a:site_01"
    assert second == first
    assert len(fake_runtime.launches) == 1
    assert fake_runtime.launches[0].profile_id == "sim-a:site_01"
    assert fake_runtime.launches[0].proxy == {
        "server": "http://160.250.166.88:20308",
        "username": "secret-user",
        "password": "secret-pass",
    }
    assert sessions == [first]
    assert closed.profile_id == "sim-a:site_01"
    assert fake_runtime.contexts[0].is_closed is True
    assert await manager.list_sessions() == []


@pytest.mark.asyncio
async def test_browser_session_manager_releases_lock_and_active_session_when_close_raises(
    tmp_path: Path,
) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=("site_01",))
    fake_runtime = FakeRuntime(close_error=RuntimeError("close failed"))
    manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=ProfileProxyManager(),
        runtime_factory=lambda _kind, _settings: fake_runtime,
    )

    await manager.open_profile("sim-a:site_01")

    with pytest.raises(RuntimeError, match="close failed"):
        await manager.close_profile("sim-a:site_01")

    assert await manager.list_sessions() == []
    reopened = await manager.open_profile("sim-a:site_01")
    assert reopened.profile_id == "sim-a:site_01"
    assert len(fake_runtime.launches) == 2


@pytest.mark.asyncio
async def test_browser_session_manager_concurrent_duplicate_opens_reuse_one_launch(
    tmp_path: Path,
) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=("site_01",))
    fake_runtime = FakeRuntime(launch_delay=0.01)
    manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=ProfileProxyManager(),
        runtime_factory=lambda _kind, _settings: fake_runtime,
    )

    first, second = await asyncio.gather(
        manager.open_profile("sim-a:site_01"),
        manager.open_profile("sim-a:site_01"),
    )

    assert first == second
    assert len(fake_runtime.launches) == 1


@pytest.mark.asyncio
async def test_browser_session_manager_rejects_unknown_profile(tmp_path: Path) -> None:
    manager = BrowserSessionManager(
        store=BrowserProfileStore(storage_root=tmp_path, site_keys=()),
        settings=Settings(),
        proxy_manager=ProfileProxyManager(),
        runtime_factory=lambda _kind, _settings: FakeRuntime(),
    )

    with pytest.raises(KeyError):
        await manager.open_profile("missing-profile")
