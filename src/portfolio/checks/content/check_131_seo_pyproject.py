"""CHECK_131 — `seo/pyproject.toml` exists (content worker is a Python project)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_131"
CHECK_NAME = "seo-pyproject"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = "seo/pyproject.toml exists (declares content-pipeline Python deps)."


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    p = Path(repo_path) / "seo" / "pyproject.toml"
    if p.is_file():
        return CheckResult(status="pass", message="seo/pyproject.toml present")
    return CheckResult(status="fail", message="seo/pyproject.toml missing")
