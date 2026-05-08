"""Tests for src/portfolio/suggest.py — score, strategies, dedupe, cache, parsing."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

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
    # 2026-05-08: TLD tier weight reduced from ×5 to ×1; .com short is now 20
    # (10 tier + 10 short), not 60. Score is still positive and signals .com.
    assert s >= 20
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


def test_parse_openai_responses_v1_message_shape():
    """Standard /v1/responses output: a list with a `message` item containing
    `output_text` content blocks."""
    payload = {
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "alpha\nbeta\ngamma"}],
            }
        ]
    }
    assert _parse_openai_text(payload) == "alpha\nbeta\ngamma"


def test_parse_openai_responses_v1_skips_reasoning_block():
    """Reasoning models (gpt-5-mini, o-series) prefix the output list with a
    `{"type": "reasoning"}` block. Parser must skip it and find the message."""
    payload = {
        "output": [
            {"type": "reasoning", "summary": []},
            {
                "type": "message",
                "content": [{"type": "output_text", "text": "zivlo\nquorbi\nblyxo"}],
            },
        ]
    }
    assert _parse_openai_text(payload) == "zivlo\nquorbi\nblyxo"


def test_parse_openai_text_fallback_output_text():
    payload = {"output_text": "x\ny"}
    assert _parse_openai_text(payload) == "x\ny"


def test_parse_openai_text_handles_unexpected_shape():
    payload = {"weird": "shape"}
    assert _parse_openai_text(payload) == ""


def test_parse_openai_text_ignores_empty_message_blocks():
    """Edge case: message block with no text content. Should return empty, not error."""
    payload = {"output": [{"type": "message", "content": []}]}
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


def test_render_options_keeps_scanning_past_unknown_to_find_true():
    """If RDAP returns unknown (None) for an early TLD, keep scanning — don't stop there.
    Confirmed available (True) is preferred over unknown.
    """
    cands = [Candidate(name="flow", strategy="trendy")]

    def fake_check(domain):
        if domain == "flow.com":
            return False, None       # taken
        if domain == "flow.ai":
            return None, None        # unknown (RDAP gap)
        if domain == "flow.io":
            return True, 49.00       # confirmed available
        return False, None

    options = render_options(cands, "any", [".com", ".ai", ".io", ".app"], fake_check)
    assert options[0].tld == ".io"
    assert options[0].available is True


def test_render_options_returns_unknown_when_no_true_found():
    """If no TLD returned True, surface the best Unknown result rather than hiding it."""
    cands = [Candidate(name="flow", strategy="trendy")]

    def fake_check(domain):
        if domain == "flow.com":
            return False, None       # taken
        if domain == "flow.ai":
            return None, None        # unknown
        return None, None

    options = render_options(cands, "any", [".com", ".ai", ".io"], fake_check)
    assert options[0].available is None
    assert options[0].tld in (".ai", ".io")


def test_render_options_sort_priority_true_unknown_false():
    """Final sort: True > None > False; within each, by score desc."""
    cands = [
        Candidate(name="alpha", strategy="x"),
        Candidate(name="beta", strategy="x"),
        Candidate(name="gamma", strategy="x"),
    ]

    def fake_check(domain):
        if domain.startswith("alpha"):
            return False, None       # all .com / .ai taken
        if domain.startswith("beta"):
            return None, None        # unknown
        if domain.startswith("gamma"):
            return True, 11.99       # confirmed available
        return False, None

    options = render_options(cands, "any", [".com", ".ai"], fake_check)
    # gamma (True) first, beta (Unknown) second, alpha (False) last
    assert options[0].name == "gamma"
    assert options[1].name == "beta"
    assert options[2].name == "alpha"


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


# =============================================================================
# v3.D — Validation-mode suggest: vocab anchor + registrar grid + register
# =============================================================================

from portfolio.suggest import (
    BROKEN_RDAP_TLDS,
    CellState,
    DEFAULT_TLDS,
    FULL_LADDER,
    GridRow,
    RegisterResult,
    SCORE_BONUS_COM_AVAILABLE,
    SCORE_PENALTY_COM_LIVE,
    _decide_pick,
    _extract_vocab_terms,
    _money_from_pricing,
    _vocab_prompt,
    _brainstorm_prompt,
    build_grid,
    extract_vocab,
    filter_default_strategies,
    porkbun_cart_url,
    register_domain,
    run_validation_pipeline,
)


# ---------- v3.D defaults ----------


def test_v3d_default_tlds_has_app_dev_xyz_site_co():
    assert DEFAULT_TLDS == (".com", ".app", ".dev", ".xyz", ".site", ".co")


def test_v3d_broken_rdap_tlds_now_empty():
    # As of 2026-05-07 we route Radix calls with verify=False; no TLDs are
    # special-cased anymore. The constant is preserved (empty) for external callers.
    assert BROKEN_RDAP_TLDS == frozenset()


# ---------- v3.D TLD tier reweight ----------


def test_v3d_app_and_dev_promoted_to_tier_9():
    assert suggest.TLD_TIER[".app"] == 9
    assert suggest.TLD_TIER[".dev"] == 9


def test_v3d_xyz_at_tier_6():
    assert suggest.TLD_TIER[".xyz"] == 6


def test_v3d_site_at_tier_5():
    assert suggest.TLD_TIER[".site"] == 5


def test_v3d_app_outranks_io_in_score():
    s_app, _ = score_name("scrubs", "x", ".app")
    s_io, _ = score_name("scrubs", "x", ".io")
    assert s_app > s_io


# ---------- v3.D defense bonuses ----------


def test_v3d_score_bonus_when_com_available():
    s_no, _ = score_name("scrubsync", "x", ".app")
    s_def, notes = score_name("scrubsync", "x", ".app", com_status="available")
    assert s_def == s_no + SCORE_BONUS_COM_AVAILABLE
    assert "com-defendable" in notes


def test_v3d_score_penalty_when_com_live():
    s_no, _ = score_name("scrubsync", "x", ".app")
    s_pois, notes = score_name("scrubsync", "x", ".app", com_status="live-site")
    assert s_pois == s_no + SCORE_PENALTY_COM_LIVE
    assert "com-poisoned" in notes


def test_v3d_score_neutral_for_parked_com():
    s_no, _ = score_name("scrubsync", "x", ".app")
    s_park, _ = score_name("scrubsync", "x", ".app", com_status="parked")
    # `parked` is not handled — no bonus, no penalty
    assert s_park == s_no


# ---------- v3.D strategies schema v2 ----------


def test_v3d_load_strategies_with_require_anchors(tmp_path):
    p = tmp_path / "strategies.json"
    p.write_text(json.dumps({
        "schema_version": 2,
        "strategies": [
            {"name": "trendy", "label": "T", "description": "d", "require_anchors": True},
            {"name": "abstract", "label": "A", "description": "d", "require_anchors": False},
        ],
    }))
    out = load_strategies(p)
    assert out[0].require_anchors is True
    assert out[1].require_anchors is False


def test_v3d_load_strategies_legacy_v1_defaults_require_anchors_true(tmp_path):
    p = tmp_path / "strategies.json"
    p.write_text(json.dumps({
        "schema_version": 1,
        "strategies": [{"name": "old", "label": "O", "description": "d"}],
    }))
    out = load_strategies(p)
    assert out[0].require_anchors is True


def test_v3d_filter_default_drops_abstract():
    strategies = [
        Strategy(name="trendy", label="T", description="d"),
        Strategy(name="abstract-brandable", label="A", description="d", require_anchors=False),
    ]
    out = filter_default_strategies(strategies, with_abstract=False)
    names = [s.name for s in out]
    assert "trendy" in names
    assert "abstract-brandable" not in names


def test_v3d_filter_with_abstract_keeps_all():
    strategies = [
        Strategy(name="trendy", label="T", description="d"),
        Strategy(name="abstract-brandable", label="A", description="d", require_anchors=False),
    ]
    out = filter_default_strategies(strategies, with_abstract=True)
    names = [s.name for s in out]
    assert "abstract-brandable" in names


def test_v3d_real_strategies_json_has_require_anchors_field():
    """Sanity-check: the shipped data/strategies.json already has v3.D schema."""
    out = load_strategies()
    by_name = {s.name: s for s in out}
    assert by_name["abstract-brandable"].require_anchors is False
    assert by_name["trendy"].require_anchors is True


# ---------- v3.D prompt anchor injection ----------


def test_v3d_brainstorm_prompt_required_anchors():
    s = Strategy(name="t", label="T", description="d", require_anchors=True)
    prompt = _brainstorm_prompt("idea", s, [], 12, vocab_terms=["scrubs", "ppe"])
    assert "must reference" in prompt.lower() or "must reference at least one" in prompt
    assert "scrubs, ppe" in prompt


def test_v3d_brainstorm_prompt_inspiration_anchors():
    s = Strategy(name="abstract", label="A", description="d", require_anchors=False)
    prompt = _brainstorm_prompt("idea", s, [], 12, vocab_terms=["scrubs", "ppe"])
    assert "inspiration" in prompt.lower()
    assert "scrubs, ppe" in prompt


def test_v3d_brainstorm_prompt_no_anchor_block_when_empty_vocab():
    s = Strategy(name="t", label="T", description="d", require_anchors=True)
    prompt = _brainstorm_prompt("idea", s, [], 12, vocab_terms=[])
    assert "concept anchors" not in prompt.lower()


# ---------- v3.D vocab extraction ----------


def test_v3d_vocab_prompt_contains_topic_and_example():
    p = _vocab_prompt("smart layer between healthcare workers and their workwear")
    assert "smart layer between healthcare workers" in p
    assert "leash" in p  # worked example
    assert "do not produce" in p.lower() or "bad terms" in p.lower()


def test_v3d_extract_vocab_terms_basic():
    text = "scrubs\ngown\nbadge\nshift\nfit\n"
    out = _extract_vocab_terms(text)
    assert out == ["scrubs", "gown", "badge", "shift", "fit"]


def test_v3d_extract_vocab_caps_at_9_chars():
    text = "compliance\nshift\nregulatory\nfit\n"  # compliance(10) and regulatory(10) too long
    out = _extract_vocab_terms(text)
    assert "shift" in out
    assert "fit" in out
    assert "compliance" not in out
    assert "regulatory" not in out


def test_v3d_extract_vocab_strips_numbering_and_dedups():
    text = "1. scrubs\n2) scrubs\n- gown\n* badge\n"
    out = _extract_vocab_terms(text)
    # scrubs deduplicated
    assert out.count("scrubs") == 1
    assert "gown" in out
    assert "badge" in out


def test_v3d_extract_vocab_rejects_digits_and_phrases():
    text = "scrub3s\nshift handover\nfit\n"
    out = _extract_vocab_terms(text)
    assert "scrub3s" not in out
    assert "shift handover" not in out
    assert "fit" in out


def test_v3d_extract_vocab_via_openai_mocked():
    """End-to-end vocab call: mock requests.post and verify parsed output."""
    fake_resp = MagicMock()
    fake_resp.json.return_value = {
        "output_text": "scrubs\ngown\nbadge\nshift\nfit\nppe\nlaundry\n"
    }
    fake_resp.raise_for_status = MagicMock()

    with patch("portfolio.suggest.requests.post", return_value=fake_resp) as mock_post:
        terms = extract_vocab("healthcare workwear", api_key="sk-fake")

    assert "scrubs" in terms
    assert "ppe" in terms
    # Verify prompt was sent to the right endpoint with the topic embedded
    assert mock_post.call_args.kwargs["json"]["model"] == suggest.OPENAI_MODEL
    assert "healthcare workwear" in mock_post.call_args.kwargs["json"]["input"]


# ---------- v3.D cache extension ----------


def test_v3d_cache_set_includes_vocab_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path / "cache")
    strategies = [Strategy(name="t", label="T", description="d")]
    cands = {"t": [Candidate(name="scrubs", strategy="t")]}
    p = cache_set("topic", strategies, cands, vocab_terms=["scrubs", "gown"])
    assert p.exists()
    payload = json.loads(p.read_text())
    assert payload["vocab_terms"] == ["scrubs", "gown"]


def test_v3d_cache_get_returns_vocab_terms(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path / "cache")
    strategies = [Strategy(name="t", label="T", description="d")]
    cands = {"t": [Candidate(name="scrubs", strategy="t")]}
    cache_set("topic", strategies, cands, vocab_terms=["scrubs"])
    out = cache_get("topic", strategies)
    assert out is not None
    assert out["vocab_terms"] == ["scrubs"]


def test_v3d_cache_set_omits_vocab_when_none(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path / "cache")
    strategies = [Strategy(name="t", label="T", description="d")]
    cands = {"t": [Candidate(name="scrubs", strategy="t")]}
    p = cache_set("topic", strategies, cands)
    payload = json.loads(p.read_text())
    assert "vocab_terms" not in payload


# ---------- v3.D porkbun cart url ----------


def test_v3d_porkbun_cart_url_single():
    assert porkbun_cart_url(["scrubsync.app"]) == "https://porkbun.com/checkout/search?q=scrubsync.app"


def test_v3d_porkbun_cart_url_bundle():
    url = porkbun_cart_url(["scrubsync.app", "scrubsync.com", "scrubsync.dev"])
    assert "scrubsync.app+scrubsync.com+scrubsync.dev" in url


# ---------- v3.D register_domain ----------


def test_v3d_register_missing_keys_returns_failure():
    result = register_domain("test.com", api_key="", secret_key="")
    assert result.ok is False
    assert "API keys" in result.detail


def test_v3d_register_success_parses_order_id():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"status": "SUCCESS", "orderId": "ord_123"}

    with patch("portfolio.suggest.requests.post", return_value=fake) as mock_post:
        result = register_domain("scrubsync.app", api_key="k", secret_key="s")

    assert result.ok is True
    assert result.order_id == "ord_123"
    assert "scrubsync.app" in result.detail
    body = mock_post.call_args.kwargs["json"]
    assert body["domain"] == "scrubsync.app"
    assert body["apikey"] == "k"
    assert body["secretapikey"] == "s"


def test_v3d_register_porkbun_error_status():
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"status": "ERROR", "message": "domain not available"}

    with patch("portfolio.suggest.requests.post", return_value=fake):
        result = register_domain("taken.com", api_key="k", secret_key="s")

    assert result.ok is False
    assert "domain not available" in result.detail


def test_v3d_register_http_error():
    fake = MagicMock()
    fake.status_code = 500
    fake.json.return_value = {"message": "server explode"}

    with patch("portfolio.suggest.requests.post", return_value=fake):
        result = register_domain("test.com", api_key="k", secret_key="s")

    assert result.ok is False
    assert "server explode" in result.detail or "500" in result.detail


def test_v3d_register_network_exception():
    with patch("portfolio.suggest.requests.post", side_effect=ConnectionError("no net")):
        result = register_domain("test.com", api_key="k", secret_key="s")
    assert result.ok is False
    assert "ConnectionError" in result.detail or "failed" in result.detail


# ---------- v3.D _money_from_pricing ----------


def test_v3d_money_from_pricing_registration():
    pricing = {"app": {"registration": "10.81", "renewal": "14.93"}}
    assert _money_from_pricing(pricing, ".app") == 10.81
    assert _money_from_pricing(pricing, ".app", key="renewal") == 14.93


def test_v3d_money_from_pricing_missing():
    assert _money_from_pricing({}, ".app") is None
    assert _money_from_pricing({"app": {}}, ".app") is None


# ---------- v3.D _decide_pick ----------


def _state(domain, available=True, price=10.0, over_max=False, com_class=None):
    return CellState(domain=domain, available=available, price=price,
                     over_max=over_max, com_class=com_class)


def test_v3d_pick_skip_when_com_live():
    cells = {".com": _state("x.com", available=False, com_class="live-site"),
             ".app": _state("x.app", available=True)}
    pick, label, why = _decide_pick("x", cells, [".com", ".app"], "live-site", max_price=20.0)
    assert pick is None
    assert label == "skip"
    assert "competing" in why


def test_v3d_pick_com_when_available():
    cells = {".com": _state("x.com", available=True),
             ".app": _state("x.app", available=True)}
    pick, label, why = _decide_pick("x", cells, [".com", ".app"], "available", max_price=20.0)
    assert pick == ".com"
    assert ".com" in why


def test_v3d_pick_app_with_bundle_when_com_available():
    cells = {".com": _state("x.com", available=True),
             ".app": _state("x.app", available=True)}
    pick, label, why = _decide_pick("x", cells, [".app"], "available", max_price=20.0)
    # .com not in visible columns, but available → bundle hint
    assert pick == ".app"
    assert "+bundle" in label


def test_v3d_pick_cheap_when_premium_unavailable():
    cells = {".com": _state("x.com", available=False),
             ".app": _state("x.app", available=False),
             ".dev": _state("x.dev", available=False),
             ".xyz": _state("x.xyz", available=True, price=2.0)}
    pick, label, why = _decide_pick("x", cells, [".com", ".app", ".dev", ".xyz"], None, 20.0)
    assert pick == ".xyz"
    assert "cheap" in why


def test_v3d_pick_question_mark_when_only_unknown():
    cells = {".com": _state("x.com", available=False),
             ".site": _state("x.site", available=None)}
    pick, label, why = _decide_pick("x", cells, [".com", ".site"], None, 20.0)
    assert pick == ".site"
    assert "verify" in label.lower()


def test_v3d_pick_none_when_nothing_available():
    cells = {".com": _state("x.com", available=False),
             ".app": _state("x.app", available=False)}
    pick, label, why = _decide_pick("x", cells, [".com", ".app"], None, 20.0)
    assert pick is None
    assert label == "skip"


# ---------- v3.D build_grid ----------


def _build_avail(map_):
    """Make a (avail, price, error) callable from a {domain: (avail, price)} dict."""
    def _check(d):
        if d in map_:
            v = map_[d]
            return v[0], v[1], None
        return False, None, None
    return _check


def test_v3d_build_grid_simple_all_available():
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {f"scrubs{t}": (True, 10.0) for t in (".com", ".app", ".dev", ".xyz", ".site", ".co")}
    rows = build_grid(cands, "topic", [".com", ".app", ".dev"], _build_avail(avail), max_price=20.0)
    assert len(rows) == 1
    row = rows[0]
    assert row.name == "scrubs"
    assert row.pick_tld == ".com"


def test_v3d_build_grid_picks_app_when_com_taken_but_classifier_not_live():
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {
        "scrubs.com": (False, None),
        "scrubs.app": (True, 11.0),
        "scrubs.dev": (True, 11.0),
    }
    classifier = lambda d: "parked"
    rows = build_grid(cands, "topic", [".com", ".app", ".dev"], _build_avail(avail),
                      max_price=20.0, com_classifier=classifier)
    assert rows[0].pick_tld == ".app"
    assert rows[0].cells[".com"].com_class == "parked"


def test_v3d_build_grid_skip_when_com_is_live_site():
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {
        "scrubs.com": (False, None),
        "scrubs.app": (True, 11.0),
    }
    classifier = lambda d: "live-site"
    rows = build_grid(cands, "topic", [".com", ".app"], _build_avail(avail),
                      max_price=20.0, com_classifier=classifier)
    assert rows[0].pick_tld is None
    assert rows[0].pick_label == "skip"
    # Score must be penalized vs a clean baseline (same name, no .com poison).
    clean_score, _ = score_name("scrubs", "topic", ".com", com_status=None)
    assert rows[0].score == clean_score + SCORE_PENALTY_COM_LIVE


def test_v3d_build_grid_checks_site_via_avail_fn():
    # 2026-05-07: .site is no longer special-cased — it goes through the same
    # avail callable as everything else. (The verify=False routing happens in
    # availability.rdap_check, not in build_grid.)
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {
        "scrubs.com": (True, 11.0),
        "scrubs.app": (True, 11.0),
        "scrubs.site": (True, 2.0),
    }
    called = []
    def check(d):
        called.append(d)
        return avail.get(d, (False, None)) + (None,)

    rows = build_grid(cands, "topic", [".com", ".app", ".site"], check, max_price=20.0)
    assert "scrubs.site" in called
    assert rows[0].cells[".site"].available is True
    assert rows[0].cells[".site"].price == 2.0


def test_v3d_build_grid_over_max_price_marked():
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {
        "scrubs.com": (True, 80.0),       # over max
        "scrubs.app": (True, 11.0),
    }
    rows = build_grid(cands, "topic", [".com", ".app"], _build_avail(avail), max_price=20.0)
    assert rows[0].cells[".com"].over_max is True
    assert rows[0].cells[".app"].over_max is False
    # Over-max .com shouldn't be picked
    assert rows[0].pick_tld == ".app"


def test_v3d_build_grid_renewal_from_pricing_dict():
    cands = [Candidate(name="scrubs", strategy="t")]
    avail = {"scrubs.app": (True, 10.81)}
    pricing = {"app": {"registration": "10.81", "renewal": "14.93"}}
    rows = build_grid(cands, "topic", [".app"], _build_avail(avail),
                      max_price=20.0, pricing_dict=pricing)
    assert rows[0].cells[".app"].renewal == 14.93


# ---------- v3.D run_validation_pipeline ----------


def test_v3d_pipeline_uses_cached_vocab(tmp_path, monkeypatch):
    monkeypatch.setattr(suggest, "CACHE_DIR", tmp_path / "cache")
    strategies = [Strategy(name="t", label="T", description="d")]

    cache_payload = {
        "vocab_terms": ["scrubs", "ppe"],
        "candidates_by_strategy": {"t": [{"name": "scrubsync", "strategy": "t",
                                          "score_base": 0, "score_notes": []}]},
    }

    avail = {"scrubsync.com": (True, 11.0)}
    rows, vocab = run_validation_pipeline(
        topic="x", api_key="sk-fake", strategies=strategies,
        columns=[".com"], avail_check=_build_avail(avail), max_price=20.0,
        cache_payload=cache_payload,
    )
    # Vocab loaded from cache; no OpenAI call needed
    assert vocab == ["scrubs", "ppe"]
    assert len(rows) == 1
    assert rows[0].name == "scrubsync"


def test_v3d_pipeline_extracts_vocab_when_no_cache(monkeypatch):
    """End-to-end: vocab extraction + brainstorm both mocked."""
    strategies = [Strategy(name="t", label="T", description="d", require_anchors=True)]

    fake_vocab_resp = MagicMock()
    fake_vocab_resp.json.return_value = {"output_text": "scrubs\nppe\nshift\n"}
    fake_vocab_resp.raise_for_status = MagicMock()

    fake_brainstorm_resp = MagicMock()
    fake_brainstorm_resp.json.return_value = {"output_text": "scrubsync\nppefit\n"}
    fake_brainstorm_resp.raise_for_status = MagicMock()

    # First request.post → vocab; subsequent → brainstorms
    responses = [fake_vocab_resp, fake_brainstorm_resp]
    def fake_post(url, headers=None, json=None, timeout=None):
        return responses.pop(0)

    avail = {"scrubsync.com": (True, 11.0), "ppefit.com": (True, 11.0)}
    with patch("portfolio.suggest.requests.post", side_effect=fake_post):
        rows, vocab = run_validation_pipeline(
            topic="healthcare workwear", api_key="sk-fake",
            strategies=strategies, columns=[".com"],
            avail_check=_build_avail(avail), max_price=20.0,
        )

    assert "scrubs" in vocab
    assert "ppe" in vocab
    assert len(rows) == 2
    names = {r.name for r in rows}
    assert "scrubsync" in names
    assert "ppefit" in names


def test_v3d_pipeline_handles_vocab_extraction_failure(monkeypatch):
    """If vocab extraction fails, pipeline proceeds with empty anchors (no crash)."""
    strategies = [Strategy(name="t", label="T", description="d", require_anchors=True)]

    fake_brainstorm_resp = MagicMock()
    fake_brainstorm_resp.json.return_value = {"output_text": "scrubsync\n"}
    fake_brainstorm_resp.raise_for_status = MagicMock()

    call_count = {"n": 0}
    def fake_post(url, headers=None, json=None, timeout=None):
        call_count["n"] += 1
        if call_count["n"] == 1:
            # Vocab extraction call → simulate HTTP 500
            raise ConnectionError("vocab API down")
        return fake_brainstorm_resp

    avail = {"scrubsync.com": (True, 11.0)}
    with patch("portfolio.suggest.requests.post", side_effect=fake_post):
        rows, vocab = run_validation_pipeline(
            topic="x", api_key="sk-fake",
            strategies=strategies, columns=[".com"],
            avail_check=_build_avail(avail), max_price=20.0,
        )

    # No vocab, but pipeline still produced rows
    assert vocab == []
    assert len(rows) >= 1


# ---------- v3.D filter_pickable_rows ----------


def test_v3d_filter_pickable_keeps_rows_with_available_cell():
    from portfolio.suggest import filter_pickable_rows
    cands = [Candidate(name="goodname", strategy="t"),
             Candidate(name="alltaken", strategy="t")]
    avail = {
        "goodname.com": (True, 11.0),
        "alltaken.com": (False, None),
        "alltaken.app": (False, None),
    }
    rows = build_grid(cands, "x", [".com", ".app"], _build_avail(avail), max_price=20.0)
    filtered = filter_pickable_rows(rows)
    names = [r.name for r in filtered]
    assert "goodname" in names
    assert "alltaken" not in names


def test_v3d_filter_pickable_drops_rows_with_only_over_max():
    from portfolio.suggest import filter_pickable_rows
    cands = [Candidate(name="expensive", strategy="t")]
    avail = {"expensive.com": (True, 200.0)}  # available but over max
    rows = build_grid(cands, "x", [".com"], _build_avail(avail), max_price=20.0)
    filtered = filter_pickable_rows(rows)
    assert filtered == []


def test_v3d_filter_pickable_drops_rows_with_only_unknown_cells():
    from portfolio.suggest import filter_pickable_rows
    cands = [Candidate(name="unknown", strategy="t")]
    # Avail callable returns (None, None, None) — all unknowns
    def check(d):
        return None, None, None
    rows = build_grid(cands, "x", [".com"], check, max_price=20.0)
    filtered = filter_pickable_rows(rows)
    # `?`-only rows have nothing pickable per the filter rule.
    assert filtered == []


# ---------- v3.D parse_expand_input ----------


def test_v3d_parse_expand_by_row_number():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="alpha", strategy="t"),
            GridRow(name="beta", strategy="t")]
    idx, err = parse_expand_input("e2", rows)
    assert err is None
    assert idx == 1


def test_v3d_parse_expand_by_name_exact():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="alpha", strategy="t"),
            GridRow(name="beta", strategy="t")]
    idx, err = parse_expand_input("e beta", rows)
    assert err is None
    assert idx == 1


def test_v3d_parse_expand_by_full_domain():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="codebeacon", strategy="t")]
    idx, err = parse_expand_input("e codebeacon.site", rows)
    assert err is None
    assert idx == 0


def test_v3d_parse_expand_by_prefix_when_unique():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="codebeacon", strategy="t"),
            GridRow(name="handoffhub", strategy="t")]
    idx, err = parse_expand_input("e code", rows)
    assert err is None
    assert idx == 0


def test_v3d_parse_expand_ambiguous_prefix_errors():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="scrubsync", strategy="t"),
            GridRow(name="scrubsfit", strategy="t")]
    idx, err = parse_expand_input("e scrub", rows)
    assert idx is None
    assert err is not None
    assert "ambiguous" in err.lower()


def test_v3d_parse_expand_no_match_errors():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="alpha", strategy="t")]
    idx, err = parse_expand_input("e nothere", rows)
    assert idx is None
    assert err is not None


def test_v3d_parse_expand_row_out_of_range():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="alpha", strategy="t")]
    idx, err = parse_expand_input("e99", rows)
    assert idx is None
    assert "out of range" in err


def test_v3d_parse_expand_not_an_expand_command():
    from portfolio.cli import parse_expand_input
    rows = [GridRow(name="alpha", strategy="t")]
    idx, err = parse_expand_input("5", rows)
    assert idx is None


# ---------- v3.D _parse_user_added_names ----------


def test_v3d_parse_user_names_basic():
    from portfolio.cli import _parse_user_added_names
    valid, rejected = _parse_user_added_names("alpha, beta, gamma")
    assert valid == ["alpha", "beta", "gamma"]
    assert rejected == []


def test_v3d_parse_user_names_strips_tld_suffix():
    from portfolio.cli import _parse_user_added_names
    valid, _ = _parse_user_added_names("alpha.com, beta.app")
    assert valid == ["alpha", "beta"]


def test_v3d_parse_user_names_rejects_invalid_chars():
    from portfolio.cli import _parse_user_added_names
    valid, rejected = _parse_user_added_names("alpha, b3-ta!, gamma")
    assert "alpha" in valid
    assert "gamma" in valid
    assert any("b3-ta!" in r for r in rejected)


def test_v3d_parse_user_names_rejects_too_long():
    from portfolio.cli import _parse_user_added_names
    valid, rejected = _parse_user_added_names("waytoolongbrandname, ok")
    assert "ok" in valid
    assert any("waytoolong" in r for r in rejected)


def test_v3d_parse_user_names_dedups():
    from portfolio.cli import _parse_user_added_names
    valid, _ = _parse_user_added_names("alpha, alpha, beta, alpha")
    assert valid == ["alpha", "beta"]


def test_v3d_parse_user_names_empty_input():
    from portfolio.cli import _parse_user_added_names
    valid, rejected = _parse_user_added_names("")
    assert valid == []
    assert rejected == []


# ---------- v3.D parse_pick_input (TLD override) ----------


def test_v3d_parse_pick_plain_number():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("5", n_rows=15, columns=[".com", ".app"])
    assert idx == 4
    assert tld is None
    assert err is None


def test_v3d_parse_pick_with_tld_override():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("5.xyz", n_rows=15, columns=[".com", ".app", ".xyz"])
    assert idx == 4
    assert tld == ".xyz"
    assert err is None


def test_v3d_parse_pick_uppercase_normalized():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("3.APP", n_rows=15, columns=[".com", ".app"])
    assert idx == 2
    assert tld == ".app"
    assert err is None


def test_v3d_parse_pick_row_out_of_range():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("99", n_rows=15, columns=[".com"])
    assert idx is None
    assert err is not None
    assert "out of range" in err


def test_v3d_parse_pick_tld_not_in_columns():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("5.tech", n_rows=15, columns=[".com", ".app"])
    assert idx is None
    assert err is not None
    assert ".tech" in err


def test_v3d_parse_pick_garbage_input():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("foo", n_rows=15, columns=[".com"])
    assert idx is None
    assert err is not None


def test_v3d_parse_pick_empty():
    from portfolio.cli import parse_pick_input
    idx, tld, err = parse_pick_input("", n_rows=15, columns=[".com"])
    assert idx is None
    assert err == "empty input"


# ---------- v3.D vocab-anchor scoring + ranking ----------


def test_v3d_vocab_anchor_bonus_added_to_score():
    s_no, _ = score_name("scrubsync", "x", ".com")
    s_yes, notes = score_name("scrubsync", "x", ".com",
                              vocab_terms=["scrubs", "ppe"])
    # Two anchors don't both match; only "scrubs" appears in "scrubsync"
    # Vocab bonus bumped to +10 per match in 2026-05-08.
    assert s_yes == s_no + 10
    assert any("anchors:1" in n for n in notes)


def test_v3d_multi_anchor_name_outranks_single_anchor():
    s1, _ = score_name("scrubfit", "x", ".com",
                       vocab_terms=["scrubs", "fit", "ppe"])
    s2, _ = score_name("flowsync", "x", ".com",
                       vocab_terms=["scrubs", "fit", "ppe"])
    # scrubfit matches "fit" (and not "scrubs" since "s" is missing) → 1 anchor
    # flowsync matches none → 0 anchors
    assert s1 > s2


def test_v3d_two_anchors_outrank_one():
    s_two, _ = score_name("scrubsfit", "x", ".com",
                          vocab_terms=["scrubs", "fit", "ppe"])
    s_one, _ = score_name("scrubsync", "x", ".com",
                          vocab_terms=["scrubs", "fit", "ppe"])
    # scrubsfit matches both "scrubs" and "fit" → 2 anchors → +20
    # scrubsync matches "scrubs" only → 1 anchor → +10
    # Difference: +10 (one extra anchor at the new +10/match weight).
    assert s_two == s_one + 10


def test_v3d_no_vocab_terms_no_bonus():
    s1, _ = score_name("scrubsync", "x", ".com")
    s2, _ = score_name("scrubsync", "x", ".com", vocab_terms=[])
    assert s1 == s2


def test_v3d_anchors_in_helper():
    from portfolio.suggest import _anchors_in
    assert _anchors_in("scrubsfit", ["scrubs", "fit", "ppe"]) == ["scrubs", "fit"]
    assert _anchors_in("flowsync", ["scrubs", "fit"]) == []
    assert _anchors_in("scrubs", None) == []
    assert _anchors_in("scrubs", []) == []


def test_v3d_anchors_in_dedupes_repeated_terms():
    from portfolio.suggest import _anchors_in
    # Even if vocab list has dups, output is unique
    assert _anchors_in("scrubsfit", ["scrubs", "scrubs", "fit"]) == ["scrubs", "fit"]


def test_v3d_build_grid_populates_anchors_matched():
    cands = [Candidate(name="scrubsfit", strategy="t"),
             Candidate(name="flowsync", strategy="t")]
    avail = {f"{c.name}{t}": (True, 11.0)
             for c in cands for t in (".com", ".app")}
    rows = build_grid(cands, "x", [".com", ".app"], _build_avail(avail),
                      max_price=20.0,
                      vocab_terms=["scrubs", "fit", "ppe"])
    by_name = {r.name: r for r in rows}
    assert by_name["scrubsfit"].anchors_matched == ["scrubs", "fit"]
    assert by_name["flowsync"].anchors_matched == []


def test_v3d_build_grid_ranks_multi_anchor_above_single_anchor():
    cands = [
        Candidate(name="scrubsync", strategy="t"),  # 1 anchor
        Candidate(name="scrubsfit", strategy="t"),  # 2 anchors
        Candidate(name="flowsync", strategy="t"),   # 0 anchors
    ]
    avail = {f"{c.name}{t}": (True, 11.0)
             for c in cands for t in (".com", ".app")}
    rows = build_grid(cands, "x", [".com", ".app"], _build_avail(avail),
                      max_price=20.0,
                      vocab_terms=["scrubs", "fit"])
    # Order: scrubsfit (2 anchors) > scrubsync (1) > flowsync (0)
    names = [r.name for r in rows]
    assert names == ["scrubsfit", "scrubsync", "flowsync"]


def test_v3d_build_grid_length_breaks_score_ties():
    """When score and anchor count are equal, shorter name wins."""
    cands = [
        Candidate(name="scrub", strategy="t"),     # short, 1 anchor
        Candidate(name="scrubblah", strategy="t"), # longer, 1 anchor
    ]
    # Same anchor count (both match "scrub" since it's a substring), same TLD.
    avail = {f"{c.name}{t}": (True, 11.0)
             for c in cands for t in (".com",)}
    rows = build_grid(cands, "x", [".com"], _build_avail(avail),
                      max_price=20.0,
                      vocab_terms=["scrub"])
    # `scrub` (5 chars) ranks above `scrubblah` (9 chars) — but only when
    # the short-length scoring bonus also matches. Both names ≤9 chars so
    # both get +6. Both match "scrub" → +5 each. Score-equal: length tiebreaks.
    names = [r.name for r in rows]
    assert names[0] == "scrub"


# ---------- v3.D renewal-cliff cell marker ----------


def test_v3d_renewal_cliff_marker_present_when_renewal_high():
    from portfolio.cli import _renewal_cliff_marker
    # .site: $2 reg / $30 renewal → 15x
    out = _renewal_cliff_marker(price=2.0, renewal=30.0)
    assert "↑15x" in out


def test_v3d_renewal_cliff_marker_absent_when_close():
    from portfolio.cli import _renewal_cliff_marker
    # .com: $11 reg / $11 renewal → 1x → no marker
    assert _renewal_cliff_marker(price=11.0, renewal=11.0) == ""
    # .xyz: $2 reg / $13 renewal → 6.5x → marker
    assert "↑" in _renewal_cliff_marker(price=2.0, renewal=13.0)


def test_v3d_renewal_cliff_marker_skips_when_data_missing():
    from portfolio.cli import _renewal_cliff_marker
    assert _renewal_cliff_marker(None, None) == ""
    assert _renewal_cliff_marker(2.0, None) == ""
    assert _renewal_cliff_marker(None, 30.0) == ""


def test_v3d_renewal_cliff_threshold_at_two_x():
    """Boundary: ratio ≤ 2.0 → no marker; ratio > 2.0 → marker."""
    from portfolio.cli import _renewal_cliff_marker
    assert _renewal_cliff_marker(10.0, 20.0) == ""    # exactly 2x: no marker
    assert "↑" in _renewal_cliff_marker(10.0, 20.5)   # just over 2x: marker


def test_v3d_pipeline_dedupes_across_strategies():
    """Same name appearing in two strategies should produce one row, not two."""
    strategies = [
        Strategy(name="a", label="A", description="d"),
        Strategy(name="b", label="B", description="d"),
    ]

    fake_vocab = MagicMock()
    fake_vocab.json.return_value = {"output_text": "scrubs\n"}
    fake_vocab.raise_for_status = MagicMock()

    fake_brainstorm = MagicMock()
    fake_brainstorm.json.return_value = {"output_text": "scrubsync\n"}
    fake_brainstorm.raise_for_status = MagicMock()

    responses = [fake_vocab, fake_brainstorm, fake_brainstorm]  # vocab + 2 strategies
    def fake_post(url, headers=None, json=None, timeout=None):
        return responses.pop(0)

    avail = {"scrubsync.com": (True, 11.0)}
    with patch("portfolio.suggest.requests.post", side_effect=fake_post):
        rows, _ = run_validation_pipeline(
            topic="x", api_key="sk-fake",
            strategies=strategies, columns=[".com"],
            avail_check=_build_avail(avail), max_price=20.0,
        )

    names = [r.name for r in rows]
    assert names.count("scrubsync") == 1


# =============================================================================
# v3.D — strict porn screen (3 layers)
# =============================================================================

from portfolio.suggest import (
    LOCAL_PORN_BLOCKLIST,
    MODERATION_THRESHOLD_SEXUAL,
    MODERATION_THRESHOLD_SEXUAL_MINORS,
    _screen_layer1,
    _screen_layer2,
    _screen_layer3,
    screen_for_content_strict,
)


# ---------- Layer 1: local blocklist ----------


def test_screen_layer1_blocks_obvious_terms():
    names = ["pornhub", "xxxsite", "milfhub", "bdsmtools",
             "smutbox", "nsfwapi", "fetishlab", "kinkbox",
             "slutapp", "whorehub", "fucker", "cuntware",
             "twatcorp", "fapdaily", "incestbox", "pedolab"]
    kept, dropped = _screen_layer1(names)
    assert kept == []
    assert {n for n, _ in dropped} == set(names)
    assert all(reason == "local" for _, reason in dropped)


def test_screen_layer1_keeps_innocent_names():
    names = ["scrubsync", "doffeasy", "handoffhub", "ppefit",
             "gownsync", "coatlink", "shiftsafe", "badgehq"]
    kept, dropped = _screen_layer1(names)
    assert kept == names
    assert dropped == []


def test_screen_layer1_doesnt_block_essex_or_asset():
    """Critical: short ambiguous terms (sex, ass, dick, tit) are NOT in the
    local list. essex/asset/dictionary/title etc. must pass Layer 1."""
    innocent = ["essex", "asset", "passport", "title", "dictionary",
                "predict", "analysis", "moral", "peacock"]
    kept, dropped = _screen_layer1(innocent)
    assert kept == innocent
    assert dropped == []


# ---------- Layer 2: OpenAI moderation ----------


def _moderation_response(scores_per_name):
    """Build a fake OpenAI /v1/moderations response payload."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {
        "results": [
            {"flagged": False, "categories": {}, "category_scores": s}
            for s in scores_per_name
        ]
    }
    fake.raise_for_status = MagicMock()
    return fake


def test_screen_layer2_moderation_drops_high_sexual_score(monkeypatch):
    fake = _moderation_response([
        {"sexual": 0.01, "sexual/minors": 0.0},  # safe
        {"sexual": 0.8, "sexual/minors": 0.0},   # drop
    ])
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer2(["alpha", "porny"], api_key="sk-fake")
    assert kept == ["alpha"]
    assert dropped == [("porny", "moderation")]


def test_screen_layer2_keeps_low_sexual_score(monkeypatch):
    fake = _moderation_response([{"sexual": 0.01, "sexual/minors": 0.0}])
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer2(["alpha"], api_key="sk-fake")
    assert kept == ["alpha"]
    assert dropped == []


def test_screen_layer2_threshold_at_0_05(monkeypatch):
    """Boundary: sexual=0.04 keeps, sexual=0.06 drops."""
    fake = _moderation_response([
        {"sexual": 0.04, "sexual/minors": 0.0},  # under → keep
        {"sexual": 0.06, "sexual/minors": 0.0},  # over → drop
    ])
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer2(["under", "over"], api_key="sk-fake")
    assert kept == ["under"]
    assert dropped == [("over", "moderation")]


def test_screen_layer2_drops_minors_at_low_threshold(monkeypatch):
    """sexual/minors threshold is 0.01 — much stricter than `sexual`."""
    fake = _moderation_response([
        {"sexual": 0.001, "sexual/minors": 0.005},  # both under
        {"sexual": 0.001, "sexual/minors": 0.02},   # minors over → drop
    ])
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer2(["safe", "minorsbad"], api_key="sk-fake")
    assert kept == ["safe"]
    assert dropped == [("minorsbad", "moderation")]


def test_screen_layer2_silently_continues_on_api_failure(monkeypatch):
    with patch("portfolio.suggest.requests.post",
               side_effect=ConnectionError("network down")):
        kept, dropped = _screen_layer2(["alpha", "beta"], api_key="sk-fake")
    assert kept == ["alpha", "beta"]
    assert dropped == []


def test_screen_layer2_silently_continues_on_http_500(monkeypatch):
    fake = MagicMock(status_code=500)
    fake.raise_for_status.side_effect = requests.HTTPError("500")
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer2(["alpha"], api_key="sk-fake")
    assert kept == ["alpha"]
    assert dropped == []


def test_screen_layer2_skipped_when_api_key_missing():
    kept, dropped = _screen_layer2(["alpha", "beta"], api_key="")
    assert kept == ["alpha", "beta"]
    assert dropped == []


# ---------- Layer 3: gpt-5-mini adjacency ----------


def _layer3_response(text):
    """Build a fake /v1/responses payload for the Layer 3 prompt."""
    fake = MagicMock()
    fake.status_code = 200
    fake.json.return_value = {"output_text": text}
    fake.raise_for_status = MagicMock()
    return fake


def test_screen_layer3_drops_when_llm_says_drop(monkeypatch):
    fake = _layer3_response("scrubsync: KEEP\npornhub: DROP\n")
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer3(["scrubsync", "pornhub"], api_key="sk-fake")
    assert kept == ["scrubsync"]
    assert dropped == [("pornhub", "adjacency")]


def test_screen_layer3_keeps_when_llm_says_keep(monkeypatch):
    fake = _layer3_response("alpha: KEEP\nbeta: KEEP\n")
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer3(["alpha", "beta"], api_key="sk-fake")
    assert kept == ["alpha", "beta"]
    assert dropped == []


def test_screen_layer3_silently_continues_on_api_failure(monkeypatch):
    with patch("portfolio.suggest.requests.post",
               side_effect=ConnectionError("down")):
        kept, dropped = _screen_layer3(["alpha"], api_key="sk-fake")
    assert kept == ["alpha"]
    assert dropped == []


def test_screen_layer3_handles_messy_llm_output(monkeypatch):
    """Whitespace tolerance, missing entries default to KEEP, extra commentary
    around the verdict word — all parsed safely."""
    fake = _layer3_response(
        "  scrubsync : KEEP \n"
        "PORNHUB:DROP — well-known adult site\n"
        "extra commentary here\n"
        # 'unmentioned' is missing from output: defaults to KEEP
    )
    with patch("portfolio.suggest.requests.post", return_value=fake):
        kept, dropped = _screen_layer3(
            ["scrubsync", "pornhub", "unmentioned"], api_key="sk-fake"
        )
    assert "scrubsync" in kept
    assert "unmentioned" in kept
    assert ("pornhub", "adjacency") in dropped


def test_screen_layer3_skipped_when_api_key_missing():
    kept, dropped = _screen_layer3(["alpha"], api_key="")
    assert kept == ["alpha"]
    assert dropped == []


# ---------- Pipeline / integration ----------


def test_screen_pipeline_local_first_skips_apis(monkeypatch):
    """A name caught by Layer 1 must never reach the API layers."""
    api_calls = []

    def track_post(url, **kw):
        api_calls.append(url)
        return MagicMock()  # would normally fail validation, but shouldn't be called

    with patch("portfolio.suggest.requests.post", side_effect=track_post):
        kept, dropped = screen_for_content_strict(["pornhub"], api_key="sk-fake")
    # Local layer caught it; no APIs hit.
    # (Layer 2/3 receive empty list and skip since `kept` is empty.)
    assert kept == []
    assert dropped == [("pornhub", "local")]
    assert api_calls == []


def test_screen_no_api_key_runs_layer1_only():
    """With no api_key, only Layer 1 runs; Layers 2/3 are bypassed."""
    kept, dropped = screen_for_content_strict(
        ["pornhub", "scrubsync"], api_key="",
    )
    assert kept == ["scrubsync"]
    assert dropped == [("pornhub", "local")]


def test_screen_pipeline_calls_log_fn_when_dropping(monkeypatch):
    """Single dim summary line; never lists flagged terms."""
    logs = []
    kept, dropped = screen_for_content_strict(
        ["pornhub", "scrubsync"], api_key="",
        log_fn=logs.append,
    )
    assert len(logs) == 1
    assert "filtered" in logs[0].lower()
    assert "pornhub" not in logs[0]  # don't display flagged terms
    assert "1" in logs[0]


def test_screen_pipeline_no_log_when_nothing_dropped():
    logs = []
    kept, dropped = screen_for_content_strict(
        ["scrubsync", "doffeasy"], api_key="",
        log_fn=logs.append,
    )
    assert logs == []
    assert dropped == []


def test_screen_thresholds_are_strict_constants():
    """Sanity-pin the strict thresholds so a future refactor can't loosen
    them silently."""
    assert MODERATION_THRESHOLD_SEXUAL == 0.05
    assert MODERATION_THRESHOLD_SEXUAL_MINORS == 0.01


def test_local_blocklist_has_expected_terms():
    expected = {"porn", "xxx", "milf", "bdsm", "smut", "nsfw",
                "fetish", "kink", "slut", "whore", "fuck", "cunt",
                "twat", "fap", "incest", "pedo"}
    assert LOCAL_PORN_BLOCKLIST == expected


def test_local_blocklist_excludes_short_ambiguous_terms():
    """Critical: these short terms are deliberately NOT in the blocklist
    (they substring into innocent words)."""
    for term in ["sex", "ass", "dick", "tit", "anal", "oral", "cock"]:
        assert term not in LOCAL_PORN_BLOCKLIST


# ---------- brainstorm() integration ----------


def test_brainstorm_calls_screen_after_extract(monkeypatch):
    """brainstorm runs the screen on extracted names before returning."""
    fake = MagicMock()
    fake.json.return_value = {"output_text": "scrubsync\npornhub\n"}
    fake.raise_for_status = MagicMock()

    with patch("portfolio.suggest.requests.post", return_value=fake):
        cands = brainstorm(
            "idea", Strategy("trendy", "Trendy", "desc"),
            history=[], api_key="sk-test",
        )
    names = [c.name for c in cands]
    assert "scrubsync" in names
    assert "pornhub" not in names  # caught by Layer 1


def test_brainstorm_logs_filter_count_when_present(monkeypatch):
    fake = MagicMock()
    fake.json.return_value = {"output_text": "scrubsync\npornhub\n"}
    fake.raise_for_status = MagicMock()

    logs = []
    with patch("portfolio.suggest.requests.post", return_value=fake):
        cands = brainstorm(
            "idea", Strategy("trendy", "Trendy", "desc"),
            history=[], api_key="sk-test", log_fn=logs.append,
        )
    # The screen logs once when something was dropped.
    assert any("filtered" in m.lower() for m in logs)


# =============================================================================
# v3.E — post-grid menu (cli.py)
# =============================================================================


def test_v3e_menu_items_only_active_features():
    """v3.E ships menu slots 1, 2, 5, 8 only; 3/4/6/7 are reserved for v4.A
    (finalists / ask AI / widen) and not present in MENU_ITEMS yet."""
    from portfolio.cli import MENU_ITEMS
    keys = [k for k, _, _ in MENU_ITEMS]
    assert keys == ["1", "2", "5", "8"]


def test_v3e_menu_items_all_active():
    """Every entry in MENU_ITEMS for v3.E is active (no coming-soon stubs)."""
    from portfolio.cli import MENU_ITEMS
    for _, _, coming_soon in MENU_ITEMS:
        assert coming_soon is False


def test_v3e_menu_keys_hint_format():
    """The bad-input hint is generated from MENU_ITEMS — keeps in sync."""
    from portfolio.cli import _menu_keys_hint
    assert _menu_keys_hint() == "1, 2, 5, 8"


def test_v3e_render_menu_includes_active_items_and_quit():
    """Snapshot-ish: _render_menu prints the four active items + 'q. Quit'."""
    from portfolio.cli import _render_menu, console
    with console.capture() as cap:
        _render_menu()
    out = cap.get()
    for key in ("1.", "2.", "5.", "8.", "q."):
        assert key in out


def test_v3e_render_menu_does_not_show_coming_soon():
    """v3.E menu has no '(coming soon)' annotation since stubs were dropped."""
    from portfolio.cli import _render_menu, console
    with console.capture() as cap:
        _render_menu()
    out = cap.get()
    assert "coming soon" not in out


# ---------- _menu_pick ----------


def _make_grid_row(name: str, picks: dict | None = None):
    """Helper: GridRow with cells populated for testing menu actions."""
    from portfolio.suggest import GridRow, CellState
    row = GridRow(name=name, strategy="t",
                  pick_tld=".com", pick_label=".com", why=".com available",
                  score=10)
    if picks is None:
        picks = {".com": (True, 11.0), ".app": (True, 11.0)}
    for tld, (avail, price) in picks.items():
        row.cells[tld] = CellState(domain=f"{name}{tld}", available=avail, price=price)
    return row


def test_v3e_menu_pick_returns_row_and_tld_on_valid_input():
    from portfolio.cli import _menu_pick
    rows = [_make_grid_row("alpha"), _make_grid_row("beta")]
    with patch("portfolio.cli.typer.prompt", return_value="2"):
        result = _menu_pick(rows, [".com", ".app"])
    assert result is not None
    row, tld = result
    assert row.name == "beta"
    assert tld == ".com"


def test_v3e_menu_pick_handles_tld_override():
    from portfolio.cli import _menu_pick
    rows = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value="1.app"):
        result = _menu_pick(rows, [".com", ".app"])
    assert result is not None
    _, tld = result
    assert tld == ".app"


def test_v3e_menu_pick_returns_none_on_empty_input():
    from portfolio.cli import _menu_pick
    rows = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value=""):
        assert _menu_pick(rows, [".com"]) is None


def test_v3e_menu_pick_returns_none_on_out_of_range():
    from portfolio.cli import _menu_pick
    rows = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value="99"):
        assert _menu_pick(rows, [".com"]) is None


def test_v3e_menu_pick_rejects_taken_override():
    from portfolio.cli import _menu_pick
    rows = [_make_grid_row("alpha", picks={".com": (False, None), ".app": (True, 11.0)})]
    with patch("portfolio.cli.typer.prompt", return_value="1.com"):
        assert _menu_pick(rows, [".com", ".app"]) is None


# ---------- _menu_expand ----------


def test_v3e_menu_expand_prefixes_e_for_parser():
    """User types `5` at the expand sub-prompt — the helper prepends `e ` so
    parse_expand_input recognizes it."""
    from portfolio.cli import _menu_expand
    rows = [_make_grid_row("alpha"), _make_grid_row("beta")]
    # Mock typer.prompt to return "1" first (which row), then "b" (back) inside _expand_and_pick.
    prompts = iter(["1", "b"])
    with patch("portfolio.cli.typer.prompt", side_effect=lambda *a, **kw: next(prompts)):
        result = _menu_expand(rows, [".com"], max_price=20.0, show_renewal=False)
    # `b` from expand view → None back to menu
    assert result is None


def test_v3e_menu_expand_returns_none_on_empty_input():
    from portfolio.cli import _menu_expand
    rows = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value=""):
        assert _menu_expand(rows, [".com"], 20.0, False) is None


def test_v3e_menu_expand_returns_none_on_unknown_name():
    from portfolio.cli import _menu_expand
    rows = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value="nothere"):
        assert _menu_expand(rows, [".com"], 20.0, False) is None


# ---------- _menu_add_names ----------


def test_v3e_menu_add_names_empty_input_returns_rows_unchanged():
    from portfolio.cli import _menu_add_names
    rows_before = [_make_grid_row("alpha")]
    with patch("portfolio.cli.typer.prompt", return_value=""):
        rows_after = _menu_add_names(
            rows_before, topic="x", openai_key="",
            vocab_terms=[], tld_list=[".com"],
            max_price=20.0, pricing_dict={}, avail_fn=lambda d: (True, 11.0, None),
            show_renewal=False, log_fn=None,
        )
    assert rows_after is rows_before


def test_v3e_menu_add_names_merges_validated_names():
    """When user types valid names, _menu_add_names probes them and merges."""
    from portfolio.cli import _menu_add_names
    rows_before = [_make_grid_row("alpha")]
    avail_map = {f"newone{t}": (True, 11.0, None) for t in (".com", ".app", ".dev",
                                                              ".xyz", ".site", ".co",
                                                              ".ai", ".io", ".shop",
                                                              ".life", ".info", ".pro")}

    def fake_avail(d):
        return avail_map.get(d, (False, None, None))

    # Stub screen_for_content_strict (no API key → only Layer 1 runs anyway,
    # but make sure the function returns the names through).
    def stub_screen(names, api_key, log_fn=None):
        return list(names), []

    with patch("portfolio.cli.typer.prompt", return_value="newone"), \
         patch("portfolio.suggest.screen_for_content_strict", side_effect=stub_screen):
        rows_after = _menu_add_names(
            rows_before, topic="x", openai_key="",
            vocab_terms=[], tld_list=[".com", ".app"],
            max_price=20.0, pricing_dict={}, avail_fn=fake_avail,
            show_renewal=False, log_fn=None,
        )
    names_after = [r.name for r in rows_after]
    assert "newone" in names_after
    assert "alpha" in names_after  # original survived


# ---------- TLD reference (option 8) ----------


def test_v3e_tld_reference_constant_has_expected_tlds():
    from portfolio.cli import TLD_REFERENCE
    tlds = [e["tld"] for e in TLD_REFERENCE]
    for required in (".com", ".app", ".dev", ".xyz", ".site", ".co",
                     ".ai", ".io", ".shop", ".life", ".info", ".pro"):
        assert required in tlds, f"missing {required}"


def test_v3e_tld_reference_grades_are_valid():
    """Every grade is one of A+/A/A-/B+/B/C+/C — same scheme used in chat."""
    from portfolio.cli import TLD_REFERENCE
    valid_grades = {"A+", "A", "A-", "B+", "B", "C+", "C"}
    for entry in TLD_REFERENCE:
        assert entry["grade"] in valid_grades, f"{entry['tld']} has unexpected grade {entry['grade']}"


def test_v3e_tld_reference_each_entry_has_full_card_fields():
    """Every entry must have all the fields the renderer prints."""
    from portfolio.cli import TLD_REFERENCE
    required_keys = {"tld", "grade", "operator", "reg", "renew",
                     "vibe", "trust", "seo", "best_for", "catch"}
    for entry in TLD_REFERENCE:
        missing = required_keys - set(entry.keys())
        assert not missing, f"{entry.get('tld', '?')} missing fields: {missing}"


def test_v3e_render_tld_reference_prints_card_format_for_known_tlds():
    """Card output includes operator/SEO/vibe lines, not just a tabular row."""
    from portfolio.cli import _render_tld_reference, console
    with console.capture() as cap:
        _render_tld_reference()
    out = cap.get()
    # TLDs the user explicitly graded
    for tld in (".com", ".app", ".dev", ".xyz", ".site"):
        assert tld in out
    # Card format markers — the labels printed for every entry
    assert "operator" in out
    assert "reg/renew" in out
    assert "trust" in out
    assert "SEO" in out
    assert "best for" in out
    assert "catch" in out
    # Grades present
    assert "A+" in out
    assert "C" in out
    # The Google Registry citation for .app / .dev appears verbatim
    assert "Google Registry (2018)" in out
    assert "Google Registry (2019)" in out
    # Renewal-cliff annotation for .site present
    assert "$30" in out


def test_v3e_render_tld_reference_includes_validation_summary():
    from portfolio.cli import _render_tld_reference, console
    with console.capture() as cap:
        _render_tld_reference()
    out = cap.get()
    # The closing summary line should land at the bottom of the output.
    assert "validation pipeline" in out
    assert ".app and .dev are honest peers" in out
