"""Tests for 2026-05-24 retry-with-backoff in `serp.call_openai`.

Operator-hit bug: a transient OpenAI HTTP 500 mid-`lamill new validate`
surfaced as a hard "cluster expansion failed" instead of a self-
recovering retry. Adding retry-with-backoff for 5xx + 429 (transient)
while preserving immediate-raise for 4xx (permanent).

Mocks `requests.post` via monkeypatch and injects `_sleep` so the
backoff loop runs instantly.
"""
from __future__ import annotations

import pytest

from portfolio import serp
from portfolio.serp import ResearchError, call_openai


class _MockResponse:
    def __init__(self, status_code: int, text: str = "", json_data: dict | None = None):
        self.status_code = status_code
        self.text = text
        self._json = json_data

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def test_call_openai_success_first_try_no_retry(monkeypatch):
    """Happy path — single POST returns 200; no sleeps."""
    sleeps: list[float] = []
    posts: list[dict] = []

    def _post(url, headers, json, timeout):
        posts.append({"url": url})
        return _MockResponse(
            200, json_data={"output_text": "the response"},
        )
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    out = call_openai("sys", "user", api_key="k",
                     _sleep=lambda s: sleeps.append(s))
    assert out == "the response"
    assert len(posts) == 1
    assert sleeps == []


def test_call_openai_retries_on_500_then_succeeds(monkeypatch):
    """500 on first attempt → backoff → 200 on second. One sleep."""
    sleeps: list[float] = []
    responses = iter([
        _MockResponse(500, text='{"error":{"message":"upstream"}}'),
        _MockResponse(200, json_data={"output_text": "recovered"}),
    ])

    def _post(*a, **kw):
        return next(responses)
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    out = call_openai("sys", "user", api_key="k",
                     _sleep=lambda s: sleeps.append(s))
    assert out == "recovered"
    # Backoff intervals: (1.0, 2.0, 4.0, 8.0). First sleep is 1.0s.
    assert sleeps == [serp._OPENAI_RETRY_INTERVALS_S[0]]


def test_call_openai_retries_on_429_rate_limit(monkeypatch):
    """429 is treated as transient (rate-limited) → backoff + retry."""
    sleeps: list[float] = []
    responses = iter([
        _MockResponse(429, text="rate limited"),
        _MockResponse(200, json_data={"output_text": "ok"}),
    ])

    monkeypatch.setattr(
        "portfolio.serp.requests.post",
        lambda *a, **kw: next(responses),
    )

    out = call_openai("sys", "user", api_key="k",
                     _sleep=lambda s: sleeps.append(s))
    assert out == "ok"
    assert sleeps == [serp._OPENAI_RETRY_INTERVALS_S[0]]


def test_call_openai_raises_immediately_on_401(monkeypatch):
    """401 is permanent (bad API key) — must raise on first attempt, no
    retries (don't waste backoff budget on auth failures)."""
    sleeps: list[float] = []
    calls: list[int] = []

    def _post(*a, **kw):
        calls.append(1)
        return _MockResponse(401, text="invalid api key")
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    with pytest.raises(ResearchError, match="HTTP 401"):
        call_openai("sys", "user", api_key="bad",
                    _sleep=lambda s: sleeps.append(s))
    assert calls == [1]  # only one attempt
    assert sleeps == []


def test_call_openai_raises_after_exhausting_retries(monkeypatch):
    """5xx every attempt → after backoff budget exhausted, raise with a
    clear 'transient failure after N attempts' message."""
    sleeps: list[float] = []

    def _post(*a, **kw):
        return _MockResponse(503, text="upstream busy")
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    with pytest.raises(ResearchError, match="transient failure after"):
        call_openai("sys", "user", api_key="k",
                    _sleep=lambda s: sleeps.append(s))
    # 4 intervals + initial = 5 attempts → 4 sleeps between them.
    assert sleeps == list(serp._OPENAI_RETRY_INTERVALS_S)


def test_call_openai_retries_on_network_error(monkeypatch):
    """`requests.RequestException` (connection reset, DNS, etc.) → treat
    as transient + retry."""
    import requests as _req
    sleeps: list[float] = []
    attempts = {"n": 0}

    def _post(*a, **kw):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise _req.ConnectionError("connection reset")
        return _MockResponse(200, json_data={"output_text": "ok"})
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    out = call_openai("sys", "user", api_key="k",
                     _sleep=lambda s: sleeps.append(s))
    assert out == "ok"
    assert len(sleeps) == 1


def test_call_openai_network_error_exhausted_raises(monkeypatch):
    """Persistent network errors across the budget → raise after attempts."""
    import requests as _req
    sleeps: list[float] = []

    def _post(*a, **kw):
        raise _req.Timeout("never connects")
    monkeypatch.setattr("portfolio.serp.requests.post", _post)

    with pytest.raises(ResearchError, match="failed after"):
        call_openai("sys", "user", api_key="k",
                    _sleep=lambda s: sleeps.append(s))
    assert sleeps == list(serp._OPENAI_RETRY_INTERVALS_S)
