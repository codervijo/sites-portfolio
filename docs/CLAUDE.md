# CLAUDE.md — sites/portfolio/

Per-project orientation for Claude. Read this first when picking up work
on this repo. Index of decisions, conventions, and deliberate non-features
that aren't obvious from the code or git history.

## Project

`portfolio` is a Python+uv CLI for managing a personal domain portfolio
plus a sibling `sites/<domain>/` workspace. It does three big things:

  1. Domain lifecycle — `domain suggest` (brainstorm + price/availability
     + interactive shortlist + decision aid + register via Porkbun).
  2. Project bootstrap — `bootstrap <domain>` scaffolds a Vite/Astro site
     under `sites/<domain>/` (first project-dir write surface). `deploy
     <domain>` creates the GitHub repo + Cloudflare Pages project.
  3. Universal check catalog — `check --live`, `check --git` (cross-repo),
     `check --seo` (per-domain runtime probe). Checks live in
     `src/portfolio/checks/<category>/check_NNN_<slug>.py` with
     auto-discovery via the registry.

`docs/prd.md` is the canonical spec; `docs/Prompts.md` is the prompt log
(parsed by `portfolio info status`); `docs/CLAUDE.md` is this file.

## Commands

The CLI was reorganized in v5.F into four groups: `focus`, `check`, `new`,
`info`. Old top-level names (`bootstrap`, `summary`, `project status`, …)
still work via deprecation aliases that print a one-line nudge.

```bash
# Test
uv run pytest -q

# Catalog list (descriptions, severities, categories)
uv run portfolio check catalog

# Cross-repo health (default summary; --detail for per-repo breakdown)
uv run portfolio check --git

# Per-domain runtime SEO (HTTP + GSC + CrUX)
uv run portfolio check --seo --only=all

# Bootstrap a new sites/<domain>/ project
uv run portfolio new bootstrap <domain>

# Per-project conformance status
uv run portfolio info status <domain>
```

## Conventions

  - **pnpm-only** for all `sites/*` projects. `package-lock.json` /
    `bun.lockb` / `yarn.lock` are conformance failures. Vite ≥6, Astro ≥5
    (CF Pages bun-detection trap was hit on Vite 5).
  - **Makefile forwards to parent** — every `sites/*` project's Makefile
    delegates to `~/work/projects/builder/`'s `Makefile` via
    `$(MAKE) -C ..` (CHECK_012). Don't duplicate build logic per-site.
  - **Two write surfaces only**: v3 bootstrap (creates new project dirs)
    and v6.C remediation (modifies existing project dirs to fix
    conformance gaps; planned, not yet shipped). Everything else is
    read-only.
  - **`portfolio` repo is excluded from `check --git`** by default
    (`[git] ignore_repos = ["portfolio"]`) — it's a Python CLI tool, not
    a website, so the SEO/stack checks would all skip and create noise.
  - **AI_AGENTS.md (plural)** at root for general AI orientation;
    `docs/CLAUDE.md` for Claude-specific. The two are intentionally
    separate.

## Deferred decisions

Things deliberately *not* shipped — don't re-propose without new context.

### PageSpeed Insights / Lighthouse lab fallback for `check --seo`

CrUX returns `no-data` for personal-portfolio-scale origins (below the
~10k+ monthly Chrome-visits threshold). The empty LCP/INP/CLS columns
on `check --seo` are *expected*, not a tool problem. The footer message
explains this clearly.

Considered: adding a `--lab` flag that calls PageSpeed Insights to run
Lighthouse synthetically against any URL regardless of traffic.

Rejected because:
  - ~15–30s per origin × ~22 domains ≈ 5–10 min per run; makes
    `check --seo` feel heavy.
  - Lab data ≠ field data Google actually ranks on. Synthetic numbers
    would mislead more than help.
  - `check --git`'s static-source SEO category already surfaces what's
    actionable without traffic.

Don't reopen unless: user explicitly asks for synthetic metrics, or a
use-case for them appears (e.g. comparing pre-deploy performance
across staged builds where field data is unavailable by definition).

Decision date: 2026-05-09 (after v5.D shipped).
