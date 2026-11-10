"""CHECK_164 — the live site loads GA4 with the ID recorded in
`lamill.toml [analytics] ga4_id` (v49.D).

Fetches the live homepage; passes when the ID is in the HTML or in one of
its same-origin JS bundles (client-side loaders such as homeloom's /
mdburst's `initAnalytics()` only show the ID in a bundle; Astro island
`component-url`s count as bundles). Follows static
and dynamic imports between bundles up to `MAX_SCRIPTS` fetches.

Catches "committed but not deployed" and ID mismatches (live loads a
different `G-`). Report-only — the deploy is `lamill fleet ga`'s job
(v49.E), which calls `live_state()` and shows ↷ "deploying" when the
fresh tag isn't live yet. Network failures → `warn`, never `fail`.
"""
from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urljoin, urlparse

from ..result import CheckResult
from ._live import LiveFetchError, fetch_html, resolve_live_url
from .check_162_ga4_id_recorded import _GA_ID, _not_applicable, recorded_id

CHECK_ID = "CHECK_164"
CHECK_NAME = "ga4-live-tag"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "Live homepage (HTML or its JS bundles) loads gtag with the lamill.toml GA4 ID (v49.D)."

MAX_SCRIPTS = 25

_SCRIPT_SRC = re.compile(r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", re.I)
_MODULE_PRELOAD = re.compile(r"""<link\b[^>]*\brel\s*=\s*["']modulepreload["'][^>]*\bhref\s*=\s*["']([^"']+)["']""", re.I)
_ISLAND_URL = re.compile(r"""\b(?:component|renderer|before-hydration)-url\s*=\s*["']([^"']+)["']""", re.I)
_JS_IMPORT = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(\s*|\bimport\s*)["']([^"']+\.m?js)["']""")


def _real_ids(text: str) -> set[str]:
    return {m for m in _GA_ID.findall(text) if set(m[2:]) != {"X"}}


def _same_origin(url: str, origin: str) -> bool:
    return urlparse(url).netloc == urlparse(origin).netloc


def live_state(base: Path, *, client=None) -> tuple[str, str]:
    """("live" | "mismatch" | "missing" | "unreachable" | "n/a", detail).

    `live` = the recorded ID is served; `mismatch` = other `G-` IDs only;
    `missing` = no GA4 ID anywhere on the homepage or its bundles."""
    ga = recorded_id(base)
    if not ga:
        return "n/a", "no GA4 ID recorded — CHECK_162 first"
    origin = resolve_live_url(str(base))
    if not origin:
        return "unreachable", "no live URL configured"
    home = origin + "/"
    try:
        html = fetch_html(home, client=client)
    except LiveFetchError as e:
        return "unreachable", f"{home}: {e}"

    seen_ids = _real_ids(html)
    if ga in seen_ids:
        return "live", f"{ga} in homepage HTML"

    queue = [urljoin(home, s) for s in _SCRIPT_SRC.findall(html) + _MODULE_PRELOAD.findall(html) + _ISLAND_URL.findall(html)]
    visited: set[str] = set()
    while queue and len(visited) < MAX_SCRIPTS:
        url = queue.pop(0).split("#")[0]
        if url in visited or not _same_origin(url, origin):
            continue
        visited.add(url)
        try:
            js = fetch_html(url, client=client)
        except LiveFetchError:
            continue
        ids = _real_ids(js)
        if ga in ids:
            return "live", f"{ga} in {urlparse(url).path}"
        seen_ids |= ids
        queue.extend(urljoin(url, s) for s in _JS_IMPORT.findall(js))

    if seen_ids:
        return "mismatch", f"live loads {', '.join(sorted(seen_ids))}, expected {ga}"
    return "missing", f"{ga} not on {home} ({len(visited)} bundle(s) scanned)"


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"{reason} — n/a")
    state, detail = live_state(base)
    if state in ("live", "n/a"):
        return CheckResult(status="pass", message=detail)
    if state == "missing":
        return CheckResult(status="warn", message=f"{detail} — not deployed yet? (CHECK_163 for source)")
    if state == "mismatch":
        return CheckResult(status="warn", message=detail)
    return CheckResult(status="warn", message=f"live site unreachable ({detail}) — skipped")
