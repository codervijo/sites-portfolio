---
project: portfolio
prd_version: 2
project_version: v12.A
status: in-progress
owner: Vijo
last_updated: 2026-05-18
---

# portfolio — PRD

## 1. Purpose

`portfolio` (CLI name `lamill`) is the **inventory + standards enforcer
+ production line** for the `sites/` workspace. As the number of
sibling projects under `sites/` grows, it becomes infeasible to
remember per-project state, deploy quirks, build conventions, or where
each one is in its lifecycle. portfolio is the single place to:

1. **Ask "what is the status of project X?"** and get an answer drawn
   from git, project docs (Prompts.md, prd.md), `data/portfolio.json`,
   live HTTP checks, GSC analytics, and (later) deploy verification.
2. **Detect and flag deviations from sites/* conventions** so the
   workspace stays uniform rather than drifting into N bespoke setups.
   portfolio's status output is a conformance report; gaps are surfaced
   and (from v6.D) optionally fixed.
3. **Manage the domain portfolio itself** — categorize, track
   expirations across multiple registrars (GoDaddy, Namecheap,
   Porkbun), cross-reference with Google Search Console.
4. **Find the right domain to register for any new idea** *(Power 1,
   v2)* — brainstorm SEO-quality candidates from a topic via OpenAI,
   score them, check availability via RDAP. Prevents bad registrations.
5. **Bootstrap a new commercial site to ship-ready state** *(Power 2,
   v3)* — given a registered domain + topic, scaffold the project at
   full conformance: stack (Astro/Vite/etc.) via the central builder,
   SEO baseline (sitemap/robots/OG/JSON-LD/favicon), deploy-target
   abstraction (Cloudflare Pages default, swappable), optional LLM-
   seeded content. The actual scaling lever for the 30-commercial-sites
   goal — turns "I have an idea" into "indexed live site" in under an
   hour.
6. **Validate a niche before committing to a build** *(v8 + v12)* —
   `lamill new validate <topic>` walks a mechanical SERP gate plus an
   LLM interpretive verdict; `--verify` (v12) adds an adversarial audit
   pass against a different model. REVIEW_REQUIRED is a first-class
   verdict when models disagree — visibility over false confidence.

## 2. Goals & non-goals

**Goals**:

- Single CLI surface for status, conformance, drift, and (from v6.D)
  remediation across all `sites/*` projects.
- Multi-registrar consolidation with normalization (GoDaddy, Namecheap,
  Porkbun).
- Skill-friendly JSON outputs for natural-language wrapping (v1.E
  ships the project-status skill).
- Read-only by default; the **two write surfaces** (`new bootstrap`,
  `project fix`) are explicit and dry-run-by-default (ADR-0003).
- Versioning convention canonicalized in `AI_AGENTS.md` and propagated
  to other `sites/*` projects opt-in (`vN.X` two-level, ADR-0004,
  CHECK_013).
- **Standard project scaffolding required across all sites/* projects**
  — `docs/`, `docs/prd.md`, `docs/Prompts.md`, `AI_AGENTS.md`,
  `README.md`, `.gitignore` — produced by `new bootstrap` and enforced
  via the universal check catalog (~85 rules, v5).
- Five-canonical-doc model (ADR-0010) — `docs/prd.md` (this file),
  `docs/architecture.md`, `docs/shipping-history.md`, `docs/decisions/`
  ADRs, `docs/CLAUDE.md`, plus `AI_AGENTS.md` at the root for agents.

**Non-goals (intentionally never)**:

| Item | Why |
|---|---|
| Real SEO analytics (Ahrefs/SEMrush/Moz) | $$ APIs; manual remains best |
| GA4 Data API consumption (per-page metrics, fleet rollup, acquisition/funnel) | Google's GA4 UI does this well for one operator; reading analytics into the CLI duplicates UI without compressing time. *Install enforcement (v18.B) is in scope — that's conformance, not consumption.* |
| Trademark search (USPTO) | manual at purchase time |
| Domain history (Wayback parsing) | niche |
| Social handle availability | different problem domain |
| Wide registrar API auto-sync | dropped — manual CSV exports cover it |
| ~~Live Porkbun pricing API~~ | reinstated 2026-05-02 — buying-side price is a critical decision criterion (≠ owned-domain valuation, which stays out of scope) |
| Multi-tenancy / permissions / public surface | single user; CLI-only |

## 3. Problem statement

**The fleet outgrew the operator.** Across 54 domains at 3 registrars
and 34 sibling `sites/<domain>/` projects, manual fleet management
hits four breakdowns:

1. **State amnesia.** Per-project state (deploy platform, build status,
   last commit, conformance, live status, GSC ranking) lives in N
   different places — no single answer to "what's the status of X?"
2. **Drift between projects.** Without enforcement, every site ends
   up bespoke — different scaffolding, lockfiles, build conventions.
   That kills the "ship a new site in under an hour" goal.
3. **Bad domain registrations.** Picking a domain by gut → over-paying,
   buying brand-poisoned `.com`-taken names, missing keyword-cluster
   opportunities. Costs compound (renewals × N years).
4. **Bad niche bets.** Shipping a site before validating the SERP
   landscape → week+ of work on niches owned by programmatic
   incumbents, or zero-traffic informational queries.

portfolio is the single tool that addresses all four — inventory +
standards + acquisition + validation — for one operator.

## 4. Target user

Sole user: Vijo. No multi-tenancy, no permissions, no public surface.
CLI-only. Daily-driver workflow:

- Domain ideation → `lamill new domain <topic>` (v2/v4 Power 1).
- Niche validation → `lamill new validate <topic>` (v8 + v12).
- Project scaffold → `lamill new bootstrap <domain>` (v3 Power 2).
- Deploy → `lamill new deploy <domain>` (v3.C).
- Daily fleet ops → `lamill fleet focus`, `lamill fleet dashboard`,
  `lamill project diagnose <domain>` (v7).
- Conformance → `lamill project check <domain>`, `lamill project fix
  <domain> --apply` (v5 + v6).

## 5. Spec discipline

**Reality + code + all five canonical doc surfaces must match.**

The five surfaces, by purpose:

| Doc | Holds | Update when |
|---|---|---|
| `docs/prd.md` (this file) | WHY (purpose, problem, target user) + WHAT (goals, conformance rules) + WHEN (versions/phases, open questions) | Goals shift, a new phase is planned/shipped, an open question is resolved, conformance rules change |
| `docs/architecture.md` | HOW (project layout, mechanisms, schemas, modules, CLI/UX, integrations, stack baselines, active implementation plans, risks, tracked refactors) | A schema changes, a module is added/removed/renamed, a mechanism is altered, a new external integration lands |
| `docs/shipping-history.md` | Archived design rationale + resolved open questions for shipped phases (append-only) | A phase ships — move its design notes + resolved opens here |
| `docs/decisions/` (ADRs) | Load-bearing architectural decisions (Nygard format; see ADR-0001 and `decisions/README.md`) | A new load-bearing decision is made or reversed — write an ADR **in the same commit** |
| `docs/CLAUDE.md` | Claude-specific orientation: decisions, locked target shapes, deferred decisions, heading hygiene rule, ADR workflow | A Claude-specific convention changes, a target shape is locked/unlocked, a decision is deferred or revisited |

Plus `AI_AGENTS.md` at the repo root — agent orientation; canonical
versioning rule (per ADR-0004).

**Stale docs are a conformance failure, not a backlog item.** If a
change touches a mechanism or schema, update `architecture.md` in the
same commit. If a phase ships, move its design notes from this file
to `shipping-history.md`. If a new load-bearing decision is made,
write an ADR in `docs/decisions/` in the same commit. Never defer doc
updates.

**Heading hygiene** (per `docs/CLAUDE.md § Heading hygiene` and
CHECK_043): before adding any heading to any long-lived `.md` file,
grep the outline first (`grep -nE '^#+ ' path/to/file.md`) and
confirm the planned new heading's depth + label don't collide. Applies
especially to `prd.md`, `AI_AGENTS.md`, `architecture.md`,
`docs/CLAUDE.md`.

## 6. Versions

Tier-grouped roadmap. Each `### vN` is a major capability tier; each
`#### Phases` row is a shippable slice (`vN.X`). Two-level only —
never `vN.X.Y` (ADR-0004; CHECK_013).

Read/write surface note: portfolio is **read-only** through v2.
**v3** (bootstrap) is the first write surface; **v6.D** (remediation)
is the second. Everything else — `fleet *`, `project check`,
`project diagnose`, `new domain`, `new validate`, `settings *` — is
read-only.

### v1 — project status + multi-registrar inventory ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v1.A | ✅ | Skeleton + repo-isolation gate. `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active). |
| v1.B | ✅ | Full git pulse + Prompts.md + deploy-detect + live. Activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view. |
| v1.C | ✅ | Registrar consolidation. `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (3 date formats; auto-renew yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price · Porkbun rows excluded from value rollups (low-value TLDs). |
| v1.D | ✅ | Cleanup + classification migration (plan.md → portfolio.json). `portfolio cleanup` subcommand · reads raw registrar CSVs + plan.md · writes `data/portfolio.json` (single canonical record per domain: name, registrar, category, expires, created, auto_renew, renewal_price, estimated_value, privacy, transfer_locked, nameservers, forwarding_url, raw passthrough for forensics) · auto-classification rules: Namecheap rows → "Under build", Porkbun rows → "Under build", GoDaddy rows → plan.md category (or warn if uncategorized) · `load_domains()` pivots to read from `portfolio.json` after cleanup · `load_plan()` is removed · plan.md gets a deprecation comment in v1.D; actual file deletion happens in a later cleanup commit · drift output surfaces uncategorized domains as warnings · resolver continues to fuzzy-match against `portfolio.json` keys instead of plan.md. |
| v1.E | ✅ | NLP skill. `~/.claude/skills/project-status/SKILL.md` (global; works from any cwd) — routes natural-language questions like "what's the status of iotnews" → `make run ARGS="project status <name> --json"` → short prose answer (1-line headline + up to 3 contextual bullets). Disambiguation: lists `candidates` and asks the user. Read-only by design. |
| v1.F | ✅ | Parked-detection accuracy. Extend `check.py` `_classify()` with body-content inspection: detect GoDaddy in-line parking (sub-1KB body containing `window.location.href = "/lander"` or similar JS redirect) and reclassify spurious `live-site` → `parked` with reason `js-redirect-to-parking-page` · capture truncated body excerpt in `CheckResult` so future re-classifications run offline against the snapshot · re-run `check --only all` to refresh the 53-domain dataset. |

### v2 — acquisition — domain suggest (Power 1) ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v2.A | ✅ | Multi-strategy brainstorm + score + already-own. `portfolio domain suggest <topic>` interactive subcommand · OpenAI `gpt-5-mini` brainstorm looped through configurable naming strategies (5 default: trendy / dev-technical / benefit-driven / metaphor / abstract-brandable; extensible via config) · per-strategy: ~12 candidates → strict gen rules (≤12 chars, no hyphens, brandable) → SEO-weighted scoring (TLD tier · length · keyword presence · hyphen/digit penalty) → top-5 sorted · `history` deduplication · already-own intersection against `data/portfolio.json` (depends on v1.C) · 7-day caching by topic-hash · `--non-interactive` flag dumps ranked candidates for piping; default is interactive. |
| v2.B | ✅ | Availability + price via Porkbun (RDAP fallback). Porkbun `domain/checkAvailability` API by default if `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` env vars present (returns availability and price in one call) · RDAP fallback when Porkbun keys unset (availability only, no price) · TLD ladder per the SEO tier config: `.com / .ai / .io / .app / .dev / .co` default; `--tlds=` overrides · stop-at-first-available-TLD per name · rate-limited (~3/sec, matching script convention) · per-TLD endpoint cache · `--max-price=$N` filter so premium-priced names get excluded. |

### v3 — bootstrap — ship-ready scaffold (Power 2) ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v3.A | ✅ | Bootstrap — scaffold a new project. `portfolio bootstrap <domain>` typer command with three paths: (1) template (default empty target → minimal Astro or `--stack=vite` React+JSX scaffold); (2) `--from-genai` (target dir + `genai/` subdir exist → copy `genai/*` to project root + CF Pages safety fixes — Vite ≥6 bump, `_redirects` removal, `wrangler.toml` add); (3) `--git-url=<url>` (clone into `genai/` then `--from-genai`). All paths write standard scaffolding (AI_AGENTS with Building/Deployment, docs/prd.md, docs/Prompts.md, README, .gitignore, local Makefile with `BUILDER_PATH=../../builder`) + `git init` + initial commit. `--with-ingester` adds `scripts/ingest.py`. `--topic` injects into AI_AGENTS + PRD. |
| v3.B | ✅ | SEO baseline pack. Meta-tag template (title, description, canonical, OG, Twitter card) injected stack-aware into `index.html` (Vite) and `src/pages/index.astro` (Astro); JSON-LD structured data (Organization + WebSite @id graph); favicon SVG monogram (deterministic color from a 12-color palette, hash-picked per domain); `public/robots.txt`; `public/sitemap.xml` stub. **v3.B follow-up (2026-05-04):** sitemap-generation: Vite path adds `scripts/generate-sitemap.mjs` (post-build dist/-scan, no deps) chained into `build`; Astro path adds `@astrojs/sitemap` integration with `site` URL set. Technical-SEO regression check `src/__tests__/seo.test.js` asserts the baseline. |
| v3.C | ✅ | Deploy abstraction + Cloudflare Pages impl. `DeployTarget` Protocol (`verify_local_config` / `create_github_repo` / `create_project`); `CloudflarePagesDeploy` concrete impl. `portfolio deploy <domain>` CLI: verifies local config (wrangler.jsonc, public/_headers, package.json build script, pnpm-lock.yaml, no bun/npm/yarn lockfiles, .git initialized) → `gh repo create` (idempotent) → POST to `/accounts/{id}/pages/projects` with `build_command="pnpm run build"` and `destination_dir="dist"` set explicitly (avoids the bun-detection trap). `CF_API_TOKEN` (Pages:Edit) + `CF_ACCOUNT_ID` env. `--dry-run` shows planned API calls; `--skip-{verify,repo,pages}` for partial runs. Idempotent throughout. |
| v3.D | ✅ | Validation-mode suggest (vocab anchor + registrar grid + cheap-first score). One-shot LLM vocabulary extraction (12-15 practitioner-register concrete-noun/verb terms, ≤9 chars, no topic-word echo); vocab injected as must-reference anchors. Registrar-grid output: rows = names, columns = TLDs; cells: `✓ $N` / `✗ live` / `✗ park` / `?` / `$N!`. Pick + Why columns recommend a TLD per row. Score reweighted (`.app`/`.dev` tier-9, `.xyz` tier-6, etc.). Auto-register via Porkbun `/domain/create` after pick (one-domain auto-register only; defense-bundle is manual cart URL). |
| v3.E | ✅ | Validation-mode polishing — post-grid menu + porn screen + TLD reference card. Replaces inline pickers with a numbered menu after each grid update (slots 1, 2, 5, 8, q; 3/4/6/7 reserved for v4). 3-layer strict porn screen always-on (local blocklist · OpenAI moderation · gpt-5-mini adjacency/brand-collision). TLD reference card surface (option 8). |

### v4 — validation pipeline + launcher (Power 1 refined) ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v4.A | ✅ | Mark/unmark shortlist + grid alphabetical sort + AI seed-expansion. (1) Grid sort flips from score-desc to alphabetical-by-name. (2) Mark/unmark shortlist with multi-target input (`m N1 N2`, `m alpha beta`, `m 1,3,5`); shortlist persists across menu iterations; shortlist count shown in menu label when nonzero. (3) AI seed-expansion in option 5 — after seed names entered, prompt `Expand with AI to get plurals, near-synonyms, etc.? [Y/n]`; on Y, send seeds + topic + vocab to gpt-5-mini for 12-18 closely-related variants. |
| v4.B | ✅ | Decide from shortlist — guided 6-step decision aid. Menu item 7 activates. Six steps: (1) gpt-5-mini brand-collision check per finalist; (2) USPTO TESS URL print per finalist (manual click-through); (3) gpt-5-mini brand-extensibility per finalist; (4) 5-year cost projection (reg + 4×renewal); (5) phone-test prompt (user says each name out loud, types any that tripped); (6) memory-test prompt (look away 30s, type any finalists they couldn't recall). One-block "Test concerns:" summary then pick prompt. New `src/portfolio/decide.py` module. |
| v4.C | ✅ | Widen search + ask AI. Menu items 3 (ask AI about a name) + 4 (widen search). Ask AI: gpt-5-mini call given topic + vocab + name + question, returns 1-3 sentence explanation; cached by (topic, name, question) hash. Widen: LLM call with existing names as history-dedup + optional user guidance ("shorter", "foreign roots"); returns 12-24 fresh candidates merged into the grid. Both pass through v3.E porn screen. |
| v4.D | ✅ | Interactive launcher (menu). `portfolio` invoked with no subcommand drops into a grouped, rich-rendered menu. Groups: Manage (summary, project status, cleanup, check) · Build (domain suggest, bootstrap, deploy) · Reports (expiring, category, wip, list). Per-command flow: prompt for required positional args first, then `use defaults for everything else? [Y/n]`. After command exits, returns to menu. Implementation: `app(invoke_without_command=True)` with callback running `menu()` from new `src/portfolio/menu.py`. |

### v5 — universal check catalog + check flags ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v5.A | ✅ | Universal check catalog foundation + scaffold/git checks. New `src/portfolio/checks/` package: file-per-check registry with auto-discovery (`check_NNN_<slug>.py` modules each declaring `CHECK_ID`, `CHECK_NAME`, `CATEGORY`, `SEVERITY`, `DESCRIPTION`, `run(repo_path) -> CheckResult`). `CheckResult` dataclass. `~/.config/portfolio/config.toml` loader (repos_dir, github_token, skip_checks). Initial 17 checks: scaffold (CHECK_001-012) + git (CHECK_020-024). Read-only. |
| v5.B | ✅ | `check --git` command. New `--git` flag on `check` subcommand. Runs scaffold + git subset over all sibling repos. Output: summary table (Repo · Score · Fails · Warns) sorted by score ascending; `--detail` for full per-repo breakdown; `--check CHECK_xxx` to run one check across all repos; `--repo <name>` for one repo, all checks. |
| v5.C | ✅ | Stack/deploy/SEO checks + cross-repo aggregate view (CHECK_025–CHECK_080). Extended catalog: docs-quality (CHECK_025-027), git (CHECK_028 last-deploy-date), stack (CHECK_029 has-live-url + CHECK_030-039 pnpm-only lockfile discipline, Vite ≥6 / Astro ≥5, build+dev scripts, tsconfig), deploy (CHECK_050-056), SEO assets (CHECK_060-064), SEO meta (CHECK_070-080). Recategorized CHECK_005-008 from `scaffold` to new `docs` category and CHECK_024 from `git` to new `ci`. `check --git` adds "Most common failures across N repos" block. Config gains `[git] ignore_repos = ["portfolio"]` default. |
| v5.D | ✅ | `check --seo` (live HTTP + GSC + CrUX). New `--seo` flag on `check`. Per-domain runtime probe — separate runner from per-repo registry. Picks live-site/forwarder domains, dedupes bare/www. Live HTTP: HTTPS status, HSTS, `/robots.txt` (must be text/plain), `/sitemap.xml`. GSC probe via existing `gsc.py` OAuth: aggregates clicks/imp/CTR/avg-position across multi-property domains. CrUX probe via `chromeuxreport.googleapis.com/v1/records:queryRecord` (`CRUX_API_KEY`, mobile-only). Web Vitals thresholds (LCP 2.5/4/6s, INP 200/500/1000ms, CLS 0.1/0.25/0.5, position 10/30/50). Sorted by impressions desc. |
| v5.E | ✅ | Refactor `project status` onto the catalog. `project status <name>` drives its conformance section from the registry. 9 hand-rolled legacy rules replaced by `run_checks()` across scaffold + docs + git + ci + stack + deploy + seo categories — every project gets ~50 catalog checks instead of 9. Output shape preserved; rule names migrated to CHECK_* IDs. `has-category` (portfolio.json) + `live-site` (snapshot) kept under legacy names. |
| v5.F | ✅ | Revamp CLI structure — four-group rename. Top-level groups: `focus` (queued v5.G) · `check {--live,--git,--seo}` · `new {suggest,bootstrap,deploy}` · `info {summary,status,expiring,wip,list,category,cleanup}`. Old top-level names keep working via deprecation aliases. `--live` added as the explicit form of legacy default-no-flag mode. Menu rebuilt to 14-item structure. |
| v5.G | ✅ | focus + SEO cache + menu-trim follow-ups. (1) `portfolio focus` shipped: ranks domains by 🔴 site-down · ⚠️ expiring ≤30d · 🟠 indexed-zero-impressions · 🟡 position >20. (2) SEO cache layer: `check seo` persists to `data/seo/<date>.json`; `--refresh` forces re-probe. (3) `check live --domain <one>` one-shot HTTP probe doesn't overwrite the shared snapshot. (4) `info wip` removed; `info category` merged into `info list`. Menu trimmed 14 → 12 items. |
| v5.H | ✅ | `check live/git/seo` as real subcommands. Made `check` symmetric with `new` and `info`. The flag form (`check --live`) kept as deprecation alias. |
| v5.I | ✅ | Content-pipeline checks (hybridautopart pattern). CHECK_130-CHECK_137 (new `content` category): has-seo-dir, seo-pyproject, seo-uv-lock, seo-claude-md, seo-pipeline-prompt, content-plan-json, seo-makefile-pipeline, seo-tests-dir. Auto-skip pattern: every check returns warn-skip when `seo/` is absent. CHECK_130 is the gate. |

### v6 — drift + per-stack + remediation

#### Phases

| # | Status | Feature |
|---|---|---|
| v6.A | ✅ | Drift detection — `info drift`. New `portfolio info drift` subcommand cross-checks four sources of truth (portfolio.json, registrar CSVs, sites/* dirs, GSC properties, latest check snapshot) and surfaces six signals: registered-but-never-bootstrapped, CSV-only domains, expiry mismatch, GSC orphans, deployed-but-flagged-for-deletion, duplicate across registrars. New `src/portfolio/drift.py` module is pure data analysis (no CLI side effects). |
| v6.B | ✅ | Catalog↔bootstrap reconciliation. New CHECK_013 `ai-agents-references-versioning` (warn). Bootstrap output reconciled with catalog: previously, freshly-bootstrapped projects failed CHECK_006 (no docs/CLAUDE.md), CHECK_011 (no .env.example), CHECK_024 (no .github/workflows), CHECK_029 (no homepage in package.json), CHECK_003/004 (heading mismatch), and CHECK_079 (Astro JSON-LD parser miss). All seven gaps closed. New regression test `test_template_path_passes_day_zero_catalog` locks in zero day-zero failures. |
| v6.C | ✅ | Per-stack rules — submodules + gitignore-build-output. CHECK_141 `no-git-submodules` (deploy/error): CF Pages doesn't clone submodules, so gitlinks silently produce broken deploys. CHECK_142 `gitignore-covers-build-output` (stack/warn): extends CHECK_038 — at minimum `dist/` must be in `.gitignore`. Tier 1 fixer appends `dist/`, `build/`, `.next/`, `.astro/` (idempotent). |
| v6.D | ✅ | Remediation Tier 1 (templated; second project-dir write surface). `portfolio project fix <name>` — 16 templated fixers. Dry-run by default; `--apply` to write; `--rule CHECK_xxx` for surgical fixes; `--yes` skips lockfile-deletion confirmations. All fixers idempotent. New `templates.py` + `fixers.py`. Fixable: CHECK_001/002/003/004/005/006/007/008/009/011/012/026/027/032/033/034. Manual-only items printed in plan with one-line reason. **`project` namespace revived** (it was retired in v5.F when its only command was the read-only `status`); now hosts `project fix`. |
| v6.E | ✅ | Remediation Tier 2 — Claude subprocess for content-quality fixes + co-located fixer architecture. (1) Architecture migration: per-check co-location — each check module declares `fix_tier_1` and/or `fix_tier_2`; new `fix_registry.py` discovers them. Old `fixers.py` and `ai_fixers.py` deleted. (2) Tier 2 wired live: `--ai` flag spawns `claude -p` non-interactively in the project dir with `--allowedTools "Read Edit Glob Grep"` and `--max-budget-usd`. Three Tier 2 fixers shipped: CHECK_025 (growth experiments), CHECK_026 (CLAUDE.md content), CHECK_027 (prd.md content). |
| v6.F | ⏳ | own-git-repo guided migration. `portfolio project fix --rule CHECK_020` carved out as its own phase — touches the parent repo (parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit). Explicit confirmation each step touching parent repo. |
| v6.G | ✅ | Fleetwide `project fix --all`. New `--all` flag iterates every fleetwide-eligible project (`repos_dir` minus `ignore_repos` minus domains in 'To be deleted immediately'). Default: dry-run plan + fleet totals; `--apply` writes; single confirm-once prompt. Continue-on-error. Lockfile deletions auto-skipped in fleetwide mode unless `--yes`. |

### v7 — fleet operations layer ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v7.A | ✅ | CLI restructure — scope-first (`project` / `fleet` / `new` / `settings`). Reorganized the CLI surface around scope-first namespaces. New commands: `project check` (replaces `info status`), `project fix`, `project seo` (replaces `check seo --domain`), `fleet focus`/`live`/`seo`/`check`/`fix`/`drift`, `fleet info {summary,expiring,cleanup}`, `settings catalog {list,describe,run}`, `settings gsc {auth,status}`, `settings apikeys {list,set,delete}` (NEW — replaces manual `portfolio.env` editing). Old paths kept as additive aliases. |
| v7.B | ✅ | `fleet dashboard` — unified live + SEO + git view. Single per-domain row joining `data/checks/<date>.json` + `data/seo/<date>.json` + local git state. Worst-of rollup dot leftmost. Sort modes: attention (worst rollup first — default), name, imp, age. |
| v7.C | ✅ | Age tracking — `launched` + `domain_created`. Two new fields on each row in `data/portfolio.json`. `launched` manual via `lamill settings deploy set-launched <domain> <YYYY-MM-DD>`, falls back to first-commit-date inference; `domain_created` via RDAP `registration` event date. `fleet sync --refresh-rdap`. Both surface as columns in `fleet dashboard` (Site age + Domain age). |
| v7.D | ✅ | `fleet focus` enhancements + P4 age-aware SEO grading. Five fixes: (1) variant-aware site-down; (2) platform-aware action text; (3) `--refresh` flag; (4) age-aware SEO signal suppression for sites <90d old with `--include-young` to override; (5) idle (🟡) signal for forwarder/parked. P4 closed the age-awareness loop in `seo_runtime.overall_status` — masks imp + pos cells when site is young. |
| v7.E | ✅ | `fleet repos` audit + naming-consistency cluster + archived state. Read-only audit of every `sites/<domain>/`'s git-layer state. Three new git-category catalog checks: CHECK_040 (git-remote-name-matches-domain), CHECK_041 (dir-matches-portfolio-entry), CHECK_042 (live-final-url-matches-domain). Archived support via `TOMBSTONE.md` marker or portfolio.json category in `{to be deleted immediately, archived, tombstoned}`. |
| v7.F | ✅ | `project diagnose <domain>` — five-layer auto-investigate. Probes DNS / HTTP / TLS / repo / inventory and synthesizes a root cause + suggested fix. Seven heuristics catching real-world patterns: Vercel deployment-not-found, Namecheap parking, intent-vs-actual mismatch, TLS alert 112 on intended platform, no-DNS-at-all, normal live site, forwarder/parked decision. |
| v7.G | ✅ | Tool rename: `portfolio` → `lamill` (light). `[project.scripts]` entry exposes both `lamill` (canonical) and `portfolio` (legacy alias). Python package stays `portfolio` internally. Installed system-wide via `uv tool install --editable`. |
| v7.H | ✅ | GSC sitemap health + dark-site detection + CF edge-cache check (CHECK_057). (1) GSC sitemap health: `probe_gsc` keeps per-sitemap `errors`/`warnings`/`isPending`/`lastDownloaded`; new `gsc_sitemap_health` signal. (2) Dark-site detection from robots.txt: classifies as `dark` when `User-agent: *` carries `Disallow: /` with no overriding `Allow: /`. (3) `CHECK_057 cf-edge-cache-fresh` + tier-1 fix + `settings cloudflare {token,status}`. |

### v8 — SERP research for new projects ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v8.A | ✅ | `new validate <topic>` core command. *(absorbed by v8.D 2026-05-14)* |
| v8.B | ✅ | Multi-keyword cluster mode. *(absorbed by v8.D 2026-05-14)* |
| v8.D | ✅ | Research module v2 — real SERP + three-gate framework + operator profile. Rebuild from AI-only synthesis to SerpAPI primary with synthesis fallback. Phase 1 (SerpAPI fetch + per-query dated snapshots); Phase 2 (three-gate logic — Market / SERP-with-7-classifiers / Moat-interactive-prompt); Phase 3 (operator profile read from `sites/portfolio/lamill.toml [operator]`). Verdict vocabulary: GO / NICHE-DOWN / NO-GO. Schema bumped; old caches archived. |
| v8.E | ✅ | Primary-pass payload assembly. `interpretive_pass.build_payload(cluster, operator_profile)`. Pure data-shaping helper. |
| v8.F | ✅ | Primary-pass prompt rendering. `interpretive_pass.render_primary_prompt(payload, operator_profile)`. Operator-var placeholders substituted; payload JSON in a fenced block. `UnfilledPlaceholderError` raised at render time on drift. |
| v8.G | ✅ | Primary-pass response parser. `interpretive_pass.parse_verdict(markdown)` + `ParsedVerdict` dataclass + `VerdictParseError`. Splits on `### <header>` boundaries. Strict on `verdict` / `confidence` / `reasoning` and canonical token sets; tolerant on optional sections, bullet markers, header case, NICHE-DOWN separator variants. |
| v8.H | ✅ | Primary interpretive pass runner. `interpretive_pass.run_primary_pass(cluster, ...)`. End-to-end build_payload → render → run_claude_text → parse_verdict. Returns `InterpretivePassResult`. |
| v8.I | ✅ | Wire primary pass into `new validate` orchestrator. First user-visible v8.E-series feature. Renders "Interpretive verdict (Claude):" section in human output. Snapshot schema bumped to v2.1. |
| v8.J | ✅ | Adversarial audit payload builder. `audit_pass.build_audit_payload(cluster, *, primary_verdict, operator_profile)` — extends the v8.E primary payload with `primary_response_markdown` reconstructed from the persisted parsed verdict. `_reconstruct_primary_markdown` strips `blind_spot_self_report` by default (anti-anchoring). |

### v9 — bootstrap UX — canonical AI_AGENTS + interactive prompts ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v9.A | ✅ | Canonical AI_AGENTS.md section schema + conformance check + tier-1 fix. Lock the 10-section AI_AGENTS canonical schema: Summary / Audience / ICP / Goals / Tech stack / Building info / Deployment info / Content strategy / Versioning / Conventions (4 operator-input + 6 template-driven). New conformance check `ai-agents-md-has-canonical-sections`; tier-1 fix injects missing sections with `(to be filled in)` placeholders. |
| v9.B | ✅ | `new bootstrap` interactive prompts for operator-input AI_AGENTS sections. Prompts for the 5 operator-input sections (Summary / Audience / ICP / Goals / Content strategy). Defaults to `(to be filled in)` when blank; `--non-interactive` skips all prompts; per-section flags pre-populate. |
| v9.C | ✅ | `new bootstrap` domain-registration prompt + portfolio.json auto-update. Bootstrap asks "Is `<domain>` registered? [Y/n]" + registrar (porkbun / godaddy / namecheap / other) and auto-appends the row to `data/portfolio.json` with conservative placeholders. Closes the "new domain on disk but not in portfolio.json" gap. |
| v9.D | ✅ | `new bootstrap` growth-hypothesis prompt → seeded `docs/growth.md`. Prompts for the initial growth hypothesis (one paragraph) and writes it as the first dated H2 entry in `docs/growth.md`. `--non-interactive` / `--growth-hypothesis "X"` flags for scripted use. |
| v9.E | ✅ | Canonical-sections TOML-driven single source of truth. Refactor v9.A's in-code canonical-sections list to a TOML file. Loader module reads at runtime; conformance check, interactive prompts, and bootstrap template renderer all consume from the loader. |

### v10 — per-site deploy declarations ✅ *(wrapped 2026-05-18; renumbered 2026-05-17, was v9)*

Visible TOML file at each `sites/<domain>/` repo root declaring where
the site deploys. Closes the gap for hosts without canonical configs
(HostGator, WordPress, custom VPS). Scope expanded 2026-05-17 to
include a `[backend]` section for non-JS-rendering server stacks.

The v10 tier shipped across **v10.A-E** (foundation → CLI → auto-write
→ real-fleet validation → drift detection + conformance checks) on
2026-05-18. The originally-planned **v10.F** (HostGator cPanel
integration) was absorbed into v11.A — the unified 3-provider hosting
walker is the more coherent home for inventory. **v10.G** (SFTP deploy
abstraction) was renumbered **v11.B**; the active-hosting-operations
cluster belongs in v11 alongside the read-only walker.

Tier-level design notes moved to `docs/shipping-history.md`. See
`docs/architecture.md § 4 Schemas / § 9 Active implementation plans
/ § 10 Risks` for the technical mechanism.

#### Phases

| # | Status | Feature |
|---|---|---|
| v10.A | ✅ | `lamill.toml` foundation — schema constants (`PLATFORM_VALUES`, `DB_VALUES`, `FRAMEWORK_VALUES`, `BACKEND_HOSTING_VALUES`), dataclasses (`DeployBlock` / `HostingBlock` / `BackendBlock` / `LamillToml`), `load()` (strict-on-read, raises `ParseError`), atomic `write()` (tmpfile + rename, round-trip determinism), `infer_from_existing_configs()` + `detect_platform_signals()` (filesystem-marker classification with ambiguous-case detection). Shipped `4395e1d` → `c9d543b` → `be10787` 2026-05-18. 70 tests. |
| v10.B | ✅ | Operator CLI surfaces — `lamill settings deploy set <name> <platform>` (interactive prompts when stdin is TTY; `--non-interactive` rejects on missing required fields; hostgator/custom walks cpanel + FTP breadcrumbs) + `lamill settings deploy show <name>` (pretty table renderer + `--json`). `set-launched` also moved into the same `settings project` namespace 2026-05-18 for consistency (was `project set-launched` v7.C). Shipped 2026-05-18 across `d28c516` → `890841e` → show-deploy commit. |
| v10.C | ✅ | Auto-write integration — `new bootstrap` writes `lamill.toml` as part of scaffolding (platform priority: `--platform <X>` flag → infer-from-existing-configs → `cf-pages` default; `hostgator/custom` rejected at bootstrap, use `settings deploy set` instead). `fleet repos --add-deploy-declarations [--dry-run/--apply] [--include-ambiguous]` migration sweep walks every `sites/<dir>/`, classifies (unambiguous / ambiguous / manual / already-declared / archived), writes safe cases. Shipped 2026-05-18 across `fd725ff` + migration-sweep commit. v10.D validation phase next — runs this against the real fleet. |
| v10.D | ✅ | **Validation phase** — real-fleet sweep. Run the migration against the actual ~22-domain fleet; review the dry-run plan; `--apply` the unambiguous cases; handle ambiguous + manual-entry cases interactively via `settings deploy set`. End state: every applicable sibling `sites/<domain>/` repo has a valid `lamill.toml` committed. Surfaces bugs / edge cases that only appear against real config files. ~2-3h (mostly running the tools, fixing edge cases that surface). |
| v10.E | ✅ | Drift detection + lamill.toml conformance checks. Three deploy-category checks: `CHECK_058 has-lamill-toml`, `CHECK_059 lamill-toml-valid`, `CHECK_143 deploy-drift`. Drift compares declared platform against a best-effort classification of the live HTTP snapshot (WordPress generator / title / wp-includes paths → hostgator; `*.vercel.app` / `*.pages.dev` / `*.netlify.app` in final URL or redirect chain → that provider). Canonical drift case `iotnews.today` (declared=vercel, classified=hostgator via WP title) fires `fail`. 26 tests. |
| v10.F | ✅ *(absorbed by v11.A-L 2026-05-18)* | HostGator cPanel integration — folded into v11's unified hosting walker cluster (Vercel + CF Pages + CF Workers + HostGator). One `fleet hosting` command replaces two (`fleet hosting` + `fleet hostgator`); single rollup table; operator no longer has to remember which command surfaces which provider. HG-specific walker work lives in v11.D. See v11 below. |
| v10.G | ✅ *(absorbed by v11.M-N 2026-05-18)* | SFTP deploy abstraction — split into v11.M (`new deploy` polymorphic dispatch for CF/Vercel/Workers) + v11.N (UAPI file-upload for `hostgator`/`custom`). Different risk profiles: M reuses v3.C; N adds a third deploy verb surface, gated on ADR-0011 (originally specced as ADR-0009; that slot was already taken). See v11 below. |

### v11 — active hosting layer *(renumbered 2026-05-17, was v10; scope expanded 2026-05-18 to absorb v10.F + v10.G; sub-phases re-split 2026-05-19; v11.A-N ✅ shipped 2026-05-18 → 2026-05-19; tier complete)*

The hosting cluster — read-only inventory across every provider in
the fleet, plus the active deploy verb that operates against those
providers. **All 14 sub-phases shipped** over two days. The walker
cluster (v11.A-L) walks Vercel + Cloudflare Pages + Cloudflare
Workers + HostGator UAPI in parallel and writes
`data/hosting/<date>.json` snapshots. The deploy half (v11.M-N)
adds polymorphic `new deploy` that dispatches by `lamill.toml`
platform — `cf-pages` reuses v3.C; `cf-workers` shells out to
`pnpm run deploy`; `vercel` shells out to `vercel deploy --prod`;
`hostgator` / `custom` upload via cPanel UAPI with stage-then-rename
atomicity (ADR-0011). Tier-level design rationale (problem statement,
goals, non-goals, user journey, all resolved 11.A-T questions,
effort + approval) lives in `docs/shipping-history.md § v11 — active
hosting layer`. Per-phase rationale in the same file under
`## v11.X · ...` sections. Technical mechanisms in
`docs/architecture.md § 2 Write surfaces / § 3 Mechanisms / § 4
Schemas`. Remote-write category in ADR-0011.

Real-fleet hand test 2026-05-19 verified the cluster end-to-end:
walked operator's actual Vercel + CF accounts; surfaced two
post-ship bugs immediately patched (v11.C single-shot pagination,
v11.H new CF Workers walker after `/pages/projects` returned
`result: []`). 11 fleet rows populate against the live API.

The original 2-phase split (v11.A read-only + v11.B deploy) bundled
14 commits under v11.A — much chunkier than the v3 / v5 / v6 / v9
norm of 1-3 commits per sub-phase. Re-split 2026-05-19 into 14
granular phases (then 15 after v11.H insertion); commits `139fb63`
(apikeys plumbing) and `1b59e85` (`HostingRow` dataclass + constants)
stay correctly labeled `v11.A` and roll up as the foundation phase.

#### Phases

| # | Status | Feature |
|---|---|---|
| v11.A | ✅ | Foundation — `apikeys` plumbing (`VERCEL_TOKEN` + `HOSTGATOR_TOKEN_GATOR3164` + `HOSTGATOR_TOKEN_GATOR4216` known-keys + `_probe_vercel()` / `_probe_hostgator()` connectivity probes) + `HostingRow` dataclass + constants (`PROVIDERS`, `RECENT_DAYS=30`, `STALE_DAYS=90`, `MAX_DEPLOY_LOOKBACK=10`). Shipped `139fb63` + `1b59e85` 2026-05-18. 25 new tests (14 apikeys + 11 hosting). |
| v11.B | ✅ | Vercel walker — `walk_vercel(token, fleet_domains, *, only_domain)` paginates `/v9/projects`, extracts `targets.production.alias` custom domains, bare-host-normalizes per 11.E, matches against fleet_domains, walks deploy history via `/v6/deployments` up to `MAX_DEPLOY_LOOKBACK`, classifies states (READY=success / ERROR-CANCELED=failure / BUILDING-INITIALIZING-QUEUED=in-flight per 11.D), emits `HostingRow`s. `VercelAuthError` raised on 401 (orchestrator skips walker per 11.H); per-project failures attach to row `error`. 25 tests. |
| v11.C | ✅ | Cloudflare Pages walker — `walk_cf_pages(api_token, account_id, fleet_domains, *, only_domain)`. Mirrors v11.B's contract against CF Pages API (`/accounts/{id}/pages/projects` + `/.../deployments`). Reuses `CF_API_TOKEN` / `CF_ACCOUNT_ID`. CF-specific: `latest_stage.{name,status}` deploy classification — SUCCESS only when `(deploy, success)`; FAILURE when `stage.status==failure` at any stage; everything else IN_PROGRESS. `CFPagesAuthError` for 401 / empty inputs; `CFPagesWalkError` for 5xx / envelope `success=false` / non-JSON. 25 tests. |
| v11.D | ✅ | HostGator walker — `walk_hostgator(token, account_id, fleet_domains, *, only_domain)`. cPanel UAPI: `DomainInfo/list_domains` (main + addon + parked + sub) with `documentroot` extraction, `Quota/get_quota_info` for account-level `disk_used_mb`, `WordPressManager/list_installations` for `wp_version` + `install_path` (404-tolerant — WPM plugin isn't on every cPanel). Custom `cpanel <user>:<token>` auth scheme. Tolerant of both modern (dict) and legacy (string) addon-domain entry shapes. `HostGatorAuthError` on 401 / empty inputs; `HostGatorWalkError` on `list_domains` 5xx + UAPI status=0. Closes the v10.F use case. 16 tests. |
| v11.E | ✅ | Orchestrator + match logic — `run_hosting(fleet_domains, *, only_domain) -> HostingResult`. ThreadPoolExecutor fan-out across Vercel + CF Pages + N per-account HG walkers. Reads tokens from `apikeys.get_key`; pre-checks each provider's required keys and records skip-reasons (`HostingResult.skipped`) when missing. Catches `*AuthError` / `*WalkError` per walker and records the failure without crashing the run. `_flag_provider_conflicts` post-pass sets `provider_conflict=True` on every row whose domain is matched by ≥2 distinct providers (resolution 11.F — two-row drift surface). 15 tests. |
| v11.F | ✅ | Snapshot cache — `src/portfolio/hosting_cache.py` mirroring `seo_cache.py`. `save_snapshot(HostingResult)` writes `data/hosting/<UTC-today>.json` (rows + skipped + fetched_at); `list_snapshots()` / `latest_snapshot()` / `load_snapshot()` / `result_from_snapshot()` / `is_stale(path, max_age_hours=24)`. Forward-compat — unknown row keys dropped on load so a newer HostingRow field doesn't break older snapshots. One file per UTC date, overwrites same-day. Git-tracked, kept forever (11.I). 14 tests. |
| v11.G | ✅ | CLI shell — `lamill fleet hosting` Typer command + `--refresh` / `--only DOMAIN` / `--provider {vercel\|cloudflare-pages\|hostgator}` / `--json` flags. Cache-eligibility: re-use latest snapshot if fresh (<24h) unless `--refresh` or `--only` is set; fleet-wide walks persist; single-domain probes don't overwrite the fleet snapshot. `--provider` validated against `PROVIDERS` (exit 2 on unknown). Minimal table renderer in place — v11.H upgrades with status emoji + walker error footers. 11 tests via Typer's CliRunner. |
| v11.H | ✅ | Cloudflare Workers walker — `walk_cf_workers(token, account_id, fleet_domains, *, only_domain)`. Net-new phase inserted 2026-05-19 after the real-fleet hand test surfaced that operator's CF sites are deployed as **Workers (with static assets)**, not legacy Pages — `/accounts/{id}/pages/projects` returned `result: []` for these accounts. Hits `/workers/scripts` (script metadata + `modified_on`) and `/workers/domains` (hostname → script mapping — the matching layer). No per-script deploy-history walk: Workers deploys are atomic (success or wrangler-publish error caught locally), so `consecutive_failures` stays `0` and `last_successful_deploy_at == latest_deploy_at == script.modified_on`. Filters to `environment="production"`. Reuses `CF_API_TOKEN` / `CF_ACCOUNT_ID`. New `PROVIDER_CF_WORKERS = "cloudflare-workers"`; orchestrator (v11.E) calls both `walk_cf_pages` AND `walk_cf_workers` against the same CF account. Hand-test verification: 6 CF Workers rows populate against operator's real fleet (airsucks, cricketfansite, donready, isitholiday, kwizicle, voltloop). 19 tests. |
| v11.I | ✅ *(renumbered 2026-05-19 — was v11.H)* | Table renderer + walker error surfaces. `hosting.hosting_status_emoji(row)` cascade: provider=None → `—`; provider_conflict → `🤐`; consecutive_failures ≥ MAX_DEPLOY_LOOKBACK → `✗`; else age-from-last-success (<30d `✓`, <90d `⚠`, ≥90d `💤`, None `—`). `hosting.hosting_footer_summary()` one-line tally below the table. Conditional `HG-extra` column (only present when ≥1 HG row). Filter-empty distinction — when `--provider X` returns 0 but pre-filter had N>0, show the breakdown. Closed bugs 2/3/4 from the 2026-05-19 hand test. 28 new tests (20 emoji/footer/counts helpers + 8 CLI). |
| v11.J | ✅ *(renumbered 2026-05-19 — was v11.I)* | `--apply-declarations` writer — `apply_hg_declarations(rows, *, dry_run, sites_root, plan)` data-layer function + `fleet hosting --apply-declarations [--apply]` CLI flag. For HG rows from the walker, writes `lamill.toml` via v10.A's `lamill_toml.write()` when the local `sites/<domain>/` exists, the site isn't archived (TOMBSTONE.md / portfolio.json category), and no `lamill.toml` already exists. Mirrors v10.C's migration-sweep dry-run/apply convention. Scoped "missing-only" per resolution 11.N — never overwrites. Render breaks down per-action (would_write / wrote / skipped_no_site_dir / skipped_already / skipped_archived) plus footer + `--apply` next-step hint. 15 tests. |
| v11.K | ✅ *(renumbered 2026-05-19 — was v11.J)* | `fleet dashboard` + `project diagnose` integration. Dashboard gains Host (🟢/🟡/🔴/—) + Prov (VC/CFP/CFW/HG, `+` suffix on conflict) columns plus a `host=` entry in the freshness footer; rollup widens to 4 dimensions. Diagnose gains a sixth `HostingLayer` (snapshot-read only — never re-walks); renders provider / project_slug / hg_account_id / status / last_ok date / failures / disk / WP per matching row; surfaces 🤐 conflict on multi-row drift. Both reuse v11.F's `hosting_cache.result_from_snapshot()`. New `_host_dot()` cascade mirrors `hosting_status_emoji` but maps to the dashboard's 🟢/🟡/🔴/— vocabulary. 19 tests. |
| v11.L | ✅ *(renumbered 2026-05-19 — was v11.K)* | Docs sync closing the v11.A-K read-only walker cluster. Per-phase entries for v11.I (renderer upgrade), v11.J (`--apply-declarations` writer), v11.K (dashboard + diagnose integrations) added to `shipping-history.md`. v11.D entry expanded with post-ship-fix notes (`42bb98b` HG auth username decoupling + `d3bae51` megabytes_used / conflict-detection / install_path). v11 tier-level design notes deferred to v11.U (full tier-level migration once v11.M-N also ship). Operator hand-test verified all integrations 2026-05-19 (dashboard `HG+` conflict flag, diagnose `🤐 conflict` rows for hybridautopart, diagnose `provider=hostgator` for declared-vercel iotnews.today). |
| v11.M | ✅ | `new deploy` polymorphic dispatch — reads `lamill.toml`, dispatches `cf-pages` → existing v3.C `CloudflarePagesDeploy` (extracted into private `_deploy_cf_pages_v3c()`); `cf-workers` → `deploy_cf_workers_via_shell()` which runs `pnpm run deploy` in the project dir (delegates to wrangler — replicating the assets-upload pipeline against raw HTTP is non-trivial maintenance burden); `vercel` → `deploy_vercel_via_shell()` which runs `vercel deploy --prod`; `hostgator` / `custom` → v11.N placeholder (until that ships); `netlify` / `github-pages` → "not implemented yet" with a clear hint; `none` → reject with `set-deploy` hint; missing `lamill.toml` → assumes `cf-pages` (legacy default) with a notice. `--dry-run` propagates to every branch. Shell helpers use a `runner=` injection seam for tests (no real subprocesses). 22 new tests (8 shell-helper + 14 CLI dispatcher). |
| v11.N | ✅ | UAPI file-upload deploy for `hostgator` / `custom`. Adds `deploy_source: str = "dist/"` to `HostingBlock` in `lamill_toml.py` (operator-configurable per site). New `hosting.py` helpers — `_hg_upload_file` (multipart POST to `Fileman/upload_files`), `_hg_mkdir`, `_hg_rename`, `_hg_delete_dir` (all via existing `_call_hg_uapi` for GETs). Orchestrator `deploy_hg_files(row, *, lamill_toml, token, cpanel_user, sites_root, dry_run, client) -> HgDeployRow` is single-row by design (ADR-0011's per-site allowlist). Stage-then-rename atomicity: mkdir `<path>.next/` → upload all files (lazy subdir mkdirs) → rename current to `.prev/` → rename `.next/` to current → delete `.prev/`. Rollback on swap failure: rename `.prev/` back to current so prod stays up. Action vocabulary mirrors `HgApplyRow`: `would_deploy` / `deployed` / `skipped_wp` / `skipped_no_source` / `skipped_no_path` / `failed`. WP-skip when `wp_version` set on the snapshot row (resolution 11.R). CLI wired in `cli.py::_deploy_hostgator_v11n` — reads token via `apikeys.get_key("HOSTGATOR_TOKEN_<account>")`, cpanel_user via `apikeys.hg_user_for_account`, snapshot via `hosting_cache.latest_snapshot()`; new `--apply` flag flips dry-run-default → push. Third deploy verb surface; gated on **ADR-0011** (PRD originally referenced ADR-0009 but that slot was already taken; ADR-0011 establishes remote-host writes as a separate category from ADR-0003's local-FS scope). 35 new tests (4 lamill_toml `deploy_source` + 31 `test_hosting_deploy.py` + ~6 CLI integration in `test_new_deploy_dispatch.py`). |
| v11.U | ✅ | Docs sync closing v11 tier. architecture.md adds active-deploy-verb mechanism section + `HgDeployRow` schema + `deploy_source` field; CLAUDE.md + AI_AGENTS.md qualify "two write surfaces" as ADR-0003 local-FS scope (+ ADR-0011 remote-host pointer); per-phase v11.M + v11.N entries added to shipping-history.md; full v11 tier-level design block migrated from prd.md → shipping-history.md following the v10 wrap pattern; v10.G row's stale "ADR-0009" reference corrected to ADR-0011. Tier closed (read-only walker v11.A-L + active deploy v11.M-N + tier doc-sync v11.U = 15 sub-phases total). |


### v12 — adversarial audit pass + reconciliation *(new 2026-05-17 PM)*

Continuation of v8's research-module interpretive layer. GPT-4o
adversarial audit pass against `prompts/adversarial_audit_v1.md`,
`REVIEW_REQUIRED` first-class verdict when the two models disagree,
`--verify` opt-in flag, cost ledger + granular cache invalidation.
v8.E-I shipped the primary interpretive pass; v8.J shipped the audit
payload builder; v12.A onward picks up the audit arc. **See
`docs/architecture.md § 3 Mechanisms (Research module) / § 4 Schemas
(research-cluster-v2.1) / § 9 Active implementation plans / § 10
Risks` for the technical design.**

#### Phases

| # | Status | Feature |
|---|---|---|
| v12.A | ✅ | Adversarial audit prompt rendering. `audit_pass.render_audit_prompt(payload)` — loads `prompts/adversarial_audit_v1.md`, appends the audit payload JSON (built by v8.J) in a fenced block. Parallel to v8.F's `render_primary_prompt`. Renderer runs `render_prompt()` anyway as drift protection. 12 tests. |
| v12.B | ✅ | Adversarial audit response parser. `audit_pass.parse_audit(markdown) → ParsedAudit` + `AuditParseError`. Different schema from `parse_verdict`: required `### agreement_level` ∈ {full, partial, disagree}, `### confidence`, `### specific_concerns` (≥1 bullet). Optional `### counter_verdict` (only on `disagree`, split into `counter_verdict_token` + `counter_verdict_reasoning`), `### audit_self_check`. Same tolerances as parse_verdict — reuses `_split_sections` / `_parse_bullets` / `_normalize_verdict_token`. 24 tests. |
| v12.C | ✅ | Adversarial audit pass runner. `audit_pass.run_audit_pass(cluster, *, primary_verdict, operator_profile, model, timeout_s, openai_caller, api_key) → AuditPassResult`. Orchestrates build_audit_payload → render_audit_prompt → OpenAI Responses-API call → parse_audit + cost computation. Default model `gpt-4o`, override via `model=` (CLI `--audit-model` wiring is v12.E). `AuditPassError` wraps HTTP/transport/parse failures. Per-1M-token pricing table covers `gpt-4o` / `gpt-4o-mini` / `gpt-4-turbo` / `gpt-4.1` plus dated-alias prefix match; unknown models record cost=0 rather than crash. `openai_caller=` injection seam for tests. 19 tests. |
| v12.D | ✅ | Reconciliation + REVIEW_REQUIRED first-class verdict. New `reconciliation.py` module: pure logic, no I/O. `reconcile(primary, audit) → Reconciliation`. Full → primary verdict + confidence preserved, no caveats. Partial → primary verdict, confidence downgraded one notch (HIGH→MEDIUM→LOW→LOW saturates), caveats = audit.specific_concerns. Disagree → `REVIEW_REQUIRED` (new fourth verdict token), confidence LOW, caveats surfaced. Intentionally NO auto-resolution per the human-tiebreaker principle. `requires_review` convenience property. Primary + audit dataclasses preserved on the result for the v12.E renderer to show side-by-side. 20 tests. |
| v12.E | ✅ | CLI `--verify` flag + `--audit-model` override (default `gpt-4o`) wired into `new validate` orchestrator. New `_run_audit_pass_and_reconcile()` helper runs after primary pass; new `_render_reconciliation_block()` renders below the primary block (full/partial/disagree shapes; REVIEW_REQUIRED in magenta to distinguish from red NO-GO). Same-model rejection: errors when `--audit-model X` matches the primary's `model_id`. Cache-aware: `from_cache + audit` short-circuits the audit on subsequent runs. Persists `audit` + `audit_pass_meta` + `reconciliation` blocks into the cluster snapshot. 17 tests. |
| v12.F | ✅ | Polish — cost ledger + `verify_by_default` + granular cache invalidation. (a) `costs` block on the cluster snapshot — `{primary_usd, audit_usd, total_usd, currency}` — populated idempotently by `_update_cost_summary(payload)` after each pass writes its meta. Render-footer shows breakdown when both passes contributed; omitted on zero-cost / old snapshots. (b) `verify_by_default` field on `OperatorProfile` (loaded from `lamill.toml [operator]`); new `--no-verify` CLI flag overrides for a single run. `effective_verify = (verify or profile.verify_by_default) and not no_verify`. (c) New `--invalidate {none, interpretive, audit, all}` CLI flag; granular per-pass cache short-circuit on a cached cluster. `--no-cache` (boolean) still bypasses the SerpAPI cluster cache wholesale. 30 tests. |
| v12.G | ✅ | Docs sync — closes v12 tier. Migrated v12 tier-level design notes (problem, goals, non-goals, user journey, resolved 12.A-J open questions, effort+approval) from `prd.md` to `docs/shipping-history.md § v12` following the v10 + v11 wrap pattern. Added per-phase entries in `shipping-history.md` for v12.A (fleshed out from placeholder) and v12.B/C/D/E/F (new). Updated `architecture.md § 3 Mechanisms (Research module)` with the v12.A-G end-state (cost notes, `--invalidate` semantics, REVIEW_REQUIRED dispatch, audit-failure semantics). Rewrote `architecture.md § 4 Schemas` cluster-snapshot block to reflect the actual field shape that shipped (`primary_verdict` + `primary_pass_meta` + `audit` + `audit_pass_meta` + `reconciliation` + `costs`) — replaced the v2.1 prediction with the as-shipped additive schema. Added `lamill new validate --verify` capability line to `AI_AGENTS.md § Current capabilities`. Doc-only. |

*Tier-level design notes (problem statement, goals, non-goals, user
journey scenarios, resolved 12.A-J open questions, effort, approval)
migrated to `docs/shipping-history.md § v12 — adversarial audit pass
+ reconciliation` on 2026-05-19 as part of v12.G — same pattern as
v10 + v11 wraps.*
v8.D shipped 2026-05-15; v8.E-J shipped 2026-05-16/17 (full primary
interpretive pass + audit payload builder); v12.A shipped 2026-05-17.

### v13 — per-project GSC diagnostics *(retheme 2026-05-20; was "analytical roll-ups"; v13.A absorbed by v16.D (fleet rollup; was --trend pre-v16-reshape 2026-05-20); old v13.B `project list` roll-up + draft GSC-ownership-conformance retheme both dropped 2026-05-20; old v13.C moved to v15.F)*

Diagnostics drill-down for `lamill project seo <domain>`. When
`fleet focus` flags "GSC: sitemap parse errors (4)" or "Stale CF
edge cache" for a site, today there's no command to see *what
specifically* is broken — operator must open the GSC web UI.
v13 closes that loop: `project seo <domain>` becomes a one-shot
diagnostics view by default (no flag), itemizing sitemap parse
errors, manual actions, mobile usability, and per-URL coverage
failures with actionable hints.

This is the **diagnostics** angle on `project seo`. Distinct from
v16's **analytics** angle (impressions / clicks / position /
trend / opportunities — what's working). Both live on the same
command; v13's content is the new no-flag default, v16's
content is composed in via section flags (`--queries`, `--pages`,
`--trend`, …).

Behavior change: today's `project seo <domain>` renders only a
1-row 28-day aggregate. After v13.B, the aggregate stays as a
header line above the new diagnostics block. Backwards-
incompatible for any consumer that scraped the 1-row output —
but scripts that scraped the 1-row output will need to adapt (a future `--json` mode would be a clean answer; not in v16 scope).

**Kickoff gate.** Before starting `v13.B`, re-validate the plan
against existing GSC infrastructure (auth scope, cache shape) +
what `fleet focus`'s existing sitemap-error detector reports
(don't duplicate; rendering should be consistent across the two
surfaces).

#### Phases

| # | Status | Feature |
|---|---|---|
| v13.A | ✅ *(absorbed by v16.D 2026-05-19; v16.D subsequently reshaped 2026-05-20 from `--trend` section flag to fleet rollup)* | GSC trend correlation — the persisted `data/gsc/` snapshots + w/w delta computation feed into v16.D's fleet-aggregated `W/w Δimp` column on `fleet dashboard`. Per-property trend rendering dropped in v16's 2026-05-20 reshape (GSC UI does single-property trend well). |
| v13.B | ✅ | Per-project GSC diagnostics shipped as the new `project seo <domain>` default. New module `src/portfolio/project_seo_diagnostics.py` — `ProjectSeoDiagnostics` dataclass + `build_diagnostics(domain, *, top_n=10)` orchestrator + `fetch_sitemap_details()` (GSC Sitemaps API per-sitemap status/errors/warnings/last-fetch) + `fetch_coverage_details()` (top-N URLs from live sitemap → URL Inspection API per URL via existing `gsc_recrawl.inspect_one_url`). Hardcoded `_COVERAGE_HINTS` mapping by coverage_state ({crawled_not_indexed, discovered_not_indexed, not_found_404, redirect_error, server_error, blocked_by_robots, soft_404}) — deterministic, no LLM cost. Sitemap-error hints reference `project fix --apply` for CF-cache clearing. New per-domain cache `src/portfolio/gsc_detail_cache.py` writing `data/gsc/<domain>/<UTC-today>.json` (24h TTL, mirrors `hosting_cache` shape with per-domain subdirs). Manual actions + security issues NOT shipped — no public GSC API; mobile usability folded inline with per-URL coverage detail (from `urlInspection.mobileUsabilityResult`). Render block `_render_project_seo_diagnostics()` in `cli.py` — sitemap status cascade (OK / WARN / PENDING / ERROR) with glyph+color; coverage rows with truncate-middle URL formatting; hints with severity-colored bullets; supports both dataclass and dict-from-cache shapes. 33 tests including consistency predicate test (focus's sitemap-error detector and v13.B's per-sitemap ERROR status fire on the same condition). |

#### Design notes

**Sample output.**

```text
$ lamill project seo homeloom.app

  Property: https://homeloom.app/  ·  Verified ✓  ·  Last fetch: 2026-05-19
  28-day totals: 466 imp · 12 clicks · 2.6% CTR · pos 16.5

  📋 Sitemaps (3 submitted)
    ✓ /sitemap.xml          OK     · 47 URLs · 47 indexed · fetched 1d ago
    ✗ /sitemap-pages.xml    ERROR  · "Unparseable XML at line 14" · last OK 12d ago
    ⚠ /sitemap-blog.xml     WARN   · 12 URLs · 8 indexed · 4 crawled-not-indexed

  🚨 Manual actions: none
  📱 Mobile usability: 47 of 47 URLs pass

  📊 Coverage (47 of 51 submitted URLs indexed — 92%)
    ✗ /about                crawled-not-indexed       (last crawled 3d ago)
    ✗ /pricing              discovered-not-indexed
    ✗ /docs/old-guide       404-not-found
    ✗ /api/v1               redirect-error

  💡 Hints
    · /sitemap-pages.xml parse error → re-deploy with valid XML; current
      build is probably serving a stale prerender. Run
      `lamill project fix homeloom.app --apply` to clear CF edge cache.
    · /about crawled-not-indexed → likely thin content; expand to ≥300
      words or remove from sitemap.

  Run with --queries · --pages · --trend · --opportunities for analytics (v16)
```

**Why no flag.** The operator wants diagnostics surfaced
unconditionally when running `project seo <domain>`. Hiding them
behind a `--diagnose` flag would defeat the workflow — `fleet
focus` flags a site, operator runs `project seo <site>`,
diagnostics must be there. Flag-gating would be one more thing to
remember.

**Relationship to other GSC tiers.**
| Tier | Angle | Surface |
|---|---|---|
| v5.D | Runtime live SEO probe | `project seo` 1-row aggregate (today) |
| **v13** | **Diagnostics (what's broken)** | **`project seo` default block** |
| v16.C | Per-URL index conformance (binary check) | `project check`, `project seo` |
| v16.D | Fleet-level GSC rollup (coverage / crawl errors / opportunity counts) | `fleet dashboard` + `fleet seo --detail` |
| v23 | Fleet-level sitemap status | `fleet seo` |

Some overlap with v16.C (URL Inspection coverage) and v23.B (Sitemaps
API). The kickoff gate validates that v16.C / v23.B aren't
prematurely committing to the same Sitemaps API wrapper — v13.B
ships first; v16.C / v23.B reuse what lands here.

**Open questions** (resolved at v13.B kickoff):
| # | Question |
|---|---|
| 13.A | Cap on per-URL coverage detail — top 10 / 25 / all submitted URLs? Default 10 (matches v16.C's planned default). |
| 13.B | Hints — hardcoded mapping by error type vs LLM-generated per finding? Hardcoded first (deterministic, no LLM cost); LLM-generated could be a v13.B+ polish. |
| 13.C | Domain has no GSC property — show "not registered" hint + suggest manual setup vs error out? Show hint; defer auto-registration to a future tier (the old v13 GSC-ownership theme is parked for revisit). |
| 13.D | `fleet focus` ↔ `project seo` consistency — when focus says "GSC: sitemap parse errors (4)", the diagnostics block should show those exact 4 errors. Wire the focus detector to the same sitemap-API call (or shared cache) so the counts match. |

### v14 — CLI rethink after drift *(new 2026-05-20)*

The v7.A scope-first design locked the CLI shape on 2026-05-10.
v8-v13 added nodes opportunistically without re-validating against
that design. v14 is the audit + re-alignment pass — not a re-write,
a deliberate re-validation of which nodes earn their slot, which
need to move, and which can fold into a peer.

**Kickoff gate.** `v14.A` planning catalogs the drift, locks the
target tree, and decides the cutover style before any code moves.

#### Phases

| # | Status | Feature |
|---|---|---|
| v14.A | ✅ | **Kickoff planning.** Locked the target CLI tree from the 2026-05-20 design pass. Resolved still-open items: (a) verb trim under `settings deploy` — `set`/`show` (drop the redundant `-deploy` suffix), (b) `set-launched` stays under `settings deploy` despite the mild lifecycle-vs-deploy semantic mismatch (revisit if a 2nd lifecycle verb appears — then split into `settings lifecycle`), (c) **hard cutover** — no deprecation aliases (operator's own tool, no third-party consumers, daily-driver muscle memory will adjust in days). See `#### Design notes` for the locked tree and the migration map. |
| v14.B | ✅ | **Apply renames + namespace moves (hard cutover).** Wired the locked target tree into `cli.py` — `new suggest`→`new domain`, `new research`→`new validate`, fold `fleet info summary`/`expiring` into flags on `fleet domains`, rename `fleet info cleanup`→`fleet sync` (promoted out of `info` since it writes), delete the `fleet info` typer, rename `settings project`→`settings deploy`, trim its verbs to `set`/`show`/`set-launched`. No deprecation aliases — old paths return typer's standard "no such command" error. Full code-side sweep: `cli.py` + `menu.py` (CmdSpec entries + group preamble) + every test referencing an old command path + `project_deploy.py` / `bootstrap.py` / `diagnose.py` + check messages (CHECK_058 / CHECK_143) — 28 files touched. Suite stayed at 2251 / 1. |
| v14.C | ✅ | **Docs sync.** Rewrote `architecture.md § Projected CLI surface` with the v14.B-shipped tree + planned-by-phase annotations. Marked the v7.A locked-target-shape section in `CLAUDE.md` as superseded (preserved as archeology). Updated `AI_AGENTS.md` capability lines + usage examples. Migrated v14 design notes from `prd.md` to `shipping-history.md § v14`. Phase-table rows in `prd.md` updated to reflect new names where they describe planned/active work; historical entries (v7.A, v8.A, v10.B) annotated rather than rewritten. Doc-only. |

*Tier-level design notes (locked target tree, migration map, deliberate keeps, parked items, resolved open questions) migrated to `docs/shipping-history.md § v14 — CLI rethink after drift` 2026-05-20 as part of v14.C — same pattern as v10 + v11 + v12 wraps.*

### v15 — deploy verification + DNS/translation automation ✅ *(renumbered 2026-05-17 PM; deprioritized; absorbed v13.C 2026-05-20 then dropped same day; renumbered 2026-05-20, was v14; v15.F LLM content seeding dropped 2026-05-20 per `§ 2 Non-goals` audit — automating content bypasses the operator's scarce-hours scaling lever; new v15.B inserted 2026-05-20 for `project hosting` CLI symmetry, bumped v15.B-E → v15.C-F; **v15.A-F tier complete 2026-05-20**; **v15.G + v15.H + v15.I + v15.J added + shipped 2026-05-20** — bootstrap stack-translation + `new deploy` end-to-end automation via Pages-API per ADR-0012 and Astro-only stack policy per ADR-0013; **v15.K-R added + shipped 2026-05-20** during `agesdk.dev` real-world testing — resilience + budget + tooling + decoupled translation + scope probe + env-first token + Workers Services + GET-then-PUT + pain removal; **v15.S added + shipped 2026-05-21** — translate output quality fixes from `disclosur.dev` port run)*

Build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel
API integration (v15.C-F — original tier scope; heavy overlap with
v11's `fleet hosting`; revisit at v15.A kickoff). New v15.B inserted
2026-05-20 to restore CLI symmetry — `fleet hosting --only <domain>`
is a fleet verb pretending to be per-project; `project hosting
<domain>` makes the symmetry explicit (`project check ↔ fleet check`,
`project seo ↔ fleet seo`, `project fix ↔ fleet fix`, `project
hosting ↔ fleet hosting`). The previously-parked LLM content seeding
sub-phase (briefly v15.F, originally v13.C) was dropped 2026-05-20 —
automating starter content bypasses the operator's scarce-hours
scaling lever (per § 2 Non-goals: content is where operator time
goes; this tool automates the parts that don't scale, not the parts
that do).

#### Phases

| # | Status | Feature |
|---|---|---|
| v15.A | ✅ | **Kickoff planning.** Locked four decisions 2026-05-20: (a) `project hosting <domain>` uses **vertical-sections layout** (matches v13.B's `project seo` GSC-diagnostics pattern; sections grow incrementally as v15.D + v15.E land). (b) v15.E `last-build-success` **folds into the existing `fleet hosting` walker** — surface as a new `Last build` column on `fleet hosting` + matching row on `project hosting`; no new platform-API infra. CF Pages + Vercel deployment-list endpoints already return this state; CF Workers and HostGator render `—` (no build concept). (c) v15.F ships **both** `--refresh` (live Porkbun pull; GoDaddy/Namecheap deferred until account-API setup) and `--watch` (filesystem watcher on `data/domains/*.csv`) on `fleet sync`. (d) Sequential execution A→B→C→D→E→F. See `#### Design notes` for the locked `project hosting` mockup. |
| v15.B | ✅ | **CLI symmetry — `project hosting <domain>`** (new verb) + **drop `fleet hosting --only`** (hard cutover, matching v14.B posture). Single-domain view of the existing fleet-hosting probe data, rendered as vertical sections: Property / Account / branch header · 📦 Deploy · 📌 Domains. Sections 📋 Freshness (v15.D) + 🔧 Build (v15.E) layer in as later phases land. New module `src/portfolio/project_hosting_render.py` (modeled after v13.B's `project_seo` diagnostics renderer). `_project_hosting_impl` helper extracts the single-domain probe out of `_fleet_hosting_impl` (which loses its `only_domain` parameter entirely — hard cutover). Becomes the surface for v15.D + v15.E — both signals are per-site and belong on `project hosting`, not on `project diagnose` (diagnose = "what's broken"; hosting = "what's the state"). 10 new tests (happy path · JSON · unknown domain · case-insensitive lookup · cache reuse · `--refresh` triggers single-domain probe · stale snapshot fallback · no-fleet-snapshot-clobber invariant · conflict rendering · `--only` hard-cutover guard). Suite 2251 → 2261. |
| v15.C | ✅ | Build-time stamping. Convention: every sites/* project's Vite build writes `dist/version.json` containing `{schema:1, commit, built_at}`. Generation lives in `~/work/projects/builder/vite-version-stamp.ts` (canonical reference; sites inline a copy in their `vite.config.{ts,js,mjs}` so CF Pages / Vercel deploy environments can run it). Commit-SHA resolution: native git → `CF_PAGES_COMMIT_SHA` → `VERCEL_GIT_COMMIT_SHA` → `GITHUB_SHA` → literal `"unknown"`. New conformance check `CHECK_144 has-version-stamp` (deploy category, warn severity) fetches `<live_url>/version.json` and validates shape — fails on 404 / non-200 / non-JSON / missing required fields; warns on network errors (matches v090 posture). 14 new tests; suite 2261 → 2275. Per-site rollout (updating each site's `vite.config` + redeploying) is operational work that follows the convention; not gated on this commit. |
| v15.D | ✅ | HEAD vs deployed. New shared `src/portfolio/version_stamp.py` owns `/version.json` fetch + parse + HEAD-vs-live comparison (refactored CHECK_144 to use it). New conformance check **CHECK_145 `deploy-fresh`** (deploy/warn) — passes when local HEAD matches live commit, fails on drift with a "push + redeploy" hint, warns when one side undetermined. `_project_hosting_impl` fetches freshness data and passes to renderer; `render_project_hosting` gains a 📋 Freshness section between Deploy and Domains (omitted when freshness unavailable). 8 new tests on CHECK_145; suite 2275 → 2283. |
| v15.E | ✅ | Build status. New conformance check **CHECK_146 `last-build-success`** (deploy/warn) — reads the operator's `fleet hosting` cache and surfaces the `latest_deploy_status` per-project. Passes on READY/SUCCESS/ACTIVE; fails on ERROR/CANCELED with consecutive-failures count; warns when in-flight / no snapshot / CFW or HG provider (no build pipeline). Folded purely into the existing snapshot; no new platform-API infra per v15.A. **No new `Last build` column on `fleet hosting`** — the existing `Deploy state` + `Last Success` + `Failures` columns already surface the same signal; adding a column would be redundant. **No new 🔧 Build section on `project hosting <domain>`** — same reasoning; the existing 📦 Deploy block already shows status/when/failures. Operator can revisit if a dedicated framing proves valuable. 9 new tests on CHECK_146; suite 2283 → 2292. |
| v15.F | ✅ | Domain-list refresh tooling. `lamill fleet sync` gains two flags: `--refresh` (pulls live Porkbun owned-domain list via the API, writes `data/domains/porkbun.csv`, then runs the existing CSV merge) and `--watch` (polls `data/domains/*.csv` mtimes at `--interval` seconds, re-runs merge on any change, Ctrl-C exits — no `watchdog` dep, mtime polling is good enough for the CSV-edit cadence). GoDaddy/Namecheap deferred until those registrars' account-API setup lands. New `src/portfolio/porkbun_list.py` module wraps `domain/listAll` (handles missing creds / network / non-200 / non-SUCCESS / shape errors via typed `PorkbunListError`). 11 new tests on porkbun_list (watch loop is integration-tested manually); suite 2292 → 2303. |
| v15.G | ✅ | **Kickoff planning** for the v15.G-J extension. Locked six decisions 2026-05-20: (a) cf-workers becomes the bootstrap default (was cf-pages); (b) Astro+Vite is the only supported `sites/*` stack — non-Astro `--git-url` repos translated via Claude subprocess (see ADR-0013); (c) `lamill new deploy` is the single entry point for the entire deploy lifecycle — no new commands, no `wrangler deploy` calls; uses git-integrated CF Pages-API for all CF deploys (see ADR-0012); (d) `agesdk.dev` nuked + re-bootstrapped blank Astro; (e) existing 5 cf-pages sites + airsucks.com left as legacy (no migration); (f) Lovable workflow: operator pushes Lovable to prefer Astro exports going forward. Two ADRs written (0012 + 0013). API endpoints pre-verified against current CF + GitHub + Porkbun docs to avoid course-correction during code. Doc-only phase. |
| v15.H | ✅ | **Bootstrap stack normalization via Claude subprocess.** New module `src/portfolio/stack_translate.py` — `detect_stack(genai_dir)` returns one of `{astro, vite-react, tanstack-start, nextjs, sveltekit, unknown}` by inspecting `package.json` deps + presence of config files (`astro.config.{mjs,ts}`, `next.config.*`, `svelte.config.*`, `wrangler.jsonc` + `src/server.ts` pattern). `translate_to_astro(project_dir, *, detection)` spawns `claude` CLI (same Tier-2-fixer subprocess pattern as ADR-0006) with a translation prompt — read genai source, emit equivalent Astro+Vite project at root, drop framework-specific server code with `TODO:` markers, preserve pages/components/copy/styles. `validate_translation(project_dir)` runs basic shape checks (package.json mentions `astro`; `astro.config.*` exists; no `tanstack`/`next`/`@sveltejs` deps remain; no `wrangler.jsonc` at root — that's v15.I's territory) and bails with `StackTranslationError` on failure. Hooked into `bootstrap.py` `--from-genai` / `--git-url` flow between `_clone_to_genai()` and `_copy_from_genai()`. 26 new tests (12 detector + 9 validator + 5 orchestration). **Known issue (bugs.md 2026-05-20):** default `$0.50` budget cap is too low for real-world TanStack→Astro translations; operator's `agesdk.dev` hit `error_max_budget_usd` after 22 turns / $0.524. v15.K candidate: bump default + add `--budget` flag. |
| v15.I | ✅ | **`new deploy` end-to-end automation (git-integrated, no wrangler).** Replaced `_deploy_cf_pages_v3c()` and `_deploy_cf_workers()` with one unified `_deploy_cf_unified()` orchestrator routing both `platform ∈ {cf-pages, cf-workers}` through the same git-integrated CF Pages-API pipeline (the old functions were left as dead code at v15.I ship time, then removed in v15.K's cleanup pass — see `## Phases` v15.K row for the deletion record). New `src/portfolio/gh_repo.py` (GitHub REST API primary via `GITHUB_TOKEN`; `gh` CLI fallback; `POST /user/repos` for create + `GET /repos/{owner}/{repo}` for idempotency probe). New `src/portfolio/porkbun_dns.py` (`get_porkbun_ns` + `update_porkbun_ns` — get-then-update idempotency, no blind retry). Extended `src/portfolio/cloudflare.py` with `ensure_zone(domain)`, `get_pages_project(name)`, `create_pages_project_with_git(name, ..., source.type=github)`, `attach_pages_custom_domain(project, hostname)` (GET-then-POST against project.domains[]), `latest_deployment_status(name)` + `poll_build(name, timeout_s=300)`. Bootstrap default platform flipped to `cf-workers`. Pipeline is idempotent at every step: each step probes existing state and prints `✓ exists, skipping` / `✓ created` / `↷ warn-skipped: <reason>` / `✗ <error>`. Honors `--dry-run` (plan + skip writes) + new `--yes` flag (auto-confirm NS update). Pre-flight detects missing CF GitHub App installation (operator-only one-time dashboard step) and surfaces with explicit dashboard link. 48 new tests across `gh_repo` (20) + `porkbun_dns` (12) + `cloudflare_v15i` (16). All HTTP stubbed via `httpx.MockTransport`; subprocess stubbed via `MagicMock`. |
| v15.J | ✅ | **Docs sync wrap** — closes v15.G-J. Marked v15.G/H/I/J as ✅ in prd; added `docs/shipping-history.md § v15.G-J addendum`. Architecture.md + AI_AGENTS.md + decisions/README.md were already updated in v15.G's doc-plan commit (`ad8739d`). 4 obsolete `test_new_deploy_dispatch.py` tests removed (the cf-pages-shells-to-v3c and cf-workers-shells-to-wrangler tests verify behavior intentionally changed in v15.I); 2 replacement tests added that verify both platforms route through `_deploy_cf_unified()`. Doc-only; suite stays at v15.I's final count + the dispatch-test delta. |
| v15.S | ✅ | **Translate output quality — 4 sub-fixes** triggered by operator's `disclosur.dev` real-world port-to-Astro run 2026-05-20. The v15.M port verb (`lamill project translate`) succeeded and validator passed, but the operator hit three different runtime failures in the resulting site: (a) Vite couldn't resolve `@import "tailwindcss"` from `src/styles/globals.css` — Claude faithfully ported the v4 Tailwind import but didn't add `tailwindcss` / `@tailwindcss/vite` to `package.json`; (b) Astro dev server emitted `Unsupported file type` warnings on three `*.astro.tmp.<pid>.<hex>` files in `src/pages/dashboard/` — Claude's atomic-write artifacts that didn't get cleaned up; (c) `pnpm install` blocked the `esbuild` + `sharp` build scripts despite the parent `sites/pnpm-workspace.yaml` listing them in `onlyBuiltDependencies` — pnpm v11's interactive `approve-builds` flow had silently written a local stub `pnpm-workspace.yaml` with `allowBuilds: set this to true or false` placeholders that overrode the parent. Per `feedback_fix_pipeline_not_siblings`, all four fixes land in `src/portfolio/stack_translate.py`, never in the sibling. **Fix 1 — validator dep-import consistency.** New `_detect_tailwind_usage(src_dir)` scans `src/**/*.css|scss|sass|pcss` for `@import "tailwindcss"` (v4) and `@tailwind <base\|components\|utilities>` (v3); `validate_translation` rejects when either pattern fires without matching `tailwindcss` in deps (and additionally requires `@tailwindcss/vite` for v4). Catches both bootstrap (`translate_to_astro`) and port (`port_to_astro`) — both call the same validator. **Fix 2 — tmp-file sweep.** New `sweep_tmp_artifacts(project_dir)` regex-matches `\.tmp\.\d+\.[0-9a-f]+$` and unlinks under project root, skipping `node_modules`, `genai`, `.git`, `dist`, `.astro`. Wired into both `translate_to_astro` and `port_to_astro` after `run_claude` returns (cleans up on failure too). **Fix 3 — translation prompt CSS toolchain section.** Both `_build_translation_prompt` and `_build_port_prompt` now have explicit instructions to port `tailwindcss` / `@tailwindcss/vite` / `tailwind-merge` / `clsx` / `class-variance-authority` / `postcss` / `autoprefixer` / `sass`-family deps from `genai/package.json` to target + wire the matching Vite plugin into `astro.config.mjs`. Port prompt's old `"Do NOT touch package.json"` constraint relaxed to `"you MAY (and often must)"` for CSS toolchain additions. **Fix 4 — pre-seed pnpm-workspace.yaml.** New `write_pnpm_workspace_yaml(project_dir)` writes `onlyBuiltDependencies: [esbuild, sharp]` to `<project>/pnpm-workspace.yaml` so pnpm never enters the interactive flow. Idempotent — preserves operator-customized files; only overwrites pnpm's placeholder stub (detected by `"set this to true or false"` substring). Called from both translation paths after the tmp-sweep. 13 new tests in `tests/test_v15s_translate_quality.py` (5 validator + 3 sweep + 2 prompt + 3 pnpm-workspace). Suite 2492 → 2505. |
| v15.R | ✅ | **Operator pain removal — DNS auto-cleanup + per-step dashboard URLs + Porkbun pre-check.** Triggered by operator's `agesdk.dev` real-world session 2026-05-20 where every CF write step required a dashboard click + the DNS conflict at Workers attach forced manual deletion of 4 records. v15.R bundles 4 automations: (1) **Auto-purge conflicting DNS** — new `cloudflare.purge_conflicting_root_records(zone_id, domain)` lists `/zones/{id}/dns_records` and DELETEs A/AAAA/CNAME records on root + `*.domain` + `www.domain` (the patterns CF's "Connect a domain" auto-populates as parking placeholders). Inserted as Step 5.5 between project detect (Step 5) and custom domain attach (Step 6) when `cf_surface == "workers"`. Token's existing DNS:Edit zone-scope is sufficient. (2) **Step 6 explicit dashboard URL on 403** — surfaces the exact `https://dash.cloudflare.com/{cf_account}/workers/services/view/{slug}/production/domains` URL + numbered steps (+ Add → Custom Domain → enter domain → Save) when PUT /workers/domains 403s. (3) **Step 3 explicit dashboard URL on zone 403** — surfaces "+ Add → Connect a domain → enter domain → Free plan" steps. (4) **Step 5 explicit dashboard URL on project 403** — Workers & Pages → + Add → Workers → Connect to Git with each numbered substep (authorize GitHub App, select repo, project name=slug, prod branch=main, build command=pnpm run build, output=dist). (5) **Step 0 Porkbun per-domain access pre-check** — when registrar=porkbun, calls `get_porkbun_ns` and catches `API_ACCESS_DISABLED`; surfaces porkbun.com/account/domains URL with toggle instructions, exits 2 cleanly instead of failing mid-pipeline at Step 4. New `cloudflare.DnsRecord` dataclass + `list_dns_records` + `delete_dns_record` helpers. 4 new tests on the DNS helpers (list / delete / purge happy + skip-clean-zone). Suite 2488 → 2492. |
| v15.Q | ✅ | **GET-then-PUT idempotency on Workers custom domain attach.** v15.P's `attach_workers_custom_domain` did a blind PUT. Operator's real-world testing 2026-05-20 showed PUT 403ing for tokens with `Workers Scripts:Edit` despite that being the documented permission. Pre-existing mappings (cricketfansite, voltloop) likely added via dashboard (no API write needed). v15.Q has the helper do `GET /workers/domains` first; if the (hostname, service) pair is already in the list → skip PUT → return False ("already attached"). Lets operators attach custom domains via dashboard, then re-run `lamill new deploy` to verify state without the 403. Matches v15.I's `attach_pages_custom_domain` GET-then-POST pattern. 1 new test covering the skip-PUT-when-attached path. |
| v15.P | ✅ | **Workers Services API support — Pages-vs-Workers auto-dispatch in deploy pipeline.** Operator's `agesdk.dev` real-world deploy 2026-05-20 succeeded at Steps 0-4 but failed at Step 5 with `POST /pages/projects/agesdk → 403 Authentication error`. Diagnosis: CF unified Workers & Pages in 2025 but the APIs are still separate. CF's dashboard "+ Add → Pages → Connect to Git" creates a **Workers Service** (not a Pages Project) — operator's entire fleet (10 sites: agesdk, homeloop, airsucks, cricketfansite, voltloop, kwizicle, donready, isitholiday, lamillio, newiniot) is on the Workers Services API surface. v15.I's Pages-API-only pipeline was wrong for this fleet. v15.P adds dual-surface routing: Step 5 probes Pages first via `get_pages_project`, then Workers via new `cloudflare.get_workers_service(name)` (GET `/accounts/{id}/workers/services/{name}`). When Workers detected, `cf_surface = "workers"` carries through Step 6+. Step 6 dispatches: Pages uses `attach_pages_custom_domain` (existing); Workers uses new `attach_workers_custom_domain(service, hostname, zone_id)` via `PUT /accounts/{id}/workers/domains`. Step 7 skips for Workers (Workers Builds API is dashboard-only as of Jan 2026 per CF docs; surface the dashboard URL for build watching). Step 8 unchanged. Workers Services *create* still requires CF dashboard (no public API for git-integrated create — explicitly documented as an open feature request `cloudflare/workers-sdk#12058`); pipeline surfaces this as an actionable error if neither Pages nor Workers detected + create attempt fails. 4 new tests on the helpers (get/attach happy paths + 403 + 404). |
| v15.O | ✅ | **Env-first CF token lookup hotfix.** Operator's v15.N retry 2026-05-20 still failed with Pages:403 / Account:403 despite the token clearly having the required permissions in CF's dashboard. Diagnosis: two CF token storage locations had diverged — `portfolio.env` `CF_API_TOKEN` had the NEW token with Pages:Edit (set via `lamill settings apikeys set`), but `cloudflare._read_token()` was reading the LEGACY file at `~/.config/portfolio/cloudflare/token` (the OLD token without Pages:Edit, leftover from CHECK_057's pre-apikeys cache-purge setup). v15.O makes `_read_token()` env-first: try `apikeys.get_key("CF_API_TOKEN")` first, fall back to the legacy file for backward compat. Updated error message points operators at `lamill settings apikeys set CF_API_TOKEN` (canonical since v15.I) instead of the file. Test fixtures stub `apikeys.get_key` to control env-vs-file priority; added 2 new tests (env wins / file fallback). |
| v15.N | ✅ | **Pre-flight CF token scope probe.** Operator's `agesdk.dev` real-world deploy 2026-05-20 failed at step 3 (CF zone create) with HTTP 403: "Requires permission com.cloudflare.api.account.zone.create". The pipeline had already created the GH repo + pushed origin/main by then — partial state. v15.N adds a read-only scope probe at Step 0 that catches under-scoped tokens BEFORE any GitHub state is mutated. New `cloudflare.probe_token_scopes(account_id)` runs three GETs (`/user/tokens/verify` · `/accounts/{id}/pages/projects?per_page=1` · `/zones?per_page=1` · `/accounts/{id}`) and returns a `TokenScopeReport` with a `missing` list of operator-actionable permission names. Read-side failure implies Edit-side failure too (CF's Edit ⊇ Read hierarchy). `_deploy_cf_unified` Step 0 surfaces missing scopes with the dashboard URL + "edit token → add permissions → save" instructions, then exits 2. 4 new tests on the probe (all-ok / Pages-403 / invalid-token / Zone-403). |
| v15.M | ✅ | **Decoupled translation — `lamill project translate <domain>` verb** (operator-triggered, separate from bootstrap). `lamill new bootstrap <domain> --git-url <url>` for non-Astro sources now defers translation by default — scaffolds blank Astro+Vite at root via existing `ASTRO_FILES` template, leaves `genai/` untouched as untranslated reference, writes `.lamill-translation-pending` marker file with source-stack signals. Bootstrap completes in seconds. New `lamill project translate <domain>` verb runs the Claude-driven port from `genai/` into the existing scaffold via `port_to_astro()` (smaller-delta prompt than v15.H from-scratch translation). Default budget $5.00, timeout 30min — both configurable via `--budget` / `--timeout` flags. Marker file consumed on success; preserved on failure for retry. New `--translate-now` flag on `new bootstrap` preserves the v15.H synchronous behavior for operators who want it (or tests that mock Claude). v15.H "no `wrangler.jsonc`" validator check removed — bootstrap legitimately writes one via CF safety fixes. 9 new tests on `test_v15m_decoupled_translation.py` (deferred path produces marker · `--translate-now` invokes synchronous · Astro source still direct-copies · `project translate` exit codes for missing project / missing genai / missing marker / port failure / validator failure / happy path consumes marker). Triggered by operator's 2026-05-20 test session: agesdk.dev's TanStack→Astro translation kept timing out at 5min even with $5 budget — Claude can't write much under tight time pressure. Decoupling separates the slow operation from the critical bootstrap path; operator can background it (`lamill project translate agesdk.dev &`). |
| v15.L | ✅ | **Hotfix — translation needs Write + Bash tools.** Operator's v15.K retry on `agesdk.dev` succeeded past the budget cap but Claude couldn't actually CREATE the Astro+Vite scaffolding because `run_claude()` restricted to the Tier-2-fixer toolset (`Read Edit Glob Grep` — no Write, no Bash). v15.L extends `run_claude()` with an `allowed_tools=` parameter (default keeps existing behavior for every Tier-2 fixer; backward-compatible). v15.H's `translate_to_astro()` now passes `"Read Write Edit Glob Grep Bash"` so Claude can create new files at project root + `mkdir src/pages/`. No new tests — existing v15.H tests mock `run_claude` so they don't exercise the toolset; a real-Claude integration test would have caught this but isn't part of the default suite. |
| v15.K | ✅ | **Resilience pass — rollback + budget + dead-code cleanup** (bundled Option A per 2026-05-20 plan). 5 sub-items: (a) **Transactional rollback** — `bootstrap()` wraps the body in try/except after `project_dir.mkdir`; on any exception, removes project_dir via `_rollback_project_dir(project_dir)` and re-raises. Pre-existing dirs detected at pre-flight (raise BootstrapError "already exists") fire BEFORE the dir-tracker flips so they don't trigger rollback. (b) **PermissionError handling** — `_rollback_project_dir` catches PermissionError (Docker-owned files under `genai/node_modules/`), retries with `ignore_errors=True`, warns operator with Docker-cleanup-inside-container hint. (c) **Translation budget bump** — `_DEFAULT_BUDGET_USD` raised from $0.50 → $2.00 after operator's `agesdk.dev` hit `error_max_budget_usd` at $0.524. (d) **`--budget USD` flag** on `new bootstrap` — flows through `bootstrap(translation_budget_usd=...)` → `translate_to_astro(budget_usd=...)`. Default 0.0 = module default. (e) **Dead-code removal** — deleted `_deploy_cf_pages_v3c()` + `_deploy_cf_workers()` from `cli.py`; deleted `deploy_cf_workers_via_shell()` + 4 obsolete `test_cf_workers_*` tests from `test_new_deploy_dispatch.py`. Bootstrap.py default platform comment refreshed to point at v15.I + ADR-0012. 8 new rollback tests + apikeys test updated for GITHUB_TOKEN + bootstrap test fixtures bumped to include `astro` dep (keeps existing `--from-genai` tests exercising direct-copy path post-v15.H). |

*Tier-level design notes (locked target shape, migration map, fold
approach for v15.E, flag wiring, CLI symmetry restoration, locked
→ as-shipped deltas, resolved open questions, parked items) migrated
to `docs/shipping-history.md § v15 — deploy verification` 2026-05-20
as part of the v15 tier wrap — same pattern as v10 + v11 + v12 + v14.*

### v16 — GSC fleet-level intelligence ✅ *(new 2026-05-19; absorbs v13.A; renumbered 2026-05-20, was v15; reshaped 2026-05-20 — dropped original v16.B/C/E single-property reinvention per `§ 2 Non-goals` audit; relabeled original v16.D→v16.B + v16.F→v16.C; kickoff inserted 2026-05-20 — bumped foundation/check/rollup to v16.B/C/D; **tier complete 2026-05-20**)*

GSC web UI handles single-property dim views (queries / pages /
devices / trend) well — operator can browse `search.google.com/
search-console` per site. What it does *not* do is aggregate across
multiple properties, and what `lamill` does well is per-URL
conformance enforcement. v16 leans into both: a URL Inspection
binary check (`project check` fires fail when URLs aren't indexed)
and a fleet-level rollup that the GSC UI can't produce.

The 2026-05-19 design originally proposed full single-property
rebuilds (top queries / top pages / device split / weekly trend
/ derived opportunities) as `project seo` section flags. The
2026-05-20 audit dropped those as UI-reinvention per the project's
non-goals — same family as the dropped GA4 Data API consumers.

#### Phases

| # | Status | Feature |
|---|---|---|
| v16.A | ✅ | **Kickoff planning.** Locked five decisions 2026-05-20: (a) v16.C URL Inspection check inspects **sitemap URLs ranked by GSC impressions desc** (alphabetical fallback for zero-imp URLs) — works for new sites + prioritizes URLs that actually matter. (b) v16.D fleet-aggregated views surface via a **single `fleet seo --detail` flag** rather than compositional section flags — coherent unit, fewer flags. (c) Cache TTL stays **24h default** — matches existing `hosting_cache`/`seo_cache` conventions; GSC's own 2-3 day publishing lag dominates anyway. (d) v16.C binary check is **indexing-only** (`crawl_state != submitted_indexed`); mobile-usability data renders but doesn't fail the check (one assertion per CHECK_NNN). (e) Formally adopted the kickoff-phase convention — bumped existing v16.A/B/C → v16.B/C/D. See `#### Design notes` for the locked decisions; this matches the v14.A / v15.A kickoff precedent. |
| v16.B | ✅ | Foundation — `gsc.query_with_dims(service, site_url, *, dimensions, row_limit)` dimension-aware searchAnalytics wrapper. Reuses `query_totals`' OAuth + retry plumbing; supports any combination of GSC dimensions (query, page, device, country, date). Per-domain cache lives in the existing `gsc_detail_cache.py` (v13.B) — no new cache module needed; v16.C/D layer their data into new sections of the same per-domain JSON file. 7 new tests on `query_with_dims`. |
| v16.C | ✅ | URL Inspection API wrapper + binary check. `CHECK_147 url-indexed` (deploy/warn) — fetches top-N pages ranked by GSC impressions (sitemap fallback for zero-imp sites), runs `urlInspection.index:inspect` per URL via the existing `gsc_recrawl.inspect_one_url`, fires `fail` when any URL is in a non-indexed `coverageState`. Indexed states: `"Submitted and indexed"` + `"Indexed, not submitted in sitemap"` (matches GSC's actual API response text, not the v13.B-era enum-token assumption — that mismatch was the v13.B bug logged 2026-05-20). Cache-aware: reads cached inspections when fresh (24h TTL), refetches via API otherwise. Mobile-usability data renders alongside but doesn't trigger fail — surgical check posture per v16.A. GSC layer errors (auth, property lookup, network) warn-skip rather than fail-grade. 11 new tests. |
| v16.D | ✅ | Fleet-level GSC rollup. New `src/portfolio/gsc_rollup.py` — read-only fleet aggregation over the per-domain caches: `domain_coverage_stats()`, `domain_queries()`/`pages()`, `page_2_opp_count()`, `fleet_aggregated_top_queries()`, `fleet_aggregated_top_pages()`, `fleet_page_2_opportunities()`. `fleet dashboard` gains 3 columns (Cov % · Crawl-err · P2-opp) that read from the per-domain cache and render `—` when absent. `fleet seo --detail` flag appends three fleet-aggregated sections below the per-site table (🔎 Top queries, 📄 Top pages, 💡 Page-2 opportunities) — sections render "(empty)" when no domains have cached GSC data yet. **Trimmed from the locked design**: the `W/w impressions Δ` dashboard column was dropped — needs comparing across multi-day snapshots, deferred until snapshot history exists. Cache-population step (filling `v16b_queries`/`v16b_pages` per-domain sections) is a follow-up hook on `project seo` — gsc_rollup ships the read side. 15 new tests on the aggregation helpers. |

*Tier-level design notes (problem statement, goals, non-goals,
locked → as-shipped deltas, resolved open questions, user journey
scenarios, effort tally, approval, kickoff-gate convention)
migrated to `docs/shipping-history.md § v16 — GSC fleet-level
intelligence` 2026-05-20 as part of the v16 tier wrap — same
pattern as v10 + v11 + v12 + v14 + v15.*

<!-- BEGIN v16-design-notes-purged
**Problem statement.** Two operator-facing gaps `lamill` should close,
both one or two GSC API calls away:

1. **Per-URL coverage as a binary conformance fail.** Today's
   `project check <domain>` doesn't know whether Google has actually
   *indexed* the URLs the site submits via sitemap. A submitted-but-
   `crawled_not_indexed` URL is a silent ranking failure — invisible
   to every other check. The URL Inspection API exposes the verdict
   per URL; v16 turns that into a binary CHECK_NNN that fires `fail`
   when any inspected URL is non-`submitted_indexed`.
2. **Fleet-aggregated signals the GSC UI cannot produce.** GSC's web
   UI is one-property-at-a-time. Operator running 20+ sites cannot
   ask "across all my properties, what's the total page-2 opportunity
   count? which queries appear on the most sites? what's the w/w
   impressions delta fleet-wide?" v16 builds that rollup on top of
   per-property snapshots.

**Goals.**

- One shared per-project GSC cache at `data/gsc/<domain>/<UTC-today>.json`
  so per-URL coverage + fleet rollup read from the same persisted
  snapshots without re-burning GSC quota.
- `--refresh` re-fetches the underlying GSC calls (mirrors
  `fleet seo --refresh` / `fleet hosting --refresh` posture).
- Default no-flag `project seo` output unchanged from v13.B —
  backwards-compatible for any existing scripts.
- Heavy reuse of existing OAuth + retry plumbing in `gsc.py` — no
  new auth surfaces.

**Non-goals.**

- Cross-project aggregation outside the explicit fleet rollup (e.g.
  ad-hoc "compare these 3 sites" — not in scope; `fleet dashboard`
  + `fleet seo --detail` are the aggregation surfaces).
- Persistent trend storage beyond the 24h cache + the existing
  `data/gsc/<date>.json` snapshots (long-horizon analytics is a
  different tier).
- GSC property-management ops (already covered by `settings gsc
  auth` / `settings gsc status` in v7.A).
- Writing back to GSC (URL Inspection is read-only; we never POST
  reindex requests from this command — that's an `apply` write
  surface and would need an ADR).
- Multi-property sites — when `data/portfolio.json` lists multiple
  GSC properties for one domain (apex + `sc-domain:` form), v16
  aggregates the same way `fleet seo` does today.
- **Single-property dim views (top queries / top pages / device
  split / weekly trend / derived opportunities for one site) — the
  GSC web UI already does this well; per-property reinvention
  violates `§ 2 Non-goals`.** The originally-planned
  `--queries` / `--pages` / `--devices` / `--trend` / `--opportunities`
  / `--full` section flags (2026-05-19 design) were dropped in the
  2026-05-20 audit — same family as the dropped GA4 Data API
  consumers.

**User journey scenarios.**

```text
# Default — unchanged from v13.B (per-project GSC diagnostics block)
$ lamill project seo lamillrentals.com
<sitemaps · coverage · hints diagnostics block, as shipped in v13.B>

# v16.C — per-URL index conformance fires as a binary check
$ lamill project check airsucks.com
…
 ✗ url-indexed (CHECK_NNN)
     7 submitted URLs · 5 indexed · 2 non-indexed:
       · /pricing       crawled_not_indexed
       · /docs/old      not_found_404
     Hint: re-publish or remove from sitemap; re-submit if intentional.

# v16.D — fleet rollup columns on the dashboard
$ lamill fleet dashboard
Domain                Status  …  Cov %   Crawl-err  W/w Δimp   P2-opp
airsucks.com           ✓      …  92%       0        +18         3
homeloom.app           ✓      …  88%       1        -22         5
lamillrentals.com      ⚠      …  78%       4        +6          2
…

# v16.D — fleet-aggregated top queries / page-2 opportunities
$ lamill fleet seo --detail
🔎 Top queries (fleet-aggregated, 28d)
 Query                            Sites  Imp     Pos avg
 rv rental washington               2     312    8.6
 motorhome hire seattle             3     201   13.4
 …

💡 Page-2 opportunities (fleet-summed, ≥50 imp · pos 11-20)
 Site                  Query                      Imp  Pos
 lamillrentals.com     motorhome hire seattle      89  12.1
 lamillrentals.com     rv hire bellevue            54  14.8
 …

# Re-fetch underlying GSC calls (bypasses 24h cache)
$ lamill fleet seo --detail --refresh
```

**Open questions.**

| # | Question | Resolution |
|---|---|---|
| 16.A | URL Inspection cap — how to bound the per-day quota burn? | **Top N pages from the sitemap, ranked by GSC impressions desc** with alphabetical fallback (default top 10). A 100-page site at one inspect call each would chew the daily quota; capping at top-N keeps it bounded. Ranking by impressions surfaces the most-trafficked URLs first. |
| 16.B | Per-project GSC cache TTL? | **24h default**, configurable via `is_stale(max_age_hours=N)` like `hosting_cache`. GSC search data has a 2-3 day publishing lag anyway; 24h matches the daily-run cadence. |
| 16.C | Cache directory shape — `data/gsc/<domain>/<date>.json` (per-domain subdir) vs flat `data/gsc/<domain>-<date>.json`? | **Per-domain subdir.** Matches how `data/seo/` would scale if we ever wanted per-domain history. Cleaner `ls` output. Already adopted in v13.B's `gsc_detail_cache.py`. |
| 16.D | Fleet-aggregated views — single `--detail` flag or compositional `--queries`/`--pages`/`--opportunities` flags on `fleet seo`? | **Single `--detail` flag.** Renders all three fleet-aggregated sections (top queries / top pages / page-2 opportunities) below the existing per-site table. Coherent unit; simpler flag surface. Can decompose into section flags later if section-by-section iteration becomes valuable. |
| 16.E | v16.C binary check failure semantics — fail on indexing only, or also on mobile usability? | **Indexing only** (`crawl_state != submitted_indexed`). Mobile-usability data renders in the URL Inspection output but doesn't trigger conformance failure. Keeps the CHECK_NNN surgical (one assertion per check). Mobile-friendliness could become a separate CHECK_NNN later. |

**Effort estimate.** ~4.5-6.5h total across 4 sub-phases:

| Phase | Scope | Effort |
|---|---|---|
| v16.A | Kickoff planning (✅ shipped 2026-05-20) | ~0.5h |
| v16.B | `gsc.py` dim-aware queries + per-project cache module | ~2h |
| v16.C | URL Inspection wrapper + binary CHECK_NNN | ~1-2h |
| v16.D | Fleet rollup columns + `fleet seo --detail` | ~1-2h |

Real GSC API quirks (paging behavior on filtered queries, rate-limit
edges, URL Inspection quota math) surface only on first run against
the operator's actual properties.

**Approval.** Shape C (compositional section flags) + v16 tier
assignment approved 2026-05-19. Reshape approved 2026-05-20 per
`§ 2 Non-goals` audit.

**Kickoff gate.** Now adopted as the explicit `v16.A` phase (above) — 2026-05-20 locked the five decisions captured there. For consistency, v16+ (post-kickoff-convention) all carry the explicit `vN.A — kickoff planning` row; v15 also adopted it 2026-05-20. v13/v14 absorbed it as a one-line tier-preamble note since their letter slots were already assigned at shipping.
END v16-design-notes-purged -->

### v17 — SEO check expansion *(new 2026-05-19; renumbered 2026-05-20, was v16)*

Extend `src/portfolio/checks/seo/` beyond the current 24 checks
(060-079 static + 090-095 live) to close coverage gaps identified
2026-05-19. 14 new universal checks (foundational-tag enrichment,
robustness, live-runtime) plus a WordPress-specific lane to handle
the operator's 2-3 active WP sites. Each check is a new
`check_NNN_<slug>.py` file in the existing registry, auto-discovered
by `src/portfolio/checks/registry.py`. **See `docs/architecture.md
§ 3 Mechanisms (check catalog) / § 5 CLI surface` for the full
catalog conventions (post-implementation).**

`v17.A` kickoff phase re-validates the candidate-check list against
whatever shipped in v16 (some overlap possible — e.g., per-page
coverage signal may already live in v16.C's URL Inspection wrapper,
in which case the equivalent v17 check thins out).

#### Phases

| # | Status | Feature |
|---|---|---|
| v17.A | ⏳ | **Kickoff planning.** Re-validate v17.B-E candidate checks against v16 final shape (which signals already covered? which check thresholds need tuning given live-fleet data?). Lock the final 14 checks. ~0.5h. |
| v17.B | ⏳ | Foundational-tag enrichment — 4 static checks. CHECK_081 title-length-in-range (30-65 chars). CHECK_082 exactly-one-h1. CHECK_083 og-completeness (`og:title` + `og:description` + `og:image` + `og:url` + `og:type` all present). CHECK_084 json-ld-org-has-logo-and-sameAs. ~1.5h. |
| v17.C | ⏳ | Robustness checks — 4 static checks. CHECK_085 canonical-points-to-production-https (no localhost / staging). CHECK_086 no-noindex-on-production (`meta robots` doesn't include `noindex`). CHECK_087 image-alt-coverage (≥80% of `<img>` tags have non-empty alt). CHECK_088 twitter-card-type-set (`summary` or `summary_large_image`). ~1.5h. |
| v17.D | ⏳ | Live runtime checks — 6 checks. CHECK_096 https-only (no mixed http content in rendered HTML + linked resources). CHECK_097 404-returns-proper-status (random-path probe returns 404, not soft-200). CHECK_098 sitemap-urls-all-200 (sampled). CHECK_099 sitemap-freshness (`lastmod` within 90d). CHECK_100 robots-allows-crawling (no global `Disallow: /`). CHECK_101 apex-www-redirect-symmetry (one canonical form, not split). ~2-3h. |
| v17.E | ⏳ | WordPress-specific lane — 4 WP-only checks. CHECK_102 yoast-or-rankmath-present (one SEO plugin, not zero). CHECK_103 no-yoast-rankmath-conflict (not both). CHECK_104 wp-jsonld-website-with-searchaction (WordPress should emit WebSite schema with SearchAction). CHECK_105 wp-oembed-cleanup (oEmbed discovery links not bloating `<head>`). Gated on detecting WP (existing generator/title heuristics). ~1.5h. |

#### Design notes

**Why universal-first, WP-second.** The 14 universal checks (B/C/D)
apply to every site regardless of stack — Vite/Astro/CFW/WP all
render the same SEO tags. Shipping universal first lets the
operator's pre-deploy quality bar rise across the whole fleet in
one tier. WordPress lane (E) lands after because it requires WP-
specific detection logic plus Yoast/RankMath plugin awareness that
doesn't generalize.

**Out of scope (deferred):**
- Per-page coverage (currently checks homepage only) — that's a
  separate "multi-page check sweep" concern; v17 stays single-page.
- GSC-coverage check (% submitted indexed) — already in v16.C.
- Lighthouse / Core Web Vitals — dropped (v20 reserved; see tier note).
- Performance budgets (bundle size, image count) — dropped with v20.

### v18 — Google Analytics 4 install helper *(new 2026-05-19; deferred behind v16 + v17; renumbered 2026-05-20, was v17; scope shrunk 2026-05-20 — Data API consumers v18.C-F dropped as out-of-scope per `§ 2 Non-goals`)*

GA4 measurement-ID install is conformance — every site should have
analytics, uniformly. Beyond install, GA4 Data API *consumption* is
not in scope: the GA4 web UI already does that job well for one
operator (parallel to the existing non-goal on Ahrefs/SEMrush). v18
ships the install helper only.

#### Phases

| # | Status | Feature |
|---|---|---|
| v18.A | ⏳ | **Kickoff planning.** Audit fleet GA4 coverage (which sites have measurement IDs today). Decide gtag-injection format (inline vs partial template) + whether the operator's existing GTM-managed sites need a separate code path. ~0.5h. |
| v18.B | ⏳ | GA4 install helper. `new bootstrap` injects a gtag block given a `--ga4 G-XXXXXX` flag (or pulls from `[analytics]` block in `lamill.toml`). `project fix` adds an `inject-ga4` remediation for existing sites missing analytics. New conformance check: `has-analytics` (warns if no gtag/GTM detected in rendered HTML). ~1-2h. |

#### Design notes

**Scope decision (2026-05-20).** Dropped v18.C-F (GA4 Data API
foundation + per-page metrics + fleet rollup + acquisition/funnel
consumers). Rationale: same family as the non-goal on paid SEO
analytics (Ahrefs / SEMrush / Moz) — Google's GA4 UI already gives
the operator everything those phases would consume, and reading
analytics into the CLI duplicates UI rather than compressing
operator time. Install enforcement (v18.B) stays because it's
conformance, not consumption.

### v19 — Google Trends integration *(new 2026-05-19; renumbered 2026-05-20, was v18)*

Google Trends gives search-interest direction (rising / flat /
declining), seasonality, related queries, geographic concentration —
signal complementary to GSC (current performance) and GA4 (user
behavior). No official Google API; the integration uses **SerpAPI's
`google_trends` engine** as the primary path (reuses existing
`SERPAPI_KEY` + `serpapi_quota.py` monthly ledger) with **`pytrends`
as a fallback** when SerpAPI quota is exhausted.

`v19.B` (foundation) ships first as a standalone wrapper + cache; B-F
(CLI, wiring into suggest/research/seo, geo+comparison views) are
sketched in design notes but not committed to the Phases table until
v19.A kickoff re-validates them against learnings from v16-v18.

#### Phases

| # | Status | Feature |
|---|---|---|
| v19.A | ⏳ | **Kickoff planning.** Re-validate v19.B foundation + B-F future-expansion list against v16/v17/v18 final shape. Decide pytrends-fallback trigger (quota-exhaustion-only vs first-attempt-parallel). Resolve open question 18.D (ADR-0012 for trends-as-cluster-signal schema bind). ~0.5h. |
| v19.B | ⏳ | Foundation — `gtrends.py` SerpAPI `google_trends` engine wrapper · `data/gtrends/<topic-hash>.json` per-topic cache (mirrors `serp_query_cache.py` shape) · `is_stale(max_age_hours=24)` · integrates with existing `serpapi_quota.consume_quota()` · `pytrends` fallback path · `GTrendsError` exception · primitive table renderer for the standalone `lamill trends <topic>` test invocation. ~2-3h. |

#### Design notes

**Future expansion (v19.C-F+).** Not in Phases table until v19.A
re-scopes:

- `lamill trends <topic>` rich CLI — interest-over-time + related-
  queries (top + rising) + `--region` + `--timeframe {7d, 30d, 90d,
  12m, 5y, all}` + `--json`.
- Wire into `new domain` shortlist — per-candidate "interest
  direction" badge (📈 rising / ➡️ flat / 📉 declining) from 12-month
  slope. Reject topics on clear downtrends pre-purchase.
- Wire into `new validate` (v8) cluster snapshot — trend signal for
  the cluster's primary query, persisted alongside SERP data,
  surfaced in interpretive_pass payload so the LLM weighs trajectory.
  **Schema-evolution gate: ADR-0012** binds the `trends` block to
  the `research-cluster-v2.1` schema.
- Wire into `project seo --trends` — new section flag (v16-compatible)
  showing seasonality + rising related queries for an existing site's
  primary topic.
- Geographic + comparison views — `lamill trends <topic> --geo` /
  `--vs <competitor>`.

**Open questions** (resolved at v19.A kickoff):
| # | Question |
|---|---|
| 18.A | Cache TTL — 24h matches `hosting_cache` / `seo_cache`; lock there? |
| 18.B | Default timeframe — 12m (signal/noise sweet spot) vs 5y (long-horizon seasonality). |
| 18.C | Interest-direction threshold — proposed `>10%/month` rising, `<-10%/month` declining. |
| 18.D | Cluster-snapshot schema bind — **ADR-0012** when v19 wires into v8. |
| 18.E | Single primary topic per site — `[hosting].primary_topic` config vs auto-pick from top GSC query. |
| 18.F | `pytrends` fallback trigger — quota-exhaustion-only vs parallel-call. |

### v20 — *(reserved — Lighthouse + CrUX, dropped 2026-05-20 per `§ 2 Non-goals` audit; re-confirms `docs/CLAUDE.md § Deferred decisions` 2026-05-09 rejection — PSI is heavy (~15-30s × N domains), CrUX returns `no-data` at portfolio scale, lab ≠ field; may revisit if traffic grows past CrUX threshold across many fleet sites)*

### v21 — Indexing API hook *(new 2026-05-19; renumbered 2026-05-20, was v20)*

Post-deploy ping to `https://indexing.googleapis.com/v3/urlNotifications:publish`
requesting reindex per changed URL. Officially supported only for
JobPosting + LiveStream content per Google's docs, but empirically
works for general URLs as a "we updated this, please re-crawl" signal.
Reuses GSC OAuth (same scope: `https://www.googleapis.com/auth/indexing`).

Wires into `new deploy` as an optional post-deploy step — natural fit
now that v11.M-N's polymorphic deploy verb is in place.

#### Phases

| # | Status | Feature |
|---|---|---|
| v21.A | ⏳ | **Kickoff planning.** Validate empirical effectiveness for general URLs (Google warns it's officially job/livestream-only) against operator's launched sites. Lock the OAuth-scope addition. ~0.5h. |
| v21.B | ⏳ | `indexing.publish(url, type='URL_UPDATED')` wrapper + `lamill new deploy --reindex [<url>...]` flag. Without specific URLs, defaults to the project's homepage + sitemap. Optional `[deploy].reindex_on_deploy` flag in `lamill.toml` for default-on behavior. Quota-aware (200 calls/day per token). ~1h. |

### v22 — *(reserved — Gemini integration for audit-pass model diversity, skipped 2026-05-19; may revisit; renumbered 2026-05-20, was v21)*

Originally proposed as a third LLM family in v12's verify mode
(Claude primary + GPT-4o audit + Gemini cross-check) to strengthen
REVIEW_REQUIRED signal via 3-way model disagreement. Operator opted
out 2026-05-19 in favor of v21/v23. Slot reserved so re-
introduction doesn't require renumbering.

#### Phases

*None — tier reserved.*

### v23 — GSC Sitemaps + per-URL Indexing status *(new 2026-05-19; renumbered 2026-05-20, was v22)*

Two GSC API surfaces not covered by v16: the **Sitemaps API**
(`/webmasters/v3/sites/{site}/sitemaps`) for tracking submitted-
sitemap status (lastSubmitted, lastDownloaded, errors, warnings)
and the **Search Console API `index` endpoint** for index-status-
inspection at the per-URL level. Distinct from v16.C's URL
Inspection: Sitemaps API is bulk + lower-quota; URL Inspection
(v16.C) is per-URL + higher-detail. Both surfaces useful for
different operator workflows.

#### Phases

| # | Status | Feature |
|---|---|---|
| v23.A | ⏳ | **Kickoff planning.** Re-check API surface coverage against what v16.C actually shipped. If v16.C's URL Inspection already covers per-URL index status sufficiently, v23 shrinks to just the Sitemaps API. ~0.5h. |
| v23.B | ⏳ | GSC Sitemaps API wrapper + `project seo --sitemaps` section flag (composable with v16). Shows submitted sitemaps with last-fetch / error counts / warning counts per site. ~1h. |
| v23.C | ⏳ | Per-URL bulk-index-status integration into `fleet dashboard` (indexed/submitted column augmentation from v16.D). ~1h. |

## 7. Conformance rules for all websites

**Scope: every sibling `sites/<domain>/` website project.** This
section is *not* about the `portfolio` (a.k.a. `lamill`) tool itself
— `portfolio` is a Python CLI, not a website, and is explicitly
excluded from these checks via `[git] ignore_repos = ["portfolio"]`
in `~/.config/portfolio/config.toml`. The rules below are what
`portfolio` *enforces on* the websites it manages.

`portfolio` runs these checks via `project check <domain>` (one
website) and `fleet check` (every sibling website not in
`ignore_repos`). Failures show in the `failed` list with optional fix
hints. Skipped rules don't apply (e.g. `live-site` for a CLI project
that doesn't deploy). The complete numbered catalog (~85 checks
across scaffold / git / stack / deploy / SEO / content categories)
lives under `src/portfolio/checks/`; this table summarizes the
load-bearing checks and where each landed.

| Rule | Pass condition | Lands in |
|---|---|---|
| `own-git-repo` | `git rev-parse --show-toplevel` resolves to project dir itself | v1.A |
| `has-category` (was `in-plan-md`) | domain has a category set in `portfolio.json` | v1.B (renamed in v1.D) |
| `has-prompts-md` | `docs/Prompts.md` exists | v1.B |
| `prompts-md-format` | last H2 matches `^## \d{4}-\d{2}-\d{2}` | v1.B |
| `has-makefile` | `Makefile` with `run` and `build` targets | v1.B |
| `has-ai-agents-md` | `AI_AGENTS.md` exists | v1.B |
| `has-growth-log` | `docs/growth.md` exists | v3.A |
| `platform-declared` | filesystem markers identify cloudflare/vercel/netlify, OR project is n/a | v1.B |
| `live-site` | latest check classification is `live-site` | v1.B |
| `vite-version-ok` | Vite ≥6 for React projects | v7.A |
| `has-prd-md` | `docs/prd.md` exists | v7.A |
| `has-readme` | `README.md` exists at project root | v7.A |
| `has-gitignore` | `.gitignore` exists at project root | v7.A |
| `ai-agents-md-has-building-info` | `AI_AGENTS.md` contains a `## Building info` heading | v7.A |
| `ai-agents-md-has-deployment-info` | `AI_AGENTS.md` contains a `## Deployment info` heading | v7.A |
| `cf-pages-deployable` | frozen-lockfile install OK; no stray gitlinks; no `_redirects` SPA fallback | v5.C / CHECK_050-056 |
| `domain-dir-match` | dir name matches a portfolio.json domain (or override map) | v5.A |
| `gsc-verified` | dir's eTLD is a verified GSC property | v10.E *(renumbered 2026-05-18 — was v10.B → v9.B)* |
| `has-version-stamp` | project writes `version.json` at build time | v15.C *(renumbered 2026-05-17 PM — was v13.A → v12.A → v10.A; bumped from v15.A → v15.B → v15.C 2026-05-20)* |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v15.D *(renumbered 2026-05-17 PM — was v13.B → v12.B → v10.B; bumped from v15.B → v15.C → v15.D 2026-05-20)* |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v15.E *(renumbered 2026-05-17 PM — was v13.C → v12.C → v10.C; bumped from v15.C → v15.D → v15.E 2026-05-20)* |
| `ai-agents-md-has-canonical-sections` | AI_AGENTS.md has all 10 canonical H2 sections | v9.A *(new 2026-05-17)* |
| `cf-edge-cache-fresh` (CHECK_057) | live origin's `/`, `/robots.txt`, `/sitemap*.xml` don't return 200 for paths absent from `dist/` (with `follow_redirects=False`) | v7.H |

The numbered check catalog (`CHECK_NNN_<slug>.py` modules) is the
authoritative source. Categories: `scaffold` (CHECK_001-019), `git`
(CHECK_020-024), `ci` (CHECK_024), `docs` (CHECK_025-027), `stack`
(CHECK_028-039), `deploy` (CHECK_040-058), `seo-assets`
(CHECK_060-064), `seo-meta` (CHECK_070-080), `content`
(CHECK_130-137), `gitignore` (CHECK_141-142). Heading-hygiene fleet
rule: CHECK_043.

## 8. Open questions

Append-only log. Questions get answered (with date) but never
deleted. Tier-specific design questions live under each `### vN`'s
`#### Design notes`; this list is for cross-cutting tool-level
questions.

- *(no open cross-cutting questions at this time — all current open
  questions are tier-scoped and live in the relevant `### vN ####
  Design notes` block.)*

## 9. References

- `docs/architecture.md` — HOW the tool is built (mechanisms, schemas,
  modules, CLI/UX, integrations, stack baselines, implementation
  plans, risks).
- `docs/shipping-history.md` — archived design rationale for shipped
  phases (append-only).
- `docs/decisions/` — ADRs for load-bearing architectural decisions
  (see `decisions/README.md` for the index).
- `docs/CLAUDE.md` — Claude-specific orientation; conventions; locked
  target shapes; deferred decisions; heading hygiene rule; ADR
  workflow.
- `AI_AGENTS.md` (repo root) — agent orientation; canonical
  versioning rule (ADR-0004); canonical-docs map.
