from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

from account_automation_lab.models import JobCreate, JobEvent, JobRecord, JobStatus


class AutomationRepository(Protocol):
    async def create_job(self, payload: JobCreate) -> JobRecord: ...

    async def list_jobs(self) -> list[JobRecord]: ...

    async def get_job(self, job_id: str) -> JobRecord | None: ...

    async def add_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> JobEvent: ...

    async def get_job_events(self, job_id: str) -> list[JobEvent]: ...

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        event_type: str = "job.status_changed",
        message: str | None = None,
    ) -> JobRecord: ...

    async def claim_next_queued(
        self,
        *,
        exclude_sites: Collection[str] = (),
    ) -> JobRecord | None: ...
