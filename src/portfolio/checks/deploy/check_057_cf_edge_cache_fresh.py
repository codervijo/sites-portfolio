"""CHECK_057 — Cloudflare edge isn't serving stale critical files.

The donready-style failure: a previously-deployed `/sitemap.xml` lingers
at the Cloudflare edge after a build that no longer produces that file,
and Google Search Console reports "Sitemap could not be read" while
every other dashboard signal is green.

This check probes a fixed list of paths and flags any that:
  - return HTTP 200 from the live origin,
  - AND have no corresponding file in `dist/` (i.e., the current build
    no longer produces them — the edge is serving leftovers).

The cf-cache-status header is captured for reporting (so the failure
message can say "HIT" vs "MISS") but isn't required for the verdict —
"served but not in dist" is stale regardless of why.

Tier-1 fix: re-probe to identify stale paths, then call CF's purge_cache
API to remove them. Re-probes once more after the purge to verify.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from ..result import CheckResult
from ...fix_helpers import FixerSpec, FixResult

CHECK_ID = "CHECK_057"
CHECK_NAME = "cf-edge-cache-fresh"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "Cloudflare edge isn't serving stale critical files (sitemap*, "
    "robots.txt) that don't exist in the current dist/."
)

# Paths probed against the live origin. Order is reported back unchanged.
# `critical=True` paths drive the check's fail/pass verdict; non-critical
# paths only warn. Add new paths sparingly — every entry is one curl per
# site on every check run.
_PROBE_PATHS: list[tuple[str, bool]] = [
    ("/robots.txt", True),
    ("/sitemap.xml", True),
    ("/sitemap-index.xml", True),
    ("/sitemap-0.xml", True),
    ("/", False),
]

HTTP_TIMEOUT = 8.0


def _dist_path_for(repo_path: Path, url_path: str) -> Path:
    """Map a URL path to the file `dist/` should contain. Trailing-slash
    paths and `/` resolve to `index.html` in their directory — matches
    Cloudflare Pages' default not_found_handling for static sites."""
    rel = url_path.lstrip("/")
    if not rel or rel.endswith("/"):
        rel += "index.html"
    return repo_path / "dist" / rel


def _probe_one(client: httpx.Client, domain: str, path: str) -> dict[str, Any]:
    """Single HEAD-equivalent probe. Uses GET (HEAD isn't always cached
    by CF the same way as GET, and we want the cache-status the user
    would see from a real client).

    Must NOT follow redirects — otherwise a path that's correctly
    301-redirecting to a real file (e.g. /sitemap.xml → /sitemap-index.xml)
    silently records the destination's 200+HIT as if the source path
    were stale-cached. We want the literal response for *this* path.
    """
    url = f"https://{domain}{path}"
    try:
        resp = client.get(url)
    except httpx.HTTPError as e:
        return {"path": path, "url": url, "status": None,
                "cf_cache_status": None, "content_type": None,
                "etag": None, "age": None, "cache_control": "",
                "error": f"{type(e).__name__}: {e}"}
    raw_ct = resp.headers.get("content-type") or ""
    age_raw = (resp.headers.get("age") or "").strip()
    return {
        "path": path,
        "url": url,
        "status": resp.status_code,
        "cf_cache_status": resp.headers.get("cf-cache-status"),
        "content_type": raw_ct.split(";")[0].strip().lower(),
        "etag": resp.headers.get("etag"),
        # `age` > 0 means the edge served a copy that's been sitting in cache
        # for that many seconds (vs fetching fresh from origin this request).
        "age": int(age_raw) if age_raw.isdigit() else None,
        "cache_control": (resp.headers.get("cache-control") or "").lower(),
        "error": None,
    }


def _run_probes(repo_path: Path, domain: str, *,
                client: httpx.Client | None = None) -> list[dict[str, Any]]:
    """Probe every `_PROBE_PATHS` entry against the live origin and
    decorate each row with `in_dist` (does dist/ have the corresponding
    file?) and `is_critical` (drives the verdict).

    Network errors don't crash — they're recorded per-row so the rest
    of the probe completes.
    """
    own_client = client is None
    if client is None:
        # follow_redirects=False is load-bearing — see _probe_one.
        client = httpx.Client(
            timeout=HTTP_TIMEOUT, follow_redirects=False,
            headers={"User-Agent": "portfolio-cli/cf-edge-check"},
        )
    try:
        rows = []
        for path, is_critical in _PROBE_PATHS:
            row = _probe_one(client, domain, path)
            row["is_critical"] = is_critical
            row["in_dist"] = _dist_path_for(repo_path, path).is_file()
            rows.append(row)
    finally:
        if own_client:
            client.close()
    return rows


# Non-HTML asset suffixes — a 200 + text/html response on these paths
# is the signature of CF's not_found_handling = single-page-application
# config synthesizing a fallback response (see _is_spa_fallback).
_NON_HTML_ASSET_SUFFIXES: tuple[str, ...] = (".xml", ".txt", ".json")


def _is_spa_fallback(row: dict[str, Any]) -> bool:
    """Return True when a non-HTML-asset path is being served as
    text/html — the signature of CF's `not_found_handling = single-
    page-application` config returning the SPA's index.html for any
    unknown path.

    These responses are NOT real files at the edge and NOT origin
    orphans either: every cache miss re-fires the fallback and returns
    200+text/html again. Purging is a no-op (verified on kwizicle.com
    2026-05-27 — endless fix/refresh loop pre-fix). Excluding them
    here prevents the false-fail on every Vite/Astro SPA in the fleet.

    A missing content-type (older test stubs, network errors) does
    NOT trigger the exclusion — the row falls through to the existing
    in-dist / stale verdict path."""
    path = row.get("path") or ""
    if not any(path.endswith(s) for s in _NON_HTML_ASSET_SUFFIXES):
        return False
    ct = row.get("content_type") or ""
    return ct.startswith("text/html")


# cf-cache-status values that mean "served from the CF zone/CDN cache" — these
# are evictable by the purge_cache API.
_ZONE_CACHED_STATUSES = ("HIT", "REVALIDATED", "EXPIRED", "STALE", "UPDATING")


def _is_edge_cached(row: dict[str, Any]) -> bool:
    """True when the edge served a CACHED copy (vs fetching fresh from origin
    this request). A 200 that's `DYNAMIC`/`MISS` with no `age` reflects origin's
    current truth — it can't be stale-cached, so it's not a CHECK_057 concern
    (this is what kept airsucks's fresh `/robots.txt` + `/sitemap.xml`, served
    `max-age=0, DYNAMIC`, from being false-flagged)."""
    if (row.get("cf_cache_status") or "").upper() in _ZONE_CACHED_STATUSES:
        return True
    return (row.get("age") or 0) > 0


def _is_zone_purgeable(row: dict[str, Any]) -> bool:
    """True when the stale copy lives in the CF zone/CDN cache (purge_cache can
    evict it). A stale 200 served `DYNAMIC` but with a large `age` is the CF
    Pages asset cache — pinned by the asset's `s-maxage`, NOT evictable by the
    zone purge API (confirmed 2026-06-20: purge_files + purge_everything both
    no-op'd on earnlog /sitemap.xml). Those expire on their own."""
    return (row.get("cf_cache_status") or "").upper() in _ZONE_CACHED_STATUSES


def _stale_paths(rows: list[dict[str, Any]], *, critical_only: bool = False
                 ) -> list[dict[str, Any]]:
    """Filter probe rows for stale-cached entries: 200 served + not in dist +
    not a SPA-fallback + actually served from cache (`_is_edge_cached`).
    `critical_only=True` limits to critical paths — used by the fail verdict."""
    out = []
    for r in rows:
        if r.get("status") != 200:
            continue
        if r.get("in_dist"):
            continue
        if _is_spa_fallback(r):
            continue
        if not _is_edge_cached(r):
            continue
        if critical_only and not r.get("is_critical"):
            continue
        out.append(r)
    return out


def _is_cf_pages_project(repo_path: Path) -> bool:
    return (repo_path / "wrangler.jsonc").is_file() or \
           (repo_path / "wrangler.toml").is_file()


def _domain_from_repo_path(repo_path: Path) -> str:
    """`sites/<domain>/` convention — last path segment is the live host."""
    return repo_path.name


def _format_stale_summary(stale: list[dict[str, Any]]) -> str:
    """Compact one-line summary of stale paths for CheckResult messages."""
    parts = []
    for r in stale:
        cache = r.get("cf_cache_status") or "?"
        parts.append(f"{r['path']} (cache={cache})")
    return ", ".join(parts)


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    if not _is_cf_pages_project(base):
        return CheckResult(status="warn",
                           message="not a Cloudflare Pages project — skipped")
    if not (base / "dist").is_dir():
        return CheckResult(status="warn",
                           message="no dist/ — run build first")

    domain = _domain_from_repo_path(base)
    rows = _run_probes(base, domain)

    # If every probe errored, the origin's likely unreachable — that's a
    # different problem (live-check territory); don't fail the cache check.
    if all(r.get("error") is not None for r in rows):
        first = rows[0]
        return CheckResult(
            status="warn",
            message=f"origin unreachable, all probes errored "
                    f"(first: {first['path']} → {first['error']})",
        )

    stale_critical = _stale_paths(rows, critical_only=True)
    if stale_critical:
        purgeable = [r for r in stale_critical if _is_zone_purgeable(r)]
        if purgeable:
            # Zone/CDN-cached → the purge API can evict it. Actionable fail.
            return CheckResult(
                status="fail",
                message=f"stale at edge: {_format_stale_summary(stale_critical)} "
                        f"— run 'portfolio project fix <domain> --apply' to purge",
            )
        # Only CF Pages-pinned (DYNAMIC + age): the zone purge API can't evict
        # these (see _is_zone_purgeable). Warn, not fail — they expire as the
        # asset's s-maxage runs out. Prevent recurrence with a short
        # Cache-Control for these files in public/_headers.
        return CheckResult(
            status="warn",
            message=f"stale in CF Pages cache (not zone-purgeable): "
                    f"{_format_stale_summary(stale_critical)} — expires as the "
                    f"asset's s-maxage runs out; for SEO files add a short "
                    f"Cache-Control via public/_headers so changes don't pin.",
        )

    stale_any = _stale_paths(rows)
    if stale_any:
        return CheckResult(
            status="warn",
            message=f"stale at edge (non-critical): "
                    f"{_format_stale_summary(stale_any)}",
        )

    return CheckResult(status="pass",
                       message=f"{len(rows)} probed paths reconcile with dist/")


# ---------- Tier-1 fix: purge stale paths via CF API ----------


def _apply_purge(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    """Identify stale paths via the same probe `run` uses, then call
    Cloudflare's `purge_cache` API for those URLs. Re-probes once after
    the purge to verify cache-status actually flipped off HIT.

    Returns:
      - nothing-to-do: no stale paths to purge
      - manual:        CF API token not configured
      - would-fix:     dry-run mode
      - error:         purge call failed, OR re-probe still HITs after purge
      - fixed:         all stale paths purged and verified
    """
    if not _is_cf_pages_project(project_dir):
        return FixResult(status="nothing-to-do",
                         summary="not a Cloudflare Pages project",
                         files_touched=[])
    if not (project_dir / "dist").is_dir():
        return FixResult(status="manual",
                         summary="no dist/ — build the project before purging",
                         files_touched=[])

    domain = _domain_from_repo_path(project_dir)
    rows = _run_probes(project_dir, domain)
    stale = _stale_paths(rows)
    if not stale:
        return FixResult(status="nothing-to-do",
                         summary="no stale paths at edge",
                         files_touched=[])

    urls = [r["url"] for r in stale]
    if dry_run:
        return FixResult(
            status="would-fix",
            summary=f"would purge {len(urls)} path(s): {', '.join(r['path'] for r in stale)}",
            files_touched=[],
        )

    # Local imports — keeps the module importable in environments where
    # httpx-based CF auth isn't configured (the registry walks every
    # check module at startup; we don't want one missing config to break
    # `portfolio project check` for everyone).
    from ... import cloudflare

    try:
        zone_id = cloudflare.resolve_zone_id(domain)
    except cloudflare.MissingCredentialsError as e:
        return FixResult(status="manual", summary=str(e), files_touched=[])
    except cloudflare.CloudflareAPIError as e:
        return FixResult(
            status="error",
            summary=f"zone-id lookup failed: {e}\n"
                    "  Diagnose: `portfolio settings cloudflare status --verify` "
                    "confirms whether the saved token is still accepted by CF "
                    "(common cause: token revoked or missing Zone:Cache Purge "
                    "permission for this account).",
            files_touched=[],
        )

    try:
        cloudflare.purge_files(zone_id, urls)
    except cloudflare.MissingCredentialsError as e:
        return FixResult(status="manual", summary=str(e), files_touched=[])
    except cloudflare.CloudflareAPIError as e:
        return FixResult(
            status="error",
            summary=f"purge call failed: {e}\n"
                    "  Diagnose: `portfolio settings cloudflare status --verify` "
                    "checks whether CF still accepts the token. If it does, the "
                    "failure is likely zone-specific (token lacks Cache Purge "
                    "permission for this zone).",
            files_touched=[],
        )

    # Verify: re-probe the same paths. A successful purge makes the edge
    # re-fetch from origin, so a still-stale path means the purge didn't take.
    # Use the SAME staleness criterion as pre-purge (`_stale_paths`) — NOT a
    # narrower HIT/REVALIDATED filter. A stale object can be served as
    # `cf-cache-status: DYNAMIC` (e.g. a removed static file pinned by a long
    # `s-maxage`), and the old HIT-only check let those slip through → the fix
    # false-reported "fixed" while the stale content persisted (bugs.md
    # 2026-06-19). Report the surviving paths with their cache-status.
    after = _run_probes(project_dir, domain)
    still_stale = _stale_paths(after)
    if still_stale:
        detail = ", ".join(
            f"{r['path']} (cache={r.get('cf_cache_status') or '?'})"
            for r in still_stale
        )
        return FixResult(
            status="error",
            summary=f"purge sent but {len(still_stale)} path(s) still stale at "
                    f"edge: {detail}. CF purge-by-URL can lag a few seconds — "
                    f"re-run to retry (idempotent). If it persists, the cached "
                    f"key isn't matching the purge (purge the zone, or check the "
                    f"object's s-maxage / CF Pages asset caching).",
            files_touched=[],
        )

    return FixResult(
        status="fixed",
        summary=f"purged {len(urls)} path(s) from CF edge "
                f"({', '.join(r['path'] for r in stale)})",
        files_touched=[],
    )


fix_tier_1 = FixerSpec(
    check_id="",     # registry rewrites at discovery time
    tier=1,
    summary="purge stale paths from Cloudflare edge cache",
    apply=_apply_purge,
)
