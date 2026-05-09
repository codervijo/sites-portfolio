"""CHECK_031 — Has pnpm-lock.yaml (web project)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_031"
CHECK_NAME = "has-pnpm-lock"
CATEGORY = "stack"
SEVERITY = "error"
DESCRIPTION = "pnpm-lock.yaml exists (pnpm is the canonical package manager for sites/*)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    if (Path(repo_path) / "pnpm-lock.yaml").is_file():
        return CheckResult(status="pass", message="pnpm-lock.yaml present")
    return CheckResult(status="fail", message="pnpm-lock.yaml missing")
