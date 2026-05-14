"""v8.D P1.B — SerpAPI fetcher with normalized response shape.

Hits SerpAPI's `/search` endpoint for one query and normalizes the
result into the schema documented in research-module-v2.md §P1.2.

This module owns the HTTP + parsing layer ONLY. Caching, quota
tracking, and synthesis-only fallback live in their own modules
(P1.C / P1.F / P1.E respectively) so this one stays a pure adapter.

SerpAPI's response shape is rich but varies by query — different
SERPs have different feature combinations, optional fields appear
inconsistently. The normalizer flattens to a stable shape so
downstream gate-classification code doesn't have to defensively
check every key path.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx

SERPAPI_URL = "https://serpapi.com/search"
SERPAPI_TIMEOUT = 30.0     # SerpAPI can take 10-20s on cold queries
RETRY_BACKOFF_S = 2.0      # one retry on transient failures


class SerpFetchError(RuntimeError):
    """Raised on non-recoverable SerpAPI failures. Caller maps to
    fallback behavior (synthesis-only mode per P1.E)."""


def fetch_serp(query: str, *, api_key: str,
               depth: int = 10) -> dict:
    """Fetch one query's top-N organic + SERP features. Returns the
    normalized shape per docs/prd/research-module-v2.md §P1.2.

    Raises:
      SerpFetchError: HTTP error, malformed response, missing key.
      QuotaExhausted: SerpAPI quota for this UTC month is used up.

    Retries once on transient (5xx, network) failures before raising.
    Consumes one quota unit on success (failed calls don't count).
    """
    if not api_key:
        raise SerpFetchError("SERPAPI_KEY not provided")
    if not query or not query.strip():
        raise SerpFetchError("query cannot be empty")

    # Pre-flight quota check — refuses cleanly if we have no headroom,
    # without burning an HTTP call we can't pay for.
    from .serpapi_quota import is_quota_available, consume_quota, QuotaExhausted
    if not is_quota_available():
        raise QuotaExhausted(
            "SerpAPI free-tier quota exhausted for this UTC month. "
            "Caller should fall back to synthesis-only mode."
        )

    params = {
        "engine": "google",
        "q": query,
        "num": depth,
        "api_key": api_key,
    }

    raw = _call_with_retry(params)
    consume_quota()   # only counts successful fetches
    return _normalize(query, raw)


def _call_with_retry(params: dict) -> dict:
    """One retry on 5xx / network errors. 4xx errors don't retry."""
    last_err: str | None = None
    for attempt in range(2):
        try:
            r = httpx.get(SERPAPI_URL, params=params, timeout=SERPAPI_TIMEOUT)
        except httpx.HTTPError as e:
            last_err = f"{type(e).__name__}: {e}"
            if attempt == 0:
                time.sleep(RETRY_BACKOFF_S)
                continue
            raise SerpFetchError(f"network error after retry: {last_err}") from e

        if r.status_code == 200:
            try:
                return r.json()
            except ValueError as e:
                raise SerpFetchError(f"SerpAPI returned non-JSON: {e}") from e

        if r.status_code == 401:
            raise SerpFetchError(
                "SerpAPI 401 unauthorized — check SERPAPI_KEY in portfolio.env"
            )
        if r.status_code == 429:
            # 429 = rate limit. SerpAPI returns this when the quota's
            # exhausted; caller handles fallback per P1.F.
            raise SerpFetchError("SerpAPI 429 — quota exhausted or rate limited")

        if 500 <= r.status_code < 600 and attempt == 0:
            last_err = f"http {r.status_code}: {r.text[:200]}"
            time.sleep(RETRY_BACKOFF_S)
            continue

        raise SerpFetchError(f"SerpAPI http {r.status_code}: {r.text[:200]}")

    raise SerpFetchError(f"unreachable retry-loop exit: {last_err}")


def _normalize(query: str, raw: dict) -> dict:
    """Flatten SerpAPI's response into the stable schema from
    research-module-v2.md §P1.2.

    Defensive about missing keys; SerpAPI omits feature sections when
    the SERP doesn't have them rather than returning empty objects.
    """
    organic_results = []
    for i, item in enumerate(raw.get("organic_results", []), start=1):
        url = item.get("link", "")
        organic_results.append({
            "position": item.get("position", i),
            "domain": _domain_of(url),
            "url": url,
            "title": item.get("title", ""),
            "snippet": item.get("snippet", ""),
            "displayed_link": item.get("displayed_link", ""),
        })

    features = _normalize_features(raw, organic_results)

    return {
        "schema": "serp-query-v1",
        "query": query,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "serpapi",
        "organic_results": organic_results,
        "features": features,
    }


def _normalize_features(raw: dict, organic_results: list[dict]) -> dict:
    """Extract SERP features in the stable shape. Most fields are
    `{"present": bool, ...optional metadata}` so downstream code can
    do `features["ai_overview"]["present"]` without key-checking."""

    # AI Overview — SerpAPI surfaces this as `ai_overview` with
    # `text_blocks` containing cited references.
    ai = raw.get("ai_overview") or {}
    ai_overview = {"present": bool(ai)}
    if ai:
        refs = ai.get("references", [])
        ai_overview["cited_domains"] = sorted({
            _domain_of(r.get("link", "")) for r in refs if r.get("link")
        })

    # People Also Ask — `related_questions` array of {question, snippet}.
    paa = raw.get("related_questions", [])
    people_also_ask = [q.get("question", "") for q in paa if q.get("question")]

    # Featured snippet — SerpAPI uses `answer_box`.
    answer_box = raw.get("answer_box") or {}
    featured_snippet = {
        "present": bool(answer_box),
    }
    if answer_box:
        featured_snippet["source_domain"] = _domain_of(answer_box.get("link", ""))

    # Image pack — `inline_images` or `images_results` (varies).
    image_pack = {
        "present": bool(raw.get("inline_images") or raw.get("images_results"))
    }

    # Video pack — `inline_videos`.
    video_pack = {"present": bool(raw.get("inline_videos"))}

    # Local pack — `local_results`.
    local_pack = {"present": bool(raw.get("local_results"))}

    # Reddit card — heuristic: if any organic result's domain is
    # reddit.com OR a sub-domain, mark present with its position.
    reddit_card = {"present": False}
    for r in organic_results:
        if r["domain"].endswith("reddit.com"):
            reddit_card = {"present": True, "position": r["position"]}
            break

    return {
        "ai_overview": ai_overview,
        "people_also_ask": people_also_ask,
        "featured_snippet": featured_snippet,
        "image_pack": image_pack,
        "video_pack": video_pack,
        "local_pack": local_pack,
        "reddit_card": reddit_card,
    }


def _domain_of(url: str) -> str:
    """Extract bare domain from a URL. Strips `www.` for consistency."""
    if not url:
        return ""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host
