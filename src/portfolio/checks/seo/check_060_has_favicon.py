"""CHECK_060 — Has public/favicon.{ico,png,svg,jpg,jpeg}."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_060"
CHECK_NAME = "has-favicon"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "public/favicon.* exists (any common extension)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    public = Path(repo_path) / "public"
    if not public.is_dir():
        return CheckResult(status="fail", message="public/ missing")
    for ext in ("ico", "png", "svg", "jpg", "jpeg", "webp"):
        if list(public.glob(f"favicon.{ext}")):
            return CheckResult(status="pass", message=f"favicon.{ext} present")
    return CheckResult(status="fail", message="public/favicon.* missing")
