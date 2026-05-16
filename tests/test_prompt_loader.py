"""Tests for v8.E — prompt loader + renderer (`portfolio.prompt_loader`)."""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.prompt_loader import (
    PROMPTS_DIR,
    PromptNotFoundError,
    UnfilledPlaceholderError,
    find_placeholders,
    load_prompt,
    render_prompt,
)


# ---------- load_prompt ----------


def test_load_existing_prompt():
    text = load_prompt("niche_evaluation_v1")
    assert text  # non-empty
    assert "{{operator_expertise}}" in text


def test_load_appends_md_extension():
    a = load_prompt("niche_evaluation_v1")
    b = load_prompt("niche_evaluation_v1.md")
    assert a == b


def test_load_missing_prompt_raises():
    with pytest.raises(PromptNotFoundError) as excinfo:
        load_prompt("does_not_exist_v1")
    assert "does_not_exist_v1.md" in str(excinfo.value)


def test_load_strips_doc_h1_header(tmp_path: Path, monkeypatch):
    """The `# filename.md` heading at the top of a prompt is operator-
    facing documentation, not part of the model input. The loader
    strips it so the model sees the actual instructions starting at
    the first content paragraph."""
    fake = tmp_path / "fake_v1.md"
    fake.write_text("# fake_v1.md\n\nYou are an analyst.\nGo.\n")

    import portfolio.prompt_loader as pl
    monkeypatch.setattr(pl, "PROMPTS_DIR", tmp_path)

    text = load_prompt("fake_v1")
    assert text.startswith("You are an analyst.")
    assert "# fake_v1.md" not in text


def test_load_without_h1_returns_unchanged(tmp_path: Path, monkeypatch):
    """A prompt that doesn't open with an H1 is returned verbatim."""
    fake = tmp_path / "fake_v1.md"
    fake.write_text("You are an analyst.\nGo.\n")

    import portfolio.prompt_loader as pl
    monkeypatch.setattr(pl, "PROMPTS_DIR", tmp_path)

    text = load_prompt("fake_v1")
    assert text == "You are an analyst.\nGo.\n"


# ---------- render_prompt ----------


def test_render_basic_substitution():
    out = render_prompt("Hello {{name}}!", name="world")
    assert out == "Hello world!"


def test_render_multiple_substitutions():
    out = render_prompt(
        "Expertise: {{expertise}}, cadence: {{cadence}}.",
        expertise="SEO", cadence="weekly",
    )
    assert out == "Expertise: SEO, cadence: weekly."


def test_render_repeats_substitutions():
    out = render_prompt("{{x}} and {{x}}.", x="bar")
    assert out == "bar and bar."


def test_render_ignores_unused_substitutions():
    """Extra vars passed but not referenced → fine, not an error."""
    out = render_prompt("Hello {{name}}!", name="world", extra="ignored")
    assert out == "Hello world!"


def test_render_raises_on_unfilled_placeholder():
    with pytest.raises(UnfilledPlaceholderError) as excinfo:
        render_prompt("Hello {{name}} from {{place}}.", name="X")
    assert excinfo.value.placeholders == ["place"]


def test_render_lists_all_unfilled_placeholders():
    with pytest.raises(UnfilledPlaceholderError) as excinfo:
        render_prompt("{{a}} {{b}} {{c}}")
    assert excinfo.value.placeholders == ["a", "b", "c"]


def test_render_dedups_unfilled_placeholders():
    """The error lists each missing name once even if it appears multiple times."""
    with pytest.raises(UnfilledPlaceholderError) as excinfo:
        render_prompt("{{a}} {{a}} {{b}}")
    assert excinfo.value.placeholders == ["a", "b"]


def test_render_is_case_insensitive_on_lookup():
    """`{{Name}}` matches a substitution of `name=`. Helps catch
    case-mismatch typos when the prompt author and the call-site
    disagree."""
    out = render_prompt("Hello {{Name}}!", name="world")
    assert out == "Hello world!"


def test_render_tolerates_whitespace_in_placeholder():
    out = render_prompt("Hello {{  name  }}!", name="world")
    assert out == "Hello world!"


def test_render_coerces_values_to_str():
    """Numbers and lists pass through `str()`. Caller is responsible
    for fancier rendering."""
    out = render_prompt("Count: {{n}}, items: {{xs}}",
                        n=42, xs=["a", "b"])
    assert "42" in out
    assert "['a', 'b']" in out


def test_render_leaves_unrelated_braces_alone():
    """Curly braces that aren't `{{var}}` placeholders survive
    untouched — important for code blocks inside prompts (PRD §10.G
    rationale for the custom regex over `str.format()`)."""
    template = "Code: `def f(x): return {x}` end."
    out = render_prompt(template)
    assert out == template


def test_render_empty_template():
    assert render_prompt("") == ""


def test_render_template_without_placeholders():
    s = "no placeholders here"
    assert render_prompt(s, unused="value") == s


# ---------- find_placeholders ----------


def test_find_placeholders_returns_names_in_order():
    template = "{{a}} {{b}} {{a}} {{c}}"
    assert find_placeholders(template) == ["a", "b", "a", "c"]


def test_find_placeholders_returns_empty_when_none():
    assert find_placeholders("nothing here") == []


# ---------- integration with shipped prompts ----------


def test_niche_evaluation_v1_renders_with_operator_vars():
    """The shipped primary prompt renders cleanly when given the three
    operator-profile vars it references."""
    template = load_prompt("niche_evaluation_v1")
    out = render_prompt(
        template,
        operator_expertise="SEO and programmatic content; Python CLI tooling",
        operator_workflow_preference="builder",
        operator_motivation_cadence="weekly",
    )
    assert "{{operator_expertise}}" not in out
    assert "{{operator_workflow_preference}}" not in out
    assert "{{operator_motivation_cadence}}" not in out
    assert "SEO and programmatic content" in out
    assert "builder" in out
    assert "weekly" in out


def test_niche_evaluation_v1_lists_only_known_placeholders():
    """The primary prompt references exactly the three operator vars
    declared when the niche_evaluation_v1 prompt was drafted — guards
    against accidental new placeholders sneaking into the prompt
    without the orchestrator knowing to fill them."""
    template = load_prompt("niche_evaluation_v1")
    placeholders = set(find_placeholders(template))
    assert placeholders == {
        "operator_expertise",
        "operator_workflow_preference",
        "operator_motivation_cadence",
    }


def test_niche_evaluation_v1_unfilled_raises():
    """Calling the primary prompt without the required vars surfaces
    a clean UnfilledPlaceholderError naming every missing var."""
    template = load_prompt("niche_evaluation_v1")
    with pytest.raises(UnfilledPlaceholderError) as excinfo:
        render_prompt(template)
    assert "operator_expertise" in excinfo.value.placeholders
    assert "operator_workflow_preference" in excinfo.value.placeholders
    assert "operator_motivation_cadence" in excinfo.value.placeholders


def test_adversarial_audit_v1_has_no_placeholders():
    """The audit prompt is intentionally operator-agnostic — its
    context comes from the user-message payload, not the system
    message. Verify no `{{var}}` slipped in by accident."""
    template = load_prompt("adversarial_audit_v1")
    assert find_placeholders(template) == []
    # And render() with no vars should succeed unchanged.
    assert render_prompt(template) == template


def test_prompts_dir_resolves_to_repo_root():
    """Per resolved §10.A: prompts/ at repo root, not under src/ or data/."""
    assert PROMPTS_DIR.name == "prompts"
    assert (PROMPTS_DIR / "README.md").exists()
