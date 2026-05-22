"""v19.B — Google Trends via `pytrends`.

Standalone `lamill new trends <topic>` data fetcher. Cache layout
matches `seo_cache.py` / `hosting_cache.py` conventions (24h TTL,
per-topic JSON file, atomic write). pytrends boundary stays at the
edge of this module so tests can mock `pytrends.request.TrendReq`
without touching real Google Trends.

Per v19.A scope lock 2026-05-22: no cluster-snapshot integration,
no shortlist binding, no SerpAPI fallback — pytrends is the only
path. Soft failure on library errors (caller decides to surface or
exit; module just raises `GTrendsError`).

**2026-05-22 PM — 429 mitigation pass.** Two operator-logged bugs
addressed:

  1. `ModuleNotFoundError: No module named 'pytrends'` (operator on
     older Python env where the `lamill` binary predates v19.B's
     pytrends dep) → wrapped `from pytrends.request import TrendReq`
     in try/except ImportError → raises typed `GTrendsError` with
     `uv sync` hint.
  2. HTTP 429 surfaced as cryptic `pytrends fetch failed for 'X':
     The request failed: Google returned a response with code 429`
     → detect "429" / "Too Many Requests" in pytrends error → raise
     new `GTrendsRateLimitError(GTrendsError)` subclass with
     wait-10-30-min hint.

Plus two structural mitigations:

  - **L1 stale-cache fallback**: on rate-limit, return ANY cached
    payload regardless of 24h TTL (renderer surfaces a stale-age
    warning). Better than failing when operator already has a
    47h-old copy on disk.
  - **L3 UA rotation**: cycle 5 realistic browser User-Agents per
    pytrends call. Anecdotal help with Google's IP-rate-limiter.

L4 SerpAPI fallback intentionally NOT shipped — pinned for later
re-litigation if pytrends becomes chronically unreliable. v19.A's
"serp etc not needed" decision stands as long as L1+L3 keep the
common cases working.
"""
from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .data import ROOT

GTRENDS_DIR = ROOT / "data" / "gtrends"
SCHEMA = "gtrends-v1"
DEFAULT_TTL_HOURS = 24

# Map v19.A's flag values to pytrends' string conventions. Reject
# anything else — operator-facing CLI validates first, but the wrapper
# also guards so direct callers don't pass garbage.
TIMEFRAME_MAP: dict[str, str] = {
    "7d":  "now 7-d",
    "30d": "today 1-m",
    "90d": "today 3-m",
    "12m": "today 12-m",
    "5y":  "today 5-y",
    "all": "all",
}
DEFAULT_TIMEFRAME = "12m"


class GTrendsError(RuntimeError):
    """Raised when `pytrends` fails to fetch trend data. Carries the
    underlying error in the message. Caller (CLI) prints + exits
    non-zero; no automatic retry since pytrends has no official SLA."""


class GTrendsRateLimitError(GTrendsError):
    """Subclass for HTTP 429 / IP-rate-limited responses.

    Caller (CLI) handles separately from the generic GTrendsError so
    the operator-facing message can be specifically actionable
    ("wait 10-30 min; rate limit is IP-based, trying other topics
    from the same IP won't help") rather than a generic failure.

    `fetch_trends()` catches this internally to attempt the L1
    stale-cache fallback before re-raising — operator usually gets
    data anyway as long as they've queried the topic recently."""


# L3 — User-Agent rotation. Cycle realistic modern browser UAs per
# pytrends call. Anecdotal help against Google's rate-limiter; cheap
# to ship. Picked one at random per call rather than round-robin
# because the rate-limit window is per-IP, not per-UA — randomization
# just avoids the static pytrends default being a recognizable
# fingerprint.
_USER_AGENTS: tuple[str, ...] = (
    # Chrome — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Chrome — Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
    # Firefox — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14.1; rv:120.0) "
    "Gecko/20100101 Firefox/120.0",
    # Firefox — Windows
    "Mozilla/5.0 (Windows NT 10.0; rv:120.0) Gecko/20100101 Firefox/120.0",
    # Safari — macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.0 Safari/605.1.15",
)


def _pick_user_agent() -> str:
    """Random UA per call. Module-level seeded RNG is fine — security
    isn't the concern here; we just want variability across calls."""
    return random.choice(_USER_AGENTS)


def _make_pytrends_client():
    """Shared TrendReq construction — used by both topic-specific
    `_fetch_from_pytrends` and the latest-trends fetcher. Centralizes
    the ImportError wrap + UA rotation so both paths get the same
    mitigations.

    Raises typed `GTrendsError` if pytrends isn't installed (with the
    `uv sync` hint). Returns a `pytrends.request.TrendReq` instance.
    """
    try:
        from pytrends.request import TrendReq
    except ImportError as e:
        raise GTrendsError(
            f"pytrends library not installed ({e}). "
            f"Run `uv sync` in the portfolio project root to install the "
            f"v19.B dependency, then re-run `uv run lamill new trends`. "
            f"If using a system-installed `lamill` binary, reinstall "
            f"(e.g. `pipx reinstall portfolio`)."
        ) from e
    return TrendReq(
        hl="en-US",
        tz=0,
        timeout=(10, 30),
        requests_args={
            "headers": {
                "User-Agent": _pick_user_agent(),
                "Accept-Language": "en-US,en;q=0.9",
            },
        },
    )


# 2026-05-22 PM — "latest trends" surface for the no-topic call.
# pytrends' `trending_searches(pn=...)` returns Google's daily
# trending searches per region. Region codes are full names with
# underscores (united_states, united_kingdom, ...), which is
# inconsistent with the ISO codes accepted by `build_payload` /
# `realtime_trending_searches`. Maintain a small mapping so the CLI
# can keep `-r US` / `-r GB` shape consistent regardless of which
# pytrends endpoint we hit.
_DAILY_REGION_MAP: dict[str, str] = {
    "US": "united_states",
    "GB": "united_kingdom",
    "UK": "united_kingdom",   # alias — operators often type UK
    "IN": "india",
    "DE": "germany",
    "JP": "japan",
    "FR": "france",
    "CA": "canada",
    "AU": "australia",
    "BR": "brazil",
    "MX": "mexico",
    "ES": "spain",
    "IT": "italy",
    "NL": "netherlands",
    "SG": "singapore",
}

DEFAULT_LATEST_REGION = "US"


@dataclass(frozen=True)
class LatestTrendsPayload:
    """Daily trending searches snapshot. Schema is intentionally
    distinct from `TrendsPayload` (different cache key, different
    JSON shape, different schema version) so the two never collide
    in cache files or in the renderer's type dispatch."""
    region: str       # operator-facing ISO code (e.g., "US")
    fetched_at: str   # ISO 8601 UTC
    trending: list[str]   # ordered list of trending query strings


LATEST_SCHEMA = "gtrends-latest-v1"


@dataclass(frozen=True)
class TrendsPayload:
    """Normalized trends snapshot. Cache file is a serialized form
    of this; in-memory shape is the same for renderer + JSON output."""
    topic: str
    timeframe: str  # operator-facing string from TIMEFRAME_MAP keys
    region: str
    fetched_at: str
    interest_over_time: list[dict]  # [{"date": "YYYY-MM-DD", "value": int}, ...]
    related_top: list[dict]         # [{"query": "...", "value": int}, ...]
    related_rising: list[dict]


# ---- cache plumbing -------------------------------------------------


def _topic_hash(topic: str, *, timeframe: str, region: str) -> str:
    """12-char sha256 prefix of the (topic, timeframe, region) tuple.
    Same topic at different timeframes hits separate cache files —
    operator running `lamill new trends X --timeframe 7d` and then
    `lamill new trends X --timeframe 12m` shouldn't get stale results
    from the first call."""
    key = f"{topic.strip().lower()}|{timeframe}|{region}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def cache_path(topic: str, *, timeframe: str, region: str) -> Path:
    return GTRENDS_DIR / f"{_topic_hash(topic, timeframe=timeframe, region=region)}.json"


def is_stale(payload: dict, *, max_age_hours: int = DEFAULT_TTL_HOURS) -> bool:
    """Cache freshness check. Caller passes the loaded JSON; we look
    at `fetched_at` (UTC ISO 8601). Missing / malformed timestamps
    count as stale — defensive against schema drift."""
    fetched = payload.get("fetched_at")
    if not isinstance(fetched, str):
        return True
    try:
        ts = datetime.fromisoformat(fetched)
    except ValueError:
        return True
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - ts
    return age > timedelta(hours=max_age_hours)


def load_cached(
    topic: str, *,
    timeframe: str, region: str,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> TrendsPayload | None:
    """Return cached TrendsPayload if a fresh entry exists; else None."""
    path = cache_path(topic, timeframe=timeframe, region=region)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema") != SCHEMA:
        return None
    if is_stale(raw, max_age_hours=max_age_hours):
        return None
    return TrendsPayload(
        topic=raw["topic"],
        timeframe=raw["timeframe"],
        region=raw["region"],
        fetched_at=raw["fetched_at"],
        interest_over_time=list(raw.get("interest_over_time") or []),
        related_top=list(raw.get("related_top") or []),
        related_rising=list(raw.get("related_rising") or []),
    )


def load_any_cached(
    topic: str, *,
    timeframe: str, region: str,
) -> TrendsPayload | None:
    """Same as `load_cached` but skips the staleness check — returns
    the cached payload regardless of age. Used by the L1 fallback in
    `fetch_trends`: when pytrends rate-limits, we'd rather give the
    operator a 47h-old payload than a hard error.

    Returns None only when no cache file exists for the
    (topic, timeframe, region) tuple OR the file is unreadable /
    schema-mismatched (defensive against schema drift).
    """
    path = cache_path(topic, timeframe=timeframe, region=region)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema") != SCHEMA:
        return None
    return TrendsPayload(
        topic=raw["topic"],
        timeframe=raw["timeframe"],
        region=raw["region"],
        fetched_at=raw["fetched_at"],
        interest_over_time=list(raw.get("interest_over_time") or []),
        related_top=list(raw.get("related_top") or []),
        related_rising=list(raw.get("related_rising") or []),
    )


def payload_age_hours(payload: TrendsPayload) -> float | None:
    """How old is this payload, in hours? Used by the CLI renderer
    to decide whether to print a stale-warning header on L1 fallback
    payloads. Returns None if `fetched_at` can't be parsed."""
    try:
        ts = datetime.fromisoformat(payload.fetched_at)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return delta.total_seconds() / 3600.0


def save_cached(payload: TrendsPayload) -> Path:
    """Atomic write of the payload to its cache file."""
    GTRENDS_DIR.mkdir(parents=True, exist_ok=True)
    path = cache_path(
        payload.topic, timeframe=payload.timeframe, region=payload.region,
    )
    body = {
        "schema": SCHEMA,
        "topic": payload.topic,
        "timeframe": payload.timeframe,
        "region": payload.region,
        "fetched_at": payload.fetched_at,
        "interest_over_time": payload.interest_over_time,
        "related_top": payload.related_top,
        "related_rising": payload.related_rising,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


# ---- pytrends wrapper ----------------------------------------------


def _fetch_from_pytrends(
    topic: str, *,
    timeframe_pytrends: str, region: str,
) -> TrendsPayload:
    """Make the actual pytrends call. Boundary kept narrow so tests
    mock `pytrends.request.TrendReq` here without faking the broader
    fetch flow."""
    try:
        client = _make_pytrends_client()
        client.build_payload([topic], timeframe=timeframe_pytrends, geo=region)
        iot_df = client.interest_over_time()
        related = client.related_queries()
    except GTrendsError:
        # ImportError-wrap from _make_pytrends_client; let it propagate.
        raise
    except Exception as e:
        # 2026-05-22 — detect HTTP 429 specifically so the CLI can
        # render the rate-limit case yellow (transient) instead of red
        # (permanent failure). Closes the bugs.md 429 cryptic-error
        # entry. pytrends raises as `pytrends.exceptions.TooManyRequestsError`
        # in newer versions OR wraps as generic Exception with "429" /
        # "Too Many Requests" in the message string — match on the
        # string content to handle both shapes.
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg.lower():
            raise GTrendsRateLimitError(
                f"Google Trends rate-limited (HTTP 429) for {topic!r}. "
                f"Wait 10-30 minutes and retry — the limit is IP-based, "
                f"so trying other topics from the same IP won't help. "
                f"pytrends has no official quota; backoff windows vary "
                f"by IP reputation."
            ) from e
        raise GTrendsError(f"pytrends fetch failed for {topic!r}: {e}") from e

    # interest_over_time DataFrame → list of {date, value}. pytrends
    # adds an `isPartial` column for the current incomplete period;
    # we keep all rows (partial flagged via a separate field if we
    # add one later) but drop the `isPartial` column from the value.
    iot_rows: list[dict] = []
    if iot_df is not None and not iot_df.empty:
        topic_col = topic if topic in iot_df.columns else iot_df.columns[0]
        for ts, row in iot_df.iterrows():
            iot_rows.append({
                "date": ts.strftime("%Y-%m-%d"),
                "value": int(row[topic_col]),
            })

    # related_queries returns {topic: {top: DataFrame|None, rising: DataFrame|None}}.
    # Either side can be None when Google has insufficient data; treat
    # as empty list rather than blowing up.
    top_rows: list[dict] = []
    rising_rows: list[dict] = []
    block = (related or {}).get(topic) or {}
    top_df = block.get("top")
    rising_df = block.get("rising")
    if top_df is not None and not top_df.empty:
        for _idx, row in top_df.iterrows():
            top_rows.append({
                "query": str(row["query"]),
                "value": int(row["value"]),
            })
    if rising_df is not None and not rising_df.empty:
        for _idx, row in rising_df.iterrows():
            rising_rows.append({
                "query": str(row["query"]),
                # "Breakout" / huge spikes render as the string "Breakout"
                # in pytrends rather than a number. Normalize to None so
                # the renderer can show "↑" instead of trying to parse.
                "value": _parse_rising_value(row["value"]),
            })

    return TrendsPayload(
        topic=topic,
        timeframe=_pytrends_to_flag(timeframe_pytrends),
        region=region,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        interest_over_time=iot_rows,
        related_top=top_rows,
        related_rising=rising_rows,
    )


def _parse_rising_value(raw) -> int | None:
    """pytrends' rising-queries value is either an integer (% growth)
    or the literal string `"Breakout"`. Normalize to int|None so JSON
    serialization stays clean."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _pytrends_to_flag(pytrends_tf: str) -> str:
    """Inverse of TIMEFRAME_MAP — used after a pytrends fetch to
    record the operator-facing flag value in the cache (so the
    renderer can display "12m" instead of "today 12-m")."""
    for flag, pt in TIMEFRAME_MAP.items():
        if pt == pytrends_tf:
            return flag
    return pytrends_tf  # passthrough for anything unmapped


# ---- public surface ------------------------------------------------


def fetch_trends(
    topic: str, *,
    timeframe: str = DEFAULT_TIMEFRAME,
    region: str = "",
    refresh: bool = False,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> TrendsPayload:
    """Top-level entry point used by `lamill new trends`.

    Fast path:
      1. Read cache; if fresh (≤24h), return.
      2. Else call pytrends, write cache, return.

    L1 stale-cache fallback (2026-05-22):
      3. If pytrends raises `GTrendsRateLimitError`, look for ANY
         cached payload regardless of TTL. If one exists, return it
         (renderer surfaces the stale-age warning). If none, re-raise.

    Raises `GTrendsRateLimitError` when no cache is available to
    fall back to (operator should wait + retry). Raises
    `GTrendsError` (generic) for other pytrends failures (network,
    parse error). `ValueError` when `timeframe` isn't one of
    `TIMEFRAME_MAP`'s keys.
    """
    if timeframe not in TIMEFRAME_MAP:
        raise ValueError(
            f"timeframe={timeframe!r} not in {list(TIMEFRAME_MAP)}"
        )

    if not refresh:
        cached = load_cached(
            topic, timeframe=timeframe, region=region,
            max_age_hours=max_age_hours,
        )
        if cached is not None:
            return cached

    try:
        payload = _fetch_from_pytrends(
            topic,
            timeframe_pytrends=TIMEFRAME_MAP[timeframe],
            region=region,
        )
    except GTrendsRateLimitError:
        # L1 fallback — operator already has this topic cached.
        # Better than failing outright.
        stale = load_any_cached(topic, timeframe=timeframe, region=region)
        if stale is not None:
            return stale
        raise

    save_cached(payload)
    return payload


# ---- latest trends (no-topic surface, 2026-05-22 PM) --------------


def _region_hash(region: str) -> str:
    """Short hash of the operator-facing region code. Used in the
    latest-trends cache filename so multiple regions don't collide."""
    return hashlib.sha256(region.upper().encode("utf-8")).hexdigest()[:12]


def latest_cache_path(region: str) -> Path:
    return GTRENDS_DIR / f"latest_{_region_hash(region)}.json"


def load_cached_latest(
    region: str, *,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> LatestTrendsPayload | None:
    """Return fresh cached latest-trends payload, or None if absent /
    stale / schema-mismatched."""
    path = latest_cache_path(region)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema") != LATEST_SCHEMA:
        return None
    if is_stale(raw, max_age_hours=max_age_hours):
        return None
    return LatestTrendsPayload(
        region=raw["region"],
        fetched_at=raw["fetched_at"],
        trending=list(raw.get("trending") or []),
    )


def load_any_cached_latest(region: str) -> LatestTrendsPayload | None:
    """L1 fallback variant — skips TTL check. Returns whatever's on
    disk for this region, even if days old. Used when pytrends
    rate-limits the latest-trends call."""
    path = latest_cache_path(region)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if raw.get("schema") != LATEST_SCHEMA:
        return None
    return LatestTrendsPayload(
        region=raw["region"],
        fetched_at=raw["fetched_at"],
        trending=list(raw.get("trending") or []),
    )


def save_cached_latest(payload: LatestTrendsPayload) -> Path:
    """Atomic write of a LatestTrendsPayload to its cache file."""
    GTRENDS_DIR.mkdir(parents=True, exist_ok=True)
    path = latest_cache_path(payload.region)
    body = {
        "schema": LATEST_SCHEMA,
        "region": payload.region,
        "fetched_at": payload.fetched_at,
        "trending": payload.trending,
    }
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(body, indent=2), encoding="utf-8")
    tmp.replace(path)
    return path


def latest_payload_age_hours(payload: LatestTrendsPayload) -> float | None:
    """Same shape as `payload_age_hours` but for the latest-trends
    payload type."""
    try:
        ts = datetime.fromisoformat(payload.fetched_at)
    except (ValueError, TypeError):
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - ts
    return delta.total_seconds() / 3600.0


def _fetch_latest_from_pytrends(region: str) -> LatestTrendsPayload:
    """Call pytrends' `trending_searches(pn=...)` to get Google's
    daily trending searches for `region`. Same UA rotation + 429
    detection + ImportError wrap as the topic-specific path.

    `region` is the operator-facing ISO code (e.g., "US"); we map to
    pytrends' full-name region internally via `_DAILY_REGION_MAP`.
    """
    region_iso = region.upper()
    if region_iso not in _DAILY_REGION_MAP:
        raise GTrendsError(
            f"region={region!r} not supported for daily trending searches. "
            f"Supported regions: {', '.join(sorted(_DAILY_REGION_MAP))}. "
            f"(Different from the `--region` codes accepted on the "
            f"topic-specific path — pytrends' `trending_searches` API "
            f"uses a smaller fixed set.)"
        )
    region_pytrends = _DAILY_REGION_MAP[region_iso]

    try:
        client = _make_pytrends_client()
        df = client.trending_searches(pn=region_pytrends)
    except GTrendsError:
        raise   # ImportError wrap propagates cleanly
    except Exception as e:
        msg = str(e)
        if "429" in msg or "Too Many Requests" in msg.lower():
            raise GTrendsRateLimitError(
                f"Google Trends rate-limited (HTTP 429) on daily "
                f"trending fetch for region={region_iso!r}. "
                f"Wait 10-30 minutes and retry; the limit is IP-based."
            ) from e
        raise GTrendsError(
            f"pytrends trending_searches failed for region={region_iso!r}: {e}"
        ) from e

    # `trending_searches` returns a DataFrame with one column (the
    # trending queries). Column name varies by pytrends version — use
    # iloc[:, 0] to be defensive. Convert each to str + strip.
    if df is None or df.empty:
        trending: list[str] = []
    else:
        trending = [str(s).strip() for s in df.iloc[:, 0].tolist()]
        trending = [t for t in trending if t]   # drop empties

    return LatestTrendsPayload(
        region=region_iso,
        fetched_at=datetime.now(timezone.utc).isoformat(),
        trending=trending,
    )


def fetch_latest_trends(
    region: str = DEFAULT_LATEST_REGION, *,
    refresh: bool = False,
    max_age_hours: int = DEFAULT_TTL_HOURS,
) -> LatestTrendsPayload:
    """Top-level entry for the no-topic `lamill new trends` path.

    Mirrors `fetch_trends`'s shape: cache first (24h TTL), then live
    fetch via `_fetch_latest_from_pytrends`. On rate-limit (
    `GTrendsRateLimitError`), L1 fallback to any cached entry
    regardless of staleness.
    """
    region_iso = region.upper()

    if not refresh:
        cached = load_cached_latest(region_iso, max_age_hours=max_age_hours)
        if cached is not None:
            return cached

    try:
        payload = _fetch_latest_from_pytrends(region_iso)
    except GTrendsRateLimitError:
        stale = load_any_cached_latest(region_iso)
        if stale is not None:
            return stale
        raise

    save_cached_latest(payload)
    return payload
