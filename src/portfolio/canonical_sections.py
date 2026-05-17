"""Canonical section list for `sites/<domain>/AI_AGENTS.md` files.

Single source of truth for the v9.A schema — every `sites/<domain>/`
project's AI_AGENTS.md must contain these 10 H2 sections, in order.
The conformance check (`CHECK_014 ai-agents-md-has-canonical-sections`)
reads this list to verify; the matching tier-1 fix reads it to inject
missing sections; the bootstrap template renderer reads it to produce
new projects with the full structure.

Five sections are **operator-input** — the bootstrap interactive
prompts (v9.B) collect those at scaffold time; missing values render
as `(to be filled in)` placeholders. Five are **template-driven** —
the bootstrap template renderer populates them with project-aware
boilerplate.

v9.E will refactor this in-code list to a JSON-driven single source
of truth (e.g., `data/canonical_sections.json`) loaded at runtime,
so the schema can be edited as data without touching Python. For now
(v9.A) the list lives in this module as a frozen tuple of
dataclasses — same shape; just the storage changes.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CanonicalSection:
    """One row in the AI_AGENTS.md canonical schema.

    `heading` is the exact H2 text (without the `## ` marker) — the
    check matches on `## {heading}` line-anchored at the start of a
    line. Case-sensitive (renaming "Summary" to "summary" would
    silently break every existing project's check, so the schema is
    strict by design).

    `source` is `"operator"` when the bootstrap interactive prompts
    collect this section's content from the user; `"template"` when
    the bootstrap template renderer populates it with project-aware
    boilerplate.

    `description` is a one-line human-readable hint used by the
    tier-1 fix's placeholder body, the `lamill new bootstrap`
    interactive-prompt help text, and the `--help` rendering.
    """
    heading: str
    source: str          # "operator" | "template"
    description: str


# v9.A schema — 10 sections, in render order. Order matters: missing
# sections are injected at the END of AI_AGENTS.md by the tier-1 fix
# (appending preserves existing operator content), but the bootstrap
# template renderer writes them in this order so new projects start
# with the canonical layout.
AI_AGENTS_SECTIONS: tuple[CanonicalSection, ...] = (
    CanonicalSection(
        heading="Summary",
        source="operator",
        description="one paragraph: what this site is, what it does",
    ),
    CanonicalSection(
        heading="Audience",
        source="operator",
        description="one sentence: who this is for (broad demographic)",
    ),
    CanonicalSection(
        heading="ICP",
        source="operator",
        description=(
            "the specific ideal customer — demographics, pain points, what "
            "they use today. More detail than Audience: Audience is the "
            "broad demo (\"homeowners with EV chargers\"), ICP is the "
            "specific targetable subset (\"Tesla owners in CA who "
            "installed in last 90d, paid $2k+\")"
        ),
    ),
    CanonicalSection(
        heading="Goals",
        source="operator",
        description="1-2 sentences: primary business / product goal",
    ),
    CanonicalSection(
        heading="Tech stack",
        source="template",
        description="frontend stack (Astro / Vite / etc.) + key deps",
    ),
    CanonicalSection(
        heading="Building info",
        source="template",
        description=(
            "Makefile forwards-to-parent, `make deps` / `make dev` / "
            "`make build` recipes"
        ),
    ),
    CanonicalSection(
        heading="Deployment info",
        source="template",
        description=(
            "platform (CF Pages / Vercel / Netlify), wrangler.jsonc, "
            "predicted live URL"
        ),
    ),
    CanonicalSection(
        heading="Content strategy",
        source="operator",
        description=(
            "what content this site needs — page types, initial topics, "
            "format mix (long-form vs reference vs tool)"
        ),
    ),
    CanonicalSection(
        heading="Versioning",
        source="template",
        description=(
            "two-level vN.X rule pointer + CHECK_013 reference "
            "(canonical convention defined in sites/portfolio/AI_AGENTS.md)"
        ),
    ),
    CanonicalSection(
        heading="Conventions",
        source="template",
        description=(
            "pnpm-only, Vite ≥6, deferred-decisions log, project-specific "
            "quirks"
        ),
    ),
)


def operator_sections() -> tuple[CanonicalSection, ...]:
    """The sections the bootstrap interactive prompts (v9.B) need to
    collect from the operator. Filtered view of AI_AGENTS_SECTIONS
    so callers don't have to know the source-tag literal."""
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
