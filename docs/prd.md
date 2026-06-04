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
| ~~v23~~ | ~~Fleet-level sitemap status~~ | *Dropped 2026-05-22 — pre-empted by v13.B + v16.C + v16.D; see § v23 placeholder for the audit.* |

Some overlap with v16.C (URL Inspection coverage) — the v13.B kickoff
gate validated that v16.C wouldn't prematurely commit to the same
Sitemaps API wrapper. v13.B's `fetch_sitemap_details()` is the
shipped wrap; v16.C reuses the same `gsc.py` OAuth plumbing. v23
turned out to be redundant — see the v23 placeholder.

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


### v17 — *(reserved — SEO check expansion, dropped 2026-05-21 per `§ 2 Non-goals` audit; moved to operator's separate SEO pipeline project — every proposed check has authoritative implementations elsewhere (Lighthouse / Yoast / Screaming Frog / GSC). Per-check scoring + adjacent "consume Lighthouse CI output via `fleet check` reader" posture (similar to v16.D's GSC consumption) captured in `docs/for-seo-check-improvements.md`; resurface if portfolio gains a pre-deploy framing that earns the 4-5 unique gates back.)*

### v18 — GA4 property automation + static conformance *(new 2026-05-19; renumbered 2026-05-20, was v17; scope shrunk 2026-05-20 — Data API consumers v18.C-F dropped per `§ 2 Non-goals`; re-scoped 2026-05-21 — markup injection moved to operator's SEO pipeline project; portfolio retains lifecycle property-creation + static checks per the bootstrap-orchestration pattern)*

GA4 property creation is **lifecycle** — same shape as the CF zone /
GitHub repo / Porkbun NS creation that `new bootstrap` already
orchestrates. v18 adds GA4 Admin API automation to bootstrap so
operators don't visit the GA console for every new domain. The
returned measurement ID (`G-XXXXXX`) lands in each site's
`lamill.toml [analytics] ga4_id` field — that's the boundary
where the SEO pipeline picks up to do markup injection (which is
content-shaping, not lifecycle, and belongs there).

Three pieces sit in portfolio:

  1. **Static conformance checks** (CHECK_080 broad detector stays;
     new CHECK_148 ID-well-formed + CHECK_149 script-src-google for
     GA4-specific rigor).
  2. **GA4 Admin API client + OAuth flow** at `~/lamill/ga4/`
     (mirrors GSC's pattern but new location per
     `[[feedback_no_hidden_config]]`).
  3. **Bootstrap integration** writing `G-XXXXXX` to per-site
     `lamill.toml [analytics] ga4_id`.

Three pieces explicitly do NOT sit in portfolio (SEO pipeline owns
them per the 2026-05-21 v17 scope call):

  - Markup injection (`Analytics.astro` partial / Layout wiring /
    inline `<script>` blocks).
  - `inject-ga4` Tier-2-fixer remediation for existing sites.
  - GA4 Data API reads (already dropped — § 2 Non-goals).

#### Phases

| # | Status | Feature |
|---|---|---|
| v18.A | ✅ | **Kickoff planning.** Locked seven decisions 2026-05-21: (a) property creation in portfolio, markup injection in SEO pipeline. (b) measurement-ID handoff via per-site `lamill.toml [analytics] ga4_id` (Option A in `docs/for-seo-check-improvements.md` open question). (c) Bootstrap default = auto-create GA4 property when GA4 OAuth configured; `--skip-ga4` opt-out for dark sites (`csinorcal.church` etc.). (d) OAuth credential location = `~/lamill/ga4/{credentials.json,token.json}` — DO NOT copy GSC's `~/.config/portfolio/gsc/` location (existing GSC location predates `feedback_no_hidden_config` and is itself due for migration). (e) Static check rigor: CHECK_080 stays broad (any analytics provider), new CHECK_148 (`ga4-id-well-formed`) + CHECK_149 (`ga4-script-src-google`) for GA4-specific rigor — both fire only when CHECK_080 detected GA4. (f) Five existing GA4-wired sites (`keralavotemap`, `lamillrentals`, `washcalc`, `homeloom`, `calcengine`) left alone — CHECK_080 already says they pass; operator backfills `lamill.toml [analytics]` manually if/when a single source of truth is wanted. (g) Phase order strict numerical: B (static checks · independent) → C (OAuth + Admin API · standalone) → D (schema + bootstrap integration · depends on C) → E (docs wrap). |
| v18.B | ✅ | **Static GA4 conformance checks.** New `CHECK_148 ga4-id-well-formed` (regex-validates `G-[A-Z0-9]{6,12}` extracted from rendered HTML — catches lowercase-leaked IDs, missing IDs in GA4-wired pages). New `CHECK_149 ga4-script-src-google` (verifies a `<script src="https://www.googletagmanager.com/gtag/js…">` loader is present alongside the inline `gtag()` calls — catches the common "inline-only without loader" breakage). Both fire only when CHECK_080's GA4-specific markers (`gtag(` / `googletagmanager.com`) are found; skip cleanly on Plausible / CF Analytics / Umami-only sites per the atomic-check posture from v16.A. Manual-fix hints registered in `cli.py` `_MANUAL_HINTS`. 13 new tests in `tests/test_v18b_ga4_static_checks.py` (well-formed pass · skip-no-GA4 · malformed-fail · no-ID-extractable-fail · skip-not-web · loader-present pass · inline-only fail · typo'd-CDN fail · skip-not-web · both-quoting-styles · registry-discoverable). Suite 2515 → 2528. |
| v18.C | ✅ | **GA4 OAuth + Admin API client.** New `src/portfolio/ga4_admin.py` (httpx-direct client matching the v15.I `gh_repo.py` / `cloudflare.py` pattern, not `googleapiclient.discovery.build`). Public surface: `create_property(account_id, display_name, *, time_zone, currency_code)` → `"123456789"`; `create_web_stream(property_id, default_uri, *, display_name)` → `(stream_id, "G-XXXXXX")`; `authenticate(force)` returns `Credentials`; `has_token()` cheap probe. OAuth scope `analytics.edit`. Credentials + token at `~/lamill/ga4/{credentials.json,token.json}` (chmod 600 on token) per `feedback_no_hidden_config` — deliberately new location, not `~/.config/portfolio/`. Typed errors: `MissingCredentialsError` (no `credentials.json` — surfaces actionable GCP-Console setup steps) + `GA4AdminError` (non-200 API response — carries HTTP status + truncated body). New `settings_ga4_app` typer group registered as `lamill settings ga4`; `lamill settings ga4 auth [--force]` mirrors the GSC auth command shape (open browser → consent → token cached → success line with cache path). 13 new tests in `tests/test_v18c_ga4_admin.py` (create_property happy + 403 + bad-shape + custom-timezone/currency · create_web_stream happy + custom-display-name + 404 + missing-measurement-id · has_token absent/present · authenticate raises missing-creds · CLI registered · CLI actionable on missing-creds). All HTTP via `httpx.MockTransport`. Suite 2528 → 2541. |
| v18.D | ✅ | **Schema + bootstrap integration.** New `AnalyticsBlock` dataclass in `lamill_toml.py` (`ga4_id: str \| None = None`) + parser (`_parse_analytics` validates `G-[A-Z0-9]{6,12}` shape when present; rejects non-string IDs / malformed shapes) + serializer (omits `[analytics]` block entirely when `ga4_id is None`, keeping round-trip determinism + minimal files). New `_maybe_create_ga4_property(domain, *, skip_ga4)` helper in `bootstrap.py` — returns `(measurement_id, status_message)` tuple with five terminal states: `created` (happy path) / `skipped:--skip-ga4` / `skipped:GA4 OAuth not configured` / `skipped:GA4_ACCOUNT_ID not set` / `failed:<truncated error>`. All failure modes are soft — bootstrap continues without GA4 wired. New `BootstrapResult.ga4_status` + `.ga4_measurement_id` fields surface the outcome to the CLI; new `--skip-ga4` flag on `new bootstrap` short-circuits for dark sites (csinorcal.church etc.). New `GA4_ACCOUNT_ID` row in `apikeys.KNOWN_KEYS` (the parent-account ID for property creation; set once via `lamill settings apikeys set GA4_ACCOUNT_ID <id>`); surfaces as "not-testable when set / missing otherwise" on `apikeys list` (matches the HG-username and CF_ACCOUNT_ID pattern). CLI render block in `_render_bootstrap_summary` prints `✓ GA4 property created · measurement ID G-... written to lamill.toml [analytics]` on success, `↷ GA4 property creation <skip-reason>` on skips, `✗ GA4 property creation failed (continuing) · <error>` on Admin API failures. 14 new tests in `tests/test_v18d_ga4_bootstrap.py` (schema parse + missing-means-none + malformed-rejection + non-string-rejection + round-trip + omit-when-none · helper 5 terminal states · 3 end-to-end bootstrap integrations). Two existing tests updated for the new `KNOWN_KEYS` entry + `SimpleNamespace` stub fields. Suite 2541 → 2555. |
| v18.E | ✅ | **Docs sync wrap.** Marked v18.A-D ✅ (commits 95a5e5f / 909a63b / 62016e1 / 3041a6a). Added `ga4_admin.py` to `docs/architecture.md` § 3 source-tree listing AND § 12 module map (with public surface + credential location). Added `[analytics]` block to § 4 Schemas `sites/<domain>/lamill.toml` example + defaults notes. Added `ga4 {auth}` row to § Projected CLI surface settings subgroup. Suite stays at 2555 / 1 skip (doc-only). |

#### Design notes

**Why "auto-create on bootstrap" not "explicit `--ga4` flag."** Operator's
stated goal is "automatic" GA4 setup. Bootstrap is the moment of
greatest context (operator just registered the domain, about to ship
it). Adding a step that calls Admin API parallels the existing CF
zone create / GH repo create steps — same lifecycle pattern. The
escape valve (`--skip-ga4`) covers the rare exception (dark sites
like `csinorcal.church`). Default-on is the right call for the
common case.

**Why split portfolio (lifecycle) vs SEO pipeline (markup).** The
2026-05-21 v17 scope call drew the line at "portfolio does
conformance / SEO pipeline does the using of GA4." Property creation
is lifecycle-shaped (one-shot per domain at registration time, same
as registering the zone or creating the repo). Markup injection is
content-shaping (recurring concern as sites evolve, Layout components
change, etc.). The boundary is the measurement ID written to
`lamill.toml [analytics] ga4_id` — portfolio writes; SEO pipeline
reads. See `docs/for-seo-check-improvements.md` for the full fork
analysis (Option A chosen 2026-05-21).

**Why `~/lamill/ga4/` not `~/.config/portfolio/ga4/`.**
`[[feedback_no_hidden_config]]` (2026-05-19 operator rule): prefer
`~/lamill/` over `~/.lamill/` etc.; PRDs that recommend hidden paths
predate the rule. GSC's existing `~/.config/portfolio/gsc/` location
predates the rule too — v18 deliberately picks the new location for
GA4. (Side note: GSC migration to `~/lamill/gsc/` is a separate
tracked item; not blocking v18.)

**Why the five pre-wired sites are left alone.** `keralavotemap.site`
(`G-QG4CYZ7MXE`), `lamillrentals.com` (`G-41C0WXB0HR`),
`washcalc.app` (`G-HP39MQPM2M`), `homeloom.app`, and `calcengine.site`
all already have working gtag blocks in their `index.html` /
`BaseLayout.astro` markup. CHECK_080 says they pass; new CHECK_148/149
will validate their markup is well-formed (likely all four — verified
during v18.B implementation). Backfilling `lamill.toml [analytics]
ga4_id` for them is operator-discretion via a one-shot shell loop
or a future polish phase; not part of v18.

**Why the new checks are atomic (CHECK_148 + CHECK_149) instead of
one big upgraded CHECK_080.** v16.A locked the "one assertion per
CHECK_NNN" posture: atomic checks make pass/fail buckets meaningful
on the rendered report, and `project fix` can target individual
checks. Bundling three assertions into CHECK_080 would lose that
resolution.

**Scope decision (2026-05-20).** Dropped v18.C-F (GA4 Data API
foundation + per-page metrics + fleet rollup + acquisition/funnel
consumers). Rationale: same family as the non-goal on paid SEO
analytics (Ahrefs / SEMrush / Moz) — Google's GA4 UI already gives
the operator everything those phases would consume, and reading
analytics into the CLI duplicates UI rather than compressing
operator time. Property creation (v18.D) stays because it's
lifecycle, and static conformance (v18.B) stays because it's the
existing project purpose; consumption stays out.

### v19 — `lamill new trends` command *(new 2026-05-19; renumbered 2026-05-20, was v18; scope shrunk 2026-05-22 — operator narrowed to "just the command + show output"; SerpAPI integration + cluster wiring + shortlist badge + `project seo --trends` + geo/comparison views all dropped per operator's "serp etc not needed at this time")*

Google Trends gives search-interest direction (rising / flat /
declining), seasonality, related queries — signal complementary to
GSC + GA4 that informs the `new domain` brainstorm and `new validate`
decision flow. **v19 ships a standalone `lamill new trends <topic>`
command only**; no cluster integration, no shortlist binding. Operator
runs the command ad-hoc when evaluating a topic; reads the rendered
output. Anything beyond that lives in the operator's separate research
pipeline (same scope-discipline lens as v17/v18 — portfolio renders
signal that's load-bearing for its existing decision flow, but doesn't
re-implement trends.google.com's UI).

#### Phases

| # | Status | Feature |
|---|---|---|
| v19.A | ✅ | **Kickoff planning.** Locked eleven decisions 2026-05-22: (a) **Single command, no validation wiring.** Only `lamill new trends <topic>` ships; future-expansion list (v19.C-F — cluster signal / shortlist badge / `project seo --trends` / geo views / comparison views) dropped entirely per operator's "serp etc not needed at this time". (b) **`pytrends` library only** — SerpAPI's `google_trends` engine dropped; keeps SerpAPI's monthly quota free for `new validate`. (c) **No cluster-snapshot schema change** — v8.D's `research-cluster-v2` schema stays as-is; no ADR-0014 needed; open question 18.D becomes moot. (d) **Per-topic cache** at `data/gtrends/<topic-hash>.json` with 24h TTL matching `hosting_cache` / `seo_cache` convention (closes 18.A). (e) **Default timeframe 12m** — signal/noise sweet spot; `--timeframe {7d, 30d, 90d, 12m, 5y, all}` flag available (closes 18.B). (f) **Output shape** — interest-over-time sparkline-style table + related-queries blocks (top + rising); `--json` for machine-readable. (g) Open questions 18.C (interest-direction threshold), 18.E (primary topic per site), 18.F (pytrends fallback trigger) all moot — no shortlist badge, no per-site integration, pytrends is primary not fallback. (h) **Command placement** under the `new` lifecycle subgroup as a peer to `new domain` / `new validate` (matches "research-before-build" framing). (i) **pytrends boundary mocking in tests** — never hit real Google Trends in the suite. (j) **Soft failure on pytrends errors** — print the error, exit non-zero; no automatic retry / fallback since pytrends is the only path. (k) **`new pyproject.toml` dep**: `pytrends>=4.9`. |
| v19.B | ✅ | **`lamill new trends <topic>` implementation.** New `src/portfolio/gtrends.py` — `fetch_trends(topic, *, timeframe, region, refresh)` returns a `TrendsPayload` dataclass (`interest_over_time` list + `related_top` + `related_rising`). pytrends boundary inside `_fetch_from_pytrends` so tests mock `pytrends.request.TrendReq` cleanly. Per-topic cache at `data/gtrends/<topic-hash>.json` keyed by `(topic, timeframe, region)` so `--timeframe 7d` and `--timeframe 12m` don't share cache entries; 24h TTL via `is_stale()`. `TIMEFRAME_MAP` translates CLI flag values (`7d`/`30d`/`90d`/`12m`/`5y`/`all`) to pytrends strings (`now 7-d`/`today 1-m`/…). Rising-queries values normalized — pytrends emits literal `"Breakout"` for huge spikes which becomes `None` (rendered as `↑↑` instead of a number). New `@new_app.command("trends")` in `cli.py` with `--timeframe` / `--region` / `--json` / `--refresh`. Renderer: interest-over-time as a sampled 30-char bar chart (max 8-row sample to fit on a terminal screen) + direction badge (rising/flat/declining based on first-vs-last value, ±10% thresholds) + related queries (top 10 each side). Exit codes: 0 success, 2 invalid `--timeframe`, 3 pytrends fetch failure. pyproject.toml dep `pytrends>=4.9` added. 20 new tests in `tests/test_v19b_gtrends.py` — cache layer (path stability across runs · path varies by timeframe/region · staleness logic · round-trip · schema-mismatch invalidation · stale-bypass) · fetch_trends (happy path · cache hit · refresh bypass · invalid-timeframe ValueError · GTrendsError on pytrends failure · empty-related blocks · Breakout→None normalization) · CLI integration (table render · `--json` valid JSON · invalid-timeframe exit 2 · fetch-fail exit 3 · `--refresh` bypasses cache). All pytrends calls mocked at `pytrends.request.TrendReq`. Suite 2555 → 2575. |

### v20 — *(reserved — Lighthouse + CrUX, dropped 2026-05-20 per `§ 2 Non-goals` audit; re-confirms `docs/CLAUDE.md § Deferred decisions` 2026-05-09 rejection — PSI is heavy (~15-30s × N domains), CrUX returns `no-data` at portfolio scale, lab ≠ field; may revisit if traffic grows past CrUX threshold across many fleet sites)*

### v21 — *(reserved — Indexing API hook, dropped 2026-05-22 per `§ 2 Non-goals` audit; moved to operator's separate SEO pipeline project — Google's Indexing API is officially `JobPosting` / `BroadcastEvent`-only and effectiveness for general URLs is anecdotal at best. v23.B's GSC Sitemaps API wrapper is the officially-sanctioned post-deploy indexing-ping path and stays in portfolio. See `docs/for-seo-check-improvements.md` "Open question (2026-05-22) — v21 Indexing API hook" for the audit; resurface if (a) Google opens the API for general URLs OR (b) empirical effectiveness gets validated on operator's launched sites + the SEO pipeline decides not to own it.)*

### v22 — *(reserved — Gemini integration for audit-pass model diversity, skipped 2026-05-19; may revisit; renumbered 2026-05-20, was v21)*

Originally proposed as a third LLM family in v12's verify mode
(Claude primary + GPT-4o audit + Gemini cross-check) to strengthen
REVIEW_REQUIRED signal via 3-way model disagreement. Operator opted
out 2026-05-19 in favor of v23 (v21 also subsequently dropped
2026-05-22 to the SEO pipeline project). Slot reserved so re-
introduction doesn't require renumbering.

#### Phases

*None — tier reserved.*

### v23 — *(reserved — GSC Sitemaps + per-URL Indexing status, dropped 2026-05-22 per the v23.A audit; **pre-empted by v13.B + v16.C + v16.D**, not by `§ 2 Non-goals`. The GSC Sitemaps API is already wrapped in `project_seo_diagnostics.py:133-175 fetch_sitemap_details() → SitemapDetail` and rendered in `lamill project seo <domain>` as the `📋 Sitemaps` block; v16.D's `gsc_rollup.domain_coverage_stats()` already feeds `fleet dashboard`'s `Cov %` + `Crawl-err` columns from v16.C's per-URL inspections. v23.B + v23.C were going to add work that already exists. **The sitemap-SUBMIT verb that would be the genuinely-new piece is now part of v24.**)*

### v24 — GSC property auto-provisioning at deploy time *(new 2026-05-22 after the v23 audit + operator's stated 10+-sites-to-launch use-case)*

Post-deploy step that adds a new domain to Google Search Console
without any manual GSC clicks. Mirrors v18.D's GA4 lifecycle posture:
portfolio owns the one-shot property-creation action; SEO pipeline (if
it exists later) owns ongoing optimization concerns. Fits inside the
existing `lamill new deploy` orchestrator after Step 8's live probe.

Three API surfaces compose:

  - **Site Verification API** (`siteverification` OAuth scope) —
    `getToken` returns a TXT record value; `insert` verifies once
    that value lands in DNS.
  - **Search Console API** (`webmasters` write scope; bumped from
    `webmasters.readonly`) — `sites.add()` registers the verified
    domain as an `sc-domain:` property.
  - **Sitemaps API** (same `webmasters` scope) — `sitemaps.submit()`
    points GSC at the site's sitemap.xml.

The CF angle that makes this tractable: DNS TXT writes go through
the existing `cloudflare.create_dns_record()` from v15.R-era zone
work. Operator's bootstrap default is `cf-workers` with NS pointed
at CF, so the new-domain path always has CF DNS write access. No
operator-side dashboard clicks for the verification step.

#### Phases

| # | Status | Feature |
|---|---|---|
| v24.A | ✅ | **Kickoff planning.** Locked 14 decisions 2026-05-22: (a) **Placement: `new deploy` Step 9+, not `new bootstrap`.** Site must be live for sitemap submission to succeed; bootstrap only does `git init` + scaffold. (b) **Portfolio feature, not SEO feature** — one-shot lifecycle action at deploy time; parallels CF zone create + GH repo create + GA4 property create (v18.D). Same scope-discipline call as v18 — SEO pipeline owns ongoing GSC consumption; portfolio owns the property-creation lifecycle. (c) **Property type: `sc-domain:<domain>`** (DNS-only verify; captures all host variants — matches the form `gsc.list_properties()` already returns for the operator's verified properties). (d) **Three API surfaces, NOT collapsed.** Site Verification's `insert` does NOT auto-create the GSC property (separate services). Explicit `webmasters.sites.add()` required after verification. Original Option B from chat is wrong. (e) **OAuth scope bump on `gsc.py`**: `webmasters.readonly` → `webmasters` + `siteverification`. Operator re-runs `lamill settings gsc auth --force` after the bump; one-time. (f) **CF-only DNS writes for v24.** Porkbun TXT-write extension deferred — operator's bootstrap default is `cf-workers` with NS at CF, so new-domain path always has CF DNS access; the long tail of Porkbun-DNS-only sites isn't worth blocking on. (g) **No new `[gsc]` block in `lamill.toml`.** Each step probes Google's APIs for current state (TXT record present? verification done? property in `sites.list()`? sitemap in `sitemaps.list()`?) and skips on present. Source-of-truth stays on Google's side, not in the local file. (h) **Idempotency via API state probes**, matching v15.I's deploy-pipeline pattern: `✓ exists, skipping` / `✓ created` / `↷ warn-skipped: <reason>` / `✗ <error>` per step. (i) **Soft-fail on any GSC step failure.** GSC isn't a load-bearing deploy prerequisite; deploy completes with `gsc_status: failed:<msg>` on the result; CLI prints a yellow warning + dashboard URL. (j) **New `--skip-gsc` flag** on `new deploy` for dark sites / sites where the operator doesn't want GSC wiring. Parallels `--skip-ga4`. (k) **DNS propagation poll** — CF typically propagates within seconds, but the verification API will fail until Google's DNS resolver sees the TXT. Poll for up to 60s with exponential backoff (5s, 10s, 20s, 25s). Surface a wait line so operator knows what's happening. (l) **Sitemap URL convention** — submit `https://<domain>/sitemap.xml`. Pre-flight check at Step 9 entry: HEAD the URL; if 404, soft-skip the sitemap submission with a hint ("site doesn't expose /sitemap.xml; check CHECK_063"). (m) **Lazy-import error pattern** — wrap `from googleapiclient...` and `from google_auth_oauthlib...` etc. in try/except ImportError → raise typed error with `uv sync` hint. Closes the pytrends-style gap. (n) **Phase order strict numerical**: B (helpers + OAuth bump · standalone) → C (deploy pipeline integration · depends on B) → D (docs wrap). |
| v24.B | ✅ | **`gsc_admin.py` module + OAuth scope bump.** New `src/portfolio/gsc_admin.py` — httpx-direct client matching the `ga4_admin.py` / `gh_repo.py` pattern. Public surface: `get_verification_token(domain) → str` (POSTs to `siteVerification/v1/token` with `DNS_TXT` method + `INET_DOMAIN` site type); `verify_domain(domain, *, intervals, sleep) → None` (POSTs to `siteVerification/v1/webResource` with retry loop on 400 "Failed to verify"; raises `VerificationFailedError` after exhausting the 5+10+20+25=60s poll budget; injects `sleep` for tests to run instantly); `add_site(domain) → bool` (probes `sites.list()` first, returns False if `sc-domain:<domain>` already present, else PUTs `webmasters/v3/sites/{encoded-site-uri}` — URL-encodes the colon to `%3A`; returns True if newly added); `submit_sitemap(domain, sitemap_url) → bool` (same idempotency-probe-then-PUT pattern via `sites/{site}/sitemaps/{feedpath}` — URL-encodes both path components); `list_sites()` + `list_sitemaps(domain)` helpers used by the idempotency probes. Typed errors: `GSCAdminError` (non-2xx API response, carries HTTP status + truncated body; matches `CloudflareAPIError` / `GA4AdminError` shape) and `VerificationFailedError` (DNS propagation budget exhausted; operator-action hint includes the `lamill new deploy` retry command + manual-verify URL). `verify_domain` distinguishes `403 insufficient_scope` (permanent — operator needs `lamill settings gsc auth --force` re-consent) from `400 Failed to verify` (transient — retry the poll loop). OAuth scope bump in `gsc.py`: `SCOPES` changed from `["webmasters.readonly"]` to `["webmasters", "siteverification"]` — broader `webmasters` scope is a superset so all existing read paths (`gsc.list_properties`, `gsc.query_with_dims`, `gsc_recrawl.inspect_one_url`, `gsc_rollup.domain_coverage_stats`) keep working. 17 new tests in `tests/test_v24b_gsc_admin.py` via `httpx.MockTransport` — get_verification_token (happy + 403 + empty-token defensive) · verify_domain (first-attempt success + after-one-wait + budget-exhausted with actionable hint + 403-no-retry + actionable-message-in-403) · add_site (newly-added + already-exists idempotent skip + 403 on unverified) · submit_sitemap (newly-submitted + already-submitted idempotent skip + 404 on bad sitemap URL) · list_sites + list_sitemaps return shapes · gsc.SCOPES content assertion. URL-encoding verified via `request.url.raw_path` (httpx-decoded `.path` doesn't carry the encoding). Suite 2575 → 2592. |
| v24.C | ✅ | **Deploy pipeline integration + `--skip-gsc` flag.** New Step 9 GSC block in `_deploy_cf_unified` (`cli.py`) extracted into the `_deploy_step9_gsc()` helper (returns `(status, detail)` tuple — keeps the pipeline orchestrator clean and the step unit-testable in isolation). Five sub-stages: (9a) `gsc_admin.get_verification_token(domain)`; (9b) probe `cloudflare.list_dns_records` for an existing matching TXT, `create_dns_record(type="TXT", name=domain, content=token)` only if absent; (9c) `gsc_admin.verify_domain(domain)` with the 60s propagation poll; (9d) `gsc_admin.add_site(domain)` (returns False if `sc-domain:<domain>` already in GSC); (9e) HEAD-probe `https://<domain>/sitemap.xml`, then `gsc_admin.submit_sitemap()` only if reachable. New `--skip-gsc` flag wired through `new_deploy` → `_deploy_cf_unified` → `_deploy_step9_gsc`. Soft-fail semantics throughout — any GSC failure logs but doesn't abort; deploy completes with the GSC status surfaced on its own outcome line below "Deploy complete." Status values: `created` (happy path) / `already-registered` (fully-idempotent re-run) / `skipped:--skip-gsc` / `skipped:--dry-run` / `skipped:GSC OAuth not configured` (no `~/.config/portfolio/gsc/token.json`) / `skipped:OAuth scope insufficient` (token still on `webmasters.readonly` — operator runs `lamill settings gsc auth --force`) / `failed:get_token:<msg>` / `failed:dns_list:<msg>` / `failed:dns_create:<msg>` / `failed:verify:propagation_timeout` / `failed:verify:<msg>` / `failed:add_site:<msg>` / `failed:submit_sitemap:<msg>`. Lazy imports inside the helper — sites that don't use GSC don't pay the import cost. **Also added**: `cloudflare.create_dns_record()` (v15.R era only had `list_dns_records` + `delete_dns_record`; create was missing) with full ZoneInfo-shaped return; direct httpx.MockTransport tests verify wire format (POST body + path + 403 handling). 14 helper tests covering happy path + 5 skip paths + 3 soft-fail paths + sitemap-deferred branches + cloudflare integration + CLI `--skip-gsc` flag presence; 2 cloudflare.create_dns_record direct tests. Suite 2592 → 2608. |
| v24.D | ✅ | **Docs sync wrap.** v24.A-C marked ✅ in their respective ship commits (`3576af8` / `2e2e277` / `29c4002`). `docs/architecture.md` updated: (a) § 3 source-tree gets `gsc_admin.py` row + `gsc.py` comment refreshed to flag the v24.B scope bump; (b) § Integrations table's GSC row rewritten to enumerate `gsc_admin.py`'s write helpers + the `webmasters` + `siteverification` scopes (replaces the old `GOOGLE_OAUTH_*` placeholder); (c) § 12 module map gets `gsc_admin.py` row with full public surface + the v24.B SCOPES note added to `gsc.py`'s row + `gsc_recrawl.py` row expanded with `inspect_one_url`; (d) the CF-Pages/CF-Workers deploy row in § Deploy adapters table now lists Step 9 explicitly (verify TXT write → verify_domain → add_site → HEAD-probe → submit_sitemap) and adds `--skip-gsc` to the honored-flags list. Doc-only; suite stays at 2608/1 skip. |

#### Design notes

**Why `new deploy` not `new bootstrap`** — operator's framing in
chat 2026-05-22: "bootstrap setup git essentially. since this is to
be done during website setup, this is a portfolio feature, not seo
feature." Bootstrap creates the project dir + git repo; deploy
makes the site live. GSC sitemap submission requires a live URL,
so it can only happen post-deploy. v18.D's GA4 placement at
bootstrap is fine because GA4 property creation doesn't require
the site to be live; GSC does.

**Why this is portfolio-shape, not SEO-pipeline-shape** — same lens
that approved v18 (GA4 property auto-create): one-shot lifecycle
action at deploy time = portfolio. Ongoing GSC consumption (queries,
diagnostics, dashboards) = SEO pipeline (or in our case, already
shipped by v13.B + v16). v24 is purely "register the property and
point GSC at the sitemap"; everything downstream stays where it is.

**Why no `[gsc]` block in `lamill.toml`** — unlike v18.D's
`[analytics] ga4_id` (which the SEO pipeline needs to know to inject
markup), there's nothing downstream of v24 that needs the GSC
property URL recorded locally. `gsc.py:list_properties()` and
`gsc_recrawl.py:find_gsc_property()` already query Google directly
for the property→domain mapping. Source-of-truth stays on Google's
side; idempotency runs through API state probes, not local file
state.

**Why CF-only DNS writes (Porkbun deferred)** — operator's bootstrap
default platform is `cf-workers` with NS pointed at CF, so the
new-domain happy path always has CF DNS write access. Existing
sites on Porkbun-DNS (the legacy fleet) won't benefit from v24's
auto-verification — they'd have to add the TXT record manually
through Porkbun's dashboard. That's acceptable; v24's stated goal
is "10+ sites I need to bring up" which are all going through the
new bootstrap+deploy path. Porkbun TXT extension to `porkbun_dns.py`
becomes a v24.E (or its own tier) only if a concrete
Porkbun-DNS-site use-case emerges.

**OAuth one-time re-consent** — operator's existing
`~/.config/portfolio/gsc/token.json` was issued for
`webmasters.readonly` scope. v24.B bumps `SCOPES` to include
`webmasters` (write) + `siteverification`. Old token will hit
`insufficient_scope` 403s on the new operations. CLI surfaces this
cleanly the first time and tells operator to run
`lamill settings gsc auth --force` for the re-consent. One-time
friction; mechanism is already in place from v15.O.

**The `~/.config/portfolio/gsc/` location** still violates
`[[feedback_no_hidden_config]]` (preserved from pre-rule era). v24.B
does NOT migrate to `~/lamill/gsc/` — that's a separate tracked
migration with its own breakage risk (existing token gets stranded;
re-consent required regardless). Address the migration at the same
time the operator next re-consents, or as a tracked refactor.

**Note** — v24's `gsc_admin.py` joins `ga4_admin.py` as the second
Google-Admin-API client in the tree. Both follow the httpx-direct
pattern (not `googleapiclient.discovery.build`) for testability via
`httpx.MockTransport`. The pattern is now load-bearing for any
future Google Admin API integration.

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

### v25 — CF integration resilience *(new 2026-05-22 PM after dropaudit.co's CF-token pain pattern)*

Three improvements that share one root cause (operator-side CF
token permission gaps) and one shape (operator-action surfaced
cleanly + automation paths that don't require the missing scopes).
Bundled because all three serve the same "mistakes avoided + redo
cycles eliminated + vicarious building" value frame (operator's
2026-05-22 PM reflection): cf. v15.R's pain-removal pattern, just
applied to the next layer of CF friction.

#### Phases

| # | Status | Feature |
|---|---|---|
| v25.A | ✅ | **Kickoff planning.** Locked nine decisions 2026-05-22 PM after dropaudit.co exposed two distinct token-permission failure modes (Step 5.5 DNS:Edit 403; Step 9 Site Verification API not enabled in GCP project). (a) **HTML-file verification FIRST in Step 9** — `siteVerification.getToken(method="FILE")` + write `public/google<token>.html` + commit/push + HEAD-probe-then-verify loop. DNS TXT method preserved as fallback. The file-method path doesn't need `DNS:Edit` on the zone at all; works with any token having the `siteverification` scope (which the operator's already has). (b) **Step 3.5 zone-level DNS:Edit pre-flight probe.** After `ensure_zone` succeeds at Step 3, before Steps 5.5 / 9 attempt any DNS writes, probe whether the token can write to this specific zone. Catches the dropaudit.co pattern (zone-scoped DNS:Edit gap) at the cheapest moment + surfaces operator-action gate. (c) **`lamill settings cloudflare check-token` diagnostic verb** — comprehensive per-account + per-zone scope audit, prints what works vs what's missing, surfaces token-create dashboard URL with pre-populated permissions. (d) **GSC 403 error-body parsing in `_deploy_step9_gsc`** — distinguish `insufficient_authentication_scopes` (re-auth) from `SERVICE_DISABLED` (enable Site Verification API in GCP project; the dropaudit.co case) from `invalid_grant` (token expired). Current code lumps all three as "scope insufficient" which misled operator. Folded into v25.D's diagnostic posture. (e) **ADR-0014** documents the multi-method verification posture + zone-level probe pattern as load-bearing architectural decisions. (f) **HTML file location**: `public/google<token>.html` (Astro convention; ends up at `<domain>/google<token>.html` after build+deploy). (g) **Cleanup posture**: leave the HTML file in place; standard SEO practice (Google re-checks ownership periodically). (h) **Standalone verb naming**: `settings cloudflare check-token` joins the existing `settings cloudflare {token, status}` subgroup (rather than a new `settings cf` namespace). (i) **Phase order strict numerical**: B (zone-level probe, standalone) → C (HTML-file verification, depends on gsc_admin.py extension) → D (check-token verb + GSC error parsing) → E (docs wrap). |
| v25.B | ✅ | **Step 3.5 zone-level DNS:Edit probe.** New `cloudflare.probe_zone_write_capability(zone_id) -> ZoneWriteProbe` helper — POSTs to `/zones/{id}/dns_records` with a deliberately-invalid TTL (`2`; CF requires `1` or `60-86400`). 403 → `can_write=False`, surfaces missing-scope hint; 400 → auth passed, validation rejected the bogus payload → `can_write=True`; 401 → token globally invalid → `can_write=False` with distinct hint; 200/201 (unexpected) → cleanup-DELETE then `can_write=True`; 404 / 5xx → `CloudflareAPIError`. Wired into `_deploy_cf_unified` immediately after `ensure_zone` returns. When `can_write=False`: prints "[red]✗[/] Token cannot write DNS records on this zone" + dashboard URL + token-edit instructions + exit 8 (consistent with the v15.R sequential-code pattern; PRD's "exit 2" sketch superseded by the operational pattern). When `can_write=True`: prints "[green]✓[/] Zone DNS:Edit OK"; pipeline continues. 8 new tests via `httpx.MockTransport`. Shipped 2026-05-22 PM. |
| v25.C | ✅ | **HTML-file GSC verification.** `gsc_admin.get_verification_token(domain, *, method)` accepts `method ∈ {"FILE", "DNS_TXT"}` (default `"FILE"` per v25.A decision a). New `gsc_admin.write_verification_file(project_dir, token) -> Path` writes `<project_dir>/public/<token>` with body `google-site-verification: <token>` (Google spec); raises `GSCAdminError` if `public/` missing (structural fallback signal). New `gsc_admin.wait_for_verification_file_live(domain, token, *, intervals=...)` HEAD-polls `https://<domain>/<token>` with backoff (~180s budget; tries immediately + once per interval). `gsc_admin.verify_domain(domain, *, method)` also accepts method; URL query + site payload shape switches accordingly. `_deploy_step9_gsc` split into `_step9_file_verify` (FILE-method orchestration: get_token → write_file → git add + commit + push → wait_for_live → verify_domain) and `_step9_dns_verify` (DNS_TXT path preserved from v24.C). Orchestrator tries FILE first; on `("fallback", reason)` (no `public/` → HG static-only sites), runs DNS_TXT instead. Soft-fail semantics preserved end-to-end. 14 new tests + 13 v24.C tests migrated to pass `project_dir=tmp_path` (exercises FILE → DNS fallback path naturally). Suite 2642 passed. Shipped 2026-05-23. |
| v25.D | ✅ | **`settings cloudflare check-token` diagnostic + GSC 403 error-body parsing.** `cloudflare.diagnose_token() -> TokenDiagnostic` probes `/user/tokens/verify`, `/accounts` (per-account Pages:Edit / Workers:Edit / Settings:Read), `/zones?per_page=100` (per-zone DNS:Edit via the v25.B `probe_zone_write_capability`). Returns typed `TokenDiagnostic` + `AccountDiag` + `ZoneDiag` dataclasses with flat `missing_account_permissions` / `missing_zone_permissions` lists. New `lamill settings cloudflare check-token` CLI command renders per-account + per-zone table; on gaps prints dashboard URL + the 7 permissions lamill needs + the `lamill settings apikeys set` follow-up. (Pre-populated `?permissionGroupKeys=` URL deferred — CF's encoding isn't well-documented; manual permission list is more reliable.) `gsc_admin.classify_403(error_body) -> (cause, hint)` distinguishes three causes: `insufficient_scope` (re-consent), `service_disabled` (enable Site Verification API in GCP project — pre-populates `?project=<id>` URL when consumer metadata available; the dropaudit.co Step 9 failure mode), `invalid_grant` (token revoked). Wired into all three `_step9_*_verify` 403 branches; status now `skipped:<cause>` instead of generic `skipped:OAuth scope insufficient`. 12 new tests + 2 existing v24.C assertions updated. Suite 2654 passed. Shipped 2026-05-23. |
| v25.E | ✅ | **Docs sync wrap.** Marked v25.B/C/D ✅ in their ship commits; this phase updates `docs/architecture.md`: deploy-verb table row for cf-pages/cf-workers documents the new v25.B Step 3.5 + v25.C FILE-first/DNS-fallback Step 9 flow; module index entries updated for `cloudflare.py` (`probe_zone_write_capability`, `diagnose_token`) and `gsc_admin.py` (multi-method verification helpers + `classify_403`); `Projected CLI surface` adds `check-token` under `settings cloudflare`; `Net additions by phase` table adds v24.A-D + v25.A-E rows. Shipped 2026-05-23. |
| v25.F | ✅ | **Flip Step 9 default to DNS_TXT + Domain property (revert FILE-first).** Operator's permittruck.xyz first-real GSC run (2026-05-23 PM, after re-consenting OAuth + enabling Site Verification API in GCP) exposed a property-type / verification-method mismatch in v25.A's "FILE-first" design: FILE method only verifies URL-prefix properties (`https://<domain>/`), but the rest of the GSC pipeline (`add_site`, `submit_sitemap`) operates on Domain properties (`sc-domain:<domain>`) per v24.A decision (c). Verifying URL-prefix doesn't grant Domain ownership → sitemap-submit 403 "User does not have sufficient permission." Fix: since v25.B Step 3.5 already gates the pipeline on DNS:Edit being available, FILE-first to "avoid DNS:Edit" is no longer needed — DNS_TXT is always reachable. `get_verification_token(method=DNS_TXT)` + `verify_domain(method=DNS_TXT)` defaults flipped; `_deploy_step9_gsc` calls `_step9_dns_verify` first. FILE method preserved as documented fallback / future URL-prefix path (effectively unreachable in normal flow). New [ADR-0016](decisions/0016-gsc-verification-method-and-property-type-coupling.md) documents the verification-method ↔ property-type coupling rule. 1 test renamed + retargeted; suite 2667 passed. Shipped 2026-05-23. |

#### Design notes

**Why bundle three improvements into one tier.** They share a single
root cause (CF token permission model) and a single value frame
(operator-side dashboard pain). Splitting into v25/v26/v27 would
fragment the docs ceremony for work that's coherent as one piece.
Operator-facing the bundle ships as "CF integration got smarter"
rather than three separate fixes.

**Why HTML-file verification first (vs DNS TXT first).** The file
method:
  - Works with any token that has `siteverification` scope (the
    operator's existing token already has it).
  - Doesn't need `DNS:Edit` on the zone (the dropaudit.co failure
    mode — token has zone-scoped DNS:Edit but not for this zone).
  - Doesn't need CF dashboard interaction (no manual TXT add).
  - The file persists harmlessly; Google re-checks periodically;
    removal would un-verify. Standard SEO practice keeps it.

The DNS TXT method has fewer requirements (works for sites that
aren't deployed yet) but in practice all lamill-managed sites are
deployed at Step 9 (it runs after Step 8 live probe). So the file
method is universally applicable for the lamill use case.

**Why Step 3.5 probe attempts a write vs reads policies.** CF's
`/user/tokens/verify` returns a policies array, but the array's
shape is undocumented for machine-parsing — it includes permission
group names like "DNS Write" that don't directly map to API
operations. A real write-attempt against the specific zone is the
cleanest signal: either 200 / 400 (token can write, just our
payload was rejected) or 403 (token can't write). The probe uses a
deliberately-invalid payload to ensure a 400 on success — we never
actually modify state.

**ADR-0014 scope**. The multi-method verification posture + zone-
level pre-flight probe pattern are both load-bearing for future
CF + Google integrations (future Workers Routes work, future GA4
property creation alternatives, etc.). They're not just v25-local
implementation choices; they establish patterns the rest of the
pipeline will reach for. Hence the ADR.

**Why v25.D bundles the GSC error-body parsing** (vs a standalone
fix). v25.D's overarching goal is "operator can diagnose CF + GSC
token issues without trial-and-error mid-pipeline". The GSC 403
error-body parsing serves the same purpose — distinguishes three
distinct failures the operator might encounter, each with a
specific actionable hint. Same shape as the rest of v25.D's
diagnostic work; same module's commit; same testing posture.

### v26 — fleetwide canonical-redirect conformance *(new 2026-05-25 after homeloom.app's 307-redirect blocked Google indexation)*

Adopt apex-as-canonical with permanent (308) redirect from www as the
fleetwide standard, and ship a check that enforces it on `fleet seo` /
`project seo`. The trigger was a real operator-observed regression on
homeloom.app (Vercel-hosted, www-as-canonical with a 307 temporary
redirect from apex) — Google's URL Inspection returned `page with
redirect (NEUTRAL)` for the apex and refused to index the www variant
either. The 307 ate the canonical signal entirely; the homepage was
non-indexable until the redirect type flipped.

The same misconfiguration is structurally likely to recur as the fleet
grows: Vercel and other PaaS providers expose apex-vs-www and 307-vs-308
as separate dashboard controls, and the operator-friendly defaults
don't always match SEO-optimal ones. Without a check, each new site is
a fresh chance to land in the same hole.

#### Phases

| # | Status | Feature |
|---|---|---|
| v26.A | ✅ | **Kickoff planning.** Lock decisions before implementation: (a) **Canonical is apex** for the entire fleet — bare domain (`<domain>`) is the 200 endpoint; matches CF Pages/Workers defaults (most of fleet) + HSTS-preload requirements + cleaner share URLs. www-as-canonical is non-conformant. (b) **Required redirect type is 308 or 301** (permanent); 307 / 302 fail the check — Google holds signal-transfer indefinitely on temporary redirects. (c) **HTTP→HTTPS** is in scope of the same check (`http://<apex>/` must 308→ `https://<apex>/`); folds naturally into the redirect-chain probe. (d) **Trailing-slash policy** is OUT of scope — `<link rel="canonical">` (CHECK_072) + framework defaults handle that orthogonally; a separate check can land later if GSC flags duplicates. (e) **HSTS preload** is OUT of scope — separate concern, lower-priority, separate check. (f) **www DNS absent is PASS** — sites without a www DNS record at all (CF Pages default) satisfy the rule trivially; no www → no possibility of split-canonical. (g) **Severity ramp**: ship as `warn` for one soak cycle (lets operator audit fleet without dashboard going red overnight), promote to `fail` in v26.C after offenders are fixed. (h) **Check ID = 150** (next available; current high is CHECK_149). (i) **Category = `seo/`** (runs as part of `fleet seo` / `project seo`). (j) **No ADR required** — implementation is a checklist of network behaviors, not a load-bearing architectural decision; the convention itself goes in `docs/CLAUDE.md § Locked target shapes` (light, not ADR-weight). |
| v26.B | ✅ | **Ship `CHECK_150_apex_canonical_redirect.py` at `warn` severity.** Probe sequence per domain: (1) `HEAD https://<apex>/` — must be 200 (else `fail`: "apex isn't the canonical endpoint"). (2) `HEAD https://www.<apex>/` — must be 308/301 → `https://<apex>/` (else `fail`: "www is a second canonical" OR "redirect is temporary — 308 needed"); DNS NXDOMAIN on www is `pass` (no www = no split). (3) `HEAD http://<apex>/` — must be 308/301 → `https://<apex>/` (else `fail`: "HTTP→HTTPS not permanent"). Each step ends with one `✓ ✗ ↷` marker (per global output discipline). Severity = `warn` for the soak cycle. ~3 HEAD requests × ~22 domains ≈ 5s under existing probe budget. Reuses the `requests`-session pattern from `seo/_live.py`. Add `tests/test_check_150_apex_canonical_redirect.py` covering: apex-200 + www-308 (pass), apex-307 (fail), apex-200 + www-307 (fail — temp redirect), apex-200 + www-200 (fail — split canonical), apex-200 + www-NXDOMAIN (pass — no www), HTTP-302 (fail), `requests` exception (warn: "could not reach domain"), archived sites (skipped — same posture as CHECK_042). |
| v26.C | ✅ | **`fix_tier_1` dispatch + Cloudflare fixer.** Add `fix_tier_1: FixerSpec` to `check_150_apex_canonical_redirect.py` (mirrors v6 fixer pattern; check-fix pairing). Dispatcher reads `lamill.toml [deploy].platform` and routes to per-platform helpers. **First helper: CF Pages + CF Workers** — toggles `always_use_https` setting via the existing `cloudflare.py` client (`PATCH /zones/{zone_id}/settings/always_use_https`). Covers 7 of 19 offenders (6 cf-pages + 1 cf-workers). Dry-run by default; `--apply` commits (matches CHECK_057 fixer posture). Returns `FixResult(status="fixed", summary="always_use_https → on")` on success; `error` with the specific 4xx/5xx body on API failure. Verification: re-runs the http-probe portion of `run()` after the toggle to confirm `http=200` → `http=308`. |
| v26.D | ✅ | **Vercel fixer.** New `vercel.py` module (parallel to `cloudflare.py`) wrapping the Vercel REST API. New `VERCEL_API_TOKEN` slot in `settings apikeys` with the same atomic-write + connectivity-probe pattern. Per-site fix: locate the project ID by domain (`GET /v9/projects?search=<domain>`); set apex as primary (`POST /v10/projects/{id}/domains/<apex>`); configure www→apex 308 redirect (`PATCH /v9/projects/{id}/domains/www.<apex>` with `redirect=<apex>` + `redirectStatusCode=308`). Covers 11 of 20 remaining offenders post-v26.C (homeloom.app, keralavotemap.site, linkedcsi.live, washcalc.app, civictools.app, lamill.io, iotbastion.com, whizgraphs.com, calcengine.site — plus Bucket E broken sites iotnews.today + lamillrentals.com once their underlying issues are resolved). Dry-run default; verification re-probes apex + www after the changes. |
| v26.E | ☐ | **HostGator fixer.** Reuses existing v11.N UAPI integration to push an `.htaccess` patch (force-HTTPS + 301 www→apex block) to the project's public_html. Covers 1 of 20 remaining offenders (streamsgalaxy.com). Pattern preserves for the 4 no-local-repo HG-shaped sites (maslist.com, veezp.com, yesuinnu.com, carrepairsite.com) if their fleet entries get wired up later. Dry-run default; verification re-probes apex + www + http after the upload. |
| v26.F | ☐ | **Fleetwide audit + promote to `fail` + lock invariant.** Once v26.C/D/E ship: re-run the fleetwide CHECK_150 probe (already exists as `_classify` in the check module — can wrap as a one-off bulk runner). Expect the count to drop from `29 fail / 6 pass` toward fleet-clean. For any remaining offenders (Bucket E broken sites, no-local-repo entries): log per-site in `docs/bugs.md` with platform + reason. Once the fleet is clean (or every remaining offender has a justified exemption logged), promote CHECK_150 from `warn` to `fail` (one-line `SEVERITY` change). Update `docs/CLAUDE.md § Locked target shapes` with the apex-canonical + 308-permanent invariant + cross-link to CHECK_150 so future bootstraps inherit it. |

#### Design notes

**Why apex as canonical (vs www).** Three reasons aligned with the
existing fleet shape and SEO best practices:

  1. **Matches the existing fleet default.** CF Pages and CF Workers
     serve the apex natively without configuration; most of the
     ~22-site fleet already lands at the apex (`<domain>`) as the
     200 endpoint. Standardizing on apex is "lock in what's already
     true for ~all sites" rather than a fleetwide migration.
  2. **HSTS preload requires apex.** Future preload-list submission
     (not in scope of v26, but on the longer roadmap) needs the
     apex as the primary domain; a www-canonical site can't
     meaningfully preload.
  3. **Single canonical = single signal pool.** Either choice avoids
     split-rank, but apex consolidates onto the shorter / cleaner /
     more-shareable URL; given equal SEO weight (Google treats apex
     vs www identically for ranking), the marketing axis breaks the
     tie.

**Why 308 specifically (vs 301).** Both 301 and 308 are permanent
redirects; Google treats them identically for SEO signal transfer.
The check accepts BOTH as pass. 308 is the modern HTTP/1.1 standard
and the default Vercel/CF emit when configured for "permanent
redirect"; 301 is older but still universally supported. Refusing
either would be incorrect; refusing 307/302 is the actual gate.

**Why scope-narrow (no HSTS / trailing-slash / canonical-tag check).**
v26 covers ONE network-behavior axis (redirect-chain status codes +
targets). Folding in HSTS preload status or trailing-slash policy
would conflate concerns and make the check ID overloaded — separate
checks at different IDs are cleaner to audit, fix, and report on
independently. Each gets its own future tier if/when needed.

**Why warn-then-fail (not fail from day one).** Per the global
`feedback_quick_idempotent_default_over_blocking_waits.md` posture +
the v25 dropaudit.co lesson: a new failing check that flips the
fleet dashboard red overnight is operator-hostile, even when the
finding is legitimate. The warn cycle gives the operator one soak
window to audit, plan fixes per affected domain, and ship them
calmly. Promoting to `fail` once the fleet is clean is a one-line
change and locks in the invariant.

**Out-of-scope today, possible later:**
  - Trailing-slash conformance check (when GSC starts flagging
    duplicates across the fleet — currently none observed).
  - HSTS preload conformance + `hstspreload.org` submission helper.
  - `<link rel="canonical">` validation that the tag's `href`
    matches the apex (CHECK_072 only asserts the tag exists; it
    doesn't validate the target URL shape).
  - Bootstrap-time intervention: have `new deploy` set Vercel's
    Primary Domain to apex automatically (only relevant if/when
    the fleet starts bootstrapping more Vercel-hosted sites; most
    are CF, where the default is already correct).

**Why fix lives in v26 (not a separate v27 tier).** The fixer is the
mirror-image of the check — same canonical-redirect axis, just the
write-side. Splitting detect and remediate across tiers fragments the
abstraction; whoever picks up the work would have to cross-reference
two tiers' docs to understand the full pipeline. The v6 catalog's
established pattern is `check_NNN_*.py` declares `fix_tier_1` at
module level; v26 inherits that pattern without ceremony.

**Why dispatch on `[deploy].platform` (vs probe + infer).** lamill
already owns the canonical platform record via `lamill.toml`. Probing
HTTP headers (`server: Vercel`) is heuristic — the 2026-05-25 audit
proved how easily a single pattern (307 apex→www) maps to multiple
platforms with similar defaults. Reading the declared platform is
one TOML load per fix; cheaper than probe-and-classify.

The TOML itself can drift (calcengine.site's declared platform was
stale 2026-05-26 — declared `netlify` while Vercel was serving;
corrected via `lamill settings deploy set`). `CHECK_143 deploy-drift`
catches this class of inconsistency by comparing the declared
platform to a fingerprint of the live response; running it before
v26.D/E fix sweeps surfaces stale TOMLs before they mis-route a
fixer.

**Why ship per-platform fixers in distinct phases (v26.C/D/E split).**
Each platform's API surface is non-trivial enough that mixing two in
one phase muddies testing + commit shape. CF was the easy win (existing
`cloudflare.py` + token; ~one API call); Vercel needs a new module +
token slot + the `settings apikeys` extension. Bundling them would
force the simpler half to wait on the harder half's design decisions.
Each phase ships independent value: v26.C covered 8/19 (CF Pages +
Workers); v26.D covers 11/20 (Vercel, after calcengine.site
re-classification); v26.E covers 1/20 (HostGator). v26.F is the gate.
(Netlify was originally scoped into v26.E based on calcengine.site's
TOML declaration; the fleet actually has zero Netlify sites, so the
Netlify branch is out of scope — keeps v26.E to the one HG site.)

**Why `--apply` (not auto-apply) by default.** Mirrors lamill's
existing `project fix` posture (CHECK_012, CHECK_057, etc.). Operator
runs `lamill project fix <domain> --apply --yes` once they're ready;
default dry-run prints the diff without committing. Matches the
global `feedback_quick_idempotent_default_over_blocking_waits.md`
posture — re-running a dry-run costs nothing; an accidental write
is unrecoverable.

**Why Bucket E (broken sites) ships separately from v26.F.** Bucket E
domains (apex=500, TLS broken, CONNREFUSED) need site-level liveness
fixes that have nothing to do with the redirect chain. v26.F doesn't
wait on them; the operator can log exemptions in `docs/bugs.md`
("`iotnews.today` — apex 500, site offline; v26 doesn't apply until
the site is live again") and the promote-to-fail proceeds without
those domains.

### v27 — per-site todo + stack tracking in `lamill.toml` *(new 2026-05-28; scope expanded 2026-05-29 to absorb `[stack]` alongside `[[todo]]` — one durability pass for both additive tables; v27.A shipped 2026-05-29 — decisions locked + ADR-0017 + `[[todo]]` and `[stack]` shapes in `docs/CLAUDE.md § Locked target shapes`; v27.B shipped 2026-05-29 — both tables first-class in `lamill_toml.py`, drdebug pilot round-trips cleanly; v27.C shipped 2026-05-29 — 27 sites backfilled via `stack_classifier`, 5 flagged for operator review, 3 lack `lamill.toml`; v27.D shipped 2026-05-29 — `project todos` + `fleet todos` read views in new `todos.py` module, 12 tests; v27.E shipped 2026-05-29 — stack-aware checks (CHECK_035/036/037) read `[stack]` first + new `CHECK_151 stack-drift`, 26 tests; v27.F shipped 2026-05-29 — `fleet focus` surfaces each site's top open `high` todo as a `📝` signal (rank 1, below every live signal; `lamill.toml`-only, honors focus's never-blocks-on-a-live-fetch contract), 12 tests; v27.G/H/I shipped 2026-05-30 — surgical upsert helper (`lamill_toml_edit.py`) + `project todos --add/--done/--reopen` write verbs (preserve `[content]`/comments per ADR-0018) + `new bootstrap` auto-writes `[stack]` & seeds the 4-item starter set, 24 tests; v27.J shipped 2026-05-31 — `set_deploy` updates existing files via a generic `set_table` upsert (the deploy-migration + hosting paths were already new-file-only/safe), 5 tests)*

Two additive optional tables for each site's `lamill.toml`:

1. **`[[todo]]`** — canonical per-site work tracker, piloted in
   `drdebug.dev` (3 done + 5 open).
2. **`[stack]`** — explicit frontend-stack declaration (`astro` /
   `vite-react` / `tanstack` / `nextjs` / `sveltekit` / `wordpress` /
   `static` / `none`). Today this is re-inferred in FOUR places —
   `checks/stack/__init__.py` heuristics, `bootstrap.detect_stack_from_pkg`,
   `stack_translate.detect_stack`, and `hosting.py` (WP via the HostGator
   cPanel WordPress Manager API) — with no single source of truth and
   inconsistent vocabularies (`vite` vs `vite-react`, no `wordpress`
   constant outside hosting). HostGator-WP sites have no local markers at
   all; declaration is the only durable way to model them.

Same gating problem applies to both: the loader already tolerates unknown
tables (no `ParseError`, CHECK_059 stays green), but `write()` →
`to_dict()` emits only `schema/deploy/hosting/backend/analytics/notes`
and `tomli_w` drops comments, so any write path (`settings deploy set`,
hosting set, `new bootstrap`) silently erases the table on round-trip.
**Durability before rollout** is therefore the gating requirement, and
shipping both schemas in one writer pass is the cheapest path: same code
change, same ADR, same risk surface.

Fleet baseline (classifier ran 2026-05-29 across 37 sibling dirs):
**14 astro** (agesdk, boxchive, calcengine, dailyring, disclosur,
donready, drdebug, dropaudit, dunam, earnlog, lamillrentals, marginready,
permittruck, vijocherian) · **11 vite-react** (civictools,
cricketfansite, csinorcal, homeloom, isitholiday, keralavotemap,
kwizicle, lamill.io, levents, voltloop, washcalc) · **1 tanstack**
(airsucks) · **9 wordpress-or-static / no-local-repo** (hybridautopart,
streamsgalaxy, iotnews, iotbastion, linkedcsi, thoralox, whizgraphs,
hostkit, harmonia) · **2 sibling-tools / artifacts** (`rankmill`,
`node_modules`). One anomaly: `lamillrentals.com` carries BOTH
`astro.config.mjs` and `vite.config.ts` — likely a half-finished
migration; surfaces as `stack-drift` once v27.E lands.

Decisions locked 2026-05-28/29 (operator): schema string stays
`lamill-toml-v1` (both tables additive optional — old files parse, old
readers ignore); the writer regenerates a canonical `#` header comment
on `[[todo]]` (operator freeform comments are not preserved verbatim;
`[stack]` has no equivalent comment requirement); CLI surface scope —
**plural symmetric** `project todos` / `fleet todos` for the
collection-typed `[[todo]]`; **no operator-facing CLI** for `[stack]` —
it's a tooling-internal declaration (`new bootstrap` writes it, `v27.C`
backfills, stack-aware checks read it, `v27.E` `stack-drift` surfaces
mismatches through the existing `project check` / `fleet check`
surfaces).

#### Phases

| # | Status | Feature |
|---|---|---|
| v27.A | ✅ | **Kickoff / decisions lock — both tables.** (a) Schema stays `lamill-toml-v1`; both `[[todo]]` and `[stack]` are additive *optional* tables. (b) `[[todo]]` field schema: `status ∈ {done, open}` (required); `task` non-empty string (required); `priority ∈ {high, medium, low}` (open items only — `priority` on a `done` item is a `ParseError`). (c) `[stack]` field schema: `framework ∈ {astro, vite-react, tanstack, nextjs, sveltekit, wordpress, static, none}` required when the section is present; optional `build_tool` (e.g. `vite` under astro/tanstack). (d) CLI surface: plural symmetric `lamill project todos <d>` / `lamill fleet todos` for `[[todo]]`; **no CLI for `[stack]`** — it's tooling-internal (`new bootstrap` writes it, `v27.C` backfills, stack-aware checks read it; operator inspects via the file). (e) Writer regenerates a canonical `#` header comment above `[[todo]]`; operator freeform comments are NOT preserved verbatim through a `tomli_w` round-trip. (f) ADR-0017 captures the additive-optional schema-evolution posture — *adding an optional table doesn't bump the schema string* — so future tables inherit the rule rather than re-litigating. (g) `[[todo]]` and `[stack]` shapes locked in `docs/CLAUDE.md § Locked target shapes` so future bootstraps inherit them. **No code in this phase.** |
| v27.B | ✅ | **Both tables first-class (durability — blocks rollout).** Add `TodoItem(status, task, priority=None)` + `LamillToml.todos: list[TodoItem]`; add `StackBlock(framework, build_tool=None)` + `LamillToml.stack: StackBlock \| None`. `_parse_doc` reads `doc.get("todo", [])` and `doc.get("stack")` and validates strictly (→ `ParseError` on bad enums, missing required fields, or `priority` on a `done` item). `to_dict()` emits both when present so all four write paths round-trip them (`project_deploy.py:187` + `:719`, `hosting.py:1695`, `bootstrap.py:2082`). Writer prepends the canonical `#` header comment on `[[todo]]`. Validity rides on CHECK_059 (no new check). Tests: round-trip the drdebug pilot (todos + header comment survive); valid `[stack]` parses; bad `framework` → `ParseError`; both tables absent → fields default empty/`None`; existing v1 files without either are unaffected. |
| v27.C | ✅ | **Backfill `[stack]` fleetwide.** New `src/portfolio/stack_classifier.py` module is the single source of truth for the heuristic (used here and by v27.E's drift check). Backfill swept all sibling dirs (skip `rankmill` / `node_modules` / `tarball`) and wrote `[stack].framework` into each site's `lamill.toml` via `lamill_toml.write()`. Result 2026-05-29: **27 declared** (14 astro / 11 vite-react / 1 tanstack / 2 wordpress via known-WP operator policy: `hybridautopart.com`, `streamsgalaxy.com`); **5 flagged** with no JS or WP markers (`iotbastion.com`, `iotnews.today`, `linkedcsi.live`, `thoralox.com`, `whizgraphs.com`) — operator decides framework; **3 lack `lamill.toml`** (`harmonia`, `hostkit.app`, `levents`) — out of scope. `lamillrentals.com` resolved to `astro` via the dep tiebreaker (`astro` is in deps, `vite.config.ts` is the migration artifact); v27.E `stack-drift` will surface the lingering vite config. The 27 sibling `lamill.toml` files are locally modified (uncommitted in their sibling repos) for operator review + commit. Todos remain LAZY (drdebug stays the reference, no bulk-seed). |
| v27.D | ✅ | **Read views — todos only.** `lamill project todos <d>` (done dimmed; open grouped by priority; counts) + `lamill fleet todos [--priority --status]` (fleetwide worklist). Stack has no read CLI — drift surfaces through the v27.E `stack-drift` check on the existing `project check` / `fleet check` surfaces. Pure reads of `lamill.toml`; no live fetch. |
| v27.E | ✅ | **Stack-aware checks read declaration + add `CHECK_151 stack-drift`.** Existing stack-aware checks (`CHECK_035 vite-version-ok`, `CHECK_036 astro-version-ok`, `CHECK_037 build-dev-scripts`, …) read `[stack].framework` first and skip cleanly when it says `wordpress` / `static`; fall back to the existing config-file heuristic when no declaration is present. New `CHECK_xxx stack-drift` compares declared vs detected (same posture as `CHECK_143 deploy-drift` for platform), catching the `lamillrentals` two-config case + accidental in-flight migrations. |
| v27.F | ✅ | **`fleet focus` `📝` todo signal.** Each site's top open `high` todo becomes a focus one-liner (`headline`/`action` = the task), ranked below 🔴 down / ⚠️ but feeding the same `_add_signal` plumbing in `focus.py`. Reads `lamill.toml` only → honors focus's "never blocks on a live fetch" contract. |
| v27.G | ✅ | **`lamill.toml` upsert helper (`lamill_toml_edit.py`).** Surgical raw-text write primitives so any CLI mutation leaves the rest of the file — comments, `[content]`, table ordering — byte-identical. Foundation for the v27.H verbs (and the deferred legacy-path migration). Regenerates only the `[[todo]]` region from the parsed+mutated list (canonical header reused from `write()`); everything outside that span is untouched. ADR-0018 locks the upsert-not-rewrite write-surface posture. |
| v27.H | ✅ | **Todo write verbs.** `lamill project todos <d> --add "<task>" [--priority] [--due +14d\|ISO]` / `--done <n>` / `--reopen <n>` — mutate via the v27.G upsert helper (no `[content]` loss). `<n>` = 1-based file-order index shown as `[n]` in `project todos`. `--done` strips `priority` (invalid on done items per the locked shape). `--due` bakes a `(revisit ~<date>)` hint into the task text (text-only; no schema field). |
| v27.I | ✅ | **Closure.** `new bootstrap` auto-writes `[stack]` from the detector + seeds the approved 4-item starter set (`[content]` fill-in · SEO check ~2wk · GA4-receiving · GSC verify), idempotent (skips a task that already exists). `docs/CLAUDE.md § Locked target shapes` updated with the `[[todo]]` write-verb + upsert invariants. |
| v27.J | ✅ | **Legacy rewrite paths → upsert.** Audit found only `set_deploy` (`settings deploy set`) was a real clobber risk — it "create-or-update"s existing files and rebuilt the payload, dropping `[stack]`/`[[todo]]`/`[content]`. Now it upserts only `[deploy]` / `[hosting]` via a new generic `lamill_toml_edit.set_table` primitive (full `write()` reserved for new files). The other two suspects — the v10.C deploy-declaration migration (`_execute_write`) and `hosting`'s apply-declarations — both **skip-if-`lamill.toml`-exists** (new-file-only), so they were never a clobber risk and stay on `write()`. 5 tests. |

#### Design notes

**Backward-compatibility invariant — `lamill.toml` files without either
table must keep working everywhere (operator-stated 2026-05-29).** Both
`[[todo]]` and `[stack]` are additive optional in the truest sense: no
parser is allowed to *require* either, and no consumer (checks, deploy
pipeline, hosting, focus, `new bootstrap`, `settings deploy set`) may
fail or warn just because they're missing. A site with a bare `[deploy]`
block stays valid forever. Concretely: `_parse_doc` treats absent tables
as `todos == []` and `stack is None`; backfill (v27.C) is operator-policy,
not a parser requirement; stack-aware checks fall back to the existing
config-file heuristic when `[stack]` is absent; CHECK_059 still passes;
the new `stack-drift` check (v27.E) skips quietly when there's nothing
to compare. Every test plan in v27.B must include the "neither table
present" baseline.

**Why one durability pass for both tables (v27.B).** Same write-path
drops, same schema-evolution posture, same risk surface. Splitting the
writer change across two tiers would mean revising `to_dict()` twice +
re-testing the four write paths twice for no incremental safety. The
combined pass is one ADR, one commit, one round of test churn.

**Why durability is the gate (v27.B must precede v27.C/F).** The risk
isn't a broken deploy — the loader ignores unknown tables, so a
hand-added `[[todo]]` or `[stack]` parses fine today and CHECK_059 stays
green. The risk is silent data loss: `lamill_toml.write()` → `to_dict()`
only emits known sections and `tomli_w` can't carry comments. The four
write paths are `project_deploy.py:187` + `:719` (`settings deploy set`),
`hosting.py:1695` (hosting set), and `bootstrap.py:2082` (`new
bootstrap`). `settings deploy set` is the realistic clobber trigger
(operator adds a custom domain on a site that has todos or a declared
stack — both vanish on save).

**Why declare stack at all (vs continue inferring).** Today four places
redo the inference with inconsistent vocabularies (`vite` vs
`vite-react`, no `wordpress` constant outside hosting). HostGator-WP
sites have no local markers, so every check guesses from side channels.
A `[stack].framework` declaration is the single source of truth: faster
(one TOML read, no file-system probing), cleaner (checks skip-by-
declaration on `wordpress` / `static`), and enables a drift check.
Matches the existing `feedback_trust_operator_fleet_categorization`
posture — *operator declares, tools trust*.

**Why schema stays `lamill-toml-v1` (operator decision 2026-05-28/29).**
Two additive optional tables are still backward-compatible in both
directions: old files (without either) parse, older readers ignore both.
Bumping to v2 would force a decision on how the loader treats v1-vs-v2
files for zero correctness benefit. The reusable posture — *adding an
optional table doesn't bump the schema string* — is captured in the
v27.A ADR so future tables follow the rule rather than re-litigating.

**Why regenerate the comment vs adopt `tomlkit` (operator decision
2026-05-28).** `tomli_w` can't round-trip comments. `tomlkit` would
preserve all operator comments + formatting, but switching the writer to
it touches all four write paths + the serialization tests and risks
output-format churn across the fleet. A regenerated canonical `#` header
is deterministic, zero-dependency, and preserves the *data* losslessly;
freeform notes aren't preserved verbatim. Revisit `tomlkit` only if
comment fidelity becomes operator-felt friction.

**Why plural symmetric `todos`, no CLI for `stack` (operator decision
2026-05-29).** The `cli-naming-plural-symmetric` memory makes
`project todos` / `fleet todos` plural and mirrored across scopes. For
`[stack]`, the operator chose **no operator-facing CLI**: stack is a
tooling-internal declaration that `new bootstrap` writes, v27.C
backfills, and stack-aware checks read — drift surfaces through `project
check` / `fleet check` via the v27.E `stack-drift` check, not a
dedicated verb. Keeps the CLI surface area smaller; operator inspects
the value by reading the file when needed.

**Why `fleet focus` consumes todos (vs a standalone dashboard).** `focus`
is already the "where do I spend my scarce hours today" surface — it
ranks domains by their worst signal and prints an actionable one-liner
each. A high-priority open todo is exactly that kind of signal and slots
into the existing `_add_signal` ranking without a new surface. Reading
`lamill.toml` (a local cache) keeps focus's never-block-on-a-live-fetch
contract intact.

**Why backfill stack (v27.C) but lazy-rollout todos.** Stack is
deterministic for every existing site — the classifier runs in seconds
across the whole fleet and produces a definitive answer. Todos are
operator-authored content that doesn't apply until real work arises;
bulk-seeding empty arrays adds noise without value. Different shapes,
different rollout strategies.

**Why a `stack-drift` check (v27.E).** Catches the `lamillrentals.com`
two-config case automatically and surfaces accidental in-flight
migrations + stale declarations the moment they happen. Same posture as
`CHECK_143 deploy-drift` for the platform field — declaration is the
canonical record; the check enforces that on-disk markers stay aligned.

**Why no `--stack` write verb today (v27.G).** Stack declarations change
rarely (only on a real migration). `settings deploy set` already covers
occasional one-off edits, and a dedicated `--stack` flag is easy to add
later if the operator hits friction. The todo verbs themselves stay
deferred per the reactive-over-proactive posture.

### v28 — topic-aware TLD expansion in `new domain` *(new 2026-06-01 after a family-archive topic surfaced that the generic `.com/.app/.xyz` ladder misses the topically-perfect TLDs — `.family`, `.fm`, `.gift`, `.photos`; v28.A/B shipped 2026-06-01 — decisions locked + `THEME_MAP`/`TOPICAL_TLDS`/`topical_tlds_for` + `lookup_renewal`, 10 tests; v28.C shipped 2026-06-01 — topic→theme selection folded into the vocab call + in-place topical-column merge (`merge_topical=not tlds`), 14 tests; v28.D shipped 2026-06-01 — topical-fit recommendation (under-cap topical beats generic cheap) + premium over-cap topical shown/pickable but never auto-highlighted, 7 tests)*

`new domain`'s TLD ladder is generic (credible primaries + cheap-validation
lane). For topic-fitting projects it should also surface the *topically*
right TLDs — `.family` for a family service, `.fm` for voice/audio, `.video`,
`.gift`, `.photos`, `.church`, … — and let a topically-ideal-but-premium TLD
be a visible choice rather than a silently-skipped over-cap cell.

The plumbing is already there: Porkbun `/pricing/get` prices every TLD they
sell, RDAP gaps fall back to the existing `verify-at-registrar` cell state,
and v3.D already carries `ScoredOption.renewal` / `CellState.renewal` /
`--show-renewal` / `--max-price` + `over_max` ("shown but unselectable").
v28 is two new ideas on top: (1) **topic-aware auto-selection** of which
topical TLDs to merge into a given run's ladder, and (2) **premium / topical
fit** — over-cap topical TLDs stay visible (flagged, with renewal cost) and
can be *recommended*, not filtered out.

**Decisions locked (v28.A, operator 2026-06-01):** (a) **topic-aware
auto-select**, not a static widen — only the topical TLDs matching THIS
run's topic are merged in (keeps the grid bounded; a devtool doesn't get
`.family`). (b) **LLM-assisted matching** — the brainstorm step already
calls OpenAI with the topic, so it also picks the fitting TLDs from a
**curated allow-set** (guardrail against hallucinated/junk TLDs); no second
API call. (c) **Premium-not-hidden** — an over-`--max-price` topical TLD
renders flagged `premium · topical fit` with its renewal price and is
*pickable*, instead of being skipped. (d) **Renewal surfaced** for topical
picks (these are reg-cheap / renew-expensive: `.family` $5.66→$31.41,
`.life` $2→$29, `.fm` $88 flat). (e) Manual `--tlds` override stays the
power-user escape hatch.

#### Phases

| # | Status | Feature |
|---|---|---|
| v28.A | ✅ | **Kickoff / decisions lock.** Approach (topic-aware auto-select), matching mechanism (LLM-assisted from a curated allow-set), premium-not-hidden + renewal-surfacing rules, topical-fit scoring posture — all locked above. Curated topical-TLD set + theme map defined in v28.B. No code. |
| v28.B | ✅ | **Topical-TLD set + theme map + renewal lookup.** `THEME_MAP` (theme → TLDs) + flat `TOPICAL_TLDS` curated allow-set + `topical_tlds_for(themes)` resolver in `suggest.py` — family/memories (`.family .gift .photos .life`), voice/audio (`.fm`), video (`.video .cam`), photos (`.photos`), faith (`.church`), music (`.band .fm`); all confirmed Porkbun-priced. `availability.lookup_renewal` parallels `lookup_price` (renewal = the true keep cost). Renewal already populated per-cell (v3.D), so making it *visible* in the grid rides on v28.D's display. 10 tests. |
| v28.C | ✅ | **Topic-aware selection.** Folded into the existing v3.D vocab call (no second API call): `extract_vocab_and_themes` returns practitioner terms **+** themes (constrained to `THEME_MAP` keys via a `THEMES:` trailer; vocab parser ignores that line). `run_validation_pipeline(merge_topical=...)` merges `topical_tlds_for(themes)` into the run's `columns` in place (bounded `max_extra=4`, idempotent), so grid + pick-validation stay in sync without a return-shape change. CLI passes `merge_topical=(not tlds)` — topical TLDs only augment the **default** ladder; `--tlds` override unchanged. Heuristic `_themes_from_keywords` fallback on API failure / cached runs. 14 tests. |
| v28.D | ✅ | **Topical-fit recommendation + premium shown-not-highlighted.** `_decide_pick` gains a topical lane: an **under-cap** topical TLD (e.g. `.family` at $5) is recommended with `why = "topical fit"`, ranking above the generic cheap lane (beats a generic `.xyz`). An **over-cap** topical TLD is *never* the highlighted/auto pick (operator rule 2026-06-01 — picks it only in rare cases); it stays visible (`$N!` cell, + renewal when it differs) and manually pickable, and `filter_pickable_rows` keeps its row instead of dropping it. When only a premium topical is available, the Pick reads `— · premium topical available — pick manually`. Renewal stays visible via the existing `↑Nx` cliff marker. |
| v28.E | ☐ | **(Reactive) Tune the theme map** as more project topics surface; promote/demote topical TLDs by track record. |

#### Design notes

**Why topic-aware, not a static widen (v28.A).** Adding `.family` /
`.church` / `.fm` to the universal ladder shows them for *every* topic — a
devtool brainstorm doesn't want a `.family` column. Topic-aware selection
keeps the grid bounded and the columns relevant; it also lets the
recommendation favor a topical match only when the topic actually fits.

**Why LLM-assisted from a curated allow-set (v28.A).** Free-text topics
("weekly WhatsApp service… private family archive…") map to themes more
robustly via the LLM than via keyword heuristics, and the brainstorm step
*already* calls OpenAI with the topic — so it's near-zero extra cost. The
**curated allow-set** is the guardrail: the model may only pick from TLDs we
price-check and vouch for, so it can't surface a hallucinated or absurdly
expensive registry. Heuristic keyword match is the offline fallback.

**Why premium-not-hidden + renewal surfaced (v28.A).** The topically-perfect
TLD is often the expensive one (`.fm` $88, `.family` renews $31). Silently
filtering it by `--max-price` hides the *best* option; instead it renders
flagged `premium · topical fit` so it's a deliberate operator choice. And
because these TLDs are reg-cheap / renew-expensive, the grid must show
**renewal** (the real keep-forever cost), not just first-year registration —
the data is already on `CellState.renewal` (v3.D), v28 just makes it visible
for these picks.

**Why this reuses v3.D scaffolding (v28.B/D).** `ScoredOption.renewal`,
`CellState.renewal`, `--show-renewal`, and `--max-price` + `over_max` already
exist. v28 doesn't add a pricing path — it adds the curated set, the
topic→TLD selection, and the premium-pickable + topical-fit-scoring
behavior on top of the existing grid.

### v29 — seed `lamill.toml [content]` from the bootstrap interview *(new 2026-06-03 after the operator noticed `new bootstrap` collects ICP but writes it only to `AI_AGENTS.md`, leaving `lamill.toml [content]` an empty skeleton with a nag-todo)*

`new bootstrap` already collects ICP (and 4 other prose sections) and writes
them to `AI_AGENTS.md`, but `lamill.toml [content]` is appended as a hardcoded
all-empty `CONTENT_SKELETON` (`lamill_toml_edit.py:297`) with a "Fill in
[content]" nag-todo. ICP is authored once, stored twice, the second copy left
blank. The interview and the `[content]` block were built at different times —
the block arrived in the v27.I / 2026-05-30 migration — and were never unified.
v29 closes the seam: collect the `[content]` fields during the interview and
seed the block, so a fully-answered bootstrap ships todo-free.

**Decisions locked (operator, 2026-06-03):** (a) **ICP reuse, verbatim** — `[content].icp`
is the `AI_AGENTS.md ## ICP` answer copied as-is (a paragraph); single source,
no double-ask, the field's "one sentence" intent is relaxed and the skeleton
comment updates to say so. (b) **All `[content]` fields optional** — every field
is skippable; a blank keeps the skeleton default line and re-seeds the "Fill in
[content]" todo *for the blank fields only*, honoring the `[content]` "empty is
better than wrong" rule and the `lamill.toml` additive-optional invariant.
(c) **One paste, not 7 new prompts** — the structured fields ride the existing
LLM paste template + `bootstrap_paste` parser; interactive per-section fallback
mirrors today's flow.

#### Phases

| # | Status | Feature |
|---|---|---|
| v29.A | ☐ | **Kickoff / decisions lock.** (a) ICP-reuse-verbatim, (b) all-fields-optional + todo-reseeds-only-blanks, (c) paste-template collection — locked above. Decide ADR-vs-shipping-history for the ICP coupling. No code. |
| v29.B | ☐ | **Values-aware seed renderer.** `content_block(values)` in `lamill_toml_edit.py` fills provided fields, preserves the guidance comments, leaves unset fields at `= ""`. `ensure_content_block(repo, values=None)` gains the arg. Handles the multi-line ICP paragraph (safe TOML string) + `secondary_keywords` list. **All-empty output stays byte-identical to today** (CHECK_059 + existing tests green). Unit tests: empty / partial / full / escaping. |
| v29.C | ☐ | **Collect the 8 fields.** Extend the paste template + `bootstrap_paste` parser + `canonical_sections` so the structured fields arrive in the same single paste; `icp` pulled from `operator_inputs["ICP"]` (not re-asked); interactive fallback, every field Enter-to-skip. Tests: parse, ICP-reuse, all-skip. |
| v29.D | ☐ | **Wire into bootstrap + todo.** Pass collected values to `ensure_content_block` (`bootstrap.py:2139`); seed the "Fill in [content]" todo only when ≥1 field is still blank, naming which. `--non-interactive` smoke + test that a fully-answered bootstrap ships todo-free. |
| v29.E | ☐ | **(Reactive)** Tune which fields are worth prompting as real bootstraps surface friction; promote/demote per track record. |

#### Design notes

**Why reuse the ICP paragraph (v29.A).** The operator already authors a rich,
specific ICP at bootstrap. Re-asking for a one-liner is double work for the same
fact; copying verbatim makes `AI_AGENTS.md ## ICP` the single source and the TOML
a faithful mirror. Cost: `[content].icp` holds prose rather than a one-liner —
acceptable, rankmill reads it whole.

**Invariants honored.** Seeding goes through the surgical `lamill_toml_edit`
append (ADR-0018 upsert-not-rewrite), never a `write()` that would clobber
`[content]`/comments. The block stays additive-optional — absent or empty is
still valid everywhere, and the all-empty render must stay byte-identical to
today so CHECK_059 and the existing round-trip tests stay green.

**Main implementation subtlety (v29.B).** The ICP paragraph carries quotes,
apostrophes, and newlines → emit it as a safe TOML multi-line string;
`secondary_keywords` emits as an array. That's the bulk of v29.B's test surface.

**Docs same-commit.** prd.md phase rows, `architecture.md` (bootstrap mechanism +
the content-seed renderer). A short ADR for the ICP-coupling decision is a v29.A
call (ADR vs. `shipping-history.md` note).

## The [content] and [todo] blocks: what each is for

`lamill.toml` carries two human-authored blocks that look similar at a glance but do different jobs. Keeping them separate keeps the file honest.

**`[content]` is declarative configuration.** It describes what this site *is*, content-wise: who it's for, what it ranks for, what tone it speaks in, what law or pain it addresses. It is stable — fields rarely change after a site is conceived. It is authored by the human and consumed by rankmill as the source of truth for content generation and audits. lamill and rankmill both read `[content]`; only the human writes to it.

**`[todo]` is imperative work state.** It tracks what needs to happen next on this site — pending tasks, blockers, deadlines. It is volatile, edited constantly, and reflects the site's current operational status rather than its identity. It has no fixed schema.

The test: if a field still makes sense a year from now without edits, it belongs in `[content]`. If it would be stale by next week, it belongs in `[todo]`.

The boundary matters because the two blocks have different lifecycles. `[content]` wants to be edited rarely and carefully, because its values seed every piece of content rankmill produces and every audit check rankmill runs — a wrong `icp` propagates into every draft and every report. `[todo]` wants to be edited freely. Mixing them invites churn on fields that should be stable, and stagnation on fields that should move.

rankmill's own working state — what's been generated, what's been audited, when — lives in `sites/<domain>/content-draft/` (drafts), `sites/<domain>/rankmill-output/` (analysis), and `rankmill-data/` at the workspace root (fleet-wide caches and snapshots). It does not live in lamill.toml.

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
