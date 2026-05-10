"""CHECK_136 — `seo/Makefile.pipeline` exists (wires content-worker steps)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_136"
CHECK_NAME = "seo-makefile-pipeline"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = "seo/Makefile.pipeline exists — orchestrates content-generation steps."


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    p = Path(repo_path) / "seo" / "Makefile.pipeline"
    if p.is_file():
        return CheckResult(status="pass", message="seo/Makefile.pipeline present")
    return CheckResult(status="fail", message="seo/Makefile.pipeline missing")
