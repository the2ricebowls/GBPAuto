from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, status

from account_automation_lab.adapters.registry import adapter_for, load_adapters
from account_automation_lab.browser.profiles import (
    BrowserProfileExistsError,
    BrowserProfileStore,
    BrowserSessionError,
    BrowserSessionManager,
)
from account_automation_lab.jobs.runner import JobRunner
from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserProfileView,
    BrowserSession,
    BrowserSessionStatus,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    ProfileProxyAssignment,
    ProxyAttachRequest,
    ProxyEnsureRequest,
    SecretCheck,
    SiteSpec,
)
from account_automation_lab.proxy import ProfileProxyManager, ProxyVNClient, ProxyVNError
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.factory import create_repository
from account_automation_lab.repositories.memory import InvalidJobTransitionError
from account_automation_lab.settings import Settings, get_settings


def create_app(
    *,
    settings: Settings | None = None,
    repository: AutomationRepository | None = None,
    start_runner: bool = True,
    proxy_manager: ProfileProxyManager | None = None,
    proxyvn_client: Any | None = None,
    browser_profile_store: BrowserProfileStore | None = None,
    browser_session_manager: BrowserSessionManager | None = None,
) -> FastAPI:
    app_settings = settings or get_settings()
    repo = repository or create_repository(app_settings)
    profile_proxy_manager = proxy_manager or ProfileProxyManager()
    proxy_client = proxyvn_client or _create_proxyvn_client(app_settings)
    browser_store = browser_profile_store or BrowserProfileStore(
        storage_root=Path(app_settings.browser_profile_storage_root),
        repository=repo,
    )
    browser_sessions = browser_session_manager or BrowserSessionManager(
        store=browser_store,
        settings=app_settings,
        proxy_manager=profile_proxy_manager,
    )
    runner = JobRunner(repository=repo, settings=app_settings)

    async def _page_provider(profile_id: str) -> Any:
        active = browser_sessions._active.get(profile_id)
        if active is None:
            opened = await browser_sessions.open_profile(profile_id)
            active = browser_sessions._active.get(opened.profile_id)
        context = active.context if active is not None else None
        if context is None:
            return None
        pages = getattr(context, "pages", None)
        if pages:
            return pages[0]
        new_page = getattr(context, "new_page", None)
        return await new_page() if new_page is not None else None

    runner.set_page_provider(_page_provider)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if start_runner:
            await runner.start()
        try:
            yield
        finally:
            await browser_sessions.close_all()
            if start_runner:
                await runner.stop()

    app = FastAPI(title="Account Automation Lab", version="0.1.0", lifespan=lifespan)
    app.state.settings = app_settings
    app.state.repository = repo
    app.state.runner = runner
    app.state.proxy_manager = profile_proxy_manager
    app.state.proxyvn_client = proxy_client
    app.state.browser_profile_store = browser_store
    app.state.browser_session_manager = browser_sessions

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {
            "ok": True,
            "environment": app_settings.app_env,
            "database_backend": app_settings.database_backend,
            "runner_started": runner.is_started,
        }

    @app.get("/api/secrets/health")
    async def secrets_health() -> dict[str, SecretCheck]:
        return {
            "supabase": _check_required(
                app_settings.supabase_url,
                app_settings.supabase_service_role_key,
                names=("SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"),
                enabled=app_settings.database_backend == "supabase",
            ),
            "sim_otp_api": _check_required(
                app_settings.sim_otp_api_base_url,
                app_settings.sim_otp_api_key,
                names=("SIM_OTP_API_BASE_URL", "SIM_OTP_API_KEY"),
                enabled=True,
            ),
            "proxy_api": _check_required(
                app_settings.proxyvn_api_key,
                names=("PROXYVN_API_KEY",),
                enabled=True,
            ),
            "captcha_provider": _check_required(
                app_settings.captcha_provider_base_url,
                app_settings.captcha_provider_api_key,
                names=("CAPTCHA_PROVIDER_BASE_URL", "CAPTCHA_PROVIDER_API_KEY"),
                enabled=app_settings.captcha_provider_enabled,
            ),
            "cloakbrowser": _check_required(
                "enabled" if app_settings.cloakbrowser_enabled else "",
                names=("CLOAKBROWSER_ENABLED",),
                enabled=app_settings.cloakbrowser_enabled,
            ),
        }

    @app.get("/api/sites")
    async def list_sites() -> list[SiteSpec]:
        return [adapter.spec for adapter in load_adapters().values()]

    @app.get("/api/sims")
    async def list_sims() -> list[dict[str, str]]:
        return [{"id": "sim-a", "label": "SIM A"}, {"id": "sim-b", "label": "SIM B"}]

    @app.get("/api/profiles")
    async def list_profiles() -> list[dict[str, Any]]:
        assignments = {
            assignment.profile_id: assignment
            for assignment in await profile_proxy_manager.list_assignments()
        }
        profiles: list[dict[str, Any]] = []
        for site_key in load_adapters():
            profile_id = f"sim-a:{site_key}"
            assignment = assignments.get(profile_id)
            profiles.append(
                {
                    "id": profile_id,
                    "site_key": site_key,
                    "proxy_assigned": assignment is not None,
                    "proxy": assignment.proxy.masked_proxy if assignment else None,
                }
            )
        return profiles

    @app.get("/api/browser-profiles")
    async def list_browser_profiles() -> list[BrowserProfileView]:
        profiles = await browser_store.list_profiles()
        return [
            await _browser_profile_view(profile, profile_proxy_manager, browser_sessions)
            for profile in profiles
        ]

    @app.post(
        "/api/browser-profiles",
        status_code=status.HTTP_201_CREATED,
    )
    async def create_browser_profile(payload: BrowserProfileCreate) -> BrowserProfile:
        try:
            return await browser_store.create_profile(payload)
        except BrowserProfileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.patch("/api/browser-profiles/{profile_id}")
    async def update_browser_profile(
        profile_id: str, payload: BrowserProfileUpdate
    ) -> BrowserProfile:
        try:
            return await browser_store.update_profile(profile_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser profile not found") from exc

    @app.post("/api/browser-profiles/{profile_id}/clone", status_code=status.HTTP_201_CREATED)
    async def clone_browser_profile(profile_id: str) -> BrowserProfile:
        try:
            return await browser_store.clone_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser profile not found") from exc

    @app.delete("/api/browser-profiles/{profile_id}")
    async def delete_browser_profile(
        profile_id: str, remove_storage: bool = False
    ) -> dict[str, str | bool]:
        await browser_store.delete_profile(profile_id, remove_storage=remove_storage)
        return {"deleted": True, "profile_id": profile_id}

    @app.get("/api/profile-groups")
    async def list_profile_groups() -> list[ProfileGroup]:
        return await repo.list_profile_groups()

    @app.post("/api/profile-groups", status_code=status.HTTP_201_CREATED)
    async def create_profile_group(payload: ProfileGroupCreate) -> ProfileGroup:
        return await repo.create_profile_group(payload)

    @app.patch("/api/profile-groups/{group_id}")
    async def update_profile_group(
        group_id: str, payload: ProfileGroupUpdate
    ) -> ProfileGroup:
        try:
            return await repo.update_profile_group(group_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Group not found") from exc

    @app.delete("/api/profile-groups/{group_id}")
    async def delete_profile_group(group_id: str) -> dict[str, str | bool]:
        await repo.delete_profile_group(group_id)
        return {"deleted": True, "group_id": group_id}

    @app.get("/api/browser-sessions")
    async def list_browser_sessions() -> list[BrowserSession]:
        return await browser_sessions.list_sessions()

    @app.post("/api/browser-profiles/{profile_id}/open")
    async def open_browser_profile(profile_id: str) -> BrowserSession:
        try:
            return await browser_sessions.open_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser profile not found") from exc
        except BrowserSessionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/browser-profiles/{profile_id}/close")
    async def close_browser_profile(profile_id: str) -> dict[str, str | bool]:
        try:
            await browser_sessions.close_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser session not found") from exc
        return {"closed": True, "profile_id": profile_id}

    @app.get("/api/proxies")
    async def list_proxies() -> list[ProfileProxyAssignment]:
        return await profile_proxy_manager.list_assignments()

    @app.post("/api/profiles/{profile_id}/proxy/ensure")
    async def ensure_profile_proxy(
        profile_id: str,
        payload: ProxyEnsureRequest | None = None,
    ) -> ProfileProxyAssignment:
        existing = await profile_proxy_manager.get(profile_id)
        if existing is not None:
            return existing.safe_assignment()
        client = _require_proxy_client(proxy_client)
        request = payload or ProxyEnsureRequest()
        try:
            lease = await client.purchase_one_day_proxy()
        except ProxyVNError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        assignment = await profile_proxy_manager.assign(profile_id, lease, request.policy)
        return assignment.safe_assignment()

    @app.post("/api/profiles/{profile_id}/proxy/refresh")
    async def refresh_profile_proxy(profile_id: str) -> ProfileProxyAssignment:
        client = _require_proxy_client(proxy_client)
        existing = await profile_proxy_manager.get(profile_id)
        try:
            if existing is None:
                lease = await client.purchase_one_day_proxy()
                policy = ProxyEnsureRequest().policy
            else:
                lease = await client.change_proxy(existing.proxy.idproxy)
                policy = existing.policy
        except ProxyVNError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        assignment = await profile_proxy_manager.assign(profile_id, lease, policy)
        return assignment.safe_assignment()

    @app.post("/api/profiles/{profile_id}/proxy/attach")
    async def attach_existing_profile_proxy(
        profile_id: str,
        payload: ProxyAttachRequest,
    ) -> ProfileProxyAssignment:
        client = _require_proxy_client(proxy_client)
        try:
            leases = await client.list_proxy(str(payload.idproxy))
        except ProxyVNError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        if not leases:
            raise HTTPException(status_code=404, detail=f"Proxy {payload.idproxy} not found")
        assignment = await profile_proxy_manager.assign(profile_id, leases[0], payload.policy)
        return assignment.safe_assignment()

    @app.post("/api/jobs", status_code=status.HTTP_201_CREATED)
    async def create_job(payload: JobCreate) -> JobRecord:
        try:
            site = adapter_for(payload.site_key).spec
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not site.enabled:
            raise HTTPException(status_code=409, detail=f"Site {site.key} is disabled")
        return await repo.create_job(payload)

    @app.get("/api/jobs")
    async def list_jobs() -> list[JobRecord]:
        return await repo.list_jobs()

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str) -> JobRecord:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.get("/api/jobs/{job_id}/events")
    async def get_job_events(job_id: str) -> list[JobEvent]:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return await repo.get_job_events(job_id)

    @app.post("/api/jobs/{job_id}/cancel")
    async def cancel_job(job_id: str) -> JobRecord:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if not can_transition(job.status, JobStatus.CANCELLED):
            raise HTTPException(
                status_code=409,
                detail=f"Cannot cancel a job in status {job.status.value}",
            )
        runner.cancel_checkpoint(job_id)
        try:
            return await repo.update_job_status(
                job_id,
                JobStatus.CANCELLED,
                event_type="job.cancelled",
                message="Job cancelled by operator",
            )
        except InvalidJobTransitionError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/jobs/{job_id}/resume")
    async def resume_job(job_id: str) -> dict[str, str | bool]:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        runner.resume(job_id)
        return {"resumed": True, "job_id": job_id}

    @app.post("/api/jobs/{job_id}/pause")
    async def pause_job(job_id: str) -> dict[str, str | bool]:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status == JobStatus.RUNNING:
            await repo.update_job_status(
                job_id,
                JobStatus.WAITING_HUMAN,
                event_type="job.paused",
                message="Paused by operator",
            )
        return {"paused": True, "job_id": job_id}

    @app.get("/api/jobs/{job_id}/checkpoint")
    async def get_job_checkpoint(job_id: str) -> dict[str, Any]:
        checkpoint = runner.checkpoints.current(job_id)
        if checkpoint is None:
            return {"checkpoint": None}
        return {"checkpoint": {"kind": checkpoint.kind, "message": checkpoint.message}}

    return app


def _check_required(*values: str, names: tuple[str, ...], enabled: bool) -> SecretCheck:
    missing = [name for name, value in zip(names, values, strict=False) if not value]
    return SecretCheck(configured=not missing, enabled=enabled, missing=missing)


def _create_proxyvn_client(settings: Settings) -> ProxyVNClient | None:
    if not settings.proxyvn_api_key:
        return None
    return ProxyVNClient(
        api_key=settings.proxyvn_api_key,
        base_url=settings.proxyvn_base_url,
        loaiproxy=settings.proxyvn_default_loaiproxy,
        default_days=settings.proxyvn_default_days,
        default_type=settings.proxyvn_default_type,
    )


def _require_proxy_client(proxy_client: Any | None) -> Any:
    if proxy_client is None:
        raise HTTPException(status_code=503, detail="PROXYVN_API_KEY is not configured")
    return proxy_client


async def _browser_profile_view(
    profile: BrowserProfile,
    proxy_manager: ProfileProxyManager,
    browser_sessions: BrowserSessionManager,
) -> BrowserProfileView:
    assignment = await proxy_manager.get(profile.id)
    session = await browser_sessions.get_session(profile.id)
    return BrowserProfileView(
        id=profile.id,
        name=profile.name,
        group_id=profile.group_id,
        sim_id=profile.sim_id,
        site_key=profile.site_key,
        runtime=profile.runtime,
        storage_dir=profile.storage_dir,
        status=profile.status,
        fingerprint=profile.fingerprint,
        tags=profile.tags,
        proxy_assigned=assignment is not None,
        proxy=assignment.proxy.masked_proxy if assignment is not None else None,
        session_status=session.status if session is not None else BrowserSessionStatus.IDLE,
    )
