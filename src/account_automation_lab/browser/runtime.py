from __future__ import annotations

import importlib
import os
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from account_automation_lab.models import RuntimeKind
from account_automation_lab.settings import Settings


@dataclass(frozen=True)
class BrowserProfileConfig:
    profile_id: str
    storage_dir: Path
    proxy: str | dict[str, str] | None = None
    extension_paths: tuple[Path, ...] = ()
    fingerprint_kwargs: dict[str, Any] | None = None


class BrowserRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class WindowGeometry:
    left: int
    top: int
    width: int
    height: int
    screen_width: int
    screen_height: int


class PlaywrightChromiumRuntime:
    async def launch_context(self, config: BrowserProfileConfig) -> Any:
        from playwright.async_api import async_playwright

        playwright = await async_playwright().start()
        args = [f"--disable-extensions-except={path}" for path in config.extension_paths]
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(config.storage_dir),
            headless=False,
            args=args,
            proxy=cast(Any, _playwright_proxy(config.proxy)),
        )
        return _PlaywrightManagedContext(context=context, playwright=playwright)


@dataclass
class _PlaywrightManagedContext:
    context: Any
    playwright: Any

    def __getattr__(self, name: str) -> Any:
        return getattr(self.context, name)

    async def close(self) -> None:
        try:
            await self.context.close()
        finally:
            await self.playwright.stop()


class CloakBrowserRuntime:
    def __init__(
        self,
        settings: Settings,
        launcher: Callable[..., Awaitable[Any]] | None = None,
    ) -> None:
        self.settings = settings
        self.launcher = launcher

    async def launch_context(self, config: BrowserProfileConfig) -> Any:
        if not self.settings.cloakbrowser_enabled:
            raise BrowserRuntimeError("CloakBrowser runtime is disabled.")
        if self.settings.cloakbrowser_binary_path:
            os.environ["CLOAKBROWSER_BINARY_PATH"] = self.settings.cloakbrowser_binary_path
        if self.settings.cloakbrowser_filter_no_sandbox:
            _patch_cloakbrowser_ignore_default_args()
        launcher = self.launcher
        if launcher is None:
            from cloakbrowser import launch_persistent_context_async  # type: ignore[import-untyped]

            launcher = launch_persistent_context_async
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
        fingerprint_viewport_set = "viewport" in fingerprint_kwargs
        launch_kwargs.update(fingerprint_kwargs)

        args = _cloakbrowser_args(self.settings) + list(fingerprint_args)
        if args:
            launch_kwargs["args"] = args
        if _should_fit_screen(self.settings) and not fingerprint_viewport_set:
            launch_kwargs["viewport"] = None
        return await launcher(**launch_kwargs)


def runtime_for(
    kind: RuntimeKind,
    settings: Settings,
) -> PlaywrightChromiumRuntime | CloakBrowserRuntime:
    if kind == RuntimeKind.PLAYWRIGHT_CHROMIUM:
        return PlaywrightChromiumRuntime()
    return CloakBrowserRuntime(settings)


def _playwright_proxy(proxy: str | dict[str, str] | None) -> dict[str, str] | None:
    if proxy is None:
        return None
    if isinstance(proxy, str):
        return {"server": proxy}
    return proxy


def _cloakbrowser_args(settings: Settings) -> list[str]:
    args: list[str] = []
    if settings.cloakbrowser_filter_no_sandbox:
        args.extend(_default_stealth_args_without_no_sandbox())
    if _should_fit_screen(settings):
        args.extend(_headed_window_args(settings))
    return args


def _should_fit_screen(settings: Settings) -> bool:
    return settings.cloakbrowser_fit_screen and not settings.cloakbrowser_headless


def _default_stealth_args_without_no_sandbox() -> list[str]:
    from cloakbrowser.config import get_default_stealth_args  # type: ignore[import-untyped]

    return [
        arg
        for arg in get_default_stealth_args()
        if arg.split("=", 1)[0] != "--no-sandbox"
    ]


def _patch_cloakbrowser_ignore_default_args() -> None:
    cloakbrowser_browser = cast(Any, importlib.import_module("cloakbrowser.browser"))
    ignore_default_args = cast(list[str], cloakbrowser_browser.IGNORE_DEFAULT_ARGS)
    if "--no-sandbox" not in ignore_default_args:
        ignore_default_args.append("--no-sandbox")


def _headed_window_args(settings: Settings) -> list[str]:
    geometry = _resolve_window_geometry(settings)
    args = [
        f"--window-position={geometry.left},{geometry.top}",
        f"--window-size={geometry.width},{geometry.height}",
        f"--fingerprint-screen-width={geometry.screen_width}",
        f"--fingerprint-screen-height={geometry.screen_height}",
    ]
    if settings.cloakbrowser_start_maximized:
        args.insert(0, "--start-maximized")
    return args


def _resolve_window_geometry(settings: Settings) -> WindowGeometry:
    detected = _windows_primary_monitor_geometry() or WindowGeometry(
        left=0,
        top=0,
        width=1920,
        height=1080,
        screen_width=1920,
        screen_height=1080,
    )
    width = settings.cloakbrowser_window_width or detected.width
    height = settings.cloakbrowser_window_height or detected.height
    screen_width = settings.cloakbrowser_window_width or detected.screen_width
    screen_height = settings.cloakbrowser_window_height or detected.screen_height
    return WindowGeometry(
        left=detected.left,
        top=detected.top,
        width=width,
        height=height,
        screen_width=screen_width,
        screen_height=screen_height,
    )


def _windows_primary_monitor_geometry() -> WindowGeometry | None:
    if os.name != "nt":
        return None
    try:
        import ctypes

        class Rect(ctypes.Structure):
            _fields_ = [
                ("left", ctypes.c_long),
                ("top", ctypes.c_long),
                ("right", ctypes.c_long),
                ("bottom", ctypes.c_long),
            ]

        user32 = ctypes.windll.user32
        try:
            user32.SetProcessDPIAware()
        except OSError:
            pass
        screen_width = int(user32.GetSystemMetrics(0))
        screen_height = int(user32.GetSystemMetrics(1))
        rect = Rect()
        if user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
            return WindowGeometry(
                left=int(rect.left),
                top=int(rect.top),
                width=int(rect.right - rect.left),
                height=int(rect.bottom - rect.top),
                screen_width=screen_width,
                screen_height=screen_height,
            )
        return WindowGeometry(
            left=0,
            top=0,
            width=screen_width,
            height=screen_height,
            screen_width=screen_width,
            screen_height=screen_height,
        )
    except (AttributeError, OSError, ValueError):
        return None
