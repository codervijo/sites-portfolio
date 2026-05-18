"""Tests for v9.E — `canonical_sections.toml` single source of truth
loaded by `portfolio.canonical_sections._load_from_toml`.

Two layers:
  1. The real file at repo root parses cleanly and produces the
     same 10-section schema v9.A/B/C/D depend on.
  2. The loader rejects malformed / wrong-schema / missing TOML
     loudly via `CanonicalSchemaError` (no silent fallback).
"""
from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from portfolio.canonical_sections import (
    AI_AGENTS_SECTIONS,
    CANONICAL_SECTIONS_TOML,
    CanonicalSchemaError,
    CanonicalSection,
    EXPECTED_SCHEMA_VERSION,
    _load_from_toml,
)


# ---------- real-file sanity ----------


def test_canonical_sections_toml_exists_at_repo_root():
    """The TOML file lives at the repo root (not in src/ or data/).
    This is the contract operators rely on when editing the schema."""
    assert CANONICAL_SECTIONS_TOML.is_file(), (
        f"canonical_sections.toml missing at {CANONICAL_SECTIONS_TOML}"
    )


def test_real_toml_produces_ten_sections():
    """The shipped TOML matches the v9.A schema — 10 sections."""
    assert len(AI_AGENTS_SECTIONS) == 10


def test_real_toml_preserves_canonical_order():
    """Whatever order is in the TOML is the order consumers see.
    Pins the expected order against drift introduced by future
    edits to the TOML."""
    assert [s.heading for s in AI_AGENTS_SECTIONS] == [
        "Summary", "Audience", "ICP", "Goals",
        "Tech stack", "Building info", "Deployment info",
        "Content strategy", "Versioning", "Conventions",
    ]


# ---------- _load_from_toml: happy path ----------


def test_loader_parses_minimal_valid_toml(tmp_path):
    p = tmp_path / "minimal.toml"
    p.write_text(dedent(f"""\
        schema_version = "{EXPECTED_SCHEMA_VERSION}"

        [[sections]]
        heading = "Only Section"
        source = "operator"
        description = "just one"
    """))
    out = _load_from_toml(p)
    assert len(out) == 1
    assert out[0] == CanonicalSection(
        heading="Only Section",
        source="operator",
        description="just one",
    )


def test_loader_preserves_order_from_toml(tmp_path):
    p = tmp_path / "order.toml"
    p.write_text(dedent(f"""\
        schema_version = "{EXPECTED_SCHEMA_VERSION}"

        [[sections]]
        heading = "Z"
        source = "operator"
        description = "last alphabetically"

        [[sections]]
        heading = "A"
        source = "template"
        description = "first alphabetically"
    """))
    out = _load_from_toml(p)
    assert [s.heading for s in out] == ["Z", "A"]


# ---------- _load_from_toml: failure modes ----------


def test_loader_raises_when_file_missing(tmp_path):
    """Missing TOML → loud failure with a message telling the
    operator where the file should live."""
    missing = tmp_path / "does_not_exist.toml"
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(missing)
    assert "not found" in str(exc.value)
    assert str(missing) in str(exc.value)


def test_loader_raises_on_malformed_toml(tmp_path):
    """Syntactically broken TOML → wrapped error pointing at the
    file so the operator knows what to fix."""
    p = tmp_path / "broken.toml"
    p.write_text("this is not [ valid toml = ")
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    assert "not valid TOML" in str(exc.value)


def test_loader_raises_on_schema_version_mismatch(tmp_path):
    """Wrong `schema_version` → refuses to load. Forces an explicit
    code bump alongside any schema-shape change."""
    p = tmp_path / "wrong_version.toml"
    p.write_text(dedent("""\
        schema_version = "v99.Z"

        [[sections]]
        heading = "X"
        source = "operator"
        description = "..."
    """))
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    msg = str(exc.value)
    assert "schema_version" in msg
    assert "v99.Z" in msg
    assert EXPECTED_SCHEMA_VERSION in msg


def test_loader_raises_when_schema_version_missing(tmp_path):
    """Same code path treats missing-version as a mismatch (None vs
    expected string) — defensive against operator drops the field
    while editing."""
    p = tmp_path / "no_version.toml"
    p.write_text(dedent("""\
        [[sections]]
        heading = "X"
        source = "operator"
        description = "..."
    """))
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    assert "schema_version" in str(exc.value)


def test_loader_raises_when_no_sections(tmp_path):
    """Empty / missing `[[sections]]` → explicit error rather than
    a silent empty tuple."""
    p = tmp_path / "no_sections.toml"
    p.write_text(f'schema_version = "{EXPECTED_SCHEMA_VERSION}"\n')
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    assert "no [[sections]] entries" in str(exc.value).lower() or \
           "sections" in str(exc.value).lower()


def test_loader_raises_on_section_missing_required_field(tmp_path):
    """A section entry without `heading` / `source` / `description`
    → specific error naming the missing field."""
    p = tmp_path / "incomplete.toml"
    p.write_text(dedent(f"""\
        schema_version = "{EXPECTED_SCHEMA_VERSION}"

        [[sections]]
        heading = "X"
        source = "operator"
        # description omitted intentionally
    """))
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    assert "description" in str(exc.value)


def test_loader_raises_on_invalid_source_value(tmp_path):
    """`source` must be `operator` or `template` — anything else is
    a contract violation that would break v9.B's prompt filter."""
    p = tmp_path / "bad_source.toml"
    p.write_text(dedent(f"""\
        schema_version = "{EXPECTED_SCHEMA_VERSION}"

        [[sections]]
        heading = "X"
        source = "wrong-tag"
        description = "..."
    """))
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    msg = str(exc.value)
    assert "source" in msg
    assert "wrong-tag" in msg


def test_loader_error_messages_include_section_index(tmp_path):
    """Errors on the Nth section name N so the operator can find
    the entry in a long TOML without grep guesswork."""
    p = tmp_path / "indexed.toml"
    p.write_text(dedent(f"""\
        schema_version = "{EXPECTED_SCHEMA_VERSION}"

        [[sections]]
        heading = "First"
        source = "operator"
        description = "ok"

        [[sections]]
        heading = "Second"
        source = "operator"
        description = "ok"

        [[sections]]
        heading = "Third"
        source = "broken"
        description = "the bad one"
    """))
    with pytest.raises(CanonicalSchemaError) as exc:
        _load_from_toml(p)
    msg = str(exc.value)
    # The error message references the offending section's index.
    assert "#3" in msg or "Third" in msg
