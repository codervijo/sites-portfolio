"""v5.D — `check --seo` runtime probes.

Per-domain runtime SEO health check. Different shape from the file-system
registry (`src/portfolio/checks/`) because it runs against a deployed URL
+ external services (Google Search Console, Chrome UX Report) instead of
a project directory.

Three probe layers, each independently optional:

  1. Live HTTP — synchronous fetch of `https://<domain>/` and `/robots.txt`;
     parses `Sitemap:` directives from robots.txt and probes each declared
     URL (with fallback to `/sitemap.xml`, `/sitemap-index.xml`,
     `/sitemap_index.xml`); checks HSTS header on the root response.

  2. GSC totals — `query_totals()` over the last N days for every GSC
     property covering the domain (uses existing `gsc.py` OAuth path).
     Skipped silently when OAuth is not set up.

  3. CrUX field data — Chrome UX Report mobile-form-factor LCP/INP/CLS
     p75 values for the origin. Requires `CRUX_API_KEY` in portfolio.env;
     skipped silently if absent or the origin has no CrUX data.

Each probe contributes a status emoji (🟢/🟡/🟠/🔴) per metric. The row's
overall status is the worst of its individual metrics.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

import httpx

CRUX_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
CRUX_TIMEOUT = 10.0
HTTP_TIMEOUT = 8.0

# Thresholds per metric. Keys: green-upper, yellow-upper, orange-upper.
# Anything past orange-upper is red. For position, *lower* is better so
# the comparison flips (handled in `_position_status`).
_LCP_MS = (2500, 4000, 6000)         # Web Vitals "good" / "needs improvement" / "poor"
_INP_MS = (200, 500, 1000)
_CLS = (0.10, 0.25, 0.5)
_POSITION_GOOD = (10, 30, 50)        # avg position lower is better


@dataclass
class SEORow:
    """One domain's full SEO snapshot (HTTP + GSC + CrUX)."""
    domain: str

    # HTTP probes (None means probe skipped/errored).
    http_status: int | None = None
    http_error: str | None = None
    hsts: bool | None = None
    robots_served: bool | None = None
    sitemap_served: bool | None = None

    # GSC totals (None means not in GSC or auth not set up).
    gsc_status: str = "unknown"            # "ok", "not-in-gsc", "auth-skipped", "error"
    gsc_clicks: int | None = None
    gsc_impressions: int | None = None
    gsc_ctr: float | None = None           # 0.0 - 1.0
    gsc_position: float | None = None
    gsc_sitemap_count: int | None = None   # number of sitemaps submitted

    # Per-sitemap processing status from GSC's `sitemaps().list()` response.
    # Distinct from `gsc_sitemap_count` (presence only): these are what
    # surface "Sitemap could not be read" in Search Console. None means
    # the data wasn't collected (auth-skipped / not-in-gsc / API error).
    gsc_sitemap_errors: int | None = None      # summed across submitted sitemaps
    gsc_sitemap_warnings: int | None = None    # summed across submitted sitemaps
    gsc_sitemap_pending: int | None = None     # how many GSC hasn't fetched yet
    gsc_sitemap_details: list | None = None    # raw per-sitemap dicts (path, errors, warnings, lastDownloaded, isPending)

    # CrUX (None means no API key, no CrUX data, or error).
    crux_status: str = "unknown"           # "ok", "no-data", "no-key", "error"
    crux_lcp_p75: float | None = None      # ms
    crux_inp_p75: float | None = None      # ms
    crux_cls_p75: float | None = None

    # URL of the sitemap that responded 200 — useful for the dashboard
    # to surface non-default paths (e.g. /sitemap-index.xml). None when
    # no sitemap was found OR the probe was skipped.
    sitemap_url: str | None = None

    # Crawler intent declared in robots.txt. "dark" means the site is
    # deliberately blocked from crawlers (members-only, staging, etc.) —
    # detected from `User-agent: *` or `User-agent: Googlebot` having
    # `Disallow: /` with no overriding `Allow: /` in the same block.
    # Dark rows short-circuit the SEO overall to 🔒 and suppress focus
    # signals tied to public-web discovery (no-sitemap, sitemap-errors,
    # zero-impressions, bad-position). None when robots.txt wasn't served.
    robots_intent: str | None = None       # "dark", "open", or None

    notes: list[str] = field(default_factory=list)


# ---------- HTTP probes ----------


# Conventional sitemap paths to try when robots.txt doesn't declare one.
# Order matters: `/sitemap.xml` is by far the most common; `-index` and
# `_index` cover the two index conventions seen in the wild.
_SITEMAP_FALLBACK_PATHS = ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml")


def _robots_intent_from_body(body: str) -> str:
    """Detect dark-site intent in a robots.txt body.

    Returns "dark" when the file deliberately blocks all crawlers or
    Googlebot at the site root; "open" otherwise.

    Dark rule: a `User-agent: *` or `User-agent: Googlebot` block (case-
    insensitive, exact match on the agent name) carries `Disallow: /`
    with no overriding `Allow: /` in the same block. Partial-tree
    blocks (e.g. `Disallow: /admin`) are NOT dark — only root-level
    universal blocks qualify. We intentionally over-conservative here:
    flagging a normal site as dark hides real signals; missing one is
    just a transient cosmetic gap.

    Consecutive `User-agent:` lines combine into a single rule group —
    standard robots.txt grammar (RFC 9309 / Google's spec). Blank lines
    or a non-agent directive close the group.
    """
    if not body:
        return "open"

    DARK_AGENTS = {"*", "googlebot"}
    # Per agent we've seen, the list of (directive, path) pairs.
    rules: dict[str, list[tuple[str, str]]] = {}

    current_agents: set[str] = set()
    expecting_more_agents = True
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            # Blank line / comment → close the current rule group.
            current_agents = set()
            expecting_more_agents = True
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip().lower()
        val = val.strip()
        if key == "user-agent":
            if not expecting_more_agents:
                # New group starts here — drop the prior agent set.
                current_agents = set()
                expecting_more_agents = True
            current_agents.add(val.lower())
        elif key in ("disallow", "allow"):
            expecting_more_agents = False
            for agent in current_agents:
                rules.setdefault(agent, []).append((key, val))
        # All other directives (Sitemap, Crawl-delay, Host, …) don't
        # affect dark detection and don't close the agent group.

    for agent in DARK_AGENTS:
        agent_rules = rules.get(agent, [])
        if not agent_rules:
            continue
        has_root_disallow = any(d == "disallow" and v == "/" for d, v in agent_rules)
        has_root_allow = any(d == "allow" and v == "/" for d, v in agent_rules)
        if has_root_disallow and not has_root_allow:
            return "dark"
    return "open"


def _parse_robots_sitemaps(body: str) -> list[str]:
    """Extract absolute sitemap URLs from a robots.txt body. Case-insensitive
    on the directive name; ignores blank/comment lines and malformed entries
    (anything that isn't `http(s)://...`).
    """
    urls: list[str] = []
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Match `Sitemap: <url>` (case-insensitive directive name).
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        if key.strip().lower() != "sitemap":
            continue
        url = val.strip()
        if url.startswith("http://") or url.startswith("https://"):
            urls.append(url)
    return urls


def probe_http(domain: str, *, timeout: float = HTTP_TIMEOUT,
               client: httpx.Client | None = None) -> dict[str, Any]:
    """Fetch the root + /robots.txt, then probe for the sitemap. Returns a
    dict with keys: status, error, hsts, robots_served, sitemap_served,
    sitemap_url.

    Sitemap discovery: read `Sitemap:` directives from robots.txt; if any
    are declared, probe each in turn (first 200 wins). If robots is missing
    or declares no sitemap, fall back to /sitemap.xml, /sitemap-index.xml,
    /sitemap_index.xml in that order.

    Caller may inject an `httpx.Client` (used by tests for transport mocks).
    """
    out: dict[str, Any] = {
        "status": None, "error": None, "hsts": None,
        "robots_served": None, "sitemap_served": None,
        "sitemap_url": None, "robots_intent": None,
    }
    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout, follow_redirects=True,
                              headers={"User-Agent": "portfolio-cli/seo-probe"})
    try:
        try:
            root = client.get(f"https://{domain}/")
            out["status"] = root.status_code
            out["hsts"] = "strict-transport-security" in {
                k.lower() for k in root.headers.keys()
            }
        except httpx.HTTPError as e:
            out["error"] = f"{type(e).__name__}: {e}"
            return out

        robots_body = ""
        try:
            r = client.get(f"https://{domain}/robots.txt")
            ctype = r.headers.get("content-type", "").lower()
            # Parked pages often serve text/html for /robots.txt — reject that
            # explicitly. Accept text/plain (the standard) or unset content-type
            # paired with `User-agent:` somewhere in the body as a fallback.
            ok = r.status_code == 200 and (
                "text/plain" in ctype
                or (ctype == "" and "user-agent" in r.text.lower())
            )
            out["robots_served"] = ok
            if ok:
                robots_body = r.text
                out["robots_intent"] = _robots_intent_from_body(robots_body)
        except httpx.HTTPError:
            out["robots_served"] = False

        # Build sitemap-candidate list: declared in robots.txt first
        # (already absolute URLs), then fallback paths under the same host.
        declared = _parse_robots_sitemaps(robots_body) if robots_body else []
        candidates: list[str] = list(declared)
        for path in _SITEMAP_FALLBACK_PATHS:
            url = f"https://{domain}{path}"
            if url not in candidates:
                candidates.append(url)

        out["sitemap_served"] = False
        for url in candidates:
            try:
                s = client.get(url)
            except httpx.HTTPError:
                continue
            if s.status_code == 200:
                out["sitemap_served"] = True
                out["sitemap_url"] = str(s.url)
                break
    finally:
        if own_client:
            client.close()
    return out


# ---------- GSC ----------


def probe_gsc(domain: str, *, days: int,
              gsc_service=None, coverage=None,
              auth_skipped: bool = False) -> dict[str, Any]:
    """Pull GSC totals for `domain` over the last `days` days. The caller
    is expected to authenticate once and reuse `gsc_service`/`coverage`
    across all domains. Returns keys: status, clicks, impressions, ctr,
    position, sitemap_count.

    `auth_skipped=True` short-circuits to status="auth-skipped" without
    making any API call (used when no OAuth credentials are configured).
    """
    out: dict[str, Any] = {
        "status": "unknown", "clicks": None, "impressions": None,
        "ctr": None, "position": None, "sitemap_count": None,
        "sitemap_errors": None, "sitemap_warnings": None,
        "sitemap_pending": None, "sitemap_details": None,
    }
    if auth_skipped:
        out["status"] = "auth-skipped"
        return out

    from .gsc import query_totals  # local import: optional dep if user hasn't installed Google libs
    properties = (coverage or {}).get(domain, [])
    if not properties:
        out["status"] = "not-in-gsc"
        return out

    # Sum across multi-property domains (sc-domain: + url-prefix can both exist).
    end = date.today() - timedelta(days=3)  # GSC has ~3 days of lag
    start = end - timedelta(days=days - 1)
    total_clicks = 0
    total_imp = 0
    weighted_pos: list[tuple[float, int]] = []
    sitemap_count = 0
    sitemap_errors = 0
    sitemap_warnings = 0
    sitemap_pending = 0
    sitemap_details: list[dict] = []
    try:
        for p in properties:
            t = query_totals(gsc_service, p["siteUrl"], start, end)
            total_clicks += int(t.get("clicks", 0))
            total_imp += int(t.get("impressions", 0))
            if t.get("position") is not None and t.get("impressions"):
                weighted_pos.append((float(t["position"]), int(t["impressions"])))
            # Sitemaps API is one call per property. We keep per-sitemap
            # `errors` / `warnings` / `isPending` — that's where "Sitemap
            # could not be read" surfaces. Counts alone hide that signal.
            try:
                sm = gsc_service.sitemaps().list(siteUrl=p["siteUrl"]).execute()
                entries = sm.get("sitemap", []) or []
                sitemap_count += len(entries)
                for entry in entries:
                    err = _coerce_int(entry.get("errors"))
                    warn = _coerce_int(entry.get("warnings"))
                    pending = bool(entry.get("isPending"))
                    sitemap_errors += err
                    sitemap_warnings += warn
                    if pending:
                        sitemap_pending += 1
                    sitemap_details.append({
                        "path": entry.get("path"),
                        "errors": err,
                        "warnings": warn,
                        "is_pending": pending,
                        "last_downloaded": entry.get("lastDownloaded"),
                        "last_submitted": entry.get("lastSubmitted"),
                        "property": p["siteUrl"],
                    })
            except Exception:
                pass
    except Exception as e:
        out["status"] = "error"
        out["error"] = f"{type(e).__name__}: {e}"
        return out

    out["status"] = "ok"
    out["clicks"] = total_clicks
    out["impressions"] = total_imp
    out["ctr"] = (total_clicks / total_imp) if total_imp else 0.0
    if weighted_pos:
        out["position"] = sum(p * i for p, i in weighted_pos) / sum(i for _, i in weighted_pos)
    else:
        out["position"] = None
    out["sitemap_count"] = sitemap_count
    out["sitemap_errors"] = sitemap_errors
    out["sitemap_warnings"] = sitemap_warnings
    out["sitemap_pending"] = sitemap_pending
    out["sitemap_details"] = sitemap_details
    return out


def _coerce_int(value: Any) -> int:
    """GSC's Sitemaps API returns errors/warnings as numeric strings.
    Coerce safely — anything we can't parse is treated as 0 so a
    malformed field doesn't poison the aggregate."""
    if value is None:
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


# ---------- CrUX ----------


def probe_crux(domain: str, api_key: str, *,
               client: httpx.Client | None = None,
               timeout: float = CRUX_TIMEOUT) -> dict[str, Any]:
    """Query Chrome UX Report for the origin's mobile-form-factor p75 LCP,
    INP, CLS. Returns keys: status, lcp_p75, inp_p75, cls_p75.

    A 404 from CrUX means the origin doesn't have enough field data to
    appear in the dataset — that's "no-data", not an error.
    """
    out: dict[str, Any] = {
        "status": "unknown", "lcp_p75": None, "inp_p75": None, "cls_p75": None,
    }
    if not api_key:
        out["status"] = "no-key"
        return out

    own_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout)
    try:
        try:
            resp = client.post(
                f"{CRUX_ENDPOINT}?key={api_key}",
                json={
                    "origin": f"https://{domain}",
                    "formFactor": "PHONE",
                    "metrics": ["largest_contentful_paint",
                                "interaction_to_next_paint",
                                "cumulative_layout_shift"],
                },
            )
        except httpx.HTTPError as e:
            out["status"] = "error"
            out["error"] = f"{type(e).__name__}: {e}"
            return out
        if resp.status_code == 404:
            out["status"] = "no-data"
            return out
        if resp.status_code != 200:
            out["status"] = "error"
            out["error"] = f"http {resp.status_code}"
            return out
        body = resp.json()
        metrics = body.get("record", {}).get("metrics", {})
        out["lcp_p75"] = _crux_p75(metrics.get("largest_contentful_paint"))
        out["inp_p75"] = _crux_p75(metrics.get("interaction_to_next_paint"))
        out["cls_p75"] = _crux_p75(metrics.get("cumulative_layout_shift"))
        out["status"] = "ok"
    finally:
        if own_client:
            client.close()
    return out


def _crux_p75(metric: dict | None) -> float | None:
    if not metric or "percentiles" not in metric:
        return None
    val = metric["percentiles"].get("p75")
    if val is None:
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


# ---------- Status emojis ----------

_GREEN = "🟢"
_YELLOW = "🟡"
_ORANGE = "🟠"
_RED = "🔴"
_GREY = "⚪"   # unknown / skipped

# Distinct callout for "GSC site exists but no sitemap submitted." Big
# red X — visually distinct from the 🟢/🟡/🔴/⚪ dot palette (different
# shape entirely, not just a different color). Reads instantly as a
# fixable ops gap when scanning the table.
_NO_SITEMAP_SUBMITTED = "❌"

# Dark site indicator — robots.txt deliberately blocks crawlers. Distinct
# shape (lock) for at-a-glance "this row is intentionally not crawled,
# don't grade it on GSC/imp/pos." Rolls up into the SEO overall and the
# GSC-sitemap cell, suppresses focus signals tied to public-web discovery.
_DARK = "🔒"


def _status_for_higher(value: float | None, thresholds: tuple[float, float, float]) -> str:
    """Lower value → better health. green/yellow/orange thresholds, then red."""
    if value is None:
        return _GREY
    g, y, o = thresholds
    if value <= g:
        return _GREEN
    if value <= y:
        return _YELLOW
    if value <= o:
        return _ORANGE
    return _RED


def _bool_status(value: bool | None) -> str:
    if value is None:
        return _GREY
    return _GREEN if value else _RED


def _http_status(status: int | None) -> str:
    if status is None:
        return _RED
    if 200 <= status < 300:
        return _GREEN
    if 300 <= status < 400:
        return _YELLOW
    return _RED


def _position_status(pos: float | None) -> str:
    """Avg position: lower is better. <=10 green, <=30 yellow, <=50 orange, else red."""
    if pos is None:
        return _GREY
    g, y, o = _POSITION_GOOD
    if pos <= g:
        return _GREEN
    if pos <= y:
        return _YELLOW
    if pos <= o:
        return _ORANGE
    return _RED


def _impressions_status(imp: int | None) -> str:
    """Just a presence signal: zero is red, non-zero green, unknown grey."""
    if imp is None:
        return _GREY
    return _GREEN if imp > 0 else _RED


def _gsc_presence_status(gsc_status: str) -> str:
    """Whether the domain is registered as a GSC property.
    "ok" → 🟢, "not-in-gsc" → 🔴, anything else (auth-skipped/error/unknown) → ⚪."""
    if gsc_status == "ok":
        return _GREEN
    if gsc_status == "not-in-gsc":
        return _RED
    return _GREY


def _gsc_sitemap_submitted_status(gsc_status: str,
                                  sitemap_count: int | None) -> str:
    """Whether a sitemap is submitted to GSC for this domain.

    Distinct from `_bool_status(row.sitemap_served)` which checks the
    LIVE URL. A site can serve a valid sitemap and still have zero
    submitted to Search Console — that's a real, fixable ops gap.

    Returns:
      🟢 — submitted (count ≥ 1)
      🗺 — in GSC but zero sitemaps submitted (the distinct callout)
      ⚪ — not in GSC / auth-skipped / unknown (can't tell)
    """
    if gsc_status != "ok":
        # Can't distinguish "no submission" from "no auth"; render grey.
        return _GREY
    if sitemap_count is None:
        return _GREY
    if sitemap_count >= 1:
        return _GREEN
    return _NO_SITEMAP_SUBMITTED


def _gsc_sitemap_health_status(gsc_status: str,
                               sitemap_count: int | None,
                               sitemap_errors: int | None,
                               sitemap_warnings: int | None) -> str:
    """Whether GSC could actually READ the submitted sitemap(s).

    Distinct from `_gsc_sitemap_submitted_status` (presence only): this
    is the per-sitemap processing status from GSC's `sitemaps().list()`
    response. A sitemap can be submitted and still have GSC report
    "Sitemap could not be read" — that's `errors > 0`.

    Returns:
      🔴 — at least one submitted sitemap has errors (GSC can't read it)
      🟡 — at least one submitted sitemap has warnings (read but flagged)
      🟢 — submitted and clean
      ⚪ — nothing to grade (no submission, no GSC, no data)
    """
    if gsc_status != "ok":
        return _GREY
    if sitemap_count is None or sitemap_errors is None:
        return _GREY
    if sitemap_count == 0:
        # No sitemap → presence handles this case; nothing to grade here.
        return _GREY
    if sitemap_errors > 0:
        return _RED
    if (sitemap_warnings or 0) > 0:
        return _YELLOW
    return _GREEN


def _robots_cell_status(robots_served: bool | None,
                        robots_intent: str | None) -> str:
    """Robots column status. 🔒 when intent is dark (operator declared
    or detected the site is intentionally off-limits to crawlers);
    otherwise the plain served/not-served bool status."""
    if robots_intent == "dark":
        return _DARK
    return _bool_status(robots_served)


def row_statuses(row: SEORow) -> dict[str, str]:
    """Per-column emoji status for a row. Used by the renderer."""
    return {
        "http": _http_status(row.http_status),
        "hsts": _bool_status(row.hsts),
        "robots": _robots_cell_status(row.robots_served, row.robots_intent),
        "sitemap": _bool_status(row.sitemap_served),
        "gsc": _gsc_presence_status(row.gsc_status),
        "gsc_sitemap": _gsc_sitemap_submitted_status(
            row.gsc_status, row.gsc_sitemap_count,
        ),
        "gsc_sitemap_health": _gsc_sitemap_health_status(
            row.gsc_status, row.gsc_sitemap_count,
            row.gsc_sitemap_errors, row.gsc_sitemap_warnings,
        ),
        "imp": _impressions_status(row.gsc_impressions),
        "pos": _position_status(row.gsc_position),
        "lcp": _status_for_higher(row.crux_lcp_p75, _LCP_MS),
        "inp": _status_for_higher(row.crux_inp_p75, _INP_MS),
        "cls": _status_for_higher(row.crux_cls_p75, _CLS),
    }


def gsc_sitemap_cell(row: SEORow) -> str:
    """Single-cell merge of presence + health for the dashboard table.

    Operators scan this column for one signal: "is my sitemap situation
    OK from Google's perspective." Presence alone (`gsc_sitemap`) misses
    "submitted but GSC errored on it" (the donready incident). Health
    alone misses "never submitted." This combines them, ranked so the
    worse status wins.

    Dark sites short-circuit to 🔒 — they shouldn't be in GSC at all,
    so "no sitemap submitted" is correct, not a gap to fix.
    """
    if row.robots_intent == "dark":
        return _DARK
    s = row_statuses(row)
    health = s["gsc_sitemap_health"]
    presence = s["gsc_sitemap"]
    # Error on a submitted sitemap is the worst case — GSC has the file
    # and can't use it. Rank it above "never submitted" (a fixable gap).
    if health == _RED:
        return _RED
    if presence == _NO_SITEMAP_SUBMITTED:
        return _NO_SITEMAP_SUBMITTED
    if health == _YELLOW:
        return _YELLOW
    if health == _GREEN:
        return _GREEN
    return presence  # _GREY when no GSC data; _GREEN when count >= 1 but no health data


_OVERALL_RANK = {_GREEN: 0, _YELLOW: 1, _ORANGE: 2, _RED: 3, _GREY: -1}

# Only true SEO signals contribute to the row's overall status.
# HSTS is a security signal (belongs in `check --security` / `--live`); HTTP
# is observed for context but failures cascade naturally into robots/sitemap
# reds; CrUX field-data tiering is a separate dimension shown beside but not
# folded into the SEO overall. `gsc` (in-GSC vs not-in-GSC) IS a real SEO
# signal — a site missing from Search Console is invisible to Google.
_OVERALL_KEYS = ("imp", "pos", "robots", "sitemap", "gsc", "gsc_sitemap_health")

# P4 — age-aware grading. Sites inside the Google freshness window get
# their imp + pos cells masked out of the overall grade because zero
# impressions / bad position is normal for a 1-week-old indexed site —
# baking it into a 🔴 grade is misleading. Same threshold focus uses.
YOUNG_SITE_THRESHOLD_DAYS = 90
_AGE_MASKED_KEYS = ("imp", "pos")


def overall_status(row: SEORow, *, site_age_days: int | None = None,
                   young_threshold_days: int = YOUNG_SITE_THRESHOLD_DAYS) -> str:
    """Worst non-grey emoji across the SEO-signal metrics
    (impressions, position, robots, sitemap, gsc-presence).

    When `site_age_days` is provided AND less than `young_threshold_days`,
    the impressions and position cells are treated as grey for grading
    purposes — they don't pull the overall toward red. Robots / sitemap /
    GSC-presence still count because those are structural (the site
    either has them or doesn't, regardless of age).

    `site_age_days=None` → no masking (backward compatible with callers
    that don't have age data; better to over-flag than silently hide).

    Dark sites short-circuit to 🔒: SEO-discovery signals are by design
    inapplicable (members-only / blocked from search), so rolling up
    "zero impressions" or "not in GSC" as 🔴 would be misleading.
    """
    if row.robots_intent == "dark":
        return _DARK
    statuses = row_statuses(row)
    if (site_age_days is not None
            and site_age_days < young_threshold_days):
        for k in _AGE_MASKED_KEYS:
            statuses[k] = _GREY
    cells = [statuses[k] for k in _OVERALL_KEYS]
    real = [c for c in cells if c != _GREY]
    if not real:
        return _GREY
    return max(real, key=lambda c: _OVERALL_RANK.get(c, -1))


# ---------- Runner ----------


def _live_domains_from_snapshot(snapshot: dict) -> list[str]:
    """Return the unique domains from a `data/checks/*.json` snapshot whose
    classification is live-site or forwarder. Uses the "bare" variant when
    available so each domain appears once."""
    seen: dict[str, str] = {}
    for r in snapshot.get("results", []):
        cls = r.get("classification")
        if cls not in ("live-site", "forwarder"):
            continue
        domain = r.get("domain", "").lower()
        if not domain:
            continue
        # Prefer the bare variant; only overwrite www-only with bare-only.
        variant = r.get("variant", "")
        if domain not in seen or variant == "bare":
            seen[domain] = variant
    return sorted(seen.keys())


def _snapshot_scope_split(snapshot: dict) -> tuple[int, int, int]:
    """Return (total, probed, excluded) domain counts for a check snapshot.

    `probed` is the count of unique live-site/forwarder domains (the set
    `fleet seo` actually probes); `total` is every unique domain in the
    snapshot regardless of classification; `excluded = total - probed`
    (parked / dead / error / ssl-broken — classifications SEO can't grade).

    Used by `fleet seo` to surface why its domain count is smaller than
    `fleet domains`' fleet total."""
    all_domains: set[str] = set()
    for r in snapshot.get("results", []):
        domain = r.get("domain", "").lower()
        if domain:
            all_domains.add(domain)
    probed = len(_live_domains_from_snapshot(snapshot))
    total = len(all_domains)
    return total, probed, total - probed


def run_seo(
    domains: list[str],
    *,
    days: int = 28,
    crux_api_key: str = "",
    concurrency: int = 4,
    progress_callback=None,
) -> list[SEORow]:
    """Probe HTTP, GSC, and CrUX for each domain. Returns one SEORow per
    domain, in input order.

    `progress_callback`, if given, is called with (n_done, n_total, domain)
    after each domain completes — used by the CLI for a live progress line.
    """
    if not domains:
        return []

    # Set up GSC once (auth + coverage map). Tolerate failure quietly so the
    # HTTP/CrUX probes still produce useful output. Per-thread service is
    # built inside `fetch_one` because httplib2 (under googleapiclient) is
    # not thread-safe — same pattern as `gsc.sync()`.
    creds = None
    gsc_coverage: dict[str, list[dict]] = {}
    auth_skipped = False
    try:
        from .gsc import authenticate, get_service, list_properties, coverage_map
        creds = authenticate()
        bootstrap = get_service(creds)
        gsc_coverage = coverage_map(list_properties(bootstrap))
    except Exception:
        # Most common: MissingCredentialsError. Treat all as auth-skipped.
        auth_skipped = True

    def fetch_one(domain: str) -> SEORow:
        row = SEORow(domain=domain)
        http = probe_http(domain)
        row.http_status = http["status"]
        row.http_error = http["error"]
        row.hsts = http["hsts"]
        row.robots_served = http["robots_served"]
        row.sitemap_served = http["sitemap_served"]
        row.sitemap_url = http.get("sitemap_url")
        row.robots_intent = http.get("robots_intent")

        local_service = None
        if not auth_skipped and creds is not None:
            from .gsc import get_service as _gs
            local_service = _gs(creds)
        gsc_data = probe_gsc(
            domain, days=days,
            gsc_service=local_service, coverage=gsc_coverage,
            auth_skipped=auth_skipped,
        )
        row.gsc_status = gsc_data["status"]
        row.gsc_clicks = gsc_data.get("clicks")
        row.gsc_impressions = gsc_data.get("impressions")
        row.gsc_ctr = gsc_data.get("ctr")
        row.gsc_position = gsc_data.get("position")
        row.gsc_sitemap_count = gsc_data.get("sitemap_count")
        row.gsc_sitemap_errors = gsc_data.get("sitemap_errors")
        row.gsc_sitemap_warnings = gsc_data.get("sitemap_warnings")
        row.gsc_sitemap_pending = gsc_data.get("sitemap_pending")
        row.gsc_sitemap_details = gsc_data.get("sitemap_details")

        crux = probe_crux(domain, crux_api_key)
        row.crux_status = crux["status"]
        row.crux_lcp_p75 = crux.get("lcp_p75")
        row.crux_inp_p75 = crux.get("inp_p75")
        row.crux_cls_p75 = crux.get("cls_p75")
        return row

    rows: list[SEORow] = [None] * len(domains)  # type: ignore[list-item]
    completed = 0
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(fetch_one, d): i for i, d in enumerate(domains)}
        # Report in COMPLETION order, not submission order — otherwise the
        # progress counter blocks on each domain in turn (a slow domain #0
        # freezes the count at 0/N while the rest finish in the background,
        # then it jumps N/N). `rows[i]` keeps results in input order.
        for fut in as_completed(futures):
            i = futures[fut]
            try:
                rows[i] = fut.result()
            except Exception as e:
                rows[i] = SEORow(domain=domains[i],
                                 http_error=f"runner error: {type(e).__name__}: {e}")
            completed += 1
            if progress_callback is not None:
                progress_callback(completed, len(domains), domains[i])
    return rows


def sort_rows(rows: list[SEORow], key: str) -> list[SEORow]:
    """Sort by 'domain' (default — alphabetical), 'impressions', 'clicks',
    'position', or 'ctr'."""
    if key == "impressions":
        return sorted(rows, key=lambda r: -(r.gsc_impressions or 0))
    if key == "clicks":
        return sorted(rows, key=lambda r: -(r.gsc_clicks or 0))
    if key == "position":
        # Lower position is better; None goes to the end.
        return sorted(rows, key=lambda r: (
            r.gsc_position is None, r.gsc_position or 999.0
        ))
    if key == "ctr":
        return sorted(rows, key=lambda r: -(r.gsc_ctr or 0.0))
    # Default: domain alphabetical (2026-05-28). Scanning a mostly-young
    # fleet by name beats impressions-desc, which buried most domains in
    # a 0-impression block.
    return sorted(rows, key=lambda r: r.domain.lower())
