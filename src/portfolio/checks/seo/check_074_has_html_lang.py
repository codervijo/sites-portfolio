"""CHECK_074 — <html lang="..."> attribute set."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_074"
CHECK_NAME = "has-html-lang"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "<html lang=\"...\"> attribute is set (improves accessibility + SEO)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    html_tag = soup.find("html")
    if html_tag is None:
        # Astro can omit <html> in fragment templates; check the raw text.
        if "lang=" in html:
            return CheckResult(status="pass", message="lang attribute present (raw)")
        return CheckResult(status="warn", message="no <html> tag found in template")
    lang = html_tag.get("lang", "")
    if lang.strip():
        return CheckResult(status="pass", message=f'lang="{lang}"')
    return CheckResult(status="fail", message="<html> tag has no lang attribute")
