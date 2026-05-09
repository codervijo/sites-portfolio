"""v5.A — Universal check registry.

Auto-discovers `check_NNN_<slug>.py` modules under `portfolio/checks/<category>/`,
each declaring:
  - `CHECK_ID` (str, e.g. "CHECK_001")
  - `CHECK_NAME` (str)
  - `CATEGORY` (str — usually matches the parent directory name)
  - `SEVERITY` (str: "error" | "warn" | "info")
  - `DESCRIPTION` (str)
  - `run(repo_path: str) -> CheckResult`

Discovery happens lazily on first registry access. Add a new check by
dropping a file into the right category directory — no edits elsewhere.
"""
from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .result import CheckResult


@dataclass(frozen=True)
class CheckSpec:
    """Discovered metadata + runner for one check."""
    id: str
    name: str
    category: str
    severity: str
    description: str
    run: Callable[[str], CheckResult]
    module_name: str  # for debugging — fully-qualified module path


_CACHE: dict[str, CheckSpec] | None = None


def _discover() -> dict[str, CheckSpec]:
    """Walk `portfolio.checks.*` subpackages and collect every `check_*.py`
    module that declares the required attributes."""
    out: dict[str, CheckSpec] = {}
    pkg = importlib.import_module("portfolio.checks")
    pkg_path: list[str] = list(getattr(pkg, "__path__", []))
    # Walk subpackages (categories) at depth 1, then their check_*.py modules.
    for category_info in pkgutil.iter_modules(pkg_path):
        if not category_info.ispkg:
            continue
        category = category_info.name
        sub_pkg = importlib.import_module(f"portfolio.checks.{category}")
        sub_path: list[str] = list(getattr(sub_pkg, "__path__", []))
        for mod_info in pkgutil.iter_modules(sub_path):
            if not mod_info.name.startswith("check_"):
                continue
            mod_name = f"portfolio.checks.{category}.{mod_info.name}"
            mod = importlib.import_module(mod_name)
            try:
                check_id = getattr(mod, "CHECK_ID")
                check_name = getattr(mod, "CHECK_NAME")
                check_severity = getattr(mod, "SEVERITY")
                check_description = getattr(mod, "DESCRIPTION")
                check_run = getattr(mod, "run")
                check_category = getattr(mod, "CATEGORY", category)
            except AttributeError as e:
                raise RuntimeError(
                    f"check module {mod_name} is missing a required attribute: {e}"
                )
            if check_id in out:
                raise RuntimeError(
                    f"duplicate CHECK_ID {check_id!r} in {mod_name} "
                    f"(already defined by {out[check_id].module_name})"
                )
            out[check_id] = CheckSpec(
                id=check_id,
                name=check_name,
                category=check_category,
                severity=check_severity,
                description=check_description,
                run=check_run,
                module_name=mod_name,
            )
    return out


def _all_checks() -> dict[str, CheckSpec]:
    global _CACHE
    if _CACHE is None:
        _CACHE = _discover()
    return _CACHE


def reset_cache() -> None:
    """Force re-discovery on next access. Useful in tests after dynamically
    adding/removing check modules."""
    global _CACHE
    _CACHE = None


def list_checks(
    *, category: str | None = None, ids: list[str] | None = None
) -> list[CheckSpec]:
    """Return all discovered checks, optionally filtered by category or ID list.
    Sorted by CHECK_ID ascending so output is stable."""
    items = list(_all_checks().values())
    if category is not None:
        items = [c for c in items if c.category == category]
    if ids is not None:
        wanted = set(ids)
        items = [c for c in items if c.id in wanted]
    items.sort(key=lambda c: c.id)
    return items


def get_check(check_id: str) -> CheckSpec:
    """Look up one check by ID. Raises KeyError if unknown."""
    spec = _all_checks().get(check_id)
    if spec is None:
        raise KeyError(f"unknown check: {check_id!r}")
    return spec


def run_check(check_id: str, repo_path: str) -> CheckResult:
    """Run a single check by ID against `repo_path`.

    Wraps the check's `run()` so any exception inside the check becomes a
    `warn`-status result with the exception text as the message — keeps
    runner loops from crashing on a single check failure."""
    spec = get_check(check_id)
    try:
        result = spec.run(repo_path)
    except Exception as e:
        return CheckResult(status="warn",
                           message=f"check raised {type(e).__name__}: {e}")
    if not isinstance(result, CheckResult):
        return CheckResult(status="warn",
                           message=f"check returned non-CheckResult: {type(result).__name__}")
    return result


def run_checks(
    repo_path: str,
    *,
    category: str | None = None,
    ids: list[str] | None = None,
    skip_checks: list[str] | None = None,
) -> dict[str, CheckResult]:
    """Run multiple checks. Returns `{check_id: CheckResult}`. Order matches
    `list_checks()` (CHECK_ID ascending)."""
    skip = set(skip_checks or [])
    out: dict[str, CheckResult] = {}
    for spec in list_checks(category=category, ids=ids):
        if spec.id in skip:
            out[spec.id] = CheckResult(status="warn", message="skipped via config")
            continue
        out[spec.id] = run_check(spec.id, repo_path)
    return out
