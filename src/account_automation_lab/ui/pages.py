from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import FastAPI

from account_automation_lab.adapters.registry import load_adapters
from account_automation_lab.browser.profiles import (
    BrowserProfileExistsError,
    BrowserProfileStore,
    BrowserSessionError,
    BrowserSessionManager,
)
from account_automation_lab.jobs.state import can_transition
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserSession,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileProxyAssignment,
    ProxyPolicy,
    RuntimeKind,
)
from account_automation_lab.proxy import ProfileProxyManager, ProxyVNError
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import InvalidJobTransitionError
from account_automation_lab.settings import Settings


def _short_id(value: str) -> str:
    return value[:8]


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.strftime("%Y-%m-%d %H:%M:%S UTC")


def _job_rows(jobs: list[JobRecord]) -> list[dict[str, str]]:
    return [
        {
            "id": _short_id(job.id),
            "full_id": job.id,
            "profile": job.profile_id or f"{job.sim_id}:{job.site_key}",
            "site": job.site_key,
            "sim": job.sim_id,
            "runtime": job.runtime.value,
            "status": job.status.value,
            "updated": _format_datetime(job.updated_at),
        }
        for job in sorted(jobs, key=lambda item: item.created_at, reverse=True)
    ]


def _event_rows(events: list[JobEvent]) -> list[dict[str, str]]:
    return [
        {
            "id": event.id,
            "time": _format_datetime(event.created_at),
            "type": event.event_type,
            "message": event.message,
        }
        for event in sorted(events, key=lambda item: item.created_at)
    ]


def _browser_profile_rows(
    profiles: list[BrowserProfile],
    assignments: list[ProfileProxyAssignment],
    sessions: list[BrowserSession],
) -> list[dict[str, str]]:
    proxy_by_profile = {assignment.profile_id: assignment for assignment in assignments}
    session_by_profile = {session.profile_id: session for session in sessions}
    return [
        {
            "id": profile.id,
            "name": profile.name,
            "sim": profile.sim_id,
            "site": profile.site_key,
            "runtime": profile.runtime.value,
            "session": session_by_profile[profile.id].status.value
            if profile.id in session_by_profile
            else "idle",
            "proxy": proxy_by_profile[profile.id].proxy.masked_proxy
            if profile.id in proxy_by_profile
            else "",
            "tags": ", ".join(profile.tags),
        }
        for profile in sorted(profiles, key=lambda item: item.id)
    ]


def _session_rows(sessions: list[BrowserSession]) -> list[dict[str, str]]:
    return [
        {
            "profile_id": session.profile_id,
            "runtime": session.runtime.value,
            "status": session.status.value,
            "started": _format_datetime(session.started_at),
            "url": session.start_url or "",
        }
        for session in sorted(sessions, key=lambda item: item.started_at, reverse=True)
    ]


def _proxy_rows(assignments: list[ProfileProxyAssignment]) -> list[dict[str, str]]:
    return [
        {
            "profile_id": assignment.profile_id,
            "policy": assignment.policy.value,
            "proxy": assignment.proxy.masked_proxy,
            "type": assignment.proxy.type,
            "expires": str(assignment.proxy.expires_at or ""),
        }
        for assignment in sorted(assignments, key=lambda item: item.profile_id)
    ]


def _secret_rows(settings: Settings) -> list[dict[str, str]]:
    checks = [
        (
            "Supabase shared DB",
            settings.database_backend == "supabase",
            {
                "SUPABASE_URL": settings.supabase_url,
                "SUPABASE_SERVICE_ROLE_KEY": settings.supabase_service_role_key,
            },
        ),
        (
            "SIM OTP API",
            True,
            {
                "SIM_OTP_API_BASE_URL": settings.sim_otp_api_base_url,
                "SIM_OTP_API_KEY": settings.sim_otp_api_key,
            },
        ),
        ("ProxyVN", True, {"PROXYVN_API_KEY": settings.proxyvn_api_key}),
        (
            "CAPTCHA provider",
            settings.captcha_provider_enabled,
            {
                "CAPTCHA_PROVIDER_BASE_URL": settings.captcha_provider_base_url,
                "CAPTCHA_PROVIDER_API_KEY": settings.captcha_provider_api_key,
            },
        ),
        ("CloakBrowser", settings.cloakbrowser_enabled, {"CLOAKBROWSER_ENABLED": "true"}),
    ]
    rows: list[dict[str, str]] = []
    for name, enabled, values in checks:
        missing = [key for key, value in values.items() if not value]
        rows.append(
            {
                "name": name,
                "enabled": "yes" if enabled else "no",
                "configured": "yes" if not missing else "no",
                "missing": ", ".join(missing),
            }
        )
    return rows


def mount_ui(app: FastAPI) -> None:
    repo: AutomationRepository = app.state.repository
    settings: Settings = app.state.settings
    proxy_manager: ProfileProxyManager = app.state.proxy_manager
    proxy_client: Any | None = app.state.proxyvn_client
    browser_store: BrowserProfileStore = app.state.browser_profile_store
    browser_sessions: BrowserSessionManager = app.state.browser_session_manager
    site_keys = list(load_adapters())
    default_site_key = site_keys[0] if site_keys else None

    from nicegui import ui

    @ui.page("/")
    async def cockpit() -> None:
        refresh_lock = asyncio.Lock()
        refresh_again = False

        ui.page_title("Account Automation Lab")
        ui.query("body").classes("bg-gray-50 text-gray-900")

        with ui.header().classes("bg-white text-gray-900 border-b border-gray-200"):
            with ui.row().classes("w-full items-center justify-between gap-4 px-4"):
                with ui.column().classes("gap-0"):
                    ui.label("Account Automation Lab").classes("text-xl font-semibold")
                    ui.label("Profile Cockpit").classes("text-xs text-green-700 uppercase")
                ui.button(icon="refresh", on_click=lambda: refresh_all()).props("flat round")

        with ui.tabs().classes("w-full bg-white border-b border-gray-200") as tabs:
            profiles_tab = ui.tab("Profiles")
            sessions_tab = ui.tab("Sessions")
            jobs_tab = ui.tab("Jobs")
            proxies_tab = ui.tab("Proxies")
            sites_tab = ui.tab("Sites")
            settings_tab = ui.tab("Settings")

        metric_labels: dict[str, Any] = {}

        with ui.tab_panels(tabs, value=profiles_tab).classes("w-full bg-gray-50 overflow-x-auto"):
            with ui.tab_panel(profiles_tab):
                with ui.grid(columns=5).classes("w-full gap-3"):
                    for label, key in (
                        ("Profiles", "profiles"),
                        ("Running", "running"),
                        ("Jobs", "jobs"),
                        ("Proxies", "proxies"),
                        ("Missing Secrets", "secrets"),
                    ):
                        with ui.card().classes("rounded-lg shadow-sm"):
                            ui.label(label).classes("text-xs text-gray-500 uppercase")
                            metric_labels[key] = ui.label("0").classes("text-2xl font-semibold")

                ui.label("Browser Profiles").classes("text-xl font-semibold")
                browser_profiles_table = ui.table(
                    columns=[
                        {"name": "id", "label": "Profile", "field": "id"},
                        {"name": "name", "label": "Name", "field": "name"},
                        {"name": "sim", "label": "SIM", "field": "sim"},
                        {"name": "site", "label": "Site", "field": "site"},
                        {"name": "runtime", "label": "Runtime", "field": "runtime"},
                        {"name": "session", "label": "Session", "field": "session"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy"},
                        {"name": "tags", "label": "Tags", "field": "tags"},
                    ],
                    rows=[],
                    row_key="id",
                ).classes("w-full min-w-max whitespace-normal break-words")

                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    selected_profile = ui.select({}, label="Profile").classes("min-w-96")
                    ui.button(
                        "Open",
                        icon="play_arrow",
                        on_click=lambda: open_profile(str(selected_profile.value or "")),
                    )
                    ui.button(
                        "Stop",
                        icon="stop",
                        on_click=lambda: close_profile(str(selected_profile.value or "")),
                    )
                    ui.button(
                        "Run Signup",
                        icon="smart_toy",
                        on_click=lambda: run_signup(str(selected_profile.value or "")),
                    )

                ui.separator()
                ui.label("Create Profile").classes("text-lg font-semibold")
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    create_sim = ui.input("SIM ID", value="sim-a").classes("w-48")
                    create_site = ui.select(
                        site_keys,
                        value=default_site_key,
                        label="Site",
                    ).classes("w-48")
                    create_name = ui.input("Name").classes("w-64")
                    create_tags = ui.input("Tags").classes("w-64")
                    ui.button(
                        "Create",
                        icon="add",
                        on_click=lambda: create_profile(
                            str(create_sim.value or ""),
                            str(create_site.value or ""),
                            str(create_name.value or ""),
                            str(create_tags.value or ""),
                        ),
                    )

            with ui.tab_panel(sessions_tab):
                ui.label("Active Browser Sessions").classes("text-xl font-semibold")
                sessions_table = ui.table(
                    columns=[
                        {"name": "profile_id", "label": "Profile", "field": "profile_id"},
                        {"name": "runtime", "label": "Runtime", "field": "runtime"},
                        {"name": "status", "label": "Status", "field": "status"},
                        {"name": "started", "label": "Started", "field": "started"},
                        {"name": "url", "label": "URL", "field": "url"},
                    ],
                    rows=[],
                    row_key="profile_id",
                ).classes("w-full min-w-max whitespace-normal break-words")

            with ui.tab_panel(jobs_tab):
                ui.label("Jobs").classes("text-xl font-semibold")
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    job_site_select = ui.select(
                        site_keys,
                        value=default_site_key,
                        label="Site",
                    ).classes("w-48")
                    job_sim_input = ui.input("SIM ID", value="sim-a").classes("w-48")
                    job_runtime_select = ui.select(
                        [item.value for item in RuntimeKind],
                        value=RuntimeKind.CLOAKBROWSER.value,
                        label="Runtime",
                    ).classes("w-64")
                    ui.button(
                        "Queue Job",
                        icon="add_task",
                        on_click=lambda: queue_job(
                            str(job_site_select.value or ""),
                            str(job_sim_input.value or ""),
                            str(job_runtime_select.value or RuntimeKind.CLOAKBROWSER.value),
                            None,
                        ),
                    )

                jobs_table = ui.table(
                    columns=[
                        {"name": "id", "label": "Job", "field": "id"},
                        {"name": "profile", "label": "Profile", "field": "profile"},
                        {"name": "site", "label": "Site", "field": "site"},
                        {"name": "sim", "label": "SIM", "field": "sim"},
                        {"name": "runtime", "label": "Runtime", "field": "runtime"},
                        {"name": "status", "label": "Status", "field": "status"},
                        {"name": "updated", "label": "Updated", "field": "updated"},
                    ],
                    rows=[],
                    row_key="id",
                ).classes("w-full min-w-max whitespace-normal break-words")
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    job_select = ui.select({}, label="Job").classes("min-w-96")
                    ui.button("Load Events", icon="article", on_click=lambda: refresh_events())
                    ui.button(
                        "Cancel Job",
                        icon="cancel",
                        on_click=lambda: cancel_job(str(job_select.value or "")),
                    ).props("color=negative")
                events_table = ui.table(
                    columns=[
                        {"name": "id", "label": "Event", "field": "id"},
                        {"name": "time", "label": "Time", "field": "time"},
                        {"name": "type", "label": "Type", "field": "type"},
                        {"name": "message", "label": "Message", "field": "message"},
                    ],
                    rows=[],
                    row_key="id",
                ).classes("w-full min-w-max whitespace-normal break-words")

            with ui.tab_panel(proxies_tab):
                ui.label("Profile Proxy Map").classes("text-xl font-semibold")
                proxy_table = ui.table(
                    columns=[
                        {"name": "profile_id", "label": "Profile", "field": "profile_id"},
                        {"name": "policy", "label": "Policy", "field": "policy"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy"},
                        {"name": "type", "label": "Type", "field": "type"},
                        {"name": "expires", "label": "Expires", "field": "expires"},
                    ],
                    rows=[],
                    row_key="profile_id",
                ).classes("w-full min-w-max whitespace-normal break-words")
                with ui.row().classes("w-full items-end gap-3 flex-wrap"):
                    proxy_profile_input = ui.input("Profile ID", value="sim-a:site_01").classes(
                        "w-72"
                    )
                    idproxy_input = ui.number("Existing idproxy", value=308, min=1).classes("w-48")
                    ui.button(
                        "Attach",
                        icon="link",
                        on_click=lambda: attach_proxy(
                            str(proxy_profile_input.value or ""),
                            idproxy_input.value,
                        ),
                    )
                    ui.button(
                        "Buy 1-day",
                        icon="add_shopping_cart",
                        on_click=lambda: ensure_proxy(str(proxy_profile_input.value or "")),
                    )
                    ui.button(
                        "Rotate",
                        icon="sync",
                        on_click=lambda: refresh_proxy(str(proxy_profile_input.value or "")),
                    )

            with ui.tab_panel(sites_tab):
                ui.label("Sites").classes("text-xl font-semibold")
                ui.table(
                    columns=[
                        {"name": "key", "label": "Key", "field": "key"},
                        {"name": "name", "label": "Name", "field": "name"},
                        {"name": "captcha", "label": "CAPTCHA", "field": "captcha"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy"},
                    ],
                    rows=[
                        {
                            "key": adapter.spec.key,
                            "name": adapter.spec.display_name,
                            "captcha": adapter.spec.captcha_mode.value,
                            "proxy": adapter.spec.proxy_policy.value,
                        }
                        for adapter in load_adapters().values()
                    ],
                    row_key="key",
                ).classes("w-full min-w-max whitespace-normal break-words")

            with ui.tab_panel(settings_tab):
                ui.label("Secrets Health").classes("text-xl font-semibold")
                secrets_table = ui.table(
                    columns=[
                        {"name": "name", "label": "Name", "field": "name"},
                        {"name": "enabled", "label": "Enabled", "field": "enabled"},
                        {"name": "configured", "label": "Configured", "field": "configured"},
                        {"name": "missing", "label": "Missing", "field": "missing"},
                    ],
                    rows=[],
                    row_key="name",
                ).classes("w-full min-w-max whitespace-normal break-words")

        async def refresh_browser_profiles() -> None:
            profiles = await browser_store.list_profiles()
            assignments = await proxy_manager.list_assignments()
            sessions = await browser_sessions.list_sessions()
            rows = _browser_profile_rows(profiles, assignments, sessions)
            browser_profiles_table.rows = rows
            browser_profiles_table.update()
            selected_profile.options = {
                row["id"]: f'{row["id"]} | {row["session"]} | {row["site"]}' for row in rows
            }
            if rows and selected_profile.value not in selected_profile.options:
                selected_profile.value = rows[0]["id"]
            if not rows:
                selected_profile.value = None
            selected_profile.update()
            metric_labels["profiles"].text = str(len(rows))
            metric_labels["running"].text = str(sum(1 for row in rows if row["session"] != "idle"))

        async def refresh_sessions() -> None:
            sessions = await browser_sessions.list_sessions()
            sessions_table.rows = _session_rows(sessions)
            sessions_table.update()

        async def refresh_jobs() -> list[JobRecord]:
            jobs = await repo.list_jobs()
            rows = _job_rows(jobs)
            jobs_table.rows = rows
            jobs_table.update()
            job_select.options = {
                row["full_id"]: f'{row["id"]} | {row["site"]} | {row["status"]}'
                for row in rows
            }
            if rows and job_select.value not in job_select.options:
                job_select.value = rows[0]["full_id"]
            if not rows:
                job_select.value = None
            job_select.update()
            metric_labels["jobs"].text = str(len(jobs))
            return jobs

        async def refresh_events() -> None:
            if not job_select.value:
                events_table.rows = []
                events_table.update()
                return
            events = await repo.get_job_events(str(job_select.value))
            events_table.rows = _event_rows(events)
            events_table.update()

        async def refresh_proxies() -> None:
            assignments = await proxy_manager.list_assignments()
            proxy_table.rows = _proxy_rows(assignments)
            proxy_table.update()
            metric_labels["proxies"].text = str(len(assignments))

        async def refresh_secrets() -> None:
            rows = _secret_rows(settings)
            secrets_table.rows = rows
            secrets_table.update()
            metric_labels["secrets"].text = str(
                sum(1 for row in rows if row["enabled"] == "yes" and row["configured"] == "no")
            )

        async def refresh_all() -> None:
            nonlocal refresh_again
            if refresh_lock.locked():
                refresh_again = True
                return
            async with refresh_lock:
                while True:
                    refresh_again = False
                    await refresh_browser_profiles()
                    await refresh_sessions()
                    await refresh_jobs()
                    await refresh_events()
                    await refresh_proxies()
                    await refresh_secrets()
                    if not refresh_again:
                        return

        async def profile_exists(profile_id: str) -> bool:
            if not profile_id:
                ui.notify("Profile ID is required", color="negative")
                return False
            if await browser_store.get_profile(profile_id) is None:
                ui.notify("Browser profile not found", color="negative")
                await refresh_browser_profiles()
                await refresh_proxies()
                return False
            return True

        async def create_profile(sim_id: str, site_key: str, name: str, tags: str) -> None:
            if not sim_id or not site_key:
                ui.notify("SIM and site are required", color="negative")
                return
            try:
                profile = await browser_store.create_profile(
                    BrowserProfileCreate(
                        name=name or None,
                        sim_id=sim_id,
                        site_key=site_key,
                        tags=[tag.strip() for tag in tags.split(",") if tag.strip()],
                    )
                )
            except BrowserProfileExistsError as exc:
                ui.notify(str(exc), color="negative")
                return
            ui.notify(f"Created profile {profile.id}", color="positive")
            await refresh_all()

        async def open_profile(profile_id: str) -> None:
            if not profile_id:
                ui.notify("Select a profile first", color="negative")
                return
            try:
                session = await browser_sessions.open_profile(profile_id)
            except KeyError:
                ui.notify("Browser profile not found", color="negative")
                await refresh_browser_profiles()
                return
            except BrowserSessionError:
                ui.notify("Could not open profile due to a browser session error", color="negative")
                await refresh_sessions()
                await refresh_browser_profiles()
                return
            except Exception:
                ui.notify("Could not open profile", color="negative")
                await refresh_sessions()
                await refresh_browser_profiles()
                return
            ui.notify(f"Opened {session.profile_id}", color="positive")
            await refresh_all()

        async def close_profile(profile_id: str) -> None:
            if not profile_id:
                ui.notify("Select a profile first", color="negative")
                return
            try:
                await browser_sessions.close_profile(profile_id)
            except KeyError:
                ui.notify("Browser session not running", color="info")
                await refresh_sessions()
                await refresh_browser_profiles()
                return
            ui.notify(f"Stopped {profile_id}", color="positive")
            await refresh_all()

        async def run_signup(profile_id: str) -> None:
            profile = await browser_store.get_profile(profile_id)
            if profile is None:
                ui.notify("Browser profile not found", color="negative")
                await refresh_browser_profiles()
                return
            await queue_job(profile.site_key, profile.sim_id, profile.runtime.value, profile.id)

        async def queue_job(
            site_key: str,
            sim_id: str,
            runtime: str,
            profile_id: str | None,
        ) -> None:
            if not site_key or not sim_id:
                ui.notify("Site and SIM are required", color="negative")
                return
            record = await repo.create_job(
                JobCreate(
                    site_key=site_key,
                    sim_id=sim_id,
                    runtime=RuntimeKind(runtime),
                    profile_id=profile_id,
                )
            )
            ui.notify(f"Queued job {_short_id(record.id)}", color="positive")
            await refresh_all()

        async def cancel_job(job_id: str) -> None:
            if not job_id:
                ui.notify("Select a job first", color="negative")
                return
            job = await repo.get_job(job_id)
            if job is None:
                ui.notify("Job not found", color="negative")
                await refresh_all()
                return
            if not can_transition(job.status, JobStatus.CANCELLED):
                ui.notify(
                    f"Cannot cancel a {job.status.value} job",
                    color="warning",
                )
                return
            try:
                await repo.update_job_status(
                    job_id,
                    JobStatus.CANCELLED,
                    event_type="job.cancelled",
                    message="Job cancelled by operator",
                )
            except InvalidJobTransitionError:
                ui.notify("Job can no longer be cancelled", color="warning")
                await refresh_all()
                return
            ui.notify(f"Cancelled job {_short_id(job_id)}", color="positive")
            await refresh_all()

        async def attach_proxy(profile_id: str, idproxy_value: float | int | None) -> None:
            if proxy_client is None:
                ui.notify("PROXYVN_API_KEY is not configured", color="negative")
                return
            if not profile_id or not idproxy_value:
                ui.notify("Profile ID and idproxy are required", color="negative")
                return
            if not await profile_exists(profile_id):
                return
            try:
                leases = await proxy_client.list_proxy(str(int(idproxy_value)))
            except ProxyVNError as exc:
                ui.notify(str(exc), color="negative")
                return
            if not leases:
                ui.notify("Proxy not found", color="negative")
                return
            await proxy_manager.assign(profile_id, leases[0], ProxyPolicy.STICKY_PROFILE)
            ui.notify(f"Attached proxy to {profile_id}", color="positive")
            await refresh_all()

        async def ensure_proxy(profile_id: str) -> None:
            if proxy_client is None:
                ui.notify("PROXYVN_API_KEY is not configured", color="negative")
                return
            if not profile_id:
                ui.notify("Profile ID is required", color="negative")
                return
            if not await profile_exists(profile_id):
                return
            existing = await proxy_manager.get(profile_id)
            if existing is not None:
                ui.notify(f"Proxy already assigned to {profile_id}", color="info")
                await refresh_all()
                return
            try:
                lease = await proxy_client.purchase_one_day_proxy()
            except ProxyVNError as exc:
                ui.notify(str(exc), color="negative")
                return
            await proxy_manager.assign(profile_id, lease, ProxyPolicy.STICKY_PROFILE)
            ui.notify(f"Bought and attached proxy to {profile_id}", color="positive")
            await refresh_all()

        async def refresh_proxy(profile_id: str) -> None:
            if proxy_client is None:
                ui.notify("PROXYVN_API_KEY is not configured", color="negative")
                return
            if not profile_id:
                ui.notify("Profile ID is required", color="negative")
                return
            if not await profile_exists(profile_id):
                return
            existing = await proxy_manager.get(profile_id)
            try:
                lease = (
                    await proxy_client.change_proxy(existing.proxy.idproxy)
                    if existing is not None
                    else await proxy_client.purchase_one_day_proxy()
                )
            except ProxyVNError as exc:
                ui.notify(str(exc), color="negative")
                return
            await proxy_manager.assign(profile_id, lease, ProxyPolicy.STICKY_PROFILE)
            ui.notify(f"Proxy updated for {profile_id}", color="positive")
            await refresh_all()

        await refresh_all()
        ui.timer(3.0, refresh_all)
