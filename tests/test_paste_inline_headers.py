"""Tests for 2026-05-24 inline-section-header parser fixes in
bootstrap_paste.py.

Operator's dunam.co bootstrap paste exposed two parser limitations:

1. **Inline section start.** Operator pasted:
       7. Domain registered?
       Y8. Registrar GoDaddy
   No newline between the `Y` answer for prompt 7 and the `8.` opening
   prompt 8. The line-start regex (`^\\d+\\.`) didn't detect section 8;
   it ended up merged into section 7's content as "Y8. Registrar GoDaddy".

2. **Trailing-answer on header line.** The line `8. Registrar GoDaddy`
   has the canonical-header word "Registrar" + the answer "GoDaddy"
   on the same line. The strict `_match_header` only did exact
   matches, so "registrar godaddy" normalized form didn't match
   alias "registrar" → section 8 was dropped.

Both fixes together restore the operator's intent: section 7 = "Y",
section 8 = "GoDaddy", everything else as paste-intended.
"""
from __future__ import annotations

import pytest

from portfolio.bootstrap_paste import (
    _match_header,
    _matched_alias_for,
    _normalize_header,
    _split_inline_section_starts,
    parse_multisection_paste,
)


# ---- _match_header — longest-alias-prefix matching ------------------


def test_match_header_exact_match_still_works():
    assert _match_header("summary") == "summary"
    assert _match_header("registrar") == "registrar"
    assert _match_header("growth hypothesis") == "growth_hypothesis"


def test_match_header_longest_prefix_match():
    """Operator wrote answer on header line — header text has trailing
    words past the canonical alias."""
    assert _match_header("registrar godaddy") == "registrar"
    assert _match_header("registrar porkbun") == "registrar"
    assert _match_header("summary foo bar") == "summary"


def test_match_header_unknown_still_returns_none():
    assert _match_header("frobnicator") is None
    assert _match_header("") is None


def test_matched_alias_for_returns_actual_alias_key():
    """For trailing-content extraction the caller needs to know how
    many words of the header were the alias (rest is content)."""
    assert _matched_alias_for("registrar") == "registrar"
    assert _matched_alias_for("registrar godaddy") == "registrar"
    # Longest-first: "ideal customer profile" should win over "icp"
    # if both could match.
    assert _matched_alias_for("ideal customer profile") == "ideal customer profile"


# ---- _split_inline_section_starts — preprocessor --------------------


def test_split_inline_inserts_newline_before_recognized_section():
    """The classic dunam.co case: `Y8. Registrar` becomes `Y\\n8. Registrar`."""
    input_text = "7. Domain registered?\nY8. Registrar GoDaddy\n9. Growth hypothesis\nFoo"
    out = _split_inline_section_starts(input_text)
    # Should now have a newline before "8."
    assert "Y\n8. Registrar GoDaddy" in out


def test_split_inline_leaves_line_start_sections_alone():
    """Sections already at line-start aren't double-split."""
    input_text = "2. Summary\nfoo\n3. Audience\nbar"
    out = _split_inline_section_starts(input_text)
    # Identical (no insertions)
    assert out == input_text


def test_split_inline_skips_when_header_isnt_known_alias():
    """Content with digits like '1. apples, 2. oranges' must NOT be split."""
    input_text = "Goals\nShip features: 1. apples, 2. oranges, 3. pears"
    out = _split_inline_section_starts(input_text)
    # No insertions — these aren't real section headers
    assert out == input_text


def test_split_inline_handles_multiple_inline_starts():
    """Edge case: multiple inline starts in one paste."""
    input_text = "abc6. Content strategy\nfoo bar7. Domain registered?\nY"
    out = _split_inline_section_starts(input_text)
    assert "abc\n6. Content strategy" in out
    assert "bar\n7. Domain registered?" in out


# ---- parse_multisection_paste — end-to-end --------------------------


def test_parse_handles_inline_section_start():
    """End-to-end: Y8 case splits correctly and section 7 gets clean
    'Y' answer; section 8 gets 'GoDaddy' from trailing-on-header-line
    extraction."""
    paste = """\
2. Summary
Dunam is a fire safety SaaS.

3. Audience
Fire inspection companies.

4. ICP
Owner-operator of 2-10 person fire shops.

5. Goals
Sign 10 customers in 90 days.

6. Content strategy
SEO + comparison pages.

7. Domain registered?
Y8. Registrar GoDaddy
9. Growth hypothesis
Direct outreach + SEO.
"""
    out = parse_multisection_paste(paste)
    assert out is not None
    assert out["summary"].startswith("Dunam is a fire safety SaaS")
    assert out["audience"] == "Fire inspection companies."
    assert out["icp"].startswith("Owner-operator")
    assert out["goals"] == "Sign 10 customers in 90 days."
    assert out["content_strategy"].startswith("SEO")
    assert out["domain_registered"] == "Y"
    assert out["registrar"] == "GoDaddy"
    assert out["growth_hypothesis"] == "Direct outreach + SEO."


def test_parse_handles_trailing_answer_on_header_line_alone():
    """Standalone (no inline-merge) version of the trailing-answer
    case: '8. Registrar GoDaddy' is the whole line."""
    paste = """\
2. Summary
Stuff goes here.

3. Audience
Folks.

8. Registrar Porkbun
"""
    out = parse_multisection_paste(paste)
    assert out is not None
    assert out["registrar"] == "Porkbun"


def test_parse_preserves_existing_behavior_when_no_inline_issues():
    """Clean paste (one section per group of lines) still works."""
    paste = """\
2. Summary
Foo.

3. Audience
Bar.

5. Goals
Baz.
"""
    out = parse_multisection_paste(paste)
    assert out == {
        "summary": "Foo.",
        "audience": "Bar.",
        "goals": "Baz.",
    }


def test_parse_doesnt_misinterpret_content_with_digits():
    """Section content containing 'N. word' patterns that AREN'T
    canonical aliases must not be split. Note: needs 3+ canonical
    sections to even pass the threshold."""
    paste = """\
2. Summary
Steps to take: 1. signup, 2. activation, 3. retention.

3. Audience
General consumers.

5. Goals
Win them all.
"""
    out = parse_multisection_paste(paste)
    assert out is not None
    # Critical: the "1. signup, 2. activation, 3. retention" was NOT split.
    assert "1. signup" in out["summary"]
    assert "2. activation" in out["summary"]
    assert out["audience"] == "General consumers."
