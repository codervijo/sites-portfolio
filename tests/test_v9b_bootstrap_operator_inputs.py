"""Tests for v9.B — `new bootstrap` interactive prompts collect the
5 operator-input AI_AGENTS sections; per-section flags override the
prompt; --non-interactive skips all prompts.

Two layers tested:
  1. `_collect_operator_inputs(...)` helper in cli.py — pure logic
     for merging flag values + interactive prompts.
  2. `bootstrap.bootstrap(... operator_inputs=...)` end-to-end —
     scaffolds a project, verifies the rendered AI_AGENTS.md has the
     supplied content substituted in place of the
     `(to be filled in)` placeholders.

`typer.prompt` is monkeypatched in the helper tests so no real TTY
is needed.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from portfolio import bootstrap_cli as cli_mod  # v35.F incr 8: these helpers moved out of cli.py
from portfolio.bootstrap import bootstrap


# ---------- _collect_operator_inputs ----------


def _collect(**kwargs):
    """Defaults match the CLI command's `typer.Option('')` defaults."""
    return cli_mod._collect_operator_inputs(
        summary=kwargs.get("summary", ""),
        audience=kwargs.get("audience", ""),
        icp=kwargs.get("icp", ""),
        goal=kwargs.get("goal", ""),
        content_strategy=kwargs.get("content_strategy", ""),
        non_interactive=kwargs.get("non_interactive", False),
    )


def test_collect_returns_dict_keyed_by_canonical_heading(monkeypatch):
    """Output keys are the canonical headings — not the CLI flag
    names. Downstream renderer (`_ai_agents_md`) looks up by heading."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    inputs = _collect(non_interactive=True)
    assert set(inputs.keys()) == {
        "Summary", "Audience", "ICP", "Goals", "Content strategy",
    }


def test_collect_all_flags_take_precedence_no_prompt(monkeypatch):
    """When every section has a flag value, no interactive prompt
    runs. Patch `typer.prompt` to fail loud if invoked."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not be called")))
    inputs = _collect(
        summary="One-line summary.",
        audience="Broad demo.",
        icp="Specific ICP.",
        goal="Primary goal.",
        content_strategy="Page-type mix.",
    )
    assert inputs == {
        "Summary": "One-line summary.",
        "Audience": "Broad demo.",
        "ICP": "Specific ICP.",
        "Goals": "Primary goal.",
        "Content strategy": "Page-type mix.",
    }


def test_collect_non_interactive_skips_all_prompts(monkeypatch):
    """--non-interactive + no flag values → every section empty.
    Renderer will use placeholders."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not be called")))
    inputs = _collect(non_interactive=True)
    assert inputs == {
        "Summary": "",
        "Audience": "",
        "ICP": "",
        "Goals": "",
        "Content strategy": "",
    }


def test_collect_prompts_for_missing_sections_only(monkeypatch):
    """One flag value supplied → that section skips its per-section
    prompt; the other 4 sections get prompted in canonical order.

    2026-05-29: the collector leads with a full cut-and-paste prompt,
    then prompts each still-empty section. Paragraph sections (Summary /
    ICP / Content strategy) use `_prompt_multiline`; one-line sections
    (Audience / Goals) stay on `typer.prompt`. Patch both."""
    prompts_called = []

    def fake_prompt(prompt_str, default="", show_default=True):
        prompts_called.append(prompt_str)
        return "answer"
    monkeypatch.setattr(typer, "prompt", fake_prompt)
    monkeypatch.setattr(
        cli_mod, "_prompt_multiline",
        lambda *a, **k: (prompts_called.append(a[0] if a else "") or "answer"),
    )
    inputs = _collect(summary="From flag.")
    assert inputs["Summary"] == "From flag."
    assert inputs["Audience"] == "answer"
    assert inputs["ICP"] == "answer"
    assert inputs["Goals"] == "answer"
    assert inputs["Content strategy"] == "answer"
    # 5 prompts: the leading full-paste prompt + 4 section prompts
    # (Summary supplied via flag, so it isn't prompted section-by-section).
    assert len(prompts_called) == 5


def test_collect_prompts_carry_prompt_order_numbers(monkeypatch):
    """Bug-fix 2026-05-28: each section prompt carries an inline
    `[N/9]` matching the preflight banner / LLM-template order so the
    operator can't blend a later prompt's description into an earlier
    answer (the Audience/ICP confusion).

    Multiline section labels (Summary/ICP/Content strategy) ride on
    `_prompt_multiline`'s arg; single-line labels (Audience/Goals)
    print via `console.print` above the `  >` input — capture both."""
    seen = []

    def fake_prompt(prompt_str, default="", show_default=True):
        return "answer"
    monkeypatch.setattr(typer, "prompt", fake_prompt)
    monkeypatch.setattr(
        cli_mod, "_prompt_multiline",
        lambda *a, **k: (seen.append(a[0] if a else "") or ""),
    )
    monkeypatch.setattr(
        cli_mod.console, "print",
        lambda *a, **k: seen.append(" ".join(str(x) for x in a)),
    )
    _collect()
    joined = "\n".join(seen)
    # Prompt-order numbers from the preflight banner — all 5 sections.
    for num in ("[2/9]", "[3/9]", "[4/9]", "[5/9]", "[6/9]"):
        assert num in joined, f"missing prompt number {num}"


def test_collect_echoes_saved_confirmation_after_each_answer(monkeypatch):
    """Bug-fix 2026-05-28: after a non-empty answer, a `✓ saved as
    <section>` line prints so the next prompt's description doesn't
    blend into the prior section's input area."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "audience answer")
    monkeypatch.setattr(cli_mod, "_prompt_multiline",
                        lambda *a, **k: "para answer")
    captured = []
    monkeypatch.setattr(
        cli_mod.console, "print",
        lambda *a, **k: captured.append(" ".join(str(x) for x in a)),
    )
    _collect()
    joined = "\n".join(captured)
    for heading in ("Summary", "Audience", "ICP", "Goals", "Content strategy"):
        assert f"saved as {heading}" in joined, f"missing echo: {heading}"


def test_collect_no_saved_echo_for_skipped_section(monkeypatch):
    """Empty answer (operator hit Enter to skip) → no `saved as` echo
    for that section (nothing was saved)."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    monkeypatch.setattr(cli_mod, "_prompt_multiline", lambda *a, **k: "")
    captured = []
    monkeypatch.setattr(
        cli_mod.console, "print",
        lambda *a, **k: captured.append(" ".join(str(x) for x in a)),
    )
    _collect()
    joined = "\n".join(captured)
    assert "saved as" not in joined


def test_collect_empty_prompt_answer_renders_placeholder_downstream(monkeypatch):
    """Pressing Enter on a prompt → empty string in the inputs dict
    → renderer drops in the `(to be filled in)` placeholder. The
    helper itself just preserves the empty string; the placeholder
    behavior lives in `_ai_agents_md`."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    monkeypatch.setattr(cli_mod, "_prompt_multiline", lambda *a, **k: "")
    inputs = _collect()
    assert inputs["Summary"] == ""


def test_collect_strips_whitespace_around_flag_values(monkeypatch):
    """Operators sometimes paste content with surrounding newlines.
    Strip so the rendered AI_AGENTS.md doesn't carry blank lines
    inside the section body."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    monkeypatch.setattr(cli_mod, "_prompt_multiline", lambda *a, **k: "")
    inputs = _collect(summary="   padded   \n", non_interactive=True)
    assert inputs["Summary"] == "padded"


def test_collect_strips_whitespace_around_prompt_answer(monkeypatch):
    """Bug-fix 2026-05-20: Summary now uses `_prompt_multiline`.
    Audience (typer.prompt) still strips; both helpers' answers land
    in the inputs dict via the same `.strip()` path."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: "   trailing-spaces   ")
    monkeypatch.setattr(cli_mod, "_prompt_multiline",
                        lambda *a, **k: "   trailing-spaces   ")
    inputs = _collect()
    # Both Summary (multiline) and Audience (typer.prompt) end up
    # stripped — `_prompt_multiline` returns text without trailing
    # newlines and the operator-inputs collector strips around it.
    assert inputs["Summary"] == "trailing-spaces"
    assert inputs["Audience"] == "trailing-spaces"


def test_collect_prompts_in_canonical_order(monkeypatch):
    """The interactive prompts should ask in the same order the
    sections appear in the canonical schema — preserves operator's
    mental model between the bootstrap flow and the rendered file."""

    def fake_prompt(prompt_str, default="", show_default=True):
        # The cli.py prompt is bare ("  >") because the heading is
        # rendered separately above via console.print. We can still
        # observe order by tracking call order.
        return ""

    # Track via a sentinel injected in console.print since that's
    # where the heading shows up.
    headings = []

    def capture_print(*args, **kw):
        for a in args:
            s = str(a)
            for h in ("Summary", "Audience", "ICP", "Goals",
                      "Content strategy"):
                if f"[cyan]{h}[/]" in s:
                    headings.append(h)

    monkeypatch.setattr(typer, "prompt", fake_prompt)
    # Bug-fix 2026-05-20: paragraph prompts now use `_prompt_multiline`.
    # It prints the label itself, so we capture headings from that
    # call too (the label arg is a rich-markup string containing
    # `[cyan]Summary[/]`).
    def fake_multiline(label, *, hint=None, detect_blob=False):
        capture_print(label)
        return ""
    monkeypatch.setattr(cli_mod, "_prompt_multiline", fake_multiline)
    monkeypatch.setattr(cli_mod.console, "print", capture_print)
    _collect()
    assert headings == ["Summary", "Audience", "ICP", "Goals", "Content strategy"]


# ---------- end-to-end: bootstrap writes operator inputs ----------


def test_bootstrap_substitutes_operator_inputs_into_ai_agents_md(tmp_path):
    """Pass `operator_inputs` to bootstrap → AI_AGENTS.md carries
    the operator content under the right H2 headings."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    operator_inputs = {
        "Summary": "agesdk.dev is a SaaS helping JS devs handle SB 361 / DROP compliance.",
        "Audience": "Independent JS/React Native developers shipping consumer apps with CA users.",
        "ICP": "RN/Expo developers + small-team CTOs who found the law via Twitter/email.",
        "Goals": "Reach 100 paying customers in the first year.",
        "Content strategy": "Compliance guide + decision tree + cost calculator.",
    }
    bootstrap(
        domain="agesdk.dev", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        operator_inputs=operator_inputs,
    )
    ai_md = (sites_root / "agesdk.dev" / "AI_AGENTS.md").read_text()

    # Every operator-input section's content appears under its
    # canonical heading.
    for heading, content in operator_inputs.items():
        # Heading present + content present.
        assert f"## {heading}" in ai_md
        assert content in ai_md
        # And the placeholder is NOT present for these sections.
        # The italic hint above each placeholder still appears (it's
        # part of the template), but the literal "(to be filled in)"
        # body should be replaced.
        # Check by looking at the body of each section.
        section_start = ai_md.index(f"## {heading}")
        # Body ends at next "## " or EOF.
        next_h2 = ai_md.find("\n## ", section_start + 5)
        body_end = next_h2 if next_h2 != -1 else len(ai_md)
        section_body = ai_md[section_start:body_end]
        assert "(to be filled in)" not in section_body
        assert content in section_body


def test_bootstrap_empty_operator_inputs_keeps_placeholders(tmp_path):
    """`operator_inputs={}` → all five operator-input sections render
    with `(to be filled in)` placeholders so CHECK_014's tier-1 fix
    can populate them later."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="empty.com", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        operator_inputs={},
    )
    ai_md = (sites_root / "empty.com" / "AI_AGENTS.md").read_text()
    for heading in ("Summary", "Audience", "ICP", "Goals", "Content strategy"):
        assert f"## {heading}" in ai_md
    # All five operator-input sections render with placeholders.
    assert ai_md.count("(to be filled in)") == 5


def test_bootstrap_partial_operator_inputs(tmp_path):
    """Mixed: Summary + ICP supplied, the other 3 left blank →
    rendered file has 2 real sections + 3 placeholders. Confirms
    per-section substitution doesn't bleed across sections."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="partial.com", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        operator_inputs={
            "Summary": "Real summary text.",
            "ICP": "Real ICP text.",
        },
    )
    ai_md = (sites_root / "partial.com" / "AI_AGENTS.md").read_text()
    assert "Real summary text." in ai_md
    assert "Real ICP text." in ai_md
    # Audience / Goals / Content strategy still have placeholders.
    assert ai_md.count("(to be filled in)") == 3


def test_bootstrap_default_no_operator_inputs_still_passes_check_014(tmp_path):
    """Backward-compat: omitting `operator_inputs` entirely (as old
    callers do) renders exactly the same file v9.A produced — all
    five operator-input sections with placeholders. CHECK_014 still
    passes on this output."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="legacy.com", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        # No operator_inputs kwarg
    )
    # Run CHECK_014 against the bootstrap output.
    from portfolio.checks.scaffold import (
        check_014_ai_agents_md_has_canonical_sections as check_014,
    )
    r = check_014.run(str(sites_root / "legacy.com"))
    assert r.status == "pass", (
        f"day-zero CHECK_014 failed on default bootstrap: {r.message}"
    )


def test_bootstrap_operator_inputs_does_not_break_other_canonical_sections(tmp_path):
    """The 5 template-driven sections (Tech stack / Building info /
    Deployment info / Versioning / Conventions) render the same
    whether operator_inputs is provided or not — they're rendered
    by the template renderer, not the operator."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="tmpl.com", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        operator_inputs={"Summary": "x"},
    )
    ai_md = (sites_root / "tmpl.com" / "AI_AGENTS.md").read_text()
    for heading in ("Tech stack", "Building info", "Deployment info",
                    "Versioning", "Conventions"):
        assert f"## {heading}" in ai_md
    # Tech stack body still mentions "Astro" (template-driven content
    # didn't get stomped by operator_inputs).
    assert "Astro" in ai_md
