"""v6.C — Fixer registry: discovers `fix_tier_1` / `fix_tier_2` attrs
on each check module.

Mirrors the check registry's lazy-discovery pattern. Walks every
discovered check module looking for module-level attributes:

  fix_tier_1: FixerSpec     (Tier 1 — templated)
  fix_tier_2: FixerSpec     (Tier 2 — Claude subprocess; v6.C.1+)

Both are optional; absence means "no auto-fix at this tier" (the
check ends up in the manual list).

The check-module's `CHECK_ID` is authoritative — the registry rewrites
each FixerSpec's `check_id` field via dataclasses.replace at discovery
time, so factories don't have to know the ID up front.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import replace

from .checks.registry import _all_checks
from .fix_helpers import FixerSpec


_TIER_1_CACHE: dict[str, FixerSpec] | None = None
_TIER_2_CACHE: dict[str, FixerSpec] | None = None


def _discover(tier_attr: str, tier: int) -> dict[str, FixerSpec]:
    """Walk every check module via the existing check registry, pulling
    `tier_attr` (e.g. 'fix_tier_1') off each. Returns a {check_id → FixerSpec}
    dict with the check_id field rewritten to match the module's CHECK_ID."""
    out: dict[str, FixerSpec] = {}
    for spec in _all_checks().values():
        mod = importlib.import_module(spec.module_name)
        fix_spec = getattr(mod, tier_attr, None)
        if fix_spec is None:
            continue
        if not isinstance(fix_spec, FixerSpec):
            raise TypeError(
                f"{spec.module_name}.{tier_attr} must be a FixerSpec, "
                f"got {type(fix_spec).__name__}"
            )
        if fix_spec.tier != tier:
            raise ValueError(
                f"{spec.module_name}.{tier_attr} has tier={fix_spec.tier}, "
                f"expected tier={tier}"
            )
        out[spec.id] = replace(fix_spec, check_id=spec.id)
    return out


def reset_cache() -> None:
    """Force re-discovery on next access."""
    global _TIER_1_CACHE, _TIER_2_CACHE
    _TIER_1_CACHE = None
    _TIER_2_CACHE = None


def list_tier_1() -> dict[str, FixerSpec]:
    global _TIER_1_CACHE
    if _TIER_1_CACHE is None:
        _TIER_1_CACHE = _discover("fix_tier_1", tier=1)
    return _TIER_1_CACHE


def list_tier_2() -> dict[str, FixerSpec]:
    global _TIER_2_CACHE
    if _TIER_2_CACHE is None:
        _TIER_2_CACHE = _discover("fix_tier_2", tier=2)
    return _TIER_2_CACHE


def get_tier_1(check_id: str) -> FixerSpec | None:
    return list_tier_1().get(check_id)


def get_tier_2(check_id: str) -> FixerSpec | None:
    return list_tier_2().get(check_id)


def fixable_check_ids(*, tier: int = 1) -> set[str]:
    """Set of CHECK_IDs that have a fixer at the requested tier."""
    if tier == 1:
        return set(list_tier_1().keys())
    if tier == 2:
        return set(list_tier_2().keys())
    raise ValueError(f"unknown tier: {tier!r}")
