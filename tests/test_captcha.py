import pytest

from account_automation_lab.captcha import CaptchaBroker, ProviderDisabledError
from account_automation_lab.models import CaptchaMode, CaptchaOutcome


@pytest.mark.asyncio
async def test_test_key_captcha_returns_configured_token() -> None:
    broker = CaptchaBroker(test_key_token="test-token")

    result = await broker.solve(
        mode=CaptchaMode.TEST_KEY,
        site_key="site_01",
        page_url="http://localhost/mock",
        job_id="job-1",
    )

    assert result.outcome == CaptchaOutcome.SOLVED
    assert result.token == "test-token"


@pytest.mark.asyncio
async def test_manual_captcha_creates_waiting_checkpoint() -> None:
    broker = CaptchaBroker()

    result = await broker.solve(
        mode=CaptchaMode.MANUAL,
        site_key="site_01",
        page_url="http://localhost/mock",
        job_id="job-1",
    )

    assert result.outcome == CaptchaOutcome.WAITING
    assert result.manual_checkpoint_id == "job-1:site_01:manual-captcha"


@pytest.mark.asyncio
async def test_provider_captcha_is_disabled_by_default() -> None:
    broker = CaptchaBroker(provider_enabled=False)

    with pytest.raises(ProviderDisabledError):
        await broker.solve(
            mode=CaptchaMode.PROVIDER,
            site_key="site_01",
            page_url="http://localhost/mock",
            job_id="job-1",
        )
