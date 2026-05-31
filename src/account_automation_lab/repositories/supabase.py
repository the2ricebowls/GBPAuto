from __future__ import annotations

import asyncio
from collections.abc import Collection
from typing import Any, cast

from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    CaptchaMode,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    ProxyPolicy,
    SiteCreate,
    SiteSpec,
    SiteUpdate,
    utc_now,
)
from account_automation_lab.repositories.memory import InvalidJobTransitionError
from account_automation_lab.settings import Settings

AUTOMATION_JOBS_TABLE = "automation_jobs"
AUTOMATION_JOB_EVENTS_TABLE = "automation_job_events"
AUTOMATION_PROFILES_TABLE = "automation_profiles"
AUTOMATION_PROFILE_GROUPS_TABLE = "automation_profile_groups"
AUTOMATION_SITES_TABLE = "automation_sites"


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

    async def list_profiles(self) -> list[BrowserProfile]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .select("*")
            .order("created_at")
            .execute()
        )
        return [BrowserProfile.model_validate(row) for row in result.data]

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .select("*")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return BrowserProfile.model_validate(result.data[0])

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        row = profile.model_dump(mode="json")
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE).insert(row).execute()
        )
        return BrowserProfile.model_validate(result.data[0])

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        changes = update.model_dump(mode="json", exclude_unset=True)
        changes["updated_at"] = utc_now().isoformat()
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .update(changes)
            .eq("id", profile_id)
            .execute()
        )
        if not result.data:
            raise KeyError(profile_id)
        return BrowserProfile.model_validate(result.data[0])

    async def delete_profile(self, profile_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .delete()
            .eq("id", profile_id)
            .execute()
        )

    async def list_profile_groups(self) -> list[ProfileGroup]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .select("*")
            .order("created_at")
            .execute()
        )
        return [ProfileGroup.model_validate(row) for row in result.data]

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup:
        group = ProfileGroup(name=payload.name, color=payload.color)
        row = group.model_dump(mode="json")
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE).insert(row).execute()
        )
        return ProfileGroup.model_validate(result.data[0])

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup:
        changes = update.model_dump(mode="json", exclude_unset=True)
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .update(changes)
            .eq("id", group_id)
            .execute()
        )
        if not result.data:
            raise KeyError(group_id)
        return ProfileGroup.model_validate(result.data[0])

    async def delete_profile_group(self, group_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .delete()
            .eq("id", group_id)
            .execute()
        )

    def _site_from_row(self, row: dict[str, Any]) -> SiteSpec:
        from account_automation_lab.adapters.registry import code_adapter_keys

        key = str(row["key"])
        hints = row.get("otp_sender_hints") or []
        return SiteSpec(
            key=key,
            display_name=str(row.get("display_name") or key),
            base_url=str(row.get("base_url") or ""),
            description=str(row.get("description") or ""),
            captcha_mode=CaptchaMode(str(row.get("captcha_mode") or "test_key")),
            otp_sender_hints=tuple(str(hint) for hint in hints),
            proxy_policy=ProxyPolicy(str(row.get("proxy_policy") or "sticky_profile")),
            has_code_adapter=key in code_adapter_keys(),
            enabled=bool(row.get("enabled", True)),
        )

    async def list_sites(self) -> list[SiteSpec]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_SITES_TABLE).select("*").order("key").execute()
        )
        return [self._site_from_row(cast(dict[str, Any], row)) for row in result.data]

    async def get_site(self, site_key: str) -> SiteSpec | None:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_SITES_TABLE)
            .select("*")
            .eq("key", site_key)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return self._site_from_row(cast(dict[str, Any], result.data[0]))

    async def create_site(self, payload: SiteCreate) -> SiteSpec:
        row: dict[str, Any] = {
            "key": payload.key,
            "display_name": payload.display_name,
            "base_url": payload.base_url,
            "description": payload.description,
            "captcha_mode": payload.captcha_mode.value,
            "otp_sender_hints": list(payload.otp_sender_hints),
            "proxy_policy": payload.proxy_policy.value,
            "enabled": payload.enabled,
        }
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_SITES_TABLE).insert(row).execute()
        )
        return self._site_from_row(cast(dict[str, Any], result.data[0]))

    async def update_site(self, site_key: str, update: SiteUpdate) -> SiteSpec:
        changes = update.model_dump(mode="json", exclude_unset=True)
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_SITES_TABLE)
            .update(changes)
            .eq("key", site_key)
            .execute()
        )
        if not result.data:
            raise KeyError(site_key)
        return self._site_from_row(cast(dict[str, Any], result.data[0]))

    async def delete_site(self, site_key: str) -> None:
        await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_SITES_TABLE)
            .delete()
            .eq("key", site_key)
            .execute()
        )
