"""CHECK_147 — Top-N submitted URLs are indexed by Google (v16.C).

Reads GSC's URL Inspection API for the top-N pages (sorted by
impressions — sitemap fallback for zero-impression sites) and fires
`fail` when any inspected URL is in a non-indexed `coverageState`.

Pass / warn / fail:
  - pass: every inspected URL has coverageState ∈ {"Submitted and
          indexed", "Indexed, not submitted in sitemap"} — Google's
          two "this URL is indexed" verdicts.
  - fail: ≥1 URL has any other coverageState (crawled-not-indexed,
          discovered-not-indexed, not found, redirect-error, etc.).
          Message lists the failing URLs + their states.
  - warn: GSC credentials not configured / no GSC property matches
          domain / cache stale + live fetch failed / not a web
          project / no live URL.

Reads from cache (`data/gsc/<domain>/<UTC-today>.json` via
`gsc_detail_cache`) when fresh; refetches via GSC URL Inspection
API otherwise. URL Inspection has a 2000/day quota; capped at
top-10 per site (configurable via `top_n` arg if invoked
directly) to keep daily fleet sweeps under ~300 calls.

URL set per v16.A: top-N pages ranked by GSC impressions desc,
alphabetical fallback for zero-imp URLs. Works for new sites
(zero impressions → alphabetical from sitemap) and for established
sites (highest-traffic URLs are inspected first — catches the
most painful "high-imp but non-indexed" cases).

Mobile-usability data is rendered but doesn't fail the check
(v16.A decision — keep CHECK_NNN surgical, one assertion per check).
"""
from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from ..result import CheckResult
from ..seo._live import LiveFetchError, get_sitemap_urls, resolve_live_url
from ..seo import _is_web_project
from ... import gsc_detail_cache

CHECK_ID = "CHECK_147"
CHECK_NAME = "url-indexed"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Top-N submitted URLs are indexed by Google (URL Inspection API; v16.C)."
)

DEFAULT_TOP_N = 10

# GSC `coverageState` strings that count as "indexed". Per the
# v13.B bug fix logged in docs/bugs.md (2026-05-20) — the API
# returns human text with spaces, not enum tokens.
_INDEXED_STATES = frozenset({
    "Submitted and indexed",
    "Indexed, not submitted in sitemap",
})


def run(repo_path: str, *, top_n: int = DEFAULT_TOP_N) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")

    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    domain = Path(repo_path).resolve().name

    # Try cache first.
    inspections = _load_cached_inspections(domain)
    source = "cache"

    if inspections is None:
        # Cache miss / stale — fetch live.
        try:
            inspections = _fetch_inspections(domain, origin, top_n=top_n)
        except _GscUnavailable as e:
            return CheckResult(
                status="warn",
                message=f"GSC URL Inspection unavailable ({e}) — skipped",
            )
        source = "live"
        _save_inspections(domain, inspections)

    if not inspections:
        return CheckResult(
            status="warn",
            message=(
                f"no URLs inspected for {domain} — empty sitemap or "
                f"no GSC property match. Check `lamill project seo "
                f"{domain}` for diagnostics."
            ),
        )

    # Evaluate. Inspections that errored at the GSC layer count as warns,
    # not fails (transient API issues shouldn't fail-grade the site).
    errored = [i for i in inspections if i.get("status") == "error"]
    if errored and len(errored) == len(inspections):
        return CheckResult(
            status="warn",
            message=f"all {len(inspections)} URL inspections errored — GSC layer issue",
        )

    non_indexed = []
    indexed_count = 0
    for insp in inspections:
        if insp.get("status") == "error":
            continue
        state = insp.get("coverage_state") or ""
        if state in _INDEXED_STATES:
            indexed_count += 1
        else:
            non_indexed.append((insp.get("url", ""), state or "unknown"))

    total_checked = indexed_count + len(non_indexed)

    if not non_indexed:
        return CheckResult(
            status="pass",
            message=(
                f"{indexed_count}/{total_checked} top URLs indexed "
                f"(source: {source})"
            ),
        )

    # Build a compact summary — first 3 failing URLs as a preview.
    preview = "; ".join(
        f"{_short_url(url)} ({state})"
        for url, state in non_indexed[:3]
    )
    if len(non_indexed) > 3:
        preview += f"; +{len(non_indexed) - 3} more"

    return CheckResult(
        status="fail",
        message=(
            f"{indexed_count}/{total_checked} top URLs indexed · "
            f"{len(non_indexed)} non-indexed: {preview}. Run `lamill "
            f"project seo {domain}` for the full per-URL breakdown."
        ),
    )


# ---------- internals ----------


class _GscUnavailable(RuntimeError):
    """GSC layer (auth, property lookup, API call) unavailable.

    Surfaced as `warn` to the operator — `project check` should not
    fail-grade a site because GSC credentials aren't set up.
    """


def _load_cached_inspections(domain: str) -> list[dict] | None:
    """Return the cached `v16c_inspections` list when a fresh
    snapshot exists; None otherwise."""
    snap_path = gsc_detail_cache.latest_snapshot(domain)
    if snap_path is None or gsc_detail_cache.is_stale(snap_path):
        return None
    try:
        snap = gsc_detail_cache.load_snapshot(snap_path)
    except (OSError, ValueError):
        return None
    cached = snap.get("v16c_inspections")
    if not isinstance(cached, list):
        return None
    return cached


def _save_inspections(domain: str, inspections: list[dict]) -> None:
    """Merge `v16c_inspections` into today's snapshot. Other v13.B /
    v16 sections in the same file are preserved."""
    snap_path = gsc_detail_cache.latest_snapshot(domain)
    existing: dict = {}
    if snap_path is not None:
        try:
            existing = gsc_detail_cache.load_snapshot(snap_path)
        except (OSError, ValueError):
            existing = {}
    # Strip the fetched_at + domain metadata so save_snapshot can
    # re-populate them with current values.
    existing.pop("fetched_at", None)
    existing.pop("domain", None)
    existing["v16c_inspections"] = inspections
    gsc_detail_cache.save_snapshot(domain, existing)


def _fetch_inspections(domain: str, origin: str, *, top_n: int) -> list[dict]:
    """Live fetch — authenticate, resolve GSC property, get top-N
    URLs, inspect each. Raises `_GscUnavailable` for any layer error
    the operator can't easily fix from this command (auth missing,
    property mismatch, network)."""
    try:
        from ...gsc import (
            DEFAULT_LAG_DAYS,
            MissingCredentialsError,
            authenticate,
            get_service,
            query_with_dims,
        )
        from ...gsc_recrawl import find_gsc_property, inspect_one_url
    except ImportError as e:
        raise _GscUnavailable(f"GSC modules unavailable: {e}") from e

    try:
        creds = authenticate()
    except (MissingCredentialsError, RefreshError_or_OSError) as e:
        raise _GscUnavailable(f"GSC auth: {type(e).__name__}: {e}") from e
    except Exception as e:  # noqa: BLE001 — auth raises many shapes
        raise _GscUnavailable(f"GSC auth: {type(e).__name__}: {e}") from e

    try:
        service = get_service(creds)
        property_url = find_gsc_property(domain, service=service)
    except Exception as e:  # noqa: BLE001
        raise _GscUnavailable(
            f"GSC property lookup for {domain}: {type(e).__name__}: {e}"
        ) from e

    # Top-N URLs ranked by impressions. Falls back to sitemap when
    # GSC returns < top_n.
    try:
        rows = query_with_dims(
            service, property_url,
            dimensions=["page"], row_limit=max(top_n * 2, 50),
        )
    except Exception as e:  # noqa: BLE001
        rows = []
    pages_by_imp = [
        r["keys"][0] for r in rows
        if r.get("keys") and r["keys"][0].startswith(("http://", "https://"))
    ]

    if len(pages_by_imp) < top_n:
        # Augment from sitemap alphabetically.
        try:
            sitemap_urls = list(get_sitemap_urls(origin))[:50]
        except LiveFetchError:
            sitemap_urls = []
        seen = set(pages_by_imp)
        for url in sorted(sitemap_urls):
            if url not in seen and len(pages_by_imp) < top_n:
                pages_by_imp.append(url)
                seen.add(url)

    top_pages = pages_by_imp[:top_n]
    if not top_pages:
        return []

    inspections: list[dict] = []
    for url in top_pages:
        insp = inspect_one_url(service, property_url, url)
        d = asdict(insp)
        # last_crawl_time is a datetime — JSON-serialize as ISO.
        lct = d.get("last_crawl_time")
        if lct is not None:
            d["last_crawl_time"] = lct.isoformat() if hasattr(lct, "isoformat") else str(lct)
        inspections.append(d)
    return inspections


def _short_url(url: str, max_len: int = 50) -> str:
    if len(url) <= max_len:
        return url
    return url[: max_len - 1] + "…"


# RefreshError import is conditional — google.auth.exceptions.RefreshError
# exists in modern versions but we keep the import lazy to avoid hard-fail
# when google-auth isn't installed in some test environments.
try:
    from google.auth.exceptions import RefreshError as RefreshError_or_OSError
except ImportError:
    RefreshError_or_OSError = OSError
