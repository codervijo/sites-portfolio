"""Tests for v8.H — `run_primary_pass` (end-to-end orchestration of
build_payload → render_primary_prompt → run_claude_text → parse_verdict).

The runner is the smallest layer that ties the four primitives
together. Tests use the `claude_runner` injection seam to stub
`run_claude_text` with canned `ClaudeTextResult` values — no real
subprocess invocation, no live Claude API quota burn.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.fix_helpers import ClaudeTextResult
from portfolio.interpretive_pass import (
    InterpretivePassError,
    InterpretivePassResult,
    PRIMARY_PROMPT_VERSION,
    run_primary_pass,
)
from portfolio.operator_profile import OperatorProfile


# ---------- fixtures ----------


def _minimal_cluster() -> dict:
    """Smallest cluster snapshot that satisfies `build_payload`'s
    required keys."""
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


def _canonical_markdown(verdict="GO", confidence="HIGH") -> str:
    return (
        f"### verdict\n{verdict}\n\n"
        f"### confidence\n{confidence}\n\n"
        "### reasoning\nMechanical gates lined up; SERP confirms.\n\n"
        "### moat_required\nfalse"
    )


def _fake_runner_returning(text: str, *, cost: float = 0.04,
                           duration: float = 5.2,
                           ok: bool = True,
                           error: str | None = None):
    """Build a stub callable matching `run_claude_text`'s signature.
    Returns a canned `ClaudeTextResult` regardless of the prompt
    passed in — tests should assert prompt-shape via separate
    render-layer tests, not here."""
    def _stub(prompt: str, *, cwd: Path,
             budget_usd: float, timeout_s: int) -> ClaudeTextResult:
        return ClaudeTextResult(
            ok=ok, text=text if ok else "",
            cost_usd=cost, duration_s=duration,
            error=error, raw_output="" if ok else "stubbed-failure",
        )
    return _stub


# ---------- happy path ----------


def test_run_primary_pass_returns_full_result(tmp_path):
    runner = _fake_runner_returning(_canonical_markdown())
    result = run_primary_pass(
        _minimal_cluster(), cwd=tmp_path, claude_runner=runner,
    )
    assert isinstance(result, InterpretivePassResult)
    assert result.verdict.verdict == "GO"
    assert result.verdict.confidence == "HIGH"
    assert result.prompt_version == PRIMARY_PROMPT_VERSION
    assert result.model_id == "claude-cli"
    assert result.cost_usd == 0.04
    assert result.duration_s == 5.2


def test_run_primary_pass_includes_rendered_prompt(tmp_path):
    """The rendered prompt is preserved on the result so the snapshot
    can audit exactly what was sent. Useful when comparing verdicts
    across prompt versions."""
    runner = _fake_runner_returning(_canonical_markdown())
    result = run_primary_pass(
        _minimal_cluster(), cwd=tmp_path, claude_runner=runner,
    )
    # The topic appears inside the rendered prompt's JSON payload.
    assert "ev charger installation cost" in result.rendered_prompt
    # And the standing prompt's system-message preamble.
    assert "niche analyst" in result.rendered_prompt


def test_run_primary_pass_threads_operator_profile_into_render(tmp_path):
    """Operator profile flows through build_payload AND
    render_primary_prompt — verify by inspecting the rendered
    prompt for the operator var substitutions."""
    runner = _fake_runner_returning(_canonical_markdown())
    profile = OperatorProfile(
        expertise=["SEO programmatic content"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )
    result = run_primary_pass(
        _minimal_cluster(), cwd=tmp_path,
        operator_profile=profile, claude_runner=runner,
    )
    assert "SEO programmatic content" in result.rendered_prompt
    assert "builder" in result.rendered_prompt
    assert "weekly" in result.rendered_prompt


def test_run_primary_pass_default_cwd_is_dot(tmp_path, monkeypatch):
    """When `cwd` is omitted, the runner uses `Path(".")` — the
    `run_claude_text` subprocess inherits the caller's working dir
    rather than failing on a None argument."""
    captured: dict = {}

    def capturing_runner(prompt, *, cwd, budget_usd, timeout_s):
        captured["cwd"] = cwd
        return ClaudeTextResult(ok=True, text=_canonical_markdown(),
                                cost_usd=0.01, duration_s=2.0,
                                error=None, raw_output="")
    run_primary_pass(_minimal_cluster(), claude_runner=capturing_runner)
    assert captured["cwd"] == Path(".")


def test_run_primary_pass_passes_budget_and_timeout(tmp_path):
    """Budget cap + timeout flow through to the Claude CLI subprocess —
    a regression here could let the runner exceed the operator's
    intended cost ceiling."""
    captured: dict = {}

    def capturing_runner(prompt, *, cwd, budget_usd, timeout_s):
        captured["budget_usd"] = budget_usd
        captured["timeout_s"] = timeout_s
        return ClaudeTextResult(ok=True, text=_canonical_markdown(),
                                cost_usd=0.0, duration_s=0.0,
                                error=None, raw_output="")
    run_primary_pass(_minimal_cluster(), cwd=tmp_path,
                     budget_usd=1.25, timeout_s=60,
                     claude_runner=capturing_runner)
    assert captured["budget_usd"] == 1.25
    assert captured["timeout_s"] == 60


# ---------- failure paths ----------


def test_run_primary_pass_raises_on_cli_failure(tmp_path):
    """`run_claude_text` returning ok=False → `InterpretivePassError`
    with the underlying error in the message. Caller (the
    orchestrator) catches this and surfaces it to the operator."""
    runner = _fake_runner_returning(
        "", ok=False, error="claude-not-found",
    )
    with pytest.raises(InterpretivePassError) as exc:
        run_primary_pass(_minimal_cluster(), cwd=tmp_path,
                         claude_runner=runner)
    assert "claude-not-found" in str(exc.value)


def test_run_primary_pass_raises_on_unparseable_response(tmp_path):
    """LLM returns markdown that's missing required sections →
    `InterpretivePassError` wraps the underlying `VerdictParseError`
    so the orchestrator sees one exception type from this layer."""
    bad_response = "Here's my thought but I didn't follow the format."
    runner = _fake_runner_returning(bad_response)
    with pytest.raises(InterpretivePassError) as exc:
        run_primary_pass(_minimal_cluster(), cwd=tmp_path,
                         claude_runner=runner)
    assert "parse" in str(exc.value).lower()


def test_run_primary_pass_raises_on_invalid_verdict_token(tmp_path):
    """LLM hallucinates a non-canonical verdict ("SHIP" / "MAYBE") →
    parse fails inside the runner, wrapped as InterpretivePassError."""
    bad_response = (
        "### verdict\nMAYBE\n\n"   # not in {GO, NICHE-DOWN, NO-GO}
        "### confidence\nHIGH\n\n"
        "### reasoning\nreasoning."
    )
    runner = _fake_runner_returning(bad_response)
    with pytest.raises(InterpretivePassError):
        run_primary_pass(_minimal_cluster(), cwd=tmp_path,
                         claude_runner=runner)


def test_run_primary_pass_cli_failure_preserves_cost_in_message(tmp_path):
    """When the CLI fails mid-call (timeout, partial response), the
    error message includes cost so far — the operator can audit
    whether the failure burned subscription quota."""
    runner = _fake_runner_returning(
        "", ok=False, error="timeout",
        cost=0.02, duration=180.0,
    )
    with pytest.raises(InterpretivePassError) as exc:
        run_primary_pass(_minimal_cluster(), cwd=tmp_path,
                         claude_runner=runner)
    msg = str(exc.value)
    assert "timeout" in msg
    assert "0.0200" in msg or "$0.02" in msg


# ---------- production-default routing ----------


def test_run_primary_pass_defaults_to_real_run_claude_text(monkeypatch, tmp_path):
    """When `claude_runner` is omitted, the runner picks up
    `fix_helpers.run_claude_text` automatically — confirms the
    production callsite isn't accidentally stub-only."""
    captured: dict = {"called": False}

    # Patch the imported name inside interpretive_pass so the runner
    # uses our stub when `claude_runner` is None.
    from portfolio import interpretive_pass

    def fake_real_run_claude_text(prompt, *, cwd, budget_usd, timeout_s):
        captured["called"] = True
        return ClaudeTextResult(ok=True, text=_canonical_markdown(),
                                cost_usd=0.0, duration_s=0.0,
                                error=None, raw_output="")
    monkeypatch.setattr(interpretive_pass, "run_claude_text",
                        fake_real_run_claude_text)
    run_primary_pass(_minimal_cluster(), cwd=tmp_path)
    # No `claude_runner` kwarg passed → falls back to the imported
    # `run_claude_text` (which we just patched).
    assert captured["called"] is True
