# 0001 — Record architecture decisions

- **Status:** Accepted
- **Date:** 2026-05-18

## Context

The `portfolio` / `lamill` project has accumulated ~30–50 load-bearing
architectural decisions across its first 14 version tiers: language
choice, write-surface constraints, catalog shape, model-family
choices, lockfile policy, build conventions, doc structure, and more.

Until today, most of these decisions lived as either (a) one-line
mentions in `docs/CLAUDE.md` (under "Conventions" or "Deferred
decisions"), (b) "Resolved YYYY-MM-DD" annotations inside the open-
questions sections of detailed PRDs in `docs/prd.md`, or (c) commit
messages.

Two problems with the status quo:

1. **Discoverability is poor.** A future session (or operator
   re-evaluating an old choice) has to grep across the PRD's detailed
   sections + scan commit history to reconstruct "why is it this way."
2. **The active spec (`docs/prd.md`) bloats with historical
   rationale.** As of 2026-05-18 the PRD was 3700+ lines, largely
   because resolved open questions persisted alongside the active spec.

The recent canonical-docs restructure (2026-05-18, ADR-0010) split
the spec into `prd.md` (WHY/WHAT/WHEN), `architecture.md` (HOW), and
`shipping-history.md` (per-phase rationale archive). That helps, but
shipping-history.md is organized by **phase**, while many decisions
are cross-cutting (they apply across phases — e.g., Python + uv is
v0-level, not bound to a specific phase). ADRs fit that cross-cutting
shape better.

## Decision

Adopt **Architecture Decision Records (ADRs)** in `docs/decisions/`
for load-bearing architectural decisions in this project.

- Format: lightweight Nygard
  (Status / Context / Decision / Consequences / References).
- Files: `NNNN-kebab-case-title.md`, sequentially numbered, never
  re-numbered.
- Append-only — new ADRs supersede old ones; old bodies stay intact.
- **Scope:** `portfolio` repo only. Sibling `sites/<domain>/`
  projects do NOT use ADRs — they're consumer projects without
  architectural complexity to warrant the overhead.
- **Forward commitment:** when a new phase introduces a load-bearing
  decision, an ADR is part of the shipping unit (alongside code +
  PRD/architecture updates per § Spec discipline).
- Heuristic for "is this load-bearing": *"if someone re-evaluating
  the codebase six months from now asked 'why is it this way?' —
  would the answer be obvious from the code alone, or would they need
  the rationale?"* The latter case warrants an ADR.

Backfill: ten initial ADRs (0001–0010) capture the most load-bearing
existing decisions. Smaller existing resolved open questions stay in
`shipping-history.md`.

## Consequences

**Positive.**
- Decision rationale becomes durable and indexed (via
  `docs/decisions/README.md`).
- Active spec (`prd.md`) stays lean — resolved cross-cutting
  decisions no longer accrete there.
- Industry-standard convention; future Claude sessions and any
  human collaborators recognize the pattern immediately.
- Supersession workflow surfaces *progression* of thinking, not just
  the latest state — useful when revisiting an area.

**Negative.**
- Some maintenance overhead: each load-bearing decision means
  another file. Heuristic must be honored — without discipline, ADR
  count balloons.
- Risk of "write-only" — ADRs only pay off when actually read on
  re-evaluation. Personal projects can lose this habit.
- Adds a fifth canonical location to a doc model that just landed
  at four (prd, architecture, shipping-history, CLAUDE.md). The
  AI_AGENTS.md "Canonical docs" table expands by one row.
- Backfilling ~10 ADRs has a one-time cost (this commit).

**Trade-offs accepted.**
- Granularity: load-bearing only. Small open-question resolutions
  stay in `shipping-history.md`. Boundary is judgment-call — when in
  doubt, err on writing the ADR (cheap to add; expensive to recover
  rationale that was never written down).
- Sibling sites/* exclusion: revisit if a sibling grows to
  meaningful architectural complexity. None do today.

## References

- Michael Nygard, "Documenting Architecture Decisions" (2011) —
  the canonical Nygard format.
- `../prd.md` § Spec discipline.
- `../CLAUDE.md` § ADR workflow.
- ADR-0010 — Three-canonical-doc model + heading hygiene (the
  parent restructure this ADR builds on).
