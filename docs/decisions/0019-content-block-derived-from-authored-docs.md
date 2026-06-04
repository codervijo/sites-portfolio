# 0019 — `lamill.toml [content]` is derived from the authored `AI_AGENTS.md`, not asked separately

- **Status:** Accepted
- **Date:** 2026-06-04

## Context

`new bootstrap` runs a short interview and writes the operator's answers
into `sites/<domain>/AI_AGENTS.md` — five authored prose sections:
Summary, Audience, ICP, Goals, Content strategy. Separately, the
2026-05-30 migration added a `[content]` block to every `lamill.toml`
(rankmill's content-identity source of truth): `site_type`,
`primary_keyword`, `secondary_keywords`, `icp`, `urgency_trigger`,
`penalty`, `tone`, `law`. Bootstrap seeded that block **empty** and left
a "Fill in [content]" todo.

The two were built at different times and never connected, so ICP (and
more) was authored once into the markdown and left blank in the TOML.
v29 set out to close the seam. The initial decision (v29.A) was narrow:
copy `icp` verbatim from `## ICP`, ask the operator for the other seven
fields.

A real-data check on four freshly-bootstrapped sites
(dearreels / meetwhen / scopeguard / threadradar) changed that. Their
authored `## Content strategy` and `## ICP` sections already contained
nearly every `[content]` field: Content strategy literally lists the
keyword targets (dearreels: *"questions to ask my mother," "long distance
grandparenting"*; meetwhen: *"best time to meet between [city] and
[city]"*) and often states the tone (scopeguard: *"speak like a security
peer"*). The fields did not need to be **asked** — they were already
**written**, just in prose.

This crosses the upgrade trigger recorded in v29.A: "the ICP-coupling sits
below the ADR bar — upgrades to an ADR only if more `[content]` fields get
sourced from `AI_AGENTS.md`." Sourcing seven fields from the authored docs
is a provenance posture, so it earns an ADR.

## Decision

**`lamill.toml [content]` is a derived projection of the authored
`AI_AGENTS.md` sections, not an independently-authored block.**

- `AI_AGENTS.md` is the single **authored** source of truth for a site's
  content identity. `[content]` is **generated** from it.
- `icp` is copied **verbatim** from `## ICP` (a direct paraphrase target,
  not an inference).
- The other seven fields are **derived** from the sections (especially
  `## Content strategy`) via one structured LLM call
  (`content_derive.derive_content`), reusing the existing OpenAI client.
- Bootstrap asks **no new questions** for `[content]`; derivation runs
  over sections the interview already collected.

**Derivation is best-effort and never load-bearing.** No `OPENAI_API_KEY`,
an empty brief, an HTTP failure, or unparseable model output all degrade
to "seed whatever we have" (at minimum the verbatim `icp`, possibly
nothing). Unfilled fields stay blank and re-seed the "Fill in [content]"
todo — honoring `[content]`'s "empty is better than wrong" rule and the
`lamill.toml` additive-optional invariant. The model's output is coerced
to the field schema (unknown keys dropped, `secondary_keywords` forced to
a list) before it touches the file.

**Conflict rule:** on divergence between `AI_AGENTS.md` and a derived
`[content]` value, `AI_AGENTS.md` is authoritative — `[content]` can be
re-derived from it, never the reverse. Operators may hand-edit
`[content]` (it remains a plain human-editable TOML block), but a re-run
of derivation reflects the docs, so durable changes belong in the docs.

## Consequences

- **No double-authoring.** The operator writes the brief once; `[content]`
  follows. The seam that left ICP stored-twice-second-copy-blank is closed.
- **A model dependency enters the bootstrap path** — but only as an
  optional enhancement. Bootstrap still succeeds with no API key (empty
  block + full todo), so the dependency is soft, matching the
  soft-fail-auxiliary posture of ADR-0015.
- **Derived ≠ verified.** LLM-derived fields are a starting point; they
  can be wrong or thin. The "Fill in [content]" todo re-seeds for blank
  fields, and operators are expected to review/refine. We do not treat a
  derived block as authoritative content.
- **`[content]` provenance is now documented**, so a future reader asking
  "why is this LLM-generated, not hand-written?" has the answer, and the
  conflict rule tells them which file to edit.
- **Existing sites are unaffected until backfilled.** The four sites that
  surfaced this keep their empty blocks until the v29.E backfill path runs
  `content_derive` over their docs (deferred until the bootstrap path
  proves derivation quality).

## See also

- `docs/prd.md § v29` — phases + design notes
- ADR-0017 — additive-optional tables (why an empty/partial `[content]`
  is always valid)
- ADR-0018 — upsert-not-rewrite (how the seeded block is written without
  clobbering)
- `docs/CLAUDE.md § 🔒 lamill.toml additive-optional invariant`
- `src/portfolio/content_derive.py`, `src/portfolio/lamill_toml_edit.py`
