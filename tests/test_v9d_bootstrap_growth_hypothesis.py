"""Tests for v9.D — `new bootstrap` growth-hypothesis prompt that
seeds docs/growth.md's first dated entry.

Three layers:
  1. `_docs_growth_md(domain, today, growth_hypothesis)` — pure
     template function; empty hypothesis reproduces pre-v9.D
     behavior; non-empty produces a Hypothesis-bearing first entry.
  2. `_shorten_hypothesis_for_title(text, max_chars=70)` — derives
     the H2 title from a multi-sentence paragraph.
  3. `bootstrap(... growth_hypothesis=...)` end-to-end — scaffolds
     a project + verifies the rendered docs/growth.md.
  4. `_resolve_growth_hypothesis(...)` CLI helper — flag /
     non-interactive / interactive-prompt routing.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import typer

from portfolio import bootstrap_cli as cli_mod  # v35.F incr 8: these helpers moved out of cli.py
from portfolio.bootstrap import (
    _docs_growth_md,
    _shorten_hypothesis_for_title,
    bootstrap,
)


# ---------- _docs_growth_md ----------


def test_growth_md_empty_hypothesis_keeps_pre_v9d_first_entry():
    """No hypothesis → the file's first dated H2 is the old
    "site scaffolded; growth log started" entry. Pre-v9.D operators
    relying on the file shape aren't affected.

    Note: the format-docs block at the top still mentions
    `**Hypothesis:**` (template docs were updated to teach the new
    field for future entries). The assertion here scopes to the
    actual first entry, which should NOT carry a Hypothesis field
    when none was supplied."""
    out = _docs_growth_md("example.com", "2026-05-17",
                          growth_hypothesis="")
    assert "## 2026-05-17 — site scaffolded; growth log started" in out
    # The first entry's body (everything after the `---` divider that
    # closes the format-docs block) must not carry a Hypothesis field
    # when the operator didn't supply one.
    first_entry = out.split("---", 1)[1]
    assert "**Hypothesis:**" not in first_entry


def test_growth_md_with_hypothesis_adds_hypothesis_field():
    """Operator-supplied hypothesis → entry's H2 title summarizes
    the bet, and a new `**Hypothesis:**` field carries the full
    text. The pre-v9.D entry-template fields (Status, KPI, Baseline,
    Action, Result, Learning) stay in place so the workflow doesn't
    change."""
    out = _docs_growth_md(
        "example.com", "2026-05-17",
        growth_hypothesis=(
            "Programmatic-content site targeting EV owners; SEO traffic "
            "from long-tail installation-cost queries; aiming for first "
            "indexed pages within 30d."
        ),
    )
    assert "## 2026-05-17 —" in out
    assert "**Hypothesis:** Programmatic-content site targeting EV owners" in out
    assert "**Status:** active" in out
    assert "**KPI:**" in out
    assert "**Action:**" in out
    # The site-scaffolded-default entry doesn't appear when a real
    # hypothesis IS supplied.
    assert "site scaffolded; growth log started" not in out


def test_growth_md_format_docs_mention_hypothesis_field():
    """The "Format" docs block at the top of growth.md teaches the
    operator the entry shape. v9.D adds the `Hypothesis` field — the
    docs should list it so the next-entry workflow knows about it."""
    out = _docs_growth_md("example.com", "2026-05-17",
                          growth_hypothesis="")
    # The format block lists each field; Hypothesis must be in there.
    assert "- **Hypothesis:**" in out


def test_growth_md_review_date_is_today_plus_28d():
    """Both branches (with + without hypothesis) compute the review
    date the same way — today + 28d. Defensive check that the
    refactor didn't drop the calculation."""
    out_empty = _docs_growth_md("x.com", "2026-05-17", "")
    out_hyp = _docs_growth_md("x.com", "2026-05-17",
                              growth_hypothesis="test bet")
    assert "review 2026-06-14" in out_empty
    assert "review 2026-06-14" in out_hyp


# ---------- _shorten_hypothesis_for_title ----------


def test_shorten_returns_unchanged_when_under_limit():
    short = "Build it and they will come."
    assert _shorten_hypothesis_for_title(short) == short


def test_shorten_cuts_at_first_sentence_end():
    """A multi-sentence paragraph gets cut at the first sentence
    end under max_chars so the H2 title reads as a complete claim."""
    text = (
        "Programmatic content targets EV owners. We expect first "
        "indexed pages within 30d. The KPI is impressions."
    )
    title = _shorten_hypothesis_for_title(text, max_chars=70)
    assert title == "Programmatic content targets EV owners."


def test_shorten_falls_back_to_word_boundary_when_no_sentence_end():
    """A long single-clause paragraph (no sentence-ending punctuation
    in range) gets cut at the last word boundary inside max_chars +
    ellipsis appended."""
    text = (
        "Programmatic content targeting EV owners shipping content at "
        "scale across thousands of long-tail queries with no sentence "
        "breaks inside the window"
    )
    title = _shorten_hypothesis_for_title(text, max_chars=40)
    assert title.endswith("…")
    assert len(title) <= 41   # 40 chars + the ellipsis


def test_shorten_flattens_multiline_input():
    """A multi-line paragraph flattens to a single line before the
    title is derived."""
    text = (
        "Programmatic content\n"
        "targets EV owners.\n"
        "We expect first indexed pages within 30d."
    )
    title = _shorten_hypothesis_for_title(text, max_chars=70)
    assert "\n" not in title
    assert title == "Programmatic content targets EV owners."


# ---------- bootstrap end-to-end ----------


def test_bootstrap_writes_hypothesis_into_growth_md(tmp_path):
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="hypo.dev", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        growth_hypothesis=(
            "Long-tail SEO content for compliance edge cases the big "
            "publishers don't cover."
        ),
    )
    growth = (sites_root / "hypo.dev" / "docs" / "growth.md").read_text()
    assert "**Hypothesis:** Long-tail SEO content for compliance" in growth
    assert "## 2026-05-17 —" in growth
    # Default placeholder entry is gone.
    assert "site scaffolded; growth log started" not in growth


def test_bootstrap_default_growth_md_still_renders_without_hypothesis(tmp_path):
    """Backward compat: no `growth_hypothesis` kwarg → file reproduces
    the pre-v9.D output exactly (default first entry)."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    bootstrap(
        domain="legacy.dev", stack="astro",
        sites_root=sites_root, today_iso="2026-05-17",
        # No growth_hypothesis kwarg.
    )
    growth = (sites_root / "legacy.dev" / "docs" / "growth.md").read_text()
    assert "## 2026-05-17 — site scaffolded; growth log started" in growth
    assert "**Hypothesis:**" not in growth.split("---", 1)[-1]  # not in the first entry


# ---------- _resolve_growth_hypothesis ----------


def test_resolve_growth_hypothesis_flag_takes_precedence(monkeypatch):
    """When the flag is set, no prompt fires."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    result = cli_mod._resolve_growth_hypothesis(
        flag_value="my hypothesis", non_interactive=False,
    )
    assert result == "my hypothesis"


def test_resolve_growth_hypothesis_strips_whitespace(monkeypatch):
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    result = cli_mod._resolve_growth_hypothesis(
        flag_value="   padded   \n", non_interactive=False,
    )
    assert result == "padded"


def test_resolve_growth_hypothesis_non_interactive_no_flag_is_empty(monkeypatch):
    """--non-interactive + no flag → empty string. docs/growth.md
    will render the default first entry (no operator hypothesis)."""
    monkeypatch.setattr(typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("prompt should not fire")))
    result = cli_mod._resolve_growth_hypothesis(
        flag_value="", non_interactive=True,
    )
    assert result == ""


def test_resolve_growth_hypothesis_interactive_prompts(monkeypatch):
    """Bug-fix 2026-05-20: growth hypothesis is a paragraph-style
    prompt so it now uses `_prompt_multiline`, not `typer.prompt`.
    Patch the helper directly."""
    prompts_called = []

    def fake_multiline(label, *, hint=None):
        prompts_called.append(label)
        return "my interactive bet"
    monkeypatch.setattr(cli_mod, "_prompt_multiline", fake_multiline)
    result = cli_mod._resolve_growth_hypothesis(
        flag_value="", non_interactive=False,
    )
    assert result == "my interactive bet"
    assert len(prompts_called) == 1


def test_resolve_growth_hypothesis_empty_prompt_returns_empty(monkeypatch):
    """Pressing Enter twice on the interactive prompt → empty result.
    docs/growth.md falls back to default first entry."""
    monkeypatch.setattr(cli_mod, "_prompt_multiline", lambda *a, **k: "")
    result = cli_mod._resolve_growth_hypothesis(
        flag_value="", non_interactive=False,
    )
    assert result == ""
