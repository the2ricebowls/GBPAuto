from datetime import UTC, datetime
from pathlib import Path

from account_automation_lab.models import OtpRequest
from account_automation_lab.otp import otp_from_shared_db_rows
from account_automation_lab.settings import Settings


def test_settings_do_not_define_a_second_sms_database() -> None:
    fields = set(Settings.model_fields)

    assert "sms_forwarder_supabase_url" not in fields
    assert "sms_forwarder_supabase_service_role_key" not in fields


def test_env_example_uses_one_supabase_database() -> None:
    env_example = Path(".env.example").read_text(encoding="utf-8")

    assert "SUPABASE_URL=" in env_example
    assert "SUPABASE_SERVICE_ROLE_KEY=" in env_example
    assert "SMS_FORWARDER_SUPABASE" not in env_example


def test_shared_otp_rows_match_receiver_phone_sender_and_time() -> None:
    requested_after = datetime(2026, 5, 27, 1, 0, tzinfo=UTC)
    request = OtpRequest(
        sim_id="+84 901 234 567",
        site_key="site_01",
        sender_hints=("SITE01",),
        requested_after=requested_after,
        timeout_seconds=0.01,
    )

    result = otp_from_shared_db_rows(
        [
            {
                "receiver_phone_normalized": "84901234567",
                "sender_phone": "OTHER",
                "otp": "000000",
                "received_at": "2026-05-27T01:01:00+00:00",
            },
            {
                "receiver_phone_normalized": "84901234567",
                "sender_phone": "SITE01",
                "otp": "123456",
                "received_at": "2026-05-27T01:02:00+00:00",
            },
        ],
        request,
    )

    assert result == "123456"
