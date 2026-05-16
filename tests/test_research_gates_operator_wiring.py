"""Tests for v8.D — operator-fit wired into `_run_gates_with_prompt`.

The CLI orchestrator (`portfolio.cli._run_gates_with_prompt`) reads
the operator profile from sites/portfolio/lamill.toml and feeds it
into the gates pipeline. These tests verify the wire-up — that
edits to the on-disk profile actually change the operator_fit field
in the returned `GateResults`.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from rich.console import Console

from portfolio.cli import _run_gates_with_prompt
from portfolio.research_gates import (
    GateResult,
    LABEL_PASS,
)


def _patch_lamill_path(monkeypatch, path: Path) -> None:
    import portfolio.operator_profile as op
    monkeypatch.setattr(op, "LAMILL_TOML", path)


def _stub_gates(monkeypatch) -> None:
    """Replace Gate 1 / Gate 2 / Gate 3 with no-op PASS results so the
    integration test exercises only the operator-fit wire-up (Gate 1's
    real implementation calls an LLM volume estimator — out of scope)."""
    pass_result = GateResult(
        passed=True, label=LABEL_PASS, findings=[], raw={"classifications": {}},
    )
    import portfolio.cli as cli_mod
    # We patch on the local import path. cli's _run_gates_with_prompt
    # imports lazily, so patch at the source module.
    import portfolio.research_gates as gates_mod
    monkeypatch.setattr(gates_mod, "evaluate_gate_1", lambda *a, **kw: pass_result)
    monkeypatch.setattr(gates_mod, "evaluate_gate_2", lambda *a, **kw: pass_result)
    monkeypatch.setattr(gates_mod, "evaluate_gate_3", lambda *a, **kw: pass_result)
    monkeypatch.setattr(gates_mod, "is_moat_required", lambda *a, **kw: False)


def _cluster_with_listicle_informational() -> dict:
    """Cluster that triggers the workflow check (builder + listicle)."""
    listicle_results = [
        {"domain": "site1.example", "url": "u1",
         "title": "10 Best Tools of 2026", "snippet": ""},
        {"domain": "site2.example", "url": "u2",
         "title": "Top 5 Picks for the Year", "snippet": ""},
    ]
    return {
        "topic": "best lawn mowers",
        "cluster_queries": [
            "best lawn mowers", "top mowers", "how to pick a mower",
            "what mower to buy", "guide to mowers",
        ],
        "per_query_results": [
            {"query": q, "organic_results": listicle_results, "features": {}}
            for q in [
                "best lawn mowers", "top mowers", "how to pick a mower",
                "what mower to buy", "guide to mowers",
            ]
        ],
    }


def test_no_profile_file_means_no_operator_fit_warnings(monkeypatch, tmp_path):
    """If sites/portfolio/lamill.toml doesn't exist, operator_fit is empty."""
    _patch_lamill_path(monkeypatch, tmp_path / "nonexistent.toml")
    _stub_gates(monkeypatch)
    cluster = _cluster_with_listicle_informational()
    result = _run_gates_with_prompt(
        cluster, console=Console(), non_interactive=True,
    )
    assert result.operator_fit.warnings == []
    assert result.operator_fit.auto_fail_gate_2 is False


def test_loaded_profile_drives_operator_fit_warnings(monkeypatch, tmp_path):
    """A populated profile triggers the relevant fit-check warning."""
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        workflow_preference = "builder"
    """).strip())
    _patch_lamill_path(monkeypatch, f)
    _stub_gates(monkeypatch)
    cluster = _cluster_with_listicle_informational()
    result = _run_gates_with_prompt(
        cluster, console=Console(), non_interactive=True,
    )
    assert any("Builder profile" in w for w in result.operator_fit.warnings)


def test_default_profile_silent_on_listicle_cluster(monkeypatch, tmp_path):
    """A profile present but with all-default values still silences
    the workflow check (workflow_preference="mixed" is the default)."""
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        workflow_preference = "mixed"
    """).strip())
    _patch_lamill_path(monkeypatch, f)
    _stub_gates(monkeypatch)
    cluster = _cluster_with_listicle_informational()
    result = _run_gates_with_prompt(
        cluster, console=Console(), non_interactive=True,
    )
    assert not any("Builder profile" in w for w in result.operator_fit.warnings)
