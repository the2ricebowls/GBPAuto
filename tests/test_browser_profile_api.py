from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from account_automation_lab.api import create_app
from account_automation_lab.browser.profiles import BrowserProfileStore, BrowserSessionManager
from account_automation_lab.proxy import ProfileProxyManager
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


class FakeContext:
    async def close(self) -> None:
        return None


class FakeRuntime:
    def __init__(self) -> None:
        self.launch_count = 0

    async def launch_context(self, config: Any) -> FakeContext:
        self.launch_count += 1
        return FakeContext()


def test_browser_profile_api_lists_creates_opens_and_closes_profiles(tmp_path: Path) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=("site_01",))
    proxy_manager = ProfileProxyManager()
    fake_runtime = FakeRuntime()
    session_manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=proxy_manager,
        runtime_factory=lambda _kind, _settings: fake_runtime,
    )
    app = create_app(
        settings=Settings(database_backend="memory"),
        repository=MemoryRepository(),
        start_runner=False,
        proxy_manager=proxy_manager,
        browser_profile_store=store,
        browser_session_manager=session_manager,
    )
    client = TestClient(app)

    listed = client.get("/api/browser-profiles")
    created = client.post(
        "/api/browser-profiles",
        json={"sim_id": "sim-b", "site_key": "site_02", "name": "SIM B / site_02"},
    )
    opened = client.post("/api/browser-profiles/sim-a:site_01/open")
    opened_again = client.post("/api/browser-profiles/sim-a:site_01/open")
    sessions = client.get("/api/browser-sessions")
    closed = client.post("/api/browser-profiles/sim-a:site_01/close")

    assert listed.status_code == 200
    assert listed.json()[0]["id"] == "sim-a:site_01"
    assert listed.json()[0]["session_status"] == "idle"
    assert created.status_code == 201
    assert created.json()["id"] == "sim-b:site_02"
    assert opened.status_code == 200
    assert opened.json()["profile_id"] == "sim-a:site_01"
    assert opened.json()["status"] == "running"
    assert opened_again.status_code == 200
    assert fake_runtime.launch_count == 1
    assert sessions.json()[0]["profile_id"] == "sim-a:site_01"
    assert closed.status_code == 200
    assert closed.json() == {"closed": True, "profile_id": "sim-a:site_01"}
    assert client.get("/api/browser-sessions").json() == []


def test_browser_profile_api_returns_404_for_unknown_profile(tmp_path: Path) -> None:
    store = BrowserProfileStore(storage_root=tmp_path, site_keys=())
    session_manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=ProfileProxyManager(),
        runtime_factory=lambda _kind, _settings: FakeRuntime(),
    )
    app = create_app(
        settings=Settings(database_backend="memory"),
        repository=MemoryRepository(),
        start_runner=False,
        browser_profile_store=store,
        browser_session_manager=session_manager,
    )
    client = TestClient(app)

    response = client.post("/api/browser-profiles/missing/open")

    assert response.status_code == 404
    assert response.json()["detail"] == "Browser profile not found"
