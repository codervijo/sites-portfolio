"""CHECK_011 — Has .env.example."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult

CHECK_ID = "CHECK_011"
CHECK_NAME = "has-env-example"
CATEGORY = "scaffold"
SEVERITY = "info"
DESCRIPTION = ".env.example documents the env vars new contributors should set."


def run(repo_path: str) -> CheckResult:
    p = Path(repo_path) / ".env.example"
    if p.exists() and p.is_file():
        return CheckResult(status="pass", message=".env.example present")
    return CheckResult(status="warn", message=".env.example missing")
