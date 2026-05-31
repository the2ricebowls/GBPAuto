from __future__ import annotations

import pkgutil
from importlib import import_module

import account_automation_lab.adapters as adapters_pkg
from account_automation_lab.adapters.base import GenericSiteAdapter, SiteAdapter
from account_automation_lab.models import SiteSpec

# Modules in this package that are infrastructure, not site adapters.
_NON_ADAPTER_MODULES = {"base", "registry"}

_CACHE: dict[str, SiteAdapter] | None = None


def load_adapters() -> dict[str, SiteAdapter]:
    """Discover every code adapter module in the adapters package.

    Each adapter module exposes a module-level ``adapter`` with a ``spec``.
    Add a new site by dropping a module next to ``example.py``.
    """
    global _CACHE
    if _CACHE is not None:
        return dict(_CACHE)
    adapters: dict[str, SiteAdapter] = {}
    for module_info in pkgutil.iter_modules(adapters_pkg.__path__):
        name = module_info.name
        if name in _NON_ADAPTER_MODULES or name.startswith("_"):
            continue
        module = import_module(f"account_automation_lab.adapters.{name}")
        adapter = getattr(module, "adapter", None)
        if adapter is None:
            continue
        adapters[adapter.spec.key] = adapter
    _CACHE = adapters
    return dict(adapters)


def code_adapter_keys() -> frozenset[str]:
    """Site keys that have a bespoke code adapter."""
    return frozenset(load_adapters())


def adapter_for(site_key: str, spec: SiteSpec | None = None) -> SiteAdapter:
    """Return the adapter for a site.

    If a code adapter module is registered for ``site_key`` it wins. Otherwise,
    when a ``spec`` is supplied (a data-only site managed in the UI), a generic
    fallback adapter is returned so the site can still be opened and driven by
    hand. Without either, a ``KeyError`` is raised.
    """
    adapters = load_adapters()
    existing = adapters.get(site_key)
    if existing is not None:
        return existing
    if spec is not None:
        return GenericSiteAdapter(spec)
    raise KeyError(f"Unknown site adapter: {site_key}")
