"""Tests for v8.E — `render_primary_prompt` (combines the
`niche_evaluation_v1.md` standing prompt with the build_payload
output to produce the final string `run_claude_text` consumes).

Pure-string composition — no LLM calls, no network. Tests fix the
contract so subsequent commits (response parser, runner, orchestrator
wiring) can rely on this output shape.
"""
from __future__ import annotations

import json

import pytest

from portfolio.interpretive_pass import (
    PRIMARY_PROMPT_NAME,
    build_payload,
    render_primary_prompt,
)
from portfolio.operator_profile import OperatorProfile
from portfolio.prompt_loader import UnfilledPlaceholderError


def _minimal_cluster() -> dict:
    return {
        "topic": "ev charger installation cost",
        "cluster_queries": ["ev charger installation cost"],
        "gates": {"gate_1_market": {"status": "PASS"}},
        "operator_fit": {"warnings": []},
        "per_query_results": [
            {"query": "ev charger installation cost",
             "organic_results": [{"position": 1, "domain": "x.com",
                                  "url": "https://x.com/", "title": "X",
                                  "snippet": "long", "displayed_link": "x.com"}],
             "features": {"ai_overview": {"present": True}}},
        ],
    }


def _full_profile() -> OperatorProfile:
    return OperatorProfile(
        expertise=["SEO programmatic content", "Python CLI tooling"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )


# ---------- structural contract ----------


def test_render_primary_prompt_returns_single_string():
    payload = build_payload(_minimal_cluster(), operator_profile=_full_profile())
    rendered = render_primary_prompt(payload, operator_profile=_full_profile())
    assert isinstance(rendered, str)
    assert len(rendered) > 100   # the standing prompt is ~3KB at minimum


def test_render_primary_prompt_substitutes_operator_vars():
    payload = build_payload(_minimal_cluster(), operator_profile=_full_profile())
    rendered = render_primary_prompt(payload, operator_profile=_full_profile())
    # System-message portion carries the operator values verbatim.
    assert "SEO programmatic content" in rendered
    assert "builder" in rendered
    assert "weekly" in rendered
    # And no unresolved placeholder remains.
    assert "{{operator_expertise}}" not in rendered
    assert "{{operator_workflow_preference}}" not in rendered
    assert "{{operator_motivation_cadence}}" not in rendered


def test_render_primary_prompt_embeds_payload_json():
    """The JSON payload appears inside a ```json fence after the
    `---` delimiter — so the rendered string reads cleanly as
    "system message → divider → input payload"."""
    payload = build_payload(_minimal_cluster())
    rendered = render_primary_prompt(payload)
    # The literal "INPUT PAYLOAD" marker and fence appear.
    assert "INPUT PAYLOAD" in rendered
    assert "```json" in rendered
    # And the topic / queries from the payload appear inside.
    assert "ev charger installation cost" in rendered


def test_render_primary_prompt_payload_json_is_parseable():
    """The JSON block must round-trip — the LLM should see well-formed
    structured data, not a malformed approximation. Catches accidental
    dataclass-in-payload bugs that would corrupt the fence."""
    payload = build_payload(_minimal_cluster())
    rendered = render_primary_prompt(payload)
    fence_start = rendered.index("```json\n") + len("```json\n")
    fence_end = rendered.index("```", fence_start)
    json_body = rendered[fence_start:fence_end].strip()
    parsed = json.loads(json_body)
    assert parsed["topic"] == "ev charger installation cost"


def test_render_primary_prompt_separates_system_and_payload_with_divider():
    rendered = render_primary_prompt(build_payload(_minimal_cluster()))
    # The horizontal-rule divider appears between system prompt and
    # payload — a quick visual marker when reading the rendered string.
    sys_idx = rendered.index("niche analyst")   # first line of system prompt
    divider_idx = rendered.index("---")
    payload_idx = rendered.index("INPUT PAYLOAD")
    assert sys_idx < divider_idx < payload_idx


# ---------- operator-profile fallbacks ----------


def test_render_primary_prompt_no_profile_uses_not_configured(monkeypatch):
    """No operator profile → all three operator vars render as
    `(not configured)`. The LLM should know honestly when constraints
    aren't set rather than inheriting dataclass defaults (`mixed` /
    `monthly`) that imply operator choice."""
    payload = build_payload(_minimal_cluster())
    rendered = render_primary_prompt(payload, operator_profile=None)
    assert rendered.count("(not configured)") == 3


def test_render_primary_prompt_default_profile_uses_not_configured():
    """A default-valued OperatorProfile is the same as no profile —
    operator hasn't set anything, just instantiated the dataclass."""
    rendered = render_primary_prompt(
        build_payload(_minimal_cluster()),
        operator_profile=OperatorProfile(),
    )
    assert rendered.count("(not configured)") == 3


def test_render_primary_prompt_partial_profile_uses_real_values():
    """Operator set workflow + cadence but no expertise yet — render
    the real workflow/cadence values; expertise becomes
    `(none declared)`."""
    partial = OperatorProfile(
        expertise=[],
        workflow_preference="writer",
        motivation_cadence="quarterly",
    )
    rendered = render_primary_prompt(
        build_payload(_minimal_cluster()), operator_profile=partial,
    )
    # workflow + cadence are the operator's real picks.
    assert "writer" in rendered
    assert "quarterly" in rendered
    # Expertise renders as the "none declared" sentinel.
    assert "(none declared)" in rendered
    # But this is NOT a fully-empty profile — only one "(not configured)"
    # placeholder slot lit. (Actually zero, since partial profile
    # routes through the non-default branch.)
    assert "(not configured)" not in rendered


# ---------- placeholder-drift safety ----------


def test_render_primary_prompt_raises_on_unfilled_placeholder(monkeypatch):
    """If `niche_evaluation_v1.md` ever adds a new `{{var}}` and the
    operator-var substitution list doesn't, the renderer must fail
    loudly (UnfilledPlaceholderError) rather than send a half-rendered
    prompt to the LLM. Simulate the drift by injecting a template
    that references an unknown placeholder."""
    from portfolio import interpretive_pass
    bad_template = (
        "Test system message.\n"
        "- Expertise: {{operator_expertise}}\n"
        "- Workflow: {{operator_workflow_preference}}\n"
        "- Cadence: {{operator_motivation_cadence}}\n"
        "- New thing: {{operator_blood_type}}\n"   # not in the substitution dict
    )
    monkeypatch.setattr(interpretive_pass, "load_prompt", lambda name: bad_template)
    with pytest.raises(UnfilledPlaceholderError) as exc:
        render_primary_prompt(build_payload(_minimal_cluster()))
    assert "operator_blood_type" in str(exc.value)


# ---------- prompt-name plumbing ----------


def test_primary_prompt_name_constant_matches_filename():
    """`PRIMARY_PROMPT_NAME` is the filename (sans extension) of the
    standing prompt — `prompt_loader.load_prompt` resolves it against
    `prompts/`. Pinning the constant here catches a rename of either
    the prompt file or the constant."""
    assert PRIMARY_PROMPT_NAME == "niche_evaluation_v1"


def test_render_primary_prompt_accepts_alternate_prompt_name(monkeypatch):
    """Caller can override `prompt_name` to render against a
    different standing prompt (audit pass uses
    `adversarial_audit_v1`). Confirms the dispatch routes through
    load_prompt + render_prompt correctly."""
    from portfolio import interpretive_pass
    monkeypatch.setattr(
        interpretive_pass, "load_prompt",
        lambda name: f"loaded:{name}\n"
                     "- Expertise: {{operator_expertise}}\n"
                     "- Workflow: {{operator_workflow_preference}}\n"
                     "- Cadence: {{operator_motivation_cadence}}",
    )
    rendered = render_primary_prompt(
        build_payload(_minimal_cluster()),
        prompt_name="some_other_prompt",
    )
    assert "loaded:some_other_prompt" in rendered
