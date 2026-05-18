# 0004 — `vN.X` two-level versioning convention

- **Status:** Accepted
- **Date:** 2026-05-17 *(formalized during the v8.E split)*

## Context

Phase numbering had begun to drift toward three-level identifiers
(`vN.X.Y`) and colloquial "wedge N of M" / "sub-phase" labels as
in-flight commits introduced internal sub-numbering. The drift broke
two things: (1) commit-message archeology — a reference like
`v8.E.3` was ambiguous between "the third sub-step of v8.E" and "a
formal phase identifier"; (2) the phase-table 1:1 relationship with
the shipping cadence — an umbrella row covering 5 commits hides the
actual structure.

## Decision

**Two levels only: `vN.X`.**

- `vN` — major capability tier (SemVer-MAJOR semantics).
- `vN.X` — phase letter within a tier (`A`, `B`, `C`, …). Each phase
  letter is a shippable slice with exactly one commit subject.
- **Never `vN.X.Y`.** If a phase needs multiple shippable steps,
  push subsequent letters down to make room (the v8.E split:
  original v8.E became v8.E–v8.M).
- **Never `Phase N` / "wedge" / colloquial sub-numbering.**
- Renumbered rows carry a lineage marker
  (`*(renumbered YYYY-MM-DD — was vN.X)*`) so commit archeology
  resolves.
- The canonical statement lives in
  `sites/portfolio/AI_AGENTS.md` § Versioning. `CHECK_013
  ai-agents-references-versioning` enforces it across all
  `sites/<domain>/` projects.

## Consequences

**Positive.**
- Phase table stays 1:1 with the actual ship cadence — commit
  subjects honest (`portfolio: v8.H — primary interpretive pass
  runner`, not `… [wedge 4 of 5]`).
- Unambiguous references in commits, PRs, prompts, Prompts.md.
- The rule is enforceable mechanically (CHECK_013).

**Negative.**
- Renumbering propagates across multiple files when a tier expands
  (PRD phase table, AI_AGENTS roadmap row, Prompts.md, commits).
  Each renumber requires a lineage marker on every affected row.
- Long alphabet runs become awkward (`v8.E–v8.M` is 9 letters).
  Re-tiering (moving rows to a new major version, see the v8.E →
  v12 split) is the escape valve.

## References

- `sites/portfolio/AI_AGENTS.md` § Versioning (canonical statement).
- `CHECK_013 ai-agents-references-versioning`.
- Note on v8.E split (2026-05-17) in `docs/prd.md` § Versions.
- ADR-0010 — Three-canonical-doc model (this ADR's enforcement
  rule lives in `AI_AGENTS.md`).
