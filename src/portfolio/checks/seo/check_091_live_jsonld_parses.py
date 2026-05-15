"""CHECK_091 — Every JSON-LD block on every sitemap URL parses as JSON.

Catches the silent regression class where a templating bug or escaping
mismatch produces a `<script type="application/ld+json">` whose body
isn't valid JSON. Google ignores invalid blocks entirely — the page
loses all of its structured-data signal without any visible error.

A page with zero JSON-LD blocks is not a failure for this check
(CHECK_078 already covers "has-json-ld"); CHECK_091 only fires when a
block exists but doesn't parse.
"""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project
from ._live import (
    LiveFetchError,
    fetch_html,
    get_sitemap_urls,
    parse_jsonld_blocks,
    resolve_live_url,
)

CHECK_ID = "CHECK_091"
CHECK_NAME = "live-jsonld-parses"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = "Every JSON-LD block on every live sitemap URL parses as valid JSON."


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

    # Per-URL findings list: (url, block_index, error_msg). We surface
    # the first few in the message; full list lives in the run's debug
    # output if a renderer wants more.
    failures: list[tuple[str, int, str]] = []
    fetched = 0
    total_blocks = 0
    for url in urls:
        try:
            html = fetch_html(url)
        except LiveFetchError:
            # Transport error on one URL — let the user see this happen
            # via CHECK_090's reporting; don't double-report here.
            continue
        fetched += 1
        blocks = parse_jsonld_blocks(html)
        total_blocks += len(blocks)
        for i, block in enumerate(blocks, 1):
            if block.error is not None:
                failures.append((url, i, block.error))

    if fetched == 0:
        return CheckResult(
            status="warn",
            message=f"all {len(urls)} sitemap URL(s) unreachable",
        )

    if not failures:
        return CheckResult(
            status="pass",
            message=f"{total_blocks} JSON-LD block(s) across {fetched} URL(s) parse cleanly",
        )

    sample = "; ".join(
        f"{url}#{i}: {err[:50]}" for url, i, err in failures[:3]
    )
    return CheckResult(
        status="fail",
        message=f"{len(failures)} of {total_blocks} JSON-LD block(s) failed to parse — {sample}",
    )
