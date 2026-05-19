"""Tests for v12.C — `audit_pass.run_audit_pass` (end-to-end
orchestration of build_audit_payload → render_audit_prompt →
OpenAI Responses-API call → parse_audit).

The runner is the smallest layer that ties the four primitives plus
cost computation together. Tests use the `openai_caller` injection
seam to stub the HTTP call with canned `OpenAIChatResult` values —
no real network traffic, no live OpenAI quota burn.

Parallel to `test_interpretive_pass_runner.py` (v8.H) — different
LLM provider, different schema, same orchestration shape.
"""
from __future__ import annotations

import pytest
import requests

from portfolio.audit_pass import (
    AUDIT_PROMPT_VERSION,
    AuditPassError,
    AuditPassResult,
    DEFAULT_AUDIT_MODEL,
    OpenAIChatResult,
    ParsedAudit,
    _call_openai_chat,
    _compute_cost_usd,
    _openai_pricing_for,
    run_audit_pass,
)


# ---------- fixtures ----------


def _minimal_cluster() -> dict:
    """Smallest cluster snapshot that satisfies `build_audit_payload`'s
    required keys (same shape as test_interpretive_pass_runner)."""
    return {
        "topic": "ev charger installation cost",
        "cluster_queries": ["ev charger installation cost"],
        "gates": {"gate_1_market": {"status": "PASS"}},
        "operator_fit": {"warnings": []},
        "per_query_results": [
            {"query": "ev charger installation cost",
             "organic_results": [
                 {"position": 1, "domain": "x.com",
                  "url": "https://x.com/", "title": "X",
                  "snippet": "...", "displayed_link": "x.com"},
             ],
             "features": {"ai_overview": {"present": True}}},
        ],
    }


def _primary_verdict() -> dict:
    return {
        "verdict": "GO",
        "confidence": "HIGH",
        "reasoning": "Gates passed; SERP doesn't show a programmatic incumbent.",
        "moat_required": False,
        "moat_prompt": "",
        "reductions": [],
        "operator_fit_warnings": [],
        "blind_spot_self_report": "Maybe over-confident on incumbent read.",
    }


def _canonical_audit_markdown(*,
                              agreement_level: str = "partial",
                              concerns: list[str] | None = None) -> str:
    bullets = concerns or [
        "INCUMBENT UNDER-DETECTION: notateslaapp.com has 4 templated URLs.",
    ]
    return (
        f"### agreement_level\n{agreement_level}\n\n"
        "### confidence\nMEDIUM\n\n"
        "### specific_concerns\n"
        + "\n".join(f"- {c}" for c in bullets)
    )


def _fake_caller(text: str, *,
                 input_tokens: int = 1500, output_tokens: int = 300):
    """Build a stub matching `_call_openai_chat`'s signature.
    Returns a canned `OpenAIChatResult` regardless of inputs — prompt
    shape is asserted via separate render-layer tests, not here."""
    def _stub(system, user, *, model, api_key, timeout_s):
        return OpenAIChatResult(
            text=text,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
    return _stub


def _capturing_caller(text: str):
    """Stub that records the arguments it was called with. Returned
    object is (call_args, stub) — call_args is mutated on call so
    tests can inspect what the runner passed in."""
    captured: dict = {}

    def _stub(system, user, *, model, api_key, timeout_s):
        captured["system"] = system
        captured["user"] = user
        captured["model"] = model
        captured["api_key"] = api_key
        captured["timeout_s"] = timeout_s
        return OpenAIChatResult(text=text, input_tokens=100, output_tokens=50)

    return captured, _stub


# ---------- happy path ----------


def test_run_audit_pass_returns_full_result():
    text = _canonical_audit_markdown()
    result = run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        openai_caller=_fake_caller(text),
        api_key="placeholder-not-used-with-stub",
    )
    assert isinstance(result, AuditPassResult)
    assert isinstance(result.audit, ParsedAudit)
    assert result.audit.agreement_level == "partial"
    assert result.audit.confidence == "MEDIUM"
    assert result.prompt_version == AUDIT_PROMPT_VERSION
    assert result.model_id == DEFAULT_AUDIT_MODEL  # gpt-4o
    assert result.duration_s >= 0.0


def test_run_audit_pass_includes_rendered_prompt():
    """The rendered prompt is preserved on the result so the snapshot
    can audit exactly what was sent. Useful for cross-prompt-version
    comparison."""
    text = _canonical_audit_markdown()
    result = run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        openai_caller=_fake_caller(text),
        api_key="x",
    )
    # Topic flows through build_audit_payload → render_audit_prompt
    # into the JSON payload block.
    assert "ev charger installation cost" in result.rendered_prompt
    # Primary's verdict is reconstructed into the audit prompt's payload.
    assert "GO" in result.rendered_prompt


def test_run_audit_pass_splits_prompt_on_delimiter():
    """The renderer separates system + payload with `\\n---\\n`; the
    runner splits there and sends them as the OpenAI Responses-API
    `system` and `user` messages respectively. Verifies the split
    keeps both halves non-empty and routes them correctly."""
    captured, stub = _capturing_caller(_canonical_audit_markdown())
    run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        openai_caller=stub,
        api_key="x",
    )
    # System part is the audit prompt body — mentions adversarial role.
    assert "adversarial auditor" in captured["system"].lower() or \
           "adversarial" in captured["system"].lower()
    # User part is the JSON payload section — has the input-payload header.
    assert "INPUT PAYLOAD" in captured["user"]
    assert "```json" in captured["user"]


# ---------- model override + propagation ----------


def test_run_audit_pass_default_model_is_gpt4o():
    captured, stub = _capturing_caller(_canonical_audit_markdown())
    run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        openai_caller=stub, api_key="x",
    )
    assert captured["model"] == "gpt-4o"


def test_run_audit_pass_model_override():
    captured, stub = _capturing_caller(_canonical_audit_markdown())
    result = run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        model="gpt-4-turbo",
        openai_caller=stub, api_key="x",
    )
    assert captured["model"] == "gpt-4-turbo"
    assert result.model_id == "gpt-4-turbo"


def test_run_audit_pass_propagates_api_key_and_timeout():
    captured, stub = _capturing_caller(_canonical_audit_markdown())
    run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        timeout_s=42,
        openai_caller=stub, api_key="sk-test-key-xyz",
    )
    assert captured["api_key"] == "sk-test-key-xyz"
    assert captured["timeout_s"] == 42


# ---------- error wrapping ----------


def test_run_audit_pass_wraps_parser_errors():
    """A bad LLM response surfaces as `AuditPassError` (not the raw
    `AuditParseError`) so callers have a single exception type to
    catch at the orchestration boundary."""
    garbage = "I refuse to follow the format; here are some thoughts."
    with pytest.raises(AuditPassError, match="could not parse"):
        run_audit_pass(
            _minimal_cluster(),
            primary_verdict=_primary_verdict(),
            openai_caller=_fake_caller(garbage),
            api_key="x",
        )


def test_run_audit_pass_wraps_caller_exceptions():
    """If the openai_caller raises (e.g. our default's transport
    error), the runner doesn't swallow it — caller decides whether
    to retry."""
    def boom(system, user, *, model, api_key, timeout_s):
        raise AuditPassError("OpenAI request failed: timeout")
    with pytest.raises(AuditPassError, match="timeout"):
        run_audit_pass(
            _minimal_cluster(),
            primary_verdict=_primary_verdict(),
            openai_caller=boom,
            api_key="x",
        )


# ---------- cost computation ----------


def test_cost_computation_gpt4o_known_pricing():
    """gpt-4o pricing: $2.50 input / $10.00 output per 1M tokens.
    1500 input + 300 output = $0.00375 + $0.003 = $0.00675."""
    cost = _compute_cost_usd(
        "gpt-4o", input_tokens=1500, output_tokens=300,
    )
    assert cost == pytest.approx(0.00675, abs=1e-6)


def test_cost_computation_gpt4o_dated_alias_falls_through():
    """OpenAI's dated aliases (`gpt-4o-2024-08-06`) should fall
    through to the base model's pricing — guards against breakage
    when OpenAI promotes a new snapshot."""
    cost_base = _compute_cost_usd(
        "gpt-4o", input_tokens=1000, output_tokens=1000,
    )
    cost_dated = _compute_cost_usd(
        "gpt-4o-2024-08-06", input_tokens=1000, output_tokens=1000,
    )
    assert cost_dated == cost_base
    assert cost_dated > 0


def test_cost_computation_unknown_model_returns_zero():
    """Unknown models return cost=0 rather than crashing — v12.F
    refines the pricing table; v12.C must complete even on a
    not-yet-known model id."""
    cost = _compute_cost_usd(
        "gpt-5-future", input_tokens=10_000, output_tokens=10_000,
    )
    assert cost == 0.0


def test_pricing_for_known_models():
    """Pricing table includes the audit-pass-relevant models."""
    assert _openai_pricing_for("gpt-4o")["input"] == 2.50
    assert _openai_pricing_for("gpt-4o")["output"] == 10.00
    assert _openai_pricing_for("gpt-4o-mini")["input"] < 1.00


def test_run_audit_pass_records_cost_from_usage():
    """End-to-end: caller returns token usage; runner computes USD
    via the pricing table and stores it on the result."""
    result = run_audit_pass(
        _minimal_cluster(),
        primary_verdict=_primary_verdict(),
        openai_caller=_fake_caller(
            _canonical_audit_markdown(),
            input_tokens=2_000, output_tokens=500,
        ),
        api_key="x",
    )
    # gpt-4o: 2000 * 2.50/1M + 500 * 10.00/1M = 0.005 + 0.005 = 0.01
    assert result.cost_usd == pytest.approx(0.01, abs=1e-6)


# ---------- HTTP caller — direct exercise of _call_openai_chat ----------


class _FakeResponse:
    def __init__(self, *, status_code: int, payload=None,
                 raw_text: str | None = None):
        self.status_code = status_code
        self._payload = payload
        self.text = raw_text if raw_text is not None else (
            "" if payload is None else "fake-body"
        )

    def json(self):
        if self._payload is None:
            raise ValueError("no JSON body")
        return self._payload


def _patch_requests_post(monkeypatch, response):
    def fake_post(url, headers=None, json=None, timeout=None):
        return response
    monkeypatch.setattr(requests, "post", fake_post)


def test_call_openai_chat_extracts_output_text_and_usage(monkeypatch):
    """Responses API surfaces text under `output_text` and usage under
    `usage.{input,output}_tokens`. The helper returns both."""
    _patch_requests_post(monkeypatch, _FakeResponse(
        status_code=200,
        payload={
            "output_text": "### agreement_level\nfull\n\n"
                            "### confidence\nHIGH\n\n"
                            "### specific_concerns\n- a concern",
            "usage": {"input_tokens": 1200, "output_tokens": 80},
        },
    ))
    result = _call_openai_chat(
        "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
    )
    assert result.text.startswith("### agreement_level")
    assert result.input_tokens == 1200
    assert result.output_tokens == 80


def test_call_openai_chat_extracts_text_from_structured_output(monkeypatch):
    """Responses API can also nest text under `output[].content[]`.
    The helper falls back to that shape when `output_text` is absent."""
    _patch_requests_post(monkeypatch, _FakeResponse(
        status_code=200,
        payload={
            "output": [
                {"content": [
                    {"type": "output_text", "text": "nested response text"},
                ]},
            ],
            "usage": {"input_tokens": 50, "output_tokens": 20},
        },
    ))
    result = _call_openai_chat(
        "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
    )
    assert result.text == "nested response text"


def test_call_openai_chat_raises_on_non_200(monkeypatch):
    _patch_requests_post(monkeypatch, _FakeResponse(
        status_code=429,
        raw_text="rate limited",
        payload={"error": "rate"},  # body present but irrelevant
    ))
    with pytest.raises(AuditPassError, match="HTTP 429"):
        _call_openai_chat(
            "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
        )


def test_call_openai_chat_raises_on_transport_error(monkeypatch):
    def fake_post(url, headers=None, json=None, timeout=None):
        raise requests.ConnectionError("network unreachable")
    monkeypatch.setattr(requests, "post", fake_post)
    with pytest.raises(AuditPassError, match="OpenAI request failed"):
        _call_openai_chat(
            "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
        )


def test_call_openai_chat_raises_on_non_json_body(monkeypatch):
    bad_resp = _FakeResponse(status_code=200, payload=None, raw_text="not json")
    _patch_requests_post(monkeypatch, bad_resp)
    with pytest.raises(AuditPassError, match="non-JSON"):
        _call_openai_chat(
            "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
        )


def test_call_openai_chat_raises_on_unexpected_shape(monkeypatch):
    """JSON parses but has no recognizable text field."""
    _patch_requests_post(monkeypatch, _FakeResponse(
        status_code=200,
        payload={"id": "resp_abc", "created": 0},
    ))
    with pytest.raises(AuditPassError, match="unexpected.*response shape"):
        _call_openai_chat(
            "sys", "user", model="gpt-4o", api_key="x", timeout_s=10,
        )
