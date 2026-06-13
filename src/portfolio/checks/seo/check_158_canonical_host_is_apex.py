"""CHECK_158 — every page's <link rel="canonical"> uses the apex host.

Host-consistency triad (v26.G), the markup half of canonicalization.
CHECK_150 verifies the *network* redirect (www/http → apex 308); this
verifies the *markup* agrees. A canonical that points at `www` (or any
non-apex host) splits ranking signals even when the redirect is correct —
the same coverage-break family as donready's "URL unknown to Google."

Apex is the ONLY canonical host fleet-wide (see `docs/CLAUDE.md § Locked
target shapes`; CHECK_150). The apex is the repo's directory name.

Fetches each live sitemap URL, reads its `<link rel="canonical">`, and
fails if any canonical's host isn't the apex. Missing canonicals are
CHECK_072's concern, not this one.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from ..result import CheckResult
from . import _is_web_project
from ._live import (
    LiveFetchError,
    fetch_html,
    get_sitemap_urls,
    parse_canonical,
    resolve_live_url,
)

CHECK_ID = "CHECK_158"
CHECK_NAME = "canonical-host-is-apex"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = 'Every page\'s <link rel="canonical"> uses the apex host (no www).'


def _host(u: str) -> str:
    return (urlparse(u).hostname or "").lower()


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    apex = Path(repo_path).name.lower()
    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    try:
        urls = get_sitemap_urls(origin)
    except LiveFetchError as e:
        return CheckResult(status="warn", message=f"sitemap unreachable ({e})")
    if not urls:
        return CheckResult(status="warn", message=f"sitemap empty at {origin}")

    findings: list[str] = []
    fetched = 0
    for url in urls:
        try:
            html = fetch_html(url)
        except LiveFetchError:
            continue
        fetched += 1
        canonical = parse_canonical(html)
        if canonical is None:
            continue  # missing canonical is CHECK_072's concern
        host = _host(canonical)
        if host != apex:
            findings.append(
                f"{url}: canonical host {host or '∅'!r} ≠ apex {apex!r} "
                f"({canonical})"
            )

    if fetched == 0:
        return CheckResult(
            status="warn", message=f"all {len(urls)} sitemap URL(s) unreachable")
    if not findings:
        return CheckResult(
            status="pass", message=f"canonical host == apex on {fetched} URL(s)")
    return CheckResult(
        status="fail",
        message=(f"{len(findings)} non-apex canonical(s) — "
                 + "; ".join(findings[:3])),
    )
