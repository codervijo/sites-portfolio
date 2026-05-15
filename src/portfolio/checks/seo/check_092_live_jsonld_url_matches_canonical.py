"""CHECK_092 — JSON-LD `url` field matches the page's `<link rel="canonical">`.

This is the washcalc.app regression. Every prerendered calculator page
shipped a `WebApplication` JSON-LD block whose `url` field pointed at
the homepage, despite each page having a correct per-page canonical
link. Google may treat the JSON-LD `url` as the canonical signal — at
minimum the conflicting signals harm crawl/indexing.

What this check inspects: on each live sitemap URL, every JSON-LD
node whose `@type` is in a "page-level" allow-list (WebApplication /
SoftwareApplication / WebPage / Article / NewsArticle / BlogPosting /
WebSite) — if such a node has a `url` field, that URL must equal the
page's `<link rel="canonical">`.

What this check does NOT inspect: `item` URLs inside BreadcrumbList /
ListItem entries (those are navigation links, not page identity), or
`url` fields on Question / Answer / mainEntity items, or Open Graph
`og:url` (separate concern).

A page with no canonical and no page-level JSON-LD url is fine. A
page with a canonical but no page-level JSON-LD url is also fine.
The check only fires when both are present AND don't match.
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
    parse_canonical,
    parse_jsonld_blocks,
    resolve_live_url,
)

CHECK_ID = "CHECK_092"
CHECK_NAME = "live-jsonld-url-matches-canonical"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Every JSON-LD `url` field on a page-level @type "
    "(WebApplication / SoftwareApplication / WebPage / Article / WebSite) "
    "matches the page's <link rel=\"canonical\">."
)

# @type values whose `url` field is expected to identify the page itself.
# Other @types (BreadcrumbList, ListItem, Question, etc.) have `url` /
# `item` fields with different semantics — excluded.
PAGE_LEVEL_TYPES = frozenset({
    "WebApplication",
    "SoftwareApplication",
    "WebPage",
    "AboutPage", "ContactPage", "CollectionPage", "ItemPage", "ProfilePage",
    "Article",
    "BlogPosting",
    "NewsArticle",
    "TechArticle",
    "WebSite",
})


def _normalize_url(u: str) -> str:
    """Equality-friendly form: lowercase scheme + host, preserve path.
    Trailing slash on root `/` is kept; trailing slash on deeper paths
    is stripped to avoid trivial mismatches."""
    s = (u or "").strip()
    if not s:
        return ""
    # Cheap parse — avoid urlparse since we only need scheme + host norm.
    if "://" in s:
        scheme, rest = s.split("://", 1)
        scheme = scheme.lower()
        host, sep, tail = rest.partition("/")
        host = host.lower()
        path = sep + tail if sep else ""
        # Strip trailing slash on non-root paths.
        if len(path) > 1 and path.endswith("/"):
            path = path[:-1]
        return f"{scheme}://{host}{path}"
    return s


def _is_page_level_node(node: dict) -> bool:
    return any(t in PAGE_LEVEL_TYPES for t in node_type(node))


def _check_one_url(url: str) -> list[str]:
    """Return a list of findings (mismatches) for one page. Empty list
    means the page passes."""
    try:
        html = fetch_html(url)
    except LiveFetchError:
        # Per-URL transport error — silent here (CHECK_090 reports it).
        return []

    canonical = parse_canonical(html)
    if canonical is None:
        return []   # no canonical to compare against — separate issue
    canonical_norm = _normalize_url(canonical)

    mismatches: list[str] = []
    for block in parse_jsonld_blocks(html):
        if block.parsed is None:
            continue   # CHECK_091 reports unparseable blocks
        for node in iter_jsonld_nodes(block.parsed):
            if not isinstance(node, dict):
                continue
            if not _is_page_level_node(node):
                continue
            node_url = node.get("url")
            if not isinstance(node_url, str):
                continue
            if _normalize_url(node_url) != canonical_norm:
                types_str = "/".join(node_type(node))
                mismatches.append(
                    f"{url}: {types_str} url={node_url!r} ≠ canonical={canonical!r}"
                )
    return mismatches


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

    all_findings: list[str] = []
    fetched = 0
    for url in urls:
        try:
            fetch_html(url)
        except LiveFetchError:
            continue
        fetched += 1
        all_findings.extend(_check_one_url(url))

    if fetched == 0:
        return CheckResult(
            status="warn",
            message=f"all {len(urls)} sitemap URL(s) unreachable",
        )

    if not all_findings:
        return CheckResult(
            status="pass",
            message=f"page-level JSON-LD `url` matches canonical on {fetched} URL(s)",
        )

    sample = "; ".join(all_findings[:3])
    return CheckResult(
        status="fail",
        message=f"{len(all_findings)} mismatch(es) — {sample}",
    )
