# Account Automation Lab

Internal automation control plane for authorized account-registration testing.

The MVP uses FastAPI, NiceGUI, CloakBrowser with Playwright-compatible async APIs, APScheduler, and a guarded adapter model. The UI is now a profile cockpit in the same spirit as AdsPower: profiles are the center of the workflow, each profile can have a sticky proxy, an active CloakBrowser session, and registration jobs.

## Database

Use one shared Supabase project for both `sms-forwarder` and this app:

- Run `supabase/schema.sql` in that single Supabase project. The script is idempotent and now also creates `automation_profile_groups` plus the extra `automation_profiles` columns (`name`, `group_id`, `tags`, `notes`, `runtime`, `startup_url`, `status`, `fingerprint`).
- Put the same `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in both apps.
- `sms-forwarder` writes OTPs into `otp_messages`.
- Account Automation Lab reads OTP fallback from that same `otp_messages` table. Jobs, events, accounts, artifacts, CAPTCHA task records, browser profiles, and profile groups are Supabase-backed through `automation_*` tables.

### Backend selection

- Supabase is the **default** backend. The repository factory uses Supabase when `DATABASE_BACKEND=supabase` (the default) and both `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` are present.
- When those credentials are absent, the factory automatically falls back to the in-memory backend, so the app stays offline-safe out of the box.
- Set `DATABASE_BACKEND=memory` to force the in-memory backend for offline or dev work. This keeps everything process-local and touches no external services.

## ProxyVN

Set `PROXYVN_API_KEY` in `.env`; do not commit it. The default test purchase is one 4Gvinaphone HTTP proxy for one day.

```powershell
# Ensure one proxy for a profile; second call reuses the same proxy.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/profiles/sim-a:site_01/proxy/ensure

# Attach an already purchased ProxyVN proxy to a profile without buying another one.
Invoke-RestMethod -Method Post `
  -ContentType 'application/json' `
  -Body '{"idproxy":308}' `
  http://127.0.0.1:8080/api/profiles/sim-a:site_01/proxy/attach

# Rotate the proxy for that profile.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/profiles/sim-a:site_01/proxy/refresh

# List masked profile -> proxy assignments.
Invoke-RestMethod http://127.0.0.1:8080/api/proxies
```

API responses only expose masked proxy strings such as `ip:port:***:***`; raw usernames/passwords stay inside the runtime.

## Quick Start

```powershell
cd C:\Users\vanto\Documents\code\account-automation-lab
python -m uv sync --extra dev
Copy-Item .env.example .env
# Set PROXYVN_API_KEY and, on this machine, CLOAKBROWSER_BINARY_PATH in .env.
python -m uv run account-automation-lab
```

Open <http://127.0.0.1:8080>.

## UI

The NiceGUI dashboard is wired to the same in-process FastAPI state as the API:

- Profiles shows browser profiles, session status, masked proxy, SIM, site, runtime, and tags.
- Profiles can create profiles, open/stop CloakBrowser sessions, and queue signup jobs for a profile.
- Sessions shows active browser contexts.
- Jobs shows live jobs and selected job events.
- Jobs can be cancelled from the UI for jobs that are still queued, running, or waiting on CAPTCHA.
- Proxies shows masked profile-proxy assignments and supports attach, one-day buy, and rotate actions.
- Settings shows secret health without exposing secret values.

## Browser Profile Manager

Profiles are the center of the workflow and are managed from the UI or the REST API. Each profile is **uuid-keyed** and **persisted** (in Supabase by default, in memory offline). A profile carries:

- `name`, optional `group_id`, free-form `tags`, and `notes`.
- `sim_id`, `site_key`, `runtime` (`cloakbrowser` by default), and `startup_url`.
- A `fingerprint` config (see below) and a stable storage directory under `BROWSER_PROFILE_STORAGE_ROOT` (`.profiles` by default).

You can create, edit, clone, and delete profiles. Cloning copies the profile metadata and fingerprint into a new uuid-keyed profile. Profiles can be organized into **groups** (with an optional color) and filtered by **tags**.

### Fingerprint config

Each profile's `fingerprint` maps onto CloakBrowser launch options:

| Field | Maps to |
| --- | --- |
| `platform` | `--fingerprint-platform` (emitted only when it differs from the default) |
| `seed` | `--fingerprint=<seed>` for deterministic fingerprints |
| `timezone` | CloakBrowser `timezone` |
| `locale` | CloakBrowser `locale` |
| `color_scheme` | CloakBrowser `color_scheme` |
| `user_agent` | CloakBrowser `user_agent` |
| `viewport` | CloakBrowser `viewport` (`{width, height}`) |
| `geoip_from_proxy` | CloakBrowser `geoip` (derive geolocation from the proxy egress) |
| `extension_paths` | extensions loaded into the profile |

## Browser Profile API

```powershell
# List profile cockpit rows.
Invoke-RestMethod http://127.0.0.1:8080/api/browser-profiles

# Create a profile.
Invoke-RestMethod -Method Post `
  -ContentType 'application/json' `
  -Body '{"sim_id":"sim-b","site_key":"site_02","name":"SIM B / site_02"}' `
  http://127.0.0.1:8080/api/browser-profiles

# Edit a profile (name, group, tags, fingerprint, ...).
Invoke-RestMethod -Method Patch `
  -ContentType 'application/json' `
  -Body '{"tags":["warmup"],"notes":"primary"}' `
  http://127.0.0.1:8080/api/browser-profiles/<profile-id>

# Clone a profile into a new uuid-keyed profile.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/browser-profiles/<profile-id>/clone

# Delete a profile (optionally remove its storage directory).
Invoke-RestMethod -Method Delete "http://127.0.0.1:8080/api/browser-profiles/<profile-id>?remove_storage=true"

# Open or stop a CloakBrowser session for one profile.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/browser-profiles/<profile-id>/open
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/browser-profiles/<profile-id>/close

# List active sessions.
Invoke-RestMethod http://127.0.0.1:8080/api/browser-sessions
```

### Profile groups API

```powershell
# List or create groups.
Invoke-RestMethod http://127.0.0.1:8080/api/profile-groups
Invoke-RestMethod -Method Post `
  -ContentType 'application/json' `
  -Body '{"name":"Warmup","color":"#22aa55"}' `
  http://127.0.0.1:8080/api/profile-groups

# Edit or delete a group.
Invoke-RestMethod -Method Patch `
  -ContentType 'application/json' `
  -Body '{"name":"Warmup A"}' `
  http://127.0.0.1:8080/api/profile-groups/<group-id>
Invoke-RestMethod -Method Delete http://127.0.0.1:8080/api/profile-groups/<group-id>
```

Profile storage directories live under `BROWSER_PROFILE_STORAGE_ROOT` (`.profiles` by default). Profile metadata and profile groups are persisted through the shared Supabase database (or the in-memory backend offline); active browser sessions stay process-local, and raw proxy credentials are never stored in profile rows.

## Concurrency

The job runner enforces two independent limits:

- `MAX_GLOBAL_CONCURRENCY` caps how many jobs run at once across all sites (the number of worker tasks).
- `MAX_SITE_CONCURRENCY` caps how many jobs run at once for a single site. The runner tracks active jobs per site and excludes saturated sites when claiming the next queued job, so a busy site cannot starve others.

Per-profile locks remain in place as well: a profile can only run one job at a time, regardless of the concurrency limits.

## Workflow Engine

Jobs run as ordered sequences of small, composable steps executed by a step-based workflow engine. Site adapters describe their signup flow as a list of primitive steps:

- `goto(url)` — navigate the page.
- `fill(selector, value)` — type into a field.
- `click(selector)` — click an element.
- `wait_for(seconds)` — pause for a fixed delay.
- `get_otp(sim_id, site_key, ...)` — wait for an OTP (SIM provider with `otp_messages` fallback) and stash it in the workflow context.
- `wait_for_human(kind, message)` — deliberately hand control to an operator (see below).
- `read_from(profile_id, reader)` — read a value from another profile's live page (cross-profile reads).
- `emit(event_type, message, payload)` — record a structured job event.

### Human-in-the-loop

The engine supports a `WAITING_HUMAN` job state with three entry points:

- **Code-initiated wait** — a `wait_for_human` step sets the job to `WAITING_HUMAN` and blocks on a checkpoint until an operator resumes it.
- **Error → waiting_human** — when a step raises, the engine records a `job.error` event and (unless `fail_fast` is set) pauses the job at `WAITING_HUMAN` instead of failing, so an operator can intervene and resume.
- **Operator pause** — an operator can pause a running job, inspect it, then resume or cancel.

Job control endpoints:

```powershell
# Resume a job waiting on a human checkpoint.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/jobs/<job-id>/resume

# Pause a running job for manual intervention.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/jobs/<job-id>/pause

# Cancel a job (queued, running, or waiting).
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/jobs/<job-id>/cancel

# Inspect the current human checkpoint for a job.
Invoke-RestMethod http://127.0.0.1:8080/api/jobs/<job-id>/checkpoint
```

## Guardrails

- Mock adapters are enabled for local testing.
- Real adapters must use allowlisted host suffixes.
- CAPTCHA provider mode is disabled unless `CAPTCHA_PROVIDER_ENABLED=true`.
- CloakBrowser is the default automation runtime. Playwright Chromium is kept only as an optional debug fallback.
- Secrets stay in `.env` or a secret manager, never in database rows or docs.

## CloakBrowser

This machine already has a working CloakBrowser binary at:

```powershell
C:\Users\vanto\.cloakbrowser\chromium-146.0.7680.177.4\chrome.exe
```

Set this in `.env` to avoid waiting for the package to download a newer build:

```powershell
CLOAKBROWSER_BINARY_PATH=C:\Users\vanto\.cloakbrowser\chromium-146.0.7680.177.4\chrome.exe
```

Headed CloakBrowser profile windows default to the current Windows work area:

```powershell
CLOAKBROWSER_FIT_SCREEN=true
CLOAKBROWSER_START_MAXIMIZED=true
CLOAKBROWSER_WINDOW_WIDTH=0
CLOAKBROWSER_WINDOW_HEIGHT=0
```

`CLOAKBROWSER_FILTER_NO_SANDBOX=true` keeps CloakBrowser's fingerprint flags but removes
both CloakBrowser's stealth `--no-sandbox` flag and Playwright's default `--no-sandbox`
launch arg, which cause Chromium's unsupported-flag warning on Windows.

The default job runtime is `cloakbrowser`; use `playwright_chromium` only for debug runs.
