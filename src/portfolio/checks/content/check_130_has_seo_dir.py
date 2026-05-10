"""CHECK_130 — Has a `seo/` subdirectory (the content-pipeline marker)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_130"
CHECK_NAME = "has-seo-dir"
CATEGORY = "content"
SEVERITY = "info"
DESCRIPTION = (
    "Project has a `seo/` subdirectory at root — the marker for the "
    "content-pipeline pattern (hybridautopart-style). Absent on most "
    "web projects; absence is a skip, not a fail."
)


def run(repo_path: str) -> CheckResult:
    if _is_content_project(repo_path):
        return CheckResult(status="pass", message="seo/ present (content-pipeline project)")
    return CheckResult(status="warn", message="not a content-pipeline project — skipped")
