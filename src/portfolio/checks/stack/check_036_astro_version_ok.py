"""CHECK_036 — Astro version ≥ 5."""
from __future__ import annotations

from ..result import CheckResult
from . import (
    NON_JS_FRAMEWORKS,
    _has_astro_config,
    _is_web_project,
    _parse_semver_min,
    _read_package_json,
    declared_stack,
)

CHECK_ID = "CHECK_036"
CHECK_NAME = "astro-version-ok"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "Astro ≥ 5 (current canonical for new sites/* Astro projects)."

MIN_ASTRO = 5


def run(repo_path: str) -> CheckResult:
    # v27.E — read [stack] first; skip wordpress/static/none by
    # declaration. Absent declaration → fall through to the heuristic.
    declared = declared_stack(repo_path)
    if declared in NON_JS_FRAMEWORKS:
        return CheckResult(status="warn",
                           message=f"stack declared {declared} — not an astro site")
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if not _has_astro_config(repo_path):
        return CheckResult(status="warn",
                           message="not an Astro project — skipped")
    pkg = _read_package_json(repo_path)
    if pkg is None:
        return CheckResult(status="warn", message="package.json unreadable — skipped")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    astro_spec = deps.get("astro")
    if not astro_spec:
        return CheckResult(status="warn",
                           message="astro.config.* exists but astro not in package.json")
    major = _parse_semver_min(astro_spec)
    if major is None:
        return CheckResult(status="warn", message=f"unparseable astro version: {astro_spec}")
    if major >= MIN_ASTRO:
        return CheckResult(status="pass", message=f"astro ^{major}")
    return CheckResult(status="fail", message=f"astro ^{major} — needs ≥{MIN_ASTRO}")
