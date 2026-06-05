# 0020 — Post-publish indexing notification lives in the conformance/fix loop

- **Status:** Accepted
- **Date:** 2026-06-05

## Context

The fleet ships sites but has no search-engine notification on publish:
`gsc_admin.submit_sitemap` tells Google only, and nothing notifies the
IndexNow network (Bing/Yandex/Naver/Seznam/Yep — Google does not
participate). New/changed URLs wait for organic crawl.

IndexNow is the clean, free, sanctioned channel: a self-authenticating
`public/<key>.txt` file at the domain root + a single POST that fans out to
all participating engines. The capability is gap-and-remediate shaped —
"this site should be able to notify search engines about its live URLs" —
which is exactly what the CHECK catalog + `fix_tier_1` express.

The alternative framings considered and rejected: a dedicated `index` CLI
command group (rejected — adds a command surface and a per-site invocation
burden; see the prefer-check/fix preference), and the Google Indexing API
key-rotation approach IndexerHub uses (rejected as a documented non-goal —
it circumvents a 200/day per-project quota for a `JobPosting`/`BroadcastEvent`-only
API that no fleet site qualifies for).

A separate question is whether a *remote* side effect (the IndexNow POST)
belongs inside a fixer at all. It does: `CHECK_057`'s fixer already calls
the Cloudflare API and `CHECK_150`'s calls Vercel's, both re-probing to
verify. So "fixers may perform remote writes with a re-probe" is an
established pattern, not a new write-surface category.

## Decision

**Post-publish indexing is delivered through the conformance machinery —
checks plus their `fix_tier_1` fixers — not a bespoke command.**

- Key provisioning is `CHECK_153 indexnow-key-present` + its fixer
  (`public/<key>.txt` + the `[index]` table). Submission (v30.C) is
  `indexnow-submitted` + a fixer that POSTs new URLs. Regression (v30.E)
  is `index-regression` (monitoring, no fixer).
- `fleet fix` is therefore the fleetwide backfill/autopilot, inheriting
  dry-run-by-default, `--apply`, and idempotent re-runs.
- The IndexNow ping is a **remote side effect inside a fixer**, following
  the `CHECK_057` / `CHECK_150` precedent — no new write-surface ADR is
  needed for the *mechanism*; this ADR records the *posture*.
- IndexNow only — the Google Indexing API stays a documented non-goal,
  opt-in behind `[index] google_indexing = true` only if Google ever opens
  it for general URLs.
- The `[index]` table is additive-optional (ADR-0017): absent or
  `indexnow_enabled = false` makes every consumer pass-or-skip; no check,
  fix, or reader may require it.

## Consequences

- **No new CLI surface** for a whole capability; it rides `project`/`fleet`
  `check`/`fix`, and older sites backfill via `fleet fix` rather than a
  per-site command.
- **Provisioning state is a conformance signal** — `indexnow-key-present`
  warns only on a web project that lacks a key, so the fleet's IndexNow
  coverage is visible in the same dashboard as everything else.
- **A fixer now does a remote registrar/engine write for indexing**, which
  is consistent with the existing CF/Vercel fixers but worth stating: a
  `fleet fix --apply` can POST to IndexNow endpoints. Submission is
  ledger-gated (v30.C) so re-runs are no-ops.
- **The Google Indexing arms race is explicitly out**, so we never build
  multi-service-account key rotation; if the operator ever needs it, it is
  a deliberate, risk-acknowledged opt-in, not a default.

## See also

- `docs/prd.md § v30` — phases + design notes
- `docs/indexing-module-plan.md` — the full investigation (APIs, constraints,
  capability table, data model)
- ADR-0017 — additive-optional tables (why an absent `[index]` is valid)
- ADR-0018 — upsert-not-rewrite (how `[index]` is written)
- `src/portfolio/indexnow.py`, `src/portfolio/checks/deploy/check_153_indexnow_key_present.py`
