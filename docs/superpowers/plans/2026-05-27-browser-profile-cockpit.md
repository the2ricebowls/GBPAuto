# Browser Profile Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current automation dashboard into an AdsPower-style profile cockpit for internal authorized browser profiles.

**Architecture:** Add a memory-backed browser profile store and a CloakBrowser session manager with one active context per profile. Expose FastAPI endpoints for profile/session lifecycle, then rebuild the NiceGUI shell around profiles, sessions, jobs, proxies, sites, and settings.

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, CloakBrowser, pytest, ruff, mypy.

---

### Task 1: Browser Profile Domain

**Files:**
- Modify: `src/account_automation_lab/models.py`
- Create: `src/account_automation_lab/browser/profiles.py`
- Test: `tests/test_browser_profiles.py`

- [ ] Write tests for default profile creation, path-safe storage directories, opening one CloakBrowser context per profile, duplicate-open reuse, and close cleanup.
- [ ] Implement profile/session models, a memory profile store, and `BrowserSessionManager`.
- [ ] Run `python -m uv run pytest tests/test_browser_profiles.py -q`.

### Task 2: FastAPI Endpoints

**Files:**
- Modify: `src/account_automation_lab/api/__init__.py`
- Test: `tests/test_browser_profile_api.py`

- [ ] Write API tests for listing profiles, creating a profile, opening a session, listing sessions, and closing a session.
- [ ] Inject profile store/session manager through `create_app`.
- [ ] Add `/api/browser-profiles`, `/api/browser-profiles/{profile_id}/open`, `/api/browser-profiles/{profile_id}/close`, and `/api/browser-sessions`.
- [ ] Run `python -m uv run pytest tests/test_browser_profile_api.py -q`.

### Task 3: NiceGUI Profile Cockpit

**Files:**
- Modify: `src/account_automation_lab/ui/pages.py`
- Modify: `README.md`
- Modify: `.env.example`

- [ ] Reframe the UI around profile management: profile table, active session table, job table, proxy controls, and secret health.
- [ ] Wire profile buttons to the new API-level store/session services in-process.
- [ ] Document the profile cockpit and CloakBrowser storage root.

### Task 4: Verification

- [ ] Run `python -m uv run pytest -q`.
- [ ] Run `python -m uv run ruff check .`.
- [ ] Run `python -m uv run mypy src tests`.
- [ ] Start the app, open the UI, verify no horizontal overflow, and smoke test queue/open/close flows with a fake-safe profile where possible.
