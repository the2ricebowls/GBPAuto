from __future__ import annotations

from datetime import UTC, datetime

from account_automation_lab.models import JobEvent
from account_automation_lab.ui.pages import _event_rows


def test_event_rows_include_stable_event_id() -> None:
    event = JobEvent(
        id="event-123",
        job_id="job-123",
        event_type="started",
        message="Job started",
        created_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )

    rows = _event_rows([event])

    assert rows == [
        {
            "id": "event-123",
            "time": "2026-01-02 03:04:05 UTC",
            "type": "started",
            "message": "Job started",
        }
    ]


def test_browser_profile_rows_render_group_and_status() -> None:
    from account_automation_lab.models import (
        BrowserProfile,
        FingerprintConfig,
        ProfileStatus,
    )
    from account_automation_lab.ui.pages import _profile_manager_rows

    profile = BrowserProfile(
        id="p1",
        name="My FB",
        group_id="g1",
        tags=["fb", "warm"],
        storage_dir="C:/p/p1",
        status=ProfileStatus.ACTIVE,
        fingerprint=FingerprintConfig(timezone="Asia/Ho_Chi_Minh"),
    )

    rows = _profile_manager_rows(
        profiles=[profile],
        groups={"g1": "Facebook"},
        assignments=[],
        sessions=[],
    )

    assert rows[0]["name"] == "My FB"
    assert rows[0]["group"] == "Facebook"
    assert rows[0]["tags"] == "fb, warm"
    assert rows[0]["session"] == "idle"
    assert rows[0]["proxy"] == ""
    assert rows[0]["timezone"] == "Asia/Ho_Chi_Minh"


def test_group_options_include_all_and_ungrouped() -> None:
    from account_automation_lab.models import ProfileGroup
    from account_automation_lab.ui.pages import _group_filter_options

    options = _group_filter_options([ProfileGroup(id="g1", name="Facebook")])

    assert options["__all__"] == "All profiles"
    assert options["__none__"] == "Ungrouped"
    assert options["g1"] == "Facebook"
