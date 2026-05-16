"""Tests for v8.D — synthesis-output guardrails on `new research`.

The synthesis-fallback path (--synthesis-only OR auto-fallback after
SerpAPI quota exhausts) used to render competitive verdicts —
hallucinated ranker domains, fabricated saturation scores,
ship/mixed/skip decisions — that look identical to real-SERP output.
The operator can't visually distinguish "real research" from "LLM made
up domain names," so acting on those verdicts is dangerous.

Guardrail rules tested here:
  1. The verdict surface is HARD-BLOCKED on synthesis: top_likely_rankers,
     competitive_signal, per_query_summary, decision, reasoning are all
     stripped from the rendered output.
  2. Ideation surfaces are KEPT: cluster_queries, content_patterns,
     suggested_angles render normally — but every section header
     carries the "[SYNTHESIS ONLY — not real SERP data]" prefix so a
     reader scanning the output can't mistake it for research data.
  3. The `--json` output applies the same strip + adds
     `verdict_blocked: true` plus a reason field so downstream
     scripts can detect the blocked state programmatically.
"""
from __future__ import annotations

import io
import json

import pytest
from rich.console import Console

from portfolio import cli as cli_mod


def _capturing_console() -> Console:
    """Rich console that writes to a StringIO so tests can inspect output."""
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def _synthesis_payload(*, decision: str = "ship", saturation: str = "medium",
                      include_rankers: bool = True,
                      include_per_query: bool = True) -> dict:
    """Build a payload matching `serp.research()`'s synthesis shape.
    Includes every field the renderer might want to leak — the
    guardrail tests assert they're stripped."""
    return {
        "topic": "ev charger installation cost",
        "mode": "cluster",
        "model": "gpt-4o-mini",
        "knowledge_caveat": "training cutoff applies",
        "from_cache": False,
        "analysis": {
            "cluster_queries": [
                "ev charger installation cost",
                "level 2 charger price",
                "tesla wall connector installation",
            ],
            "content_patterns": [
                "comparison tables dominate top-10",
                "video-heavy SERPs",
            ],
            "suggested_angles": [
                "Installer cost comparison by region",
                "DIY vs professional safety calculator",
                "Permit / inspection cost breakdown",
            ],
            "top_likely_rankers": ([
                {"domain": "hallucinated-example.com",
                 "type": "publisher", "intent": "commercial", "frequency": 3},
                {"domain": "another-fake.io",
                 "type": "publisher", "intent": "informational", "frequency": 2},
            ] if include_rankers else []),
            "competitive_signal": {
                "saturation": saturation,
                "ymyl_flag": False,
                "barrier": "high — programmatic incumbent dominates",
            },
            "per_query_summary": ([
                {"query": "ev charger installation cost",
                 "decision_hint": "ship", "ymyl": False},
                {"query": "level 2 charger price",
                 "decision_hint": "mixed", "ymyl": False},
            ] if include_per_query else []),
            "decision": decision,
            "reasoning": (
                "The market shows medium saturation with comparison-table "
                "content dominating. Local-installer angle has the clearest "
                "moat."
            ),
        },
    }


# ---------- _render_serp_full ----------


def test_render_serp_full_shows_verdict_blocked_banner():
    """The 'VERDICT BLOCKED' block must render before any ideation
    content so the operator sees it first."""
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "VERDICT BLOCKED" in out
    assert "AI synthesis" in out
    assert "not real SERP data" in out


def test_render_serp_full_strips_top_rankers():
    """top_likely_rankers carries hallucinated domain names. Must not
    appear in any form."""
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "hallucinated-example.com" not in out
    assert "another-fake.io" not in out
    # And the section header itself.
    assert "Cluster-level rankers" not in out
    assert "Likely top rankers" not in out


def test_render_serp_full_strips_saturation():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(saturation="high"), console)
    out = console.file.getvalue()
    # The "Saturation: <value>" row from the old renderer must not
    # appear. The word "saturation" CAN appear in the verdict-blocked
    # banner's explanation ("rankers, saturation, ship/mixed/wait are
    # blocked") — that's expected and the assertion is intentionally
    # narrow to allow it.
    assert "Saturation:" not in out
    assert "Competitive signal:" not in out
    # And the value itself isn't rendered.
    assert "Saturation: high" not in out
    assert "Saturation: medium" not in out


def test_render_serp_full_strips_per_query_decisions():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "Per-query breakdown" not in out
    # And the verbatim per-query hints.
    assert "decision_hint" not in out
    # The query strings themselves CAN appear inside cluster_queries —
    # that's safe. We're only asserting the per-query verdict surface
    # is gone, not the queries.


def test_render_serp_full_strips_final_decision():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(decision="ship"), console)
    out = console.file.getvalue()
    # The "Decision:" label and the verb tokens (SHIP/MIXED/SKIP) must
    # not appear as a verdict — the blocked banner is what the reader
    # sees instead.
    assert "Decision:" not in out
    assert "SHIP" not in out
    assert "MIXED" not in out
    assert "SKIP" not in out


def test_render_serp_full_keeps_cluster_queries():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    # The cluster query list is ideation context — kept.
    assert "ev charger installation cost" in out
    assert "Topic cluster" in out


def test_render_serp_full_keeps_content_patterns():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "Content patterns" in out
    assert "comparison tables dominate top-10" in out


def test_render_serp_full_keeps_suggested_angles():
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "Suggested angles" in out
    assert "Installer cost comparison by region" in out


def test_render_serp_full_prefixes_every_kept_section_header():
    """Each kept section header carries the "[SYNTHESIS ONLY — not real
    SERP data]" prefix — a reader scanning the table of section
    headers can't mistake synthesis output for research output."""
    console = _capturing_console()
    cli_mod._render_serp_full(_synthesis_payload(), console)
    out = console.file.getvalue()
    prefix = "[SYNTHESIS ONLY — not real SERP data]"
    # The prefix appears once before each of Topic cluster /
    # Content patterns / Suggested angles. Three sections → ≥3 prefix
    # occurrences. (Counting flexibly lets a future header insert
    # without breaking the assertion.)
    assert out.count(prefix) >= 3


# ---------- _render_serp_brief ----------


def test_render_serp_brief_shows_blocked_banner():
    console = _capturing_console()
    cli_mod._render_serp_brief(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "VERDICT BLOCKED" in out
    assert "AI synthesis" in out


def test_render_serp_brief_strips_decision_and_saturation():
    console = _capturing_console()
    cli_mod._render_serp_brief(_synthesis_payload(decision="ship",
                                                  saturation="high"), console)
    out = console.file.getvalue()
    # Same surface as full: no decision verb, no saturation value.
    assert "SHIP" not in out
    assert "MIXED" not in out
    assert "saturation" not in out
    assert "Saturation" not in out


def test_render_serp_brief_keeps_top_3_angles():
    console = _capturing_console()
    cli_mod._render_serp_brief(_synthesis_payload(), console)
    out = console.file.getvalue()
    assert "Installer cost comparison by region" in out
    assert "DIY vs professional safety calculator" in out


# ---------- _strip_unsafe_synthesis_fields + _render_serp_json ----------


def test_strip_unsafe_synthesis_fields_removes_verdict_surface():
    payload = _synthesis_payload()
    safe = cli_mod._strip_unsafe_synthesis_fields(payload)
    analysis = safe["analysis"]
    for f in cli_mod._UNSAFE_SYNTHESIS_FIELDS:
        assert f not in analysis, f"{f} should have been stripped"


def test_strip_unsafe_synthesis_fields_keeps_ideation_surface():
    payload = _synthesis_payload()
    safe = cli_mod._strip_unsafe_synthesis_fields(payload)
    analysis = safe["analysis"]
    # Ideation-safe fields survive.
    assert "cluster_queries" in analysis
    assert "content_patterns" in analysis
    assert "suggested_angles" in analysis


def test_strip_unsafe_synthesis_fields_adds_blocked_marker():
    safe = cli_mod._strip_unsafe_synthesis_fields(_synthesis_payload())
    assert safe["verdict_blocked"] is True
    assert "verdict_blocked_reason" in safe
    assert "synthesis" in safe["verdict_blocked_reason"].lower()


def test_strip_unsafe_synthesis_fields_returns_copy_not_mutation():
    """Pure-function contract — caller's original payload mustn't be
    mutated. Otherwise persisted snapshots could get the strip applied
    on disk if the caller passed in a reference."""
    payload = _synthesis_payload()
    cli_mod._strip_unsafe_synthesis_fields(payload)
    assert "decision" in payload["analysis"]
    assert "top_likely_rankers" in payload["analysis"]


def test_strip_unsafe_synthesis_fields_handles_missing_analysis():
    """Old / partial payloads without `analysis` shouldn't crash."""
    safe = cli_mod._strip_unsafe_synthesis_fields({"topic": "x"})
    assert safe["analysis"] == {}
    assert safe["verdict_blocked"] is True


def test_render_serp_json_emits_sanitized_payload(capsys):
    cli_mod._render_serp_json(_synthesis_payload())
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["verdict_blocked"] is True
    assert "verdict_blocked_reason" in parsed
    analysis = parsed["analysis"]
    for f in cli_mod._UNSAFE_SYNTHESIS_FIELDS:
        assert f not in analysis
    # Ideation kept.
    assert "cluster_queries" in analysis
    assert "suggested_angles" in analysis
