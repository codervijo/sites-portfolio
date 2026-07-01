"""CHECK_076 — Open Graph tags present (og:title, og:description, og:url, og:type, og:image)."""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_head_html

CHECK_ID = "CHECK_076"
CHECK_NAME = "has-open-graph"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "Open Graph meta tags present: og:title, og:description, og:url, og:type, og:image."


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_head_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no head source (index.html or in-code) — skipped")
    soup = _parse_html(html)
    needed = ["og:title", "og:description", "og:url", "og:type", "og:image"]
    found = []
    missing = []
    for prop in needed:
        tag = soup.find("meta", attrs={"property": prop})
        if tag is not None and tag.get("content", "").strip():
            found.append(prop)
        else:
            missing.append(prop)
    if not missing:
        return CheckResult(status="pass", message="all 5 OG tags present")
    if len(found) == 0:
        return CheckResult(status="fail", message="no OG tags present")
    return CheckResult(status="warn",
                       message=f"{len(found)}/5 OG tags; missing: {', '.join(missing)}")
