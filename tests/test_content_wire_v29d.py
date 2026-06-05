"""v29.D — wire content derivation into `new bootstrap`.

Two layers:
  1. `bootstrap_starter_todos` / `_content_blanks` — the "Fill in
     [content]" todo is gated on the derived block's blank fields.
  2. `bootstrap(...)` end-to-end — the seeded `[content]` block reflects
     derivation, `result.content_seeded` reports it, and the starter todo
     is gated. The OpenAI call + key lookup are monkeypatched so nothing
     hits the network and the test is deterministic regardless of the
     local `portfolio.env`.
"""
from __future__ import annotations

import json
import tomllib
from datetime import date
from pathlib import Path

from portfolio import apikeys
from portfolio import content_derive
from portfolio.bootstrap import bootstrap, bootstrap_starter_todos, _content_blanks


_ALL7 = {
    "site_type": "tool",
    "primary_keyword": "kw",
    "secondary_keywords": ["a", "b"],
    "icp": "the buyer",
    "urgency_trigger": "now",
    "penalty": "loss",
    "tone": "direct",
}


# ---- _content_blanks + todo gating ----------------------------------


def test_blanks_none_is_all_todo_fields():
    assert _content_blanks(None) == [
        "site_type", "primary_keyword", "secondary_keywords", "icp",
        "urgency_trigger", "penalty", "tone",
    ]


def test_blanks_full_is_empty():
    assert _content_blanks(_ALL7) == []


def test_blanks_partial():
    assert _content_blanks({"site_type": "tool", "icp": "x"}) == [
        "primary_keyword", "secondary_keywords", "urgency_trigger", "penalty", "tone",
    ]


def test_law_blank_does_not_trigger_todo():
    # All 7 gating fields filled, `law` absent → still todo-free.
    assert _content_blanks(_ALL7) == []


def test_starter_todos_full_derive_is_todo_free():
    todos = bootstrap_starter_todos(today=date(2026, 5, 30), content_values=_ALL7)
    assert len(todos) == 3  # no fill-in todo
    assert [t.priority for t in todos] == ["medium", "medium", "low"]
    assert not any("[content]" in t.task for t in todos)


def test_starter_todos_partial_names_blanks():
    todos = bootstrap_starter_todos(content_values={"site_type": "tool", "icp": "x"})
    assert len(todos) == 4
    fill = todos[0]
    assert fill.priority == "high"
    assert "primary_keyword" in fill.task and "tone" in fill.task
    # Filled fields are not named as blanks.
    assert "site_type" not in fill.task and "icp" not in fill.task


def test_starter_todos_none_preserves_legacy_shape():
    # Back-compat: no derivation → fill-in todo lists every gating field.
    todos = bootstrap_starter_todos(content_values=None)
    assert len(todos) == 4
    assert "[content]" in todos[0].task and todos[0].priority == "high"


# ---- end-to-end bootstrap wiring ------------------------------------


_SECTIONS = {
    "Summary": "A timezone meeting tool.",
    "ICP": "An IC who owns cross-timezone scheduling.",
    "Content strategy": 'pSEO "best time to meet between [city] and [city]"; clear tone.',
}

_DERIVED_JSON = json.dumps({
    "site_type": "tool",
    "primary_keyword": "best time to meet across timezones",
    "secondary_keywords": ["meeting planner timezones"],
    "urgency_trigger": "a cross-zone meeting today",
    "penalty": "another 6am invite",
    "tone": "clear, practical",
    "law": "",
})


def _bootstrap(tmp_path, **kw):
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    result = bootstrap(
        domain=kw.pop("domain", "meetwhen.xyz"), stack="astro",
        sites_root=sites_root, today_iso="2026-06-04",
        operator_inputs=kw.pop("operator_inputs", _SECTIONS),
        skip_ga4=True,
        **kw,
    )
    toml = tomllib.loads((sites_root / "meetwhen.xyz" / "lamill.toml").read_text())
    return result, toml


def test_bootstrap_seeds_derived_content(tmp_path, monkeypatch):
    monkeypatch.setattr(apikeys, "get_key", lambda name: "sk-test")
    monkeypatch.setattr(content_derive, "_call_openai", lambda prompt, api_key: _DERIVED_JSON)

    result, toml = _bootstrap(tmp_path)
    content = toml["content"]
    assert content["site_type"] == "tool"
    assert content["icp"] == _SECTIONS["ICP"]  # verbatim, not from the model
    assert content["primary_keyword"] == "best time to meet across timezones"
    assert content["secondary_keywords"] == ["meeting planner timezones"]
    assert content["law"] == ""  # underived → skeleton default

    # All 7 gating fields derived → no fill-in todo.
    tasks = [t["task"] for t in toml.get("todo", [])]
    assert not any("[content]" in t for t in tasks)
    assert "icp" in result.content_seeded and "site_type" in result.content_seeded


def test_bootstrap_no_api_key_seeds_icp_only_and_keeps_todo(tmp_path, monkeypatch):
    monkeypatch.setattr(apikeys, "get_key", lambda name: None)  # no key → no LLM
    # _call_openai must never be reached; make it loud if it is.
    monkeypatch.setattr(content_derive, "_call_openai",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM called")))

    result, toml = _bootstrap(tmp_path)
    content = toml["content"]
    assert content["icp"] == _SECTIONS["ICP"]  # verbatim reuse, no key needed
    assert content["site_type"] == ""          # not derived
    assert result.content_seeded == ["icp"]

    # icp filled but the other 6 gating fields blank → fill-in todo present,
    # naming them and NOT naming icp.
    fill = next(t["task"] for t in toml["todo"] if "[content]" in t["task"])
    assert "site_type" in fill and "tone" in fill
    assert "icp" not in fill
