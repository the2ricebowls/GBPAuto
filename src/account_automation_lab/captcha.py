from __future__ import annotations

from account_automation_lab.models import CaptchaMode, CaptchaOutcome, CaptchaResult


class ProviderDisabledError(RuntimeError):
    """Raised when provider-backed CAPTCHA solving is requested without explicit enablement."""


class CaptchaBroker:
    def __init__(
        self,
        *,
        test_key_token: str = "test-captcha-token",
        provider_enabled: bool = False,
    ) -> None:
        self.test_key_token = test_key_token
        self.provider_enabled = provider_enabled

    async def solve(
        self,
        *,
        mode: CaptchaMode,
        site_key: str,
        page_url: str,
        job_id: str,
    ) -> CaptchaResult:
        if mode == CaptchaMode.NONE:
            return CaptchaResult(outcome=CaptchaOutcome.SOLVED)
        if mode == CaptchaMode.TEST_KEY:
            return CaptchaResult(outcome=CaptchaOutcome.SOLVED, token=self.test_key_token)
        if mode == CaptchaMode.MANUAL:
            return CaptchaResult(
                outcome=CaptchaOutcome.WAITING,
                manual_checkpoint_id=f"{job_id}:{site_key}:manual-captcha",
            )
        if not self.provider_enabled:
            raise ProviderDisabledError(
                "Provider CAPTCHA mode is disabled. "
                "Use manual/test-key mode or enable it explicitly."
            )
        return CaptchaResult(
            outcome=CaptchaOutcome.FAILED,
            error=f"Provider CAPTCHA integration is not configured for {page_url}.",
        )
