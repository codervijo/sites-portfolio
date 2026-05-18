# 0008 — `pnpm`-only for `sites/*`

- **Status:** Accepted
- **Date:** 2026-05-09 *(CHECK_032/033/034 catalog entries)*

## Context

Cloudflare Pages auto-detects build tooling from lockfile presence
in the repo root. A repo with both `pnpm-lock.yaml` and any of
`package-lock.json` / `bun.lockb` / `yarn.lock` triggers CF Pages'
**bun-detection** path. The bun runner then fails on Vite ≥6 /
Astro ≥5 projects — Vite 5 happened to work; Vite ≥6 doesn't.

The trap was hit on a real sibling project in May 2026 when a stale
`package-lock.json` from an early experiment lingered in the repo
after the migration to pnpm. CF Pages build broke silently.

## Decision

**`pnpm`-only across every `sites/<domain>/` project.**

- `package-lock.json` — conformance failure (CHECK_032).
- `bun.lockb` — conformance failure (CHECK_033).
- `yarn.lock` — conformance failure (CHECK_034).
- All three have Tier 1 fixers (`file_deleter`) that remove the
  offending file on `project fix --apply`. Per-file confirmation
  unless `--yes`.
- Bootstrap output uses `pnpm` exclusively — no `npm install` /
  `bun install` in scaffold templates.
- Vite ≥6, Astro ≥5 minimum (the bun-detection trap on Vite 5
  motivated this floor).

## Consequences

**Positive.**
- CF Pages bun-detection trap is impossible on a conformant repo.
- Single, predictable build tool across all sites; faster CI installs
  via pnpm's content-addressable store.
- Lockfile diff reviews simpler (one format).

**Negative.**
- Operators with bun/yarn muscle memory must switch on `sites/*`.
- Lockfile fixers can be destructive (deleting `bun.lockb` is
  irreversible without git history) — gated behind explicit
  confirmation per file unless `--yes`.

## References

- CHECK_032 (`pnpm-lock-not-package-lock`).
- CHECK_033 (`pnpm-lock-not-bun-lockb`).
- CHECK_034 (`pnpm-lock-not-yarn-lock`).
- `src/portfolio/fix_helpers.py` `file_deleter` factory.
- `AI_AGENTS.md` § Conventions; `docs/CLAUDE.md` § Conventions.
- v6.D — Remediation Tier 1 (the fixers landed here).
