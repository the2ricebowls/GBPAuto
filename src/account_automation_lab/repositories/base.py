from __future__ import annotations

from collections.abc import Collection
from typing import Protocol

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
)


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

    async def list_profiles(self) -> list[BrowserProfile]: ...

    async def get_profile(self, profile_id: str) -> BrowserProfile | None: ...

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile: ...

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile: ...

    async def delete_profile(self, profile_id: str) -> None: ...

    async def list_profile_groups(self) -> list[ProfileGroup]: ...

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup: ...

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup: ...

    async def delete_profile_group(self, group_id: str) -> None: ...

    async def list_sites(self) -> list[SiteSpec]: ...

    async def get_site(self, site_key: str) -> SiteSpec | None: ...

    async def create_site(self, payload: SiteCreate) -> SiteSpec: ...

    async def update_site(self, site_key: str, update: SiteUpdate) -> SiteSpec: ...

    async def delete_site(self, site_key: str) -> None: ...
