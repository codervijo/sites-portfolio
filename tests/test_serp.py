"""Tests for v8.A — SERP research (AI-only).

Mocks the OpenAI call so tests run offline / deterministically.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from portfolio import serp


# ---------- topic normalization + hashing ----------


def test_normalize_topic_collapses_whitespace_and_lowercases():
    assert serp.normalize_topic("  Home Air  diagnostics ") == "home air diagnostics"


def test_topic_hash_is_deterministic():
    a = serp.topic_hash("home air diagnostics")
    b = serp.topic_hash("home air diagnostics")
    assert a == b
    assert len(a) == 12


def test_topic_hash_normalizes_before_hashing():
    """Different casing + whitespace → same hash."""
    assert serp.topic_hash("Home Air Diagnostics") == serp.topic_hash("home air diagnostics")
    assert serp.topic_hash("  home   air   diagnostics  ") == serp.topic_hash("home air diagnostics")


# ---------- cache IO ----------


@pytest.fixture
def _stub_serp_dir(tmp_path, monkeypatch):
    """Redirect cache to tmp_path so tests don't pollute real data/serp/."""
    monkeypatch.setattr(serp, "SERP_DIR", tmp_path / "serp")
    monkeypatch.setattr(serp, "SERP_INDEX", tmp_path / "serp" / "_index.json")
    return tmp_path / "serp"


def _make_payload(topic: str, age_days: float = 0.0) -> dict:
    fetched_at = (datetime.now(timezone.utc) - timedelta(days=age_days)).isoformat()
    return {
        "topic": topic,
        "topic_normalized": serp.normalize_topic(topic),
        "topic_hash": serp.topic_hash(topic),
        "fetched_at": fetched_at,
        "model": "gpt-4o-mini",
        "knowledge_caveat": "test",
        "analysis": {
            "top_likely_rankers": [{"domain": "x.com", "type": "other",
                                    "intent": "informational"}],
            "content_patterns": ["test pattern"],
            "competitive_signal": {"saturation": "low", "ymyl_flag": False,
                                   "barrier": "test"},
            "suggested_angles": ["test angle"],
            "decision": "ship",
            "reasoning": "test reasoning",
        },
    }


def test_load_cached_returns_none_when_missing(_stub_serp_dir):
    assert serp.load_cached("missing topic") is None


def test_save_then_load_roundtrip(_stub_serp_dir):
    payload = _make_payload("home air")
    serp.save_cache("home air", payload)
    hit = serp.load_cached("home air")
    assert hit is not None
    assert hit.payload["topic"] == "home air"
    assert hit.age_days < 0.1


def test_load_cached_returns_none_when_expired(_stub_serp_dir):
    """A payload older than TTL → cache miss."""
    payload = _make_payload("stale", age_days=31.0)
    serp.save_cache("stale", payload)
    assert serp.load_cached("stale", ttl_days=30) is None


def test_load_cached_within_ttl_returns_hit(_stub_serp_dir):
    payload = _make_payload("fresh", age_days=29.0)
    serp.save_cache("fresh", payload)
    hit = serp.load_cached("fresh", ttl_days=30)
    assert hit is not None
    assert hit.age_days > 28


def test_corrupt_cache_treated_as_miss(_stub_serp_dir):
    """Malformed JSON in the cache file → return None, no exception."""
    serp.SERP_DIR.mkdir(parents=True, exist_ok=True)
    p = serp.cache_path("corrupt")
    p.write_text("{not valid json")
    assert serp.load_cached("corrupt") is None


def test_index_file_maintained(_stub_serp_dir):
    serp.save_cache("topic one", _make_payload("topic one"))
    serp.save_cache("topic two", _make_payload("topic two"))
    index = json.loads(serp.SERP_INDEX.read_text())
    assert serp.topic_hash("topic one") in index
    assert serp.topic_hash("topic two") in index
    assert index[serp.topic_hash("topic one")] == "topic one"


# ---------- prompt construction ----------


def test_build_prompt_returns_system_and_user():
    system, user = serp.build_prompt("home air diagnostics")
    assert "SERP-analysis assistant" in system
    assert "JSON" in system
    assert "home air diagnostics" in user


def test_build_prompt_includes_constrained_vocab():
    system, _ = serp.build_prompt("anything")
    assert "institutional" in system
    assert "publisher-listicle" in system
    assert "ship | mixed | skip" in system
    assert "YMYL" in system


# ---------- response parsing ----------


_VALID_LLM_RESPONSE = json.dumps({
    "top_likely_rankers": [
        {"domain": "epa.gov", "type": "institutional", "intent": "informational"},
        {"domain": "healthline.com", "type": "publisher-listicle", "intent": "commercial"},
    ],
    "content_patterns": ["Top results dominated by big publishers"],
    "competitive_signal": {
        "saturation": "medium-high",
        "ymyl_flag": False,
        "barrier": "institutional players well-resourced",
    },
    "suggested_angles": ["Interactive tool gap"],
    "decision": "mixed",
    "reasoning": "Hard to outrank but tool niche open.",
})


def test_parse_response_valid_payload():
    out = serp.parse_response(_VALID_LLM_RESPONSE)
    assert out["decision"] == "mixed"
    assert out["competitive_signal"]["saturation"] == "medium-high"
    assert len(out["top_likely_rankers"]) == 2


def test_parse_response_strips_markdown_fences():
    """gpt sometimes wraps JSON in ```json ... ``` despite the prompt."""
    fenced = f"```json\n{_VALID_LLM_RESPONSE}\n```"
    out = serp.parse_response(fenced)
    assert out["decision"] == "mixed"


def test_parse_response_coerces_unknown_enum_to_safe_default():
    """Unknown `type` value gets coerced to 'other' rather than crashing."""
    bad = json.dumps({
        "top_likely_rankers": [
            {"domain": "x.com", "type": "made-up-type", "intent": "weird-intent"},
        ],
        "decision": "totally-invalid",
        "competitive_signal": {"saturation": "extreme"},
    })
    out = serp.parse_response(bad)
    assert out["top_likely_rankers"][0]["type"] == "other"
    assert out["top_likely_rankers"][0]["intent"] == "informational"
    assert out["decision"] == "unclear"
    assert out["competitive_signal"]["saturation"] == "medium"


def test_parse_response_raises_on_empty_rankers():
    bad = json.dumps({"top_likely_rankers": [], "decision": "ship"})
    with pytest.raises(serp.ResearchError, match="empty `top_likely_rankers`"):
        serp.parse_response(bad)


def test_parse_response_raises_on_malformed_json():
    with pytest.raises(serp.ResearchError, match="malformed JSON"):
        serp.parse_response("{not actually json")


def test_parse_response_drops_entries_without_domain():
    """Entries missing a domain are silently dropped, but if all are dropped,
    raise (the response is structurally bad)."""
    bad = json.dumps({
        "top_likely_rankers": [{"type": "other"}, {"domain": ""}],
        "decision": "ship",
    })
    with pytest.raises(serp.ResearchError, match="none valid"):
        serp.parse_response(bad)


# ---------- orchestrator (research) ----------


def test_research_returns_cached_when_present(_stub_serp_dir, monkeypatch):
    """A cache hit should short-circuit the OpenAI call."""
    serp.save_cache("cached topic", _make_payload("cached topic"))

    def _explode(*a, **kw):
        pytest.fail("OpenAI should not be called when cache is hit")
    monkeypatch.setattr(serp, "call_openai", _explode)
    monkeypatch.setattr(serp, "_openai_api_key", lambda: "fake-key")

    payload = serp.research("cached topic")
    assert payload["from_cache"] is True
    assert payload["topic"] == "cached topic"


def test_research_skips_cache_with_no_cache_flag(_stub_serp_dir, monkeypatch):
    serp.save_cache("topic", _make_payload("topic"))
    monkeypatch.setattr(serp, "_openai_api_key", lambda: "fake-key")
    monkeypatch.setattr(serp, "call_openai", lambda *a, **kw: _VALID_LLM_RESPONSE)

    payload = serp.research("topic", no_cache=True)
    assert payload["from_cache"] is False
    assert payload["analysis"]["decision"] == "mixed"  # from the stubbed response


def test_research_writes_cache_on_fresh_fetch(_stub_serp_dir, monkeypatch):
    monkeypatch.setattr(serp, "_openai_api_key", lambda: "fake-key")
    monkeypatch.setattr(serp, "call_openai", lambda *a, **kw: _VALID_LLM_RESPONSE)

    serp.research("brand new topic")
    p = serp.cache_path("brand new topic")
    assert p.exists()
    assert json.loads(p.read_text())["analysis"]["decision"] == "mixed"


def test_research_raises_on_empty_topic(_stub_serp_dir):
    with pytest.raises(serp.ResearchError, match="empty"):
        serp.research("")


def test_research_raises_when_no_api_key(_stub_serp_dir, monkeypatch):
    """Missing OPENAI_API_KEY → friendly error pointing at the fix."""
    monkeypatch.setattr(serp, "_openai_api_key",
                        lambda: (_ for _ in ()).throw(
                            serp.ResearchError("OPENAI_API_KEY not set ...")))
    with pytest.raises(serp.ResearchError, match="OPENAI_API_KEY"):
        serp.research("topic", no_cache=True)
