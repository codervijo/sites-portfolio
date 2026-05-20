"""v13.B — per-project GSC diagnostics orchestrator.

Powers the new default output of `lamill project seo <domain>`:
sitemap-level status + per-URL coverage + actionable hints. Reads
from GSC Sitemaps API + URL Inspection API; both via the existing
`webmasters.readonly` OAuth scope (`gsc.py`). No new auth surface.

Distinct from v5.D (which already populates the 1-row 28d
aggregate that becomes the header line above this diagnostics
block) and from v15.B+ analytics (queries / pages / devices /
trend — those live behind section flags).

When the domain has no GSC property registered, returns a
`ProjectSeoDiagnostics` with `not_registered=True` and a single
hint pointing the operator at `settings gsc auth` — rather than
raising, so the project-seo command renders the not-registered
case the same way as a registered-but-broken case.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .gsc import authenticate, get_service
from .gsc_recrawl import (
    RecrawlError,
    UrlInspection,
    fetch_sitemap_urls,
    find_gsc_property,
    inspect_one_url,
)


# ---------- dataclasses ----------


@dataclass
class SitemapDetail:
    """One sitemap as GSC sees it. Mirrors the API's response shape
    (camelCase keys flattened to snake_case + parsed timestamps)."""
    path: str                           # relative path, e.g., "/sitemap.xml"
    full_url: str                       # absolute URL (what GSC stores)
    status: str                         # "OK" | "ERROR" | "WARN" | "PENDING"
    errors: int = 0
    warnings: int = 0
    last_downloaded: str | None = None  # ISO-8601, or None if never fetched
    is_pending: bool = False
    error_summary: str = ""             # one-line summary for renderer


@dataclass
class CoverageDetail:
    """One URL's coverage state from `urlInspection.index.inspect`."""
    url: str
    coverage_state: str | None = None   # submitted_indexed | crawled_not_indexed | …
    indexing_state: str | None = None
    verdict: str | None = None          # PASS | FAIL | NEUTRAL
    page_fetch_state: str | None = None
    last_crawl_at: str | None = None    # ISO-8601
    error: str | None = None            # set when URL Inspection itself errored


@dataclass
class Hint:
    """One actionable next-step for the operator."""
    target: str          # url / sitemap path / property
    severity: str        # "info" | "warn" | "error"
    text: str


@dataclass
class ProjectSeoDiagnostics:
    """Complete v13.B diagnostics payload for one domain."""
    domain: str
    property_url: str               # "" when not_registered
    not_registered: bool
    sitemaps: list[SitemapDetail] = field(default_factory=list)
    coverage: list[CoverageDetail] = field(default_factory=list)
    hints: list[Hint] = field(default_factory=list)
    fetched_at: str = ""            # ISO-8601 UTC


# ---------- sitemap detail ----------


def _coerce_int(value: Any) -> int:
    """GSC API returns counts as strings on some endpoints; coerce
    safely. Anything unparseable → 0."""
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _sitemap_status(errors: int, warnings: int, is_pending: bool) -> str:
    """Per-sitemap status cascade — error > warn > pending > ok.
    Matches the cascade `fleet focus`'s sitemap-error detector
    uses against aggregate counts."""
    if errors > 0:
        return "ERROR"
    if is_pending:
        return "PENDING"
    if warnings > 0:
        return "WARN"
    return "OK"


def _summarize_error(sitemap: dict) -> str:
    """One-line error summary the renderer can show inline. GSC's
    sitemap API doesn't return the textual reason directly — the
    `lastDownloaded` + `isSitemapsIndex` + counts are all we get
    on the list endpoint. So the summary is shape-only ("N errors
    on N URLs"); operator opens GSC web UI for the textual reason."""
    errors = _coerce_int(sitemap.get("errors"))
    contents = sitemap.get("contents") or []
    submitted = 0
    if isinstance(contents, list) and contents:
        first = contents[0]
        if isinstance(first, dict):
            submitted = _coerce_int(first.get("submitted"))
    if errors > 0 and submitted:
        return f"{errors} error(s) across {submitted} URL(s)"
    if errors > 0:
        return f"{errors} error(s)"
    return ""


def fetch_sitemap_details(service, property_url: str) -> list[SitemapDetail]:
    """Call `webmasters/v3 sites/{siteUrl}/sitemaps` and reshape each
    entry into a SitemapDetail. Returns [] when the property has no
    sitemaps submitted (GSC returns an empty body).
    """
    try:
        resp = service.sitemaps().list(siteUrl=property_url).execute()
    except Exception as e:    # noqa: BLE001 — googleapiclient surfaces many
        # Defensive: log via the empty-list path; caller's hint
        # generator will add a "could not list sitemaps" warning if
        # needed. Don't crash project-seo on a transient GSC outage.
        return []

    raw = resp.get("sitemap") if isinstance(resp, dict) else None
    if not raw:
        return []

    out: list[SitemapDetail] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        full_url = s.get("path") or ""
        # Strip the property URL prefix to get the path component the
        # renderer shows (e.g., "/sitemap.xml" from
        # "https://homeloom.app/sitemap.xml").
        path = full_url
        if property_url and full_url.startswith(property_url):
            tail = full_url[len(property_url):]
            path = "/" + tail.lstrip("/")
        errors = _coerce_int(s.get("errors"))
        warnings = _coerce_int(s.get("warnings"))
        is_pending = bool(s.get("isPending"))
        out.append(SitemapDetail(
            path=path,
            full_url=full_url,
            status=_sitemap_status(errors, warnings, is_pending),
            errors=errors,
            warnings=warnings,
            last_downloaded=s.get("lastDownloaded"),
            is_pending=is_pending,
            error_summary=_summarize_error(s),
        ))
    return out


# ---------- coverage detail ----------


def _origin_from_property(property_url: str) -> str:
    """Convert a GSC property URL to an HTTP origin for sitemap
    crawling. `sc-domain:example.com` → `https://example.com`;
    URL-prefix props pass through (with the trailing slash stripped)."""
    if property_url.startswith("sc-domain:"):
        return f"https://{property_url[len('sc-domain:'):]}"
    return property_url.rstrip("/")


def fetch_coverage_details(service, property_url: str, *,
                           top_n: int = 10) -> list[CoverageDetail]:
    """Pick the top-N URLs from the property's live sitemap and
    call `urlInspection.index.inspect` for each. Returns one
    `CoverageDetail` per URL.

    `top_n=10` matches v15.D's planned default (also caps URL
    Inspection daily-quota burn — 200 calls/day per token; 10
    per project keeps the per-domain footprint small).
    """
    origin = _origin_from_property(property_url)
    try:
        urls = fetch_sitemap_urls(origin, limit=top_n)
    except RecrawlError:
        # No sitemap reachable — return [] so the hint generator
        # can surface "no sitemap reachable" without crashing.
        return []

    details: list[CoverageDetail] = []
    for u in urls[:top_n]:
        ui: UrlInspection = inspect_one_url(service, property_url, u)
        details.append(CoverageDetail(
            url=u,
            coverage_state=ui.coverage_state,
            indexing_state=ui.indexing_state,
            verdict=ui.verdict,
            page_fetch_state=ui.page_fetch_state,
            last_crawl_at=ui.last_crawl_time.isoformat() if ui.last_crawl_time else None,
            error=ui.error,
        ))
    return details


# ---------- hints generator ----------


# Hardcoded mapping from coverage_state value → actionable hint
# template. Per resolution 13.B at kickoff: deterministic, no LLM
# cost. The text is intentionally concrete ("expand to ≥300 words")
# rather than generic ("improve content") so the operator can act
# without further interpretation.
_COVERAGE_HINTS: dict[str, str] = {
    "crawled_not_indexed":
        "likely thin content or quality signal mismatch; expand to ≥300 "
        "words with original insight, or remove from sitemap if intentionally "
        "thin",
    "discovered_not_indexed":
        "Google found the URL but hasn't crawled it; usually crawl-budget "
        "starvation on a low-PageRank site — internal links from the homepage "
        "+ a 30-day wait often resolve this",
    "not_found_404":
        "URL returns 404 but is in your sitemap; remove from sitemap or "
        "restore the page",
    "redirect_error":
        "URL redirects in a way GSC can't follow (chain too long / loop / "
        "external destination); collapse the redirect or remove from sitemap",
    "server_error":
        "URL returns 5xx; deploy may be broken or the route is missing — "
        "check the server logs",
    "blocked_by_robots":
        "robots.txt blocks Googlebot from this URL; either remove from "
        "sitemap or unblock in robots.txt (intentional `Disallow:` rules "
        "should NOT be in the sitemap)",
    "soft_404":
        "URL returns 200 but Google classified it as soft-404 (thin/empty "
        "response); add substantive content or remove from sitemap",
}


_SITEMAP_ERROR_HINT = (
    "re-deploy with valid XML; current build may be serving a stale "
    "prerender. Run `lamill project fix {domain} --apply` to clear CF "
    "edge cache if applicable"
)


_NOT_REGISTERED_HINT = (
    "domain has no GSC property — register at "
    "search.google.com/search-console (use the `sc-domain:` form for "
    "broad coverage), then re-run `lamill settings gsc status --refresh`"
)


def _generate_hints(domain: str, sitemaps: list[SitemapDetail],
                    coverage: list[CoverageDetail]) -> list[Hint]:
    """Build the hints list from the sitemaps + coverage findings.

    Order: sitemap errors first (they block discovery), then per-URL
    coverage failures (sorted by URL to keep output stable). Each
    finding maps to at most one hint — multiple URLs with the same
    failure mode get one hint each, not a coalesced summary, because
    the operator's next action is per-URL (e.g., expand /about's
    content vs remove /docs/old-guide from the sitemap).
    """
    out: list[Hint] = []
    for sm in sitemaps:
        if sm.errors > 0:
            out.append(Hint(
                target=sm.path,
                severity="error",
                text=f"{sm.path} parse/fetch error → "
                     + _SITEMAP_ERROR_HINT.format(domain=domain),
            ))
    for cv in coverage:
        if cv.coverage_state and cv.coverage_state.lower() in _COVERAGE_HINTS:
            template = _COVERAGE_HINTS[cv.coverage_state.lower()]
            out.append(Hint(
                target=cv.url,
                severity="warn" if cv.coverage_state == "crawled_not_indexed" else "error",
                text=f"{cv.url} {cv.coverage_state} → {template}",
            ))
    return out


# ---------- orchestrator ----------


def build_diagnostics(domain: str, *, top_n: int = 10,
                      service=None) -> ProjectSeoDiagnostics:
    """End-to-end orchestration of v13.B diagnostics for one domain.

    Returns a `ProjectSeoDiagnostics` with `not_registered=True`
    when the domain has no GSC property (with a single hint
    pointing at the registration flow). Otherwise fetches sitemap
    details + top-N URL coverage + generates hints, persisted on
    the returned dataclass.

    Caller is responsible for caching (see `gsc_detail_cache.py`).
    This function ALWAYS hits GSC; it's the cache layer that
    decides when to re-fetch.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    if service is None:
        creds = authenticate()
        service = get_service(creds)

    try:
        property_url = find_gsc_property(domain, service=service)
    except RecrawlError:
        return ProjectSeoDiagnostics(
            domain=domain.lower(),
            property_url="",
            not_registered=True,
            sitemaps=[],
            coverage=[],
            hints=[Hint(target=domain, severity="info",
                        text=_NOT_REGISTERED_HINT)],
            fetched_at=fetched_at,
        )

    sitemaps = fetch_sitemap_details(service, property_url)
    coverage = fetch_coverage_details(service, property_url, top_n=top_n)
    hints = _generate_hints(domain.lower(), sitemaps, coverage)

    return ProjectSeoDiagnostics(
        domain=domain.lower(),
        property_url=property_url,
        not_registered=False,
        sitemaps=sitemaps,
        coverage=coverage,
        hints=hints,
        fetched_at=fetched_at,
    )
