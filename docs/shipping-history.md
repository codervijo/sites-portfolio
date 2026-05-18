# shipping-history.md — sites/portfolio/

**Archived design rationale for shipped phases.**

Companion to `docs/prd.md` (current spec) and `docs/architecture.md`
(current mechanisms). This document is **append-only** — entries are
moved here when a phase ships, never deleted.

Entry format:

```
## vN.X · <theme> — shipped YYYY-MM-DD
### Problem
### Design rationale
### Resolved open questions
### User journey
### Approval
```

Listed reverse-chronologically (newest first).

> **Entries marked `(TBD — migrate from prd.md)` need content moved
> over from the corresponding detailed-PRD body in the legacy `prd.md`.**

---

## v12.A · Adversarial audit prompt rendering — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2 Phase 4b portion that covered v12.A.)

## v9.E · Canonical-sections TOML-driven SSOT — shipped 2026-05-17

(TBD — minimal; brief rationale only.)

## v9.D · `new bootstrap` growth-hypothesis prompt — shipped 2026-05-17

(TBD.)

## v9.C · `new bootstrap` domain-registration prompt + portfolio.json auto-update — shipped 2026-05-17

(TBD.)

## v9.B · `new bootstrap` interactive operator-input prompts — shipped 2026-05-17

(TBD.)

## v9.A · Canonical AI_AGENTS section schema + conformance check + tier-1 fix — shipped 2026-05-17

(TBD.)

## v8.J · Adversarial audit payload builder — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.I · Wire primary pass into `new research` orchestrator — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.H · Primary interpretive pass runner — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.G · Primary-pass response parser — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.F · Primary-pass prompt rendering — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.E · Primary-pass payload assembly — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.D · Research module v2 — shipped 2026-05-14

(TBD — migrate the full v8.D detailed PRD from prd.md § 8.1: problem
statement, goals, user journey, three-phase functional requirements
narrative (Phase 1 SERP / Phase 2 three-gate / Phase 3 operator
profile), resolved open questions (8.A–8.J), approval marker.)

## v8.B · Multi-keyword cluster mode — absorbed by v8.D 2026-05-14

(One-line note; full rationale archived under v8.D.)

## v8.A · `new research <topic>` core command — absorbed by v8.D 2026-05-14

(One-line note; full rationale archived under v8.D.)

## v7.H · GSC sitemap health + dark-site detection + CF edge-cache — shipped 2026-05-16

(TBD — brief rationale; this phase shipped as a tight cluster around
the donready.xyz sitemap-could-not-be-read incident.)

## v7.G · Tool rename `portfolio` → `lamill` (light) — shipped 2026-05-13

(TBD — entry point alias decision; heavier rename deferred.)

## v7.F · `project diagnose <domain>` — shipped 2026-05-13

(TBD.)

## v7.E · `fleet repos` audit + naming-consistency cluster — shipped 2026-05-12

(TBD.)

## v7.D · `fleet focus` enhancements + age-aware SEO grading — shipped 2026-05-11

(TBD.)

## v7.C · Age tracking (launched + RDAP) — shipped 2026-05-11

(TBD.)

## v7.B · `fleet dashboard` — unified live + SEO + git view — shipped 2026-05-10

(TBD.)

## v7.A · CLI restructure to scope-first — shipped 2026-05-10

(TBD — major restructure aligned across two design sessions; rename
map from old `info status` / `check git` / `focus` etc. into the
new `project` / `fleet` / `new` / `settings` namespaces.)

## v6.G · Fleetwide `project fix --all` — shipped 2026-05-09

(TBD.)

## v6.E · Remediation Tier 2 + co-located fixer architecture — shipped 2026-05-09

(TBD — two pieces: architecture migration from centralized
`fixers.py` / `ai_fixers.py` to per-check co-location; Tier 2 wired
live with Claude subprocess.)

## v6.D · Remediation Tier 1 (second project-dir write surface) — shipped 2026-05-09

(TBD — 16 templated fixers; dry-run by default; `--apply` to write;
idempotent.)

## v6.C · Per-stack rules — submodules + gitignore-build-output — shipped 2026-05-09

(TBD.)

## v6.B · Catalog↔bootstrap reconciliation — shipped 2026-05-09

(TBD — CHECK_013 added; seven day-zero failure gaps closed in
bootstrap output.)

## v6.A · Drift detection (`info drift`) — shipped 2026-05-09

(TBD.)

## v5.I · Content-pipeline checks (CHECK_130–137) — shipped 2026-05-09

(TBD.)

## v5.H · check live/git/seo as real subcommands — shipped 2026-05-09

(TBD.)

## v5.G · focus + SEO cache + menu-trim follow-ups — shipped 2026-05-09

(TBD.)

## v5.F · CLI structure four-group rename — shipped 2026-05-09

(TBD.)

## v5.E · Refactor `project status` onto catalog — shipped 2026-05-09

(TBD.)

## v5.D · `check --seo` (live HTTP + GSC + CrUX) — shipped 2026-05-09

(TBD.)

## v5.C · Stack/deploy/SEO checks (CHECK_025–080) — shipped 2026-05-09

(TBD.)

## v5.B · `check --git` command — shipped 2026-05-09

(TBD.)

## v5.A · Universal check catalog foundation — shipped 2026-05-09

(TBD — absorbed old v6 GSC integration and old v7 stack detection.)

## v4 phases (v4.A–v4.D) — shipped 2026-05-08

(TBD — bundled entry covering the validation-pipeline arc:
shortlist, decide-from-shortlist, widen + ask AI, interactive launcher.)

## v3 phases (v3.A–v3.E) — shipped 2026-05-07 / 2026-05-08

(TBD — bootstrap + SEO baseline + deploy abstraction + validation-mode
suggest + post-grid menu polish.)

## v2 phases (v2.A–v2.B) — shipped 2026-05-04

(TBD — multi-strategy brainstorm + Porkbun availability/pricing.)

## v1 phases (v1.A–v1.F) — shipped 2026-04-28 / 2026-05-04

(TBD — bundled entry covering the skeleton, full git pulse, registrar
consolidation, cleanup migration, NLP skill, parked-detection.)

---

## See also

- `docs/prd.md` — current spec (active phases only).
- `docs/architecture.md` — current mechanisms, schemas, modules.
- `docs/CLAUDE.md` — Claude-specific decisions.
- `AI_AGENTS.md` — agent orientation; canonical versioning rule.
