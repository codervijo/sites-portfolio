"""CHECK_094 — Live BreadcrumbList JSON-LD blocks have the required shape.

Google's BreadcrumbList rich result requires:
  - `itemListElement` is a non-empty list of `ListItem` entries
  - each item has sequential `position` 1, 2, 3, ... N (no gaps, starts at 1)
  - each item has `name` (the breadcrumb label)
  - each item has `item` (the URL)

When any of these are off, Google rejects the breadcrumb entirely and
the page loses the eligibility for the breadcrumb display in the SERP.
"""
from __future__ import annotations

from ..result import CheckResult
from . import _is_web_project
from ._live import (
    LiveFetchError,
    fetch_html,
    get_sitemap_urls,
    iter_jsonld_nodes,
    node_type,
    parse_jsonld_blocks,
    resolve_live_url,
)

CHECK_ID = "CHECK_094"
CHECK_NAME = "live-breadcrumblist-shape"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Every BreadcrumbList has sequential `position` 1..N "
    "and every item has `name` + `item`."
)


def _validate_breadcrumblist(url: str, node: dict) -> list[str]:
    """Return findings for one BreadcrumbList node. Empty list = clean."""
    findings: list[str] = []
    items = node.get("itemListElement")
    if not isinstance(items, list) or not items:
        findings.append(f"{url}: BreadcrumbList itemListElement missing or empty")
        return findings

    positions: list[int | None] = []
    for i, it in enumerate(items, 1):
        if not isinstance(it, dict):
            findings.append(f"{url}: BreadcrumbList item[{i}] is not an object")
            positions.append(None)
            continue

        types = node_type(it)
        if "ListItem" not in types:
            findings.append(
                f"{url}: BreadcrumbList item[{i}] @type={types or 'missing'} "
                "(expected ListItem)"
            )

        pos = it.get("position")
        if not isinstance(pos, int) or isinstance(pos, bool):
            findings.append(
                f"{url}: BreadcrumbList item[{i}] has non-integer position={pos!r}"
            )
            positions.append(None)
        else:
            positions.append(pos)

        name = it.get("name")
        if not isinstance(name, str) or not name.strip():
            findings.append(f"{url}: BreadcrumbList item[{i}] missing/empty `name`")

        item_url = it.get("item")
        if not isinstance(item_url, str) or not item_url.strip():
            findings.append(f"{url}: BreadcrumbList item[{i}] missing/empty `item`")

    # Check sequential 1..N (only when we got valid integer positions).
    valid_positions = [p for p in positions if isinstance(p, int)]
    if valid_positions:
        expected = list(range(1, len(valid_positions) + 1))
        if valid_positions != expected:
            findings.append(
                f"{url}: BreadcrumbList positions {valid_positions} "
                f"are not sequential 1..{len(valid_positions)}"
            )
    return findings


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
    breadcrumbs_seen = 0
    fetched = 0
    for url in urls:
        try:
            html = fetch_html(url)
        except LiveFetchError:
            continue
        fetched += 1
        for block in parse_jsonld_blocks(html):
            if block.parsed is None:
                continue
            for node in iter_jsonld_nodes(block.parsed):
                if isinstance(node, dict) and "BreadcrumbList" in node_type(node):
                    breadcrumbs_seen += 1
                    findings.extend(_validate_breadcrumblist(url, node))

    if fetched == 0:
        return CheckResult(
            status="warn",
            message=f"all {len(urls)} sitemap URL(s) unreachable",
        )

    if not findings:
        if breadcrumbs_seen == 0:
            return CheckResult(
                status="pass",
                message=f"no BreadcrumbList blocks found across {fetched} URL(s)",
            )
        return CheckResult(
            status="pass",
            message=f"{breadcrumbs_seen} BreadcrumbList block(s) across {fetched} URL(s) are well-formed",
        )

    sample = "; ".join(findings[:3])
    return CheckResult(
        status="fail",
        message=f"{len(findings)} BreadcrumbList shape issue(s) — {sample}",
    )
