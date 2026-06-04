"""v29.B — values-aware `[content]` seed renderer.

Two invariants under test:
  1. `content_block()` with no values is byte-for-byte the canonical
     empty `CONTENT_SKELETON` (so the 2026-05-30 migration shape and
     CHECK_059 are unaffected).
  2. A seeded block is valid TOML whose `[content]` parses back to the
     exact values given — including an ICP paragraph with quotes,
     apostrophes, and newlines, and a `secondary_keywords` list.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

from portfolio import lamill_toml_edit as edit
from portfolio.lamill_toml import LAMILL_TOML_FILENAME


def _parse_content(block: str) -> dict:
    """Parse a rendered `[content]` block and return its table."""
    return tomllib.loads(block)["content"]


# ---- byte-identity of the empty render ------------------------------


def test_empty_render_is_byte_identical_to_skeleton():
    assert edit.content_block() == edit.CONTENT_SKELETON


def test_empty_dict_render_is_byte_identical_to_skeleton():
    assert edit.content_block({}) == edit.CONTENT_SKELETON


def test_empty_string_and_list_values_render_as_defaults():
    # Explicit empties are treated as "no value" → keep the skeleton.
    out = edit.content_block({"site_type": "", "secondary_keywords": []})
    assert out == edit.CONTENT_SKELETON


def test_unknown_keys_are_ignored():
    out = edit.content_block({"bogus": "x", "also_bogus": 1})
    assert out == edit.CONTENT_SKELETON


# ---- seeded renders parse back to the given values ------------------


def test_partial_fill_seeds_given_drops_comment_keeps_others_empty():
    out = edit.content_block({"site_type": "tool", "primary_keyword": "when2meet"})
    c = _parse_content(out)
    assert c["site_type"] == "tool"
    assert c["primary_keyword"] == "when2meet"
    # Unset fields stay at their empty defaults.
    assert c["icp"] == ""
    assert c["secondary_keywords"] == []
    # Seeded fields drop the inline guidance comment; empty ones keep it.
    assert "site_type = \"tool\"" in out
    assert "# the one phrase" not in out.split("primary_keyword")[1].split("\n")[0]
    assert "# ideal customer profile" in out  # icp still empty → comment present


def test_secondary_keywords_list_round_trips():
    kws = ["scheduling poll", "meeting time finder", "group availability"]
    c = _parse_content(edit.content_block({"secondary_keywords": kws}))
    assert c["secondary_keywords"] == kws


def test_icp_paragraph_with_quotes_apostrophes_newlines_round_trips():
    icp = (
        'The primary buyer is the eldest adult daughter in an NRI family. '
        'She does not search for "memoir services" — she searches for '
        '"questions to ask my mother."\n'
        "She's the one who manages the WhatsApp group."
    )
    c = _parse_content(edit.content_block({"icp": icp}))
    assert c["icp"] == icp


def test_full_fill_round_trips_every_field():
    values = {
        "site_type": "tool",
        "primary_keyword": "meeting scheduler",
        "secondary_keywords": ["when2meet alternative", "group poll"],
        "icp": "remote-team lead who's \"tired of email threads\"",
        "urgency_trigger": "a meeting to schedule across 4 time zones today",
        "penalty": "another lost hour in reply-all hell",
        "tone": "direct, friendly, no fluff",
        "law": "",
    }
    c = _parse_content(edit.content_block(values))
    for k, v in values.items():
        assert c[k] == v


def test_any_render_is_valid_toml():
    # Even a fully-seeded block must parse cleanly.
    out = edit.content_block({"icp": 'has "quotes" and\nnewlines', "site_type": "blog"})
    tomllib.loads(out)  # raises on malformed TOML


# ---- ensure_content_block seeding -----------------------------------


_BASE = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'


def _site(root: Path, body: str) -> Path:
    d = root / "x"
    d.mkdir()
    (d / LAMILL_TOML_FILENAME).write_text(body)
    return d


def test_ensure_content_block_no_values_appends_skeleton(tmp_path: Path):
    d = _site(tmp_path, _BASE)
    assert edit.ensure_content_block(d) is True
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert text.endswith(edit.CONTENT_SKELETON)


def test_ensure_content_block_seeds_values(tmp_path: Path):
    d = _site(tmp_path, _BASE)
    assert edit.ensure_content_block(d, {"site_type": "tool", "icp": "busy PM"}) is True
    c = tomllib.loads((d / LAMILL_TOML_FILENAME).read_text())["content"]
    assert c["site_type"] == "tool"
    assert c["icp"] == "busy PM"


def test_ensure_content_block_idempotent_does_not_merge(tmp_path: Path):
    d = _site(tmp_path, _BASE)
    edit.ensure_content_block(d, {"site_type": "tool"})
    # Second call with different values is a no-op (block already present).
    assert edit.ensure_content_block(d, {"site_type": "blog"}) is False
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert text.count("[content]") == 1
    assert tomllib.loads(text)["content"]["site_type"] == "tool"
