"""Tests for v8.D P1.D — research_v2 orchestrator.

Mocks both the LLM cluster expansion and the SerpAPI fetches so tests
run offline / deterministically.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from portfolio import research_v2


# ---------- fixtures + helpers ----------


_FAKE_CLUSTER_QUERIES = [
    "ev charger installation cost",
    "ev charger install price",
    "how much to install ev charger at home",
    "ev wall charger cost",
    "tesla wall connector installation",
]


def _fake_query_payload(query: str) -> dict:
    """Minimal SerpAPI-shape payload for a query."""
    return {
        "schema": "serp-query-v1",
        "query": query,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "source": "serpapi",
        "organic_results": [
            {"position": 1, "domain": "energy.gov", "url": "https://energy.gov/x",
             "title": f"Cost guide for {query}", "snippet": "...", "displayed_link": ""},
            {"position": 2, "domain": "reddit.com", "url": "https://reddit.com/r/x",
             "title": "Reddit discussion", "snippet": "...", "displayed_link": ""},
        ],
        "features": {
            "ai_overview": {"present": True, "cited_domains": ["energy.gov"]},
            "people_also_ask": ["?"],
            "featured_snippet": {"present": False},
            "image_pack": {"present": False},
            "video_pack": {"present": False},
            "local_pack": {"present": False},
            "reddit_card": {"present": True, "position": 2},
        },
    }


@pytest.fixture
def _stub_dir(tmp_path, monkeypatch):
    """Point all SERP caches at tmp_path."""
    from portfolio import serp_query_cache as cache_mod
    monkeypatch.setattr(cache_mod, "SERP_DIR", tmp_path / "serp")
    monkeypatch.setattr(research_v2, "SERP_DIR", tmp_path / "serp")
    return tmp_path / "serp"


def _stub_llm(monkeypatch, queries=_FAKE_CLUSTER_QUERIES):
    """Replace the LLM cluster-expansion call with a fixed result."""
    from portfolio import serp as serp_v1
    monkeypatch.setattr(serp_v1, "_openai_api_key", lambda: "fake-llm-key")
    monkeypatch.setattr(serp_v1, "call_openai", lambda *a, **kw: "ignored")
    monkeypatch.setattr(serp_v1, "parse_cluster_response",
                        lambda raw: {"cluster_queries": list(queries)})


def _stub_serpapi(monkeypatch, raise_on_query=None):
    """Replace fetch_serp() with a deterministic mock. If raise_on_query
    is provided, that one query raises SerpFetchError (others succeed)."""
    from portfolio import research_v2 as r2
    from portfolio.serp_fetch import SerpFetchError
    def _fake(query, *, api_key, depth=10):
        if raise_on_query and query == raise_on_query:
            raise SerpFetchError(f"simulated failure for {query!r}")
        return _fake_query_payload(query)
    monkeypatch.setattr(r2, "fetch_serp", _fake)


# ---------- happy path ----------


def test_returns_v2_cluster_snapshot(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    payload = research_v2.run_research_v2("ev charger cost", api_key="fake")
    assert payload["schema"] == "research-cluster-v2"
    assert payload["topic"] == "ev charger cost"
    assert payload["source"] == "serpapi"
    assert len(payload["cluster_queries"]) == 5
    assert len(payload["per_query_results"]) == 5
    assert payload["from_cache"] is False


def test_per_query_files_list_uses_today_date(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    payload = research_v2.run_research_v2("ev charger", api_key="fake")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    for path in payload["per_query_files"]:
        assert path.startswith(today + "/")


def test_cluster_snapshot_written_to_disk(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    research_v2.run_research_v2("ev charger", api_key="fake")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    clusters_dir = _stub_dir / today / "clusters"
    assert clusters_dir.exists()
    files = list(clusters_dir.glob("*.json"))
    assert len(files) == 1


def test_per_query_results_cached_individually(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    research_v2.run_research_v2("ev charger", api_key="fake")
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    # 5 cluster queries → 5 per-query cache files
    query_files = list((_stub_dir / today).glob("*.json"))
    assert len(query_files) == 5


# ---------- caching ----------


def test_cluster_cache_hit_short_circuits(_stub_dir, monkeypatch):
    """Second call with same topic returns from cluster cache without
    calling LLM or SerpAPI."""
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    # First call seeds cache
    research_v2.run_research_v2("ev charger", api_key="fake")

    # Make the LLM + SerpAPI explode if called
    def _explode_llm(*a, **kw):
        pytest.fail("LLM should not be called on cluster cache hit")
    def _explode_serp(*a, **kw):
        pytest.fail("SerpAPI should not be called on cluster cache hit")
    from portfolio import serp as serp_v1, research_v2 as r2
    monkeypatch.setattr(serp_v1, "call_openai", _explode_llm)
    monkeypatch.setattr(r2, "fetch_serp", _explode_serp)

    payload = research_v2.run_research_v2("ev charger", api_key="fake")
    assert payload["from_cache"] is True


def test_no_cache_bypasses_cluster_cache(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    research_v2.run_research_v2("ev charger", api_key="fake")
    # `--no-cache` should re-call LLM + SerpAPI
    payload = research_v2.run_research_v2("ev charger", api_key="fake", no_cache=True)
    assert payload["from_cache"] is False


def test_per_query_cache_reused_across_topics(_stub_dir, monkeypatch):
    """Two cluster runs that share a query string → SerpAPI hit only once
    for that query (per-query cache reused)."""
    # First run: cluster A
    _stub_llm(monkeypatch, queries=["shared query", "topic A unique"])
    call_count = {"n": 0}
    def _counting_fake(query, *, api_key, depth=10):
        call_count["n"] += 1
        return _fake_query_payload(query)
    from portfolio import research_v2 as r2
    monkeypatch.setattr(r2, "fetch_serp", _counting_fake)
    research_v2.run_research_v2("topic A", api_key="fake")
    after_a = call_count["n"]
    assert after_a == 2

    # Second run: cluster B includes the same "shared query"
    _stub_llm(monkeypatch, queries=["shared query", "topic B unique"])
    research_v2.run_research_v2("topic B", api_key="fake")
    after_b = call_count["n"]
    # SerpAPI called only for the new query in B, "shared query" came from cache
    assert after_b - after_a == 1


# ---------- partial-failure resilience ----------


def test_some_query_fetches_fail_still_returns_partial(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch, raise_on_query="ev charger install price")
    payload = research_v2.run_research_v2("ev charger", api_key="fake")
    # 4 of 5 queries succeeded
    assert len(payload["per_query_results"]) == 4
    assert len(payload["fetch_errors"]) == 1
    assert "ev charger install price" in payload["fetch_errors"][0]


def test_all_fetches_fail_raises(_stub_dir, monkeypatch):
    _stub_llm(monkeypatch)
    from portfolio.serp_fetch import SerpFetchError
    from portfolio import research_v2 as r2
    def _always_fail(*a, **kw):
        raise SerpFetchError("simulated")
    monkeypatch.setattr(r2, "fetch_serp", _always_fail)
    with pytest.raises(research_v2.ResearchV2Error, match="all"):
        research_v2.run_research_v2("topic", api_key="fake")


# ---------- input validation ----------


def test_empty_topic_raises(_stub_dir):
    with pytest.raises(research_v2.ResearchV2Error, match="empty"):
        research_v2.run_research_v2("", api_key="fake")


def test_topic_normalization_consistent_with_query_cache():
    """research_v2's topic_hash uses the same normalization as
    serp_query_cache's query_hash for stable cross-module hashing."""
    from portfolio import serp_query_cache as cache
    # Both should hash "Ev Charger Cost" same as "ev charger cost"
    h1 = research_v2.cluster_hash("Ev Charger Cost")
    h2 = research_v2.cluster_hash("ev charger cost")
    h3 = cache.query_hash("Ev Charger Cost")
    h4 = cache.query_hash("ev charger cost")
    assert h1 == h2
    assert h3 == h4


# ---------- LLM cluster-expansion fallback ----------


def test_empty_llm_cluster_falls_back_to_literal_topic(_stub_dir, monkeypatch):
    """If LLM returns empty cluster_queries (e.g. nonsense topic),
    fall back to the literal topic as a single-element cluster."""
    _stub_llm(monkeypatch, queries=[])
    _stub_serpapi(monkeypatch)
    payload = research_v2.run_research_v2("nonsense topic", api_key="fake")
    assert payload["cluster_queries"] == ["nonsense topic"]


def test_cluster_capped_at_5_queries(_stub_dir, monkeypatch):
    """LLM returning 8 queries → only 5 are used (free-tier quota friendly)."""
    big_cluster = [f"q{i}" for i in range(8)]
    _stub_llm(monkeypatch, queries=big_cluster)
    _stub_serpapi(monkeypatch)
    payload = research_v2.run_research_v2("topic", api_key="fake")
    assert len(payload["cluster_queries"]) == 5


# ---------- P2.F — schema gate on cluster cache ----------


def test_cluster_schema_mismatch_is_cache_miss(_stub_dir, monkeypatch):
    """A cached cluster with a non-v2 schema field is treated as a miss
    and triggers a fresh fetch (PRD P2.7 — old v8.B caches archived,
    new schema bumps force re-fetch)."""
    import json
    from datetime import datetime, timezone

    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    # Seed a stale-schema snapshot on disk.
    topic = "ev charger"
    p = research_v2.cluster_cache_path(topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "schema": "v8.B-legacy",
        "topic": topic,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cluster_queries": ["stale"],
        "per_query_results": [],
    }))
    # Run — should fall through to fresh fetch (cluster_queries come
    # from the stubbed LLM, not the stale file).
    payload = research_v2.run_research_v2(topic, api_key="fake")
    assert payload["schema"] == research_v2.CLUSTER_SCHEMA
    assert payload["cluster_queries"] != ["stale"]
    assert payload["from_cache"] is False


def test_cluster_schema_missing_is_cache_miss(_stub_dir, monkeypatch):
    """A cached file with NO schema field is also treated as a miss."""
    import json
    from datetime import datetime, timezone

    _stub_llm(monkeypatch)
    _stub_serpapi(monkeypatch)
    topic = "ev charger"
    p = research_v2.cluster_cache_path(topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "topic": topic,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "cluster_queries": ["stale"],
    }))
    payload = research_v2.run_research_v2(topic, api_key="fake")
    assert payload["from_cache"] is False


def test_save_cluster_snapshot_is_public():
    """The renamed-to-public save helper is importable + callable.
    CLI uses this to persist gates back into the snapshot after Phase 2."""
    from portfolio.research_v2 import save_cluster_snapshot, _save_cluster_snapshot
    assert save_cluster_snapshot is _save_cluster_snapshot  # alias intact


def test_save_cluster_snapshot_writes_atomically(_stub_dir):
    """Atomic write: tmp file is renamed in place; no half-written file."""
    snapshot = {
        "schema": research_v2.CLUSTER_SCHEMA,
        "topic": "x", "cluster_queries": [], "per_query_results": [],
    }
    p = research_v2.save_cluster_snapshot("x", snapshot)
    assert p.exists()
    import json
    loaded = json.loads(p.read_text())
    assert loaded["topic"] == "x"
    # No leftover tmp file in the directory
    tmps = list(p.parent.glob("*.tmp"))
    assert tmps == []
