"""CHECK_080 — Analytics tracking script present (info — opt-in convention)."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _read_index_html

CHECK_ID = "CHECK_080"
CHECK_NAME = "has-analytics"
CATEGORY = "seo"
SEVERITY = "info"
DESCRIPTION = "Analytics tracking present (Google Tag, Plausible, Cloudflare Analytics, etc.)."

_ANALYTICS_MARKERS = (
    "googletagmanager.com",  # GA4 / GTM
    "gtag(",                 # GA4 inline
    "plausible.io",          # Plausible
    "static.cloudflareinsights.com",  # CF Web Analytics
    "umami",                 # Umami
)


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")
    found = [m for m in _ANALYTICS_MARKERS if m in html]
    if found:
        return CheckResult(status="pass",
                           message=f"analytics: {', '.join(found)}")
    return CheckResult(status="warn",
                       message="no analytics markers found")
