# Account Automation Lab Plan

This project implements the approved MVP plan:

- FastAPI API with NiceGUI UI in one process.
- Async automation core with CloakBrowser as the default profile runtime; plain Playwright Chromium is debug-only.
- One shared Supabase schema for SMS Forwarder + Account Automation Lab, plus memory backend for local development and tests.
- APScheduler plus `asyncio.Queue` job runner with global and per-site concurrency limits.
- Ten separate site adapter modules with mock-safe defaults.
- SIM OTP, shared `otp_messages` fallback, ProxyVN profile-proxy manager, and CAPTCHA provider abstractions with provider-backed modes disabled by default.
- AdsPower-style profile cockpit for opening/stopping CloakBrowser profiles from the web UI.

## Shared Database Decision

There is only one Supabase project. `sms-forwarder` and Account Automation Lab should use the same `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.

Shared schema tables:

- SMS owns `contacts`, `login_accounts`, `regex_overrides`, `otp_messages`, and `cache_meta`.
- Automation owns schema for `automation_sites`, `automation_sims`, `automation_profiles`, `automation_proxies`, `automation_jobs`, `automation_job_events`, `automation_accounts`, `automation_job_artifacts`, and `automation_captcha_tasks`.
- Current MVP persistence is aligned around jobs/events and related automation records. Browser profile records and profile-proxy assignments remain in-process until the browser profile persistence follow-up is implemented.
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

- Profiles is the primary screen: it shows browser profiles, SIM, site, runtime, proxy, session status, and tags.
- Profiles can create profiles, open/stop CloakBrowser sessions, and queue signup jobs directly for a profile.
- Sessions shows active browser contexts.
- Jobs reads the live repository, shows job counts, job rows, and selected job events, and can cancel a selected job that is still queued, running, or waiting on CAPTCHA.
- Proxies reads the in-process profile-proxy manager and can attach an existing ProxyVN `idproxy`, buy a one-day proxy, or rotate a profile proxy.
- Settings renders enabled/configured/missing status for Supabase, SIM OTP, ProxyVN, CAPTCHA provider, and CloakBrowser without exposing secret values.

## Browser Profile Runtime

- `BrowserProfileStore` seeds one default profile per mock site for `sim-a`.
- `BrowserSessionManager` keeps one active CloakBrowser context per profile and reuses duplicate open requests instead of launching a second context.
- Profile storage directories are path-safe and live under `BROWSER_PROFILE_STORAGE_ROOT` (`.profiles` by default).
- Current MVP stores profile records and profile-proxy assignments in-process; persistent profile metadata should move into the shared Supabase database in the next step. Active browser sessions should stay process-local.

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
