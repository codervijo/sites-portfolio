"""CHECK_035 — Vite version ≥ 6 (CF Pages safety; v3.A.1 fix from kwizicle)."""
from __future__ import annotations

from ..result import CheckResult
from . import _has_vite_config, _is_web_project, _parse_semver_min, _read_package_json

CHECK_ID = "CHECK_035"
CHECK_NAME = "vite-version-ok"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "Vite ≥ 6 (CF Pages bun-detection trap was hit on Vite 5)."

MIN_VITE = 6


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if not _has_vite_config(repo_path):
        return CheckResult(status="warn", message="not a Vite project — skipped")
    pkg = _read_package_json(repo_path)
    if pkg is None:
        return CheckResult(status="warn", message="package.json unreadable — skipped")
    deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    vite_spec = deps.get("vite")
    if not vite_spec:
        return CheckResult(status="warn",
                           message="vite.config.* exists but vite not in package.json")
    major = _parse_semver_min(vite_spec)
    if major is None:
        return CheckResult(status="warn", message=f"unparseable vite version: {vite_spec}")
    if major >= MIN_VITE:
        return CheckResult(status="pass", message=f"vite ^{major}")
    return CheckResult(status="fail",
                       message=f"vite ^{major} — needs ≥{MIN_VITE} for CF Pages")
