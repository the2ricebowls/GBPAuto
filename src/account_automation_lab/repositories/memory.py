from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection

from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    SiteCreate,
    SiteSpec,
    SiteUpdate,
    utc_now,
)


class InvalidJobTransitionError(RuntimeError):
    pass


class SiteExistsError(RuntimeError):
    pass


class MemoryRepository:
    def __init__(self) -> None:
        self._jobs: dict[str, JobRecord] = {}
        self._events: dict[str, list[JobEvent]] = defaultdict(list)
        self._profiles: dict[str, BrowserProfile] = {}
        self._groups: dict[str, ProfileGroup] = {}
        self._sites: dict[str, SiteSpec] = {}
        self._seed_code_sites()

    def _seed_code_sites(self) -> None:
        from account_automation_lab.adapters.registry import load_adapters

        for adapter in load_adapters().values():
            self._sites[adapter.spec.key] = adapter.spec

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

    async def list_profiles(self) -> list[BrowserProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.created_at)

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return self._profiles.get(profile_id)

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        self._profiles[profile.id] = profile
        return profile

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        current = self._profiles[profile_id]
        changes = update.model_dump(exclude_unset=True)
        changes["updated_at"] = utc_now()
        updated = current.model_copy(update=changes)
        self._profiles[profile_id] = updated
        return updated

    async def delete_profile(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)

    async def list_profile_groups(self) -> list[ProfileGroup]:
        return sorted(self._groups.values(), key=lambda g: g.created_at)

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup:
        group = ProfileGroup(name=payload.name, color=payload.color)
        self._groups[group.id] = group
        return group

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup:
        current = self._groups[group_id]
        changes = update.model_dump(exclude_unset=True)
        updated = current.model_copy(update=changes)
        self._groups[group_id] = updated
        return updated

    async def delete_profile_group(self, group_id: str) -> None:
        self._groups.pop(group_id, None)

    async def list_sites(self) -> list[SiteSpec]:
        return sorted(self._sites.values(), key=lambda s: s.key)

    async def get_site(self, site_key: str) -> SiteSpec | None:
        return self._sites.get(site_key)

    async def create_site(self, payload: SiteCreate) -> SiteSpec:
        if payload.key in self._sites:
            raise SiteExistsError(f"Site {payload.key} already exists")
        spec = SiteSpec(
            key=payload.key,
            display_name=payload.display_name,
            base_url=payload.base_url,
            description=payload.description,
            captcha_mode=payload.captcha_mode,
            otp_sender_hints=tuple(payload.otp_sender_hints),
            proxy_policy=payload.proxy_policy,
            has_code_adapter=False,
            enabled=payload.enabled,
        )
        self._sites[spec.key] = spec
        return spec

    async def update_site(self, site_key: str, update: SiteUpdate) -> SiteSpec:
        current = self._sites[site_key]
        changes = update.model_dump(exclude_unset=True)
        if "otp_sender_hints" in changes and changes["otp_sender_hints"] is not None:
            changes["otp_sender_hints"] = tuple(changes["otp_sender_hints"])
        updated = current.model_copy(update=changes)
        self._sites[site_key] = updated
        return updated

    async def delete_site(self, site_key: str) -> None:
        self._sites.pop(site_key, None)
