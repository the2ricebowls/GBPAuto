from __future__ import annotations

from account_automation_lab.browser.fingerprint import fingerprint_launch_kwargs
from account_automation_lab.models import FingerprintConfig, FingerprintPlatform


def test_empty_fingerprint_produces_minimal_kwargs() -> None:
    kwargs = fingerprint_launch_kwargs(FingerprintConfig())
    assert kwargs == {"geoip": False}


def test_full_fingerprint_maps_each_field() -> None:
    fp = FingerprintConfig(
        platform=FingerprintPlatform.MACOS,
        seed=42,
        timezone="Asia/Ho_Chi_Minh",
        locale="vi-VN",
        color_scheme="dark",
        user_agent="UA/1.0",
        viewport={"width": 1280, "height": 720},
        geoip_from_proxy=True,
    )
    kwargs = fingerprint_launch_kwargs(fp)
    assert kwargs["timezone"] == "Asia/Ho_Chi_Minh"
    assert kwargs["locale"] == "vi-VN"
    assert kwargs["color_scheme"] == "dark"
    assert kwargs["user_agent"] == "UA/1.0"
    assert kwargs["viewport"] == {"width": 1280, "height": 720}
    assert kwargs["geoip"] is True
    assert "--fingerprint-platform=macos" in kwargs["args"]
    assert "--fingerprint=42" in kwargs["args"]


def test_seed_omitted_when_none() -> None:
    kwargs = fingerprint_launch_kwargs(FingerprintConfig(seed=None))
    assert "args" not in kwargs or all("--fingerprint=" not in a for a in kwargs["args"])
