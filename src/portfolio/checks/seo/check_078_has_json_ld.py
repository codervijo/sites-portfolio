"""CHECK_078 — <script type="application/ld+json"> present."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_078"
CHECK_NAME = "has-json-ld"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = '<script type="application/ld+json"> present (structured data).'


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    if not scripts:
        return CheckResult(status="fail",
                           message='<script type="application/ld+json"> missing')
    return CheckResult(status="pass",
                       message=f"{len(scripts)} JSON-LD block(s) present")
