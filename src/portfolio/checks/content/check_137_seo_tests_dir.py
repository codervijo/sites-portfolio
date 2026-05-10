"""CHECK_137 — `seo/tests/` directory exists (worker has its own test suite)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_137"
CHECK_NAME = "seo-tests-dir"
CATEGORY = "content"
SEVERITY = "info"
DESCRIPTION = "seo/tests/ exists — content-worker has its own test suite."


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    tests = Path(repo_path) / "seo" / "tests"
    if tests.is_dir():
        return CheckResult(status="pass", message="seo/tests/ present")
    return CheckResult(status="warn", message="seo/tests/ missing")
