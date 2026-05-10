"""CHECK_133 — `seo/CLAUDE.md` exists (content-worker orientation)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_133"
CHECK_NAME = "seo-claude-md"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = "seo/CLAUDE.md exists — Claude orientation for the content worker."


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    p = Path(repo_path) / "seo" / "CLAUDE.md"
    if p.is_file():
        return CheckResult(status="pass", message="seo/CLAUDE.md present")
    return CheckResult(status="fail", message="seo/CLAUDE.md missing")
