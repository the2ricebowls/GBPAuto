from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from account_automation_lab.models import ProfileProxyAssignment, ProxyLeaseSummary, ProxyPolicy

PROXYVN_STATUS_MESSAGES = {
    101: "Key không tồn tại",
    102: "Không đủ tiền",
    103: "Loại proxy này đang hết hàng",
    104: "Lỗi không xác định",
    201: "Đã mua thành công nhưng không đủ số lượng",
}


class ProxyVNError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProxyVNLease:
    idproxy: int
    loaiproxy: str
    ip: str
    port: int
    user: str
    password: str
    type: str
    expires_at: int | None = None

    @property
    def server(self) -> str:
        return f"http://{self.ip}:{self.port}"

    @property
    def masked_proxy(self) -> str:
        return f"{self.ip}:{self.port}:***:***"

    @property
    def playwright_proxy(self) -> dict[str, str]:
        return {"server": self.server, "username": self.user, "password": self.password}

    def safe_summary(self) -> ProxyLeaseSummary:
        return ProxyLeaseSummary(
            idproxy=self.idproxy,
            loaiproxy=self.loaiproxy,
            ip=self.ip,
            port=self.port,
            type=self.type,
            expires_at=self.expires_at,
            masked_proxy=self.masked_proxy,
        )


@dataclass(frozen=True)
class ProfileProxyLease:
    profile_id: str
    policy: ProxyPolicy
    proxy: ProxyVNLease

    def safe_assignment(self) -> ProfileProxyAssignment:
        return ProfileProxyAssignment(
            profile_id=self.profile_id,
            policy=self.policy,
            proxy=self.proxy.safe_summary(),
        )


def parse_proxyvn_items(payload: object) -> list[ProxyVNLease]:
    items = payload if isinstance(payload, list) else [payload]
    leases: list[ProxyVNLease] = []
    errors: list[str] = []

    for item in items:
        if not isinstance(item, dict):
            continue
        status = _int_or_none(item.get("status"))
        if status == 100 and item.get("proxy"):
            leases.append(_lease_from_item(item))
            continue
        if status in PROXYVN_STATUS_MESSAGES:
            errors.append(PROXYVN_STATUS_MESSAGES[status])

    if leases:
        return leases
    if errors:
        raise ProxyVNError("; ".join(errors))
    return []


class ProxyVNClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://proxy.vn/apiv2",
        loaiproxy: str = "4Gvinaphone",
        default_days: int = 1,
        default_type: str = "HTTP",
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("PROXYVN_API_KEY is required.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.loaiproxy = loaiproxy
        self.default_days = default_days
        self.default_type = default_type
        self.http_client = http_client

    async def purchase_one_day_proxy(self) -> ProxyVNLease:
        leases = await self._request(
            "muaproxy.php",
            {
                "loaiproxy": self.loaiproxy,
                "soluong": "1",
                "ngay": str(self.default_days),
                "type": self.default_type,
                "user": "random",
                "password": "random",
            },
        )
        if not leases:
            raise ProxyVNError("ProxyVN did not return a purchased proxy.")
        return leases[0]

    async def list_proxy(self, idproxy: str = "all") -> list[ProxyVNLease]:
        return await self._request(
            "listproxy.php",
            {"loaiproxy": self.loaiproxy, "idproxy": idproxy},
        )

    async def change_proxy(self, idproxy: int) -> ProxyVNLease:
        leases = await self._request(
            "doiproxy.php",
            {
                "loaiproxy": self.loaiproxy,
                "loaiproxynhan": self.loaiproxy,
                "type": self.default_type,
                "user": "random",
                "password": "random",
                "idproxy": str(idproxy),
            },
        )
        if not leases:
            raise ProxyVNError("ProxyVN did not return a changed proxy.")
        return leases[0]

    async def _request(self, endpoint: str, params: dict[str, str]) -> list[ProxyVNLease]:
        request_params = {**params, "key": self.api_key}
        headers = {
            "User-Agent": "Mozilla/5.0 AccountAutomationLab/0.1",
            "Accept": "application/json,text/plain,*/*",
        }
        if self.http_client is not None:
            response = await self.http_client.get(
                f"{self.base_url}/{endpoint}",
                params=request_params,
                headers=headers,
            )
            response.raise_for_status()
            return parse_proxyvn_items(response.json())

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.get(
                f"{self.base_url}/{endpoint}",
                params=request_params,
                headers=headers,
            )
            response.raise_for_status()
            return parse_proxyvn_items(response.json())


class ProfileProxyManager:
    def __init__(self) -> None:
        self._assignments: dict[str, ProfileProxyLease] = {}

    async def assign(
        self,
        profile_id: str,
        lease: ProxyVNLease,
        policy: ProxyPolicy,
    ) -> ProfileProxyLease:
        assignment = ProfileProxyLease(profile_id=profile_id, proxy=lease, policy=policy)
        self._assignments[profile_id] = assignment
        return assignment

    async def get(self, profile_id: str) -> ProfileProxyLease | None:
        return self._assignments.get(profile_id)

    async def list_assignments(self) -> list[ProfileProxyAssignment]:
        return [assignment.safe_assignment() for assignment in self._assignments.values()]


def _lease_from_item(item: dict[str, Any]) -> ProxyVNLease:
    proxy = str(item.get("proxy") or "")
    parts = proxy.split(":")
    ip = str(item.get("ip") or (parts[0] if len(parts) >= 1 else ""))
    port = _int_or_none(item.get("port")) or _int_or_none(parts[1] if len(parts) >= 2 else None)
    user = str(item.get("user") or (parts[2] if len(parts) >= 3 else ""))
    password = str(item.get("password") or (":".join(parts[3:]) if len(parts) >= 4 else ""))
    if not ip or port is None or not user or not password:
        raise ProxyVNError("ProxyVN returned an incomplete proxy record.")
    return ProxyVNLease(
        idproxy=_int_or_none(item.get("idproxy")) or 0,
        loaiproxy=str(item.get("loaiproxy") or ""),
        ip=ip,
        port=port,
        user=user,
        password=password,
        type=str(item.get("type") or "HTTP"),
        expires_at=_int_or_none(item.get("time")),
    )


def _int_or_none(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


class MemoryProxyApiClient:
    def __init__(self, seed: str = "proxy") -> None:
        self.seed = seed
        self.issue_count = 0

    async def issue_proxy(self, profile_id: str, policy: ProxyPolicy) -> str:
        self.issue_count += 1
        return f"{self.seed}-{profile_id}-{policy.value}-{self.issue_count}"


class ProxyProvider:
    def __init__(self, api_client: MemoryProxyApiClient) -> None:
        self.api_client = api_client
        self._sticky_by_profile: dict[str, str] = {}

    async def resolve_proxy(self, profile_id: str, policy: ProxyPolicy) -> str | None:
        if policy == ProxyPolicy.NONE:
            return None
        if policy == ProxyPolicy.STICKY_PROFILE:
            existing = self._sticky_by_profile.get(profile_id)
            if existing is not None:
                return existing
            proxy = await self.api_client.issue_proxy(profile_id, policy)
            self._sticky_by_profile[profile_id] = proxy
            return proxy
        return await self.api_client.issue_proxy(profile_id, policy)
