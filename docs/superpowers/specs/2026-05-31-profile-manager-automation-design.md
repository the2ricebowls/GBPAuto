# Profile Manager + Automation Engine — Design

Date: 2026-05-31
Status: Approved (pending written-spec review)

## Goal

Turn the existing internal "account automation lab" into a personal anti-detect
browser profile manager (in the spirit of AdsPower / GPM / MultiLogin / Dolphin)
combined with a step-based automation engine.

This spec covers the **first stage only**: a local, single-user web app that runs
smoothly. Multi-user (B) and desktop `.exe` packaging (C) come later.

### In scope (this spec)

1. Persistent storage on Supabase for profiles, fingerprint config, groups, tags,
   and profile-proxy references.
2. Full profile manager: API + UI CRUD (create/edit/delete/clone), groups and tags,
   fingerprint configuration faithful to CloakBrowser, proxy assignment, open/close
   headed sessions.
3. Step-based workflow engine with reusable primitive steps, an extended job state
   machine (`WAITING_HUMAN`), and human-in-the-loop handling.
4. Updated NiceGUI cockpit: AdsPower-style profile management screen and a job
   control panel with Resume / Pause / Cancel.

### Out of scope (later stages)

- Multi-user / authentication (stage B).
- Desktop `.exe` packaging — later this only runs the background server; the UI
  stays a localhost web app (stage C).
- No-code workflow definitions (JSON/YAML).
- In-browser remote control / screencast of the CloakBrowser window.
- Real per-site automation logic for production websites.
- Automated CAPTCHA solving.

## Non-negotiable constraints

- **Secrets never land in database rows.** Supabase service-role key and proxy
  username/password stay in the runtime / environment. The DB stores only an
  `idproxy` reference and a masked proxy string (`ip:port:***:***`), matching the
  existing masking behaviour.
- **Repository pattern is preserved.** All data access goes through the
  `AutomationRepository` interface. The default backend changes from `memory` to
  `supabase`. `memory` remains for tests (fast, no network).
- **Fingerprint fields must be real.** Every field in the profile fingerprint
  config must actually be applied by CloakBrowser. No decorative fields.
- **Online dependency is accepted.** Choosing Supabase means the app needs network
  access. Connection failures must be surfaced clearly (Settings page health,
  no crash), not hidden.

## Stage 1 — Architecture & storage

Single FastAPI + NiceGUI process (unchanged topology). Default storage backend
switches to Supabase.

```
Web UI (NiceGUI) ──┐
                   ├──► FastAPI (same process)
HTTP API  ─────────┘         │
                             ├─► ProfileService ──► Repository ──► Supabase (automation_* tables)
                             ├─► ProxyManager   ──► Repository ──► Supabase
                             ├─► WorkflowEngine ──► JobRunner (APScheduler + asyncio.Queue)
                             │        │
                             │        └─► SessionManager ──► CloakBrowser (headed, 1 context/profile)
                             └─► OTP provider ──► Supabase otp_messages
```

- One profile = one persistent CloakBrowser storage directory under
  `BROWSER_PROFILE_STORAGE_ROOT` (existing) + one metadata row in Supabase. The
  directory path is stored; the directory contents are not in the DB.
- `memory` backend keeps full feature parity for profiles/groups so tests do not
  touch the network.

## Stage 2 — Profile data model & Supabase schema

### `BrowserProfile`

```
BrowserProfile
├─ id              ── uuid (primary key). (sim_id, site_key) are optional attributes, not the key.
├─ name
├─ group_id        ── optional, references automation_profile_groups
├─ tags[]
├─ notes
├─ sim_id          ── optional, links a SIM for OTP
├─ site_key        ── optional
├─ runtime         ── cloakbrowser | playwright_chromium
├─ storage_dir     ── persistent profile directory
├─ startup_url     ── optional
├─ status          ── active | archived
├─ fingerprint: FingerprintConfig
│    ├─ platform         ── windows | macos   (CloakBrowser --fingerprint-platform)
│    ├─ seed             ── int (fixed) | null (random per launch)  (--fingerprint=)
│    ├─ timezone         ── IANA, e.g. "Asia/Ho_Chi_Minh" | null
│    ├─ locale           ── BCP47, e.g. "vi-VN" | null
│    ├─ color_scheme     ── light | dark | no-preference | null
│    ├─ user_agent       ── null = engine-generated
│    ├─ viewport         ── {width, height} | null (use OS window size)
│    ├─ geoip_from_proxy ── bool (derive timezone/locale from proxy exit IP)
│    └─ extension_paths[]
├─ created_at / updated_at
```

All `FingerprintConfig` fields map to confirmed CloakBrowser launch parameters
(`platform`, `seed`, `timezone`, `locale`, `color_scheme`, `user_agent`,
`viewport`, `geoip`, `extension_paths`).

### Groups & tags

- New table `automation_profile_groups (id, name, color, created_at)`.
- A profile belongs to at most one group (`group_id` nullable); tags are a text
  array on the profile.

### Schema changes (`supabase/schema.sql`, idempotent)

- `automation_profiles`: add columns `name`, `group_id`, `tags text[]`, `notes`,
  `runtime`, `startup_url`, `status`, `fingerprint jsonb` via
  `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`.
- Drop the `NOT NULL` requirement / `automation_sites` FK on `site_key`; make
  `site_key` and `sim_id` nullable (a profile is an independent unit).
- Add `automation_profile_groups`.
- `automation_proxies` already stores per-profile proxy references (masked
  `proxy_url` + policy + status + expires_at, no user/pass).

## Stage 3 — Workflow engine & job model

### Extended job state machine

```
QUEUED ─► RUNNING ─► SUCCEEDED
                 ├─► FAILED
                 ├─► WAITING_CAPTCHA ─► RUNNING
                 ├─► WAITING_HUMAN  ─► RUNNING        (operator presses "Resume")
                 └─► (any live state) ─► CANCELLED
WAITING_HUMAN ─► FAILED / CANCELLED
```

`WAITING_HUMAN` is a live (non-terminal) state. The job keeps its open browser
session and waits.

### Core concepts

**WorkflowContext** — passed to every step:
- `job`, `profile`, `site` spec
- `page` / `context` — the controlled CloakBrowser tab
- `repo` (event logging), `otp_provider`, `session_manager` (for `read_from`)
- assigned `proxy`

**Step** — `async def (ctx) -> None`. The engine runs a workflow's steps in order.

Primitive steps:

| Step | Purpose |
|---|---|
| `goto(url)` | navigate (enforces the site host allowlist) |
| `fill(selector, value)` / `click(selector)` | DOM actions |
| `wait_for(selector \| seconds)` | wait for element/time |
| `get_otp(sender_hints, timeout)` | wait for OTP from `otp_messages` (existing logic) |
| `wait_for_human(checkpoint, message)` | set job `WAITING_HUMAN`, show UI prompt, wait for Resume/Cancel |
| `read_from(profile_id, fn)` | read data from another open profile's session/tab |
| `emit(event_type, message, payload)` | record a job event |

**Workflow** — a function returning a list of steps (or an async generator). Each
site adapter defines its workflow. Mock adapter for illustration:
`goto → fill → click → get_otp → wait_for_human → emit succeeded`.

### Human-in-the-loop (three triggers)

1. **Code-initiated**: `wait_for_human(...)` sets `WAITING_HUMAN`, creates a
   checkpoint (event + a Future/Event held by the engine), and blocks until resume.
2. **On error**: if a step raises, the engine catches it, records `job.error`, and
   (default behaviour) transitions to `WAITING_HUMAN` instead of `FAILED`, so the
   operator can fix it by hand in the browser window and choose Retry-step /
   Resume / Cancel. A flag can force fail-fast instead.
3. **Operator-initiated**: a UI "Pause" button stops the job at the boundary
   between steps (never mid-action) and transitions to `WAITING_HUMAN`.

Resume/pause API: `POST /api/jobs/{id}/resume`, `POST /api/jobs/{id}/pause`.
Resume completes the awaited Future so the next step runs. Because a waiting job
keeps its browser session open, manual interaction in the window is valid.

### Session retention while waiting

A job in `WAITING_HUMAN` **holds a worker slot** while waiting (it keeps the
browser + the workflow's in-flight state). Worker behaviour: run steps in order;
on `wait_for_human`, `await` the checkpoint's `asyncio.Event`. Consequence: a
waiting job counts toward `max_global_concurrency`. Accepted for the local,
single-user stage — it keeps the browser session and workflow state intact, which
is simpler and more correct than serialising/replaying the workflow.

## Stage 4 — API & UI

### API (new / changed)

Profiles (full CRUD, replacing the current static list):
```
GET    /api/browser-profiles                 # list, filter by group/tag/status
POST   /api/browser-profiles                 # create (with fingerprint config)
GET    /api/browser-profiles/{id}            # detail
PATCH  /api/browser-profiles/{id}            # edit name/group/tags/notes/fingerprint/proxy
DELETE /api/browser-profiles/{id}            # delete (with optional storage-dir removal flag)
POST   /api/browser-profiles/{id}/clone      # clone (new seed, new storage dir)
POST   /api/browser-profiles/{id}/open       # open headed session
POST   /api/browser-profiles/{id}/close
```

Groups:
```
GET/POST/PATCH/DELETE  /api/profile-groups
```

Jobs (human-in-the-loop additions):
```
POST /api/jobs/{id}/pause      # → WAITING_HUMAN at a step boundary
POST /api/jobs/{id}/resume     # continue
POST /api/jobs/{id}/cancel     # existing
GET  /api/jobs/{id}/checkpoint # what the current checkpoint is waiting on (if any)
```

### UI (NiceGUI cockpit → AdsPower-style management)

- **Profiles** (main screen): left sidebar is the Group tree; right table lists
  profiles with columns Name / Group / Tags / Proxy (masked) / Session / SIM /
  Updated. Each row has quick actions Open / Close / Run / Edit / Clone / Delete.
  A "＋ Create profile" button opens a multi-section **config dialog**: Basic
  (name, group, tags, notes, startup URL) · Fingerprint (platform, fixed/random
  seed, timezone, locale, color scheme, user-agent, viewport, geoip-from-proxy,
  extensions) · Proxy (assign/rotate/buy, geoip). The same dialog is reused for
  Edit.
- **Jobs**: job table + events (as today) plus **Resume / Pause / Cancel**
  buttons. A `WAITING_HUMAN` job is highlighted (warning colour) with a
  "Waiting: <checkpoint message>" line.
- **Sessions**: open browser contexts (kept; add Close button).
- **Proxies / Sites / Settings**: kept; Settings adds Supabase connection health
  (now the primary backend).

## Testing

- Unit: model + fingerprint→CloakBrowser args mapping; repository (memory) for
  profile/group CRUD; job state machine with `WAITING_HUMAN`; each primitive step
  with a fake page; engine running a full workflow plus pause/resume/error→waiting
  scenarios.
- API: profile CRUD, clone, pause/resume/cancel (`TestClient` + memory repo, no
  real network).
- Schema contract: assert the new columns/tables exist in `schema.sql`.
- Supabase repository (runs through `asyncio.to_thread`) tested with a fake
  client — no real Supabase calls in tests.

## Migration notes

- Existing in-process seeded profiles (`sim-a:site_NN`) are replaced by
  Supabase-backed, uuid-keyed profiles. On first run against a fresh schema there
  are no profiles; the user creates them via the UI/API.
- `schema.sql` stays idempotent so it can be re-run on the existing shared
  Supabase project without breaking the SMS Forwarder tables.
- `DATABASE_BACKEND` default flips to `supabase`; `memory` stays available for
  local dev/tests via env override.
