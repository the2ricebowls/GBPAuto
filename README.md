# Account Automation Lab

Internal automation control plane for authorized account-registration testing.

The MVP uses FastAPI, NiceGUI, CloakBrowser with Playwright-compatible async APIs, APScheduler, and a guarded adapter model. The UI is now a profile cockpit in the same spirit as AdsPower: profiles are the center of the workflow, each profile can have a sticky proxy, an active CloakBrowser session, and registration jobs.

## Database

Use one shared Supabase project for both `sms-forwarder` and this app:

- Run `supabase/schema.sql` in that single Supabase project.
- Put the same `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` in both apps.
- `sms-forwarder` writes OTPs into `otp_messages`.
- Account Automation Lab reads OTP fallback from that same `otp_messages` table. Jobs, events, accounts, artifacts, and CAPTCHA task records can be Supabase-backed through `automation_*` tables.
- Browser profile records and profile-proxy assignments are in-process for the MVP unless or until the Supabase browser profile persistence follow-up is implemented.

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

## Browser Profile API

```powershell
# List profile cockpit rows.
Invoke-RestMethod http://127.0.0.1:8080/api/browser-profiles

# Create a profile.
Invoke-RestMethod -Method Post `
  -ContentType 'application/json' `
  -Body '{"sim_id":"sim-b","site_key":"site_02","name":"SIM B / site_02"}' `
  http://127.0.0.1:8080/api/browser-profiles

# Open or stop a CloakBrowser session for one profile.
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/browser-profiles/sim-a:site_01/open
Invoke-RestMethod -Method Post http://127.0.0.1:8080/api/browser-profiles/sim-a:site_01/close

# List active sessions.
Invoke-RestMethod http://127.0.0.1:8080/api/browser-sessions
```

Profile storage directories live under `BROWSER_PROFILE_STORAGE_ROOT` (`.profiles` by default). Profile rows and profile-proxy assignments are currently in-process for the MVP; the storage directories are stable, and the next persistence step is to back profile metadata with the shared Supabase database without storing raw proxy credentials.

## Concurrency

The job runner enforces two independent limits:

- `MAX_GLOBAL_CONCURRENCY` caps how many jobs run at once across all sites (the number of worker tasks).
- `MAX_SITE_CONCURRENCY` caps how many jobs run at once for a single site. The runner tracks active jobs per site and excludes saturated sites when claiming the next queued job, so a busy site cannot starve others.

Per-profile locks remain in place as well: a profile can only run one job at a time, regardless of the concurrency limits.

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
