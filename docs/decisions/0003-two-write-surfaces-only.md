# 0003 — Two write surfaces only (`bootstrap`, `project fix`)

- **Status:** Accepted
- **Date:** 2026-04-30 *(retroactively recorded 2026-05-18)*

## Context

`portfolio` is primarily a read-only operator console: status reports,
drift detection, focus rankings, SEO/GSC dashboards. As the tool grew,
the question arose — how much should it write back to project
directories under `sites/<domain>/`? Without an explicit constraint, a
tool with this many integrations could accumulate ad-hoc write
surfaces ("auto-sync this," "auto-fix that," "push the other"). Each
such surface multiplies the risk model and makes the audit boundary
fuzzy.

## Decision

**Exactly two write surfaces** are permitted into `sites/<domain>/`
project directories:

1. **`new bootstrap <domain>`** — creates a new project directory
   from a templated scaffold (v3.A).
2. **`project fix <domain> --apply`** — modifies an existing project
   directory to fix conformance gaps detected by the catalog
   (v6.D Tier 1; v6.E Tier 2 via Claude subprocess — see ADR-0006).

Everything else (`status`, `drift`, `focus`, `dashboard`, `check seo`,
`check live`, `check git`, `info`, `diagnose`, ...) is **read-only by
design.** Snapshot writes to `portfolio`'s own `data/` tree do not
count toward this constraint — they don't touch sibling project dirs.

## Consequences

**Positive.**
- Predictable risk model — only two commands can mutate sibling
  project dirs, both gated behind explicit flags (`--apply`, `--yes`).
- Clear audit boundary: any unexpected change in a sibling repo
  traces to one of these two commands.
- Simpler mental model for the operator and for future sessions.

**Negative.**
- Operations that *feel* write-ish (snapshot caches, OAuth token
  storage) need clear categorization. They're allowed because they
  don't touch project dirs — explicit carve-out, not a write surface.
- New write needs require explicit operator decision + ADR
  supersession — slows down ad-hoc tool growth (intended).

## References

- `AI_AGENTS.md` § Architecture (two write surfaces note).
- `docs/CLAUDE.md` § Conventions.
- v3.A (bootstrap), v6.D (project fix Tier 1), v6.E (Tier 2).
