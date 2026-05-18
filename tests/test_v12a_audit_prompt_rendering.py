"""Tests for v12.A — `audit_pass.render_audit_prompt`.

Pure prompt assembly — no LLM calls. Pins the contract between the
audit payload (v8.J) and the audit-pass runner (v12.C): everything
the audit-model LLM sees is determined here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from portfolio.audit_pass import (
    AUDIT_PROMPT_NAME,
    build_audit_payload,
    render_audit_prompt,
)
from portfolio.operator_profile import OperatorProfile
from portfolio.prompt_loader import (
    PROMPTS_DIR,
    UnfilledPlaceholderError,
    load_prompt,
)


# ---------- fixtures ----------


def _minimal_cluster() -> dict:
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


def _full_primary_verdict() -> dict:
    return {
        "verdict": "NICHE-DOWN",
        "confidence": "MEDIUM",
        "reasoning": (
            "Gate 2 FAIL keys on regex patterns this cluster doesn't "
            "actually match. The real moat is permit-cost data."
        ),
        "moat_required": True,
        "moat_prompt": "What's your unfair advantage over X?",
        "reductions": ["Local-installer cost calculator"],
        "operator_fit_warnings": [],
        "blind_spot_self_report": "I may have over-weighted permit-cost.",
    }


def _payload() -> dict:
    return build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
    )


# ---------- happy path ----------


def test_render_audit_prompt_returns_str():
    out = render_audit_prompt(_payload())
    assert isinstance(out, str)
    assert out  # non-empty


def test_render_audit_prompt_includes_template_body():
    """The rendered output starts with the audit prompt body (H1
    stripped per load_prompt). Confirms we're not double-loading or
    accidentally dropping the prompt text."""
    template = load_prompt(AUDIT_PROMPT_NAME)
    out = render_audit_prompt(_payload())
    # The template body appears at the top of the rendered prompt.
    assert out.startswith(template)


def test_render_audit_prompt_includes_payload_in_json_fence():
    """The payload is JSON-encoded inside a ```json fence so it
    reads cleanly in both the prompt sent to the LLM and any debug
    snapshot. The audit-pass runner depends on this shape — a plain
    json dump without the fence would be a regression."""
    payload = _payload()
    out = render_audit_prompt(payload)
    assert "```json" in out
    assert "```" in out.split("```json", 1)[1]   # closing fence
    # The actual JSON content is in there.
    assert json.dumps(payload, indent=2, default=str) in out


def test_render_audit_prompt_has_delimiter():
    """The `---` line between prompt body and payload makes the
    boundary scannable for humans reading the debug capture, and
    matches `render_primary_prompt`'s shape so snapshots are visually
    consistent across passes."""
    out = render_audit_prompt(_payload())
    assert "\n---\n" in out


def test_render_audit_prompt_includes_input_payload_label():
    """The `INPUT PAYLOAD (JSON):` label appears before the fence —
    the audit prompt teaches the LLM to look for this label, so
    changing the wording would silently break the prompt's
    instructions."""
    out = render_audit_prompt(_payload())
    assert "INPUT PAYLOAD (JSON):" in out


def test_render_audit_prompt_payload_contains_primary_markdown():
    """The audit needs to read the primary's reasoning. Specifically
    confirms `primary_response_markdown` lands in the JSON body — not
    in a separate section — because the audit prompt expects to find
    it under that key."""
    out = render_audit_prompt(_payload())
    assert "primary_response_markdown" in out
    # The primary's verdict text reaches the rendered prompt via the
    # reconstructed markdown.
    assert "NICHE-DOWN" in out


def test_render_audit_prompt_does_not_leak_blind_spot():
    """Anti-anchoring contract from v8.J: the primary's
    `blind_spot_self_report` is stripped from
    `primary_response_markdown`. The rendered prompt must not contain
    the blind-spot *content* — otherwise the audit anchors on the
    same concerns the primary already surfaced, defeating the
    steel-man purpose.

    The field NAME `blind_spot_self_report` does appear in the audit
    prompt's instructions (explaining why the audit won't see it),
    so this test asserts on the actual blind-spot text, not the
    schema field name.
    """
    out = render_audit_prompt(_payload())
    # The blind-spot text from `_full_primary_verdict()` is absent.
    assert "over-weighted permit-cost" not in out
    # And the reconstructed-markdown header `### blind_spot_self_report`
    # is absent — that's the form it would have if the v8.J helper
    # leaked it (rather than the prose mention in the prompt body).
    assert "### blind_spot_self_report" not in out


def test_render_audit_prompt_with_operator_profile():
    """Operator profile flows through `build_audit_payload` into
    `operator_profile_summary` (a payload field, not a prompt
    placeholder — the audit prompt deliberately reads it as data).
    The rendered prompt must surface that summary verbatim."""
    profile = OperatorProfile(
        expertise=["SEO programmatic content"],
        workflow_preference="builder",
        motivation_cadence="weekly",
    )
    payload = build_audit_payload(
        _minimal_cluster(),
        primary_verdict=_full_primary_verdict(),
        operator_profile=profile,
    )
    out = render_audit_prompt(payload)
    assert "SEO programmatic content" in out
    assert "builder" in out
    assert "weekly" in out


def test_render_audit_prompt_no_profile_renders_sentinel():
    """No operator profile → the payload's `operator_profile_summary`
    is the "no operator profile configured" sentinel; the rendered
    prompt surfaces that. Reasserts the audit's honesty contract:
    we tell the LLM when operator constraints aren't set rather than
    silently passing dataclass defaults."""
    out = render_audit_prompt(_payload())
    assert "no operator profile configured" in out


# ---------- drift protection ----------


def test_render_audit_prompt_raises_if_template_has_placeholders(tmp_path):
    """The audit prompt today has no `{{var}}` placeholders. If a
    future edit introduces one, `render_audit_prompt` must raise
    `UnfilledPlaceholderError` at assembly time — BEFORE the LLM call
    burns a token budget on a half-rendered prompt.

    We exercise this by pointing the renderer at a synthetic prompt
    file with a placeholder injected.
    """
    bad_prompt = PROMPTS_DIR / "_test_audit_with_placeholder.md"
    bad_prompt.write_text(
        "# _test_audit_with_placeholder.md\n\n"
        "You are an adversarial auditor for {{operator_name}}.\n\n"
        "Critique the primary verdict.\n"
    )
    try:
        with pytest.raises(UnfilledPlaceholderError) as exc:
            render_audit_prompt(_payload(),
                                prompt_name="_test_audit_with_placeholder")
        assert "operator_name" in exc.value.placeholders
    finally:
        bad_prompt.unlink(missing_ok=True)


# ---------- defaults & overrides ----------


def test_render_audit_prompt_uses_v1_by_default():
    """Default prompt name is the v1 audit prompt. Pins the contract
    so a future v2 prompt addition requires an explicit caller
    opt-in — silent default-bump would change LLM behavior without
    a code review touching the runner."""
    assert AUDIT_PROMPT_NAME == "adversarial_audit_v1"
    # The default load is observable: the body of the v1 prompt
    # appears in the default-rendered output.
    template_v1 = load_prompt("adversarial_audit_v1")
    out = render_audit_prompt(_payload())
    assert out.startswith(template_v1)


def test_render_audit_prompt_honors_prompt_name_override(tmp_path):
    """Explicit `prompt_name=` argument overrides the default —
    needed for testing alternate prompt versions, and forward-compat
    for a v2 prompt that ships alongside v1."""
    alt = PROMPTS_DIR / "_test_audit_alt.md"
    alt.write_text(
        "# _test_audit_alt.md\n\n"
        "ALTERNATE AUDIT BODY — different from v1.\n"
    )
    try:
        out = render_audit_prompt(_payload(), prompt_name="_test_audit_alt")
        assert "ALTERNATE AUDIT BODY" in out
        # Default body NOT in there.
        v1 = load_prompt("adversarial_audit_v1")
        # The v1 body and the alt body don't overlap on a long unique
        # substring — pick something that's distinctively v1.
        # The audit_pass_v1 prompt contains the word "adversarial" in
        # its instructions; the alt one doesn't.
        if "steel-man" in v1.lower():
            assert "steel-man" not in out.lower()
    finally:
        alt.unlink(missing_ok=True)
