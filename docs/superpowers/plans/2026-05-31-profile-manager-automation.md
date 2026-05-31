# Profile Manager + Automation Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the internal automation lab into a local, single-user anti-detect browser profile manager (AdsPower-style) with a step-based automation engine and human-in-the-loop support, backed by Supabase.

**Architecture:** Single FastAPI + NiceGUI process. All data access goes through the `AutomationRepository` interface (memory backend for tests, Supabase for runtime). Profiles become uuid-keyed independent units with a `FingerprintConfig` that maps to real CloakBrowser launch flags. A workflow engine runs site adapters as ordered async steps; jobs can enter a live `WAITING_HUMAN` state that holds the browser session open until the operator resumes.

**Tech Stack:** Python 3.12, FastAPI, NiceGUI, Pydantic v2, CloakBrowser (Playwright-compatible), APScheduler, Supabase, pytest/pytest-asyncio, mypy (strict), ruff.

**Reference spec:** `docs/superpowers/specs/2026-05-31-profile-manager-automation-design.md`

---

## Conventions for every task

- This environment's interactive shell often does not return a prompt even though
  commands run. Run test/lint commands by redirecting output to a file and reading
  it, e.g.:
  `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -q tests/PATH 2>&1 | Out-File -FilePath .tmp\out.log -Encoding utf8` then read `.tmp\out.log`.
- Type check: `.\.venv\Scripts\mypy.exe 2>&1 | Out-File -FilePath .tmp\mypy.log -Encoding utf8`.
- Lint: `.\.venv\Scripts\ruff.exe check . 2>&1 | Out-File -FilePath .tmp\ruff.log -Encoding utf8`.
- Delete temporary `.tmp\*.log` files at the end of a task; they are not gitignored.
- mypy runs in strict mode over `src` and `tests`. Every function needs type
  annotations. Keep ruff clean (line length 100).
- Do not commit secrets. Do not commit `.tmp` logs.

---

## File structure

Files created or modified across the plan:

- `src/account_automation_lab/models.py` — Modify: add `FingerprintConfig`,
  `ProfileGroup*`, extend `BrowserProfile*`, add `WAITING_HUMAN` + checkpoint models.
- `src/account_automation_lab/jobs/state.py` — Modify: add `WAITING_HUMAN`
  transitions.
- `src/account_automation_lab/browser/runtime.py` — Modify: extend
  `BrowserProfileConfig` with fingerprint fields; map them to CloakBrowser kwargs.
- `src/account_automation_lab/browser/fingerprint.py` — Create: pure mapping from
  `FingerprintConfig` to CloakBrowser launch kwargs.
- `src/account_automation_lab/repositories/base.py` — Modify: add profile/group
  methods to the protocol.
- `src/account_automation_lab/repositories/memory.py` — Modify: implement
  profile/group CRUD in memory.
- `src/account_automation_lab/repositories/supabase.py` — Modify: implement
  profile/group CRUD against Supabase.
- `src/account_automation_lab/browser/profiles.py` — Modify: `BrowserProfileStore`
  becomes repository-backed; add update/delete/clone.
- `src/account_automation_lab/workflows/__init__.py` — Create.
- `src/account_automation_lab/workflows/context.py` — Create: `WorkflowContext`.
- `src/account_automation_lab/workflows/steps.py` — Create: primitive steps.
- `src/account_automation_lab/workflows/engine.py` — Create: `WorkflowEngine`,
  checkpoint registry.
- `src/account_automation_lab/jobs/runner.py` — Modify: drive workflows, support
  pause/resume.
- `src/account_automation_lab/adapters/base.py` — Modify: adapters expose a
  `workflow(ctx)` returning steps; mock adapter demonstrates the flow.
- `src/account_automation_lab/api/__init__.py` — Modify: profile CRUD/clone, group
  CRUD, job pause/resume/checkpoint endpoints.
- `src/account_automation_lab/ui/pages.py` — Modify: AdsPower-style profile screen,
  job controls.
- `src/account_automation_lab/settings.py` — Modify: default `database_backend` →
  `supabase`.
- `supabase/schema.sql` — Modify: extend `automation_profiles`, add
  `automation_profile_groups`.
- `tests/test_*.py` — Create/Modify per task.

---

## Task 1: FingerprintConfig and ProfileGroup models

**Files:**
- Modify: `src/account_automation_lab/models.py`
- Test: `tests/test_profile_models.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_models.py`:

```python
from __future__ import annotations

from account_automation_lab.models import (
    FingerprintConfig,
    FingerprintPlatform,
    ProfileGroup,
    ProfileStatus,
)


def test_fingerprint_config_defaults_are_neutral() -> None:
    fp = FingerprintConfig()
    assert fp.platform == FingerprintPlatform.WINDOWS
    assert fp.seed is None
    assert fp.timezone is None
    assert fp.locale is None
    assert fp.color_scheme is None
    assert fp.user_agent is None
    assert fp.viewport is None
    assert fp.geoip_from_proxy is False
    assert fp.extension_paths == []


def test_fingerprint_config_round_trips_through_dict() -> None:
    fp = FingerprintConfig(
        platform=FingerprintPlatform.MACOS,
        seed=12345,
        timezone="Asia/Ho_Chi_Minh",
        locale="vi-VN",
        color_scheme="dark",
        viewport={"width": 1280, "height": 720},
        geoip_from_proxy=True,
        extension_paths=["C:/ext/one"],
    )
    restored = FingerprintConfig.model_validate(fp.model_dump())
    assert restored == fp


def test_profile_group_has_defaults() -> None:
    group = ProfileGroup(name="Facebook farm")
    assert group.id
    assert group.name == "Facebook farm"
    assert group.color is None


def test_profile_status_values() -> None:
    assert ProfileStatus.ACTIVE == "active"
    assert ProfileStatus.ARCHIVED == "archived"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -q tests/test_profile_models.py 2>&1 | Out-File -FilePath .tmp\out.log -Encoding utf8`
Expected: FAIL — `ImportError: cannot import name 'FingerprintConfig'`.

- [ ] **Step 3: Add the models**

In `src/account_automation_lab/models.py`, add these enums and models (place the
enums near the other `StrEnum` definitions, and the models near `BrowserProfile`):

```python
class FingerprintPlatform(StrEnum):
    WINDOWS = "windows"
    MACOS = "macos"


class ProfileStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


class FingerprintConfig(BaseModel):
    platform: FingerprintPlatform = FingerprintPlatform.WINDOWS
    seed: int | None = None
    timezone: str | None = None
    locale: str | None = None
    color_scheme: str | None = None
    user_agent: str | None = None
    viewport: dict[str, int] | None = None
    geoip_from_proxy: bool = False
    extension_paths: list[str] = Field(default_factory=list)


class ProfileGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    color: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class ProfileGroupCreate(BaseModel):
    name: str
    color: str | None = None


class ProfileGroupUpdate(BaseModel):
    name: str | None = None
    color: str | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -q tests/test_profile_models.py 2>&1 | Out-File -FilePath .tmp\out.log -Encoding utf8`
Expected: PASS — 4 passed.

- [ ] **Step 5: Type check + lint**

Run mypy and ruff (see Conventions). Expected: no issues. Delete `.tmp\*.log`.

- [ ] **Step 6: Commit**

```bash
git add src/account_automation_lab/models.py tests/test_profile_models.py
git commit -m "feat: add FingerprintConfig and ProfileGroup models"
```

---

## Task 2: Extend BrowserProfile model to uuid-keyed independent unit

**Files:**
- Modify: `src/account_automation_lab/models.py`
- Test: `tests/test_profile_models.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_profile_models.py`:

```python
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    RuntimeKind,
)


def test_browser_profile_create_allows_optional_sim_and_site() -> None:
    payload = BrowserProfileCreate(name="My profile")
    assert payload.name == "My profile"
    assert payload.sim_id is None
    assert payload.site_key is None
    assert payload.group_id is None
    assert payload.tags == []
    assert payload.fingerprint.platform.value == "windows"
    assert payload.runtime == RuntimeKind.CLOAKBROWSER


def test_browser_profile_has_uuid_id_and_status() -> None:
    profile = BrowserProfile(
        id="11111111-1111-1111-1111-111111111111",
        name="P1",
        storage_dir="C:/profiles/p1",
    )
    assert profile.status.value == "active"
    assert profile.sim_id is None
    assert profile.fingerprint.platform.value == "windows"


def test_browser_profile_update_is_all_optional() -> None:
    update = BrowserProfileUpdate()
    assert update.model_dump(exclude_unset=True) == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run the file (see Conventions). Expected: FAIL — `BrowserProfileUpdate` import error
and/or `BrowserProfileCreate` rejects missing `sim_id`/`site_key`.

- [ ] **Step 3: Update the models**

In `src/account_automation_lab/models.py`, replace `BrowserProfileCreate` and
`BrowserProfile` with these definitions and add `BrowserProfileUpdate`:

```python
class BrowserProfileCreate(BaseModel):
    id: str | None = None
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    startup_url: str | None = None
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)


class BrowserProfileUpdate(BaseModel):
    name: str | None = None
    group_id: str | None = None
    tags: list[str] | None = None
    notes: str | None = None
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind | None = None
    startup_url: str | None = None
    status: ProfileStatus | None = None
    fingerprint: FingerprintConfig | None = None


class BrowserProfile(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind = RuntimeKind.CLOAKBROWSER
    storage_dir: str
    startup_url: str | None = None
    status: ProfileStatus = ProfileStatus.ACTIVE
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
```

Also update `BrowserProfileView` to add the new display fields:

```python
class BrowserProfileView(BaseModel):
    id: str
    name: str
    group_id: str | None = None
    tags: list[str] = Field(default_factory=list)
    sim_id: str | None = None
    site_key: str | None = None
    runtime: RuntimeKind
    storage_dir: str
    status: ProfileStatus = ProfileStatus.ACTIVE
    fingerprint: FingerprintConfig = Field(default_factory=FingerprintConfig)
    proxy_assigned: bool = False
    proxy: str | None = None
    session_status: BrowserSessionStatus = BrowserSessionStatus.IDLE
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS. (Other modules may now have type errors — that is
expected and fixed in later tasks. Do NOT run the full suite yet.)

- [ ] **Step 5: Commit**

```bash
git add src/account_automation_lab/models.py tests/test_profile_models.py
git commit -m "feat: make BrowserProfile a uuid-keyed independent unit"
```

---

## Task 3: Add WAITING_HUMAN to the job state machine

**Files:**
- Modify: `src/account_automation_lab/models.py` (add enum value)
- Modify: `src/account_automation_lab/jobs/state.py`
- Test: `tests/test_job_state.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_job_state.py`:

```python
def test_waiting_human_transitions() -> None:
    assert can_transition(JobStatus.RUNNING, JobStatus.WAITING_HUMAN)
    assert can_transition(JobStatus.WAITING_HUMAN, JobStatus.RUNNING)
    assert can_transition(JobStatus.WAITING_HUMAN, JobStatus.FAILED)
    assert can_transition(JobStatus.WAITING_HUMAN, JobStatus.CANCELLED)
    assert not can_transition(JobStatus.WAITING_HUMAN, JobStatus.SUCCEEDED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `...pytest ... tests/test_job_state.py ...`
Expected: FAIL — `AttributeError: WAITING_HUMAN`.

- [ ] **Step 3: Implement**

In `models.py`, add to `JobStatus` (after `WAITING_CAPTCHA`):

```python
    WAITING_HUMAN = "waiting_human"
```

In `jobs/state.py`, update `_ALLOWED_TRANSITIONS`:

```python
_ALLOWED_TRANSITIONS: dict[JobStatus, set[JobStatus]] = {
    JobStatus.QUEUED: {JobStatus.RUNNING, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.WAITING_CAPTCHA,
        JobStatus.WAITING_HUMAN,
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    },
    JobStatus.WAITING_CAPTCHA: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.WAITING_HUMAN: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.SUCCEEDED: set(),
    JobStatus.FAILED: set(),
    JobStatus.CANCELLED: set(),
}
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS (both new and existing job-state tests).

- [ ] **Step 5: Commit**

```bash
git add src/account_automation_lab/models.py src/account_automation_lab/jobs/state.py tests/test_job_state.py
git commit -m "feat: add WAITING_HUMAN job state"
```

---

## Task 4: Fingerprint → CloakBrowser kwargs mapping

**Files:**
- Create: `src/account_automation_lab/browser/fingerprint.py`
- Test: `tests/test_fingerprint_mapping.py` (create)

This is a pure function so it can be unit-tested without launching a browser.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fingerprint_mapping.py`:

```python
from __future__ import annotations

from account_automation_lab.browser.fingerprint import fingerprint_launch_kwargs
from account_automation_lab.models import FingerprintConfig, FingerprintPlatform


def test_empty_fingerprint_produces_minimal_kwargs() -> None:
    kwargs = fingerprint_launch_kwargs(FingerprintConfig())
    assert kwargs == {"geoip": False}


def test_full_fingerprint_maps_each_field() -> None:
    fp = FingerprintConfig(
        platform=FingerprintPlatform.MACOS,
        seed=42,
        timezone="Asia/Ho_Chi_Minh",
        locale="vi-VN",
        color_scheme="dark",
        user_agent="UA/1.0",
        viewport={"width": 1280, "height": 720},
        geoip_from_proxy=True,
    )
    kwargs = fingerprint_launch_kwargs(fp)
    assert kwargs["timezone"] == "Asia/Ho_Chi_Minh"
    assert kwargs["locale"] == "vi-VN"
    assert kwargs["color_scheme"] == "dark"
    assert kwargs["user_agent"] == "UA/1.0"
    assert kwargs["viewport"] == {"width": 1280, "height": 720}
    assert kwargs["geoip"] is True
    # platform + seed go through extra Chromium args
    assert "--fingerprint-platform=macos" in kwargs["args"]
    assert "--fingerprint=42" in kwargs["args"]


def test_seed_omitted_when_none() -> None:
    kwargs = fingerprint_launch_kwargs(FingerprintConfig(seed=None))
    assert "args" not in kwargs or all("--fingerprint=" not in a for a in kwargs["args"])
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — module not found.

- [ ] **Step 3: Implement the mapping**

Create `src/account_automation_lab/browser/fingerprint.py`:

```python
from __future__ import annotations

from typing import Any

from account_automation_lab.models import FingerprintConfig


def fingerprint_launch_kwargs(fingerprint: FingerprintConfig) -> dict[str, Any]:
    """Translate a FingerprintConfig into CloakBrowser launch kwargs.

    Only fields CloakBrowser actually applies are emitted. ``platform`` and
    ``seed`` are passed as ``--fingerprint-*`` Chromium args; the rest map to
    dedicated launch parameters.
    """
    kwargs: dict[str, Any] = {"geoip": fingerprint.geoip_from_proxy}
    if fingerprint.timezone:
        kwargs["timezone"] = fingerprint.timezone
    if fingerprint.locale:
        kwargs["locale"] = fingerprint.locale
    if fingerprint.color_scheme:
        kwargs["color_scheme"] = fingerprint.color_scheme
    if fingerprint.user_agent:
        kwargs["user_agent"] = fingerprint.user_agent
    if fingerprint.viewport:
        kwargs["viewport"] = dict(fingerprint.viewport)

    args: list[str] = [f"--fingerprint-platform={fingerprint.platform.value}"]
    if fingerprint.seed is not None:
        args.append(f"--fingerprint={fingerprint.seed}")
    kwargs["args"] = args
    return kwargs
```

Note: `test_empty_fingerprint_produces_minimal_kwargs` expects `{"geoip": False}`
only. Adjust the implementation so `args` is omitted when it would contain just
the platform with no seed AND platform is the default — but the test expects no
`args` for an empty config. Resolve by only adding `args` when a non-default
platform or a seed is set:

```python
    args: list[str] = []
    if fingerprint.platform != FingerprintConfig().platform:
        args.append(f"--fingerprint-platform={fingerprint.platform.value}")
    if fingerprint.seed is not None:
        args.append(f"--fingerprint={fingerprint.seed}")
    if args:
        kwargs["args"] = args
    return kwargs
```

This makes the empty-config test (`{"geoip": False}`), the full-config test
(macos + seed both present in `args`), and the seed-omitted test all pass.

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS — 3 passed.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/browser/fingerprint.py tests/test_fingerprint_mapping.py
git commit -m "feat: map FingerprintConfig to CloakBrowser launch kwargs"
```

---

## Task 5: Wire fingerprint into BrowserProfileConfig and runtime

**Files:**
- Modify: `src/account_automation_lab/browser/runtime.py`
- Test: `tests/test_cloakbrowser_runtime.py` (extend)

First read `tests/test_cloakbrowser_runtime.py` to follow its existing fake-launcher
pattern (it captures `launch_kwargs`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cloakbrowser_runtime.py` (adapt imports to match the file):

```python
@pytest.mark.asyncio
async def test_cloakbrowser_runtime_passes_fingerprint_kwargs(tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    async def fake_launcher(**kwargs: object) -> str:
        captured.update(kwargs)
        return "context"

    runtime = CloakBrowserRuntime(Settings(), launcher=fake_launcher)
    config = BrowserProfileConfig(
        profile_id="p1",
        storage_dir=tmp_path / "profile",
        fingerprint_kwargs={
            "timezone": "Asia/Ho_Chi_Minh",
            "locale": "vi-VN",
            "args": ["--fingerprint=42"],
        },
    )
    await runtime.launch_context(config)

    assert captured["timezone"] == "Asia/Ho_Chi_Minh"
    assert captured["locale"] == "vi-VN"
    assert "--fingerprint=42" in cast(list[str], captured["args"])
```

(`BrowserProfileConfig`, `CloakBrowserRuntime`, `Settings`, `Path`, `cast`, and
`pytest` are already imported at the top of `test_cloakbrowser_runtime.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `BrowserProfileConfig` has no `fingerprint_kwargs`.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/browser/runtime.py`, extend `BrowserProfileConfig`:

```python
@dataclass(frozen=True)
class BrowserProfileConfig:
    profile_id: str
    storage_dir: Path
    proxy: str | dict[str, str] | None = None
    extension_paths: tuple[Path, ...] = ()
    fingerprint_kwargs: dict[str, Any] | None = None
```

In `CloakBrowserRuntime.launch_context`, merge fingerprint kwargs into
`launch_kwargs` after the base kwargs and before the `args`/viewport handling.
Fingerprint `args` must be appended to (not replace) the stealth/window args:

```python
        launch_kwargs: dict[str, Any] = {
            "user_data_dir": str(config.storage_dir),
            "headless": self.settings.cloakbrowser_headless,
            "proxy": config.proxy,
            "stealth_args": not self.settings.cloakbrowser_filter_no_sandbox,
            "humanize": self.settings.cloakbrowser_humanize,
            "extension_paths": [str(path) for path in config.extension_paths],
        }
        fingerprint_kwargs = dict(config.fingerprint_kwargs or {})
        fingerprint_args = fingerprint_kwargs.pop("args", [])
        # viewport from fingerprint overrides fit-screen default only if present
        fingerprint_viewport_set = "viewport" in fingerprint_kwargs
        launch_kwargs.update(fingerprint_kwargs)

        args = _cloakbrowser_args(self.settings) + list(fingerprint_args)
        if args:
            launch_kwargs["args"] = args
        if _should_fit_screen(self.settings) and not fingerprint_viewport_set:
            launch_kwargs["viewport"] = None
        return await launcher(**launch_kwargs)
```

(`Any` is already imported in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run the file (the whole `test_cloakbrowser_runtime.py`). Expected: PASS, including
the pre-existing runtime tests.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/browser/runtime.py tests/test_cloakbrowser_runtime.py
git commit -m "feat: pass fingerprint kwargs through CloakBrowser runtime"
```

---

## Task 6: Add profile/group methods to the repository protocol

**Files:**
- Modify: `src/account_automation_lab/repositories/base.py`

No test of its own — it is a `Protocol`. It is exercised by Tasks 7-8.

- [ ] **Step 1: Extend the protocol**

In `src/account_automation_lab/repositories/base.py`, add imports and methods. The
final import line should read:

```python
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
)
```

Add these methods to the `AutomationRepository` protocol:

```python
    async def list_profiles(self) -> list[BrowserProfile]: ...

    async def get_profile(self, profile_id: str) -> BrowserProfile | None: ...

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile: ...

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile: ...

    async def delete_profile(self, profile_id: str) -> None: ...

    async def list_profile_groups(self) -> list[ProfileGroup]: ...

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup: ...

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup: ...

    async def delete_profile_group(self, group_id: str) -> None: ...
```

Note `create_profile` takes a fully-built `BrowserProfile` (the store builds the
storage dir and assembles the record); the repository only persists it.

- [ ] **Step 2: Type check**

Run mypy. Expected: errors in `memory.py`/`supabase.py` (they do not yet implement
the new protocol methods). That is expected — fixed in Tasks 7-8. Do not commit yet.

- [ ] **Step 3: Commit**

```bash
git add src/account_automation_lab/repositories/base.py
git commit -m "feat: add profile/group methods to repository protocol"
```

---

## Task 7: Implement profile/group CRUD in the memory repository

**Files:**
- Modify: `src/account_automation_lab/repositories/memory.py`
- Test: `tests/test_profile_repository.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_profile_repository.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `MemoryRepository` has no `create_profile`.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/repositories/memory.py`:

Update imports:

```python
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    utc_now,
)
```

In `MemoryRepository.__init__`, add stores:

```python
        self._profiles: dict[str, BrowserProfile] = {}
        self._groups: dict[str, ProfileGroup] = {}
```

Add methods to the class:

```python
    async def list_profiles(self) -> list[BrowserProfile]:
        return sorted(self._profiles.values(), key=lambda p: p.created_at)

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return self._profiles.get(profile_id)

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        self._profiles[profile.id] = profile
        return profile

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        current = self._profiles[profile_id]
        changes = update.model_dump(exclude_unset=True)
        changes["updated_at"] = utc_now()
        updated = current.model_copy(update=changes)
        self._profiles[profile_id] = updated
        return updated

    async def delete_profile(self, profile_id: str) -> None:
        self._profiles.pop(profile_id, None)

    async def list_profile_groups(self) -> list[ProfileGroup]:
        return sorted(self._groups.values(), key=lambda g: g.created_at)

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup:
        group = ProfileGroup(name=payload.name, color=payload.color)
        self._groups[group.id] = group
        return group

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup:
        current = self._groups[group_id]
        changes = update.model_dump(exclude_unset=True)
        updated = current.model_copy(update=changes)
        self._groups[group_id] = updated
        return updated

    async def delete_profile_group(self, group_id: str) -> None:
        self._groups.pop(group_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS — 5 passed.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/repositories/memory.py tests/test_profile_repository.py
git commit -m "feat: implement profile/group CRUD in memory repository"
```

---

## Task 8: Implement profile/group CRUD in the Supabase repository

**Files:**
- Modify: `src/account_automation_lab/repositories/supabase.py`
- Test: `tests/test_supabase_profiles.py` (create, using a fake client)

The Supabase client is synchronous and wrapped in `asyncio.to_thread`. The test
uses a fake client that records table operations, so no network is touched.

- [ ] **Step 1: Write the failing test**

Create `tests/test_supabase_profiles.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    ProfileGroupCreate,
)


class _FakeQuery:
    def __init__(self, table: "_FakeTable") -> None:
        self._table = table
        self._filters: dict[str, Any] = {}
        self._op: str | None = None
        self._payload: Any = None

    def select(self, *_: str) -> "_FakeQuery":
        self._op = "select"
        return self

    def insert(self, payload: Any) -> "_FakeQuery":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, payload: Any) -> "_FakeQuery":
        self._op = "update"
        self._payload = payload
        return self

    def delete(self) -> "_FakeQuery":
        self._op = "delete"
        return self

    def eq(self, column: str, value: Any) -> "_FakeQuery":
        self._filters[column] = value
        return self

    def order(self, *_: str, **__: Any) -> "_FakeQuery":
        return self

    def limit(self, *_: int) -> "_FakeQuery":
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
        # select
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
    repo._client = _FakeClient()  # type: ignore[attr-defined]
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
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — methods not implemented.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/repositories/supabase.py`:

Add table constants near the existing ones:

```python
AUTOMATION_PROFILES_TABLE = "automation_profiles"
AUTOMATION_PROFILE_GROUPS_TABLE = "automation_profile_groups"
```

Add imports for the models used:

```python
from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileUpdate,
    JobCreate,
    JobEvent,
    JobRecord,
    JobStatus,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
    utc_now,
)
```

Add methods to `SupabaseRepository`. Profiles serialise `fingerprint` as JSON via
`model_dump(mode="json")`:

```python
    async def list_profiles(self) -> list[BrowserProfile]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .select("*")
            .order("created_at")
            .execute()
        )
        return [BrowserProfile.model_validate(row) for row in result.data]

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .select("*")
            .eq("id", profile_id)
            .limit(1)
            .execute()
        )
        if not result.data:
            return None
        return BrowserProfile.model_validate(result.data[0])

    async def create_profile(self, profile: BrowserProfile) -> BrowserProfile:
        row = profile.model_dump(mode="json")
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE).insert(row).execute()
        )
        return BrowserProfile.model_validate(result.data[0])

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        changes = update.model_dump(mode="json", exclude_unset=True)
        changes["updated_at"] = utc_now().isoformat()
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .update(changes)
            .eq("id", profile_id)
            .execute()
        )
        if not result.data:
            raise KeyError(profile_id)
        return BrowserProfile.model_validate(result.data[0])

    async def delete_profile(self, profile_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILES_TABLE)
            .delete()
            .eq("id", profile_id)
            .execute()
        )

    async def list_profile_groups(self) -> list[ProfileGroup]:
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .select("*")
            .order("created_at")
            .execute()
        )
        return [ProfileGroup.model_validate(row) for row in result.data]

    async def create_profile_group(self, payload: ProfileGroupCreate) -> ProfileGroup:
        group = ProfileGroup(name=payload.name, color=payload.color)
        row = group.model_dump(mode="json")
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE).insert(row).execute()
        )
        return ProfileGroup.model_validate(result.data[0])

    async def update_profile_group(
        self, group_id: str, update: ProfileGroupUpdate
    ) -> ProfileGroup:
        changes = update.model_dump(mode="json", exclude_unset=True)
        result = await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .update(changes)
            .eq("id", group_id)
            .execute()
        )
        if not result.data:
            raise KeyError(group_id)
        return ProfileGroup.model_validate(result.data[0])

    async def delete_profile_group(self, group_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._client.table(AUTOMATION_PROFILE_GROUPS_TABLE)
            .delete()
            .eq("id", group_id)
            .execute()
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS — 3 passed.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/repositories/supabase.py tests/test_supabase_profiles.py
git commit -m "feat: implement profile/group CRUD in Supabase repository"
```

---

## Task 9: Extend Supabase schema for profiles and groups

**Files:**
- Modify: `supabase/schema.sql`
- Test: `tests/test_supabase_schema_contract.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_supabase_schema_contract.py`:

```python
def test_schema_has_profile_groups_and_profile_columns() -> None:
    schema = Path("supabase/schema.sql").read_text(encoding="utf-8")

    assert "create table if not exists public.automation_profile_groups" in schema
    # profile columns added for the manager
    for column in (
        "add column if not exists name",
        "add column if not exists group_id",
        "add column if not exists tags",
        "add column if not exists notes",
        "add column if not exists runtime",
        "add column if not exists startup_url",
        "add column if not exists status",
        "add column if not exists fingerprint",
    ):
        assert column in schema
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL.

- [ ] **Step 3: Implement**

In `supabase/schema.sql`, add the groups table (before `automation_profiles`):

```sql
create table if not exists public.automation_profile_groups (
  id text primary key,
  name text not null,
  color text,
  created_at timestamptz not null default now()
);
```

After the `automation_profiles` table definition, add idempotent column additions:

```sql
alter table public.automation_profiles
  add column if not exists name text,
  add column if not exists group_id text references public.automation_profile_groups(id),
  add column if not exists tags text[] not null default '{}',
  add column if not exists notes text not null default '',
  add column if not exists runtime text not null default 'cloakbrowser',
  add column if not exists startup_url text,
  add column if not exists status text not null default 'active',
  add column if not exists fingerprint jsonb not null default '{}';

alter table public.automation_profiles alter column sim_id drop not null;
alter table public.automation_profiles alter column site_key drop not null;
```

Add to the RLS-disable block near the bottom:

```sql
alter table public.automation_profile_groups   disable row level security;
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add supabase/schema.sql tests/test_supabase_schema_contract.py
git commit -m "feat: extend Supabase schema for profile manager"
```

---

## Task 10: Make BrowserProfileStore repository-backed with create/update/delete/clone

**Files:**
- Modify: `src/account_automation_lab/browser/profiles.py`
- Test: `tests/test_browser_profiles.py` (extend; existing tests must keep passing)

The store currently seeds profiles in-process keyed by `sim-a:site_NN`. It becomes
a thin layer over an `AutomationRepository`: it owns storage-dir creation and record
assembly, and delegates persistence to the repo. Existing tests construct
`BrowserProfileStore(storage_root=..., site_keys=(...))`; we keep that constructor
shape but back it with an injected repository (default: a fresh `MemoryRepository`)
and stop auto-seeding from `site_keys` (seeding moves to being optional/no-op).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_browser_profiles.py`:

```python
import pytest

from account_automation_lab.browser.profiles import BrowserProfileStore
from account_automation_lab.models import BrowserProfileCreate, BrowserProfileUpdate
from account_automation_lab.repositories.memory import MemoryRepository


@pytest.mark.asyncio
async def test_store_create_persists_and_builds_storage_dir(tmp_path) -> None:
    repo = MemoryRepository()
    store = BrowserProfileStore(storage_root=tmp_path, repository=repo)

    profile = await store.create_profile(BrowserProfileCreate(name="My FB"))

    assert profile.id
    assert profile.name == "My FB"
    assert (tmp_path / profile.id).exists()
    # persisted in the repo
    assert await repo.get_profile(profile.id) is not None


@pytest.mark.asyncio
async def test_store_update_profile(tmp_path) -> None:
    repo = MemoryRepository()
    store = BrowserProfileStore(storage_root=tmp_path, repository=repo)
    profile = await store.create_profile(BrowserProfileCreate(name="A"))

    updated = await store.update_profile(profile.id, BrowserProfileUpdate(name="B"))

    assert updated.name == "B"


@pytest.mark.asyncio
async def test_store_clone_makes_new_id_and_dir_and_random_seed(tmp_path) -> None:
    repo = MemoryRepository()
    store = BrowserProfileStore(storage_root=tmp_path, repository=repo)
    original = await store.create_profile(BrowserProfileCreate(name="Orig"))

    clone = await store.clone_profile(original.id)

    assert clone.id != original.id
    assert clone.name.startswith("Orig")
    assert clone.storage_dir != original.storage_dir
    assert (tmp_path / clone.id).exists()


@pytest.mark.asyncio
async def test_store_delete_removes_record_and_optionally_dir(tmp_path) -> None:
    repo = MemoryRepository()
    store = BrowserProfileStore(storage_root=tmp_path, repository=repo)
    profile = await store.create_profile(BrowserProfileCreate(name="X"))
    storage_dir = tmp_path / profile.id

    await store.delete_profile(profile.id, remove_storage=True)

    assert await repo.get_profile(profile.id) is None
    assert not storage_dir.exists()
```

Note: existing tests in this file call `BrowserProfileStore(storage_root=...,
site_keys=("site_01",))` and then `await store.list_profiles()` /
`store.create_profile(BrowserProfileCreate(...))` / `store.get_profile(...)`. Those
must keep working. Keep `site_keys` as an accepted (now optional) kwarg; when
provided, seed those profiles into the repository on construction via a sync
pre-seed (acceptable because the constructor builds storage dirs synchronously).

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `repository` kwarg unknown / methods missing.

- [ ] **Step 3: Implement**

Rewrite `src/account_automation_lab/browser/profiles.py`'s `BrowserProfileStore`.
Keep `_path_safe_profile_id`, `BrowserProfileExistsError`, `BrowserSessionError`,
`ActiveBrowserSession`, and `BrowserSessionManager` as they are; only the store
changes. New store:

```python
import uuid as _uuid

from account_automation_lab.models import (
    BrowserProfile,
    BrowserProfileCreate,
    BrowserProfileUpdate,
    BrowserSession,
    BrowserSessionStatus,
    FingerprintConfig,
    utc_now,
)
from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.repositories.memory import MemoryRepository


class BrowserProfileStore:
    def __init__(
        self,
        *,
        storage_root: Path,
        repository: AutomationRepository | None = None,
        site_keys: tuple[str, ...] = (),
    ) -> None:
        self.storage_root = storage_root
        self.storage_root.mkdir(parents=True, exist_ok=True)
        self.repository: AutomationRepository = repository or MemoryRepository()
        for site_key in site_keys:
            self._seed_default(site_key)

    def _seed_default(self, site_key: str) -> None:
        profile_id = f"sim-a:{site_key}"
        storage_dir = self._ensure_storage_dir(profile_id)
        profile = BrowserProfile(
            id=profile_id,
            name=f"SIM A / {site_key}",
            sim_id="sim-a",
            site_key=site_key,
            storage_dir=str(storage_dir),
        )
        # Synchronous seed into a memory repo (only valid for MemoryRepository).
        if isinstance(self.repository, MemoryRepository):
            self.repository._profiles[profile_id] = profile  # noqa: SLF001

    async def list_profiles(self) -> list[BrowserProfile]:
        return await self.repository.list_profiles()

    async def get_profile(self, profile_id: str) -> BrowserProfile | None:
        return await self.repository.get_profile(profile_id)

    async def create_profile(self, payload: BrowserProfileCreate) -> BrowserProfile:
        profile_id = payload.id or str(_uuid.uuid4())
        if await self.repository.get_profile(profile_id) is not None:
            raise BrowserProfileExistsError(f"Browser profile {profile_id} already exists")
        storage_dir = self._ensure_storage_dir(profile_id)
        profile = BrowserProfile(
            id=profile_id,
            name=payload.name,
            group_id=payload.group_id,
            tags=payload.tags,
            notes=payload.notes,
            sim_id=payload.sim_id,
            site_key=payload.site_key,
            runtime=payload.runtime,
            storage_dir=str(storage_dir),
            startup_url=payload.startup_url,
            fingerprint=payload.fingerprint,
        )
        return await self.repository.create_profile(profile)

    async def update_profile(
        self, profile_id: str, update: BrowserProfileUpdate
    ) -> BrowserProfile:
        return await self.repository.update_profile(profile_id, update)

    async def clone_profile(self, profile_id: str) -> BrowserProfile:
        source = await self.repository.get_profile(profile_id)
        if source is None:
            raise KeyError(profile_id)
        new_id = str(_uuid.uuid4())
        storage_dir = self._ensure_storage_dir(new_id)
        # Clone fingerprint but randomise the seed so the clone is a distinct identity.
        cloned_fp = source.fingerprint.model_copy(update={"seed": None})
        profile = BrowserProfile(
            id=new_id,
            name=f"{source.name} (copy)",
            group_id=source.group_id,
            tags=list(source.tags),
            notes=source.notes,
            sim_id=source.sim_id,
            site_key=source.site_key,
            runtime=source.runtime,
            storage_dir=str(storage_dir),
            startup_url=source.startup_url,
            fingerprint=cloned_fp,
        )
        return await self.repository.create_profile(profile)

    async def delete_profile(self, profile_id: str, *, remove_storage: bool = False) -> None:
        profile = await self.repository.get_profile(profile_id)
        await self.repository.delete_profile(profile_id)
        if remove_storage and profile is not None:
            import shutil

            shutil.rmtree(Path(profile.storage_dir), ignore_errors=True)

    def _ensure_storage_dir(self, profile_id: str) -> Path:
        storage_dir = self.storage_root / _path_safe_profile_id(profile_id)
        storage_dir.mkdir(parents=True, exist_ok=True)
        return storage_dir
```

(Remove the old `_build_profile`, `_storage_dir_for`, and
`_storage_dir_is_used_by_other_profile` methods; the uuid id removes the
sanitised-collision problem. The collision-test in `test_browser_profiles.py` that
relied on `_storage_dir_for` should be deleted in Step 1's edits — if present,
delete `test_browser_profile_store_uses_distinct_path_safe_dirs_for_sanitized_collisions`.)

- [ ] **Step 4: Run test to verify it passes**

Run the whole file `tests/test_browser_profiles.py`. Expected: PASS (old + new).

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/browser/profiles.py tests/test_browser_profiles.py
git commit -m "feat: repository-backed BrowserProfileStore with clone/update/delete"
```

---

## Task 11: Pass profile fingerprint into the browser session

**Files:**
- Modify: `src/account_automation_lab/browser/profiles.py` (`BrowserSessionManager._launch_profile`)
- Test: `tests/test_browser_profiles.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_browser_profiles.py`:

```python
from account_automation_lab.models import FingerprintConfig, FingerprintPlatform


@pytest.mark.asyncio
async def test_session_manager_passes_fingerprint_kwargs_to_runtime(tmp_path) -> None:
    repo = MemoryRepository()
    store = BrowserProfileStore(storage_root=tmp_path, repository=repo)
    profile = await store.create_profile(
        BrowserProfileCreate(
            name="FP",
            fingerprint=FingerprintConfig(
                platform=FingerprintPlatform.MACOS,
                seed=99,
                timezone="Asia/Ho_Chi_Minh",
            ),
        )
    )
    fake_runtime = FakeRuntime()
    manager = BrowserSessionManager(
        store=store,
        settings=Settings(),
        proxy_manager=ProfileProxyManager(),
        runtime_factory=lambda _kind, _settings: fake_runtime,
    )

    await manager.open_profile(profile.id)

    config = fake_runtime.launches[0]
    assert config.fingerprint_kwargs is not None
    assert config.fingerprint_kwargs["timezone"] == "Asia/Ho_Chi_Minh"
    assert "--fingerprint=99" in config.fingerprint_kwargs["args"]
    assert "--fingerprint-platform=macos" in config.fingerprint_kwargs["args"]
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `config.fingerprint_kwargs` is None.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/browser/profiles.py`, import the mapper at top:

```python
from account_automation_lab.browser.fingerprint import fingerprint_launch_kwargs
```

In `BrowserSessionManager._launch_profile`, when building `BrowserProfileConfig`,
add the fingerprint kwargs:

```python
            config = BrowserProfileConfig(
                profile_id=profile.id,
                storage_dir=Path(profile.storage_dir),
                proxy=assignment.proxy.playwright_proxy if assignment is not None else None,
                extension_paths=tuple(Path(p) for p in profile.fingerprint.extension_paths),
                fingerprint_kwargs=fingerprint_launch_kwargs(profile.fingerprint),
            )
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/browser/profiles.py tests/test_browser_profiles.py
git commit -m "feat: apply profile fingerprint when opening a session"
```

---

## Task 12: Checkpoint registry for human-in-the-loop

**Files:**
- Create: `src/account_automation_lab/workflows/__init__.py` (empty)
- Create: `src/account_automation_lab/workflows/checkpoints.py`
- Test: `tests/test_checkpoints.py` (create)

A checkpoint is a named pause point keyed by job id. `wait()` blocks until another
coroutine calls `resume()` or `cancel()`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_checkpoints.py`:

```python
from __future__ import annotations

import asyncio

import pytest

from account_automation_lab.workflows.checkpoints import (
    CheckpointCancelled,
    CheckpointRegistry,
)


@pytest.mark.asyncio
async def test_resume_unblocks_waiter() -> None:
    registry = CheckpointRegistry()

    async def waiter() -> str:
        await registry.wait("job1", "captcha", "Solve the captcha")
        return "resumed"

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    assert registry.current("job1") is not None
    assert registry.current("job1").message == "Solve the captcha"

    registry.resume("job1")
    assert await task == "resumed"
    assert registry.current("job1") is None


@pytest.mark.asyncio
async def test_cancel_raises_in_waiter() -> None:
    registry = CheckpointRegistry()

    async def waiter() -> None:
        await registry.wait("job1", "manual", "Do thing")

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0.01)
    registry.cancel("job1")

    with pytest.raises(CheckpointCancelled):
        await task


@pytest.mark.asyncio
async def test_resume_without_waiter_is_noop() -> None:
    registry = CheckpointRegistry()
    registry.resume("nope")  # must not raise
    assert registry.current("nope") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

Create `src/account_automation_lab/workflows/__init__.py` (empty file).

Create `src/account_automation_lab/workflows/checkpoints.py`:

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


class CheckpointCancelled(RuntimeError):
    """Raised inside a waiting step when the operator cancels the checkpoint."""


@dataclass
class Checkpoint:
    job_id: str
    kind: str
    message: str
    _event: asyncio.Event = field(default_factory=asyncio.Event)
    _cancelled: bool = False


class CheckpointRegistry:
    def __init__(self) -> None:
        self._checkpoints: dict[str, Checkpoint] = {}

    def current(self, job_id: str) -> Checkpoint | None:
        return self._checkpoints.get(job_id)

    async def wait(self, job_id: str, kind: str, message: str) -> None:
        checkpoint = Checkpoint(job_id=job_id, kind=kind, message=message)
        self._checkpoints[job_id] = checkpoint
        try:
            await checkpoint._event.wait()  # noqa: SLF001
            if checkpoint._cancelled:  # noqa: SLF001
                raise CheckpointCancelled(job_id)
        finally:
            if self._checkpoints.get(job_id) is checkpoint:
                del self._checkpoints[job_id]

    def resume(self, job_id: str) -> None:
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint._event.set()  # noqa: SLF001

    def cancel(self, job_id: str) -> None:
        checkpoint = self._checkpoints.get(job_id)
        if checkpoint is not None:
            checkpoint._cancelled = True  # noqa: SLF001
            checkpoint._event.set()  # noqa: SLF001
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS — 3 passed.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/workflows/__init__.py src/account_automation_lab/workflows/checkpoints.py tests/test_checkpoints.py
git commit -m "feat: add checkpoint registry for human-in-the-loop"
```

---

## Task 13: WorkflowContext and primitive steps

**Files:**
- Create: `src/account_automation_lab/workflows/context.py`
- Create: `src/account_automation_lab/workflows/steps.py`
- Test: `tests/test_workflow_steps.py` (create)

Steps are factory functions returning an `async def (ctx) -> None`. They operate on
`ctx.page` (a Playwright-like page) and `ctx.repo` (event log). This keeps each step
independently testable with a fake page.

- [ ] **Step 1: Write the failing test**

Create `tests/test_workflow_steps.py`:

```python
from __future__ import annotations

from typing import Any

import pytest

from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import (
    click,
    emit,
    fill,
    goto,
    wait_for_human,
)


class FakePage:
    def __init__(self) -> None:
        self.actions: list[tuple[str, Any]] = []

    async def goto(self, url: str) -> None:
        self.actions.append(("goto", url))

    async def fill(self, selector: str, value: str) -> None:
        self.actions.append(("fill", (selector, value)))

    async def click(self, selector: str) -> None:
        self.actions.append(("click", selector))


def _ctx(page: FakePage, repo: MemoryRepository, job_id: str) -> WorkflowContext:
    return WorkflowContext(
        job_id=job_id,
        profile_id="p1",
        page=page,
        repo=repo,
        checkpoints=CheckpointRegistry(),
    )


@pytest.mark.asyncio
async def test_goto_fill_click_drive_the_page() -> None:
    page = FakePage()
    repo = MemoryRepository()
    ctx = _ctx(page, repo, "job1")

    await goto("https://localhost/x")(ctx)
    await fill("#email", "a@b.c")(ctx)
    await click("#submit")(ctx)

    assert page.actions == [
        ("goto", "https://localhost/x"),
        ("fill", ("#email", "a@b.c")),
        ("click", "#submit"),
    ]


@pytest.mark.asyncio
async def test_emit_records_a_job_event() -> None:
    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())
    ctx = _ctx(page, repo, created.id)

    await emit("note", "hello", {"k": "v"})(ctx)

    events = await repo.get_job_events(created.id)
    assert any(e.event_type == "note" and e.message == "hello" for e in events)


@pytest.mark.asyncio
async def test_wait_for_human_sets_waiting_state_then_resumes() -> None:
    import asyncio

    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())
    await repo.update_job_status(created.id, __import__(
        "account_automation_lab.models", fromlist=["JobStatus"]
    ).JobStatus.RUNNING)
    checkpoints = CheckpointRegistry()
    ctx = WorkflowContext(
        job_id=created.id, profile_id="p1", page=page, repo=repo, checkpoints=checkpoints
    )

    task = asyncio.create_task(wait_for_human("manual", "Please confirm")(ctx))
    await asyncio.sleep(0.01)

    job = await repo.get_job(created.id)
    assert job is not None and job.status.value == "waiting_human"
    assert checkpoints.current(created.id) is not None

    checkpoints.resume(created.id)
    await task
    job2 = await repo.get_job(created.id)
    assert job2 is not None and job2.status.value == "running"


def _make_job_create() -> Any:
    from account_automation_lab.models import JobCreate

    return JobCreate(site_key="site_01", sim_id="sim-a")
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — modules not found.

- [ ] **Step 3: Implement the context**

Create `src/account_automation_lab/workflows/context.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from account_automation_lab.repositories.base import AutomationRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry


@dataclass
class WorkflowContext:
    job_id: str
    profile_id: str
    page: Any
    repo: AutomationRepository
    checkpoints: CheckpointRegistry
    otp_provider: Any | None = None
    session_manager: Any | None = None
    proxy: Any | None = None
```

- [ ] **Step 4: Implement the steps**

Create `src/account_automation_lab/workflows/steps.py`:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from account_automation_lab.models import JobStatus
from account_automation_lab.workflows.context import WorkflowContext

Step = Callable[[WorkflowContext], Awaitable[None]]


def goto(url: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.goto(url)
        await ctx.repo.add_event(ctx.job_id, "step.goto", url)

    return _step


def fill(selector: str, value: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.fill(selector, value)
        await ctx.repo.add_event(ctx.job_id, "step.fill", selector)

    return _step


def click(selector: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.page.click(selector)
        await ctx.repo.add_event(ctx.job_id, "step.click", selector)

    return _step


def emit(event_type: str, message: str, payload: dict[str, Any] | None = None) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.repo.add_event(ctx.job_id, event_type, message, payload)

    return _step


def wait_for_human(kind: str, message: str) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await ctx.repo.update_job_status(
            ctx.job_id,
            JobStatus.WAITING_HUMAN,
            event_type="job.waiting_human",
            message=message,
        )
        await ctx.checkpoints.wait(ctx.job_id, kind, message)
        await ctx.repo.update_job_status(
            ctx.job_id,
            JobStatus.RUNNING,
            event_type="job.resumed",
            message="Resumed by operator",
        )

    return _step
```

- [ ] **Step 5: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 6: Type check + lint + commit**

```bash
git add src/account_automation_lab/workflows/context.py src/account_automation_lab/workflows/steps.py tests/test_workflow_steps.py
git commit -m "feat: add WorkflowContext and primitive steps"
```

---

## Task 14: get_otp and read_from steps

**Files:**
- Modify: `src/account_automation_lab/workflows/steps.py`
- Test: `tests/test_workflow_steps.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_workflow_steps.py`:

```python
@pytest.mark.asyncio
async def test_get_otp_stores_result_on_context() -> None:
    from account_automation_lab.workflows.steps import get_otp

    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())

    class FakeOtp:
        async def wait_for_otp(self, request: Any) -> str:
            return "123456"

    ctx = WorkflowContext(
        job_id=created.id,
        profile_id="p1",
        page=page,
        repo=repo,
        checkpoints=CheckpointRegistry(),
        otp_provider=FakeOtp(),
    )

    await get_otp("sim-a", "site_01", sender_hints=("SITE01",))(ctx)

    assert ctx.data["otp"] == "123456"


@pytest.mark.asyncio
async def test_read_from_uses_session_manager_callback() -> None:
    from account_automation_lab.workflows.steps import read_from

    page = FakePage()
    repo = MemoryRepository()
    created = await repo.create_job(_make_job_create())

    class FakeSessionManager:
        async def get_page(self, profile_id: str) -> Any:
            return {"profile": profile_id}

    ctx = WorkflowContext(
        job_id=created.id,
        profile_id="p1",
        page=page,
        repo=repo,
        checkpoints=CheckpointRegistry(),
        session_manager=FakeSessionManager(),
    )

    async def reader(other_page: Any) -> str:
        return other_page["profile"]

    result = await read_from("p2", reader, store_as="other")(ctx)
    assert ctx.data["other"] == "p2"
```

Note: this requires a `data: dict` field on `WorkflowContext`. Add it.

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `ctx.data` missing / steps missing.

- [ ] **Step 3: Implement**

In `context.py`, add a mutable data bag:

```python
from dataclasses import dataclass, field
...
@dataclass
class WorkflowContext:
    job_id: str
    profile_id: str
    page: Any
    repo: AutomationRepository
    checkpoints: CheckpointRegistry
    otp_provider: Any | None = None
    session_manager: Any | None = None
    proxy: Any | None = None
    data: dict[str, Any] = field(default_factory=dict)
```

In `steps.py`, add:

```python
from datetime import datetime

from account_automation_lab.models import OtpRequest, utc_now


def get_otp(
    sim_id: str,
    site_key: str,
    sender_hints: tuple[str, ...] = (),
    timeout_seconds: float = 120.0,
    store_as: str = "otp",
) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        if ctx.otp_provider is None:
            raise RuntimeError("No OTP provider configured for this workflow")
        request = OtpRequest(
            sim_id=sim_id,
            site_key=site_key,
            sender_hints=sender_hints,
            requested_after=utc_now(),
            timeout_seconds=timeout_seconds,
        )
        otp = await ctx.otp_provider.wait_for_otp(request)
        ctx.data[store_as] = otp
        await ctx.repo.add_event(
            ctx.job_id, "step.get_otp", "OTP received" if otp else "OTP timeout"
        )

    return _step


def read_from(
    profile_id: str,
    reader: Callable[[Any], Awaitable[Any]],
    store_as: str = "read",
) -> Step:
    async def _step(ctx: WorkflowContext) -> Any:
        if ctx.session_manager is None:
            raise RuntimeError("No session manager configured for this workflow")
        other_page = await ctx.session_manager.get_page(profile_id)
        value = await reader(other_page)
        ctx.data[store_as] = value
        await ctx.repo.add_event(ctx.job_id, "step.read_from", f"Read from {profile_id}")
        return value

    return _step
```

`read_from`'s inner returns a value for convenience; the `Step` type allows
returning `None`, and returning a value is harmless. To keep mypy strict happy,
annotate the inner as `-> Any` (shown above) and keep the public `Step` alias.

Also add a `wait_for` step:

```python
import asyncio


def wait_for(seconds: float) -> Step:
    async def _step(ctx: WorkflowContext) -> None:
        await asyncio.sleep(seconds)

    return _step
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/workflows/context.py src/account_automation_lab/workflows/steps.py tests/test_workflow_steps.py
git commit -m "feat: add get_otp, read_from, wait_for steps"
```

---

## Task 15: WorkflowEngine that runs steps with error→waiting_human

**Files:**
- Create: `src/account_automation_lab/workflows/engine.py`
- Test: `tests/test_workflow_engine.py` (create)

The engine runs an ordered list of steps. On an unhandled exception it records the
error and (by default) transitions the job to `WAITING_HUMAN` so the operator can
intervene; if `fail_fast=True` it transitions to `FAILED` instead. If a checkpoint
is cancelled (`CheckpointCancelled`) the job goes to `CANCELLED`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_workflow_engine.py`:

```python
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from account_automation_lab.models import JobCreate, JobStatus
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.engine import WorkflowEngine


def _ctx(repo: MemoryRepository, job_id: str, checkpoints: CheckpointRegistry) -> WorkflowContext:
    return WorkflowContext(
        job_id=job_id, profile_id="p1", page=object(), repo=repo, checkpoints=checkpoints
    )


@pytest.mark.asyncio
async def test_engine_runs_all_steps_then_succeeds() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)
    calls: list[str] = []

    async def step_a(ctx: WorkflowContext) -> None:
        calls.append("a")

    async def step_b(ctx: WorkflowContext) -> None:
        calls.append("b")

    engine = WorkflowEngine()
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [step_a, step_b])

    assert calls == ["a", "b"]
    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.SUCCEEDED


@pytest.mark.asyncio
async def test_engine_error_goes_to_waiting_human_by_default() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)

    async def boom(ctx: WorkflowContext) -> None:
        raise ValueError("kaboom")

    engine = WorkflowEngine()
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [boom])

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.WAITING_HUMAN
    events = await repo.get_job_events(created.id)
    assert any(e.event_type == "job.error" and "kaboom" in e.message for e in events)


@pytest.mark.asyncio
async def test_engine_error_fail_fast_goes_to_failed() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)

    async def boom(ctx: WorkflowContext) -> None:
        raise ValueError("kaboom")

    engine = WorkflowEngine(fail_fast=True)
    await engine.run(_ctx(repo, created.id, CheckpointRegistry()), [boom])

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.FAILED


@pytest.mark.asyncio
async def test_engine_checkpoint_cancel_goes_to_cancelled() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(JobCreate(site_key="site_01", sim_id="sim-a"))
    await repo.update_job_status(created.id, JobStatus.RUNNING)
    checkpoints = CheckpointRegistry()

    async def pause(ctx: WorkflowContext) -> None:
        await ctx.checkpoints.wait(ctx.job_id, "manual", "hold")

    engine = WorkflowEngine()
    ctx = _ctx(repo, created.id, checkpoints)
    task = asyncio.create_task(engine.run(ctx, [pause]))
    await asyncio.sleep(0.01)
    checkpoints.cancel(created.id)
    await task

    job = await repo.get_job(created.id)
    assert job is not None and job.status == JobStatus.CANCELLED
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — engine not found.

- [ ] **Step 3: Implement**

Create `src/account_automation_lab/workflows/engine.py`:

```python
from __future__ import annotations

from collections.abc import Sequence

from account_automation_lab.models import JobStatus
from account_automation_lab.workflows.checkpoints import CheckpointCancelled
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import Step


class WorkflowEngine:
    def __init__(self, *, fail_fast: bool = False) -> None:
        self.fail_fast = fail_fast

    async def run(self, ctx: WorkflowContext, steps: Sequence[Step]) -> None:
        try:
            for step in steps:
                await step(ctx)
        except CheckpointCancelled:
            await self._safe_status(ctx, JobStatus.CANCELLED, "job.cancelled", "Cancelled")
            return
        except Exception as exc:  # noqa: BLE001
            await ctx.repo.add_event(ctx.job_id, "job.error", str(exc))
            target = JobStatus.FAILED if self.fail_fast else JobStatus.WAITING_HUMAN
            message = "Failed" if self.fail_fast else f"Paused after error: {exc}"
            await self._safe_status(ctx, target, "job.error_paused", message)
            return
        await self._safe_status(ctx, JobStatus.SUCCEEDED, "job.succeeded", "Workflow completed")

    async def _safe_status(
        self, ctx: WorkflowContext, status: JobStatus, event_type: str, message: str
    ) -> None:
        from account_automation_lab.repositories.memory import InvalidJobTransitionError

        try:
            await ctx.repo.update_job_status(
                ctx.job_id, status, event_type=event_type, message=message
            )
        except InvalidJobTransitionError:
            await ctx.repo.add_event(
                ctx.job_id,
                "job.status_conflict",
                f"Skipped transition to {status.value}; job already terminal.",
            )
```

Note on `WAITING_HUMAN` after error: the job is RUNNING when the error fires, and
RUNNING→WAITING_HUMAN is allowed. The operator then resumes (→RUNNING) or cancels.
Resuming after an error does not auto-retry the failed step in this stage; the
runner re-runs the workflow from the start only if explicitly told to (out of scope
here — resume simply unblocks any pending checkpoint). For an error-pause with no
pending checkpoint, resume transitions WAITING_HUMAN→RUNNING and the job ends
(no remaining steps); this is acceptable for the skeleton and documented in the UI.

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS — 4 passed.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/workflows/engine.py tests/test_workflow_engine.py
git commit -m "feat: add WorkflowEngine with error->waiting_human handling"
```

---

## Task 16: Adapters expose a workflow; mock adapter demonstrates the flow

**Files:**
- Modify: `src/account_automation_lab/adapters/base.py`
- Test: `tests/test_registry_api.py` (extend) or `tests/test_adapter_workflow.py` (create)

Adapters keep their existing `spec` and `run(context)` (for backward-compatible
tests), and additionally expose `workflow(ctx) -> list[Step]`. The mock adapter's
workflow demonstrates: goto → fill → click → emit succeeded. (No OTP/human steps in
the default mock so existing end-to-end runner tests stay deterministic; a separate
demo adapter can add them later.)

- [ ] **Step 1: Write the failing test**

Create `tests/test_adapter_workflow.py`:

```python
from __future__ import annotations

import pytest

from account_automation_lab.adapters.registry import adapter_for
from account_automation_lab.repositories.memory import MemoryRepository
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
from account_automation_lab.workflows.context import WorkflowContext


class FakePage:
    def __init__(self) -> None:
        self.actions: list[str] = []

    async def goto(self, url: str) -> None:
        self.actions.append("goto")

    async def fill(self, selector: str, value: str) -> None:
        self.actions.append("fill")

    async def click(self, selector: str) -> None:
        self.actions.append("click")


@pytest.mark.asyncio
async def test_mock_adapter_workflow_returns_runnable_steps() -> None:
    adapter = adapter_for("site_01")
    repo = MemoryRepository()
    ctx = WorkflowContext(
        job_id="job1",
        profile_id="p1",
        page=FakePage(),
        repo=repo,
        checkpoints=CheckpointRegistry(),
    )

    steps = adapter.workflow(ctx)
    for step in steps:
        await step(ctx)

    assert ctx.page.actions[:3] == ["goto", "fill", "click"]
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — adapter has no `workflow`.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/adapters/base.py`, add the import and method to
`MockRegistrationAdapter`:

```python
from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.steps import Step, click, emit, fill, goto
```

Add to `MockRegistrationAdapter`:

```python
    def workflow(self, ctx: WorkflowContext) -> list[Step]:
        return [
            goto(self.spec.base_url),
            fill("#username", f"{ctx.profile_id}@{self.spec.key}.test"),
            click("#submit"),
            emit("adapter.mock", f"Mock registration completed for {self.spec.key}"),
        ]
```

Update the `SiteAdapter` Protocol in the same file to include `workflow`:

```python
class SiteAdapter(Protocol):
    spec: SiteSpec

    async def run(self, context: RegistrationContext) -> RegistrationResult: ...

    def workflow(self, ctx: WorkflowContext) -> list[Step]: ...
```

(Keep `run` for the existing runner path until Task 17 switches the runner to use
`workflow`.)

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/adapters/base.py tests/test_adapter_workflow.py
git commit -m "feat: adapters expose a step-based workflow"
```

---

## Task 17: Runner drives the workflow engine and shares a checkpoint registry

**Files:**
- Modify: `src/account_automation_lab/jobs/runner.py`
- Test: `tests/test_runner_scheduler.py` (extend)

The runner gains a shared `CheckpointRegistry` and a `WorkflowEngine`. `_run_job`
builds a `WorkflowContext` and runs the adapter's workflow through the engine
instead of calling `adapter.run()`. For the page, the runner asks an injected
`page_provider` callable `async (profile_id) -> page`; default provider returns a
no-op fake page so unit tests do not need a browser. Real wiring to the session
manager happens in the API layer (Task 19).

Pause/resume are exposed as methods: `pause(job_id)` records intent so the engine
stops at the next step boundary; `resume(job_id)` and `cancel(job_id)` delegate to
the checkpoint registry.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_runner_scheduler.py`:

```python
@pytest.mark.asyncio
async def test_runner_runs_workflow_to_success() -> None:
    repo = MemoryRepository()
    created = await repo.create_job(
        JobCreate(site_key="site_01", sim_id="sim-a", profile_id="p1")
    )

    runner = JobRunner(repository=repo, settings=Settings(max_global_concurrency=1))
    await runner.start()
    try:
        await asyncio.sleep(0.5)
    finally:
        await runner.stop()

    job = await repo.get_job(created.id)
    assert job is not None
    assert job.status in {JobStatus.SUCCEEDED, JobStatus.RUNNING}
    # Give it one more beat if still running
    if job.status == JobStatus.RUNNING:
        await asyncio.sleep(0.5)


@pytest.mark.asyncio
async def test_runner_resume_unblocks_waiting_job() -> None:
    repo = MemoryRepository()
    runner = JobRunner(repository=repo, settings=Settings(max_global_concurrency=1))

    # confirm the registry is shared and resume is a no-op when nothing waits
    runner.resume("nope")
    assert runner.checkpoints.current("nope") is None
```

(Adjust imports at the top of the test file to include `JobCreate`, `JobStatus`,
`Settings` — most are already imported from earlier tasks.)

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — `JobRunner` has no `checkpoints`/`resume`, or jobs
no longer succeed because `_run_job` still calls `adapter.run`.

- [ ] **Step 3: Implement**

In `src/account_automation_lab/jobs/runner.py`:

Add imports:

```python
from collections.abc import Awaitable, Callable

from account_automation_lab.workflows.context import WorkflowContext
from account_automation_lab.workflows.engine import WorkflowEngine
from account_automation_lab.workflows.checkpoints import CheckpointRegistry
```

In `__init__`, add:

```python
        self.checkpoints = CheckpointRegistry()
        self.engine = WorkflowEngine()
        self._page_provider: Callable[[str], Awaitable[Any]] = _null_page_provider
```

Add a method to set the page provider (used by the API layer):

```python
    def set_page_provider(self, provider: Callable[[str], Awaitable[Any]]) -> None:
        self._page_provider = provider

    def resume(self, job_id: str) -> None:
        self.checkpoints.resume(job_id)

    def cancel_checkpoint(self, job_id: str) -> None:
        self.checkpoints.cancel(job_id)
```

Replace the body of `_run_job` after acquiring the profile lock so it runs the
workflow through the engine:

```python
        try:
            page = await self._page_provider(profile_id)
            ctx = WorkflowContext(
                job_id=job_id,
                profile_id=profile_id,
                page=page,
                repo=self.repository,
                checkpoints=self.checkpoints,
            )
            steps = adapter.workflow(ctx)
            await self.engine.run(ctx, steps)
        except Exception as exc:
            await self.repository.add_event(job_id, "job.error", str(exc))
            await self._safe_update_status(job_id, JobStatus.FAILED)
        finally:
            await lock.release()
```

(The engine sets the terminal status itself, so the surrounding `except` only
catches failures in provider/context setup. `_safe_update_status` from the existing
code remains.)

Add a module-level null page provider at the bottom of the file:

```python
async def _null_page_provider(_profile_id: str) -> Any:
    class _NoOpPage:
        async def goto(self, *_a: Any, **_k: Any) -> None: ...
        async def fill(self, *_a: Any, **_k: Any) -> None: ...
        async def click(self, *_a: Any, **_k: Any) -> None: ...

    return _NoOpPage()
```

Remove the now-unused `RegistrationContext` import if it is no longer referenced.

- [ ] **Step 4: Run test to verify it passes**

Run `tests/test_runner_scheduler.py`. Expected: PASS. The per-site concurrency test
from the earlier work must still pass (it monkeypatches `adapter_for`; ensure that
test's fake adapter now also provides a `workflow` method, or keep its blocking via
`run`). If the per-site test breaks, update its `_BlockingAdapter` to add:

```python
    def workflow(self, ctx: Any) -> list[Any]:
        async def _block(_ctx: Any) -> None:
            await self._release.wait()
        return [_block]
```

and remove its `run` reliance.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/jobs/runner.py tests/test_runner_scheduler.py
git commit -m "feat: runner drives workflow engine with shared checkpoints"
```

---

## Task 18: Profile and group CRUD API endpoints

**Files:**
- Modify: `src/account_automation_lab/api/__init__.py`
- Test: `tests/test_browser_profile_api.py` (extend)

First read `tests/test_browser_profile_api.py` to follow its `create_app` + memory
repo + `TestClient` pattern. The app must use the same repository for both the
profile store and jobs so profiles persist across calls. Update `create_app` so the
`BrowserProfileStore` is constructed with `repository=repo` (instead of seeding from
`site_keys`).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_browser_profile_api.py`:

```python
def test_profile_crud_lifecycle() -> None:
    from account_automation_lab.api import create_app
    from account_automation_lab.repositories.memory import MemoryRepository
    from account_automation_lab.settings import Settings
    from fastapi.testclient import TestClient

    repo = MemoryRepository()
    app = create_app(settings=Settings(), repository=repo, start_runner=False)
    client = TestClient(app)

    # create
    created = client.post(
        "/api/browser-profiles",
        json={"name": "My FB", "tags": ["fb"], "fingerprint": {"platform": "windows"}},
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    # list
    listed = client.get("/api/browser-profiles").json()
    assert any(p["id"] == pid for p in listed)

    # patch
    patched = client.patch(f"/api/browser-profiles/{pid}", json={"name": "Renamed"})
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed"

    # clone
    cloned = client.post(f"/api/browser-profiles/{pid}/clone")
    assert cloned.status_code == 201
    assert cloned.json()["id"] != pid

    # delete
    deleted = client.delete(f"/api/browser-profiles/{pid}")
    assert deleted.status_code == 200
    remaining = client.get("/api/browser-profiles").json()
    assert all(p["id"] != pid for p in remaining)


def test_group_crud() -> None:
    from account_automation_lab.api import create_app
    from account_automation_lab.repositories.memory import MemoryRepository
    from account_automation_lab.settings import Settings
    from fastapi.testclient import TestClient

    app = create_app(settings=Settings(), repository=MemoryRepository(), start_runner=False)
    client = TestClient(app)

    created = client.post("/api/profile-groups", json={"name": "FB"})
    assert created.status_code == 201
    gid = created.json()["id"]

    assert any(g["id"] == gid for g in client.get("/api/profile-groups").json())

    client.patch(f"/api/profile-groups/{gid}", json={"name": "Facebook"})
    client.delete(f"/api/profile-groups/{gid}")
    assert all(g["id"] != gid for g in client.get("/api/profile-groups").json())
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — endpoints missing / store not repo-backed.

- [ ] **Step 3: Implement**

In `create_app`, change the store construction to use the repository:

```python
    browser_store = browser_profile_store or BrowserProfileStore(
        storage_root=Path(app_settings.browser_profile_storage_root),
        repository=repo,
    )
```

Add imports for the new models:

```python
from account_automation_lab.models import (
    ...,
    BrowserProfileUpdate,
    ProfileGroup,
    ProfileGroupCreate,
    ProfileGroupUpdate,
)
```

Replace the static `create_browser_profile` and add the full CRUD set:

```python
    @app.patch("/api/browser-profiles/{profile_id}")
    async def update_browser_profile(
        profile_id: str, payload: BrowserProfileUpdate
    ) -> BrowserProfile:
        try:
            return await browser_store.update_profile(profile_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser profile not found") from exc

    @app.post("/api/browser-profiles/{profile_id}/clone", status_code=status.HTTP_201_CREATED)
    async def clone_browser_profile(profile_id: str) -> BrowserProfile:
        try:
            return await browser_store.clone_profile(profile_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Browser profile not found") from exc

    @app.delete("/api/browser-profiles/{profile_id}")
    async def delete_browser_profile(
        profile_id: str, remove_storage: bool = False
    ) -> dict[str, str | bool]:
        await browser_store.delete_profile(profile_id, remove_storage=remove_storage)
        return {"deleted": True, "profile_id": profile_id}

    @app.get("/api/profile-groups")
    async def list_profile_groups() -> list[ProfileGroup]:
        return await repo.list_profile_groups()

    @app.post("/api/profile-groups", status_code=status.HTTP_201_CREATED)
    async def create_profile_group(payload: ProfileGroupCreate) -> ProfileGroup:
        return await repo.create_profile_group(payload)

    @app.patch("/api/profile-groups/{group_id}")
    async def update_profile_group(
        group_id: str, payload: ProfileGroupUpdate
    ) -> ProfileGroup:
        try:
            return await repo.update_profile_group(group_id, payload)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="Group not found") from exc

    @app.delete("/api/profile-groups/{group_id}")
    async def delete_profile_group(group_id: str) -> dict[str, str | bool]:
        await repo.delete_profile_group(group_id)
        return {"deleted": True, "group_id": group_id}
```

Keep the existing `POST /api/browser-profiles` (create) and `GET /api/browser-profiles`
(list). Ensure `list_browser_profiles` still builds `BrowserProfileView` rows; it
now reads from the repo-backed store.

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/api/__init__.py tests/test_browser_profile_api.py
git commit -m "feat: profile and group CRUD API endpoints"
```

---

## Task 19: Job pause/resume/checkpoint endpoints wired to the runner

**Files:**
- Modify: `src/account_automation_lab/api/__init__.py`
- Test: `tests/test_registry_api.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_registry_api.py`:

```python
def test_resume_endpoint_calls_runner_resume() -> None:
    from account_automation_lab.api import create_app
    from account_automation_lab.repositories.memory import MemoryRepository
    from account_automation_lab.settings import Settings

    repo = MemoryRepository()
    app = create_app(settings=Settings(), repository=repo, start_runner=False)
    client = TestClient(app)

    created = client.post("/api/jobs", json={"site_key": "site_01", "sim_id": "sim-a"}).json()
    # move job to running then waiting_human so resume is valid
    import asyncio

    async def _advance() -> None:
        await repo.update_job_status(created["id"], JobStatus.RUNNING)
        await repo.update_job_status(created["id"], JobStatus.WAITING_HUMAN)

    asyncio.get_event_loop().run_until_complete(_advance())

    resp = client.post(f"/api/jobs/{created['id']}/resume")
    assert resp.status_code == 200
    assert resp.json()["resumed"] is True


def test_checkpoint_endpoint_returns_none_when_idle() -> None:
    from account_automation_lab.api import create_app
    from account_automation_lab.repositories.memory import MemoryRepository
    from account_automation_lab.settings import Settings

    repo = MemoryRepository()
    app = create_app(settings=Settings(), repository=repo, start_runner=False)
    client = TestClient(app)
    created = client.post("/api/jobs", json={"site_key": "site_01", "sim_id": "sim-a"}).json()

    resp = client.get(f"/api/jobs/{created['id']}/checkpoint")
    assert resp.status_code == 200
    assert resp.json()["checkpoint"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — endpoints missing.

- [ ] **Step 3: Implement**

In `create_app`, after the runner is created, wire the page provider to the session
manager so real runs use the browser's first page (guarded so it never crashes if
no session/page exists):

```python
    async def _page_provider(profile_id: str) -> Any:
        session = browser_sessions._active.get(profile_id)  # noqa: SLF001
        if session is None:
            opened = await browser_sessions.open_profile(profile_id)
            session = browser_sessions._active.get(opened.profile_id)  # noqa: SLF001
        context = session.context if session is not None else None
        if context is None:
            return None
        pages = getattr(context, "pages", None)
        if pages:
            return pages[0]
        new_page = getattr(context, "new_page", None)
        return await new_page() if new_page is not None else None

    runner.set_page_provider(_page_provider)
```

Add the job endpoints:

```python
    @app.post("/api/jobs/{job_id}/resume")
    async def resume_job(job_id: str) -> dict[str, str | bool]:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        runner.resume(job_id)
        return {"resumed": True, "job_id": job_id}

    @app.post("/api/jobs/{job_id}/pause")
    async def pause_job(job_id: str) -> dict[str, str | bool]:
        job = await repo.get_job(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status == JobStatus.RUNNING:
            await repo.update_job_status(
                job_id,
                JobStatus.WAITING_HUMAN,
                event_type="job.paused",
                message="Paused by operator",
            )
        return {"paused": True, "job_id": job_id}

    @app.get("/api/jobs/{job_id}/checkpoint")
    async def get_job_checkpoint(job_id: str) -> dict[str, Any]:
        checkpoint = runner.checkpoints.current(job_id)
        if checkpoint is None:
            return {"checkpoint": None}
        return {"checkpoint": {"kind": checkpoint.kind, "message": checkpoint.message}}
```

Note: the cancel endpoint should also cancel any pending checkpoint. In the existing
`cancel_job` endpoint, add `runner.cancel_checkpoint(job_id)` before updating status.

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/api/__init__.py tests/test_registry_api.py
git commit -m "feat: job pause/resume/checkpoint endpoints"
```

---

## Task 20: UI — profile rows, group sidebar, and job control helpers

**Files:**
- Modify: `src/account_automation_lab/ui/pages.py`
- Test: `tests/test_ui_pages.py` (extend)

NiceGUI page bodies are hard to unit-test, so the plan tests the **pure helper
functions** that transform data into table rows, and keeps the page wiring
mechanical. Follow the existing pattern in `pages.py` where `_job_rows`,
`_event_rows`, etc. are module-level pure functions tested directly.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ui_pages.py`:

```python
def test_browser_profile_rows_render_group_and_status() -> None:
    from account_automation_lab.models import (
        BrowserProfile,
        FingerprintConfig,
        ProfileStatus,
    )
    from account_automation_lab.ui.pages import _profile_manager_rows

    profile = BrowserProfile(
        id="p1",
        name="My FB",
        group_id="g1",
        tags=["fb", "warm"],
        storage_dir="C:/p/p1",
        status=ProfileStatus.ACTIVE,
        fingerprint=FingerprintConfig(timezone="Asia/Ho_Chi_Minh"),
    )

    rows = _profile_manager_rows(
        profiles=[profile],
        groups={"g1": "Facebook"},
        assignments=[],
        sessions=[],
    )

    assert rows[0]["name"] == "My FB"
    assert rows[0]["group"] == "Facebook"
    assert rows[0]["tags"] == "fb, warm"
    assert rows[0]["session"] == "idle"
    assert rows[0]["proxy"] == ""
    assert rows[0]["timezone"] == "Asia/Ho_Chi_Minh"


def test_group_options_include_all_and_ungrouped() -> None:
    from account_automation_lab.models import ProfileGroup
    from account_automation_lab.ui.pages import _group_filter_options

    options = _group_filter_options([ProfileGroup(id="g1", name="Facebook")])

    assert options["__all__"] == "All profiles"
    assert options["__none__"] == "Ungrouped"
    assert options["g1"] == "Facebook"
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — helpers not found.

- [ ] **Step 3: Implement the helpers**

In `src/account_automation_lab/ui/pages.py`, add these module-level pure functions
(near the other `_*_rows` helpers). Adjust imports to include `BrowserProfile`,
`ProfileGroup`:

```python
def _profile_manager_rows(
    *,
    profiles: list[BrowserProfile],
    groups: dict[str, str],
    assignments: list[ProfileProxyAssignment],
    sessions: list[BrowserSession],
) -> list[dict[str, str]]:
    proxy_by_profile = {a.profile_id: a for a in assignments}
    session_by_profile = {s.profile_id: s for s in sessions}
    rows: list[dict[str, str]] = []
    for profile in sorted(profiles, key=lambda p: p.name.lower()):
        session = session_by_profile.get(profile.id)
        assignment = proxy_by_profile.get(profile.id)
        rows.append(
            {
                "id": profile.id,
                "name": profile.name,
                "group": groups.get(profile.group_id or "", "") if profile.group_id else "",
                "tags": ", ".join(profile.tags),
                "status": profile.status.value,
                "session": session.status.value if session is not None else "idle",
                "proxy": assignment.proxy.masked_proxy if assignment is not None else "",
                "timezone": profile.fingerprint.timezone or "",
                "sim": profile.sim_id or "",
            }
        )
    return rows


def _group_filter_options(groups: list[ProfileGroup]) -> dict[str, str]:
    options = {"__all__": "All profiles", "__none__": "Ungrouped"}
    for group in sorted(groups, key=lambda g: g.name.lower()):
        options[group.id] = group.name
    return options
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Commit the helpers**

```bash
git add src/account_automation_lab/ui/pages.py tests/test_ui_pages.py
git commit -m "feat: profile-manager UI row helpers"
```

---

## Task 21: UI — wire the profile manager screen and job controls

**Files:**
- Modify: `src/account_automation_lab/ui/pages.py`

This task is page wiring (not unit-tested). Build it incrementally and verify by
launching the app once at the end. Reuse the helpers from Task 20.

- [ ] **Step 1: Rework the Profiles tab**

Replace the static profiles tab content with:
- A left column showing a group filter `ui.select(_group_filter_options(groups))`
  plus buttons to add/rename/delete a group (calling the group endpoints' service
  methods directly via `repo`).
- A right `ui.table` built from `_profile_manager_rows(...)` with columns
  Name / Group / Tags / Status / Session / Proxy / Timezone / SIM.
- Row action buttons Open / Close / Run / Edit / Clone / Delete (call the existing
  `browser_sessions` / `repo` / `browser_store` methods used by the API).
- A "＋ Create profile" button opening the config dialog from Step 2.

- [ ] **Step 2: Build the profile config dialog**

A reusable `ui.dialog` with sections (use `ui.expansion` or labelled rows):
- Basic: name, group (`ui.select` of groups), tags (comma input), notes,
  startup URL.
- Fingerprint: platform (`ui.select(["windows","macos"])`), seed
  (`ui.number`, blank = random), timezone (`ui.input`), locale (`ui.input`),
  color_scheme (`ui.select(["light","dark","no-preference"])`), user_agent
  (`ui.input`), viewport width/height (`ui.number` x2), geoip_from_proxy
  (`ui.switch`), extension paths (comma input).
- Proxy: reuse existing attach/buy/rotate buttons bound to `proxy_manager`.

On submit, build a `BrowserProfileCreate` (create) or `BrowserProfileUpdate`
(edit) and call `browser_store.create_profile` / `browser_store.update_profile`,
then `refresh_all()`.

- [ ] **Step 3: Add job control buttons**

In the Jobs tab, next to the existing Cancel button, add Resume and Pause buttons:

```python
                    ui.button(
                        "Resume", icon="play_arrow",
                        on_click=lambda: resume_job_ui(str(job_select.value or "")),
                    ).props("color=positive")
                    ui.button(
                        "Pause", icon="pause",
                        on_click=lambda: pause_job_ui(str(job_select.value or "")),
                    ).props("color=warning")
```

With handlers that update status / call `runner.resume`:

```python
        async def resume_job_ui(job_id: str) -> None:
            if not job_id:
                ui.notify("Select a job first", color="negative")
                return
            runner.resume(job_id)
            ui.notify(f"Resumed {_short_id(job_id)}", color="positive")
            await refresh_all()

        async def pause_job_ui(job_id: str) -> None:
            if not job_id:
                ui.notify("Select a job first", color="negative")
                return
            job = await repo.get_job(job_id)
            if job is not None and job.status == JobStatus.RUNNING:
                await repo.update_job_status(
                    job_id, JobStatus.WAITING_HUMAN,
                    event_type="job.paused", message="Paused by operator",
                )
            await refresh_all()
```

`runner` is available via `app.state.runner`; pass it into `mount_ui` the same way
other state is read (add `runner = app.state.runner` at the top of `mount_ui`).
Highlight `waiting_human` rows: when building job rows, a row with
`status == "waiting_human"` can be styled via a NiceGUI table cell slot or simply
shown as-is (styling is optional for the skeleton).

- [ ] **Step 4: Verify the app boots**

Set `DATABASE_BACKEND=memory` for this smoke check (no network), then launch:

```
$env:DATABASE_BACKEND="memory"; .\.venv\Scripts\python.exe -c "from account_automation_lab.api import create_app; from account_automation_lab.ui.pages import mount_ui; from account_automation_lab.settings import Settings; from account_automation_lab.repositories.memory import MemoryRepository; app = create_app(settings=Settings(database_backend='memory'), repository=MemoryRepository(), start_runner=False); mount_ui(app); print('UI mounted OK')" 2>&1 | Out-File -FilePath .tmp\ui_boot.log -Encoding utf8
```

Read `.tmp\ui_boot.log`; expected: `UI mounted OK` with no exception.

- [ ] **Step 5: Commit**

```bash
git add src/account_automation_lab/ui/pages.py
git commit -m "feat: AdsPower-style profile manager screen and job controls"
```

---

## Task 22: Flip default backend to Supabase and surface connection health

**Files:**
- Modify: `src/account_automation_lab/settings.py`
- Modify: `.env.example`
- Modify: `src/account_automation_lab/repositories/factory.py`
- Test: `tests/test_shared_database.py` (extend)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_shared_database.py`:

```python
def test_default_backend_is_supabase() -> None:
    from account_automation_lab.settings import Settings

    assert Settings().database_backend == "supabase"


def test_factory_falls_back_to_memory_when_supabase_unconfigured() -> None:
    from account_automation_lab.repositories.factory import create_repository
    from account_automation_lab.repositories.memory import MemoryRepository
    from account_automation_lab.settings import Settings

    # supabase selected but no URL/key -> factory returns a memory repo and does not crash
    repo = create_repository(Settings(database_backend="supabase", supabase_url=""))
    assert isinstance(repo, MemoryRepository)
```

- [ ] **Step 2: Run test to verify it fails**

Run the file. Expected: FAIL — default is still `memory`, and factory raises/creates
a Supabase client without credentials.

- [ ] **Step 3: Implement**

In `settings.py`, change the default:

```python
    database_backend: str = "supabase"
```

In `.env.example`, change `DATABASE_BACKEND=memory` to `DATABASE_BACKEND=supabase`
and add a comment that `memory` is for local dev/tests.

In `factory.py`, make Supabase selection degrade gracefully when unconfigured so the
app still boots offline (surfaced on the Settings page):

```python
def create_repository(settings: Settings) -> AutomationRepository:
    if settings.database_backend == "memory":
        return MemoryRepository()
    if settings.database_backend == "supabase":
        if not settings.supabase_url or not settings.supabase_service_role_key:
            return MemoryRepository()
        from account_automation_lab.repositories.supabase import SupabaseRepository

        return SupabaseRepository(settings)
    raise ValueError(f"Unsupported DATABASE_BACKEND={settings.database_backend!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run the file. Expected: PASS.

- [ ] **Step 5: Type check + lint + commit**

```bash
git add src/account_automation_lab/settings.py .env.example src/account_automation_lab/repositories/factory.py tests/test_shared_database.py
git commit -m "feat: default to Supabase backend with offline-safe fallback"
```

---

## Task 23: Full suite, docs, and cleanup

**Files:**
- Modify: `README.md`, `docs/automation-plan.md`
- Test: full suite

- [ ] **Step 1: Run the entire suite, mypy, and ruff**

```
.\.venv\Scripts\python.exe -m pytest -p no:cacheprovider -o addopts="" -q 2>&1 | Out-File -FilePath .tmp\all.log -Encoding utf8
.\.venv\Scripts\mypy.exe 2>&1 | Out-File -FilePath .tmp\mypy.log -Encoding utf8
.\.venv\Scripts\ruff.exe check . 2>&1 | Out-File -FilePath .tmp\ruff.log -Encoding utf8
```

Read all three logs. Expected: all tests pass, mypy clean, ruff clean. Fix any
failures before continuing (do not edit tests to pass — fix the code).

- [ ] **Step 2: Update docs**

In `README.md`, document: the profile manager (create/edit/clone/delete, groups,
tags, fingerprint fields and what each maps to in CloakBrowser), the workflow engine
and `WAITING_HUMAN` / resume / pause, and that Supabase is now the default backend
(with `DATABASE_BACKEND=memory` for offline/dev). In `docs/automation-plan.md`, mark
the profile manager and workflow engine as implemented.

- [ ] **Step 3: Clean up temp files**

Delete `.tmp\*.log` files created during the plan.

- [ ] **Step 4: Commit**

```bash
git add README.md docs/automation-plan.md
git commit -m "docs: document profile manager and workflow engine"
```

---

## Self-review notes (for the implementer)

- **Spec coverage:** Stage 1 storage (Tasks 8-9, 22), Stage 2 profile model + schema
  (Tasks 1-2, 9-10), Stage 3 engine + WAITING_HUMAN + human-in-the-loop (Tasks 3,
  12-17, 19), Stage 4 API + UI (Tasks 18-21). Secrets-never-in-DB is preserved by
  reusing the existing masked-proxy model (no proxy creds added to profile rows).
- **Backward compatibility:** existing tests for `BrowserProfileStore` and the
  per-site concurrency runner test need the small adjustments called out in Tasks 10
  and 17. Do not skip those notes.
- **Type strictness:** every new function is annotated; fake test classes annotate
  their methods. Run mypy after each task, not just at the end.
- **Order matters:** Tasks 1-3 change shared models; later tasks depend on them.
  Run only the task's own test file until Task 23 runs the whole suite (intermediate
  full-suite runs will fail while shared types are mid-migration).
