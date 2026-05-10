"""CHECK_011 — Has .env.example."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...fix_helpers import file_writer
from ... import templates

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


fix_tier_1 = file_writer(
    ".env.example",
    render=lambda _p: templates.env_example(),
    summary="write .env.example",
)
