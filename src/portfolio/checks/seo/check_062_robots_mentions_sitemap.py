"""CHECK_062 — robots.txt declares Sitemap: <url>."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_web_project

CHECK_ID = "CHECK_062"
CHECK_NAME = "robots-mentions-sitemap"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "robots.txt declares the sitemap URL via `Sitemap: ...` line."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    p = Path(repo_path) / "public" / "robots.txt"
    if not p.is_file():
        return CheckResult(status="warn", message="robots.txt missing — skipped")
    text = p.read_text(errors="replace")
    for line in text.splitlines():
        if line.strip().lower().startswith("sitemap:"):
            return CheckResult(status="pass", message="Sitemap line present")
    return CheckResult(status="fail", message="robots.txt has no `Sitemap:` line")
