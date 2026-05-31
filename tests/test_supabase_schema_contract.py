from pathlib import Path

from account_automation_lab.repositories.supabase import (
    AUTOMATION_JOB_EVENTS_TABLE,
    AUTOMATION_JOBS_TABLE,
)


def test_supabase_repository_uses_automation_prefixed_tables() -> None:
    schema = Path("supabase/schema.sql").read_text(encoding="utf-8")

    assert f"create table if not exists public.{AUTOMATION_JOBS_TABLE}" in schema
    assert f"create table if not exists public.{AUTOMATION_JOB_EVENTS_TABLE}" in schema
    assert AUTOMATION_JOBS_TABLE == "automation_jobs"
    assert AUTOMATION_JOB_EVENTS_TABLE == "automation_job_events"


def test_shared_schema_namespaces_automation_tables() -> None:
    schema = Path("supabase/schema.sql").read_text(encoding="utf-8")

    assert "create table if not exists public.automation_sites" in schema
    assert "create table if not exists public.automation_sims" in schema
    assert "create table if not exists public.automation_proxies" in schema
    assert "create table if not exists public.sites" not in schema
    assert "create table if not exists public.sims" not in schema
    assert "create table if not exists public.proxies" not in schema
