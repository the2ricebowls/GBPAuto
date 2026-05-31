from __future__ import annotations

from importlib import import_module

from account_automation_lab.adapters.base import SiteAdapter

_MODULES = tuple(f"account_automation_lab.adapters.site_{index:02d}" for index in range(1, 11))
_CACHE: dict[str, SiteAdapter] | None = None


def load_adapters() -> dict[str, SiteAdapter]:
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    adapters: dict[str, SiteAdapter] = {}
    for module_name in _MODULES:
        module = import_module(module_name)
        adapter = module.adapter
        adapters[adapter.spec.key] = adapter
    _CACHE = adapters
    return dict(adapters)


def adapter_for(site_key: str) -> SiteAdapter:
    adapters = load_adapters()
    try:
        return adapters[site_key]
    except KeyError as exc:
        raise KeyError(f"Unknown site adapter: {site_key}") from exc
