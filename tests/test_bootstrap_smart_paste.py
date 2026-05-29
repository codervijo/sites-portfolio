"""Tests for the 2026-05-20 smart multi-section paste bootstrap UX.

Bug context: at the Summary prompt of `lamill new bootstrap`, the
operator may paste an LLM-staged 9-section response containing all
the bootstrap answers in numbered sections (`2. Summary`, `3. Audience`,
…, `9. Growth hypothesis`). Pre-fix: the entire blob landed in the
Summary field and prompts 3-9 fired empty. Post-fix:
`parse_multisection_paste()` recognizes the pattern, splits the paste
into canonical sections, and (on operator confirm) auto-fills all
remaining prompts in `_collect_operator_inputs` plus the cross-cutting
overrides (`git_url`, `growth_hypothesis`, `registered`, `registrar`).

Two layers tested:
  1. `portfolio.bootstrap_paste.parse_multisection_paste(text)` — pure
     parser unit tests (threshold edges, header variants, content
     spanning multiple paragraphs, weird whitespace, etc.).
  2. `portfolio.cli._collect_operator_inputs(...)` integration with
     `extras_out={}` — simulates pasting at the Summary prompt and
     confirming the auto-fill, checks that:
       - `inputs[]` is populated for all matched AI_AGENTS headings;
       - `extras_out[]` is populated for cross-section overrides;
       - declining (`n`) keeps only the Summary content.

`typer.prompt` and `sys.stdin` are monkeypatched so no real TTY is
needed.
"""
from __future__ import annotations

import io

import pytest
import typer

from portfolio import cli as cli_mod
from portfolio.bootstrap_paste import (
    is_section_header_line,
    parse_multisection_paste,
)


# The exact 9-section paste shape captured in the operator's 2026-05-20
# test session. Used by several integration tests below.
NINE_SECTION_PASTE = """\
2. Summary
AgeSDK is a React Native SDK that handles AB 1043 age signal compliance end-to-end. It wraps the Apple/Google age APIs, provides drop-in React Native components, and ships with an admin dashboard for compliance reporting.

3. Audience
React Native and Expo developers building consumer apps with California users who need AB 1043 compliance before January 2027.

4. ICP
A React Native developer or small-team CTO at a consumer app with 10K-500K MAU who just got a legal email about AB 1043 and has 90 days to ship a compliance fix without rebuilding their auth flow.

5. Goals
Own the AB 1043 compliance SDK category before any competitor ships, and rank for every developer-facing AB 1043 search term before enforcement demand spikes in late 2026. Convert organic traffic to npm installs and npm installs to paid dashboard accounts.

6. Content strategy
Landing page targeting AB 1043 compliance SDK. Docs site with per-framework integration guides. Blog with compliance deep-dives. Code samples on GitHub. Mix of long-form rationale and copy-paste reference snippets.

7. Domain registered?
Y

8. Registrar
porkbun

9. Growth hypothesis
AB 1043 creates a mandatory compliance event for every consumer app developer with California users. The SDK that ranks #1 for "AB 1043 React Native" before Q3 2026 owns the category by default. Distribution channel: developer SEO + Stack Overflow + npm trending.
"""


# ---------- parse_multisection_paste — parser unit tests ----------


def test_parser_nine_section_paste_returns_all_keys():
    """The canonical 9-section paste yields all 8 canonical keys
    (the operator's prompt template uses `1.` for the LLM template
    intro, so the actual sections start at `2. Summary`)."""
    result = parse_multisection_paste(NINE_SECTION_PASTE)
    assert result is not None
    assert set(result.keys()) == {
        "summary", "audience", "icp", "goals", "content_strategy",
        "domain_registered", "registrar", "growth_hypothesis",
    }
    # Summary content begins with "AgeSDK is a React Native SDK".
    assert result["summary"].startswith("AgeSDK is a React Native SDK")
    # Y normalizes downstream via normalize_yes_no; raw content is "Y".
    assert result["domain_registered"].strip() == "Y"
    assert result["registrar"].strip() == "porkbun"


def test_parser_partial_paste_three_sections():
    """Operator pastes a partial response with 3 sections → returns
    a dict with exactly those 3 keys."""
    text = (
        "1. Summary\n"
        "Short summary text.\n"
        "\n"
        "2. Audience\n"
        "Developers.\n"
        "\n"
        "3. Goals\n"
        "Win the category.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert set(result.keys()) == {"summary", "audience", "goals"}


def test_parser_single_paragraph_returns_none():
    """Plain single-paragraph paste (no numbered section headers) →
    None. Treated as single-section input; current behavior."""
    text = (
        "AgeSDK is a React Native SDK that handles AB 1043 "
        "age signal compliance end-to-end. It wraps the Apple/Google "
        "age APIs."
    )
    assert parse_multisection_paste(text) is None


def test_parser_two_section_threshold_returns_none():
    """Exactly 2 numbered sections → below the ≥3 threshold → None.
    The operator's input is treated as the original prompt's content."""
    text = (
        "1. Summary\n"
        "Foo.\n"
        "\n"
        "2. Audience\n"
        "Bar.\n"
    )
    assert parse_multisection_paste(text) is None


def test_parser_empty_input_returns_none():
    """Empty / whitespace-only input → None (current behavior preserved)."""
    assert parse_multisection_paste("") is None
    assert parse_multisection_paste("   \n\n  \n") is None


def test_parser_mixed_case_headers_parsed():
    """Headers with weird casing (`SUMMARY`, `audience`, `IcP`)
    normalize to the canonical key set."""
    text = (
        "1. SUMMARY\n"
        "S text.\n"
        "\n"
        "2. audience\n"
        "A text.\n"
        "\n"
        "3. IcP\n"
        "I text.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert result.keys() == {"summary", "audience", "icp"}


def test_parser_section_content_spans_multiple_paragraphs():
    """A section whose content spans multiple paragraphs (internal
    blank lines) captures the whole body until the next numbered
    header. Internal newlines are preserved."""
    text = (
        "1. Summary\n"
        "Paragraph one of the summary.\n"
        "\n"
        "Paragraph two of the summary, still part of Summary.\n"
        "\n"
        "2. Audience\n"
        "A short audience line.\n"
        "\n"
        "3. Goals\n"
        "G.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert "Paragraph one" in result["summary"]
    assert "Paragraph two" in result["summary"]
    # Internal newline preserved between the two paragraphs.
    assert "\n\nParagraph two" in result["summary"]
    # Audience should NOT contain Goals content.
    assert "G." not in result["audience"]


def test_parser_trailing_whitespace_and_extra_blank_lines():
    """Trailing/leading whitespace + extra blank lines around content
    don't break the parse and don't end up in the result."""
    text = (
        "\n\n"
        "1. Summary  \n"
        "  S content.  \n"
        "\n\n\n"
        "2. Audience\n"
        "A content.\n"
        "\n"
        "3. Goals\n"
        "G content.\n"
        "\n\n\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    # Content is stripped — no leading/trailing whitespace.
    assert result["summary"] == "S content."
    assert result["audience"] == "A content."
    assert result["goals"] == "G content."


def test_parser_punctuation_in_header_is_tolerated():
    """`Domain registered?` (with the question mark) and `Domain registered`
    (without) both normalize to the same canonical key."""
    with_q = (
        "1. Summary\nS.\n\n"
        "2. Audience\nA.\n\n"
        "3. Domain registered?\nY\n"
    )
    without_q = (
        "1. Summary\nS.\n\n"
        "2. Audience\nA.\n\n"
        "3. Domain registered\nY\n"
    )
    r1 = parse_multisection_paste(with_q)
    r2 = parse_multisection_paste(without_q)
    assert r1 is not None and r2 is not None
    assert r1.get("domain_registered") == "Y"
    assert r2.get("domain_registered") == "Y"


def test_parser_lovable_repo_alias_routes_to_lovable_repo_key():
    """`Lovable GitHub repo URL`, `GitHub repo`, `Lovable repo` all
    normalize to the `lovable_repo` canonical key."""
    text = (
        "1. Summary\nS.\n\n"
        "2. Audience\nA.\n\n"
        "3. Lovable GitHub repo URL\nhttps://github.com/u/r\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert result.get("lovable_repo") == "https://github.com/u/r"


def test_parser_unknown_section_headers_skipped():
    """Headers that don't match any canonical alias (e.g. `Topic`)
    are skipped — they don't show up in the result, and they don't
    pollute neighboring sections."""
    text = (
        "1. Topic\n"
        "AB 1043 compliance SDK.\n"
        "\n"
        "2. Summary\n"
        "S content.\n"
        "\n"
        "3. Audience\n"
        "A content.\n"
        "\n"
        "4. Goals\n"
        "G content.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert "topic" not in result
    assert result["summary"] == "S content."


# ---------- positional fallback — 2026-05-25 bug fix ----------


# Operator's earnlog.xyz paste — the LLM answered each of the 9
# numbered prompts by reprinting just the digit before the answer
# (no header label). Pre-fix this fell through the parser and the
# entire blob landed in the Summary field; post-fix the digits are
# interpreted positionally against `_POSITIONAL_ORDER`.
POSITIONAL_PASTE = """\
2. Earnlog is a mobile-first earnings intelligence platform for California rideshare and delivery drivers navigating the new collective bargaining rights created by AB 1340. It aggregates earnings across Uber, Lyft, and DoorDash into a single dashboard, calculates real effective hourly wages after expenses and dead time, tracks platform rate changes, and provides plain-language guidance on AB 1340 rights and PERB filing.

3. Full-time and part-time rideshare and delivery drivers in California who want to understand their real earnings and exercise their new collective bargaining rights under AB 1340.

4. A full-time Uber or Lyft driver in California doing 35+ hours per week across two or more platforms. Suspects they are earning less than they think after expenses. Active in driver Facebook groups or Telegram channels.

5. Become the default earnings tracking app for California gig workers under the AB 1340 framework, and build the only anonymized earnings dataset granular enough to give union reps real leverage at the bargaining table.

6. Landing page targeting rideshare earnings tracker California and AB 1340 driver rights app. Blog: real effective wage breakdowns by city and platform, AB 1340 plain-language explainers, PERB filing guides.

7. Y

8. porkbun

9. Eight hundred thousand California rideshare drivers have a brand new legal right and no app built around it. The distribution channel already exists — driver Facebook groups, Telegram channels, and subreddits are highly active communities where a tool that shows real hourly wages spreads on its own because the number is always lower than drivers expect.
"""


def test_parser_positional_paste_maps_digits_to_prompt_order():
    """Operator's LLM uses `2. <answer> / 3. <answer> / ...` instead of
    `2. Summary\\n<content>`. Each digit maps to the canonical key at
    that position in the 9-prompt order."""
    result = parse_multisection_paste(POSITIONAL_PASTE)
    assert result is not None
    assert set(result.keys()) == {
        "summary", "audience", "icp", "goals", "content_strategy",
        "domain_registered", "registrar", "growth_hypothesis",
    }
    assert result["summary"].startswith("Earnlog is a mobile-first")
    assert result["audience"].startswith(
        "Full-time and part-time rideshare"
    )
    assert result["icp"].startswith("A full-time Uber or Lyft driver")
    assert result["goals"].startswith(
        "Become the default earnings tracking app"
    )
    assert result["content_strategy"].startswith("Landing page targeting")
    assert result["domain_registered"] == "Y"
    assert result["registrar"] == "porkbun"
    assert result["growth_hypothesis"].startswith(
        "Eight hundred thousand California rideshare drivers"
    )


def test_parser_positional_paste_with_lovable_repo_section_one():
    """Positional paste that also covers section 1 (Lovable repo URL)
    routes #1 to `lovable_repo`."""
    text = (
        "1. https://github.com/operator/earnlog\n"
        "\n"
        "2. Earnlog is a mobile-first earnings intelligence platform.\n"
        "\n"
        "3. California rideshare drivers.\n"
        "\n"
        "4. A full-time Uber or Lyft driver in California.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert result["lovable_repo"] == "https://github.com/operator/earnlog"
    assert result["summary"].startswith("Earnlog is a mobile-first")
    assert result["audience"] == "California rideshare drivers."
    assert result["icp"].startswith("A full-time Uber or Lyft driver")


def test_parser_positional_threshold_three_returns_none():
    """3 sequentially-numbered blocks alone don't trip the positional
    fallback — guards against false positives on recipe-style prose
    like "1. flour 2. eggs 3. bake at 350"."""
    text = (
        "1. mix the flour with two cups of water until smooth.\n"
        "\n"
        "2. add three eggs and whisk for 30 seconds.\n"
        "\n"
        "3. bake at 350 degrees for 25 minutes.\n"
    )
    # Header-based parse: none of these match canonical aliases.
    # Positional fallback: only 3 sections, below the ≥4 threshold.
    assert parse_multisection_paste(text) is None


def test_parser_positional_out_of_range_digit_falls_through():
    """Digits outside 1-9 (e.g. 10, 11, 12) don't fit the prompt-order
    mapping → positional fallback rejects and the parse returns None."""
    text = (
        "10. first item\n"
        "\n"
        "11. second item\n"
        "\n"
        "12. third item\n"
        "\n"
        "13. fourth item\n"
    )
    assert parse_multisection_paste(text) is None


def test_parser_positional_duplicate_digits_falls_through():
    """Duplicate digits (e.g. two `2.` lines) are not a positional
    prompt-order paste — the fallback rejects."""
    text = (
        "2. first thing\n"
        "\n"
        "2. duplicate digit\n"
        "\n"
        "3. third thing\n"
        "\n"
        "4. fourth thing\n"
    )
    assert parse_multisection_paste(text) is None


def test_parser_positional_paste_does_not_interfere_with_labeled_paste():
    """Header-based paste (labels present) still goes through the
    header path — the positional fallback only fires when header-based
    yields <3 canonical sections."""
    text = (
        "2. Summary\n"
        "Real summary content.\n"
        "\n"
        "3. Audience\n"
        "Real audience content.\n"
        "\n"
        "4. Goals\n"
        "Real goals content.\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    # Header-based parse produced these — the section content does
    # NOT include the header label "Summary" / "Audience" / "Goals".
    assert result["summary"] == "Real summary content."
    assert result["audience"] == "Real audience content."
    assert result["goals"] == "Real goals content."


def test_parser_single_line_answers_still_parse():
    """A paste with only single-line content per section (no
    paragraphs) still parses if ≥3 section headers are present."""
    text = (
        "1. Audience\n"
        "Developers.\n"
        "2. Goals\n"
        "Win.\n"
        "3. Registrar\n"
        "porkbun\n"
    )
    result = parse_multisection_paste(text)
    assert result is not None
    assert result["audience"] == "Developers."
    assert result["goals"] == "Win."
    assert result["registrar"] == "porkbun"


# ---------- _collect_operator_inputs integration ----------


def _patch_stdin(monkeypatch, text: str) -> None:
    """Replace `sys.stdin` so `_prompt_multiline()` reads `text`."""
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(text))


def test_collect_smart_paste_confirm_auto_fills_all_sections(monkeypatch):
    """At the Summary prompt the operator pastes the 9-section
    response (terminated by Enter-Enter). The confirmation prompt
    fires; operator hits Y. All 5 AI_AGENTS sections populate from
    the paste; extras_out captures git_url-less / growth /
    registered=True / registrar=porkbun."""
    # Two blank lines terminate `_prompt_multiline`.
    _patch_stdin(monkeypatch, NINE_SECTION_PASTE + "\n\n")

    # Only ONE typer.prompt call expected (the confirm Y/n) — none of
    # the per-section prompts should fire because smart-paste filled
    # them all. Make the test fail loud if more prompts arrive.
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )

    # All 5 operator AI_AGENTS sections populated.
    assert inputs["Summary"].startswith("AgeSDK is a React Native SDK")
    assert inputs["Audience"].startswith("React Native and Expo developers")
    assert inputs["ICP"].startswith("A React Native developer")
    assert inputs["Goals"].startswith("Own the AB 1043 compliance SDK category")
    assert inputs["Content strategy"].startswith("Landing page targeting AB 1043")

    # Cross-section extras captured.
    assert extras["registered"] is True
    assert extras["registrar"] == "porkbun"
    assert extras["growth_hypothesis"].startswith(
        "AB 1043 creates a mandatory compliance event"
    )
    # No Lovable repo URL in this paste → key not in extras.
    assert "git_url" not in extras


def test_collect_smart_paste_decline_keeps_only_summary(monkeypatch):
    """Operator declines the auto-fill prompt with `n`. The pasted
    text stays as the Summary content; remaining prompts fire as
    normal. (Audience / ICP / Goals / Content strategy each get an
    empty answer from `typer.prompt` and become empty strings.)"""
    _patch_stdin(monkeypatch, NINE_SECTION_PASTE + "\n\n")

    # Sequence: confirm-prompt "n", then 4 single-line prompts for
    # remaining sections (Audience / ICP / Goals / Content strategy).
    # ICP and Content strategy are paragraph-style, so they're fed
    # through `_prompt_multiline` (not typer.prompt) — but stdin is
    # already drained by the Summary prompt, so the next readline()
    # call returns EOF immediately and `_prompt_multiline` returns "".
    answers = iter(["n", "", "", "", "", "", "", ""])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )

    # Summary captures the entire paste — current behavior.
    assert inputs["Summary"].startswith("2. Summary")
    # Other sections empty (operator can fill via the regular prompts).
    assert inputs["Audience"] == ""
    assert inputs["Goals"] == ""
    # No extras filled.
    assert extras == {}


def test_collect_smart_paste_partial_paste_fills_only_matched(monkeypatch):
    """Paste contains only 3 sections (Summary / Audience / Goals).
    Smart-paste fills those 3; the remaining 2 AI_AGENTS sections
    (ICP / Content strategy) still get prompted."""
    partial = (
        "1. Summary\nS content.\n"
        "\n"
        "2. Audience\nA content.\n"
        "\n"
        "3. Goals\nG content.\n"
    )
    # Two newlines terminate _prompt_multiline; we then need the ICP
    # and Content strategy multiline prompts to drain immediately.
    _patch_stdin(monkeypatch, partial + "\n\n")

    # Sequence: Y to confirm auto-fill, then no further typer.prompts
    # fire for the multiline ICP/Content-strategy sections (they use
    # _prompt_multiline which reads from stdin → EOF → empty).
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"] == "S content."
    assert inputs["Audience"] == "A content."
    assert inputs["Goals"] == "G content."
    # ICP and Content strategy weren't in the paste; they get empty
    # answers via the EOF-drained _prompt_multiline.
    assert inputs["ICP"] == ""
    assert inputs["Content strategy"] == ""


def test_collect_smart_paste_lovable_repo_routes_to_git_url(monkeypatch):
    """A paste section labeled "Lovable GitHub repo URL" with a
    valid URL value lands in `extras_out['git_url']`."""
    paste = (
        "1. Lovable GitHub repo URL\nhttps://github.com/u/r\n"
        "\n"
        "2. Summary\nS.\n"
        "\n"
        "3. Audience\nA.\n"
        "\n"
        "4. Goals\nG.\n"
    )
    _patch_stdin(monkeypatch, paste + "\n\n")
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert extras["git_url"] == "https://github.com/u/r"
    assert inputs["Summary"] == "S."


def test_collect_smart_paste_with_flag_supplied_for_summary(monkeypatch):
    """If `--summary "X"` is supplied, the Summary prompt is skipped
    AND smart-paste fires on whatever the FIRST remaining multiline
    prompt is (ICP). Verifies smart-paste isn't hardwired to Summary."""
    paste = (
        "1. ICP\nI content.\n"
        "\n"
        "2. Goals\nG content.\n"
        "\n"
        "3. Content strategy\nC content.\n"
    )
    _patch_stdin(monkeypatch, paste + "\n\n")
    # Y confirms; one Audience-typer.prompt may fire (single-line).
    answers = iter(["Y", ""])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="Pre-supplied summary.",
        audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"] == "Pre-supplied summary."
    assert inputs["ICP"] == "I content."
    assert inputs["Goals"] == "G content."
    assert inputs["Content strategy"] == "C content."


def test_collect_non_smart_paste_input_falls_through_to_normal_flow(monkeypatch):
    """Operator pastes a single-paragraph Summary (not a multi-section
    response). Smart-paste does not fire; the paste becomes the
    Summary content; remaining prompts fire normally."""
    # Single-paragraph Summary, then Audience single-line, then EOF
    # for ICP/Goals/Content strategy.
    summary_text = "AgeSDK is a React Native SDK for AB 1043 compliance.\n\n"
    _patch_stdin(monkeypatch, summary_text)
    answers = iter(["broad-audience"])  # Audience prompt only.
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"].startswith("AgeSDK is a React Native SDK")
    assert inputs["Audience"] == "broad-audience"
    assert extras == {}


def test_collect_smart_paste_audience_collapses_to_single_line(monkeypatch):
    """A paste with multi-line Audience content collapses to the
    first non-blank line (Audience is a single-line AI_AGENTS slot,
    not a paragraph)."""
    paste = (
        "1. Summary\nS.\n\n"
        "2. Audience\n"
        "First line of audience.\n"
        "Second line.\n"
        "Third line.\n"
        "\n"
        "3. Goals\nG.\n"
    )
    _patch_stdin(monkeypatch, paste + "\n\n")
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Audience"] == "First line of audience."


def test_collect_smart_paste_registered_normalization_yes(monkeypatch):
    """`Y` / `Yes` / `true` in the Domain registered? section all
    normalize to True in extras."""
    for raw in ("Y", "yes", "true", "1"):
        paste = (
            "1. Summary\nS.\n\n"
            "2. Audience\nA.\n\n"
            f"3. Domain registered?\n{raw}\n"
        )
        _patch_stdin(monkeypatch, paste + "\n\n")
        answers = iter(["Y"])
        monkeypatch.setattr(typer, "prompt",
                            lambda *a, _it=answers, **k: next(_it, ""))
        extras: dict = {}
        cli_mod._collect_operator_inputs(
            summary="", audience="", icp="", goal="", content_strategy="",
            non_interactive=False, extras_out=extras,
        )
        assert extras.get("registered") is True, f"raw={raw!r}"


def test_collect_smart_paste_registrar_falls_back_to_other(monkeypatch):
    """An unknown registrar value (e.g. `Squarespace`) normalizes to
    `other` rather than rejecting the paste."""
    paste = (
        "1. Summary\nS.\n\n"
        "2. Audience\nA.\n\n"
        "3. Registrar\nSquarespace\n"
    )
    _patch_stdin(monkeypatch, paste + "\n\n")
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert extras.get("registrar") == "other"


def test_collect_smart_paste_default_enter_accepts_confirm(monkeypatch):
    """Operator hits Enter at the confirm prompt → defaults to Y
    (auto-fill applied). Operator workflow: paste, Enter-Enter to
    terminate, Enter to confirm."""
    # 3-section paste so the threshold is met.
    paste = (
        "1. Summary\nS.\n\n"
        "2. Audience\nA.\n\n"
        "3. Goals\nG.\n"
    )
    _patch_stdin(monkeypatch, paste + "\n\n")
    # typer.prompt with default="Y" returns "Y" when the user hits
    # Enter at an empty prompt. We simulate that by returning "Y"
    # (typer's default-applied behavior). Empty input would also pass
    # since `_confirm_multisection_paste` treats empty as Yes.
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"] == "S."
    assert inputs["Audience"] == "A."
    assert inputs["Goals"] == "G."


# ---------- double-blank-separator blob — 2026-05-28 bug fix ----------


# Sections separated by TWO blank lines (`\n\n\n` between blocks). Some
# models format replies this way. Pre-fix `_prompt_multiline` stopped at
# the first double blank, capturing only the Summary block and leaking
# the rest into later prompts one slot off; the detect_blob path now
# reads the whole reply to EOF.
DOUBLE_BLANK_PASTE = (
    "2. Summary\nThe daily ring summary paragraph.\n\n\n"
    "3. Audience\nThe broad audience sentence.\n\n\n"
    "4. ICP\nThe specific ICP paragraph.\n\n\n"
    "5. Goals\nThe goals sentence.\n\n\n"
    "6. Content strategy\nThe content strategy paragraph.\n\n\n"
    "9. Growth hypothesis\nThe growth hypothesis paragraph.\n"
)


def test_prompt_multiline_blob_mode_reads_through_double_blanks(monkeypatch):
    """With detect_blob, a leading numbered header switches the reader
    to blob mode: double blanks between sections no longer terminate, so
    the whole reply is captured (terminated by EOF)."""
    import sys
    monkeypatch.setattr(sys, "stdin", io.StringIO(DOUBLE_BLANK_PASTE))
    captured = cli_mod._prompt_multiline("", detect_blob=True)
    # Every section header survived the single capture.
    for header in ("2. Summary", "3. Audience", "4. ICP", "5. Goals",
                   "6. Content strategy", "9. Growth hypothesis"):
        assert header in captured, f"missing {header!r}"


def test_prompt_multiline_plain_paragraph_still_ends_on_double_blank(monkeypatch):
    """Regression guard: prose input (no leading numbered header) keeps
    the classic two-blank-line terminator even when detect_blob is set —
    so anything typed after the double blank is NOT captured."""
    import sys
    monkeypatch.setattr(
        sys, "stdin",
        io.StringIO("A plain summary paragraph.\n\n\nLeaked next answer.\n"),
    )
    captured = cli_mod._prompt_multiline("", detect_blob=True)
    assert captured == "A plain summary paragraph."
    assert "Leaked" not in captured


def test_collect_smart_paste_double_blank_separators_routes_all(monkeypatch):
    """2026-05-28 fix (dailyring.xyz repro): a pasted reply whose
    sections are separated by TWO blank lines routes every section to
    its correct slot. Pre-fix, Summary got `2. Summary\\n<text>` and the
    rest leaked one slot off."""
    # No trailing Enter-twice — blob mode reads to EOF (StringIO end).
    _patch_stdin(monkeypatch, DOUBLE_BLANK_PASTE)
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"] == "The daily ring summary paragraph."
    assert inputs["Audience"] == "The broad audience sentence."
    assert inputs["ICP"] == "The specific ICP paragraph."
    assert inputs["Goals"] == "The goals sentence."
    assert inputs["Content strategy"] == "The content strategy paragraph."
    assert extras["growth_hypothesis"] == "The growth hypothesis paragraph."


def test_parser_positional_rejects_numbered_list_inside_prose():
    """2026-05-28 fix: a single section whose body is a numbered list
    (preceded by a prose preamble) must NOT trip the positional
    fallback — the paste doesn't START with a numbered block, so it
    stays single-section (parser returns None)."""
    text = (
        "The site needs:\n"
        "1. A landing page with the core pitch\n"
        "2. A pattern-library reference of error fixes\n"
        "3. Blog posts on common agent failures\n"
        "4. A waitlist signup form\n"
    )
    assert parse_multisection_paste(text) is None


# ---------- bare-label + code-fence headers — 2026-05-29 bug fix ----------


# claude.ai renders `2. Summary` as markdown; copy-paste strips the `N.`,
# leaving a bare label on its own line. The parser must still route it.
BARE_LABEL_PASTE = (
    "Summary\nVijo runs an archive site.\n"
    "Audience\nTechnical peers and recruiters.\n"
    "ICP\nA senior eng manager who reads a post then clicks the CV.\n"
    "Goals\nA durable indexable home that compounds in SEO.\n"
    "Content strategy\nTwo low-cadence tracks: founder notes + systems writing.\n"
    "Growth hypothesis\nGrowth by accretion — each post a durable SEO asset.\n"
)


def test_parser_bare_label_headers_route_correctly():
    """Bare canonical labels (no `N.`) parse — the operator's
    vijocherian.com mis-route (whole blob fell into Summary)."""
    result = parse_multisection_paste(BARE_LABEL_PASTE)
    assert result is not None
    assert result["summary"] == "Vijo runs an archive site."
    assert result["audience"] == "Technical peers and recruiters."
    assert result["icp"].startswith("A senior eng manager")
    assert result["goals"].startswith("A durable indexable home")
    assert result["content_strategy"].startswith("Two low-cadence tracks")
    assert result["growth_hypothesis"].startswith("Growth by accretion")


def test_parser_strips_wrapping_code_fence():
    """A numbered reply wrapped in a ``` code block (select-all keeps the
    fences) still parses — the fences are stripped."""
    fenced = "```\n2. Summary\nS.\n\n3. Audience\nA.\n\n4. Goals\nG.\n```"
    result = parse_multisection_paste(fenced)
    assert result is not None
    assert result["summary"] == "S."
    assert result["audience"] == "A."
    assert result["goals"] == "G."


def test_parser_bare_label_does_not_promote_prose_lines():
    """A single-paragraph summary that merely mentions a label word in
    prose isn't a multi-section paste (no standalone label lines)."""
    text = "This site is a summary of audience goals and content strategy."
    assert parse_multisection_paste(text) is None


def test_is_section_header_line_detection():
    assert is_section_header_line("2. Summary")
    assert is_section_header_line("Summary")
    assert is_section_header_line("Content strategy:")
    assert is_section_header_line("growth hypothesis")
    assert not is_section_header_line("Vijo runs an archive site.")
    assert not is_section_header_line("")


def test_collect_bare_label_blob_routes_all(monkeypatch):
    """Integration: the vijocherian.com repro — a bare-label reply pasted
    at the full-paste prompt routes every section to its slot instead of
    dumping the whole blob into Summary."""
    _patch_stdin(monkeypatch, BARE_LABEL_PASTE)
    answers = iter(["Y"])
    monkeypatch.setattr(typer, "prompt", lambda *a, **k: next(answers, ""))

    extras: dict = {}
    inputs = cli_mod._collect_operator_inputs(
        summary="", audience="", icp="", goal="", content_strategy="",
        non_interactive=False, extras_out=extras,
    )
    assert inputs["Summary"] == "Vijo runs an archive site."
    assert inputs["Audience"] == "Technical peers and recruiters."
    assert inputs["ICP"].startswith("A senior eng manager")
    assert inputs["Goals"].startswith("A durable indexable home")
    assert inputs["Content strategy"].startswith("Two low-cadence tracks")
    assert extras["growth_hypothesis"].startswith("Growth by accretion")
