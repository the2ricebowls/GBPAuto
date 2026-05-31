import importlib
import sys
import types
from pathlib import Path
from typing import Any, cast

import pytest

from account_automation_lab.adapters.registry import adapter_for
from account_automation_lab.browser.runtime import (
    BrowserProfileConfig,
    CloakBrowserRuntime,
    PlaywrightChromiumRuntime,
)
from account_automation_lab.models import JobCreate, RuntimeKind
from account_automation_lab.settings import Settings


def test_cloakbrowser_is_default_runtime_for_jobs_and_sites() -> None:
    assert JobCreate(site_key="site_01", sim_id="sim-a").runtime == RuntimeKind.CLOAKBROWSER
    assert adapter_for("example").spec.default_runtime == RuntimeKind.CLOAKBROWSER


def test_cloakbrowser_settings_support_local_binary_override() -> None:
    settings = Settings(cloakbrowser_binary_path=r"C:\Users\vanto\.cloakbrowser\chrome.exe")

    assert settings.cloakbrowser_binary_path.endswith("chrome.exe")


@pytest.mark.asyncio
async def test_cloakbrowser_runtime_launches_persistent_context_with_profile_proxy_and_extensions(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_launcher(**kwargs: object) -> str:
        calls.append(kwargs)
        return "context"

    runtime = CloakBrowserRuntime(Settings(), launcher=fake_launcher)
    context = await runtime.launch_context(
        BrowserProfileConfig(
            profile_id="sim-a:site_01",
            storage_dir=tmp_path / "profile",
            proxy={"server": "http://160.250.166.88:20308", "username": "u", "password": "p"},
            extension_paths=(tmp_path / "extension",),
        )
    )

    assert context == "context"
    assert len(calls) == 1
    call = calls[0]
    assert call["user_data_dir"] == str(tmp_path / "profile")
    assert call["headless"] is False
    assert call["proxy"] == {
        "server": "http://160.250.166.88:20308",
        "username": "u",
        "password": "p",
    }
    assert call["humanize"] is True
    assert call["extension_paths"] == [str(tmp_path / "extension")]


@pytest.mark.asyncio
async def test_cloakbrowser_headed_launch_fits_screen_without_no_sandbox_warning(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    async def fake_launcher(**kwargs: object) -> str:
        calls.append(kwargs)
        return "context"

    runtime = CloakBrowserRuntime(
        Settings(cloakbrowser_window_width=1600, cloakbrowser_window_height=900),
        launcher=fake_launcher,
    )

    await runtime.launch_context(
        BrowserProfileConfig(profile_id="sim-a:site_01", storage_dir=tmp_path / "profile")
    )

    call = calls[0]
    args = cast(list[str], call["args"])
    assert call["viewport"] is None
    assert call["stealth_args"] is False
    assert "--no-sandbox" not in args
    assert "--start-maximized" in args
    assert "--window-position=0,0" in args
    assert "--window-size=1600,900" in args
    assert "--fingerprint-screen-width=1600" in args
    assert "--fingerprint-screen-height=900" in args
    assert any(arg.startswith("--fingerprint=") for arg in args)
    assert any(arg.startswith("--fingerprint-platform=") for arg in args)


@pytest.mark.asyncio
async def test_cloakbrowser_runtime_ignores_playwright_no_sandbox_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    async def fake_launcher(**_kwargs: object) -> str:
        return "context"

    cloakbrowser_browser = importlib.import_module("cloakbrowser.browser")
    monkeypatch.setattr(cloakbrowser_browser, "IGNORE_DEFAULT_ARGS", ["--enable-automation"])

    runtime = CloakBrowserRuntime(Settings(), launcher=fake_launcher)
    await runtime.launch_context(
        BrowserProfileConfig(profile_id="sim-a:site_01", storage_dir=tmp_path / "profile")
    )

    ignore_default_args = cast(list[str], cloakbrowser_browser.IGNORE_DEFAULT_ARGS)
    assert "--no-sandbox" in ignore_default_args


@pytest.mark.asyncio
async def test_playwright_chromium_runtime_stops_driver_when_context_closes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class FakeContext:
        async def close(self) -> None:
            events.append("context.close")

    class FakeChromium:
        async def launch_persistent_context(self, **_kwargs: object) -> FakeContext:
            return FakeContext()

    class FakePlaywright:
        def __init__(self) -> None:
            self.chromium = FakeChromium()

        async def stop(self) -> None:
            events.append("playwright.stop")

    class FakePlaywrightStarter:
        async def start(self) -> FakePlaywright:
            events.append("playwright.start")
            return FakePlaywright()

    fake_playwright = types.ModuleType("playwright")
    fake_async_api = types.ModuleType("playwright.async_api")
    cast(Any, fake_async_api).async_playwright = lambda: FakePlaywrightStarter()
    cast(Any, fake_playwright).async_api = fake_async_api
    monkeypatch.setitem(sys.modules, "playwright", fake_playwright)
    monkeypatch.setitem(sys.modules, "playwright.async_api", fake_async_api)

    runtime = PlaywrightChromiumRuntime()
    context = await runtime.launch_context(
        BrowserProfileConfig(profile_id="sim-a:site_01", storage_dir=tmp_path / "profile")
    )

    await context.close()

    assert events == ["playwright.start", "context.close", "playwright.stop"]


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
