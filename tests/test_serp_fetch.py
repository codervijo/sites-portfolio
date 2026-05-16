"""Tests for v8.D — SerpAPI fetcher (`portfolio.serp_fetch`).

Mocks SerpAPI HTTP responses so tests run offline.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx
import pytest

from portfolio import serp_fetch


# ---------- a representative SerpAPI response fixture ----------


_TYPICAL_RESPONSE = {
    "organic_results": [
        {
            "position": 1,
            "title": "EV Charger Installation Cost: 2024 Guide",
            "link": "https://www.notateslaapp.com/2024/ev-charger-cost/",
            "snippet": "Average cost for home charger install...",
            "displayed_link": "notateslaapp.com › 2024 › ev-charger-cost",
        },
        {
            "position": 2,
            "title": "How Much Does an EV Charger Cost?",
            "link": "https://www.energy.gov/eere/ev-charger-cost",
            "snippet": "Federal rebates available...",
            "displayed_link": "energy.gov",
        },
        {
            "position": 3,
            "title": "Anyone install Tesla wall connector themselves?",
            "link": "https://www.reddit.com/r/electricvehicles/comments/abc/",
            "snippet": "Got mine installed for $400 by an electrician...",
            "displayed_link": "reddit.com › r › electricvehicles",
        },
    ],
    "ai_overview": {
        "text_blocks": ["EV charger installation typically costs..."],
        "references": [
            {"link": "https://www.energy.gov/eere/foo", "title": "Energy.gov"},
            {"link": "https://www.notateslaapp.com/foo", "title": "Not a Tesla App"},
        ],
    },
    "related_questions": [
        {"question": "How much does a Tesla wall connector cost?"},
        {"question": "Can I install an EV charger myself?"},
        {"question": "What's the cost of a Level 2 charger?"},
    ],
    "answer_box": {
        "type": "organic_result",
        "title": "Average cost: $1,200-$2,500",
        "link": "https://www.energy.gov/eere/ev-charger-cost",
    },
    "inline_images": [{"thumbnail": "..."}],
}


def _stub_serpapi(monkeypatch, response_data=_TYPICAL_RESPONSE,
                  status_code=200, raise_exc=None):
    """Helper: replace httpx.get with a canned response."""
    class _Resp:
        def __init__(self):
            self.status_code = status_code
            self.text = json.dumps(response_data) if response_data else ""
        def json(self):
            if response_data is None:
                raise ValueError("not json")
            return response_data
    def _get(*args, **kwargs):
        if raise_exc:
            raise raise_exc
        return _Resp()
    monkeypatch.setattr(serp_fetch.httpx, "get", _get)


# ---------- happy path ----------


def test_fetch_returns_normalized_shape(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("ev charger cost", api_key="fake")

    assert result["schema"] == "serp-query-v1"
    assert result["query"] == "ev charger cost"
    assert result["source"] == "serpapi"
    assert "fetched_at" in result
    # fetched_at is ISO-8601 with UTC offset
    parsed = datetime.fromisoformat(result["fetched_at"])
    assert parsed.tzinfo is not None


def test_organic_results_have_required_fields(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("ev charger cost", api_key="fake")

    assert len(result["organic_results"]) == 3
    first = result["organic_results"][0]
    assert first["position"] == 1
    assert first["domain"] == "notateslaapp.com"
    assert first["url"].startswith("https://www.notateslaapp.com/")
    assert "title" in first
    assert "snippet" in first


def test_domain_strips_www_prefix(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    for r in result["organic_results"]:
        assert not r["domain"].startswith("www.")


# ---------- SERP features ----------


def test_ai_overview_detected_with_cited_domains(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("ev charger cost", api_key="fake")
    ai = result["features"]["ai_overview"]
    assert ai["present"] is True
    assert "energy.gov" in ai["cited_domains"]
    assert "notateslaapp.com" in ai["cited_domains"]


def test_ai_overview_absent_when_not_in_response(monkeypatch):
    no_ai = {k: v for k, v in _TYPICAL_RESPONSE.items() if k != "ai_overview"}
    _stub_serpapi(monkeypatch, response_data=no_ai)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert result["features"]["ai_overview"]["present"] is False


def test_people_also_ask_extracted(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    paa = result["features"]["people_also_ask"]
    assert len(paa) == 3
    assert "How much does a Tesla wall connector cost?" in paa


def test_featured_snippet_present_with_source(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    fs = result["features"]["featured_snippet"]
    assert fs["present"] is True
    assert fs["source_domain"] == "energy.gov"


def test_reddit_card_detected(monkeypatch):
    """When reddit.com appears in organic, reddit_card is present."""
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    reddit = result["features"]["reddit_card"]
    assert reddit["present"] is True
    assert reddit["position"] == 3


def test_reddit_card_absent_when_no_reddit(monkeypatch):
    no_reddit = {**_TYPICAL_RESPONSE, "organic_results":
                 [r for r in _TYPICAL_RESPONSE["organic_results"]
                  if "reddit.com" not in r["link"]]}
    _stub_serpapi(monkeypatch, response_data=no_reddit)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert result["features"]["reddit_card"]["present"] is False


def test_image_pack_detected(monkeypatch):
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert result["features"]["image_pack"]["present"] is True


def test_local_pack_absent(monkeypatch):
    """The fixture doesn't include local_results."""
    _stub_serpapi(monkeypatch)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert result["features"]["local_pack"]["present"] is False


# ---------- error paths ----------


def test_missing_api_key_raises(monkeypatch):
    with pytest.raises(serp_fetch.SerpFetchError, match="SERPAPI_KEY not provided"):
        serp_fetch.fetch_serp("test", api_key="")


def test_empty_query_raises(monkeypatch):
    with pytest.raises(serp_fetch.SerpFetchError, match="query cannot be empty"):
        serp_fetch.fetch_serp("", api_key="fake")


def test_401_unauthorized_raises_clear_message(monkeypatch):
    _stub_serpapi(monkeypatch, status_code=401)
    with pytest.raises(serp_fetch.SerpFetchError, match="unauthorized"):
        serp_fetch.fetch_serp("test", api_key="bad-key")


def test_429_quota_exhausted_raises_for_fallback(monkeypatch):
    """The quota-fallback path (in `serpapi_quota`) keys on this error message."""
    _stub_serpapi(monkeypatch, status_code=429)
    with pytest.raises(serp_fetch.SerpFetchError, match="429"):
        serp_fetch.fetch_serp("test", api_key="fake")


def test_network_error_retries_then_raises(monkeypatch):
    """Two consecutive ConnectErrors → final error after retry."""
    call_count = {"n": 0}
    def _flaky_get(*args, **kwargs):
        call_count["n"] += 1
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(serp_fetch.httpx, "get", _flaky_get)
    # Speed up the test — skip the sleep
    monkeypatch.setattr(serp_fetch.time, "sleep", lambda _: None)

    with pytest.raises(serp_fetch.SerpFetchError, match="network error"):
        serp_fetch.fetch_serp("test", api_key="fake")
    assert call_count["n"] == 2  # initial + 1 retry


def test_5xx_retries_then_succeeds(monkeypatch):
    """One 500 followed by 200 → succeeds via retry."""
    call_count = {"n": 0}
    class _Resp:
        def __init__(self, status, body):
            self.status_code = status
            self.text = body
            self._body = body
        def json(self):
            return json.loads(self._body)
    def _flaky_get(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return _Resp(500, "server error")
        return _Resp(200, json.dumps(_TYPICAL_RESPONSE))
    monkeypatch.setattr(serp_fetch.httpx, "get", _flaky_get)
    monkeypatch.setattr(serp_fetch.time, "sleep", lambda _: None)

    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert call_count["n"] == 2
    assert result["query"] == "test"


def test_other_4xx_raises_without_retry(monkeypatch):
    call_count = {"n": 0}
    class _Resp:
        status_code = 403
        text = "forbidden"
    def _get(*args, **kwargs):
        call_count["n"] += 1
        return _Resp()
    monkeypatch.setattr(serp_fetch.httpx, "get", _get)

    with pytest.raises(serp_fetch.SerpFetchError, match="403"):
        serp_fetch.fetch_serp("test", api_key="fake")
    assert call_count["n"] == 1  # no retry for non-5xx, non-429


def test_malformed_json_response_raises(monkeypatch):
    _stub_serpapi(monkeypatch, response_data=None, status_code=200)
    with pytest.raises(serp_fetch.SerpFetchError, match="non-JSON"):
        serp_fetch.fetch_serp("test", api_key="fake")


# ---------- normalizer corner cases ----------


def test_empty_organic_results(monkeypatch):
    empty = {"organic_results": []}
    _stub_serpapi(monkeypatch, response_data=empty)
    result = serp_fetch.fetch_serp("test", api_key="fake")
    assert result["organic_results"] == []
    assert result["features"]["reddit_card"]["present"] is False


def test_domain_of_handles_malformed_url():
    assert serp_fetch._domain_of("") == ""
    assert serp_fetch._domain_of("not-a-url") == ""
    assert serp_fetch._domain_of("https://example.com/path") == "example.com"
    assert serp_fetch._domain_of("https://www.example.com/") == "example.com"
