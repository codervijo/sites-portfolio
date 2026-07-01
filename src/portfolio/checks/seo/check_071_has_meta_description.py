"""CHECK_071 — index has <meta name="description"> of reasonable length (120-160)."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_071"
CHECK_NAME = "has-meta-description"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = '<meta name="description"> present and 120-160 characters.'


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    tag = soup.find("meta", attrs={"name": "description"})
    if tag is None or not tag.get("content", "").strip():
        return CheckResult(status="fail", message='<meta name="description"> missing or empty')
    content = tag["content"].strip()
    n = len(content)
    if 120 <= n <= 160:
        return CheckResult(status="pass", message=f"{n} chars")
    if n < 120:
        return CheckResult(status="warn", message=f"{n} chars (under 120)")
    return CheckResult(status="warn", message=f"{n} chars (over 160)")
