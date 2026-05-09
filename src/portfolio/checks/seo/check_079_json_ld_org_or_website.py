"""CHECK_079 — JSON-LD includes Organization or WebSite @type."""
from __future__ import annotations

import json

from ..result import CheckResult
from . import _is_web_project, _parse_html, _read_index_html

CHECK_ID = "CHECK_079"
CHECK_NAME = "json-ld-org-or-website"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "At least one JSON-LD block declares @type Organization or WebSite (or @graph that includes them)."


def _types_in(node) -> list[str]:
    """Walk a JSON-LD node tree and collect every @type encountered."""
    out = []
    if isinstance(node, dict):
        t = node.get("@type")
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, list):
            out.extend([x for x in t if isinstance(x, str)])
        graph = node.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                out.extend(_types_in(item))
    elif isinstance(node, list):
        for item in node:
            out.extend(_types_in(item))
    return out


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    html = _read_index_html(repo_path)
    if html is None:
        return CheckResult(status="warn", message="no index.html / index.astro — skipped")
    soup = _parse_html(html)
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    if not scripts:
        return CheckResult(status="fail", message="no JSON-LD blocks")
    all_types: list[str] = []
    for s in scripts:
        try:
            parsed = json.loads(s.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        all_types.extend(_types_in(parsed))
    if "Organization" in all_types or "WebSite" in all_types:
        types_seen = sorted(set(all_types))
        return CheckResult(status="pass",
                           message=f"types: {', '.join(types_seen)}")
    return CheckResult(status="fail",
                       message=f"no Organization or WebSite type (found: {', '.join(set(all_types)) or 'none parseable'})")
