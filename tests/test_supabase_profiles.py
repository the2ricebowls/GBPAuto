from __future__ import annotations

from typing import Any

import pytest

from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    ProfileGroupCreate,
)


class _FakeQuery:
    def __init__(self, table: _FakeTable) -> None:
        self._table = table
        self._filters: dict[str, Any] = {}
        self._op: str | None = None
        self._payload: Any = None

    def select(self, *_: str) -> _FakeQuery:
        self._op = "select"
        return self

    def insert(self, payload: Any) -> _FakeQuery:
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: Any) -> _FakeQuery:
        self._op = "update"
        self._payload = payload
        return self

    def delete(self) -> _FakeQuery:
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any) -> _FakeQuery:
        self._filters[column] = value
        return self

    def order(self, *_: str, **__: Any) -> _FakeQuery:
        return self

    def limit(self, *_: int) -> _FakeQuery:
        return self

    def execute(self) -> Any:
        rows = self._table.rows
        if self._op == "insert":
            self._table.rows.append(dict(self._payload))
            return type("R", (), {"data": [dict(self._payload)]})
        if self._op == "update":
            matched = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
            for r in matched:
                r.update(self._payload)
            return type("R", (), {"data": [dict(r) for r in matched]})
        if self._op == "delete":
            self._table.rows = [
                r for r in rows if not all(r.get(k) == v for k, v in self._filters.items())
            ]
            return type("R", (), {"data": []})
        matched = [r for r in rows if all(r.get(k) == v for k, v in self._filters.items())]
        return type("R", (), {"data": [dict(r) for r in matched]})


class _FakeTable:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []


class _FakeClient:
    def __init__(self) -> None:
        self._tables: dict[str, _FakeTable] = {}

    def table(self, name: str) -> _FakeQuery:
        tbl = self._tables.setdefault(name, _FakeTable())
        return _FakeQuery(tbl)


def _make_repo() -> Any:
    from account_automation_lab.repositories.supabase import SupabaseRepository

    repo = SupabaseRepository.__new__(SupabaseRepository)
    repo._client = _FakeClient()  # type: ignore[assignment]
    return repo


@pytest.mark.asyncio
async def test_supabase_profile_create_and_get() -> None:
    repo = _make_repo()
    profile = BrowserProfile(id="p1", name="P1", storage_dir="C:/p/p1")

    created = await repo.create_profile(profile)
    fetched = await repo.get_profile("p1")

    assert created.id == "p1"
    assert fetched is not None
    assert fetched.name == "P1"
    assert await repo.get_profile("missing") is None


@pytest.mark.asyncio
async def test_supabase_profile_update_and_delete() -> None:
    repo = _make_repo()
    await repo.create_profile(BrowserProfile(id="p1", name="P1", storage_dir="C:/p/p1"))

    updated = await repo.update_profile("p1", BrowserProfileUpdate(name="Renamed"))
    assert updated.name == "Renamed"

    await repo.delete_profile("p1")
    assert await repo.get_profile("p1") is None


@pytest.mark.asyncio
async def test_supabase_group_create_and_list() -> None:
    repo = _make_repo()
    group = await repo.create_profile_group(ProfileGroupCreate(name="FB"))
    groups = await repo.list_profile_groups()
    assert group.name == "FB"
    assert [g.id for g in groups] == [group.id]
