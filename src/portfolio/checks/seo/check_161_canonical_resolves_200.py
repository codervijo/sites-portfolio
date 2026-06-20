"""CHECK_161 — every page's <link rel="canonical"> is its own final URL (200, no redirect).

The high-severity half of the canonicalization family. CHECK_158 verifies the
canonical *host* is the apex; this verifies the canonical *URL itself resolves
200* — i.e. it is the final, non-redirecting URL.

The bug this catches (donready.xyz, earnlog.xyz; 2026-06-19): Astro's directory
format serves `/calculator/` and @astrojs/sitemap lists `/calculator/`, but the
page declares `<link rel="canonical" href=".../calculator">` (no trailing slash),
which 308-redirects to `/calculator/`. A canonical pointing at a redirecting URL
is an indexing-blocker — Google won't settle on a canonical, and exactly those
sub-pages came back "URL is unknown to Google" while the (slash-clean) homepage
was indexed. CHECK_158 passes them (host is correct); only the path redirects.

Fetches each live sitemap URL, reads its `<link rel="canonical">`, and fails if
any canonical does NOT resolve 200 (a 3xx redirect, or a 4xx broken target).
Missing canonicals are CHECK_072's concern, not this one.
"""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project
from ._live import (
    LiveFetchError,
    fetch_html,
    fetch_status_no_redirect,
    get_sitemap_urls,
    parse_canonical,
    resolve_live_url,
)

CHECK_ID = "CHECK_161"
CHECK_NAME = "canonical-resolves-200"
CATEGORY = "seo"
SEVERITY = "error"
DESCRIPTION = (
    'Every page\'s <link rel="canonical"> resolves 200 (not a 3xx redirect) — '
    "it must be the page's own final URL, matching the sitemap."
)


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
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
        try:
            status = fetch_status_no_redirect(canonical)
        except LiveFetchError:
            continue  # network flake on the canonical — don't false-fail
        if 300 <= status < 400:
            findings.append(
                f"{url}: canonical {canonical} → HTTP {status} "
                f"(redirects; canonical must be the final 200 URL)"
            )
        elif status >= 400:
            findings.append(
                f"{url}: canonical {canonical} → HTTP {status} (broken target)"
            )

    if fetched == 0:
        return CheckResult(
            status="warn", message=f"all {len(urls)} sitemap URL(s) unreachable")
    if not findings:
        return CheckResult(
            status="pass",
            message=f"canonical resolves 200 on {fetched} URL(s)")
    return CheckResult(
        status="fail",
        message=(f"{len(findings)} canonical(s) don't resolve 200 — "
                 + "; ".join(findings[:3])),
    )
