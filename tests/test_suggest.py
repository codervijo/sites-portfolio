"""Tests for src/portfolio/suggest.py — score, strategies, dedupe, cache, parsing."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from portfolio import suggest
from portfolio.suggest import (
    Candidate,
    ScoredOption,
    Strategy,
    _extract_names,
    _parse_openai_text,
    _topic_hash,
    brainstorm,
    cache_get,
    cache_set,
    filter_by_max_price,
    load_strategies,
    render_options,
    score_name,
)


# ---------- score_name ----------


def test_score_basic_com_short():
    s, notes = score_name("flow", "anything", ".com")
    assert s > 30
    assert "tld:.com(10)" in notes
    assert "short" in notes


def test_score_penalizes_hyphens():
    s_clean, _ = score_name("flowsync", "x", ".com")
    s_hy, notes_hy = score_name("flow-sync", "x", ".com")
    assert s_hy < s_clean
    assert "hyphen" in notes_hy


def test_score_penalizes_digits():
    s_clean, _ = score_name("flowsync", "x", ".com")
    s_num, notes_num = score_name("flow42", "x", ".com")
    assert s_num < s_clean
    assert "digit" in notes_num


def test_score_rewards_keyword_presence():
    s_no, _ = score_name("flowsync", "cricket scores", ".com")
    s_yes, notes_yes = score_name("cricketai", "cricket scores", ".com")
    assert s_yes > s_no
    assert "keyword" in notes_yes


def test_score_rewards_premium_tld_over_low():
    s_com, _ = score_name("flow", "x", ".com")
    s_site, _ = score_name("flow", "x", ".site")
    assert s_com > s_site


def test_score_long_name_penalty():
    s_short, _ = score_name("abc", "x", ".com")
    s_long, notes_long = score_name("abcdefghijklmnopq", "x", ".com")
    assert s_long < s_short
    assert "long" in notes_long


# ---------- load_strategies ----------


def test_load_strategies_returns_default_set(tmp_path):
    out = load_strategies()
    assert len(out) == 5
    names = [s.name for s in out]
    assert "trendy" in names
    assert "abstract-brandable" in names


def test_load_strategies_from_custom_path(tmp_path):
    p = tmp_path / "strategies.json"
    p.write_text(json.dumps({
        "strategies": [{"name": "x", "label": "X", "description": "x desc"}]
    }))
    out = load_strategies(p)
    assert len(out) == 1
    assert out[0].name == "x"


# ---------- _topic_hash ----------


def test_topic_hash_stable():
    s = [Strategy("a", "A", "x"), Strategy("b", "B", "y")]
    h1 = _topic_hash("idea", [s_.name for s_ in s])
    h2 = _topic_hash("idea", [s_.name for s_ in s])
    assert h1 == h2


def test_topic_hash_case_insensitive():
    s = [Strategy("a", "A", "x")]
    h1 = _topic_hash("Idea", [s_.name for s_ in s])
    h2 = _topic_hash("IDEA", [s_.name for s_ in s])
    assert h1 == h2


def test_topic_hash_strategies_independent_of_order():
    s1 = ["a", "b"]
    s2 = ["b", "a"]
    assert _topic_hash("idea", s1) == _topic_hash("idea", s2)


# ---------- cache get/set ----------


def test_cache_set_then_get(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path)
    strategies = [Strategy("x", "X", "desc")]
    cands = {"x": [Candidate(name="foo", strategy="x")]}
    cache_set("topic", strategies, cands)
    payload = cache_get("topic", strategies)
    assert payload is not None
    assert payload["topic"] == "topic"
    assert payload["candidates_by_strategy"]["x"][0]["name"] == "foo"


def test_cache_get_misses_when_no_file(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path)
    strategies = [Strategy("x", "X", "desc")]
    assert cache_get("never-cached", strategies) is None


def test_cache_get_misses_when_expired(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(suggest, "CACHE_TTL_SECONDS", 0)
    strategies = [Strategy("x", "X", "desc")]
    cache_set("topic", strategies, {"x": [Candidate("foo", "x")]})
    import time
    time.sleep(0.01)
    assert cache_get("topic", strategies) is None


# ---------- _extract_names ----------


def test_extract_names_strips_numbering_and_filters():
    text = "1. flow\n2) sync\n- drop\n  ship42  \nbad-name\nfine\n"
    out = _extract_names(text)
    assert "flow" in out
    assert "sync" in out
    assert "drop" in out
    assert "fine" in out
    assert all("-" not in n for n in out)
    assert "bad-name" not in out


def test_extract_names_drops_too_long():
    text = "thisisareallylongname\nfine\n"
    out = _extract_names(text)
    assert "thisisareallylongname" not in out
    assert "fine" in out


def test_extract_names_drops_invalid_chars():
    text = "Domain.com\nflow\nbad name\n"
    out = _extract_names(text)
    assert "domain.com" not in out  # has dot
    assert "flow" in out
    assert "bad name" not in out  # has space


# ---------- _parse_openai_text ----------


def test_parse_openai_responses_v1_shape():
    payload = {
        "output": [
            {"content": [{"text": "alpha\nbeta\ngamma"}]}
        ]
    }
    assert _parse_openai_text(payload) == "alpha\nbeta\ngamma"


def test_parse_openai_text_fallback_output_text():
    payload = {"output_text": "x\ny"}
    assert _parse_openai_text(payload) == "x\ny"


def test_parse_openai_text_handles_unexpected_shape():
    payload = {"weird": "shape"}
    assert _parse_openai_text(payload) == ""


# ---------- brainstorm with mocked OpenAI ----------


def test_brainstorm_calls_openai_and_parses(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"output_text": "alpha\nbeta\ngamma"}
    fake_resp.raise_for_status.return_value = None

    with patch("portfolio.suggest.requests") as fake_requests:
        fake_requests.post.return_value = fake_resp
        cands = brainstorm(
            "idea", Strategy("trendy", "Trendy", "desc"), history=[], api_key="sk-test"
        )
    assert [c.name for c in cands] == ["alpha", "beta", "gamma"]
    assert all(c.strategy == "trendy" for c in cands)


def test_brainstorm_history_dedupe(monkeypatch):
    fake_resp = MagicMock()
    fake_resp.json.return_value = {"output_text": "alpha\nbeta"}
    fake_resp.raise_for_status.return_value = None

    with patch("portfolio.suggest.requests") as fake_requests:
        fake_requests.post.return_value = fake_resp
        cands = brainstorm(
            "idea", Strategy("trendy", "Trendy", "desc"),
            history=["alpha"], api_key="sk-test",
        )
    names = [c.name for c in cands]
    assert "alpha" not in names
    assert "beta" in names


# ---------- render_options ----------


def test_render_options_picks_first_available_tld():
    cands = [Candidate(name="flow", strategy="trendy")]
    seen = []

    def fake_check(domain):
        seen.append(domain)
        if domain == "flow.com":
            return False, None
        if domain == "flow.ai":
            return True, 79.00
        return True, 11.99

    options = render_options(cands, "any", [".com", ".ai", ".io"], fake_check)
    assert len(options) == 1
    o = options[0]
    assert o.tld == ".ai"
    assert o.available is True
    assert o.price == 79.00
    assert seen == ["flow.com", "flow.ai"]  # stopped at first available


def test_render_options_sorts_by_score_desc():
    cands = [
        Candidate(name="superlongname", strategy="trendy"),
        Candidate(name="flow", strategy="trendy"),
    ]
    options = render_options(
        cands, "any", [".com"],
        lambda d: (True, 11.99),
    )
    assert options[0].name == "flow"
    assert options[1].name == "superlongname"


def test_render_options_marks_all_unavailable_as_unavailable():
    cands = [Candidate(name="taken", strategy="trendy")]
    options = render_options(
        cands, "any", [".com", ".ai"],
        lambda d: (False, None),
    )
    assert options[0].available is False


# ---------- filter_by_max_price ----------


def test_filter_by_max_price_keeps_unpriced():
    opts = [
        ScoredOption("a", ".com", "a.com", True, None, 50, "x"),
        ScoredOption("b", ".com", "b.com", True, 99.0, 40, "x"),
    ]
    out = filter_by_max_price(opts, max_price=50.0)
    names = [o.name for o in out]
    assert "a" in names  # unpriced kept
    assert "b" not in names  # over budget


def test_filter_by_max_price_none_keeps_all():
    opts = [ScoredOption("a", ".com", "a.com", True, 9999.0, 50, "x")]
    assert filter_by_max_price(opts, None) == opts


# ---------- ensure_portfolio_env ----------


def test_ensure_portfolio_env_creates_when_missing(tmp_path, monkeypatch):
    target = tmp_path / "portfolio.env"
    monkeypatch.setattr(suggest, "PORTFOLIO_ENV", target)
    out = suggest.ensure_portfolio_env()
    assert out == target
    assert target.exists()
    assert "OPENAI_API_KEY" in target.read_text()


def test_ensure_portfolio_env_does_not_overwrite(tmp_path, monkeypatch):
    target = tmp_path / "portfolio.env"
    target.write_text("# my custom env\nOPENAI_API_KEY=mykey\n")
    monkeypatch.setattr(suggest, "PORTFOLIO_ENV", target)
    suggest.ensure_portfolio_env()
    assert "mykey" in target.read_text()
