# Account Automation Lab Plan

This project implements the approved MVP plan:

- FastAPI API with NiceGUI UI in one process.
- Async automation core with CloakBrowser as the default profile runtime; plain Playwright Chromium is debug-only.
- One shared Supabase schema for SMS Forwarder + Account Automation Lab (Supabase is the default backend), plus a memory backend fallback for local development and tests.
- APScheduler plus `asyncio.Queue` job runner with global and per-site concurrency limits.
- A step-based workflow engine for site adapters, with a `WAITING_HUMAN` state and operator resume/pause/cancel controls.
- Ten separate site adapter modules with mock-safe defaults.
- SIM OTP, shared `otp_messages` fallback, ProxyVN profile-proxy manager, and CAPTCHA provider abstractions with provider-backed modes disabled by default.
- AdsPower-style profile cockpit for managing uuid-keyed, persisted browser profiles (groups, tags, fingerprint) and opening/stopping CloakBrowser sessions from the web UI.

## Shared Database Decision

There is only one Supabase project. `sms-forwarder` and Account Automation Lab should use the same `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

Shared schema tables:

- SMS owns `contacts`, `login_accounts`, `regex_overrides`, `otp_messages`, and `cache_meta`.
- Automation owns schema for `automation_sites`, `automation_sims`, `automation_profile_groups`, `automation_profiles`, `automation_proxies`, `automation_jobs`, `automation_job_events`, `automation_accounts`, `automation_job_artifacts`, and `automation_captcha_tasks`.
- Supabase is the default backend. Jobs, events, accounts, artifacts, browser profiles, and profile groups are persisted in the shared Supabase database; the factory falls back to the in-memory backend when Supabase credentials are absent or when `DATABASE_BACKEND=memory` is set, so local development and tests stay offline-safe.
- Automation reads OTP fallback from SMS-owned `otp_messages` by matching `receiver_phone_normalized`, sender hints, and `received_at`.

## Proxy Profile Mapping

ProxyVN is the single proxy provider for the MVP. Set `PROXYVN_API_KEY` in `.env`; never commit it.

- `POST /api/profiles/{profile_id}/proxy/ensure` buys one 1-day 4Gvinaphone HTTP proxy only if the profile has no assigned proxy yet.
- `POST /api/profiles/{profile_id}/proxy/attach` maps an already purchased ProxyVN `idproxy` to the profile without buying another proxy.
- `POST /api/profiles/{profile_id}/proxy/refresh` calls ProxyVN change-proxy for the assigned `idproxy`.
- `GET /api/proxies` returns profile assignments with masked proxy strings only.
- Each profile uses one sticky proxy by default; `fresh_per_job` and deeper policies can be layered later once site adapters need them.

## NiceGUI MVP

The UI is a backend-first NiceGUI shell mounted into the same FastAPI process:

- Profiles is the primary screen: it shows browser profiles, SIM, site, runtime, proxy, session status, groups, and tags.
- Profiles can create, edit, clone, and delete profiles, organize them into groups, open/stop CloakBrowser sessions, and queue signup jobs directly for a profile.
- Sessions shows active browser contexts.
- Jobs reads the live repository, shows job counts, job rows, and selected job events, and can cancel a selected job that is still queued, running, or waiting on CAPTCHA.
- Proxies reads the in-process profile-proxy manager and can attach an existing ProxyVN `idproxy`, buy a one-day proxy, or rotate a profile proxy.
- Settings renders enabled/configured/missing status for Supabase, SIM OTP, ProxyVN, CAPTCHA provider, and CloakBrowser without exposing secret values.

## Browser Profile Runtime

The profile manager is implemented and is the primary surface of the app:

- Profiles are **uuid-keyed** and **persisted** in the shared Supabase database (with an in-memory fallback offline). Each profile carries `name`, optional `group_id`, `tags`, `notes`, `sim_id`, `site_key`, `runtime`, `startup_url`, `status`, and a `fingerprint` config.
- Profiles are manageable from both the UI and the REST API: create, edit, clone, and delete, plus open/close CloakBrowser sessions. Profiles can be organized into **groups** (`automation_profile_groups`) and filtered by **tags**.
- The `fingerprint` config maps onto CloakBrowser launch options: `platform`→`--fingerprint-platform`, `seed`→`--fingerprint`, plus `timezone`, `locale`, `color_scheme`, `user_agent`, `viewport`, `geoip_from_proxy`→`geoip`, and `extension_paths`.
- `BrowserProfileStore` seeds one default profile per mock site for `sim-a`.
- `BrowserSessionManager` keeps one active CloakBrowser context per profile and reuses duplicate open requests instead of launching a second context.
- Profile storage directories are path-safe and live under `BROWSER_PROFILE_STORAGE_ROOT` (`.profiles` by default). Active browser sessions stay process-local, and raw proxy credentials are never written into profile rows.

## Workflow Engine

The step-based workflow engine is implemented. Site adapters describe their flow as a sequence of primitive steps run by `WorkflowEngine`:

- Primitives: `goto`, `fill`, `click`, `wait_for`, `get_otp`, `wait_for_human`, `read_from`, and `emit`.
- Jobs support a `WAITING_HUMAN` state with three entry points: a code-initiated `wait_for_human` step, an error path (a raised step pauses the job at `WAITING_HUMAN` instead of failing unless `fail_fast` is set), and operator-initiated pause.
- Operators drive jobs through `POST /api/jobs/{id}/resume`, `POST /api/jobs/{id}/pause`, `POST /api/jobs/{id}/cancel`, and `GET /api/jobs/{id}/checkpoint`.

## Runtime Decision

CloakBrowser is the default automation runtime for jobs and site adapters. Plain Playwright Chromium remains available only as a debug fallback.

On this machine, smoke testing confirmed CloakBrowser `0.3.30` works when using:

```powershell
CLOAKBROWSER_BINARY_PATH=C:\Users\vanto\.cloakbrowser\chromium-146.0.7680.177.4\chrome.exe
```

Without this override, the package attempts to download Chromium `146.0.7680.177.5`, which timed out during testing.

For headed profile runs, the app passes `viewport=None` so Playwright does not force
CloakBrowser's default `1920x947` viewport. It also sends window sizing args
(`--start-maximized`, `--window-position`, `--window-size`) based on the current Windows
work area. CloakBrowser's own default stealth args include `--no-sandbox`; the app now
filters that flag and patches CloakBrowser's Playwright `IGNORE_DEFAULT_ARGS` list by
default while preserving CloakBrowser fingerprint args to avoid Chromium's unsupported-flag
warning on Windows.

## Skill Setup Notes

Installed successfully:

- `github/awesome-copilot@playwright-automation-fill-in-form`
- `supabase/agent-skills@supabase-postgres-best-practices`
- `mindrally/skills@fastapi-python`

Codex already has local `playwright`, `playwright-interactive`, and `browser` skills available.

## Safety Boundary

This codebase is for internal, authorized web properties and mock signup targets. It intentionally does not ship a working CAPTCHA-solving integration or anti-abuse bypass. Provider-backed CAPTCHA and CloakBrowser modes require explicit environment flags and adapter configuration.
