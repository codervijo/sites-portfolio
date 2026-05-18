# 0010 — Three-canonical-doc model + heading hygiene

- **Status:** Accepted
- **Date:** 2026-05-18 *(this restructure)*

## Context

`docs/prd.md` had grown to **3700+ lines** as four detailed-PRD
bodies were inlined under a single `## 8. Detailed PRDs` wrapper
section. Each detailed PRD was pasted at `##` heading depth — the
same depth as the file's top-level `## 1. Purpose` / `## 2.
Audience` headings — instead of being demoted to `###` under the
wrapper.

The result: four parallel `## 1. Problem statement` headings, four
parallel `## 2. Goals and non-goals` headings, four parallel
`## 4. Functional requirements` headings, etc., all sitting at the
same H2 depth as the file's actual top-level sections. VS Code's
outline view exposed it as a flat column with repeating numbers
(1, 2, 3, 4, 5, 1, 2, 3, 4, 5, …) — visual evidence of a structural
mess invisible during any individual editing session.

Internal subsection labels (`### 6.A`, `### 8.A`, `### 10.A`)
inside each detailed-PRD's open-questions section visually collided
with phase identifiers (`v6.A`, `v8.A`, `v10.A`) — the same
two-level-number-letter pattern serving two unrelated purposes.

## Decision

**Three canonical docs** in `docs/` (plus this file's directory as
the fourth load-bearing addition, plus `CLAUDE.md` as the fifth):

1. **`docs/prd.md`** — WHY / WHAT / WHEN. Purpose, problem
   statement, target user, goals, versions/phases, conformance
   rules, open questions.
2. **`docs/architecture.md`** — HOW. Project layout, mechanisms,
   schemas, data models, modules, CLI/UX conventions, external
   integrations, stack baselines, active implementation plans,
   risks, tracked refactors.
3. **`docs/shipping-history.md`** — archived design rationale for
   shipped phases (append-only).

Plus:

4. **`docs/decisions/`** — load-bearing architecture decisions
   (this ADR system). See ADR-0001.
5. **`docs/CLAUDE.md`** — Claude-specific decisions, locked target
   shapes, deferred decisions, heading-hygiene rule.

Plus `AI_AGENTS.md` at repo root — agent orientation, canonical
versioning rule (ADR-0004), `## Canonical docs` table.

**Heading-hygiene pre-edit ritual:** before adding any heading to a
Markdown file, output the file's current outline via
`grep -nE '^#+ '` and confirm the planned heading's depth and label
don't collide. Codified in `docs/CLAUDE.md` § Heading hygiene and
propagated to every `sites/<domain>/docs/CLAUDE.md`.

**Spec discipline rule** (in `docs/prd.md`): reality + code + all
five docs must match. Stale docs are a conformance failure, not a
backlog item.

## Consequences

**Positive.**
- Each doc has a single source of truth and an update-when trigger
  (codified in `AI_AGENTS.md` § Canonical docs table).
- Heading collisions become impossible by construction — each
  doc owns its own H1/H2 hierarchy.
- Future Claude sessions can identify which doc to edit from the
  triggers, reducing the chance of dropping content in the wrong
  file.
- ADRs (this directory) give cross-cutting architectural decisions
  a durable home, distinct from phase-scoped rationale in
  shipping-history.md.

**Negative.**
- Five files to keep in sync (plus per-phase rationale in
  shipping-history.md). Discipline is required — Spec discipline
  rule is the enforcement.
- Cross-references between docs need maintenance — a moved or
  renamed section in `architecture.md` must update references in
  `prd.md` / `shipping-history.md` / ADRs.
- One-time migration cost (separate commit after this ADR ships):
  move all technical detail from `prd.md` to `architecture.md`,
  move shipped-phase rationale to `shipping-history.md`,
  restructure `prd.md` to its new 9-section top-level shape.

## References

- `AI_AGENTS.md` § Canonical docs.
- `docs/CLAUDE.md` § Canonical docs — when to update which.
- `docs/CLAUDE.md` § Heading hygiene.
- Feedback memory `feedback-md-heading-outline-first` (ritual).
- ADR-0001 — Record architecture decisions (the ADR adoption itself).
