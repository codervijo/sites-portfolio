"""Tests for v8.D — three-gate skeleton (`portfolio.research_gates`).

The original three-gate skeleton commit added the dataclass /
orchestrator scaffold. Subsequent commits filled in the gate logic
(volume math, classifiers, moat handling, verdict synthesis). These
tests fix the *shape* so any of those follow-ups can't accidentally
break the contract.
"""
from __future__ import annotations

import pytest

from portfolio.research_gates import (
    GATE_1_VOLUME_THRESHOLD,
    GATE_2_BEATABLE_THRESHOLD,
    LABEL_FAIL,
    LABEL_PASS,
    LABEL_PENDING,
    LABEL_WEAK_PASS,
    VERDICT_GO,
    VERDICT_NICHE_DOWN,
    VERDICT_NO_GO,
    GateResult,
    GateResults,
    OperatorFitResult,
    _query_is_polluted,
    _stem,
    _tokenize_stems,
    evaluate_cluster,
    evaluate_gate_1,
    evaluate_gate_2,
    evaluate_gate_3,
    is_moat_required,
    synthesize_verdict,
)


# ---------- helpers ----------


def _query_payload(query: str, titles: list[str]) -> dict:
    """Build a `serp-query-v1`-shaped dict with the given top-N titles."""
    return {
        "schema": "serp-query-v1",
        "query": query,
        "organic_results": [
            {"position": i + 1, "title": t, "url": f"https://x.test/{i}",
             "domain": "x.test", "snippet": "", "displayed_link": "x.test"}
            for i, t in enumerate(titles)
        ],
        "features": {},
    }


def _cluster(topic: str, queries_with_titles: list[tuple[str, list[str]]],
             source: str = "serpapi") -> dict:
    return {
        "schema": "research-cluster-v2",
        "topic": topic,
        "source": source,
        "cluster_queries": [q for q, _ in queries_with_titles],
        "per_query_results": [_query_payload(q, t) for q, t in queries_with_titles],
    }


# ---------- constants ----------


def test_label_constants_are_distinct():
    assert {LABEL_PASS, LABEL_FAIL, LABEL_WEAK_PASS, LABEL_PENDING} == \
        {"PASS", "FAIL", "WEAK-PASS", "PENDING"}


def test_verdict_constants_are_distinct():
    assert {VERDICT_GO, VERDICT_NICHE_DOWN, VERDICT_NO_GO} == \
        {"GO", "NICHE-DOWN", "NO-GO"}


def test_gate_1_threshold_matches_prd():
    """PRD §P2.2: pollution-adjusted volume must be ≥5K SV/month to PASS."""
    assert GATE_1_VOLUME_THRESHOLD == 5000


def test_gate_2_beatable_threshold_matches_prd():
    """PRD §P2.3: at least 3 POTENTIALLY_BEATABLE results to PASS."""
    assert GATE_2_BEATABLE_THRESHOLD == 3


# ---------- GateResult / GateResults dataclass ----------


def test_gate_result_serializes_to_dict():
    r = GateResult(passed=True, label=LABEL_PASS,
                   findings=["12K SV"], raw={"volume": 12000})
    d = r.to_dict()
    assert d == {
        "passed": True, "label": "PASS",
        "findings": ["12K SV"], "raw": {"volume": 12000},
    }


def test_gate_result_defaults():
    """Empty findings + raw default to empty list / dict."""
    r = GateResult(passed=False, label=LABEL_FAIL)
    assert r.findings == []
    assert r.raw == {}


def test_gate_result_passed_can_be_none():
    """PENDING gates carry passed=None — verdict logic treats as fail."""
    r = GateResult(passed=None, label=LABEL_PENDING)
    assert r.passed is None


def test_operator_fit_result_defaults_empty():
    op = OperatorFitResult()
    assert op.warnings == []
    assert op.auto_fail_gate_2 is False


def test_gate_results_to_dict_round_trips():
    g1 = GateResult(passed=True, label=LABEL_PASS, findings=["m1"])
    g2 = GateResult(passed=False, label=LABEL_FAIL, findings=["s1"])
    g3 = GateResult(passed=None, label=LABEL_PENDING)
    op = OperatorFitResult(warnings=["w"], auto_fail_gate_2=True)
    r = GateResults(
        gate_1_market=g1, gate_2_serp=g2, gate_3_moat=g3,
        operator_fit=op, verdict=VERDICT_NICHE_DOWN,
        suggested_reductions=["narrow to EV"],
        moat_required=True, moat_provided="my-edge",
    )
    d = r.to_dict()
    assert d["verdict"] == "NICHE-DOWN"
    assert d["gate_1_market"]["label"] == "PASS"
    assert d["gate_2_serp"]["label"] == "FAIL"
    assert d["gate_3_moat"]["label"] == "PENDING"
    assert d["operator_fit"]["auto_fail_gate_2"] is True
    assert d["suggested_reductions"] == ["narrow to EV"]
    assert d["moat_required"] is True
    assert d["moat_provided"] == "my-edge"


def test_gate_results_to_dict_keys_match_schema():
    """The dict keys are the slots that get written into the cluster
    snapshot's `gates` / `verdict` / `operator_fit` fields. Locked here
    so the renderer / cache layer can rely on them."""
    g = GateResult(passed=True, label=LABEL_PASS)
    r = GateResults(
        gate_1_market=g, gate_2_serp=g, gate_3_moat=g,
        operator_fit=OperatorFitResult(),
        verdict=VERDICT_GO,
    )
    d = r.to_dict()
    assert set(d.keys()) == {
        "gate_1_market", "gate_2_serp", "gate_3_moat",
        "operator_fit", "verdict",
        "suggested_reductions", "moat_required", "moat_provided",
    }


# ---------- stub gate functions ----------


def test_evaluate_gate_2_empty_cluster_weak_pass():
    """Empty cluster: no kill-tier fires, but also no beatable results.
    Result is WEAK-PASS (passed=True, but findings flag the void)."""
    r = evaluate_gate_2({"topic": "x", "cluster_queries": [],
                        "per_query_results": []}, media_pubs={})
    assert r.label == LABEL_WEAK_PASS
    assert r.passed is True


def test_evaluate_gate_3_not_required_returns_pass():
    """When Gate 2 didn't detect a specialty/programmatic incumbent,
    Gate 3 is a free PASS regardless of moat input."""
    g2 = GateResult(passed=True, label=LABEL_PASS, raw={"classifications": {}})
    r = evaluate_gate_3(g2, None)
    assert r.label == LABEL_PASS
    assert r.passed is True
    assert r.raw["required"] is False


def test_evaluate_gate_3_required_with_moat_passes():
    """Moat required + sentence provided → PASS, sentence stored."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "specialty_incumbent": {"present": True, "incumbents": {"x.com": ["q"]}},
            "programmatic_at_scale": {"present": False, "incumbents": {}},
        }
    })
    r = evaluate_gate_3(g2, "I will win on X because Y, and Z can't close it in 6mo.")
    assert r.passed is True
    assert r.label == LABEL_PASS
    assert "I will win on X" in r.raw["moat_sentence"]
    assert r.raw["required"] is True


def test_evaluate_gate_3_required_empty_input_interactive_fails():
    """Moat required + empty sentence + interactive mode → FAIL."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "specialty_incumbent": {"present": True, "incumbents": {"x.com": ["q"]}},
        }
    })
    r = evaluate_gate_3(g2, None, non_interactive=False)
    assert r.passed is False
    assert r.label == LABEL_FAIL


def test_evaluate_gate_3_required_empty_input_non_interactive_pending():
    """Moat required + empty sentence + non-interactive mode → PENDING.
    User can re-run without --non-interactive to fill it in."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "specialty_incumbent": {"present": True, "incumbents": {"x.com": ["q"]}},
        }
    })
    r = evaluate_gate_3(g2, None, non_interactive=True)
    assert r.passed is None
    assert r.label == LABEL_PENDING


def test_evaluate_gate_3_strips_whitespace_only_sentence():
    """A sentence that's only whitespace counts as empty."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "programmatic_at_scale": {"present": True, "incumbents": {"x.com": ["a", "b", "c"]}}
        }
    })
    r = evaluate_gate_3(g2, "   \n\t  ", non_interactive=False)
    assert r.passed is False
    assert r.label == LABEL_FAIL


def test_evaluate_gate_3_required_with_programmatic_only():
    """PROGRAMMATIC_AT_SCALE alone also triggers moat-required."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "specialty_incumbent": {"present": False, "incumbents": {}},
            "programmatic_at_scale": {"present": True, "incumbents": {"e.com": ["a", "b", "c"]}},
        }
    })
    r = evaluate_gate_3(g2, "valid moat sentence")
    assert r.passed is True
    assert r.raw["required"] is True


# ---------- Gate 1: stemmer + tokenizer ----------


def test_stem_strips_common_suffixes():
    assert _stem("running") == "runn"
    assert _stem("installation") == "install"
    assert _stem("plugins") == "plugin"
    assert _stem("vehicles") == "vehicl"


def test_stem_preserves_short_tokens():
    """Tokens that would become <3 chars after stripping are left alone."""
    assert _stem("ev") == "ev"
    assert _stem("car") == "car"
    assert _stem("ai") == "ai"


def test_tokenize_stems_drops_stopwords():
    out = _tokenize_stems("the best EV charger for a home")
    # `the`, `best`, `for`, `a` are stopwords.
    assert "the" not in out
    assert "best" not in out
    assert "for" not in out
    assert "ev" in out
    assert "home" in out


def test_tokenize_stems_empty():
    assert _tokenize_stems("") == set()
    assert _tokenize_stems("   ") == set()


def test_tokenize_stems_splits_punctuation():
    out = _tokenize_stems("how-to: install an EV charger!")
    assert "install" in out
    assert "ev" in out
    # "charger" → light stemmer strips the "er" suffix → "charg"
    assert "charg" in out


# ---------- Gate 1: pollution detection ----------


def test_query_is_polluted_when_no_titles_match():
    """Top-3 titles about Tesla Model 3 won't stem-match an EV-charger cluster."""
    payload = _query_payload("ev charger installation cost", [
        "2026 Tesla Model 3 Review",
        "Top 10 Sports Cars of 2026",
        "Used Honda Civics Under $10K",
    ])
    cluster_stems = _tokenize_stems("ev charger installation cost")
    assert _query_is_polluted(payload, cluster_stems) is True


def test_query_is_polluted_false_when_one_title_matches():
    """At least one stem-match is enough to mark unpolluted."""
    payload = _query_payload("ev charger installation cost", [
        "How to Install an EV Charger at Home",
        "Random unrelated title",
        "Another random one",
    ])
    cluster_stems = _tokenize_stems("ev charger installation cost")
    assert _query_is_polluted(payload, cluster_stems) is False


def test_query_is_polluted_when_no_organic_results():
    """0-results query treated as polluted (PRD §8.J option 1)."""
    payload = {"query": "x", "organic_results": []}
    assert _query_is_polluted(payload, {"foo", "bar"}) is True


def test_query_is_polluted_only_inspects_top_3():
    """4th result shouldn't rescue a polluted top-3."""
    payload = _query_payload("ev charger", [
        "Tesla news",
        "Tesla rumor",
        "Used cars",
        # 4th and beyond ignored:
        "EV Charger installation guide",
    ])
    cluster_stems = _tokenize_stems("ev charger")
    assert _query_is_polluted(payload, cluster_stems) is True


# ---------- Gate 1: full evaluation ----------


def _const_estimator(per_query_volume: int):
    """Return a fake volume estimator that gives every query the same SV."""
    def _est(queries):
        return {q: per_query_volume for q in queries}
    return _est


def _explicit_estimator(volumes: dict[str, int]):
    """Return a fake estimator that uses an exact lookup table."""
    def _est(queries):
        return {q: volumes.get(q, 0) for q in queries}
    return _est


def test_gate_1_passes_when_clean_cluster_meets_threshold():
    """Clean cluster (no pollution) + 1500 SV × 5 = 7500 ≥ 5000 → PASS."""
    cluster = _cluster("ev charger installation cost", [
        ("ev charger installation cost", ["Best EV Charger Installation Tips", "x", "y"]),
        ("home ev charger installation", ["Home EV Charger Setup", "x", "y"]),
        ("cost of ev charging at home", ["EV Home Charging Costs", "x", "y"]),
        ("level 2 ev charger install", ["Level 2 EV Charger Install Guide", "x", "y"]),
        ("ev charger wiring", ["EV Charger Wiring Basics", "x", "y"]),
    ])
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(1500))
    assert r.passed is True
    assert r.label == LABEL_PASS
    assert r.raw["pollution_adjusted_volume"] == 7500
    assert r.raw["polluted_queries"] == []
    assert "low-confidence" in " ".join(r.findings).lower()


def test_gate_1_fails_when_volume_below_threshold():
    cluster = _cluster("niche topic", [
        ("niche topic about widgets", ["Niche topic widget guide", "x", "y"]),
        ("niche topic widgets info", ["Niche topic widget guide", "x", "y"]),
    ])
    # 2 × 1000 = 2000 < 5000 → FAIL
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(1000))
    assert r.passed is False
    assert r.label == LABEL_FAIL
    assert r.raw["pollution_adjusted_volume"] == 2000


def test_gate_1_pollution_drops_adjusted_volume_below_threshold():
    """Two queries clean (6K SV), three polluted — adjusted ends up 6K → PASS still.
    Then bump pollution to drop adjusted below 5K → FAIL."""
    cluster = _cluster("ev charger installation", [
        ("ev charger installation guide", ["EV Charger Installation Guide", "x", "y"]),
        ("home ev charger setup", ["Home EV Charger Setup Tips", "x", "y"]),
        # The next three queries are polluted — none of the topic stems
        # ({ev, charg, install}) appear in any of the top-3 titles.
        ("level 2 wiring", ["Random celebrity news", "Stock tips", "Pet care"]),
        ("home electrical", ["Movie review", "Sports update", "Weather"]),
        ("plug standards", ["Off topic one", "Off topic two", "Off topic three"]),
    ])
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(3000))
    # 2 clean × 3000 = 6000 → PASS
    assert r.passed is True
    assert len(r.raw["polluted_queries"]) == 3
    assert r.raw["pollution_adjusted_volume"] == 6000

    # Drop volume so even 2 clean queries don't clear 5K.
    r2 = evaluate_gate_1(cluster, volume_estimator=_const_estimator(2000))
    assert r2.passed is False
    assert r2.raw["pollution_adjusted_volume"] == 4000


def test_gate_1_fails_when_all_polluted():
    """All queries polluted → adjusted volume = 0 → FAIL even with high total."""
    cluster = _cluster("ev charger installation", [
        # Topic stems are {ev, charg, install}. None of these titles
        # contain any of those stems — the queries themselves use the
        # words but the SERP returned off-topic content.
        ("ev charger installation cost", ["Stock market news", "Sports update", "Movie review"]),
        ("home ev charger", ["Celebrity gossip", "Weather report", "Recipe"]),
    ])
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(50_000))
    assert r.passed is False
    assert r.raw["pollution_adjusted_volume"] == 0
    assert r.raw["total_volume"] == 100_000  # original total still surfaced
    assert len(r.raw["polluted_queries"]) == 2


def test_gate_1_fails_when_zero_results():
    """Query with no organic results counts as polluted (PRD §8.J option 1)."""
    cluster = {
        "schema": "research-cluster-v2",
        "topic": "ev charger installation",
        "source": "serpapi",
        "cluster_queries": ["ev charger installation"],
        "per_query_results": [{
            "schema": "serp-query-v1",
            "query": "ev charger installation",
            "organic_results": [],
            "features": {},
        }],
    }
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(100_000))
    assert r.passed is False
    assert r.raw["polluted_queries"] == ["ev charger installation"]


def test_gate_1_synthesis_only_skips_pollution_detection():
    """Synthesis-only mode skips pollution check, uses total volume,
    and tags findings as `[from LLM guess]` per PRD §8.F option 1."""
    cluster = {
        "schema": "research-cluster-v2",
        "topic": "ev charger installation",
        "source": "gpt-synthesis-fallback",
        "cluster_queries": ["a", "b", "c"],
        "per_query_results": [],  # synthesis-only has no real SERP
    }
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(2500))
    # 3 × 2500 = 7500 → PASS, no pollution penalty
    assert r.passed is True
    assert r.raw["pollution_adjusted_volume"] == 7500
    assert r.raw["polluted_queries"] == []
    assert r.raw["synthesis_only"] is True
    assert any("[from LLM guess]" in f for f in r.findings)


def test_gate_1_handles_missing_query_payload():
    """A cluster_queries entry with no matching per_query_results = polluted."""
    cluster = {
        "schema": "research-cluster-v2",
        "topic": "ev charger",
        "source": "serpapi",
        "cluster_queries": ["ev charger one", "ev charger two"],
        "per_query_results": [
            _query_payload("ev charger one", ["EV Charger One Guide", "x", "y"]),
            # "ev charger two" payload missing
        ],
    }
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(3000))
    assert "ev charger two" in r.raw["polluted_queries"]


def test_gate_1_handles_estimator_failure():
    """An estimator that raises is caught — every query gets 0 SV."""
    def _exploding(queries):
        raise RuntimeError("boom")
    cluster = _cluster("x", [("x clean", ["X clean title", "y", "z"])])
    r = evaluate_gate_1(cluster, volume_estimator=_exploding)
    assert r.passed is False
    assert r.raw["pollution_adjusted_volume"] == 0
    assert any("volume estimator failed" in f for f in r.findings)


def test_gate_1_uses_explicit_per_query_volumes():
    """Different volumes per query → adjusted sum is precise."""
    # Topic stems = {ev, charg}. Third query's titles don't contain
    # either, so it's polluted regardless of the query name.
    cluster = _cluster("ev charger", [
        ("ev charger installation", ["EV Charger install tips", "x", "y"]),
        ("ev charger reviews", ["EV Charger Reviews 2026", "x", "y"]),
        ("level 2 standards", ["Random stuff", "More random", "Yet more"]),
    ])
    volumes = {
        "ev charger installation": 4000,
        "ev charger reviews": 2000,
        "level 2 standards": 100_000,   # polluted, doesn't count
    }
    r = evaluate_gate_1(cluster, volume_estimator=_explicit_estimator(volumes))
    assert r.raw["pollution_adjusted_volume"] == 6000
    assert r.passed is True
    assert "level 2 standards" in r.raw["polluted_queries"]


def test_gate_1_raw_carries_threshold():
    """Caller can read the threshold from raw — useful for the renderer."""
    cluster = _cluster("x", [("x clean", ["X clean title", "y", "z"])])
    r = evaluate_gate_1(cluster, volume_estimator=_const_estimator(0))
    assert r.raw["threshold"] == GATE_1_VOLUME_THRESHOLD


# ---------- Gate 2: helpers ----------


def _organic(domain: str, url: str = "", title: str = "") -> dict:
    return {
        "position": 1,
        "domain": domain,
        "url": url or f"https://{domain}/article",
        "title": title or f"Article on {domain}",
        "snippet": "",
        "displayed_link": domain,
    }


def _cluster_with_organic(topic: str, queries: list[tuple[str, list[dict]]],
                          ai_overview_queries: list[str] | None = None,
                          source: str = "serpapi") -> dict:
    ai_overview_queries = ai_overview_queries or []
    return {
        "schema": "research-cluster-v2",
        "topic": topic,
        "source": source,
        "cluster_queries": [q for q, _ in queries],
        "per_query_results": [
            {
                "schema": "serp-query-v1",
                "query": q,
                "organic_results": orgs,
                "features": {
                    "ai_overview": {"present": q in ai_overview_queries,
                                    "cited_domains": []},
                },
            }
            for q, orgs in queries
        ],
    }


# ---------- Gate 2: individual classifiers ----------


def test_gate_2_reddit_present_fires_on_any_query():
    """Reddit alone is not a kill condition — but the classifier fires."""
    cluster = _cluster_with_organic("ev charger", [
        ("ev charger installation", [_organic("reddit.com"), _organic("a.com"),
                                     _organic("b.com")]),
        ("ev charger cost", [_organic("c.com"), _organic("d.com"),
                             _organic("e.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.raw["classifications"]["reddit_present"]["present"] is True
    # Reddit alone shouldn't kill — WEAK-PASS or PASS.
    assert r.label != LABEL_FAIL


def test_gate_2_ai_overview_dominant_kills_alone():
    """≥2 queries with AI Overview present → FAIL (kill-tier)."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("x.com"), _organic("y.com"), _organic("z.com"),
               _organic("w.com")]),
        ("b", [_organic("x2.com"), _organic("y2.com"), _organic("z2.com")]),
    ], ai_overview_queries=["a", "b"])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_FAIL
    assert "ai_overview_dominant" in r.raw["kill_tier_reasons"]


def test_gate_2_ai_overview_single_query_does_not_kill():
    """Only one query with AI Overview → not dominant → not killed."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("x.com"), _organic("y.com"), _organic("z.com"),
               _organic("w.com")]),
        ("b", [_organic("x2.com"), _organic("y2.com"), _organic("z2.com")]),
    ], ai_overview_queries=["a"])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.raw["classifications"]["ai_overview_dominant"]["dominant"] is False
    assert r.label != LABEL_FAIL


def test_gate_2_programmatic_at_scale_kills():
    """Same domain in 3 of 3 queries → PROGRAMMATIC_AT_SCALE → FAIL."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("evpedia.com"), _organic("x.com"), _organic("y.com")]),
        ("b", [_organic("evpedia.com"), _organic("z.com"), _organic("w.com")]),
        ("c", [_organic("evpedia.com"), _organic("v.com"), _organic("u.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_FAIL
    assert r.raw["classifications"]["programmatic_at_scale"]["present"] is True
    assert "evpedia.com" in r.raw["classifications"]["programmatic_at_scale"]["incumbents"]


def test_gate_2_programmatic_at_scale_needs_three_queries():
    """Same domain in only 2 queries → PROGRAMMATIC_AT_SCALE doesn't fire."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("evpedia.com")]),
        ("b", [_organic("evpedia.com")]),
        ("c", [_organic("x.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.raw["classifications"]["programmatic_at_scale"]["present"] is False


def test_gate_2_specialty_incumbent_fires_on_year_pattern():
    """Domain with /2026/ in URL → SPECIALTY_INCUMBENT → FAIL."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("notesla.com",
                        url="https://notesla.com/2026/model-y-charging-guide")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_FAIL
    assert "notesla.com" in r.raw["classifications"]["specialty_incumbent"]["incumbents"]


def test_gate_2_specialty_incumbent_fires_on_state_pattern():
    """`/tx/state/` → SPECIALTY_INCUMBENT."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("evrebates.com",
                        url="https://evrebates.com/tx/state/charger-incentives")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_FAIL


def test_gate_2_specialty_incumbent_skips_media_domains():
    """A media domain with a /2026/ URL is NOT a specialty incumbent."""
    media_pubs = {"automotive": ["caranddriver.com"]}
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("caranddriver.com",
                        url="https://caranddriver.com/2026/ev-roundup")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs=media_pubs)
    assert r.raw["classifications"]["specialty_incumbent"]["present"] is False


def test_gate_2_specialty_incumbent_skips_reddit():
    """Reddit URLs that happen to have /year/ patterns don't trigger."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("reddit.com",
                        url="https://reddit.com/r/electricvehicles/2026/thread")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.raw["classifications"]["specialty_incumbent"]["present"] is False


def test_gate_2_media_locked_needs_two_queries():
    """≥2 queries with media-pub in top-10 → MEDIA_LOCKED."""
    media_pubs = {"automotive": ["caranddriver.com", "motortrend.com"]}
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("caranddriver.com")]),
        ("b", [_organic("motortrend.com")]),
        ("c", [_organic("x.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs=media_pubs)
    assert r.raw["classifications"]["media_locked"]["locked"] is True


def test_gate_2_media_locked_only_one_query_doesnt_fire():
    media_pubs = {"automotive": ["caranddriver.com"]}
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("caranddriver.com")]),
        ("b", [_organic("x.com")]),
        ("c", [_organic("y.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs=media_pubs)
    assert r.raw["classifications"]["media_locked"]["locked"] is False


def test_gate_2_reddit_plus_media_kills():
    """REDDIT_PRESENT + MEDIA_LOCKED → FAIL (both intents locked)."""
    media_pubs = {"automotive": ["caranddriver.com", "motortrend.com"]}
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("reddit.com"), _organic("caranddriver.com")]),
        ("b", [_organic("motortrend.com")]),
        ("c", [_organic("x.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs=media_pubs)
    assert r.label == LABEL_FAIL
    assert "reddit_and_media_locked" in r.raw["kill_tier_reasons"]


def test_gate_2_reddit_alone_does_not_kill():
    """REDDIT_PRESENT alone, no media-locked → no kill."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("reddit.com")]),
        ("b", [_organic("x.com"), _organic("y.com"), _organic("z.com"),
               _organic("w.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label != LABEL_FAIL


# ---------- Gate 2: pass/fail/weak-pass synthesis ----------


def test_gate_2_passes_with_three_beatable_domains():
    """≥3 unique non-classified domains AND no kill-tier → PASS."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("x.com"), _organic("y.com"), _organic("z.com"),
               _organic("w.com"), _organic("v.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_PASS
    assert r.passed is True
    assert r.raw["classifications"]["potentially_beatable"]["count"] >= 3


def test_gate_2_weak_pass_when_few_beatable_no_kill():
    """No kill-tier but < 3 beatable → WEAK-PASS."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("x.com"), _organic("y.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    assert r.label == LABEL_WEAK_PASS
    assert r.passed is True


def test_gate_2_excludes_wikipedia_from_beatable():
    """Wikipedia is an institutional ranker — not a beatable competitor."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("wikipedia.org"), _organic("x.com")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    domains = {b["domain"] for b in r.raw["classifications"]["potentially_beatable"]["domains"]}
    assert "wikipedia.org" not in domains
    assert "x.com" in domains


def test_gate_2_findings_include_specialty_details():
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("notesla.com",
                        url="https://notesla.com/2026/charger-list")]),
    ])
    r = evaluate_gate_2(cluster, media_pubs={})
    joined = " ".join(r.findings)
    assert "notesla.com" in joined
    assert "specialty incumbent" in joined.lower()


def test_gate_2_synthesis_only_tags_findings():
    cluster = {
        "schema": "research-cluster-v2",
        "topic": "x",
        "source": "gpt-synthesis-fallback",
        "cluster_queries": ["a"],
        "per_query_results": [],
    }
    r = evaluate_gate_2(cluster, media_pubs={})
    assert any("[from LLM guess]" in f for f in r.findings)
    assert r.raw["synthesis_only"] is True


# ---------- Gate 2: moat-required helper integration ----------


def test_is_moat_required_with_real_gate_2_specialty():
    """The dict-with-`present`-flag shape from real Gate 2 triggers moat."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("notesla.com",
                        url="https://notesla.com/2026/list")]),
    ])
    g2 = evaluate_gate_2(cluster, media_pubs={})
    assert is_moat_required(g2) is True


def test_is_moat_required_with_real_gate_2_ai_overview_kill_but_no_incumbent():
    """AI-Overview kill does NOT require a moat (PRD §P2.4 — only
    specialty/programmatic incumbents trigger the moat prompt)."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("x.com"), _organic("y.com"), _organic("z.com")]),
        ("b", [_organic("x2.com"), _organic("y2.com"), _organic("z2.com")]),
    ], ai_overview_queries=["a", "b"])
    g2 = evaluate_gate_2(cluster, media_pubs={})
    assert g2.label == LABEL_FAIL
    assert is_moat_required(g2) is False


# ---------- Gate 2: media-publications loader ----------


def test_load_media_publications_returns_dict():
    """Loader reads the on-disk TOML and returns vertical → domains dict."""
    from portfolio.research_gates import load_media_publications
    pubs = load_media_publications()
    assert isinstance(pubs, dict)
    # The shipped allow-list includes automotive — sanity check it loaded.
    assert "automotive" in pubs
    assert "caranddriver.com" in pubs["automotive"]


def test_load_media_publications_domains_are_lowercased():
    from portfolio.research_gates import load_media_publications
    pubs = load_media_publications()
    for vert, doms in pubs.items():
        for d in doms:
            assert d == d.lower(), f"{vert}: {d!r} not lowercased"


# ---------- moat-required helper ----------


def test_is_moat_required_when_specialty_incumbent_detected():
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {"specialty_incumbent": ["notateslaapp.com"]}
    })
    assert is_moat_required(g2) is True


def test_is_moat_required_when_programmatic_at_scale_detected():
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {"programmatic_at_scale": ["someone.com"]}
    })
    assert is_moat_required(g2) is True


def test_is_moat_required_false_when_only_softer_classifiers():
    """Reddit + media + AI-Overview alone do NOT trigger moat —
    only specialty/programmatic incumbents do (PRD §P2.4)."""
    g2 = GateResult(passed=False, label=LABEL_FAIL, raw={
        "classifications": {
            "reddit_present": True,
            "media_locked": ["wpengine.com"],
            "ai_overview_dominant": True,
        }
    })
    assert is_moat_required(g2) is False


def test_is_moat_required_false_when_raw_empty():
    g2 = GateResult(passed=True, label=LABEL_PASS)
    assert is_moat_required(g2) is False


def test_is_moat_required_false_when_classifications_missing():
    g2 = GateResult(passed=True, label=LABEL_PASS, raw={"other": "data"})
    assert is_moat_required(g2) is False


# ---------- synthesize_verdict (stub) ----------


def test_synthesize_verdict_gate_1_fail_is_no_go():
    """Gate 1 FAIL → NO-GO regardless of other gates."""
    g1 = GateResult(passed=False, label=LABEL_FAIL)
    g_pass = GateResult(passed=True, label=LABEL_PASS)
    assert synthesize_verdict(g1, g_pass, g_pass) == VERDICT_NO_GO


def test_synthesize_verdict_all_pass_is_go():
    g = GateResult(passed=True, label=LABEL_PASS)
    assert synthesize_verdict(g, g, g) == VERDICT_GO


def test_synthesize_verdict_gate_2_fail_with_moat_is_niche_down():
    """Gate 2 FAIL + Gate 3 PASS with moat sentence → NICHE-DOWN."""
    g1 = GateResult(passed=True, label=LABEL_PASS)
    g2 = GateResult(passed=False, label=LABEL_FAIL)
    g3 = GateResult(passed=True, label=LABEL_PASS,
                    raw={"required": True, "moat_sentence": "my moat"})
    assert synthesize_verdict(g1, g2, g3) == VERDICT_NICHE_DOWN


def test_synthesize_verdict_gate_2_fail_no_moat_is_no_go():
    """Gate 2 FAIL + Gate 3 FAIL → NO-GO."""
    g1 = GateResult(passed=True, label=LABEL_PASS)
    g2 = GateResult(passed=False, label=LABEL_FAIL)
    g3 = GateResult(passed=False, label=LABEL_FAIL)
    assert synthesize_verdict(g1, g2, g3) == VERDICT_NO_GO


def test_synthesize_verdict_gate_2_fail_pending_moat_is_no_go():
    """Gate 2 FAIL + Gate 3 PENDING (non-interactive) → NO-GO."""
    g1 = GateResult(passed=True, label=LABEL_PASS)
    g2 = GateResult(passed=False, label=LABEL_FAIL)
    g3 = GateResult(passed=None, label=LABEL_PENDING)
    assert synthesize_verdict(g1, g2, g3) == VERDICT_NO_GO


def test_synthesize_verdict_weak_pass_g2_is_niche_down():
    """Gate 2 WEAK-PASS → NICHE-DOWN (no kill-tier but findings flag
    what would force narrowing)."""
    g1 = GateResult(passed=True, label=LABEL_PASS)
    g2 = GateResult(passed=True, label=LABEL_WEAK_PASS)
    g3 = GateResult(passed=True, label=LABEL_PASS, raw={"required": False})
    assert synthesize_verdict(g1, g2, g3) == VERDICT_NICHE_DOWN


def test_synthesize_verdict_op_fit_auto_fail_overrides_pass():
    """Operator-fit's auto_fail_gate_2=True treats Gate 2 as FAILED
    even when its label is PASS — verdict shifts to NO-GO without moat."""
    g_pass = GateResult(passed=True, label=LABEL_PASS)
    g3_fail = GateResult(passed=False, label=LABEL_FAIL)
    op = OperatorFitResult(auto_fail_gate_2=True)
    assert synthesize_verdict(g_pass, g_pass, g3_fail, op_fit=op) == VERDICT_NO_GO


def test_synthesize_verdict_op_fit_auto_fail_with_moat_is_niche_down():
    g_pass = GateResult(passed=True, label=LABEL_PASS)
    g3_moat = GateResult(passed=True, label=LABEL_PASS,
                         raw={"required": True, "moat_sentence": "moat"})
    op = OperatorFitResult(auto_fail_gate_2=True)
    assert synthesize_verdict(g_pass, g_pass, g3_moat, op_fit=op) == VERDICT_NICHE_DOWN


# ---------- Suggested reductions ----------


def test_suggest_reductions_returns_list_from_llm():
    from portfolio.research_gates import suggest_reductions
    def _fake_llm(system, user):
        return '{"reductions": ["narrow to EV", "regional only", "post-fault trigger"]}'
    g = GateResult(passed=False, label=LABEL_FAIL)
    out = suggest_reductions("x", g, g, g, llm_call=_fake_llm)
    assert out == ["narrow to EV", "regional only", "post-fault trigger"]


def test_suggest_reductions_caps_at_three():
    from portfolio.research_gates import suggest_reductions
    def _fake_llm(s, u):
        return '{"reductions": ["a", "b", "c", "d", "e"]}'
    g = GateResult(passed=False, label=LABEL_FAIL)
    assert len(suggest_reductions("x", g, g, g, llm_call=_fake_llm)) == 3


def test_suggest_reductions_strips_markdown_fences():
    from portfolio.research_gates import suggest_reductions
    def _fake_llm(s, u):
        return '```json\n{"reductions": ["a", "b"]}\n```'
    g = GateResult(passed=False, label=LABEL_FAIL)
    assert suggest_reductions("x", g, g, g, llm_call=_fake_llm) == ["a", "b"]


def test_suggest_reductions_returns_empty_on_llm_error():
    from portfolio.research_gates import suggest_reductions
    def _exploding(s, u):
        raise RuntimeError("openai down")
    g = GateResult(passed=False, label=LABEL_FAIL)
    assert suggest_reductions("x", g, g, g, llm_call=_exploding) == []


def test_suggest_reductions_returns_empty_on_bad_json():
    from portfolio.research_gates import suggest_reductions
    def _bad(s, u):
        return "this isn't json"
    g = GateResult(passed=False, label=LABEL_FAIL)
    assert suggest_reductions("x", g, g, g, llm_call=_bad) == []


def test_suggest_reductions_skips_empty_strings():
    """Empty reductions in the LLM list are filtered out."""
    from portfolio.research_gates import suggest_reductions
    def _fake_llm(s, u):
        return '{"reductions": ["valid", "", "  ", "also valid"]}'
    g = GateResult(passed=False, label=LABEL_FAIL)
    out = suggest_reductions("x", g, g, g, llm_call=_fake_llm)
    assert out == ["valid", "also valid"]


def test_reduction_axes_constant():
    from portfolio.research_gates import REDUCTION_AXES
    assert set(REDUCTION_AXES) == {
        "segment", "geography", "persona", "use_case", "depth", "moment",
    }


# ---------- evaluate_cluster: end-to-end orchestration ----------


def test_evaluate_cluster_calls_reductions_only_on_niche_down():
    """suggest_reductions LLM is called only when verdict=NICHE-DOWN."""
    # Titles contain "ev" / "charg" so Gate 1 won't mark them polluted.
    cluster = _cluster_with_organic("ev charger", [
        ("a", [
            _organic("x.com", title="EV charger guide on X"),
            _organic("y.com", title="EV charger picks Y"),
        ]),
    ])
    called = []
    def _fake(s, u):
        called.append((s, u))
        return '{"reductions": ["narrow it"]}'
    # No kill-tier classifiers + only 2 beatable → Gate 2 WEAK-PASS → NICHE-DOWN.
    r = evaluate_cluster(
        cluster,
        volume_estimator=lambda qs: {q: 10_000 for q in qs},
        reductions_llm_call=_fake,
    )
    assert r.verdict == VERDICT_NICHE_DOWN
    assert called  # was called
    assert r.suggested_reductions == ["narrow it"]


def test_evaluate_cluster_skips_reductions_on_no_go():
    """No LLM call for NO-GO verdicts (Gate 1 fail)."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("y.com", title="EV charger Y article")]),
    ])
    called = []
    def _fake(s, u):
        called.append(1)
        return '{"reductions": []}'
    r = evaluate_cluster(
        cluster,
        volume_estimator=lambda qs: {q: 0 for q in qs},   # → Gate 1 FAIL
        reductions_llm_call=_fake,
    )
    assert r.verdict == VERDICT_NO_GO
    assert called == []
    assert r.suggested_reductions == []


def test_evaluate_cluster_skip_reductions_flag():
    """skip_reductions=True bypasses the LLM call even for NICHE-DOWN."""
    cluster = _cluster_with_organic("ev charger", [
        ("a", [_organic("y.com", title="EV charger article on Y")]),
    ])
    called = []
    def _fake(s, u):
        called.append(1)
        return '{"reductions": ["x"]}'
    r = evaluate_cluster(
        cluster,
        volume_estimator=lambda qs: {q: 10_000 for q in qs},
        reductions_llm_call=_fake,
        skip_reductions=True,
    )
    assert r.verdict == VERDICT_NICHE_DOWN
    assert called == []
    assert r.suggested_reductions == []


# ---------- evaluate_cluster (orchestrator) ----------


def test_evaluate_cluster_returns_full_gate_results():
    """The orchestrator returns a GateResults with all four slots
    populated. All three gates are real. An empty cluster:
      - Gate 1 FAIL (zero pollution-adjusted volume)
      - Gate 2 WEAK-PASS (no kill-tier, no beatable)
      - Gate 3 PASS (no specialty/programmatic incumbent → not required)
    """
    cluster = {"topic": "x", "cluster_queries": ["x"], "per_query_results": []}
    r = evaluate_cluster(cluster, volume_estimator=lambda qs: {q: 0 for q in qs})
    assert isinstance(r, GateResults)
    assert r.gate_1_market.label == LABEL_FAIL
    assert r.gate_2_serp.label == LABEL_WEAK_PASS
    assert r.gate_3_moat.label == LABEL_PASS
    assert isinstance(r.operator_fit, OperatorFitResult)


def test_evaluate_cluster_carries_moat_through():
    cluster = {"topic": "x", "cluster_queries": [], "per_query_results": []}
    r = evaluate_cluster(cluster, moat_sentence="my moat",
                         volume_estimator=lambda qs: {})
    assert r.moat_provided == "my moat"


def test_evaluate_cluster_defaults_no_moat():
    cluster = {"topic": "x", "cluster_queries": [], "per_query_results": []}
    r = evaluate_cluster(cluster, volume_estimator=lambda qs: {})
    assert r.moat_provided is None


def test_evaluate_cluster_with_operator_fit_carries_through():
    cluster = {"topic": "x", "cluster_queries": [], "per_query_results": []}
    op = OperatorFitResult(warnings=["builder + writer niche"])
    r = evaluate_cluster(cluster, operator_fit=op,
                         volume_estimator=lambda qs: {})
    assert r.operator_fit.warnings == ["builder + writer niche"]


def test_evaluate_cluster_non_interactive_does_not_crash():
    """The non_interactive flag is part of the orchestrator signature
    so the CLI's --json / --non-interactive paths can pass it. For an
    empty cluster (no Gate 2 incumbent), Gate 3 is not required and
    PASSes without prompting."""
    cluster = {"topic": "x", "cluster_queries": [], "per_query_results": []}
    r = evaluate_cluster(cluster, non_interactive=True,
                         volume_estimator=lambda qs: {})
    assert r.gate_3_moat.label == LABEL_PASS


def test_evaluate_cluster_non_interactive_with_incumbent_yields_pending_g3():
    """When Gate 2 detects an incumbent AND --non-interactive is set
    AND no moat is provided, Gate 3 is PENDING (waiting for the user
    to re-run interactively)."""
    cluster = {
        "schema": "research-cluster-v2",
        "topic": "ev charger",
        "source": "serpapi",
        "cluster_queries": ["a", "b", "c"],
        "per_query_results": [
            {
                "schema": "serp-query-v1", "query": q,
                "organic_results": [
                    {"position": 1, "domain": "evpedia.com",
                     "url": "https://evpedia.com/article", "title": "EV"},
                ],
                "features": {},
            }
            for q in ["a", "b", "c"]
        ],
    }
    r = evaluate_cluster(cluster, non_interactive=True,
                         volume_estimator=lambda qs: {q: 0 for q in qs})
    assert r.gate_2_serp.label == LABEL_FAIL
    assert r.gate_3_moat.label == LABEL_PENDING
    assert r.moat_required is True
