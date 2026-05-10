"""CHECK_132 — `seo/uv.lock` exists (deterministic content-worker deps)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_132"
CHECK_NAME = "seo-uv-lock"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = "seo/uv.lock exists (uv-managed lockfile pins worker deps)."


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    p = Path(repo_path) / "seo" / "uv.lock"
    if p.is_file():
        return CheckResult(status="pass", message="seo/uv.lock present")
    return CheckResult(status="fail",
                       message="seo/uv.lock missing — run `uv lock` in seo/")
