"""CHECK_061 — Has public/robots.txt."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_061"
CHECK_NAME = "has-robots-txt"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "public/robots.txt exists."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    p = Path(repo_path) / "public" / "robots.txt"
    if p.is_file():
        return CheckResult(status="pass", message="robots.txt present")
    return CheckResult(status="fail", message="public/robots.txt missing")
