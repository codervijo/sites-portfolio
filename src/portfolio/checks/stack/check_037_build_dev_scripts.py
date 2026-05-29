"""CHECK_037 — package.json has both `build` and `dev` scripts."""
from __future__ import annotations

from ..result import CheckResult
from . import (
    NON_JS_FRAMEWORKS,
    _is_web_project,
    _read_package_json,
    declared_stack,
)

CHECK_ID = "CHECK_037"
CHECK_NAME = "package-json-build-and-dev-scripts"
CATEGORY = "stack"
SEVERITY = "warn"
DESCRIPTION = "package.json has both `build` and `dev` scripts."


def run(repo_path: str) -> CheckResult:
    # v27.E — read [stack] first. A wordpress/static/none site has no npm
    # build pipeline, so build/dev scripts aren't required; skip by
    # declaration. Absent declaration → fall through to the heuristic.
    declared = declared_stack(repo_path)
    if declared in NON_JS_FRAMEWORKS:
        return CheckResult(status="warn",
                           message=f"stack declared {declared} — no npm build pipeline")
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    pkg = _read_package_json(repo_path)
    if pkg is None:
        return CheckResult(status="warn", message="package.json unreadable — skipped")
    scripts = pkg.get("scripts", {})
    has_build = "build" in scripts
    has_dev = "dev" in scripts
    if has_build and has_dev:
        return CheckResult(status="pass", message="build + dev scripts present")
    missing = []
    if not has_build:
        missing.append("build")
    if not has_dev:
        missing.append("dev")
    return CheckResult(status="fail", message=f"missing scripts: {', '.join(missing)}")
