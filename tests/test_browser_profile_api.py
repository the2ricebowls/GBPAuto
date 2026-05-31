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
    assert created.json()["id"]
    assert created.json()["name"] == "SIM B / site_02"
    assert created.json()["sim_id"] == "sim-b"
    assert created.json()["site_key"] == "site_02"
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


def test_profile_crud_lifecycle() -> None:
    repo = MemoryRepository()
    app = create_app(settings=Settings(), repository=repo, start_runner=False)
    client = TestClient(app)

    created = client.post(
        "/api/browser-profiles",
        json={"name": "My FB", "tags": ["fb"], "fingerprint": {"platform": "windows"}},
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    listed = client.get("/api/browser-profiles").json()
    assert any(p["id"] == pid for p in listed)

    patched = client.patch(f"/api/browser-profiles/{pid}", json={"name": "Renamed"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    cloned = client.post(f"/api/browser-profiles/{pid}/clone")
    assert cloned.status_code == 201
    assert cloned.json()["id"] != pid

    deleted = client.delete(f"/api/browser-profiles/{pid}")
    assert deleted.status_code == 200
    remaining = client.get("/api/browser-profiles").json()
    assert all(p["id"] != pid for p in remaining)


def test_group_crud() -> None:
    app = create_app(settings=Settings(), repository=MemoryRepository(), start_runner=False)
    client = TestClient(app)

    created = client.post("/api/profile-groups", json={"name": "FB"})
    assert created.status_code == 201
    gid = created.json()["id"]

    assert any(g["id"] == gid for g in client.get("/api/profile-groups").json())

    client.patch(f"/api/profile-groups/{gid}", json={"name": "Facebook"})
    client.delete(f"/api/profile-groups/{gid}")
    assert all(g["id"] != gid for g in client.get("/api/profile-groups").json())
