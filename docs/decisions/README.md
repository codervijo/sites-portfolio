# Architecture Decision Records (ADRs)

This directory holds **load-bearing architectural decisions** for
`portfolio` / `lamill`. Each ADR captures a decision that future
re-evaluation would depend on: *why* we chose X over Y, what the
trade-offs were, and what the consequences are.

> **Scope: `portfolio` only.** Sibling `sites/<domain>/` projects do
> NOT use ADRs — they're consumer projects without architectural
> complexity to warrant the overhead.

## Index

| #    | Title                                              | Status      | Supersedes |
|------|----------------------------------------------------|-------------|-----------|
| 0001 | Record architecture decisions (meta-ADR)           | Accepted    | —         |
| 0002 | Python + uv for the portfolio CLI                  | Accepted    | —         |
| 0003 | Two write surfaces only (`bootstrap`, `project fix`)| Accepted   | —         |
| 0004 | `vN.X` two-level versioning convention             | Accepted    | —         |
| 0005 | File-per-check catalog (not centralized registry)  | Accepted    | —         |
| 0006 | Tier 2 fixers as Claude subprocess                 | Accepted    | —         |
| 0007 | Audit pass uses different model family             | Accepted    | —         |
| 0008 | `pnpm`-only for `sites/*`                          | Accepted    | —         |
| 0009 | Makefile forwards to central builder               | Accepted    | —         |
| 0010 | Three-canonical-doc model + heading hygiene        | Accepted    | —         |
| 0011 | Remote-host writes as a separate write-surface category | Accepted | —         |
| 0012 | No `wrangler deploy`; git-integrated CF Pages API for all CF deploys | Accepted | —         |
| 0013 | Astro + Vite as the only supported `sites/*` stack (Claude-translation for non-Astro `--git-url`) | Accepted | —         |

## When to write an ADR

Write an ADR when a decision is **load-bearing** — i.e., future
re-evaluation of the codebase or architecture would hinge on knowing
*why* this decision was made. Heuristic test: "if someone six months
from now asked 'why is it this way?' — would the answer be obvious from
the code alone, or would they need the rationale?"

- ✅ Write an ADR for: choice of language/runtime, write-surface
  constraints, catalog/registry shape, model-family choices, lockfile
  policy, build-tool conventions, doc-architecture choices.
- ❌ Don't write an ADR for: small implementation details (parser
  library choice, default flag values, log format) — those belong in
  the resolved-open-questions of `docs/shipping-history.md` or inline
  in code comments.

**Forward-looking commitment.** When working on a new phase that
introduces a load-bearing decision, the *expected* output includes an
ADR — alongside the code and the doc updates per
`docs/prd.md § Spec discipline`. ADRs are not a "we'll write these up
later" backlog; they're part of the shipping unit.

## Format

Lightweight Nygard. Each ADR file is a short Markdown document with:

```markdown
# NNNN — Short imperative title

- **Status:** Proposed | Accepted | Deprecated | Superseded by ADR-NNNN
- **Date:** YYYY-MM-DD

## Context
(One or two paragraphs: what's the situation, what's the problem,
 what constraints or forces are in play.)

## Decision
(The decision in plain language. What we will do.)

## Consequences
(Positive and negative outcomes of this decision, both short and
 long term. Trade-offs we explicitly accept.)

## References
- (optional — links to PRs, issues, related ADRs, external sources)
```

## Naming + numbering

- Filenames: `NNNN-kebab-case-short-title.md`, four-digit zero-padded.
- Numbers are assigned sequentially. **Never re-number** — the ID is
  the stable reference.
- Titles are short imperative phrases ("Record architecture
  decisions", "Use Python + uv for the CLI").

## Supersession workflow

Decisions evolve. Rather than editing an accepted ADR, write a new
one:

1. New ADR (next available number) captures the new decision.
2. New ADR's frontmatter says `Supersedes: ADR-NNNN`.
3. Old ADR's frontmatter changes to
   `Status: Superseded by ADR-MMMM`.
4. Old ADR body stays intact — historical record.
5. Update this index: old row's Status becomes
   `Superseded by 0XXX`; new row inserted in numerical order.

**Why append-only:** rewriting history obscures the actual progression
of thinking. Future re-evaluations benefit from seeing what was tried
and why it didn't last.

## Status meanings

- **Proposed** — drafted; awaiting alignment / sign-off. Don't act on
  it yet.
- **Accepted** — in force. Code, mechanisms, and docs reflect this.
- **Deprecated** — no longer applies, but no superseding ADR exists
  (rare; usually means the architectural area was abandoned).
- **Superseded by ADR-NNNN** — replaced by a later ADR.

## See also

- `../prd.md` § Spec discipline
- `../architecture.md` — current-state HOW
- `../shipping-history.md` — archived design rationale for shipped phases
- `../CLAUDE.md` — Claude-specific decisions + ADR workflow
- `../../AI_AGENTS.md` — agent orientation + canonical-docs table
