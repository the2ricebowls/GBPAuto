from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import FastAPI

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
    BrowserSession,
    CaptchaMode,
    FingerprintConfig,
    FingerprintPlatform,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileProxyAssignment,
    ProxyPolicy,
    RuntimeKind,
    SiteCreate,
    SiteSpec,
    SiteUpdate,
)
from account_automation_lab.proxy import ProfileProxyManager, ProxyVNError
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import InvalidJobTransitionError, SiteExistsError
from account_automation_lab.settings import Settings

# --------------------------------------------------------------------------- #
# Industrial console theme.
# Pitch-black surfaces, monospace throughout, flat 1px borders, tabular
# numerics, one accent (acid lime) plus semantic status colors.
# --------------------------------------------------------------------------- #

ACCENT = "#C6FF4A"
SIGNAL_GREEN = "#00E676"
SIGNAL_AMBER = "#FFB800"
SIGNAL_ORANGE = "#FF9F1C"
SIGNAL_RED = "#FF5247"
MUTED = "#8A8F84"

_THEME_HEAD = (
    '<link rel="preconnect" href="https://fonts.googleapis.com">'
    '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
    '<link href="https://fonts.googleapis.com/css2?'
    "family=JetBrains+Mono:wght@400;500;700&display=swap"
    '" rel="stylesheet">'
)

_THEME_CSS = """
<style>
:root {
  --aal-bg: #0B0C0A;
  --aal-panel: #131512;
  --aal-panel-2: #1A1D18;
  --aal-border: #2A2E29;
  --aal-text: #E6E8E3;
  --aal-muted: #8A8F84;
  --aal-accent: #C6FF4A;
}
html, body, .q-page-container, .nicegui-content {
  background: var(--aal-bg) !important;
  color: var(--aal-text) !important;
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}
.q-tab, .q-item, .q-btn, input, textarea, .q-field, label {
  font-family: 'JetBrains Mono', ui-monospace, monospace !important;
}
.aal-brand { color: var(--aal-accent); letter-spacing: 0.04em; }
.aal-sub { color: var(--aal-muted); letter-spacing: 0.18em; }
.aal-panel {
  background: var(--aal-panel);
  border: 1px solid var(--aal-border);
  border-radius: 2px;
}
.aal-stat {
  background: var(--aal-panel);
  border: 1px solid var(--aal-border);
  border-left: 2px solid var(--aal-accent);
  border-radius: 2px;
  padding: 10px 14px;
}
.aal-stat-label { color: var(--aal-muted); font-size: 10px; letter-spacing: 0.18em; }
.aal-stat-value { font-size: 26px; font-weight: 700; font-variant-numeric: tabular-nums; }
.aal-section { color: var(--aal-text); font-size: 13px; letter-spacing: 0.14em; }
.aal-hint { color: var(--aal-muted); font-size: 11px; }
/* Tables */
.q-table__container, .q-table {
  background: var(--aal-panel) !important;
  color: var(--aal-text) !important;
  border: 1px solid var(--aal-border);
  border-radius: 2px;
}
.q-table thead th {
  color: var(--aal-muted) !important;
  font-size: 10px;
  letter-spacing: 0.12em;
  text-transform: uppercase;
  border-bottom: 1px solid var(--aal-border) !important;
}
.q-table tbody td {
  border-bottom: 1px solid rgba(42,46,41,0.6) !important;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}
.q-table tbody tr:hover { background: var(--aal-panel-2) !important; }
/* Drawer nav */
.aal-nav .q-tab { justify-content: flex-start; min-height: 44px; color: var(--aal-muted); }
.aal-nav .q-tab--active { color: var(--aal-accent); }
.aal-nav .q-tab__indicator { background: var(--aal-accent); }
/* Scrollbar */
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: #2A2E29; border-radius: 0; }
::-webkit-scrollbar-track { background: #0B0C0A; }
</style>
"""

_STATUS_COLORS = {
    "queued": SIGNAL_AMBER,
    "running": SIGNAL_GREEN,
    "waiting_captcha": SIGNAL_ORANGE,
    "waiting_human": SIGNAL_ORANGE,
    "succeeded": SIGNAL_GREEN,
    "failed": SIGNAL_RED,
    "cancelled": MUTED,
}


def _status_color(status: str) -> str:
    return _STATUS_COLORS.get(status, MUTED)


def _session_color(session: str) -> str:
    return SIGNAL_GREEN if session and session != "idle" else MUTED


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
            "status_color": _status_color(job.status.value),
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
            "sim": profile.sim_id or "",
            "site": profile.site_key or "",
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


def _profile_manager_rows(
    *,
    profiles: list[BrowserProfile],
    groups: dict[str, str],
    assignments: list[ProfileProxyAssignment],
    sessions: list[BrowserSession],
) -> list[dict[str, str]]:
    proxy_by_profile = {a.profile_id: a for a in assignments}
    session_by_profile = {s.profile_id: s for s in sessions}
    rows: list[dict[str, str]] = []
    for profile in sorted(profiles, key=lambda p: p.name.lower()):
        session = session_by_profile.get(profile.id)
        assignment = proxy_by_profile.get(profile.id)
        session_value = session.status.value if session is not None else "idle"
        rows.append(
            {
                "id": profile.id,
                "name": profile.name,
                "group": groups.get(profile.group_id, "") if profile.group_id else "",
                "tags": ", ".join(profile.tags),
                "status": profile.status.value,
                "session": session_value,
                "session_color": _session_color(session_value),
                "proxy": assignment.proxy.masked_proxy if assignment is not None else "",
                "timezone": profile.fingerprint.timezone or "",
                "sim": profile.sim_id or "",
            }
        )
    return rows


def _group_filter_options(groups: list[ProfileGroup]) -> dict[str, str]:
    options = {"__all__": "All profiles", "__none__": "Ungrouped"}
    for group in sorted(groups, key=lambda g: g.name.lower()):
        options[group.id] = group.name
    return options


def _session_rows(sessions: list[BrowserSession]) -> list[dict[str, str]]:
    return [
        {
            "profile_id": session.profile_id,
            "runtime": session.runtime.value,
            "status": session.status.value,
            "status_color": _status_color(session.status.value),
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


def _site_rows(sites: list[SiteSpec]) -> list[dict[str, str]]:
    return [
        {
            "key": site.key,
            "name": site.display_name,
            "base_url": site.base_url,
            "captcha": site.captcha_mode.value,
            "proxy": site.proxy_policy.value,
            "adapter": "code" if site.has_code_adapter else "data",
            "adapter_color": ACCENT if site.has_code_adapter else MUTED,
            "enabled": "yes" if site.enabled else "no",
            "enabled_color": SIGNAL_GREEN if site.enabled else MUTED,
            "hints": ", ".join(site.otp_sender_hints),
        }
        for site in sorted(sites, key=lambda item: item.key)
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
                "configured_color": SIGNAL_RED if (enabled and missing) else SIGNAL_GREEN,
                "missing": ", ".join(missing),
            }
        )
    return rows


def mount_ui(app: FastAPI) -> None:
    repo: AutomationRepository = app.state.repository
    settings: Settings = app.state.settings
    runner: JobRunner = app.state.runner
    proxy_manager: ProfileProxyManager = app.state.proxy_manager
    proxy_client: Any | None = app.state.proxyvn_client
    browser_store: BrowserProfileStore = app.state.browser_profile_store
    browser_sessions: BrowserSessionManager = app.state.browser_session_manager

    from nicegui import ui

    @ui.page("/")
    async def cockpit() -> None:
        ui.add_head_html(_THEME_HEAD + _THEME_CSS)
        refresh_lock = asyncio.Lock()
        refresh_again = False
        editing_profile: dict[str, str] = {"id": ""}
        editing_site: dict[str, str] = {"key": ""}

        ui.page_title("Account Automation Lab")

        # ---- Header ---------------------------------------------------- #
        with ui.header().classes("items-center justify-between px-5 py-2").style(
            "background:#0B0C0A; border-bottom:1px solid #2A2E29;"
        ):
            with ui.row().classes("items-center gap-3"):
                ui.icon("hub").style(f"color:{ACCENT}")
                with ui.column().classes("gap-0"):
                    ui.label("ACCOUNT AUTOMATION LAB").classes("text-base font-bold aal-brand")
                    ui.label("PROFILE / SITE / WORKFLOW CONTROL").classes("text-[10px] aal-sub")
            with ui.row().classes("items-center gap-3"):
                backend_chip = ui.label("").classes("text-[11px]").style(f"color:{MUTED}")
                ui.button(icon="refresh", on_click=lambda: refresh_all()).props(
                    "flat round dense"
                ).style(f"color:{ACCENT}")

        # ---- Left nav drawer ------------------------------------------- #
        with ui.left_drawer(bordered=False).classes("aal-nav p-0").style(
            "background:#0B0C0A; border-right:1px solid #2A2E29; width:208px;"
        ):
            with ui.tabs().props("vertical").classes("w-full aal-nav") as tabs:
                profiles_tab = ui.tab("Profiles", icon="badge")
                sessions_tab = ui.tab("Sessions", icon="dvr")
                jobs_tab = ui.tab("Jobs", icon="bolt")
                sites_tab = ui.tab("Sites", icon="public")
                proxies_tab = ui.tab("Proxies", icon="vpn_lock")
                settings_tab = ui.tab("Settings", icon="tune")

        metric_labels: dict[str, Any] = {}

        with ui.tab_panels(tabs, value=profiles_tab).classes("w-full").style(
            "background:#0B0C0A;"
        ):
            # ====================== PROFILES =========================== #
            with ui.tab_panel(profiles_tab).classes("p-4"):
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    for label, key in (
                        ("PROFILES", "profiles"),
                        ("SESSIONS LIVE", "running"),
                        ("JOBS", "jobs"),
                        ("PROXIES", "proxies"),
                        ("SECRETS MISSING", "secrets"),
                    ):
                        with ui.element("div").classes("aal-stat grow"):
                            ui.label(label).classes("aal-stat-label")
                            metric_labels[key] = ui.label("0").classes("aal-stat-value").style(
                                f"color:{ACCENT}"
                            )

                with ui.row().classes("w-full items-center justify-between mt-4"):
                    ui.label("PROFILE MANAGER").classes("aal-section")
                    ui.button(
                        "New profile", icon="add", on_click=lambda: open_profile_dialog("")
                    ).props("dense").style(f"background:{ACCENT}; color:#0B0C0A;")

                with ui.row().classes("w-full items-end gap-3 flex-wrap mt-2"):
                    group_filter = ui.select(
                        _group_filter_options([]),
                        value="__all__",
                        label="Group",
                        on_change=lambda: refresh_browser_profiles(),
                    ).props("dark dense outlined").classes("w-52")
                    new_group_input = ui.input("New group").props("dark dense outlined").classes(
                        "w-44"
                    )
                    ui.button(
                        "Add", icon="create_new_folder",
                        on_click=lambda: create_group(str(new_group_input.value or "")),
                    ).props("flat dense").style(f"color:{ACCENT}")
                    ui.button(
                        "Del group", icon="folder_delete",
                        on_click=lambda: delete_group(str(group_filter.value or "")),
                    ).props("flat dense").style(f"color:{SIGNAL_RED}")

                browser_profiles_table = ui.table(
                    columns=[
                        {"name": "name", "label": "Name", "field": "name", "align": "left"},
                        {"name": "group", "label": "Group", "field": "group", "align": "left"},
                        {"name": "tags", "label": "Tags", "field": "tags", "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "session", "label": "Session", "field": "session",
                         "align": "left"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy", "align": "left"},
                        {"name": "timezone", "label": "TZ", "field": "timezone", "align": "left"},
                        {"name": "sim", "label": "SIM", "field": "sim", "align": "left"},
                    ],
                    rows=[],
                    row_key="id",
                ).props("dark flat dense").classes("w-full mt-2")
                browser_profiles_table.add_slot(
                    "body-cell-session",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.session_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )

                with ui.row().classes("w-full items-end gap-2 flex-wrap mt-2"):
                    selected_profile = ui.select({}, label="Selected profile").props(
                        "dark dense outlined"
                    ).classes("grow")
                    ui.button("Open", icon="play_arrow",
                              on_click=lambda: open_profile(str(selected_profile.value or ""))
                              ).props("dense").style(f"background:{SIGNAL_GREEN}; color:#0B0C0A;")
                    ui.button("Stop", icon="stop",
                              on_click=lambda: close_profile(str(selected_profile.value or ""))
                              ).props("outline dense").style(f"color:{MUTED}")
                    ui.button("Run", icon="smart_toy",
                              on_click=lambda: run_signup(str(selected_profile.value or ""))
                              ).props("dense").style(f"background:{ACCENT}; color:#0B0C0A;")
                    ui.button("Edit", icon="edit",
                              on_click=lambda: open_profile_dialog(
                                  str(selected_profile.value or ""))
                              ).props("outline dense").style(f"color:{ACCENT}")
                    ui.button("Delete", icon="delete",
                              on_click=lambda: delete_profile_ui(str(selected_profile.value or ""))
                              ).props("flat dense").style(f"color:{SIGNAL_RED}")

            # ====================== SESSIONS =========================== #
            with ui.tab_panel(sessions_tab).classes("p-4"):
                ui.label("ACTIVE BROWSER SESSIONS").classes("aal-section")
                sessions_table = ui.table(
                    columns=[
                        {"name": "profile_id", "label": "Profile", "field": "profile_id",
                         "align": "left"},
                        {"name": "runtime", "label": "Runtime", "field": "runtime",
                         "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "started", "label": "Started", "field": "started",
                         "align": "left"},
                        {"name": "url", "label": "URL", "field": "url", "align": "left"},
                    ],
                    rows=[],
                    row_key="profile_id",
                ).props("dark flat dense").classes("w-full mt-2")
                sessions_table.add_slot(
                    "body-cell-status",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.status_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )

            # ======================== JOBS ============================= #
            with ui.tab_panel(jobs_tab).classes("p-4"):
                ui.label("QUEUE A JOB").classes("aal-section")
                with ui.row().classes("w-full items-end gap-3 flex-wrap mt-2"):
                    job_site_select = ui.select({}, label="Site").props(
                        "dark dense outlined"
                    ).classes("w-52")
                    job_sim_input = ui.input("SIM ID", value="sim-a").props(
                        "dark dense outlined"
                    ).classes("w-40")
                    job_runtime_select = ui.select(
                        [item.value for item in RuntimeKind],
                        value=RuntimeKind.CLOAKBROWSER.value,
                        label="Runtime",
                    ).props("dark dense outlined").classes("w-56")
                    ui.button(
                        "Queue", icon="add_task",
                        on_click=lambda: queue_job(
                            str(job_site_select.value or ""),
                            str(job_sim_input.value or ""),
                            str(job_runtime_select.value or RuntimeKind.CLOAKBROWSER.value),
                            None,
                        ),
                    ).props("dense").style(f"background:{ACCENT}; color:#0B0C0A;")

                ui.label("JOBS").classes("aal-section mt-4")
                jobs_table = ui.table(
                    columns=[
                        {"name": "id", "label": "Job", "field": "id", "align": "left"},
                        {"name": "profile", "label": "Profile", "field": "profile",
                         "align": "left"},
                        {"name": "site", "label": "Site", "field": "site", "align": "left"},
                        {"name": "sim", "label": "SIM", "field": "sim", "align": "left"},
                        {"name": "runtime", "label": "Runtime", "field": "runtime",
                         "align": "left"},
                        {"name": "status", "label": "Status", "field": "status", "align": "left"},
                        {"name": "updated", "label": "Updated", "field": "updated",
                         "align": "left"},
                    ],
                    rows=[],
                    row_key="id",
                ).props("dark flat dense").classes("w-full mt-2")
                jobs_table.add_slot(
                    "body-cell-status",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.status_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )
                with ui.row().classes("w-full items-end gap-2 flex-wrap mt-2"):
                    job_select = ui.select({}, label="Selected job").props(
                        "dark dense outlined"
                    ).classes("grow")
                    ui.button("Events", icon="article",
                              on_click=lambda: refresh_events()).props("outline dense").style(
                        f"color:{ACCENT}"
                    )
                    ui.button("Resume", icon="play_arrow",
                              on_click=lambda: resume_job_ui(str(job_select.value or ""))
                              ).props("dense").style(f"background:{SIGNAL_GREEN}; color:#0B0C0A;")
                    ui.button("Pause", icon="pause",
                              on_click=lambda: pause_job_ui(str(job_select.value or ""))
                              ).props("outline dense").style(f"color:{SIGNAL_AMBER}")
                    ui.button("Cancel", icon="cancel",
                              on_click=lambda: cancel_job(str(job_select.value or ""))
                              ).props("flat dense").style(f"color:{SIGNAL_RED}")
                events_table = ui.table(
                    columns=[
                        {"name": "time", "label": "Time", "field": "time", "align": "left"},
                        {"name": "type", "label": "Type", "field": "type", "align": "left"},
                        {"name": "message", "label": "Message", "field": "message",
                         "align": "left"},
                    ],
                    rows=[],
                    row_key="id",
                ).props("dark flat dense").classes("w-full mt-2")

            # ======================== SITES ============================ #
            with ui.tab_panel(sites_tab).classes("p-4"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("SITES").classes("aal-section")
                    ui.button("New site", icon="add",
                              on_click=lambda: open_site_dialog("")).props("dense").style(
                        f"background:{ACCENT}; color:#0B0C0A;"
                    )
                ui.label(
                    "Sites with a code adapter run their bespoke workflow. Data-only sites "
                    "open the URL and wait for you to drive the signup by hand."
                ).classes("aal-hint mt-1")
                sites_table = ui.table(
                    columns=[
                        {"name": "key", "label": "Key", "field": "key", "align": "left"},
                        {"name": "name", "label": "Name", "field": "name", "align": "left"},
                        {"name": "base_url", "label": "URL", "field": "base_url", "align": "left"},
                        {"name": "adapter", "label": "Adapter", "field": "adapter",
                         "align": "left"},
                        {"name": "captcha", "label": "CAPTCHA", "field": "captcha",
                         "align": "left"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy", "align": "left"},
                        {"name": "enabled", "label": "Enabled", "field": "enabled",
                         "align": "left"},
                        {"name": "actions", "label": "", "field": "actions", "align": "right"},
                    ],
                    rows=[],
                    row_key="key",
                ).props("dark flat dense").classes("w-full mt-2")
                sites_table.add_slot(
                    "body-cell-adapter",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.adapter_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )
                sites_table.add_slot(
                    "body-cell-enabled",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.enabled_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )
                sites_table.add_slot(
                    "body-cell-actions",
                    r'''
                    <q-td :props="props" class="text-right">
                      <q-btn dense flat icon="edit" color="lime"
                        @click="() => $parent.$emit('edit_site', props.row.key)" />
                      <q-btn dense flat icon="delete" color="red"
                        @click="() => $parent.$emit('del_site', props.row.key)" />
                    </q-td>
                    ''',
                )
                sites_table.on("edit_site", lambda e: open_site_dialog(str(e.args)))
                sites_table.on("del_site", lambda e: delete_site_ui(str(e.args)))

            # ======================= PROXIES =========================== #
            with ui.tab_panel(proxies_tab).classes("p-4"):
                ui.label("PROFILE PROXY MAP").classes("aal-section")
                proxy_table = ui.table(
                    columns=[
                        {"name": "profile_id", "label": "Profile", "field": "profile_id",
                         "align": "left"},
                        {"name": "policy", "label": "Policy", "field": "policy", "align": "left"},
                        {"name": "proxy", "label": "Proxy", "field": "proxy", "align": "left"},
                        {"name": "type", "label": "Type", "field": "type", "align": "left"},
                        {"name": "expires", "label": "Expires", "field": "expires",
                         "align": "left"},
                    ],
                    rows=[],
                    row_key="profile_id",
                ).props("dark flat dense").classes("w-full mt-2")
                ui.label("PROXY ACTIONS").classes("aal-section mt-4")
                with ui.row().classes("w-full items-end gap-3 flex-wrap mt-2"):
                    proxy_profile_input = ui.input("Profile ID").props(
                        "dark dense outlined"
                    ).classes("grow")
                    idproxy_input = ui.number("Existing idproxy", value=308, min=1).props(
                        "dark dense outlined"
                    ).classes("w-44")
                    ui.button("Attach", icon="link",
                              on_click=lambda: attach_proxy(
                                  str(proxy_profile_input.value or ""), idproxy_input.value)
                              ).props("outline dense").style(f"color:{ACCENT}")
                    ui.button("Buy 1-day", icon="add_shopping_cart",
                              on_click=lambda: ensure_proxy(str(proxy_profile_input.value or ""))
                              ).props("dense").style(f"background:{ACCENT}; color:#0B0C0A;")
                    ui.button("Rotate", icon="sync",
                              on_click=lambda: refresh_proxy(str(proxy_profile_input.value or ""))
                              ).props("outline dense").style(f"color:{SIGNAL_AMBER}")

            # ====================== SETTINGS =========================== #
            with ui.tab_panel(settings_tab).classes("p-4"):
                ui.label("SECRETS HEALTH").classes("aal-section")
                ui.label("Secret values are never shown; only presence is reported.").classes(
                    "aal-hint mt-1"
                )
                secrets_table = ui.table(
                    columns=[
                        {"name": "name", "label": "Service", "field": "name", "align": "left"},
                        {"name": "enabled", "label": "Enabled", "field": "enabled",
                         "align": "left"},
                        {"name": "configured", "label": "Configured", "field": "configured",
                         "align": "left"},
                        {"name": "missing", "label": "Missing keys", "field": "missing",
                         "align": "left"},
                    ],
                    rows=[],
                    row_key="name",
                ).props("dark flat dense").classes("w-full mt-2")
                secrets_table.add_slot(
                    "body-cell-configured",
                    r'''
                    <q-td :props="props">
                      <span :style="`color:${props.row.configured_color}`">{{ props.value }}</span>
                    </q-td>
                    ''',
                )


        # ---- Dialog widget holders (populated by the builders below) --- #
        pdlg: dict[str, Any] = {}
        sdlg: dict[str, Any] = {}

        def _build_profile_dialog() -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[640px] max-w-full gap-2").style(
                "background:#131512; border:1px solid #2A2E29;"
            ):
                pdlg["title"] = ui.label("New profile").classes("aal-section")
                ui.label("BASIC").classes("aal-stat-label mt-1")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    pdlg["name"] = ui.input("Name").props("dark dense outlined").classes("w-72")
                    pdlg["group"] = ui.select({"": "(no group)"}, value="", label="Group").props(
                        "dark dense outlined"
                    ).classes("w-52")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    pdlg["tags"] = ui.input("Tags (comma separated)").props(
                        "dark dense outlined"
                    ).classes("w-72")
                    pdlg["sim"] = ui.input("SIM ID").props("dark dense outlined").classes("w-40")
                    pdlg["site"] = ui.select({"": "(none)"}, value="", label="Site").props(
                        "dark dense outlined"
                    ).classes("w-52")
                pdlg["startup_url"] = ui.input("Startup URL").props(
                    "dark dense outlined"
                ).classes("w-full")
                pdlg["notes"] = ui.textarea("Notes").props("dark dense outlined").classes("w-full")
                ui.label("FINGERPRINT").classes("aal-stat-label mt-2")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    pdlg["platform"] = ui.select(
                        ["windows", "macos"], value="windows", label="Platform"
                    ).props("dark dense outlined").classes("w-40")
                    pdlg["seed"] = ui.number("Seed (blank = random)").props(
                        "dark dense outlined"
                    ).classes("w-48")
                    pdlg["color_scheme"] = ui.select(
                        ["", "light", "dark", "no-preference"], value="", label="Color scheme"
                    ).props("dark dense outlined").classes("w-48")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    pdlg["timezone"] = ui.input("Timezone").props(
                        "dark dense outlined"
                    ).classes("w-56")
                    pdlg["locale"] = ui.input("Locale").props("dark dense outlined").classes("w-40")
                pdlg["user_agent"] = ui.input("User agent").props(
                    "dark dense outlined"
                ).classes("w-full")
                with ui.row().classes("w-full gap-3 flex-wrap items-center"):
                    pdlg["vw"] = ui.number("Viewport width").props(
                        "dark dense outlined"
                    ).classes("w-40")
                    pdlg["vh"] = ui.number("Viewport height").props(
                        "dark dense outlined"
                    ).classes("w-40")
                    pdlg["geoip"] = ui.switch("GeoIP from proxy")
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat").style(f"color:{MUTED}")
                    ui.button("Save", icon="save",
                              on_click=lambda: submit_profile_dialog()).props("dense").style(
                        f"background:{ACCENT}; color:#0B0C0A;"
                    )
            pdlg["dialog"] = dialog

        def _build_site_dialog() -> None:
            with ui.dialog() as dialog, ui.card().classes("w-[560px] max-w-full gap-2").style(
                "background:#131512; border:1px solid #2A2E29;"
            ):
                sdlg["title"] = ui.label("New site").classes("aal-section")
                sdlg["key"] = ui.input("Key (immutable id, e.g. acme)").props(
                    "dark dense outlined"
                ).classes("w-full")
                sdlg["name"] = ui.input("Display name").props(
                    "dark dense outlined"
                ).classes("w-full")
                sdlg["base_url"] = ui.input("Base URL").props(
                    "dark dense outlined"
                ).classes("w-full")
                sdlg["description"] = ui.textarea("Description").props(
                    "dark dense outlined"
                ).classes("w-full")
                with ui.row().classes("w-full gap-3 flex-wrap"):
                    sdlg["captcha"] = ui.select(
                        [m.value for m in CaptchaMode], value=CaptchaMode.TEST_KEY.value,
                        label="CAPTCHA mode",
                    ).props("dark dense outlined").classes("w-48")
                    sdlg["proxy"] = ui.select(
                        [p.value for p in ProxyPolicy], value=ProxyPolicy.STICKY_PROFILE.value,
                        label="Proxy policy",
                    ).props("dark dense outlined").classes("w-56")
                sdlg["hints"] = ui.input("OTP sender hints (comma separated)").props(
                    "dark dense outlined"
                ).classes("w-full")
                sdlg["enabled"] = ui.switch("Enabled", value=True)
                with ui.row().classes("w-full justify-end gap-2 mt-2"):
                    ui.button("Cancel", on_click=dialog.close).props("flat").style(f"color:{MUTED}")
                    ui.button("Save", icon="save",
                              on_click=lambda: submit_site_dialog()).props("dense").style(
                        f"background:{ACCENT}; color:#0B0C0A;"
                    )
            sdlg["dialog"] = dialog

        # ---- Refresh functions ----------------------------------------- #
        async def refresh_browser_profiles() -> None:
            profiles = await browser_store.list_profiles()
            assignments = await proxy_manager.list_assignments()
            sessions = await browser_sessions.list_sessions()
            groups_list = await repo.list_profile_groups()
            groups_map = {group.id: group.name for group in groups_list}

            selected_group = str(group_filter.value or "__all__")
            if selected_group == "__none__":
                visible = [profile for profile in profiles if not profile.group_id]
            elif selected_group not in ("__all__", "__none__"):
                visible = [profile for profile in profiles if profile.group_id == selected_group]
            else:
                visible = list(profiles)

            rows = _profile_manager_rows(
                profiles=visible, groups=groups_map, assignments=assignments, sessions=sessions
            )
            browser_profiles_table.rows = rows
            browser_profiles_table.update()

            group_options = _group_filter_options(groups_list)
            group_filter.options = group_options
            if group_filter.value not in group_options:
                group_filter.value = "__all__"
            group_filter.update()
            group_pairs = {g.id: g.name for g in groups_list}
            pdlg["group"].options = {"": "(no group)", **group_pairs}
            pdlg["group"].update()

            selected_profile.options = {
                row["id"]: f'{row["name"]} | {row["session"]}' for row in rows
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

        async def refresh_sites() -> None:
            sites = await repo.list_sites()
            sites_table.rows = _site_rows(sites)
            sites_table.update()
            options = {s.key: f"{s.key} | {s.display_name}" for s in sites if s.enabled}
            job_site_select.options = options
            if options and job_site_select.value not in options:
                job_site_select.value = next(iter(options))
            if not options:
                job_site_select.value = None
            job_site_select.update()
            pdlg["site"].options = {"": "(none)", **{s.key: s.key for s in sites}}
            pdlg["site"].update()

        async def refresh_jobs() -> list[JobRecord]:
            jobs = await repo.list_jobs()
            rows = _job_rows(jobs)
            jobs_table.rows = rows
            jobs_table.update()
            job_select.options = {
                row["full_id"]: f'{row["id"]} | {row["site"]} | {row["status"]}' for row in rows
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
            backend_chip.text = f"backend: {settings.database_backend}"
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
                    await refresh_sites()
                    await refresh_jobs()
                    await refresh_events()
                    await refresh_proxies()
                    await refresh_secrets()
                    if not refresh_again:
                        return


        # ---- Group handlers -------------------------------------------- #
        async def create_group(name: str) -> None:
            name = name.strip()
            if not name:
                ui.notify("Group name is required", color="negative")
                return
            group = await repo.create_profile_group(ProfileGroupCreate(name=name))
            new_group_input.value = ""
            new_group_input.update()
            ui.notify(f"Created group {group.name}", color="positive")
            await refresh_all()

        async def delete_group(group_id: str) -> None:
            if group_id in ("", "__all__", "__none__"):
                ui.notify("Select a real group to delete", color="negative")
                return
            await repo.delete_profile_group(group_id)
            group_filter.value = "__all__"
            group_filter.update()
            ui.notify("Group deleted", color="positive")
            await refresh_all()

        # ---- Profile dialog -------------------------------------------- #
        def _reset_profile_dialog() -> None:
            pdlg["name"].value = ""
            pdlg["group"].value = ""
            pdlg["tags"].value = ""
            pdlg["sim"].value = ""
            pdlg["site"].value = ""
            pdlg["startup_url"].value = ""
            pdlg["notes"].value = ""
            pdlg["platform"].value = "windows"
            pdlg["seed"].value = None
            pdlg["color_scheme"].value = ""
            pdlg["timezone"].value = ""
            pdlg["locale"].value = ""
            pdlg["user_agent"].value = ""
            pdlg["vw"].value = None
            pdlg["vh"].value = None
            pdlg["geoip"].value = False

        async def open_profile_dialog(profile_id: str) -> None:
            _reset_profile_dialog()
            editing_profile["id"] = ""
            if profile_id:
                profile = await browser_store.get_profile(profile_id)
                if profile is None:
                    ui.notify("Select a profile first", color="negative")
                    return
                editing_profile["id"] = profile.id
                pdlg["title"].text = "Edit profile"
                pdlg["name"].value = profile.name
                pdlg["group"].value = profile.group_id or ""
                pdlg["tags"].value = ", ".join(profile.tags)
                pdlg["sim"].value = profile.sim_id or ""
                pdlg["site"].value = profile.site_key or ""
                pdlg["startup_url"].value = profile.startup_url or ""
                pdlg["notes"].value = profile.notes
                fp = profile.fingerprint
                pdlg["platform"].value = fp.platform.value
                pdlg["seed"].value = fp.seed
                pdlg["color_scheme"].value = fp.color_scheme or ""
                pdlg["timezone"].value = fp.timezone or ""
                pdlg["locale"].value = fp.locale or ""
                pdlg["user_agent"].value = fp.user_agent or ""
                if fp.viewport is not None:
                    pdlg["vw"].value = fp.viewport.get("width")
                    pdlg["vh"].value = fp.viewport.get("height")
                pdlg["geoip"].value = fp.geoip_from_proxy
            else:
                pdlg["title"].text = "New profile"
            pdlg["title"].update()
            pdlg["dialog"].open()

        def _build_fingerprint() -> FingerprintConfig:
            seed_value = pdlg["seed"].value
            seed = int(seed_value) if seed_value not in (None, "") else None
            width = pdlg["vw"].value
            height = pdlg["vh"].value
            viewport: dict[str, int] | None = None
            if width not in (None, "") and height not in (None, ""):
                viewport = {"width": int(width), "height": int(height)}
            return FingerprintConfig(
                platform=FingerprintPlatform(str(pdlg["platform"].value or "windows")),
                seed=seed,
                timezone=str(pdlg["timezone"].value or "") or None,
                locale=str(pdlg["locale"].value or "") or None,
                color_scheme=str(pdlg["color_scheme"].value or "") or None,
                user_agent=str(pdlg["user_agent"].value or "") or None,
                viewport=viewport,
                geoip_from_proxy=bool(pdlg["geoip"].value),
            )

        async def submit_profile_dialog() -> None:
            name = str(pdlg["name"].value or "").strip()
            if not name:
                ui.notify("Name is required", color="negative")
                return
            tags = [t.strip() for t in str(pdlg["tags"].value or "").split(",") if t.strip()]
            group_id = str(pdlg["group"].value or "") or None
            sim_id = str(pdlg["sim"].value or "") or None
            site_key = str(pdlg["site"].value or "") or None
            startup_url = str(pdlg["startup_url"].value or "") or None
            notes = str(pdlg["notes"].value or "")
            fingerprint = _build_fingerprint()
            editing_id = editing_profile["id"]
            try:
                if editing_id:
                    await browser_store.update_profile(
                        editing_id,
                        BrowserProfileUpdate(
                            name=name, group_id=group_id, tags=tags, notes=notes,
                            sim_id=sim_id, site_key=site_key, startup_url=startup_url,
                            fingerprint=fingerprint,
                        ),
                    )
                    ui.notify("Profile updated", color="positive")
                else:
                    profile = await browser_store.create_profile(
                        BrowserProfileCreate(
                            name=name, group_id=group_id, tags=tags, notes=notes,
                            sim_id=sim_id, site_key=site_key, startup_url=startup_url,
                            fingerprint=fingerprint,
                        )
                    )
                    ui.notify(f"Created profile {profile.name}", color="positive")
            except BrowserProfileExistsError as exc:
                ui.notify(str(exc), color="negative")
                return
            except KeyError:
                ui.notify("Browser profile not found", color="negative")
                await refresh_browser_profiles()
                return
            pdlg["dialog"].close()
            await refresh_all()

        async def delete_profile_ui(profile_id: str) -> None:
            if not profile_id:
                ui.notify("Select a profile first", color="negative")
                return
            await browser_store.delete_profile(profile_id, remove_storage=False)
            ui.notify(f"Deleted profile {profile_id}", color="positive")
            await refresh_all()

        # ---- Site dialog ----------------------------------------------- #
        def _reset_site_dialog() -> None:
            sdlg["key"].value = ""
            sdlg["name"].value = ""
            sdlg["base_url"].value = ""
            sdlg["description"].value = ""
            sdlg["captcha"].value = CaptchaMode.TEST_KEY.value
            sdlg["proxy"].value = ProxyPolicy.STICKY_PROFILE.value
            sdlg["hints"].value = ""
            sdlg["enabled"].value = True

        async def open_site_dialog(site_key: str) -> None:
            _reset_site_dialog()
            editing_site["key"] = ""
            if site_key:
                site = await repo.get_site(site_key)
                if site is None:
                    ui.notify("Site not found", color="negative")
                    return
                editing_site["key"] = site.key
                sdlg["title"].text = f"Edit site / {site.key}"
                sdlg["key"].value = site.key
                sdlg["key"].props("readonly")
                sdlg["name"].value = site.display_name
                sdlg["base_url"].value = site.base_url
                sdlg["description"].value = site.description
                sdlg["captcha"].value = site.captcha_mode.value
                sdlg["proxy"].value = site.proxy_policy.value
                sdlg["hints"].value = ", ".join(site.otp_sender_hints)
                sdlg["enabled"].value = site.enabled
            else:
                sdlg["title"].text = "New site"
                sdlg["key"].props(remove="readonly")
            sdlg["title"].update()
            sdlg["key"].update()
            sdlg["dialog"].open()

        async def submit_site_dialog() -> None:
            hints = [h.strip() for h in str(sdlg["hints"].value or "").split(",") if h.strip()]
            captcha = CaptchaMode(str(sdlg["captcha"].value or CaptchaMode.TEST_KEY.value))
            proxy = ProxyPolicy(str(sdlg["proxy"].value or ProxyPolicy.STICKY_PROFILE.value))
            name = str(sdlg["name"].value or "").strip()
            base_url = str(sdlg["base_url"].value or "").strip()
            description = str(sdlg["description"].value or "")
            enabled = bool(sdlg["enabled"].value)
            editing_key = editing_site["key"]
            if editing_key:
                try:
                    await repo.update_site(
                        editing_key,
                        SiteUpdate(
                            display_name=name or None, base_url=base_url or None,
                            description=description, captcha_mode=captcha,
                            otp_sender_hints=hints, proxy_policy=proxy, enabled=enabled,
                        ),
                    )
                    ui.notify("Site updated", color="positive")
                except KeyError:
                    ui.notify("Site not found", color="negative")
                    return
            else:
                key = str(sdlg["key"].value or "").strip()
                if not key or not name or not base_url:
                    ui.notify("Key, name and base URL are required", color="negative")
                    return
                try:
                    await repo.create_site(
                        SiteCreate(
                            key=key, display_name=name, base_url=base_url,
                            description=description, captcha_mode=captcha,
                            otp_sender_hints=hints, proxy_policy=proxy, enabled=enabled,
                        )
                    )
                    ui.notify(f"Created site {key}", color="positive")
                except SiteExistsError as exc:
                    ui.notify(str(exc), color="negative")
                    return
            sdlg["dialog"].close()
            await refresh_all()

        async def delete_site_ui(site_key: str) -> None:
            site = await repo.get_site(site_key)
            if site is None:
                ui.notify("Site not found", color="negative")
                return
            if site.has_code_adapter:
                ui.notify("Cannot delete a site backed by a code adapter", color="negative")
                return
            await repo.delete_site(site_key)
            ui.notify(f"Deleted site {site_key}", color="positive")
            await refresh_all()

        # ---- Profile / session actions --------------------------------- #
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
            await queue_job(
                profile.site_key or "", profile.sim_id or "", profile.runtime.value, profile.id
            )

        async def queue_job(
            site_key: str, sim_id: str, runtime: str, profile_id: str | None
        ) -> None:
            if not site_key or not sim_id:
                ui.notify("Site and SIM are required", color="negative")
                return
            if await repo.get_site(site_key) is None:
                ui.notify(f"Unknown site: {site_key}", color="negative")
                return
            record = await repo.create_job(
                JobCreate(
                    site_key=site_key, sim_id=sim_id, runtime=RuntimeKind(runtime),
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
                ui.notify(f"Cannot cancel a {job.status.value} job", color="warning")
                return
            runner.cancel_checkpoint(job_id)
            try:
                await repo.update_job_status(
                    job_id, JobStatus.CANCELLED,
                    event_type="job.cancelled", message="Job cancelled by operator",
                )
            except InvalidJobTransitionError:
                ui.notify("Job can no longer be cancelled", color="warning")
                await refresh_all()
                return
            ui.notify(f"Cancelled job {_short_id(job_id)}", color="positive")
            await refresh_all()

        async def resume_job_ui(job_id: str) -> None:
            if not job_id:
                ui.notify("Select a job first", color="negative")
                return
            runner.resume(job_id)
            ui.notify(f"Resumed {_short_id(job_id)}", color="positive")
            await refresh_all()

        async def pause_job_ui(job_id: str) -> None:
            if not job_id:
                ui.notify("Select a job first", color="negative")
                return
            job = await repo.get_job(job_id)
            if job is not None and job.status == JobStatus.RUNNING:
                await repo.update_job_status(
                    job_id, JobStatus.WAITING_HUMAN,
                    event_type="job.paused", message="Paused by operator",
                )
            await refresh_all()

        # ---- Proxy actions --------------------------------------------- #
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

        _build_profile_dialog()
        _build_site_dialog()
        await refresh_all()
        ui.timer(3.0, refresh_all)
