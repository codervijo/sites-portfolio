"""CHECK_070 — index has <title> tag of reasonable length (30-60 chars)."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_070"
CHECK_NAME = "has-title-tag"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "<title> tag present and 30-60 characters long."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    title = soup.find("title")
    if title is None or not title.text.strip():
        return CheckResult(status="fail", message="<title> tag missing or empty")
    text = title.text.strip()
    n = len(text)
    if 30 <= n <= 60:
        return CheckResult(status="pass", message=f"{n} chars: {text!r}")
    if n < 30:
        return CheckResult(status="warn",
                           message=f"{n} chars (under 30): {text!r}")
    return CheckResult(status="warn",
                       message=f"{n} chars (over 60): {text!r}")
