# architecture.md — sites/portfolio/

**Canonical "how it's built" doc for `portfolio` / `lamill`.**

Companion to `docs/prd.md` (the WHY / WHAT / WHEN) and
`docs/shipping-history.md` (archived design rationale for shipped phases).

This document is the **single source of truth for current mechanisms,
schemas, modules, and CLI/UX conventions**. Per `prd.md § Spec
discipline`: reality + code + docs must match. If you change a
mechanism or schema in code, update the matching section here in the
same commit.

> **Sections that haven't been filled in yet are marked `(TBD)`.**
> Filling them is tracked under PRD task — content migration from
> the old `prd.md` detailed PRDs is in progress.

## 1. Project layout

(TBD — `src/portfolio/` package structure; `data/` subtrees;
`prompts/` location; `sites/<domain>/` conventions; `tests/` layout.)

## 2. Write surfaces

(TBD — the two-write-surface architectural constraint: `new bootstrap`
and `project fix`. Everything else is read-only by design.)

## 3. Mechanisms

### Check catalog

(TBD — file-per-check, registry, auto-discovery, `CheckResult`
dataclass, `check_NNN_<slug>.py` module-level contract, category
taxonomy.)

### Fix-tier

(TBD — Tier 1 templated fixers via `fix_helpers.py` factories;
Tier 2 Claude subprocess (`claude -p` with restricted tools);
co-located `fix_tier_1` / `fix_tier_2` attributes on each check
module; `fix_registry.py` discovery.)

### Provider walkers

(TBD — Vercel and Cloudflare Pages API walker patterns;
rate-limit handling; per-row error surfacing; cached snapshot
shape under `data/hosting/<date>.json`.)

## 4. Schemas

### Config schemas

(TBD — `portfolio.env` keys list; `sites/<domain>/lamill.toml`
schema (v10.A); `~/.lamill/operator.yaml` (v8.D Phase 3);
`~/.config/portfolio/config.toml`.)

### Snapshot schemas

(TBD — `data/seo/<date>.json`, `data/checks/<date>.json`,
`data/gsc/<date>.json`, `data/serp/<date>/<cluster>.json`,
`data/hosting/<date>.json`. Per-file shape and lifecycle.)

### Data model

(TBD — `Domain`, `CheckResult`, `ParsedVerdict`, `ParsedAudit`,
`HostingRow`, etc. Dataclass field definitions and invariants.)

## 5. CLI / UX design

(TBD — scope-first verb model (`project` / `fleet` / `new` /
`settings`); standard flags (`--json`, `--yes`, `--apply`,
`--refresh`, `--only`); output conventions (rich tables, emoji
status, color); confirmation patterns; destructive-action gates;
help-text conventions.)

## 6. External integrations

(TBD — GSC OAuth flow; CrUX API; Porkbun availability + pricing;
RDAP fallback; Cloudflare API + Pages; Vercel API; SerpAPI;
OpenAI; Anthropic. Auth surfaces, token management, rate limits,
retry policy per integration.)

## 7. Stack baselines

(TBD — Python ≥3.11 + uv for `portfolio` itself; pnpm-only +
Vite ≥6 + Astro ≥5 for `sites/*` projects; Makefile-forwards-to-
parent convention; central builder at `~/work/projects/builder/`;
why `portfolio` is exempt from the central builder.)

## 8. Module index

(TBD — file-by-file: what each `src/portfolio/*.py` does, what its
public API is, what other modules depend on it. Major modules:
`cli.py`, `project.py`, `check.py`, `data.py`, `gsc.py`,
`audit_pass.py`, `interpretive_pass.py`, `audit_payload.py`,
`fix_registry.py`, `fix_helpers.py`, `lamill_toml.py` (v10.A),
`seo_cache.py`, etc.)

## 9. Active implementation plans

Commit-by-commit plans for unshipped phases. Each plan moves to
`docs/shipping-history.md` when its phase ships.

(TBD — populate from prd.md detailed-PRD migration. Current active
phases: v10.A, v10.B, v10.C, v10.D, v11.A, v12.B, v12.C, v12.D,
v12.E, v12.F, v12.G, v13.A, v13.B, v13.C, v14.A, v14.B, v14.C, v14.D.)

## 10. Implementation risks

Technical risks surfaced during phase design. Each moves to
`shipping-history.md` when its phase ships.

(TBD — populate from prd.md.)

## 11. Tracked refactors

Refactors recommended during design but not yet scheduled. Carried
here so they don't get lost.

(TBD — populate from prd.md. Known item: v8.D's "recommended
preamble refactor".)

---

## See also

- `docs/prd.md` — purpose, problem statement, target user,
  versions/phases, conformance rules, open questions.
- `docs/shipping-history.md` — archived design rationale for shipped
  phases.
- `docs/CLAUDE.md` — Claude-specific decisions and conventions.
- `AI_AGENTS.md` — agent orientation; canonical versioning rule.
