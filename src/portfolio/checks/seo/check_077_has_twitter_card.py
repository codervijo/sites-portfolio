"""CHECK_077 — Twitter Card meta tags present."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_077"
CHECK_NAME = "has-twitter-card"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "Twitter Card tags present (at minimum: twitter:card)."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    card = soup.find("meta", attrs={"name": "twitter:card"})
    if card is None or not card.get("content", "").strip():
        return CheckResult(status="fail", message='<meta name="twitter:card"> missing')
    # Title/description optional but informational.
    extras = []
    for prop in ("twitter:title", "twitter:description", "twitter:image"):
        if soup.find("meta", attrs={"name": prop}) is not None:
            extras.append(prop.split(":")[-1])
    extra_str = f" (+{', '.join(extras)})" if extras else ""
    return CheckResult(status="pass",
                       message=f'twitter:card={card["content"]!r}{extra_str}')
