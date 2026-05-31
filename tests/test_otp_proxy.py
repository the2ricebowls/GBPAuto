from datetime import UTC, datetime, timedelta

import pytest

from account_automation_lab.models import OtpMessage, OtpRequest, ProxyPolicy
from account_automation_lab.otp import MemoryOtpProvider
from account_automation_lab.proxy import MemoryProxyApiClient, ProxyProvider


@pytest.mark.asyncio
async def test_otp_provider_scopes_by_sim_site_sender_and_requested_after() -> None:
    requested_after = datetime.now(UTC)
    provider = MemoryOtpProvider(
        [
            OtpMessage(
                sim_id="sim-a",
                site_key="site_01",
                sender="OTHER",
                otp="000000",
                received_at=requested_after + timedelta(seconds=1),
            ),
            OtpMessage(
                sim_id="sim-a",
                site_key="site_01",
                sender="SITE01",
                otp="123456",
                received_at=requested_after + timedelta(seconds=2),
            ),
        ]
    )

    result = await provider.wait_for_otp(
        OtpRequest(
            sim_id="sim-a",
            site_key="site_01",
            sender_hints=("SITE01",),
            requested_after=requested_after,
            timeout_seconds=0.01,
        )
    )

    assert result == "123456"


@pytest.mark.asyncio
async def test_proxy_provider_reuses_sticky_profile_proxy() -> None:
    api = MemoryProxyApiClient(seed="proxy-a")
    provider = ProxyProvider(api)

    first = await provider.resolve_proxy("profile-1", ProxyPolicy.STICKY_PROFILE)
    second = await provider.resolve_proxy("profile-1", ProxyPolicy.STICKY_PROFILE)

    assert first == second
    assert api.issue_count == 1


@pytest.mark.asyncio
async def test_proxy_provider_refreshes_for_fresh_per_job_policy() -> None:
    api = MemoryProxyApiClient(seed="proxy")
    provider = ProxyProvider(api)

    first = await provider.resolve_proxy("profile-1", ProxyPolicy.FRESH_PER_JOB)
    second = await provider.resolve_proxy("profile-1", ProxyPolicy.FRESH_PER_JOB)

    assert first != second
    assert api.issue_count == 2
