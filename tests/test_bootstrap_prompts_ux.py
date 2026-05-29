"""Tests for the 2026-05-20 `new bootstrap` UX bug-fixes.

Four bugs covered:

  1. `_prompt_multiline()` — read stdin until Enter-Enter / EOF so
     multi-paragraph pastes don't overflow into the shell. Used for
     Summary / ICP / Content strategy / Growth hypothesis.
  2. `_resolve_git_url()` — interactive prompt for the Lovable
     GitHub repo URL (the 9th, but listed first, prompt). Skipped
     when `--git-url` or `--non-interactive` is set.
  3. `_render_bootstrap_preflight()` — banner listing all 9 upcoming
     prompts so the operator can prep paragraph-length answers.
  4. Registrar validation — tighten `_resolve_inventory_inputs` to
     accept porkbun/godaddy/namecheap/other only (case-insensitive),
     retry up to 3 times, then fall back to "other".

`typer.prompt` and `sys.stdin` are monkeypatched so no real TTY is
needed.
"""
from __future__ import annotations

import io

import pytest
import typer

from portfolio import cli as cli_mod


# ---------- _prompt_multiline ----------


def _patch_stdin(monkeypatch, text: str) -> None:
    """Replace `sys.stdin` with an in-memory buffer that yields
    `text` on `readline()`."""
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_prompt_multiline_single_line_terminated_by_blank_line(monkeypatch):
    """One line of input followed by Enter (blank line) → that line
    is returned. Operators who type a one-liner shouldn't have to
    hit Enter twice; the second blank Enter is the terminator."""
    _patch_stdin(monkeypatch, "just one line\n\n")
    result = cli_mod._prompt_multiline("label")
    assert result == "just one line"


def test_prompt_multiline_paragraph_with_blank_separator_kept(monkeypatch):
    """Multi-paragraph input with a single blank line between
    paragraphs is preserved verbatim. Terminator is two consecutive
    blank lines."""
    text = "para one line one\npara one line two\n\npara two\n\n\n"
    _patch_stdin(monkeypatch, text)
    result = cli_mod._prompt_multiline("label")
    assert result == "para one line one\npara one line two\n\npara two"


def test_prompt_multiline_empty_input_returns_empty_string(monkeypatch):
    """Two blank lines immediately → empty result. Operator hit
    Enter twice to skip the prompt."""
    _patch_stdin(monkeypatch, "\n\n")
    result = cli_mod._prompt_multiline("label")
    assert result == ""


def test_prompt_multiline_eof_ends_input_early(monkeypatch):
    """Ctrl-D (EOF) ends input immediately — no need for trailing
    blank lines. The captured buffer is returned as-is (trailing
    blanks stripped)."""
    _patch_stdin(monkeypatch, "line one\nline two\n")
    result = cli_mod._prompt_multiline("label")
    # readline returns "" at EOF after the last newline; helper stops.
    assert result == "line one\nline two"


def test_prompt_multiline_strips_trailing_blank_lines(monkeypatch):
    """Trailing blank lines (before the terminator) are stripped
    from the result so AI_AGENTS.md sections don't get padded."""
    _patch_stdin(monkeypatch, "content\n\n\n")
    result = cli_mod._prompt_multiline("label")
    assert result == "content"


def test_prompt_multiline_paste_with_command_like_text(monkeypatch):
    """The exact paste-overflow shape that triggered the bug:
    paragraphs containing words like "The" / "TAM:" that the shell
    would otherwise try to execute as commands. The helper captures
    the entire paste as one field."""
    paste = (
        "The buyer is a developer or a CTO at a small team.\n"
        "They got a legal email about compliance.\n"
        "\n"
        "TAM is not the pitch. There are 4M apps.\n"
        "\n\n"
    )
    _patch_stdin(monkeypatch, paste)
    result = cli_mod._prompt_multiline("label")
    assert "The buyer is a developer" in result
    assert "TAM is not the pitch" in result
    # Both paragraphs landed in the same field, separated by the
    # blank line preserved from the paste.
    assert result.count("\n\n") == 1


def test_prompt_multiline_prints_label_and_hint(monkeypatch):
    """Label and hint are printed via console.print before reading."""
    _patch_stdin(monkeypatch, "x\n\n")
    captured = []
    monkeypatch.setattr(cli_mod.console, "print",
                        lambda *a, **k: captured.append(" ".join(str(x) for x in a)))
    cli_mod._prompt_multiline("[bold]My label[/]", hint="Hit Enter twice")
    joined = "\n".join(captured)
    assert "My label" in joined
    assert "Hit Enter twice" in joined


# ---------- _resolve_git_url ----------


def test_resolve_git_url_flag_takes_precedence(monkeypatch):
    """When `--git-url` is supplied, no prompt fires; the flag value
    is returned verbatim."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    result = cli_mod._resolve_git_url(
        flag_value="https://github.com/user/repo",
        non_interactive=False,
    )
    assert result == "https://github.com/user/repo"


def test_resolve_git_url_non_interactive_returns_empty(monkeypatch):
    """`--non-interactive` + no flag → empty string (blank scaffold)."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=True,
    )
    assert result == ""


def test_resolve_git_url_interactive_accepts_https(monkeypatch):
    """Operator pastes a valid https URL → returned."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: "https://github.com/user/agesdk-dev-ui")
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=False,
    )
    assert result == "https://github.com/user/agesdk-dev-ui"


def test_resolve_git_url_interactive_accepts_git_at(monkeypatch):
    """`git@host:path` SSH-style URLs are also accepted."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: "git@github.com:user/repo.git")
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=False,
    )
    assert result == "git@github.com:user/repo.git"


def test_resolve_git_url_interactive_empty_input_skips(monkeypatch):
    """Pressing Enter at the prompt → empty result → blank scaffold."""
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: "")
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=False,
    )
    assert result == ""


def test_resolve_git_url_invalid_then_valid(monkeypatch):
    """Invalid URL shape rejected; operator's second attempt is
    accepted. Validation re-prompts up to 3 times."""
    answers = iter(["not-a-url", "https://github.com/u/r"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=False,
    )
    assert result == "https://github.com/u/r"


def test_resolve_git_url_three_invalid_attempts_returns_empty(monkeypatch):
    """After 3 invalid attempts, the helper warns and returns empty
    rather than blocking the bootstrap flow."""
    answers = iter(["nope1", "nope2", "nope3"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    result = cli_mod._resolve_git_url(
        flag_value="", non_interactive=False,
    )
    assert result == ""


# ---------- _render_bootstrap_preflight ----------


def _capture_console(monkeypatch):
    captured: list[str] = []
    orig_print = cli_mod.console.print

    def fake_print(*args, **kwargs):
        captured.append(" ".join(str(a) for a in args))
    monkeypatch.setattr(cli_mod.console, "print", fake_print)
    return captured


def test_preflight_banner_lists_all_9_prompts(monkeypatch):
    """Interactive run with no flags → banner lists all 9 prompts."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_bootstrap_preflight(
        domain="agesdk.dev", non_interactive=False, git_url="",
        summary="", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
        registered=None, registrar="",
    )
    joined = "\n".join(captured)
    # All 9 prompt labels appear in the banner.
    for label in (
        "Lovable GitHub repo URL", "Summary", "Audience", "ICP",
        "Goals", "Content strategy", "Domain registered",
        "Registrar", "Growth hypothesis",
    ):
        assert label in joined, f"banner missing prompt: {label}"
    # And the skip-hint footer mentions both Enter-twice + Ctrl-D
    # plus `--non-interactive`.
    assert "non-interactive" in joined
    assert "Ctrl-D" in joined or "Enter twice" in joined


def test_preflight_banner_skipped_when_non_interactive(monkeypatch):
    """`--non-interactive` → no banner printed (no prompts fire)."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_bootstrap_preflight(
        domain="agesdk.dev", non_interactive=True, git_url="",
        summary="", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
        registered=None, registrar="",
    )
    assert captured == []


def test_preflight_banner_skipped_when_all_flags_supplied(monkeypatch):
    """When every per-section flag is supplied AND git_url is set
    AND registered+registrar are supplied → no prompts fire, so no
    banner."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_bootstrap_preflight(
        domain="agesdk.dev", non_interactive=False,
        git_url="https://github.com/u/r",
        summary="s", audience="a", icp="i", goal="g",
        content_strategy="c", growth_hypothesis="h",
        registered=True, registrar="porkbun",
    )
    assert captured == []


def test_preflight_banner_prints_when_partial_flags(monkeypatch):
    """Some flags supplied but not all → banner still prints (some
    prompts will fire)."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_bootstrap_preflight(
        domain="agesdk.dev", non_interactive=False, git_url="",
        summary="have a summary", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
        registered=None, registrar="",
    )
    joined = "\n".join(captured)
    assert "agesdk.dev" in joined
    assert "9 questions" in joined or "9" in joined


def test_preflight_banner_mentions_domain(monkeypatch):
    """Banner names the domain being bootstrapped so the operator
    knows what they're confirming."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_bootstrap_preflight(
        domain="example.com", non_interactive=False, git_url="",
        summary="", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
        registered=None, registrar="",
    )
    joined = "\n".join(captured)
    assert "example.com" in joined


# ---------- _render_llm_prompt_template (2026-05-28) ----------


def _render_llm_template(monkeypatch, **overrides):
    captured = _capture_console(monkeypatch)
    kwargs = dict(
        domain="agesdk.dev", topic="", non_interactive=False,
        summary="", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
    )
    kwargs.update(overrides)
    cli_mod._render_llm_prompt_template(**kwargs)
    return "\n".join(captured)


def test_llm_template_uses_numbered_labeled_format(monkeypatch):
    """The template must emit each section as `N. Label` matching the
    smart-paste parser's expected shape (bootstrap_paste header form),
    so the operator can paste the whole reply at the first prompt."""
    joined = _render_llm_template(monkeypatch)
    # Numbered + labeled headers matching the prompt order.
    for header in (
        "2. Summary", "3. Audience", "4. ICP", "5. Goals",
        "6. Content strategy", "9. Growth hypothesis",
    ):
        assert header in joined, f"template missing header: {header}"
    # Non-content prompts (Lovable repo / registered / registrar) are NOT
    # in the template — they aren't LLM-draftable.
    assert "Registrar" not in joined
    assert "Lovable" not in joined


def test_llm_template_includes_domain_and_topic(monkeypatch):
    joined = _render_llm_template(
        monkeypatch, topic="An EV-charger compliance tracker for CA homeowners",
    )
    assert "agesdk.dev" in joined
    assert "EV-charger compliance tracker" in joined


def test_llm_template_placeholder_when_no_topic(monkeypatch):
    """No --topic → the template tells the operator to add a topic line
    (the LLM needs context to draft useful sections)."""
    joined = _render_llm_template(monkeypatch, topic="")
    assert "agesdk.dev —" not in joined  # no topic interpolated into the lead
    assert "one line on what it is" in joined.lower()


def test_llm_template_skipped_when_non_interactive(monkeypatch):
    captured = _capture_console(monkeypatch)
    cli_mod._render_llm_prompt_template(
        domain="agesdk.dev", topic="x", non_interactive=True,
        summary="", audience="", icp="", goal="",
        content_strategy="", growth_hypothesis="",
    )
    assert captured == []


def test_llm_template_skipped_when_all_content_supplied(monkeypatch):
    """Every content section flag-supplied → nothing to draft → no-op."""
    captured = _capture_console(monkeypatch)
    cli_mod._render_llm_prompt_template(
        domain="agesdk.dev", topic="x", non_interactive=False,
        summary="s", audience="a", icp="i", goal="g",
        content_strategy="c", growth_hypothesis="h",
    )
    assert captured == []


def test_llm_template_prints_when_partial_content(monkeypatch):
    """Some but not all content supplied → template still prints (the
    remaining sections still need drafting)."""
    joined = _render_llm_template(monkeypatch, summary="already have this")
    assert "2. Summary" in joined


# ---------- registrar validation (interactive) ----------


def _patch_portfolio_json_empty(monkeypatch, tmp_path):
    """Helper: point data.PORTFOLIO_JSON at an empty file under
    tmp_path so `_resolve_inventory_inputs` falls through to the
    interactive path."""
    import json
    from portfolio import data as data_mod
    path = tmp_path / "portfolio.json"
    path.write_text(json.dumps({
        "generated_at": "2026-05-20T00:00:00+00:00",
        "schema_version": 1, "total": 0, "domains": [],
    }) + "\n")
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", path)


def test_registrar_prompt_accepts_canonical_value(monkeypatch, tmp_path):
    """Operator types 'porkbun' → accepted on first try."""
    _patch_portfolio_json_empty(monkeypatch, tmp_path)
    answers = iter(["y", "porkbun"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "porkbun"}


def test_registrar_prompt_case_insensitive(monkeypatch, tmp_path):
    """`Porkbun` / `PORKBUN` / ` namecheap ` all normalize."""
    _patch_portfolio_json_empty(monkeypatch, tmp_path)
    answers = iter(["y", "  NameCheap  "])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision["registrar"] == "namecheap"


def test_registrar_prompt_retries_on_invalid_then_accepts(monkeypatch, tmp_path):
    """Operator types a typo `porbun` → rejected with the accepted-
    values hint → second attempt `porkbun` accepted."""
    _patch_portfolio_json_empty(monkeypatch, tmp_path)
    answers = iter(["y", "porbun", "porkbun"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "porkbun"}


def test_registrar_prompt_three_invalid_falls_back_to_other(monkeypatch, tmp_path):
    """After 3 invalid registrar entries, fall back to "other" rather
    than re-prompting indefinitely or raising."""
    _patch_portfolio_json_empty(monkeypatch, tmp_path)
    answers = iter(["y", "nope1", "nope2", "nope3"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision == {"action": "append", "registered": True,
                        "registrar": "other"}


def test_registrar_prompt_accepts_other_explicitly(monkeypatch, tmp_path):
    """`other` is a canonical accepted value, not just the fallback."""
    _patch_portfolio_json_empty(monkeypatch, tmp_path)
    answers = iter(["y", "other"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))
    decision = cli_mod._resolve_inventory_inputs(
        domain="new.dev", registered=None, registrar="",
        non_interactive=False,
    )
    assert decision["registrar"] == "other"
