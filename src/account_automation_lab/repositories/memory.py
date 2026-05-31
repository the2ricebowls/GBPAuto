from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection

from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import JobCreate, JobEvent, JobRecord, JobStatus, utc_now


class InvalidJobTransitionError(RuntimeError):
    pass


class MemoryRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._events: dict[str, list[JobEvent]] = defaultdict(list)

    async def create_job(self, payload: JobCreate) -> JobRecord:
        job = JobRecord(
            site_key=payload.site_key,
            sim_id=payload.sim_id,
            runtime=payload.runtime,
            profile_id=payload.profile_id,
            metadata=payload.metadata,
        )
        self._jobs[job.id] = job
        await self.add_event(job.id, "job.created", "Job queued", {"status": job.status.value})
        return job

    async def list_jobs(self) -> list[JobRecord]:
        return sorted(self._jobs.values(), key=lambda job: job.created_at, reverse=True)

    async def get_job(self, job_id: str) -> JobRecord | None:
        return self._jobs.get(job_id)

    async def add_event(
        self,
        job_id: str,
        event_type: str,
        message: str,
        payload: dict[str, object] | None = None,
    ) -> JobEvent:
        event = JobEvent(
            job_id=job_id,
            event_type=event_type,
            message=message,
            payload=dict(payload or {}),
        )
        self._events[job_id].append(event)
        return event

    async def get_job_events(self, job_id: str) -> list[JobEvent]:
        return sorted(self._events.get(job_id, []), key=lambda event: event.created_at)

    async def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        *,
        event_type: str = "job.status_changed",
        message: str | None = None,
    ) -> JobRecord:
        job = self._jobs[job_id]
        if not can_transition(job.status, status):
            raise InvalidJobTransitionError(f"Cannot transition {job.status} to {status}")
        updated = job.model_copy(update={"status": status, "updated_at": utc_now()})
        self._jobs[job_id] = updated
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
        excluded = set(exclude_sites)
        queued = sorted(
            (
                job
                for job in self._jobs.values()
                if job.status == JobStatus.QUEUED and job.site_key not in excluded
            ),
            key=lambda job: job.created_at,
        )
        if not queued:
            return None
        return await self.update_job_status(queued[0].id, JobStatus.RUNNING, message="Job claimed")
