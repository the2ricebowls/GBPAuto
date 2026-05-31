from __future__ import annotations

from account_automation_lab.models import (
    FingerprintConfig,
    FingerprintPlatform,
    ProfileGroup,
    ProfileStatus,
)


def test_fingerprint_config_defaults_are_neutral() -> None:
    fp = FingerprintConfig()
    assert fp.platform == FingerprintPlatform.WINDOWS
    assert fp.seed is None
    assert fp.timezone is None
    assert fp.locale is None
    assert fp.color_scheme is None
    assert fp.user_agent is None
    assert fp.viewport is None
    assert fp.geoip_from_proxy is False
    assert fp.extension_paths == []


def test_fingerprint_config_round_trips_through_dict() -> None:
    fp = FingerprintConfig(
        platform=FingerprintPlatform.MACOS,
        seed=12345,
        timezone="Asia/Ho_Chi_Minh",
        locale="vi-VN",
        color_scheme="dark",
        viewport={"width": 1280, "height": 720},
        geoip_from_proxy=True,
        extension_paths=["C:/ext/one"],
    )
    restored = FingerprintConfig.model_validate(fp.model_dump())
    assert restored == fp


def test_profile_group_has_defaults() -> None:
    group = ProfileGroup(name="Facebook farm")
    assert group.id
    assert group.name == "Facebook farm"
    assert group.color is None


def test_profile_status_values() -> None:
    assert ProfileStatus.ACTIVE.value == "active"
    assert ProfileStatus.ARCHIVED.value == "archived"
