import pytest

from account_automation_lab.profiles import ProfileLockRegistry


@pytest.mark.asyncio
async def test_profile_lock_registry_prevents_parallel_profile_runs() -> None:
    registry = ProfileLockRegistry()

    first = await registry.try_acquire("profile-1")
    second = await registry.try_acquire("profile-1")

    assert first is not None
    assert second is None

    await first.release()
    third = await registry.try_acquire("profile-1")

    assert third is not None
    await third.release()
