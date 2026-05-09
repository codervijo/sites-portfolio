"""CHECK_063 — Has public/sitemap.xml OR scripts/generate-sitemap.* (build-time)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_063"
CHECK_NAME = "has-sitemap-xml"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "public/sitemap.xml exists OR scripts/generate-sitemap.* generates it at build time."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    base = Path(repo_path)
    if (base / "public" / "sitemap.xml").is_file():
        return CheckResult(status="pass", message="public/sitemap.xml present")
    scripts = base / "scripts"
    if scripts.is_dir():
        for ext in ("js", "mjs", "ts"):
            if list(scripts.glob(f"generate-sitemap.{ext}")) or \
               list(scripts.glob(f"generate-sitemap.*.{ext}")):
                return CheckResult(status="pass",
                                   message=f"scripts/generate-sitemap.{ext} (build-time generation)")
    return CheckResult(status="fail",
                       message="no public/sitemap.xml and no scripts/generate-sitemap.*")
