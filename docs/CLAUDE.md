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
  3. Universal check catalog — `fleet live` (classify domains), `fleet check`
     (cross-repo catalog), `fleet seo` and `project seo` (runtime SEO probe).
     Checks live in `src/portfolio/checks/<category>/check_NNN_<slug>.py`
     with auto-discovery via the registry.

`docs/prd.md` is the canonical spec; `docs/Prompts.md` is the prompt log
(parsed by `portfolio project check`); `docs/CLAUDE.md` is this file.

## Commands

CLI restructured in v7.A to scope-first (`project` / `fleet` / `new` /
`settings`). Old top-level names (`info status`, `check git`, `focus`,
`project fix`, etc.) still work as additive paths in v7.A.1; they'll
become deprecation aliases in v7.A.2.

```bash
# Test
uv run pytest -q

# Per-project status
uv run portfolio project check <domain>

# Per-project remediation
uv run portfolio project fix <domain> --apply --yes

# Cross-repo health
uv run portfolio fleet check

# Where to focus today
uv run portfolio fleet focus

# Cross-source drift report
uv run portfolio fleet drift

# Fleetwide SEO probe
uv run portfolio fleet seo --refresh

# Fleetwide remediation
uv run portfolio fleet fix --apply --yes

# Setup / debug
uv run portfolio settings apikeys list
uv run portfolio settings catalog list

# Bootstrap a new sites/<domain>/ project
uv run portfolio new bootstrap <domain>
```

## Conventions

  - **pnpm-only** for all `sites/*` projects. `package-lock.json` /
    `bun.lockb` / `yarn.lock` are conformance failures. Vite ≥6, Astro ≥5
    (CF Pages bun-detection trap was hit on Vite 5).
  - **Makefile forwards to parent** — every `sites/*` project's Makefile
    delegates to `~/work/projects/builder/`'s `Makefile` via
    `$(MAKE) -C ..` (CHECK_012). Don't duplicate build logic per-site.
  - **Two write surfaces only**: v3 bootstrap (creates new project dirs)
    and v6.D remediation (modifies existing project dirs to fix
    conformance gaps). Everything else is read-only.
  - **`portfolio` repo is excluded from `check --git`** by default
    (`[git] ignore_repos = ["portfolio"]`) — it's a Python CLI tool, not
    a website, so the SEO/stack checks would all skip and create noise.
  - **Four canonical docs** (all must match reality + code per
    `docs/prd.md § Spec discipline`):
    - `docs/prd.md` — WHY / WHAT / WHEN (purpose, problem, target
      user, goals, versions/phases, conformance rules, open questions)
    - `docs/architecture.md` — HOW (project layout, mechanisms,
      schemas, modules, CLI/UX, integrations, stack baselines,
      active implementation plans, risks, tracked refactors)
    - `docs/shipping-history.md` — archived design rationale for
      shipped phases (append-only)
    - `docs/CLAUDE.md` — this file; Claude-specific decisions,
      locked target shapes, deferred decisions, heading hygiene rule
    - Plus `AI_AGENTS.md` (at repo root) — agent orientation +
      canonical `vN.X` versioning rule.

## Canonical docs — when to update which

| If you're changing… | …update this doc | …in the same commit |
|---|---|---|
| A mechanism, schema, or module | `docs/architecture.md` | yes |
| Phase status (planned → in-progress → shipped) | `docs/prd.md` phase row | yes |
| A phase has just shipped | move its design notes from `prd.md` to `docs/shipping-history.md` | yes |
| Goals, target user, conformance rule, open question | `docs/prd.md` | yes |
| A Claude-specific convention or locked target shape | `docs/CLAUDE.md` (this file) | yes |
| Agent-orientation summary or versioning rule | `AI_AGENTS.md` | yes |

**Stale docs are a conformance failure, not a backlog item.** Never let
docs drift "to be updated later" — fix in the same commit as the code
change that made them stale.

## Heading hygiene

**Before adding any section, subsection, or heading to a Markdown
file, output the file's current heading outline first:**

```bash
grep -nE '^#+ ' path/to/file.md
```

Then confirm — in the chat — that the planned new heading's:

1. **Depth** (`#`, `##`, `###`, …) is the intended depth, not
   accidentally one level too shallow.
2. **Label** doesn't collide with existing headings — no duplicate
   `## 1. <title>`, no `### N.X` subsection labels that look like
   `vN.X` phase identifiers.

Only after that confirmation, write.

Applies especially to long-lived docs:
`docs/prd.md`, `AI_AGENTS.md`, `docs/architecture.md`, `docs/CLAUDE.md`.

**Why:** `docs/prd.md` accumulated four detailed-PRD bodies inlined
at `##` depth instead of `###` under a parent `## 8. Detailed PRDs`.
Each one created another `## 1. Problem statement` at the same depth
as the file's top-level `## 1. Purpose`. The drift was invisible in
any single design session — only visible in the aggregate (VS Code
outline view showed a flat column with repeating numbers). The
pre-edit outline ritual catches this at the point of writing, not
at quarterly cleanup time.

## Locked target shapes

Designs aligned but not yet executed. When picked up, no need to re-debate.

### v7.A — CLI restructure to scope-first (`project` / `fleet`) + `settings`

Aligned 2026-05-10 across two design sessions. Replaces the current
mixed-namespace tree with a scope-first model. `project` for ops on
one project; `fleet` for cross-portfolio. `info` group dies (its
members split: per-project status → `project check`; inventory views
→ `fleet info`). `check`-as-noun-with-modes goes away (each mode
becomes its own verb under the appropriate scope). `--all` and
`--domain` flags retire (scope is in the namespace, not the flag).

Setup / debug consolidates under a new `settings` top-level
(catalog, gsc, apikeys). Daily-ops users see four primary namespaces;
"everything else" lives under settings.

Final tree:

```
portfolio
├── project
│   ├── check <name>
│   ├── fix <name>
│   └── seo <name>
├── fleet
│   ├── focus
│   ├── live
│   ├── seo
│   ├── check
│   ├── fix
│   ├── drift
│   └── info             (inventory views — pragmatically grouped)
│       ├── summary      (--verbose replaces old `info list`)
│       ├── expiring
│       └── cleanup
├── new
│   ├── suggest
│   ├── bootstrap
│   └── deploy
└── settings
    ├── catalog
    │   ├── list
    │   ├── describe <id>
    │   └── run <path> <id>
    ├── gsc                  (simplified from auth/list/sync/compare)
    │   ├── auth
    │   └── status           (--refresh folds in old `sync`)
    └── apikeys              (NEW — replaces manual portfolio.env editing)
        ├── list             (names + set/not-set + connectivity tick)
        ├── set <key> <value>   (strict known-list; --force to override)
        └── delete <key>     (confirm; --yes to skip)
```

Rename map: `info status <name>` → `project check <name>`;
`check git --domain X` → `project check X --catalog-only`;
`check seo --domain X` → `project seo X`; `check git` → `fleet check`;
`check live` → `fleet live`; `check seo` → `fleet seo`;
`project fix --all` → `fleet fix`; `focus` → `fleet focus`;
`info summary` → `fleet info summary`; `info list` →
`fleet info summary --verbose`; `info expiring` → `fleet info expiring`;
`info cleanup` → `fleet info cleanup`; `info drift` → `fleet drift`;
`check {catalog,describe,run}` → `settings catalog {list,describe,run}`;
`gsc auth` → `settings gsc auth`; `gsc list/sync/compare` →
`settings gsc status [--refresh]`.

`settings apikeys` design:
  - `list` — shape A (name + set/not-set) plus a connectivity tick
    per provider (✓ valid / ✗ failed / dim if not testable). Tests
    each provider's API on each call (OpenAI models.list, CrUX
    queryRecord, Porkbun ping, CF /user). Adds ~3-5s; the tradeoff
    is worth it for "did I paste the right key?" signal.
  - `set` — strict; only accepts known key names
    (OPENAI_API_KEY, PORKBUN_API_KEY, PORKBUN_SECRET_API_KEY,
    CF_API_TOKEN, CF_ACCOUNT_ID, CRUX_API_KEY). `--force` to
    accept arbitrary names. Atomic write (preserves other lines,
    comments, ordering of portfolio.env).
  - `delete` — confirms by default; `--yes` skips.

Phasing (single phase, all in):
  - **v7.A.1** (additive): new commands stand alongside old; both work
  - **v7.A.2** (deprecate): old paths become deprecation aliases
  - **v7.A.3** (docs + soak): cleanup, mark removal target = v8.A

Triggers to actually execute (none yet):
  - Muscle memory has shifted (you reflexively type the new shape)
  - A new per-project read command needs a home
  - A second contributor onboards
  - 6+ months pass without churn pressure

If none happen: leave it. Action plan in `check git --domain` already
bridges discoverability for the project-check half. `apikeys` is the
one piece that's net-new functionality — could carve as separate
phase if v7.A timing slips.

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
