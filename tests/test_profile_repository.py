from __future__ import annotations

import pytest

from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    ProfileStatus,
)
from account_automation_lab.repositories.memory import MemoryRepository


@pytest.mark.asyncio
async def test_memory_repo_creates_and_lists_profiles() -> None:
    repo = MemoryRepository()
    profile = BrowserProfile(id="p1", name="P1", storage_dir="C:/p/p1")

    created = await repo.create_profile(profile)
    listed = await repo.list_profiles()

    assert created.id == "p1"
    assert [p.id for p in listed] == ["p1"]
    assert await repo.get_profile("p1") == created
    assert await repo.get_profile("missing") is None


@pytest.mark.asyncio
async def test_memory_repo_updates_profile_fields() -> None:
    repo = MemoryRepository()
    await repo.create_profile(BrowserProfile(id="p1", name="P1", storage_dir="C:/p/p1"))

    updated = await repo.update_profile(
        "p1", BrowserProfileUpdate(name="Renamed", status=ProfileStatus.ARCHIVED)
    )

    assert updated.name == "Renamed"
    assert updated.status == ProfileStatus.ARCHIVED
    assert updated.storage_dir == "C:/p/p1"  # unchanged


@pytest.mark.asyncio
async def test_memory_repo_update_missing_profile_raises() -> None:
    repo = MemoryRepository()
    with pytest.raises(KeyError):
        await repo.update_profile("missing", BrowserProfileUpdate(name="x"))


@pytest.mark.asyncio
async def test_memory_repo_deletes_profile() -> None:
    repo = MemoryRepository()
    await repo.create_profile(BrowserProfile(id="p1", name="P1", storage_dir="C:/p/p1"))

    await repo.delete_profile("p1")

    assert await repo.list_profiles() == []


@pytest.mark.asyncio
async def test_memory_repo_group_crud() -> None:
    repo = MemoryRepository()

    group = await repo.create_profile_group(ProfileGroupCreate(name="FB", color="#3b5"))
    assert group.name == "FB"

    updated = await repo.update_profile_group(group.id, ProfileGroupUpdate(name="Facebook"))
    assert updated.name == "Facebook"
    assert updated.color == "#3b5"

    assert [g.id for g in await repo.list_profile_groups()] == [group.id]

    await repo.delete_profile_group(group.id)
    assert await repo.list_profile_groups() == []


@pytest.mark.asyncio
async def test_memory_repo_seeds_example_site_and_supports_site_crud() -> None:
    from account_automation_lab.models import SiteCreate, SiteUpdate

    repo = MemoryRepository()

    seeded = await repo.list_sites()
    assert any(s.key == "example" and s.has_code_adapter for s in seeded)

    created = await repo.create_site(
        SiteCreate(key="acme", display_name="Acme", base_url="https://acme.test/signup")
    )
    assert created.key == "acme"
    assert created.has_code_adapter is False

    updated = await repo.update_site("acme", SiteUpdate(display_name="Acme Inc", enabled=False))
    assert updated.display_name == "Acme Inc"
    assert updated.enabled is False

    await repo.delete_site("acme")
    assert await repo.get_site("acme") is None


@pytest.mark.asyncio
async def test_memory_repo_rejects_duplicate_site_key() -> None:
    from account_automation_lab.models import SiteCreate
    from account_automation_lab.repositories.memory import SiteExistsError

    repo = MemoryRepository()
    await repo.create_site(SiteCreate(key="dup", display_name="Dup", base_url="https://d.test"))
    with pytest.raises(SiteExistsError):
        await repo.create_site(SiteCreate(key="dup", display_name="Dup2", base_url="https://d2.test"))
