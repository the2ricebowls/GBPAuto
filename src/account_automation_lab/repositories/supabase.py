from __future__ import annotations

import asyncio
from collections.abc import Collection
from typing import Any, cast

from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import JobCreate, JobEvent, JobRecord, JobStatus, utc_now
from account_automation_lab.repositories.memory import InvalidJobTransitionError
from account_automation_lab.settings import Settings

AUTOMATION_JOBS_TABLE = "automation_jobs"
AUTOMATION_JOB_EVENTS_TABLE = "automation_job_events"


class SupabaseRepository:
    def __init__(self, settings: Settings) -> None:
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ValueError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")
        from supabase import create_client

        self._client = create_client(settings.supabase_url, settings.supabase_service_role_key)

    async def create_job(self, payload: JobCreate) -> JobRecord:
        row: dict[str, Any] = {
            "site_key": payload.site_key,
            "sim_id": payload.sim_id,
            "runtime": payload.runtime.value,
            "profile_id": payload.profile_id,
            "metadata": payload.metadata,
        }
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOBS_TABLE).insert(row).execute()
        )
        job = JobRecord.model_validate(result.data[0])
        await self.add_event(job.id, "job.created", "Job queued", {"status": job.status.value})
        return job

    async def list_jobs(self) -> list[JobRecord]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOBS_TABLE)
            .select("*")
            .order("created_at", desc=True)
            .execute()
        )
        return [JobRecord.model_validate(row) for row in result.data]

    async def get_job(self, job_id: str) -> JobRecord | None:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOBS_TABLE)
            .select("*")
            .eq("id", job_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return JobRecord.model_validate(result.data[0])

    async def add_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> JobEvent:
        row: dict[str, Any] = {
            "job_id": job_id,
            "event_type": event_type,
            "message": message,
            "payload": payload or {},
        }
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOB_EVENTS_TABLE).insert(row).execute()
        )
        return JobEvent.model_validate(result.data[0])

    async def get_job_events(self, job_id: str) -> list[JobEvent]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOB_EVENTS_TABLE)
            .select("*")
            .eq("job_id", job_id)
            .order("created_at")
            .execute()
        )
        return [JobEvent.model_validate(row) for row in result.data]

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        event_type: str = "job.status_changed",
        message: str | None = None,
    ) -> JobRecord:
        job = await self.get_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if not can_transition(job.status, status):
            raise InvalidJobTransitionError(f"Cannot transition {job.status} to {status}")
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_JOBS_TABLE)
            .update({"status": status.value, "updated_at": utc_now().isoformat()})
            .eq("id", job_id)
            .execute()
        )
        updated = JobRecord.model_validate(result.data[0])
        await self.add_event(
            job_id,
            event_type,
            message or f"Job status changed to {status.value}",
            {"status": status.value},
        )
        return updated

    async def claim_next_queued(
        self,
        *,
        exclude_sites: Collection[str] = (),
    ) -> JobRecord | None:
        excluded = list(dict.fromkeys(exclude_sites))

        def query() -> Any:
            builder = (
                self._client.table(AUTOMATION_JOBS_TABLE)
                .select("*")
                .eq("status", JobStatus.QUEUED.value)
            )
            if excluded:
                builder = builder.not_.in_("site_key", excluded)
            return builder.order("created_at").limit(1).execute()

        result = await asyncio.to_thread(query)
        if not result.data:
            return None
        row = cast(dict[str, Any], result.data[0])
        return await self.update_job_status(
            str(row["id"]),
            JobStatus.RUNNING,
            message="Job claimed",
        )
