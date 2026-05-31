from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from typing import Any, cast

from account_automation_lab.models import OtpMessage, OtpRequest
from account_automation_lab.settings import Settings


class MemoryOtpProvider:
    def __init__(self, messages: list[OtpMessage] | None = None) -> None:
        self._messages = messages or []

    def add_message(self, message: OtpMessage) -> None:
        self._messages.append(message)

    async def wait_for_otp(self, request: OtpRequest) -> str | None:
        deadline = datetime.now(UTC).timestamp() + request.timeout_seconds
        while True:
            otp = self._find_matching_otp(request)
            if otp is not None:
                return otp
            if datetime.now(UTC).timestamp() >= deadline:
                return None
            await asyncio.sleep(min(0.25, max(request.timeout_seconds, 0.01)))

    def _find_matching_otp(self, request: OtpRequest) -> str | None:
        sender_hints = {hint.lower() for hint in request.sender_hints}
        for message in sorted(self._messages, key=lambda item: item.received_at):
            if message.sim_id != request.sim_id:
                continue
            if message.site_key != request.site_key:
                continue
            if message.received_at < request.requested_after:
                continue
            if sender_hints and message.sender.lower() not in sender_hints:
                continue
            return message.otp
        return None


def normalize_phone(value: str) -> str:
    digits = re.sub(r"\D+", "", value)
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("0") and len(digits) >= 9:
        return f"84{digits[1:]}"
    return digits


def otp_from_shared_db_rows(rows: list[dict[str, Any]], request: OtpRequest) -> str | None:
    receiver_phone = normalize_phone(request.sim_id)
    sender_hints = {hint.lower() for hint in request.sender_hints}

    for row in sorted(rows, key=lambda item: _parse_received_at(item.get("received_at"))):
        row_receiver = str(row.get("receiver_phone_normalized") or "")
        if row_receiver and row_receiver != receiver_phone:
            continue
        received_at = _parse_received_at(row.get("received_at"))
        if received_at < request.requested_after:
            continue
        sender = str(row.get("sender_phone") or "").lower()
        sender_normalized = str(row.get("sender_phone_normalized") or "").lower()
        if sender_hints and sender not in sender_hints and sender_normalized not in sender_hints:
            continue
        otp = row.get("otp")
        if otp:
            return str(otp)
    return None


class SharedSupabaseOtpProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        from supabase import create_client

        self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    async def wait_for_otp(self, request: OtpRequest) -> str | None:
        deadline = datetime.now(UTC).timestamp() + request.timeout_seconds
        while True:
            rows = await self._fetch_rows(request)
            otp = otp_from_shared_db_rows(rows, request)
            if otp is not None:
                return otp
            if datetime.now(UTC).timestamp() >= deadline:
                return None
            await asyncio.sleep(1)

    async def _fetch_rows(self, request: OtpRequest) -> list[dict[str, Any]]:
        receiver_phone = normalize_phone(request.sim_id)

        def query() -> list[dict[str, Any]]:
            result = (
                self._client.table("otp_messages")
                .select(
                    "receiver_phone_normalized,sender_phone,sender_phone_normalized,otp,received_at"
                )
                .eq("receiver_phone_normalized", receiver_phone)
                .gte("received_at", request.requested_after.isoformat())
                .order("received_at")
                .limit(20)
                .execute()
            )
            return [cast(dict[str, Any], row) for row in result.data]

        return await asyncio.to_thread(query)


def _parse_received_at(value: object) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    else:
        return datetime.min.replace(tzinfo=UTC)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)
