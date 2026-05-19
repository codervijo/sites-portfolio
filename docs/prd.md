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
   `lamill new research <topic>` walks a mechanical SERP gate plus an
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

- Domain ideation → `lamill new suggest <topic>` (v2/v4 Power 1).
- Niche validation → `lamill new research <topic>` (v8 + v12).
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
`project diagnose`, `new suggest`, `new research`, `settings *` — is
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
| v7.C | ✅ | Age tracking — `launched` + `domain_created`. Two new fields on each row in `data/portfolio.json`. `launched` manual via `lamill settings project set-launched <domain> <YYYY-MM-DD>`, falls back to first-commit-date inference; `domain_created` via RDAP `registration` event date. `fleet info cleanup --refresh-rdap`. Both surface as columns in `fleet dashboard` (Site age + Domain age). |
| v7.D | ✅ | `fleet focus` enhancements + P4 age-aware SEO grading. Five fixes: (1) variant-aware site-down; (2) platform-aware action text; (3) `--refresh` flag; (4) age-aware SEO signal suppression for sites <90d old with `--include-young` to override; (5) idle (🟡) signal for forwarder/parked. P4 closed the age-awareness loop in `seo_runtime.overall_status` — masks imp + pos cells when site is young. |
| v7.E | ✅ | `fleet repos` audit + naming-consistency cluster + archived state. Read-only audit of every `sites/<domain>/`'s git-layer state. Three new git-category catalog checks: CHECK_040 (git-remote-name-matches-domain), CHECK_041 (dir-matches-portfolio-entry), CHECK_042 (live-final-url-matches-domain). Archived support via `TOMBSTONE.md` marker or portfolio.json category in `{to be deleted immediately, archived, tombstoned}`. |
| v7.F | ✅ | `project diagnose <domain>` — five-layer auto-investigate. Probes DNS / HTTP / TLS / repo / inventory and synthesizes a root cause + suggested fix. Seven heuristics catching real-world patterns: Vercel deployment-not-found, Namecheap parking, intent-vs-actual mismatch, TLS alert 112 on intended platform, no-DNS-at-all, normal live site, forwarder/parked decision. |
| v7.G | ✅ | Tool rename: `portfolio` → `lamill` (light). `[project.scripts]` entry exposes both `lamill` (canonical) and `portfolio` (legacy alias). Python package stays `portfolio` internally. Installed system-wide via `uv tool install --editable`. |
| v7.H | ✅ | GSC sitemap health + dark-site detection + CF edge-cache check (CHECK_057). (1) GSC sitemap health: `probe_gsc` keeps per-sitemap `errors`/`warnings`/`isPending`/`lastDownloaded`; new `gsc_sitemap_health` signal. (2) Dark-site detection from robots.txt: classifies as `dark` when `User-agent: *` carries `Disallow: /` with no overriding `Allow: /`. (3) `CHECK_057 cf-edge-cache-fresh` + tier-1 fix + `settings cloudflare {token,status}`. |

### v8 — SERP research for new projects ✅

#### Phases

| # | Status | Feature |
|---|---|---|
| v8.A | ✅ | `new research <topic>` core command. *(absorbed by v8.D 2026-05-14)* |
| v8.B | ✅ | Multi-keyword cluster mode. *(absorbed by v8.D 2026-05-14)* |
| v8.D | ✅ | Research module v2 — real SERP + three-gate framework + operator profile. Rebuild from AI-only synthesis to SerpAPI primary with synthesis fallback. Phase 1 (SerpAPI fetch + per-query dated snapshots); Phase 2 (three-gate logic — Market / SERP-with-7-classifiers / Moat-interactive-prompt); Phase 3 (operator profile read from `sites/portfolio/lamill.toml [operator]`). Verdict vocabulary: GO / NICHE-DOWN / NO-GO. Schema bumped; old caches archived. |
| v8.E | ✅ | Primary-pass payload assembly. `interpretive_pass.build_payload(cluster, operator_profile)`. Pure data-shaping helper. |
| v8.F | ✅ | Primary-pass prompt rendering. `interpretive_pass.render_primary_prompt(payload, operator_profile)`. Operator-var placeholders substituted; payload JSON in a fenced block. `UnfilledPlaceholderError` raised at render time on drift. |
| v8.G | ✅ | Primary-pass response parser. `interpretive_pass.parse_verdict(markdown)` + `ParsedVerdict` dataclass + `VerdictParseError`. Splits on `### <header>` boundaries. Strict on `verdict` / `confidence` / `reasoning` and canonical token sets; tolerant on optional sections, bullet markers, header case, NICHE-DOWN separator variants. |
| v8.H | ✅ | Primary interpretive pass runner. `interpretive_pass.run_primary_pass(cluster, ...)`. End-to-end build_payload → render → run_claude_text → parse_verdict. Returns `InterpretivePassResult`. |
| v8.I | ✅ | Wire primary pass into `new research` orchestrator. First user-visible v8.E-series feature. Renders "Interpretive verdict (Claude):" section in human output. Snapshot schema bumped to v2.1. |
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
| v10.B | ✅ | Operator CLI surfaces — `lamill settings project set-deploy <name> <platform>` (interactive prompts when stdin is TTY; `--non-interactive` rejects on missing required fields; hostgator/custom walks cpanel + FTP breadcrumbs) + `lamill settings project show-deploy <name>` (pretty table renderer + `--json`). `set-launched` also moved into the same `settings project` namespace 2026-05-18 for consistency (was `project set-launched` v7.C). Shipped 2026-05-18 across `d28c516` → `890841e` → show-deploy commit. |
| v10.C | ✅ | Auto-write integration — `new bootstrap` writes `lamill.toml` as part of scaffolding (platform priority: `--platform <X>` flag → infer-from-existing-configs → `cf-pages` default; `hostgator/custom` rejected at bootstrap, use `settings project set-deploy` instead). `fleet repos --add-deploy-declarations [--dry-run/--apply] [--include-ambiguous]` migration sweep walks every `sites/<dir>/`, classifies (unambiguous / ambiguous / manual / already-declared / archived), writes safe cases. Shipped 2026-05-18 across `fd725ff` + migration-sweep commit. v10.D validation phase next — runs this against the real fleet. |
| v10.D | ✅ | **Validation phase** — real-fleet sweep. Run the migration against the actual ~22-domain fleet; review the dry-run plan; `--apply` the unambiguous cases; handle ambiguous + manual-entry cases interactively via `settings project set-deploy`. End state: every applicable sibling `sites/<domain>/` repo has a valid `lamill.toml` committed. Surfaces bugs / edge cases that only appear against real config files. ~2-3h (mostly running the tools, fixing edge cases that surface). |
| v10.E | ✅ | Drift detection + lamill.toml conformance checks. Three deploy-category checks: `CHECK_058 has-lamill-toml`, `CHECK_059 lamill-toml-valid`, `CHECK_143 deploy-drift`. Drift compares declared platform against a best-effort classification of the live HTTP snapshot (WordPress generator / title / wp-includes paths → hostgator; `*.vercel.app` / `*.pages.dev` / `*.netlify.app` in final URL or redirect chain → that provider). Canonical drift case `iotnews.today` (declared=vercel, classified=hostgator via WP title) fires `fail`. 26 tests. |
| v10.F | ✅ *(absorbed by v11.A 2026-05-18)* | HostGator cPanel integration — folded into v11.A's unified 3-provider hosting walker (Vercel + CF Pages + HostGator). One `fleet hosting` command replaces two (`fleet hosting` + `fleet hostgator`); single rollup table; operator no longer has to remember which command surfaces which provider. See v11 below. |
| v10.G | ✅ *(absorbed by v11.B 2026-05-18)* | SFTP deploy abstraction — renumbered v11.B. Active hosting operations cluster with v11.A; `new deploy <domain>` becomes polymorphic, reading `lamill.toml` to dispatch CF Pages / Vercel / SFTP-to-HG. See v11 below. |

### v11 — active hosting layer *(renumbered 2026-05-17, was v10; scope expanded 2026-05-18 to absorb v10.F + v10.G)*

The hosting cluster — read-only inventory across every provider in
the fleet, plus the active deploy verb that operates against those
providers. v11.A is the unified 3-provider walker (Vercel +
Cloudflare Pages + HostGator UAPI); v11.B is the polymorphic
`new deploy` verb that adds an SFTP path for HostGator/custom
declarations. **See `docs/architecture.md § 3 Mechanisms / § 4
Schemas / § 9 Active implementation plans / § 10 Risks` for the
technical design.**

#### Phases

| # | Status | Feature |
|---|---|---|
| v11.A | ⏳ | `fleet hosting` — unified 3-provider walker (Vercel + CF Pages + HostGator UAPI). Per-site `provider` / `status` / `last_successful_deploy_at` / `consecutive_failures` plus HG-specific optional fields (`disk_used_mb` / `wp_version` / `install_path`). Cached snapshot at `data/hosting/<date>.json`; `--refresh` re-walks; `--only <domain>` single-row probe; `--provider {vercel\|cf-pages\|hostgator}` filter; `--apply-declarations` writes `lamill.toml` for HG sites that have a local repo but no declaration yet (CF/Vercel already inferable per v10.C). Two HG accounts authenticated via `HOSTGATOR_TOKEN_GATOR3164` + `HOSTGATOR_TOKEN_GATOR4216` known-keys; cPanel host auto-derived from env-var suffix. Three slices: P1 walkers + cache (HG walker is the net-new chunk), P2 renderer + CLI + apply-declarations, P3 dashboard + diagnose integration. ~16-22h, ~14 commits. |
| v11.B | ⏳ | `new deploy <domain>` — polymorphic deploy verb. Reads `lamill.toml`, dispatches: `cf-pages` → existing v3.C logic; `vercel` → existing-equivalent; `hostgator` / `custom` → NEW SFTP push flow; `none` → reject. Adds a third write surface — needs ADR-0009 reversing or refining ADR-0003's "two write surfaces only". ~14-20h. **Design open** — see "Open questions for v11.B" below; gating questions 11.O-T need resolution before code lands. |

#### Design notes

**Problem statement.** v10 closed the *declaration* gap (every
applicable sibling repo now declares its deploy target in
`lamill.toml`, and CHECK_143 surfaces drift between declaration and
live reality). The active-hosting gap is still wide open:

1. The tool can't ask Vercel / CF Pages / HostGator directly whether
   a deploy succeeded — it infers from filesystem markers and DNS
   heuristics in `project diagnose`, missing stale deploys, forgotten
   projects, and build regressions (a clean `vercel.json` checked in,
   but the project hasn't built successfully in months and platform
   quietly leaves the previous version live).
2. There's no programmatic inventory for HostGator-hosted sites —
   the operator has to log into two cPanel accounts to enumerate
   domains, disk usage, WordPress versions. The v10.E classifier can
   tell when a site *is* HG-hosted; it can't enumerate the inverse
   ("what's on this HG account that I haven't declared yet?").
3. There's no `new deploy` path for HG/custom sites — bringing up a
   new HG-hosted site means manual SFTP outside the tool, and
   updating a deployed HG site requires the same manual workflow
   each time.

**Goals.**

v11.A (read-only inventory):
- `lamill fleet hosting` as a peer of `fleet seo` — same shape:
  read-only, cached, refreshable, emoji table.
- Walk Vercel + Cloudflare Pages + HostGator UAPI using stored tokens.
- Match each provider's project/account to a fleet domain by
  configured custom domain (Vercel/CF) or cPanel addon-domain list
  (HG) — server-side truth, not local-file inference.
- Persist results to `data/hosting/<YYYY-MM-DD>.json` mirroring the
  `data/seo/` shape. Snapshot is git-tracked.
- Surface a deploy-platform conflict signal when the same domain
  appears across providers (drift) — strengthens v10.E's CHECK_143.
- `--apply-declarations` closes the original v10.F use case: writes
  `lamill.toml` for HG sites that have a local repo but no
  declaration yet. CF/Vercel sites are already inferable via
  `infer_from_existing_configs()` (v10.A) and were migrated by
  `fleet repos --add-deploy-declarations` (v10.C).

v11.B (active deploy):
- `lamill new deploy <domain>` becomes a polymorphic dispatch verb.
- `cf-pages` / `vercel` declarations: reuse existing v3.C logic.
- `hostgator` / `custom` declarations: walk the `[hosting]` block in
  `lamill.toml`, push the configured source to the configured
  `public_html_path` via the chosen auth method (TBD — see open
  questions 11.O-T).
- Idempotent + dry-run-by-default per the v3.C convention.

**Non-goals** (deferred):
- Triggering deploys on CF Pages / Vercel (v11 reads their state but
  never POSTs a redeploy — `git push` is the contract).
- Walkers for Netlify / GH Pages / direct-Worker / Render —
  everything outside Vercel + CF Pages + HostGator is "skip" with a
  rendered "—" row.
- Cost / pricing reports.
- Auto-flagging consecutive failures as a `fleet focus` signal.
- Real-time webhooks.
- WordPress-specific deploy ops (theme/plugin/uploads). v11.B is
  static-SFTP-only; WP-aware deploy is a later phase.
- Auto-rewriting drifted `lamill.toml` declarations.
  `--apply-declarations` is scoped to "site has no declaration yet"
  per 11.N; drift remediation stays manual (operator runs
  `lamill settings project set-deploy <domain> <correct-platform>`
  after CHECK_143 fires).

**User journey scenarios.**

```text
$ lamill fleet hosting
Reading data/hosting/2026-05-19.json (1.2h old · use --refresh to re-fetch)

Domain                Provider          Status  Last Success           Failures
airsucks.com          cloudflare-pages  ✓       2026-05-14 16:12 UTC   0
calcengine.site       vercel            ✓       2026-05-13 09:44 UTC   0
hybridautopart.com    hostgator         —       —                      —     [disk 1.4 GB · WP 6.7]
iotnews.today         hostgator         —       —                      —     [disk 89 MB · WP 6.6 · drift!]
linkedcsi.live        vercel            ✗       —                      5
kwizicle.com          cloudflare-pages  💤      2026-02-08 22:01 UTC   0

  22 live-site/forwarder domains · 1 ERROR · 1 stale · 1 drift
  Run `lamill fleet hosting --refresh` to re-probe.

$ lamill fleet hosting --provider hostgator
<filtered to HG-only rows>

$ lamill fleet hosting --apply-declarations --dry-run
Inspecting HG sites without lamill.toml declarations…
Nothing to apply — every HG site with a local repo already declares.
(carrepairsite.com / thakinaam.com detected on HG but no local repo;
 skipped — `lamill new bootstrap <domain>` to create one first.)

$ lamill new deploy iotnews.today    # post fixing declaration to hostgator
Reading lamill.toml — platform=hostgator, ftp_host=gator4216.hostgator.com
Connecting via SFTP (key auth — ~/.ssh/id_ed25519)…
Pushing dist/ → /home3/<user>/public_html/iotnews.today/ …
  Uploaded 47 files (2.3 MB). 0 deleted. 0 errors.
Done. Verify: lamill project diagnose iotnews.today
```

`--refresh` and `--only` follow existing `fleet seo` conventions.

**Open questions (v11.A — answered 2026-05-18, gate-cleared).**

| # | Question | Resolution |
|---|---|---|
| 11.A | `VERCEL_TOKEN` scope — personal token only, multi-token, or single-token + team-list config? | **Personal token only.** Operator-scale tool, single user. |
| 11.B | `--only` flag name collision with `fleet seo --only wip\|all`? | **Drop the scope flag entirely** — always operate on live-site + forwarder. `--only DOMAIN` is the single-domain probe. |
| 11.C | `RECENT_DAYS` / `STALE_DAYS` thresholds — configurable or hardcoded? | **Hardcoded constants** for v11.A. Revisit if real fleet data shows the thresholds are wrong. |
| 11.D | Deployment history lookback — cap or unbounded? | **Two-tier (option 3)** — stop at 10, mark ≥10 consecutive failures. |
| 11.E | Domain ↔ project matching — bare-host normalize or exact match? | **Bare-host normalize.** Matches user intent. |
| 11.F | Provider conflict (same domain on both)? | **Two rows in the snapshot** — one per provider — make drift visible. Rollup counts treat as a single conflict. |
| 11.G | Hosting snapshot — new file or join existing? | **New file** `data/hosting/<date>.json`. Mirrors every other layer. |
| 11.H | Walker error surfaces — 401 vs 5xx? | **Skip-affected-provider on 401**; per-row `error` on 5xx / rate-limit (option 1). |
| 11.I | Snapshot retention? | **Keep forever, git-tracked.** Same as every other layer. |
| 11.J | Test strategy? | **Mock at `httpx`/`requests` layer; no CI calls to real APIs.** Same pattern as `tests/test_gsc_recrawl.py`. |
| 11.K | HG token storage shape? | **Two named env vars in `apikeys.KNOWN_KEYS`** — `HOSTGATOR_TOKEN_GATOR3164` + `HOSTGATOR_TOKEN_GATOR4216`. Add more when a third account appears. Matches `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` precedent. |
| 11.L | cPanel host derivation? | **Auto-derive from env-var suffix.** `HOSTGATOR_TOKEN_GATOR3164` → `https://gator3164.hostgator.com:2083`, username=`gator3164`. No separate override env var (YAGNI). |
| 11.M | `HostingRow` schema — typed optional fields vs `extra: dict` blob? | **Typed optional fields.** `disk_used_mb: int \| None`, `wp_version: str \| None`, `install_path: str \| None`. Matches every other dataclass in the codebase. |
| 11.N | `--apply-declarations` scope — only fix missing, or also rewrite drift? | **Only fix missing.** Matches `fleet repos --add-deploy-declarations` (v10.C) safety posture. Drift remediation stays manual via CHECK_143 + `settings project set-deploy`. |

**Open questions (v11.B — gating code).**

| # | Question |
|---|---|
| 11.O | Verb split — keep one `new deploy` (polymorphic dispatch) or split into `new deploy <domain>` (first-time setup) + `project push <domain>` (recurring SFTP push)? CF Pages git-auto-deploys after initial setup; SFTP needs an explicit push every time. |
| 11.P | What gets pushed — `dist/` (CF-Pages parity), source files, or operator-configured path in a new `[deploy].source_dir` / `[hosting].deploy_source` field? |
| 11.Q | Auth — SSH key (read from `~/.ssh/id_*` or operator-configured path), cPanel password (stored in `portfolio.env`), or cPanel UAPI file-upload (avoids SFTP libraries entirely; UAPI has an upload endpoint)? |
| 11.R | WordPress in or out for v11.B — `hybridautopart.com` + `streamsgalaxy.com` are WP-on-HG; theme/plugin/uploads deploy is fundamentally different from a static `dist/` push. Static-SFTP-only is the simpler scope. |
| 11.S | ADR-0009 — third write surface. Reverse ADR-0003, or argue external-host writes are a different category from local-FS writes? |
| 11.T | Atomicity — SFTP overwrites file-by-file; failed push = partial state. Stage-then-rename, maintenance-mode toggle, or accept best-effort and document? |

**Effort estimate.** v11.A ≈ 16-22h, ~14 commits (P1 walkers + cache
8-12h with the HG walker as the net-new chunk; P2 renderer + CLI +
apply-declarations 5-7h; P3 dashboard + diagnose 3-4h). v11.B ≈
14-20h once 11.O-T are answered. Real API quirks surface only on
first run against the fleet.

**Approval.** v11.A CLI shape + 11.K-N answers approved 2026-05-18 —
code may proceed. v11.B design open; 11.O-T gate code.

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
| v12.B | ⏳ | Adversarial audit response parser. `audit_pass.parse_audit(markdown) → ParsedAudit` + `AuditParseError`. Different schema from `parse_verdict`: required `### agreement_level` ∈ {full, partial, disagree}, `### confidence`, `### specific_concerns` (≥1 bullet). Optional `### counter_verdict` (only on `disagree`), `### audit_self_check`. Same tolerances as parse_verdict. ~2h. |
| v12.C | ⏳ | Adversarial audit pass runner. `audit_pass.run_audit_pass(cluster, *, primary_verdict, operator_profile, ...)`. Orchestrates build_audit_payload → render_audit_prompt → OpenAI chat-completions call → parse_audit. Default model `gpt-4o`, override via `--audit-model`. `AuditPassError` wraps HTTP/parse failures. ~3h. |
| v12.D | ⏳ | Reconciliation + REVIEW_REQUIRED first-class verdict. New `reconciliation.py` module: pure logic. Full-agree → confident final verdict. Partial → caveats list. Disagree → `REVIEW_REQUIRED` — intentionally NO auto-resolution. No LLM calls. ~2h. |
| v12.E | ⏳ | CLI `--verify` flag + wire audit pass into `new research` orchestrator. First user-visible audit-pass output. Default-off. Same-model rejection: errors when `--model X --audit-model X` resolve to the same model id. Persists audit + reconciliation into the cluster snapshot. ~3h. |
| v12.F | ⏳ | Polish — cost ledger + `verify_by_default` + granular cache invalidation. (a) Cost-estimate fields in snapshot. (b) `verify_by_default` operator-profile flag from `sites/portfolio/lamill.toml [operator]`; `--no-verify` overrides. (c) `--no-cache=interpretive` / `--no-cache=audit` for re-running individual passes on cached SERP data. ~3h. |
| v12.G | ⏳ | Docs. Update `docs/CLAUDE.md`, `AI_AGENTS.md`, `docs/Prompts.md`, `lamill new research --help` to reflect v12.A-F capabilities. "When to use `--verify`" guidance. ~1h. |

#### Design notes

**Problem statement.** The mechanical gates (Phase 1/2/3) plus the
primary interpretive pass (v8.I) catch many bad-niche signals, but
both share blind spots — a SERP where 3 of 10 results are
programmatic-template URLs that don't quite match the v2 regex
library; intent misclassification when SERP features (Local Pack vs
transactional snippets) contradict the surface-level read; the "KD
trap" (low keyword difficulty + a top-3 entirely owned by
incumbents); unfalsifiable moats passing the human-input gate. The
empirical claim: different model families have different blind spots.
Catching the disagreement is the signal — a second LLM in adversarial
mode that steel-mans the opposite conclusion surfaces what the
primary missed.

**Goals.**
- Add an **adversarial audit pass** using a *different* model
  (GPT-4o default) that steel-mans the opposite verdict.
- **Reconciliation surfaces disagreement** rather than auto-picking
  a winner. `REVIEW_REQUIRED` is a first-class verdict for the
  disagree case (alongside GO / NICHE-DOWN / NO-GO).
- **Opt-in cost.** Default is primary-only. The audit pass + recon
  is gated behind `--verify`.
- **Versioned prompts.** Both prompts live at repo-root `prompts/`,
  versioned (`_v1.md`, `_v2.md`, ...), and snapshots record which
  version produced their verdict.
- **Both verdicts always cached.** Even if `--verify` was off,
  re-running on cached data with `--verify` produces an audit
  without re-fetching SERP.

**Non-goals.**
- Three-model consensus / N-way voting. Two perspectives + honest
  disagreement is the point; adding a third dilutes the signal.
- Auto-resolution of disagreement. No "if audit confidence > primary
  confidence, audit wins" rules — those manufacture false certainty.
- Prompt-version A/B testing harness. Versioning lets us track which
  prompt produced what, but empirical comparison is a future feature.
- Audit-only mode (no primary, only adversarial). Audit's
  steel-man-the-opposite role doesn't make sense without a primary.

**User journey scenarios.**

```
# Default (primary only) — Phase 4a; cost ~$0.01-0.02 per run
$ lamill new research "ev charger installation cost"
... [gate output] ...
  Verdict: NICHE-DOWN (Sonnet, MEDIUM confidence)
  Reasoning: [2-4 paragraphs from primary]
  Run with --verify to add adversarial audit (~$0.05).

# Verify mode — audit fully agrees
$ lamill new research "ev charger installation cost" --verify
  Verdict: NICHE-DOWN
  ✓ Primary  (claude-sonnet-4-7, MEDIUM confidence)
  ✓ Audit    (gpt-4o, agrees, HIGH confidence)
  Final confidence: MEDIUM (lower of two)

# Verify mode — audit partially disagrees
  Verdict: NICHE-DOWN
  ✓ Primary  (claude-sonnet-4-7, MEDIUM)
  ⚠ Audit raises 2 concerns (gpt-4o, MEDIUM):
     - "Primary missed Reddit presence in 2 cluster queries"
     - "Pollution from muscle-car SERPs may be larger than counted"
  Final confidence: LOW (downgraded from MEDIUM)
  Caveats from audit: [each specific_concern]

# Verify mode — models disagree (high signal)
  ⚠⚠ REVIEW REQUIRED — models disagree
  Primary (claude-sonnet-4-7, HIGH): NICHE-DOWN
  Audit   (gpt-4o, HIGH): NO-GO
  This is a high-signal disagreement. Read both arguments
  and decide manually. Snapshot at <path>.

# Re-audit a cached primary
$ lamill new research "ev charger installation cost" --verify --no-cache=audit
  (Reads cached Phase 4a, runs Phase 4b fresh, runs Phase 4c.)
```

**Resolved open questions** (all answered 2026-05-16; recorded here
for archeology — none gate v12 implementation).

| # | Question | Resolution |
|---|---|---|
| 12.A | Where do `prompts/` live? | **`prompts/` at repo root** (option 2). First-class status alongside `tests/` and `docs/`. Operator edits prompts directly. |
| 12.B | Audit model default — GPT-4o, Gemini, or operator's choice? | **GPT-4o default.** No Gemini integration in v1 — defer the third-provider HTTP wrapper + third env var. Different-model invariant is met with Anthropic (CLI) + OpenAI. |
| 12.C | Does the audit see the primary's `blind_spot_self_report`? | **Blind to it.** The audit's value is uncovering what the primary missed; visibility into the self-report risks anchoring on the same concerns. Field is still stored on the snapshot. |
| 12.D | `--verify` default-on in operator profile? | **Yes, via operator profile only** (not a sticky state file). `verify_by_default: bool` (default false) in `sites/portfolio/lamill.toml [operator]`. CLI `--verify` overrides to true; `--no-verify` overrides to false. |
| 12.E | Audit failure handling — fail the run, proceed primary-only, or block the verdict? | **Proceed primary-only** with a prominent "audit pass failed" caveat. Snapshot records `audit_pass.error`. Don't waste the primary's verdict on a transient audit issue. |
| 12.F | Snapshot retention for audit pass — same as primary (kept forever, git-tracked)? | **Yes.** Audit responses are part of the verdict's provenance. |
| 12.G | Template-substitution engine — Jinja2, `str.format()`, or custom `{{var}}` regex? | **Custom `{{var}}` regex.** Stdlib; no curly-brace collision with code-block examples in prompts; substitution validator doubles as a no-unfilled-placeholders check. |
| 12.H | `--model` + `--audit-model` same-model behavior — reject loudly, reject with suggestion, or allow with warning? | **Reject loudly with a helpful suggestion** in the error message. The whole point of the audit is to use a different model. |
| 12.I | Prompt versioning policy — when does `_v1.md` become `_v2.md`? | **Bump to `_v2.md` only when the change would meaningfully alter the verdict on cached data.** Typo / wording / formatting tweaks stay at `_v1.md`. New failure-mode checks, structural instruction changes, or output-shape edits bump the version. Snapshots store `prompt_version`; mismatch with current `_vN.md` is treated as "stale verdict — re-render via `--no-cache=interpretive`." |
| 12.J | Cumulative cost-tracking field on snapshots? | **Yes** — record `estimated_cost_usd` on each pass (`interpretive_pass.estimated_cost_usd` and `audit_pass.estimated_cost_usd`). Pulled from provider response headers when available, estimated from token counts otherwise. Unblocks a future cost-ledger aggregation without re-fetching. |

**Effort estimate.** v12.B-G ~13-18h total. v12.B parser ~2h, v12.C
runner ~3h, v12.D reconciliation ~2h, v12.E CLI wire-up ~3h, v12.F
polish ~3h, v12.G docs ~1h. (v12.A audit prompt rendering shipped
2026-05-17.)

**Approval.** Approved 2026-05-16. Implementation may proceed.
v8.D shipped 2026-05-15; v8.E-J shipped 2026-05-16/17 (full primary
interpretive pass + audit payload builder); v12.A shipped 2026-05-17.

### v13 — analytical roll-ups *(renumbered 2026-05-17 PM)*

GSC trend correlation over PERSISTED snapshots (week-over-week
deltas); `project list` aggregate verdict-counts view; optional LLM
content seeding (still postponed indefinitely). All read-only /
informational.

#### Phases

| # | Status | Feature |
|---|---|---|
| v13.A | ⏳ | GSC trend correlation. GSC trend per project (28d clicks/imp/pos, w/w delta) over PERSISTED `data/gsc/` snapshots. **Distinct from v5.D** — v5.D is the runtime live check (one query, current state); v13.A is the longitudinal analytical layer (week-over-week deltas, trend lines). |
| v13.B | ⏳ | Roll-up. `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts. |
| v13.C | ⏸ | Optional LLM content seeding. `--seed-content` flag on `portfolio new bootstrap`: OpenAI gpt-4o-mini generates a starter home page + 1-2 supporting pages from the topic (similar prompt pipeline to v2.A) · cached by topic-hash · user reviews + commits manually before pushing · skipped by default since some projects are app-style. *Postponed indefinitely (2026-05-04 user call); v3.D built first.* |

### v14 — deploy verification *(renumbered 2026-05-17 PM; deprioritized)*

Build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel
API integration. Heavy overlap with v11's `fleet hosting`; revisit
scope when this tier's slot comes up.

#### Phases

| # | Status | Feature |
|---|---|---|
| v14.A | ⏳ | Build-time stamping. Convention: every sites/* project writes `version.json` at build (commit + built_at) · new conformance check: `has-version-stamp`. |
| v14.B | ⏳ | HEAD vs deployed. Deploy-freshness signal · `deploy-fresh` conformance check · reads `version.json` from live URL. |
| v14.C | ⏳ | Build status + deploy lag. Deploy lag (push → live) · last build status via Cloudflare/Vercel API · `last-build-success` conformance · *requires platform tokens — major new infra*. |
| v14.D | ⏳ | Domain-list refresh tooling. Flag-only enhancements to existing `cleanup` (no new commands): `--refresh` pulls live from registrar APIs (Porkbun ready; GoDaddy/Namecheap require account API setup) into `data/domains/<reg>.csv` before merging. `--watch` re-merges whenever a CSV in `data/domains/` changes on disk. Direct `$EDITOR` on `data/portfolio.json` is the no-tooling path. |

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
| `has-version-stamp` | project writes `version.json` at build time | v14.A *(renumbered 2026-05-17 PM — was v13.A → v12.A → v10.A)* |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v14.B *(renumbered 2026-05-17 PM — was v13.B → v12.B → v10.B)* |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v14.C *(renumbered 2026-05-17 PM — was v13.C → v12.C → v10.C)* |
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
