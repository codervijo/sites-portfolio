"""v8.D P1.D — research orchestrator with real SERP data.

The Phase 1 endpoint. `run_research_v2(topic)`:
  1. LLM expands topic into a 5-query cluster (reuses v8.B's cluster
     prompt — that part wasn't broken)
  2. For each query, fetches SerpAPI top-10 + features (with caching
     per `serp_query_cache`)
  3. Returns a cluster snapshot in the `research-cluster-v2` shape

What this does NOT do:
  - Three-gate decision logic (Phase 2)
  - Operator-profile filtering (Phase 3)
  - LLM interpretation (Phase 4)
  - Quota tracking + auto-fallback (P1.F)
  - Synthesis-only fallback wiring (P1.E)

Those land in subsequent commits. P1.D's job is "real SERP data
flows end-to-end into a cached, well-shaped snapshot."

The cluster snapshot shape returned here is intentionally
forward-compatible: gates / operator_fit / verdict / etc. live in
the same schema but are absent until Phase 2 populates them.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from .data import ROOT
from .serp_fetch import SerpFetchError, fetch_serp
from .serp_query_cache import (
    SERP_DIR,
    load_cached_query,
    normalize_query,
    query_hash,
    save_cached_query,
)
from .serpapi_quota import QuotaExhausted
from . import serp as serp_v1  # for cluster-query LLM expansion (reused)

CLUSTER_TTL_DAYS = 30
CLUSTER_SCHEMA = "research-cluster-v2"
DEFAULT_DEPTH = 10


class ResearchV2Error(RuntimeError):
    """Raised on v2 research-pipeline failures. Caller maps to exit codes."""


class ResearchV2QuotaExhausted(ResearchV2Error):
    """Specific subclass — CLI catches this and auto-falls back to
    synthesis-only mode with a loud banner per §8.G.3."""


def cluster_hash(topic: str) -> str:
    """12-char sha256 of normalized topic. Used to key the cluster-level
    snapshot file (a topic's cluster expansion + per-query references)."""
    return hashlib.sha256(normalize_query(topic).encode("utf-8")).hexdigest()[:12]


def cluster_cache_path(topic: str, date: str | None = None) -> Path:
    """File path for one (topic, date) cluster snapshot. Default: today UTC."""
    if date is None:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return SERP_DIR / date / "clusters" / f"{cluster_hash(topic)}.json"


def run_research_v2(topic: str, *, api_key: str, no_cache: bool = False,
                    depth: int = DEFAULT_DEPTH) -> dict:
    """Run the full P1.D pipeline. Returns a `research-cluster-v2`
    snapshot. Hits cluster cache first (if not `no_cache`); otherwise
    generates cluster queries via LLM, fetches each via SerpAPI
    (with per-query caching), assembles and stores the snapshot.

    Raises ResearchV2Error on:
      - empty topic
      - LLM cluster expansion failure
      - all per-query fetches failed (no partial data worth saving)
    """
    if not topic or not topic.strip():
        raise ResearchV2Error("topic cannot be empty")
    topic = topic.strip()

    if not no_cache:
        cached = _load_cached_cluster(topic)
        if cached is not None:
            cached["from_cache"] = True
            return cached

    # Step 1: LLM cluster expansion (reuses the existing v8.B function)
    try:
        cluster_queries = _expand_topic_to_cluster(topic)
    except Exception as e:
        raise ResearchV2Error(f"cluster expansion failed: {e}") from e

    # Step 2: SerpAPI fetch per query (with per-query caching)
    per_query: list[dict] = []
    fetch_errors: list[str] = []
    for q in cluster_queries:
        try:
            payload = _fetch_or_cache(q, api_key=api_key, depth=depth)
            per_query.append(payload)
        except QuotaExhausted as e:
            # Quota's hit — refuse to limp along on partial data. Raise
            # the specific subclass so the CLI catches it and falls back
            # cleanly to synthesis-only mode (§8.G.3).
            raise ResearchV2QuotaExhausted(str(e)) from e
        except SerpFetchError as e:
            fetch_errors.append(f"{q!r}: {e}")
            # Continue — partial data is still useful. Phase 2 will
            # handle "some queries had no data" in gate logic.

    if not per_query:
        raise ResearchV2Error(
            f"all {len(cluster_queries)} SerpAPI fetches failed: "
            + "; ".join(fetch_errors[:3])
        )

    # Step 3: assemble cluster snapshot
    snapshot = _build_cluster_snapshot(
        topic=topic,
        cluster_queries=cluster_queries,
        per_query=per_query,
        fetch_errors=fetch_errors,
    )

    _save_cluster_snapshot(topic, snapshot)
    return snapshot


def _expand_topic_to_cluster(topic: str) -> list[str]:
    """Use the existing v8.B cluster-prompt LLM call to produce 3-5
    related queries. Reuses the LLM HTTP wrapper from serp.py — no
    point in duplicating it during this phase.

    Falls back to a single-element [topic] list if the LLM response is
    unparseable (rare; the prompt is constrained).
    """
    api_key = serp_v1._openai_api_key()
    system, user = serp_v1.build_cluster_prompt(topic)
    raw = serp_v1.call_openai(system, user, api_key=api_key)
    parsed = serp_v1.parse_cluster_response(raw)
    queries = parsed.get("cluster_queries", [])
    if not queries:
        # LLM returned no cluster (e.g. nonsense topic). Phase 2's
        # unclear-verdict logic handles this — for now treat as the
        # single literal topic.
        return [topic]
    return queries[:5]  # cap at 5 to bound SerpAPI quota use


def _fetch_or_cache(query: str, *, api_key: str, depth: int) -> dict:
    """Return cached SerpAPI payload if present + within TTL; else
    fetch fresh and save to cache."""
    cached = load_cached_query(query)
    if cached is not None:
        return cached
    payload = fetch_serp(query, api_key=api_key, depth=depth)
    save_cached_query(query, payload)
    return payload


def _build_cluster_snapshot(*, topic: str, cluster_queries: list[str],
                            per_query: list[dict],
                            fetch_errors: list[str]) -> dict:
    """Assemble the cluster snapshot from cluster queries + per-query
    SerpAPI results. Forward-compatible — gates / verdict / operator_fit
    fields are left absent for Phase 2 to populate."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return {
        "schema": CLUSTER_SCHEMA,
        "topic": topic,
        "topic_normalized": normalize_query(topic),
        "topic_hash": cluster_hash(topic),
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "serpapi",
        "cluster_queries": cluster_queries,
        "per_query_files": [
            f"{today}/{query_hash(q)}.json" for q in cluster_queries
        ],
        "per_query_results": per_query,   # inlined for now; Phase 2 may move out
        "fetch_errors": fetch_errors,
        "from_cache": False,
    }


def _save_cluster_snapshot(topic: str, snapshot: dict) -> Path:
    """Atomic write to data/serp/<today>/clusters/<topic-hash>.json."""
    p = cluster_cache_path(topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(snapshot, indent=2) + "\n")
    tmp.replace(p)
    return p


def _load_cached_cluster(topic: str) -> dict | None:
    """Walk date subdirs newest-first looking for a cluster snapshot
    for this topic that's within TTL. Same pattern as
    `load_cached_query()`."""
    from datetime import timedelta
    if not SERP_DIR.exists():
        return None
    target_hash = cluster_hash(topic)
    cutoff = datetime.now(timezone.utc) - timedelta(days=CLUSTER_TTL_DAYS)

    date_dirs = sorted(
        (p for p in SERP_DIR.iterdir()
         if p.is_dir() and _is_date_subdir(p.name)),
        reverse=True,
    )
    for d in date_dirs:
        cf = d / "clusters" / f"{target_hash}.json"
        if not cf.exists():
            continue
        try:
            payload = json.loads(cf.read_text())
        except (OSError, ValueError):
            continue
        fetched_iso = payload.get("fetched_at")
        if not fetched_iso:
            continue
        try:
            fetched_at = datetime.fromisoformat(fetched_iso.replace("Z", "+00:00"))
        except ValueError:
            continue
        if fetched_at < cutoff:
            return None
        return payload
    return None


def _is_date_subdir(name: str) -> bool:
    """Local copy of the same check from serp_query_cache to avoid
    a circular import."""
    if len(name) != 10 or name[4] != "-" or name[7] != "-":
        return False
    try:
        datetime.strptime(name, "%Y-%m-%d")
        return True
    except ValueError:
        return False
