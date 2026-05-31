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
