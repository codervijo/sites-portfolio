"""v28.C — topic→theme selection (folded into the vocab call) + column merge.

Covers the theme parser, the heuristic fallback, the in-place column merge,
and the key invariant of folding themes into the vocab call: the `THEMES:`
trailer must NOT leak into the practitioner vocab terms.
"""
from __future__ import annotations

from portfolio.suggest import (
    DEFAULT_TLDS,
    _extract_themes,
    _extract_vocab_terms,
    _themes_from_keywords,
    merge_topical_columns,
)


# ---- _extract_themes (LLM trailer parse, allow-set filtered) ---------


def test_extract_themes_basic():
    assert _extract_themes("leash\npaw\nTHEMES: family, photos") == ["family", "photos"]


def test_extract_themes_case_and_separators():
    assert _extract_themes("Themes: Family / Voice and music") == ["family", "voice", "music"]


def test_extract_themes_filters_unknown():
    # "puppies" isn't a THEME_MAP key → dropped; "family" kept
    assert _extract_themes("THEMES: family, puppies, solutions") == ["family"]


def test_extract_themes_absent_line():
    assert _extract_themes("just\nvocab\nterms") == []


def test_extract_themes_dedup():
    assert _extract_themes("THEMES: family, family, photos") == ["family", "photos"]


# ---- the fold-in invariant: THEMES line must not pollute vocab -------


def test_themes_trailer_does_not_leak_into_vocab_terms():
    text = "leash\npaw\nfetch\nTHEMES: family, photos"
    terms = _extract_vocab_terms(text)
    themes = _extract_themes(text)
    assert "themes" not in terms and "family" not in terms and "photos" not in terms
    assert terms == ["leash", "paw", "fetch"]
    assert themes == ["family", "photos"]


# ---- heuristic fallback ----------------------------------------------


def test_keywords_family_and_memories():
    out = _themes_from_keywords("a private family archive for grandparents")
    assert "family" in out and "memories" in out  # "family" + "archive"


def test_keywords_voice():
    assert _themes_from_keywords("captures their voice replies") == ["voice"]


def test_keywords_order_by_appearance():
    # "video" appears before "photos" in the text
    out = _themes_from_keywords("weekly video then photos")
    assert out == ["video", "photos"]


def test_keywords_no_match():
    assert _themes_from_keywords("a devops ci/cd dashboard") == []


# ---- merge_topical_columns (in-place, idempotent, bounded) -----------


def test_merge_appends_topical_in_place():
    cols = list(DEFAULT_TLDS)
    added = merge_topical_columns(cols, ["family"])
    assert added == [".family", ".gift", ".photos", ".life"]
    assert cols[-4:] == [".family", ".gift", ".photos", ".life"]  # mutated in place


def test_merge_skips_already_present():
    cols = [".com", ".family"]
    added = merge_topical_columns(cols, ["family"])
    assert ".family" not in added              # already there
    assert added == [".gift", ".photos", ".life"]
    assert cols.count(".family") == 1          # no duplicate


def test_merge_respects_max_extra():
    cols = list(DEFAULT_TLDS)
    added = merge_topical_columns(cols, ["family"], max_extra=2)
    assert len(added) == 2


def test_merge_no_themes_is_noop():
    cols = list(DEFAULT_TLDS)
    assert merge_topical_columns(cols, []) == []
    assert cols == list(DEFAULT_TLDS)
