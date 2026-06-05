"""v29.F — CHECK_152 content-derivable + its fix_tier_1.

The LLM (`content_derive._call_openai`) and the key lookup
(`apikeys.get_key`) are monkeypatched, so nothing hits the network. The
fixer wires the v29.C derivation to the v29.E gated replace.
"""
from __future__ import annotations

import json
import tomllib

from portfolio import apikeys, content_derive
from portfolio import lamill_toml_edit as edit
from portfolio.checks.content import check_152_content_derivable as chk
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

_AI_AGENTS = """# AI Agent Context — demo.com

## ICP

*the specific ideal customer*

Mid-market SRE teams with a compliance mandate.

## Content strategy

*what content this site needs*

pSEO pages like "how to write a postmortem"; tone is direct, technical.
"""

_THIN_AI_AGENTS = """# AI Agent Context — demo.com

## Summary

*one paragraph*

(to be filled in)
"""

_DERIVED_JSON = json.dumps({
    "site_type": "tool",
    "primary_keyword": "postmortem template",
    "secondary_keywords": ["incident timeline"],
    "urgency_trigger": "a Sev1 postmortem due now",
    "penalty": "a repeat incident with no writeup",
    "tone": "direct, technical, no fluff",
    "law": "",
})

_PREFIX = (
    'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n'
    "[[todo]]\n"
    'status = "open"\n'
    'priority = "high"\n'
    'task = "Fill in [content] block (site_type, primary_keyword, icp, …)"\n\n'
)


def _site(tmp_path, *, ai=_AI_AGENTS, content=True):
    if ai is not None:
        (tmp_path / "AI_AGENTS.md").write_text(ai, encoding="utf-8")
    text = _PREFIX + (edit.CONTENT_SKELETON if content else "")
    (tmp_path / LAMILL_TOML_FILENAME).write_text(text)
    return tmp_path


def _patch_llm(monkeypatch, reply):
    def fake(prompt, api_key):
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(content_derive, "_call_openai", fake)


# ---- run() ----------------------------------------------------------


def test_run_warns_when_empty_and_derivable(tmp_path):
    _site(tmp_path)
    assert chk.run(str(tmp_path)).status == "warn"


def test_run_passes_when_content_populated(tmp_path):
    _site(tmp_path)
    edit.set_content_block(tmp_path, {"site_type": "tool"})
    assert chk.run(str(tmp_path)).status == "pass"


def test_run_passes_when_ai_agents_thin(tmp_path):
    _site(tmp_path, ai=_THIN_AI_AGENTS)
    assert chk.run(str(tmp_path)).status == "pass"


def test_run_passes_without_lamill_toml(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(_AI_AGENTS, encoding="utf-8")
    assert chk.run(str(tmp_path)).status == "pass"


# ---- fix_tier_1 -----------------------------------------------------


def test_fix_dry_run_makes_no_llm_call(tmp_path, monkeypatch):
    _site(tmp_path)
    _patch_llm(monkeypatch, RuntimeError("LLM must not be called in dry-run"))
    monkeypatch.setattr(apikeys, "get_key", lambda k: "test-key")
    res = chk.fix_tier_1.apply(tmp_path, True, False)  # dry_run=True
    assert res.status == "would-fix"


def test_fix_no_key_is_manual(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(apikeys, "get_key", lambda k: None)
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "manual"
    assert "OPENAI_API_KEY" in res.summary


def test_fix_seeds_content_from_derivation(tmp_path, monkeypatch):
    _site(tmp_path)
    _patch_llm(monkeypatch, _DERIVED_JSON)
    monkeypatch.setattr(apikeys, "get_key", lambda k: "test-key")
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "fixed"
    table = tomllib.loads((tmp_path / LAMILL_TOML_FILENAME).read_text())["content"]
    assert table["site_type"] == "tool"
    assert table["primary_keyword"] == "postmortem template"
    assert table["secondary_keywords"] == ["incident timeline"]
    # icp is reused verbatim from the ICP section (not from the LLM)
    assert table["icp"].startswith("Mid-market SRE teams")
    # the check now passes
    assert chk.run(str(tmp_path)).status == "pass"


def test_fix_closes_fillin_todo_when_fully_seeded(tmp_path, monkeypatch):
    from portfolio import lamill_toml
    _site(tmp_path)
    _patch_llm(monkeypatch, _DERIVED_JSON)
    monkeypatch.setattr(apikeys, "get_key", lambda k: "test-key")
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "fixed"
    assert "closed" in res.summary
    todos = lamill_toml.load(tmp_path).todos
    fillin = [t for t in todos if t.task.lower().startswith("fill in [content]")]
    assert fillin and fillin[0].status == "done"


def test_fix_nothing_to_do_when_already_populated(tmp_path, monkeypatch):
    _site(tmp_path)
    edit.set_content_block(tmp_path, {"site_type": "tool"})
    monkeypatch.setattr(apikeys, "get_key", lambda k: "test-key")
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "nothing-to-do"


def test_fix_manual_without_ai_agents(tmp_path, monkeypatch):
    _site(tmp_path, ai=None)
    monkeypatch.setattr(apikeys, "get_key", lambda k: "test-key")
    res = chk.fix_tier_1.apply(tmp_path, False, False)
    assert res.status == "manual"
