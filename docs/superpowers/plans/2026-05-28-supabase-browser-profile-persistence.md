# Supabase Browser Profile Persistence Follow-Up Plan

**Goal:** Align the profile cockpit with shared Supabase persistence while keeping active browser sessions process-local.

**Scope:** Persist durable browser profile metadata only. Do not persist active browser contexts, session handles, raw proxy usernames, raw proxy passwords, or full proxy URLs with credentials.

## Tasks

- Seed or upsert `automation_sites` from the configured site adapters so profile rows can reference stable site records.
- Seed or upsert `automation_sims` from the configured SIM inventory so profile rows can reference stable SIM records.
- Persist `automation_profiles` fields for cockpit state: profile id, SIM reference, site reference, `name`, `runtime`, `tags`, `notes`, and `updated_at`.
- Load profile rows from Supabase at startup when Supabase is configured; keep the current in-process defaults for local memory-only mode.
- Save profile create/update operations back to Supabase when Supabase is configured.
- Keep active CloakBrowser sessions and Playwright context handles process-local; recompute session status from the running `BrowserSessionManager`.
- Store only masked or provider reference data for proxy assignments. Never store raw proxy credentials in Supabase.
- Document migration behavior and the local memory fallback after implementation.

## Verification

- Confirm a restarted app reloads profile names, runtime, tags, and notes from Supabase.
- Confirm open browser sessions do not survive a process restart as persisted state.
- Confirm Supabase rows do not contain raw proxy usernames, passwords, or credential-bearing URLs.
