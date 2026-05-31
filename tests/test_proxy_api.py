from __future__ import annotations

from fastapi.testclient import TestClient

from account_automation_lab.api import create_app
from account_automation_lab.models import ProxyPolicy
from account_automation_lab.proxy import ProfileProxyManager, ProxyVNLease, parse_proxyvn_items
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


class FakeProxyVNClient:
    def __init__(self) -> None:
        self.purchase_count = 0
        self.change_count = 0

    async def purchase_one_day_proxy(self) -> ProxyVNLease:
        self.purchase_count += 1
        return parse_proxyvn_items(
            {
                "status": 100,
                "loaiproxy": "4Gvinaphone",
                "idproxy": 308,
                "ip": "160.250.166.88",
                "port": 20308,
                "user": "secret-user",
                "password": "secret-pass",
                "type": "HTTPS",
                "proxy": "160.250.166.88:20308:secret-user:secret-pass",
                "time": 1779906500,
            }
        )[0]

    async def list_proxy(self, idproxy: str) -> list[ProxyVNLease]:
        return [
            parse_proxyvn_items(
                {
                    "status": 100,
                    "loaiproxy": "4Gvinaphone",
                    "idproxy": int(idproxy),
                    "ip": "160.250.166.88",
                    "port": 20308,
                    "user": "secret-user",
                    "password": "secret-pass",
                    "type": "HTTPS",
                    "proxy": "160.250.166.88:20308:secret-user:secret-pass",
                    "time": 1779906500,
                }
            )[0]
        ]

    async def change_proxy(self, idproxy: int) -> ProxyVNLease:
        self.change_count += 1
        return parse_proxyvn_items(
            {
                "status": 100,
                "loaiproxy": "4Gvinaphone",
                "idproxy": idproxy,
                "ip": "160.250.166.89",
                "port": 20309,
                "user": "new-user",
                "password": "new-pass",
                "type": "HTTPS",
                "proxy": "160.250.166.89:20309:new-user:new-pass",
                "time": 1779906500,
            }
        )[0]


def test_profile_proxy_ensure_assigns_one_masked_proxy_per_profile() -> None:
    manager = ProfileProxyManager()
    proxy_client = FakeProxyVNClient()
    app = create_app(
        settings=Settings(database_backend="memory", proxyvn_api_key="test-key"),
        repository=MemoryRepository(),
        start_runner=False,
        proxy_manager=manager,
        proxyvn_client=proxy_client,
    )
    client = TestClient(app)

    first = client.post("/api/profiles/sim-a:site_01/proxy/ensure")
    second = client.post("/api/profiles/sim-a:site_01/proxy/ensure")
    listed = client.get("/api/proxies")

    assert first.status_code == 200
    assert second.status_code == 200
    assert proxy_client.purchase_count == 1
    assert first.json()["proxy"]["masked_proxy"] == "160.250.166.88:20308:***:***"
    assert "secret" not in first.text
    assert listed.json()[0]["profile_id"] == "sim-a:site_01"


def test_profile_proxy_refresh_changes_existing_proxy() -> None:
    manager = ProfileProxyManager()
    proxy_client = FakeProxyVNClient()
    app = create_app(
        settings=Settings(database_backend="memory", proxyvn_api_key="test-key"),
        repository=MemoryRepository(),
        start_runner=False,
        proxy_manager=manager,
        proxyvn_client=proxy_client,
    )
    client = TestClient(app)

    ensured = client.post(
        "/api/profiles/sim-a:site_01/proxy/ensure",
        json={"policy": ProxyPolicy.STICKY_PROFILE},
    )
    refreshed = client.post("/api/profiles/sim-a:site_01/proxy/refresh")

    assert ensured.status_code == 200
    assert refreshed.status_code == 200
    assert proxy_client.change_count == 1
    assert refreshed.json()["proxy"]["masked_proxy"] == "160.250.166.89:20309:***:***"


def test_profile_proxy_attach_uses_existing_proxy_without_purchase() -> None:
    manager = ProfileProxyManager()
    proxy_client = FakeProxyVNClient()
    app = create_app(
        settings=Settings(database_backend="memory", proxyvn_api_key="test-key"),
        repository=MemoryRepository(),
        start_runner=False,
        proxy_manager=manager,
        proxyvn_client=proxy_client,
    )
    client = TestClient(app)

    attached = client.post(
        "/api/profiles/sim-a:site_01/proxy/attach",
        json={"idproxy": 308},
    )

    assert attached.status_code == 200
    assert proxy_client.purchase_count == 0
    assert attached.json()["proxy"]["idproxy"] == 308
    assert attached.json()["proxy"]["masked_proxy"] == "160.250.166.88:20308:***:***"
