from __future__ import annotations

from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.settings import Settings


def create_repository(settings: Settings) -> AutomationRepository:
    if settings.database_backend == "memory":
        return MemoryRepository()
    if settings.database_backend == "supabase":
        if not settings.supabase_url or not settings.supabase_service_role_key:
            return MemoryRepository()
        from account_automation_lab.repositories.supabase import SupabaseRepository

        return SupabaseRepository(settings)
    raise ValueError(f"Unsupported DATABASE_BACKEND={settings.database_backend!r}")
