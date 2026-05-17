"""Tests for v8.E — `build_payload` (the structured user-message
assembled from the v8.D cluster snapshot + operator profile, fed to
the primary interpretive pass).

Pure-data-shaping function — no LLM calls, no network. Tests fix the
output shape so subsequent commits wiring this into the prompt /
parser / runner can't accidentally break the contract that
`prompts/niche_evaluation_v1.md` depends on.
"""
from __future__ import annotations

from portfolio.interpretive_pass import build_payload
from portfolio.operator_profile import OperatorProfile


# ---------- fixtures ----------


def _minimal_cluster() -> dict:
    """Smallest cluster snapshot that satisfies `build_payload`'s
    required keys. Forward-compat-shaped (extra keys tolerated)."""
    return {
        "schema": "research-cluster-v2",
        "topic": "ev charger installation cost",
        "cluster_queries": [
            "ev charger installation cost",
            "level 2 charger price",
        ],
        "gates": {
            "gate_1_market": {"status": "PASS", "raw": {"volume": 6200}},
            "gate_2_serp": {"status": "FAIL", "raw": {"classifications": {}}},
            "gate_3_moat": {"status": "PENDING"},
        },
        "operator_fit": {
            "warnings": ["Workflow mismatch: builder vs content niche"],
            "auto_fail_gate_2": False,
        },
        "per_query_results": [
            {
                "query": "ev charger installation cost",
                "organic_results": [
                    {"position": 1, "domain": "homedepot.com",
                     "url": "https://homedepot.com/installation",
                     "title": "EV Charger Installation",
                     "snippet": "long marketing copy...",
                     "displayed_link": "homedepot.com › installation"},
                    {"position": 2, "domain": "tesla.com",
                     "url": "https://tesla.com/wallconnector",
                     "title": "Tesla Wall Connector",
                     "snippet": "another long blurb...",
                     "displayed_link": "tesla.com › wallconnector"},
                ],
                "features": {
                    "ai_overview": {"present": True,
                                    "cited_domains": ["wikipedia.org"]},
                    "people_also_ask": {"present": False},
                    "reddit_card": {"present": True, "position": 5},
                    "featured_snippet": {"present": False},
                    "local_pack": {"present": False},
                    "video_pack": {"present": False},
                    "image_pack": {"present": False},
                },
            },
            {
                "query": "level 2 charger price",
                "organic_results": [
                    {"position": 1, "domain": "amazon.com",
                     "url": "https://amazon.com/", "title": "Amazon",
                     "snippet": "x", "displayed_link": "amazon.com"},
                ],
                "features": {
                    "ai_overview": {"present": False},
                    "reddit_card": {"present": False},
                },
            },
        ],
    }


def _full_profile() -> OperatorProfile:
    return OperatorProfile(
        expertise=["SEO programmatic content", "Python CLI tooling"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )


# ---------- top-level keys ----------


def test_build_payload_carries_topic_and_cluster_queries():
    payload = build_payload(_minimal_cluster())
    assert payload["topic"] == "ev charger installation cost"
    assert payload["cluster_queries"] == [
        "ev charger installation cost",
        "level 2 charger price",
    ]


def test_build_payload_passes_gates_through_verbatim():
    """Gates are already structured dicts in the cluster snapshot —
    pass-through is the right shape (LLM should see the same data the
    mechanical pipeline saw, including raw classifier output)."""
    payload = build_payload(_minimal_cluster())
    assert payload["gates"]["gate_1_market"]["status"] == "PASS"
    assert payload["gates"]["gate_1_market"]["raw"]["volume"] == 6200
    assert payload["gates"]["gate_2_serp"]["status"] == "FAIL"
    assert payload["gates"]["gate_3_moat"]["status"] == "PENDING"


def test_build_payload_passes_operator_fit_through_verbatim():
    payload = build_payload(_minimal_cluster())
    assert payload["operator_fit"]["auto_fail_gate_2"] is False
    assert "Workflow mismatch" in payload["operator_fit"]["warnings"][0]


def test_build_payload_always_contains_required_keys():
    """The prompt is structured around these key names; missing one
    would break the substitution."""
    payload = build_payload(_minimal_cluster())
    for k in ("topic", "cluster_queries", "gates", "operator_fit",
              "operator_profile_summary", "raw_top_10_per_query",
              "serp_features_per_query"):
        assert k in payload, f"required key {k!r} missing from payload"


# ---------- raw_top_10_per_query (PRD: title/URL/domain only) ----------


def test_raw_top_10_strips_snippet_and_displayed_link():
    """Snippet (~100-300 chars per result) and displayed_link
    (redundant with URL) are dropped to keep prompt token cost bounded
    across 5 queries × 10 results."""
    payload = build_payload(_minimal_cluster())
    first_result = payload["raw_top_10_per_query"][0]["results"][0]
    assert "snippet" not in first_result
    assert "displayed_link" not in first_result
    # Position / domain / URL / title preserved.
    assert first_result["position"] == 1
    assert first_result["domain"] == "homedepot.com"
    assert first_result["title"] == "EV Charger Installation"


def test_raw_top_10_preserves_query_grouping():
    """Each entry in the list carries its query string so the LLM
    knows which SERP a result was from (different cluster queries
    surface different rankers)."""
    payload = build_payload(_minimal_cluster())
    queries = [q["query"] for q in payload["raw_top_10_per_query"]]
    assert queries == ["ev charger installation cost", "level 2 charger price"]


def test_raw_top_10_caps_at_ten_results_per_query():
    """SerpAPI sometimes returns >10 results (rich SERPs spill over).
    The payload caps at 10 per query per PRD spec."""
    cluster = _minimal_cluster()
    cluster["per_query_results"][0]["organic_results"] = [
        {"position": i, "domain": f"d{i}.com", "url": f"u{i}",
         "title": f"t{i}", "snippet": "s", "displayed_link": "x"}
        for i in range(1, 16)
    ]
    payload = build_payload(cluster)
    assert len(payload["raw_top_10_per_query"][0]["results"]) == 10
    # First 10 by position order — slice off the back, not random.
    assert payload["raw_top_10_per_query"][0]["results"][9]["position"] == 10


def test_raw_top_10_handles_missing_organic_results():
    """A failed fetch on one cluster query leaves `organic_results`
    missing or empty — payload renders the query with an empty results
    list rather than crashing."""
    cluster = _minimal_cluster()
    cluster["per_query_results"][0].pop("organic_results")
    payload = build_payload(cluster)
    assert payload["raw_top_10_per_query"][0]["results"] == []


# ---------- serp_features_per_query (only present features) ----------


def test_serp_features_drops_absent_features():
    """The cluster snapshot pads every query's features dict with
    `{present: false}` entries for absent features. The LLM doesn't
    need that negative space — only fired features make it through."""
    payload = build_payload(_minimal_cluster())
    feats = payload["serp_features_per_query"][0]["features"]
    # Present features survive.
    assert "ai_overview" in feats
    assert "reddit_card" in feats
    # Absent ones are stripped.
    assert "people_also_ask" not in feats
    assert "featured_snippet" not in feats
    assert "local_pack" not in feats


def test_serp_features_preserves_subfields_on_present_features():
    """When a feature fires, its subfields (cited_domains for AI
    Overview, position for Reddit card, etc.) pass through — these
    are what the LLM uses to reason about the SERP layout."""
    payload = build_payload(_minimal_cluster())
    feats = payload["serp_features_per_query"][0]["features"]
    assert feats["ai_overview"]["cited_domains"] == ["wikipedia.org"]
    assert feats["reddit_card"]["position"] == 5


def test_serp_features_empty_when_no_features_fired():
    """A SERP with all features absent renders as an empty features
    dict for that query — not omitted from the list, just empty."""
    payload = build_payload(_minimal_cluster())
    feats_q2 = payload["serp_features_per_query"][1]["features"]
    assert feats_q2 == {}


# ---------- operator_profile_summary ----------


def test_operator_profile_summary_renders_full_profile():
    payload = build_payload(_minimal_cluster(), operator_profile=_full_profile())
    summary = payload["operator_profile_summary"]
    assert "SEO programmatic content" in summary
    assert "Python CLI tooling" in summary
    assert "builder" in summary
    assert "weekly" in summary


def test_operator_profile_summary_none_when_no_profile():
    """No profile passed → 'no operator profile configured' string —
    same convention as `settings operator show`. Lets the LLM know
    it's running without operator constraints."""
    payload = build_payload(_minimal_cluster(), operator_profile=None)
    assert payload["operator_profile_summary"] == "no operator profile configured"


def test_operator_profile_summary_default_profile_treated_as_none():
    """An OperatorProfile with no expertise + default workflow/cadence
    is the same as having no profile — don't pretend the operator
    declared a 'mixed monthly' preference if they just never ran
    `settings operator`."""
    default_profile = OperatorProfile()
    payload = build_payload(_minimal_cluster(), operator_profile=default_profile)
    assert payload["operator_profile_summary"] == "no operator profile configured"


def test_operator_profile_summary_renders_partial_profile():
    """Operator who set workflow + cadence but no expertise yet
    still gets a non-empty summary — partial info is still useful
    to the LLM."""
    partial = OperatorProfile(
        expertise=[],
        workflow_preference="writer",
        motivation_cadence="quarterly",
    )
    payload = build_payload(_minimal_cluster(), operator_profile=partial)
    summary = payload["operator_profile_summary"]
    assert summary != "no operator profile configured"
    assert "writer" in summary
    assert "quarterly" in summary


# ---------- tolerance ----------


def test_build_payload_tolerates_missing_optional_keys():
    """A bare minimum cluster (just topic + cluster_queries) shouldn't
    crash — the empty defaults are sane downstream."""
    minimal = {
        "topic": "x",
        "cluster_queries": ["x"],
    }
    payload = build_payload(minimal)
    assert payload["gates"] == {}
    assert payload["operator_fit"] == {}
    assert payload["raw_top_10_per_query"] == []
    assert payload["serp_features_per_query"] == []
