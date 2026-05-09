"""CHECK_073 — index has <meta name="viewport"> (mobile-friendly)."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_index_html

CHECK_ID = "CHECK_073"
CHECK_NAME = "has-meta-viewport"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = '<meta name="viewport"> present (mobile-friendly).'


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")
    soup = _parse_html(html)
    tag = soup.find("meta", attrs={"name": "viewport"})
    if tag is None or not tag.get("content", "").strip():
        return CheckResult(status="fail", message='<meta name="viewport"> missing')
    return CheckResult(status="pass", message="viewport meta present")
