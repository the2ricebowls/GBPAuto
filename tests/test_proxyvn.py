from __future__ import annotations

import httpx
import pytest

from account_automation_lab.models import ProxyPolicy
from account_automation_lab.proxy import (
    ProfileProxyManager,
    ProxyVNClient,
    ProxyVNError,
    parse_proxyvn_items,
)


def test_parse_proxyvn_purchase_response_masks_credentials() -> None:
    leases = parse_proxyvn_items(
        [
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
            },
            {"status": 200, "comen": "You have successfully purchased 1"},
        ]
    )

    assert len(leases) == 1
    lease = leases[0]
    assert lease.idproxy == 308
    assert lease.playwright_proxy == {
        "server": "http://160.250.166.88:20308",
        "username": "secret-user",
        "password": "secret-pass",
    }
    assert lease.masked_proxy == "160.250.166.88:20308:***:***"
    assert "secret" not in lease.safe_summary().model_dump_json()


@pytest.mark.asyncio
async def test_proxyvn_client_purchases_one_day_proxy_with_default_params() -> None:
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return httpx.Response(
            200,
            json=[
                {
                    "status": 100,
                    "loaiproxy": "4Gvinaphone",
                    "idproxy": 308,
                    "ip": "160.250.166.88",
                    "port": 20308,
                    "user": "u",
                    "password": "p",
                    "type": "HTTPS",
                    "proxy": "160.250.166.88:20308:u:p",
                    "time": 1779906500,
                },
                {"status": 200, "comen": "You have successfully purchased 1"},
            ],
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http:
        client = ProxyVNClient(api_key="test-key", http_client=http)
        lease = await client.purchase_one_day_proxy()

    assert lease.idproxy == 308
    assert captured_request is not None
    params = dict(captured_request.url.params)
    assert captured_request.url.path.endswith("/muaproxy.php")
    assert params["loaiproxy"] == "4Gvinaphone"
    assert params["soluong"] == "1"
    assert params["ngay"] == "1"
    assert params["type"] == "HTTP"
    assert params["user"] == "random"
    assert params["password"] == "random"


def test_proxyvn_status_errors_are_human_readable() -> None:
    with pytest.raises(ProxyVNError, match="Không đủ tiền"):
        parse_proxyvn_items({"status": 102})


@pytest.mark.asyncio
async def test_profile_proxy_manager_reuses_one_proxy_per_profile() -> None:
    manager = ProfileProxyManager()
    lease = parse_proxyvn_items(
        {
            "status": 100,
            "loaiproxy": "4Gvinaphone",
            "idproxy": 308,
            "ip": "160.250.166.88",
            "port": 20308,
            "user": "u",
            "password": "p",
            "type": "HTTPS",
            "proxy": "160.250.166.88:20308:u:p",
            "time": 1779906500,
        }
    )[0]

    first = await manager.assign("sim-a:site_01", lease, ProxyPolicy.STICKY_PROFILE)
    second = await manager.get("sim-a:site_01")

    assert first == second
    assert first is not None
    assert first.profile_id == "sim-a:site_01"
    assert first.proxy.masked_proxy == "160.250.166.88:20308:***:***"
