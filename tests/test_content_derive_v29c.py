"""v29.C — derive `[content]` field values from authored AI_AGENTS sections.

The LLM call (`content_derive._call_openai`) is monkeypatched in every
test that needs it, so nothing hits the network. Invariants under test:
  - `icp` is reused verbatim and never depends on the model.
  - Derivation is best-effort: no key / HTTP failure / bad JSON degrade to
    "return what we have" without raising.
  - The model's output is coerced to the field schema and feeds the v29.B
    renderer cleanly.
"""
from __future__ import annotations

import json

import pytest
import requests

from portfolio import content_derive
from portfolio import lamill_toml_edit as edit


_SECTIONS = {
    "Summary": "meetwhen.xyz visualizes overlapping working hours across timezones.",
    "Audience": "Remote workers coordinating across timezones.",
    "ICP": "An IC on a distributed team who owns recurring cross-timezone scheduling "
           'and is "blamed for the 6am invite."',
    "Goals": "Become the tool people link to for cross-zone meeting times.",
    "Content strategy": 'pSEO pages like "best time to meet between [city] and [city]"; '
                        "tone is clear and practical.",
}

_FULL_JSON = json.dumps({
    "site_type": "tool",
    "primary_keyword": "best time to meet across timezones",
    "secondary_keywords": ["meeting planner timezones", "[city] to [city] meeting time"],
    "urgency_trigger": "a cross-zone meeting to schedule today",
    "penalty": "another 6am invite and back-and-forth email",
    "tone": "clear, practical, no fluff",
    "law": "",
})


def _patch_llm(monkeypatch, reply):
    """Make `_call_openai` return `reply` (str) or raise it (Exception)."""
    def fake(prompt, api_key):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(content_derive, "_call_openai", fake)


# ---- icp reuse (model-independent) ----------------------------------


def test_icp_reused_verbatim_without_api_key():
    out = content_derive.derive_content(_SECTIONS)  # no api_key → no LLM
    assert out == {"icp": _SECTIONS["ICP"]}


def test_no_icp_section_yields_no_icp_without_key():
    out = content_derive.derive_content({"Summary": "x"})
    assert out == {}


def test_icp_present_even_when_llm_fails(monkeypatch):
    _patch_llm(monkeypatch, requests.ConnectionError("boom"))
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out == {"icp": _SECTIONS["ICP"]}  # icp survives, derived fields dropped


# ---- full derive ----------------------------------------------------


def test_full_derive_returns_all_fields(monkeypatch):
    _patch_llm(monkeypatch, _FULL_JSON)
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out["icp"] == _SECTIONS["ICP"]
    assert out["site_type"] == "tool"
    assert out["primary_keyword"] == "best time to meet across timezones"
    assert out["secondary_keywords"] == ["meeting planner timezones", "[city] to [city] meeting time"]
    assert out["tone"] == "clear, practical, no fluff"
    # Empty `law` is dropped, not carried as "".
    assert "law" not in out


def test_model_icp_field_is_ignored_in_favor_of_verbatim(monkeypatch):
    # Even if the model echoes an `icp`, we keep the verbatim section copy.
    payload = json.loads(_FULL_JSON)
    payload["icp"] = "some model-rewritten icp"
    _patch_llm(monkeypatch, json.dumps(payload))
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out["icp"] == _SECTIONS["ICP"]


# ---- robustness: empty/partial/bad output ---------------------------


def test_partial_derive_drops_empty_fields(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({
        "site_type": "tool",
        "primary_keyword": "",
        "secondary_keywords": [],
        "tone": "clear",
    }))
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out["site_type"] == "tool"
    assert out["tone"] == "clear"
    assert "primary_keyword" not in out
    assert "secondary_keywords" not in out


def test_bad_json_yields_icp_only(monkeypatch):
    _patch_llm(monkeypatch, "the model rambled and produced no json")
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out == {"icp": _SECTIONS["ICP"]}


def test_json_wrapped_in_fence_and_prose_is_parsed(monkeypatch):
    _patch_llm(monkeypatch, "Here you go:\n```json\n" + _FULL_JSON + "\n```\nHope that helps!")
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out["site_type"] == "tool"


def test_secondary_keywords_comma_string_coerced_to_list(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({"secondary_keywords": "a, b, c"}))
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert out["secondary_keywords"] == ["a", "b", "c"]


def test_unknown_keys_dropped(monkeypatch):
    _patch_llm(monkeypatch, json.dumps({"site_type": "tool", "bogus": "x", "nonsense": 1}))
    out = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    assert set(out) == {"icp", "site_type"}


def test_empty_brief_skips_llm(monkeypatch):
    # All sections empty → no icp, and the LLM must not be called.
    called = {"n": 0}
    def fake(prompt, api_key):
        called["n"] += 1
        return _FULL_JSON
    monkeypatch.setattr(content_derive, "_call_openai", fake)
    out = content_derive.derive_content({"Summary": "", "ICP": ""}, api_key="sk-test")
    assert out == {}
    assert called["n"] == 0


# ---- integration with the v29.B renderer ----------------------------


def test_derived_values_feed_content_block_and_round_trip(monkeypatch):
    import tomllib
    _patch_llm(monkeypatch, _FULL_JSON)
    values = content_derive.derive_content(_SECTIONS, api_key="sk-test")
    block = edit.content_block(values)
    parsed = tomllib.loads(block)["content"]
    assert parsed["site_type"] == "tool"
    assert parsed["icp"] == _SECTIONS["ICP"]
    assert parsed["secondary_keywords"] == values["secondary_keywords"]
    # Underived field stays at its skeleton default.
    assert parsed["law"] == ""
