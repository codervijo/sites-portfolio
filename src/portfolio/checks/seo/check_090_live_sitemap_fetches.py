"""CHECK_090 — Every URL in the sitemap fetches HTTP 200 as Googlebot.

Foundation for the runtime SEO checks (CHECK_091+) — those need
sitemap URLs to actually serve content. A 404 here means the sitemap
is shipping URLs that no longer exist, which Google will treat as a
soft-quality signal.

Network errors are downgraded to `warn` (skipped) so flaky CI doesn't
fail-grade an SEO check on a transient outage. Real HTTP 4xx responses
ARE failures — that's a site bug, not infrastructure.
"""
from __future__ import annotations

from ..result import CheckResult
from ._live import (
    LiveFetchError,
    fetch_response_status,
    get_sitemap_urls,
    resolve_live_url,
)
from . import _is_web_project

CHECK_ID = "CHECK_090"
CHECK_NAME = "live-sitemap-fetches"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "Every URL in the live sitemap returns HTTP 200 to a Googlebot UA."


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

    bad: list[tuple[str, int | str]] = []
    fetched = 0
    for url in urls:
        try:
            status = fetch_response_status(url)
        except LiveFetchError as e:
            # Network-level failure on this URL → don't fail the whole
            # check on flaky CI. Record it as a warn-finding instead.
            bad.append((url, str(e)))
            continue
        fetched += 1
        if not (200 <= status < 300):
            bad.append((url, status))

    if not bad:
        return CheckResult(
            status="pass",
            message=f"{fetched} sitemap URL(s) returned 200 as Googlebot",
        )

    # If every URL failed at the network layer, treat as warn (likely
    # flaky environment) rather than as a site bug.
    if fetched == 0:
        first = bad[0]
        return CheckResult(
            status="warn",
            message=f"all {len(bad)} sitemap URL(s) unreachable "
                    f"(first: {first[0]} → {first[1]})",
        )

    sample = ", ".join(f"{u} → {s}" for u, s in bad[:3])
    return CheckResult(
        status="fail",
        message=f"{len(bad)} of {len(urls)} sitemap URL(s) not 200: {sample}",
    )
