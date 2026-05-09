"""CHECK_075 — <meta name="robots"> present."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_index_html

CHECK_ID = "CHECK_075"
CHECK_NAME = "has-meta-robots"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = '<meta name="robots" content="..."> present (e.g. "index, follow").'


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")
    soup = _parse_html(html)
    tag = soup.find("meta", attrs={"name": "robots"})
    if tag is None or not tag.get("content", "").strip():
        return CheckResult(status="warn", message='<meta name="robots"> missing')
    return CheckResult(status="pass", message=f'robots={tag["content"]!r}')
