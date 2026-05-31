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

    args: list[str] = []
    if fingerprint.platform != FingerprintConfig().platform:
        args.append(f"--fingerprint-platform={fingerprint.platform.value}")
    if fingerprint.seed is not None:
        args.append(f"--fingerprint={fingerprint.seed}")
    if args:
        kwargs["args"] = args
    return kwargs
