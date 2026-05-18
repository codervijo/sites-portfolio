"""Canonical section list for `sites/<domain>/AI_AGENTS.md` files.

Single source of truth for the v9.A schema. **As of v9.E**, the list
lives in `canonical_sections.toml` at the repo root, not in this
module — operators can edit the schema (rename a section, add a new
one, reorder, change source=operator vs template, tweak placeholder
text) by editing the TOML without touching Python code or shipping a
release.

This module loads the TOML at import time and exposes the parsed
result as the same `AI_AGENTS_SECTIONS` tuple of `CanonicalSection`
dataclasses every consumer used pre-v9.E. The contract for consumers
(the conformance check, the bootstrap template renderer, the v9.B
interactive prompts) is unchanged.

Schema version handling: the loader checks `schema_version` in the
TOML against `EXPECTED_SCHEMA_VERSION` in this module. A mismatch
raises `CanonicalSchemaError` rather than silently loading. Bumping
the schema (e.g., adding a new field, changing the source enum) is
an explicit two-step: edit the TOML + bump the constant here.
"""
from __future__ import annotations

import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .data import ROOT


CANONICAL_SECTIONS_TOML = ROOT / "canonical_sections.toml"
EXPECTED_SCHEMA_VERSION = "v9.A"
VALID_SOURCES = ("operator", "template")


class CanonicalSchemaError(RuntimeError):
    """Raised when canonical_sections.toml is missing, unparseable,
    schema-version mismatched, or contains invalid section entries.

    Loud failure is intentional — the AI_AGENTS schema is the
    contract underlying CHECK_014 / v9.B prompts / bootstrap template.
    Silently falling back to an in-code default would mask drift
    between the TOML and consumer code."""


@dataclass(frozen=True)
class CanonicalSection:
    """One row in the AI_AGENTS.md canonical schema.

    `heading` is the exact H2 text (without the `## ` marker) — the
    check matches on `## {heading}` line-anchored. Case-sensitive
    by design.

    `source` is `"operator"` when the bootstrap interactive prompts
    collect this section's content from the user; `"template"` when
    the bootstrap template renderer populates it with project-aware
    boilerplate.

    `description` is the one-line human-readable hint surfaced in
    the tier-1 fix's placeholder body, the interactive-prompt help
    text, and the `--help` rendering.
    """
    heading: str
    source: str          # "operator" | "template"
    description: str


def _load_from_toml(path: Path = CANONICAL_SECTIONS_TOML) -> tuple[CanonicalSection, ...]:
    """Parse the canonical-sections TOML into a frozen tuple.

    Validates:
      - File exists and is readable.
      - Parses as valid TOML.
      - `schema_version` matches `EXPECTED_SCHEMA_VERSION`.
      - At least one `[[sections]]` entry.
      - Each entry has `heading`, `source`, `description` fields.
      - `source` value is in `VALID_SOURCES`.

    Raises `CanonicalSchemaError` on any check failure with a
    message that names exactly what's wrong so the operator can
    fix the TOML without spelunking.
    """
    if not path.is_file():
        raise CanonicalSchemaError(
            f"canonical_sections.toml not found at {path}. "
            "This file is the single source of truth for the "
            "AI_AGENTS.md schema; the loader refuses to fall back "
            "to a hardcoded default to prevent silent drift. "
            "If the file was accidentally deleted, restore it from git."
        )
    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise CanonicalSchemaError(
            f"canonical_sections.toml at {path} is not valid TOML: {e}"
        ) from e

    version = data.get("schema_version")
    if version != EXPECTED_SCHEMA_VERSION:
        raise CanonicalSchemaError(
            f"canonical_sections.toml schema_version={version!r}, but "
            f"this build expects {EXPECTED_SCHEMA_VERSION!r}. "
            "Either upgrade the codebase (edit "
            "`EXPECTED_SCHEMA_VERSION` in portfolio/canonical_sections.py) "
            "or roll the TOML back to the matching version."
        )

    raw_sections = data.get("sections")
    if not isinstance(raw_sections, list) or not raw_sections:
        raise CanonicalSchemaError(
            f"canonical_sections.toml at {path} has no [[sections]] "
            "entries. At least one section is required."
        )

    out: list[CanonicalSection] = []
    for i, entry in enumerate(raw_sections, 1):
        if not isinstance(entry, dict):
            raise CanonicalSchemaError(
                f"[[sections]] entry #{i} is not a table — got {type(entry).__name__}"
            )
        for required in ("heading", "source", "description"):
            if required not in entry:
                raise CanonicalSchemaError(
                    f"[[sections]] entry #{i} (heading="
                    f"{entry.get('heading')!r}) missing required "
                    f"field {required!r}"
                )
        if entry["source"] not in VALID_SOURCES:
            raise CanonicalSchemaError(
                f"[[sections]] entry #{i} (heading={entry['heading']!r}) "
                f"has invalid source={entry['source']!r}; must be one of "
                f"{VALID_SOURCES}"
            )
        out.append(CanonicalSection(
            heading=entry["heading"],
            source=entry["source"],
            description=entry["description"],
        ))
    return tuple(out)


# Loaded at import — raises CanonicalSchemaError if TOML is missing
# or malformed. Test code that wants to exercise the loader against
# a synthetic TOML can call `_load_from_toml(path)` directly.
AI_AGENTS_SECTIONS: tuple[CanonicalSection, ...] = _load_from_toml()


def operator_sections() -> tuple[CanonicalSection, ...]:
    """The sections the bootstrap interactive prompts (v9.B) collect
    from the operator. Filtered view of AI_AGENTS_SECTIONS so callers
    don't have to know the source-tag literal."""
    return tuple(s for s in AI_AGENTS_SECTIONS if s.source == "operator")


def template_sections() -> tuple[CanonicalSection, ...]:
    """The sections the bootstrap template renderer populates with
    project-aware boilerplate. Filtered view of AI_AGENTS_SECTIONS."""
    return tuple(s for s in AI_AGENTS_SECTIONS if s.source == "template")


def section_headings() -> tuple[str, ...]:
    """Just the H2 heading strings, in canonical order. Used by the
    conformance check's "find missing sections" loop and by callers
    that don't need the source/description metadata."""
    return tuple(s.heading for s in AI_AGENTS_SECTIONS)
