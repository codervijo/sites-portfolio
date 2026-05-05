---
project: portfolio
prd_version: 1
project_version: v1.C
status: in-progress
owner: Vijo
last_updated: 2026-05-01
---

# portfolio — PRD

## 1. Purpose

`portfolio` is the **inventory + standards enforcer + production line** for the sites/ workspace. As the number of sibling projects under `sites/` grows, it becomes infeasible to remember per-project state, deploy quirks, build conventions, or where each one is in its lifecycle. portfolio is the single place to:

1. **Ask "what is the status of project X?"** and get an answer drawn from git, project docs (Prompts.md, prd.md), `data/portfolio.json`, live HTTP checks, GSC analytics, and (later) deploy verification.
2. **Detect and flag deviations from sites/* conventions** so the workspace stays uniform rather than drifting into N bespoke setups. portfolio's status output is a conformance report; gaps are surfaced and (from v4.D) optionally fixed.
3. **Manage the domain portfolio itself** — categorize, track expirations across multiple registrars (GoDaddy, Namecheap, Porkbun), cross-reference with Google Search Console.
4. **Find the right domain to register for any new idea** *(Power 1, v2)* — brainstorm SEO-quality candidates from a topic via OpenAI, score them, check availability via RDAP. Prevents bad registrations.
5. **Bootstrap a new commercial site to ship-ready state** *(Power 2, v3)* — given a registered domain + topic, scaffold the project at full conformance: stack (Astro/Vite/etc.) via the central builder, SEO baseline (sitemap/robots/OG/JSON-LD/favicon), deploy-target abstraction (Cloudflare Pages default, swappable), optional LLM-seeded content. The actual scaling lever for the 30-commercial-sites goal — turns "I have an idea" into "indexed live site" in under an hour.

## 2. Audience

Sole user: Vijo. No multi-tenancy, no permissions, no public surface. CLI-only.

## 3. Goals & non-goals

**Goals**:

- Single CLI surface for status, conformance, drift, and (later) remediation across all sites/* projects.
- Multi-registrar consolidation with normalization (GoDaddy, Namecheap, Porkbun).
- Skill-friendly JSON outputs for natural-language wrapping (v1.D ships the project-status skill).
- Read-only through v2 (domain suggest); v3 (bootstrap) and v4.D (remediation) are the two write surfaces. Write operations are explicit (always behind a confirmation or flag).
- Versioning convention canonicalized here, propagated to other sites/* projects opt-in.
- **Standard project scaffolding required across all sites/* projects** — `docs/`, `docs/prd.md`, `docs/Prompts.md`, `AI_AGENTS.md`, `README.md`, `.gitignore` — produced by the `/project-init` slash command and enforced via v2.A conformance rules. Single source of truth for spec/roadmap/conformance lives in each project's `docs/prd.md`; `AI_AGENTS.md` is the agent-orientation doc and references the PRD rather than duplicating it.

**Non-goals (intentionally never)**:

| Item | Why |
|---|---|
| Real SEO analytics (Ahrefs/SEMrush/Moz) | $$ APIs; manual remains best |
| Trademark search (USPTO) | manual at purchase time |
| Domain history (Wayback parsing) | niche |
| Social handle availability | different problem domain |
| Wide registrar API auto-sync | dropped — manual CSV exports cover it |
| ~~Live Porkbun pricing API~~ | reinstated 2026-05-02 — buying-side price is a critical decision criterion (≠ owned-domain valuation, which stays out of scope) |

## 4. Versions

| Version | Theme | Acceptance |
|---|---|---|
| **v1** | project status + multi-registrar inventory | `portfolio project status <name>` ships with full git pulse, Prompts.md parsing, deploy detection, live-site join, conformance reporting; multi-registrar CSVs consolidated; NLP skill wraps the JSON output |
| **v2** | acquisition — domain suggest *(Power 1)* | `portfolio domain suggest <topic>` with OpenAI brainstorm + SEO scoring + RDAP availability — high-ROI scaling lever |
| **v3** | bootstrap — ship-ready scaffold *(Power 2)* | `portfolio bootstrap <domain>` creates a sites/* project at full conformance: git init, Astro/Vite (or other) stack scaffold via the central builder, SEO baseline pack, deploy-target abstraction (CF Pages default), optional LLM content seed — the production line for the 17-site gap |
| **v4** | conformance + drift + stack + remediation | stack identifier, plan-drift signal, dir↔domain mapping; v4.D's `portfolio project fix <name>` is the second write surface for retro-fixing pre-bootstrap projects |
| **v5** | live correlation + roll-up | GSC trend join; `portfolio project list` aggregate view |
| **v6** | deploy verification | build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel API integration |

## 5. Phases

Strict sequence (option a). 21 phases total; v1.A–v1.F + v2.A + v2.B + v3.A shipped (9/21).

Note on read/write surfaces: portfolio is **read-only** through v2 (domain suggest). **v3 (bootstrap) is the first write surface** — it creates new project dirs, runs `git init`, scaffolds files. **v4.D (remediation) is the second write surface** — it modifies existing project dirs to fix conformance gaps. Everything else (v4.A–C, v5, v6) is read-only.

Note on the v2/v3/v6 reorder (2026-05-02):

- Domain-suggest (Power 1) moved from v3 → v2 — high ROI for the 30-commercial-sites goal: picking the right domain at registration time prevents bad investments.
- Bootstrap (Power 2) added as v3 — the actual scaling lever; turns "I have an idea" → "live commercial site" in under an hour.
- Original v2 (conformance + remediation) → v4. Original v4 (GSC + roll-up) → v5. Original v5 (deploy verification) → v6.
- Rationale: both scaling levers up front; conformance polish and post-deploy verification later.

| Phase | Theme | Features |
|---|---|---|
| **v1.A** ✅ | Skeleton + repo-isolation gate | `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active) |
| **v1.B** ✅ | Full git pulse + Prompts.md + deploy-detect + live | activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view |
| **v1.C** ✅ | Registrar consolidation | `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (3 date formats; auto-renew yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price · Porkbun rows excluded from value rollups (low-value TLDs) |
| **v1.D** ✅ | Cleanup + classification migration (plan.md → portfolio.json) | `portfolio cleanup` subcommand · reads raw registrar CSVs + plan.md · writes `data/portfolio.json` (single canonical record per domain: name, registrar, category, expires, created, auto_renew, renewal_price, estimated_value, privacy, transfer_locked, nameservers, forwarding_url, raw passthrough for forensics) · auto-classification rules: Namecheap rows → "Under build", Porkbun rows → "Under build", GoDaddy rows → plan.md category (or warn if uncategorized) · `load_domains()` pivots to read from `portfolio.json` after cleanup · `load_plan()` is removed (categories now come from `domain.category` directly) · plan.md gets a deprecation comment in v1.D; actual file deletion happens in a later cleanup commit · drift output surfaces uncategorized domains as warnings · resolver in `project status` continues to fuzzy-match, just against `portfolio.json` keys instead of plan.md · typo / fuzzy-similar-name detection deferred to v4.B |
| **v1.E** ✅ | NLP skill | `~/.claude/skills/project-status/SKILL.md` (global; works from any cwd) — routes natural-language questions like "what's the status of iotnews" → `make run ARGS="project status <name> --json"` → short prose answer (1-line headline + up to 3 contextual bullets). Disambiguation: lists `candidates` and asks the user. Read-only by design; defers fixes to v4.D and cross-project roll-up to v5.B. |
| **v1.F** ✅ | Parked-detection accuracy | extend `check.py` `_classify()` with body-content inspection: detect GoDaddy in-line parking (sub-1KB body containing `window.location.href = "/lander"` or similar JS redirect to `/lander` / `/landing` / `/sale` / `/park`) and reclassify from spurious `live-site` → `parked` with reason `js-redirect-to-parking-page` · capture truncated body excerpt in `CheckResult` so future re-classifications run offline against the snapshot · re-run `check --only all` to refresh the 53-domain dataset · `summary` and `project status` now reflect reality for parked GoDaddy domains (newiniot.com etc.) |
| **v2.A** | Multi-strategy brainstorm + score + already-own *(Power 1 — find the right domain)* | `portfolio domain suggest <topic>` interactive subcommand · OpenAI `gpt-5-mini` brainstorm, looped through configurable naming **strategies** (5 default: trendy / dev-technical / benefit-driven / metaphor / abstract-brandable; extensible via config) · per-strategy: ~12 candidates → strict gen rules (≤12 chars, no hyphens, brandable, easy to say) → SEO-weighted scoring (TLD tier · length · keyword presence · hyphen/digit penalty) → top-5 sorted · `history` deduplication so subsequent strategies don't repeat names · already-own intersection against `data/portfolio.json` (depends on v1.C) — surface owned matches *before* generating new ones · 7-day caching by `topic-hash` in `data/cache/suggest/` so iterating on the same idea is cheap · `--non-interactive` flag dumps ranked candidates for piping; default is interactive (per-strategy round → user picks / moves on / types custom) |
| **v2.B** | Availability + **price** via Porkbun (RDAP fallback) | Porkbun `domain/checkAvailability` API by default if `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` env vars present (returns availability **and price** in one call — both are buying-side decision criteria) · RDAP fallback when Porkbun keys unset (availability only, no price) · TLD ladder per the SEO tier config: `.com / .ai / .io / .app / .dev / .co` default; `--tlds=` overrides · stop-at-first-available-TLD per name to keep round time manageable · rate-limited (~3/sec, matching script convention) · per-TLD endpoint cache · **`--max-price=$N` filter** so premium-priced names get excluded — user explicitly does not want to overpay at registration time · output column shape per round: `name · TLD · avail · price · score` |
| **v3.A** ✅ | Bootstrap — scaffold a new project *(Power 2 — ship-ready scaffold)* | `portfolio bootstrap <domain>` typer command with three paths: **(1) template**: empty target → writes minimal Astro (default) or `--stack=vite` (React+JSX) scaffold; **(2) `--from-genai`**: target dir + `genai/` subdir exist → copies `genai/*` to project root and applies CF Pages safety fixes (Vite ≥6 bump, `_redirects` removal, `wrangler.toml` add); **(3) `--git-url=<url>`**: clones URL into `genai/` then proceeds as `--from-genai`. All paths write standard scaffolding (AI_AGENTS with Building/Deployment, docs/prd.md, docs/Prompts.md, README, .gitignore, local `Makefile` that includes `BUILDER_PATH=../../builder`) and run `git init` + initial commit. `--with-ingester` adds `scripts/ingest.py` template. `--topic` injects into AI_AGENTS + PRD. Filesystem-only by default (genai+template paths); `--git-url` is the only network-touching path. |
| **v3.B** | SEO baseline pack | meta-tag template (title, description, canonical, OG, Twitter card) · sitemap.xml generator script · robots.txt · JSON-LD structured data (Organization + WebSite) · favicon auto-generation from domain (1-letter monogram default; SVG → multi-size pipeline) · technical-SEO check at scaffold time (heading structure, meta lengths, alt-tag scaffolds, page weight baseline) · all of these are stack-aware (Astro vs Vite injection points differ) |
| **v3.C** | Deploy abstraction + Cloudflare Pages impl | `DeployTarget` interface (provider-agnostic): `configure_build` / `register_domain` / `connect_repo` · `CloudflarePagesDeploy` concrete impl writes `wrangler.toml`, satisfies `platform-declared` from day one · `gh repo create` integration creates GitHub repo + connects it · CF Pages dashboard linkage (manual one-time auth, automated thereafter) · architected so future `VercelDeploy` / `NetlifyDeploy` impls slot in without callers changing |
| **v3.D** | Optional LLM content seeding | `--seed-content` flag: OpenAI gpt-4o-mini generates a starter home page + 1–2 supporting pages from the topic (similar prompt pipeline to v2.A's brainstorm) · cached by topic-hash · user reviews + commits manually before pushing · skipped by default since some projects are app-style (no narrative content) |
| **v4.A** | Stack detection + scaffold completeness *(was v3.A pre-2026-05-02 reorder)* | stack identifier (React+Vite / Astro / Python+uv / Go+Fiber / scaffold-only) · C7 vite-version-ok · C9 has-prd-md · **scaffolding-required rules: has-readme · has-gitignore · ai-agents-md-has-building-info · ai-agents-md-has-deployment-info** (every sites/* project must have the standard scaffolding produced by `/project-init` or v3 bootstrap) |
| **v4.B** | Drift + mapping | plan-drift signal · C10 domain-dir-match (override map for harmonia / etc.) · C8 cf-pages-deployable |
| **v4.C** | Per-stack rules | placeholder for emerging conventions: pnpm-lockfile-only · no-package-lock-json · gitignore-covers-build-output · python-uses-uv |
| **v4.D** | Remediation (second write surface) | `portfolio project fix <name>` subcommand · dry-run by default; `--apply` required to write · `--rule R` for surgical fixes · all fixes idempotent · auto-fixes: has-prompts-md · has-ai-agents-md · has-makefile (depends on v4.A's stack identifier) · prompts-md-format · own-git-repo guided migration (parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit; explicit confirmation each step touching parent repo) · `--yes` skips prompts for scripted runs · templates embedded in `src/portfolio/templates.py` · `platform-declared` and `has-category` deferred (require user choice / curation) |
| **v5.A** | GSC trend correlation | GSC trend per project (28d clicks/imp/pos, w/w delta) · C12 gsc-verified · reads existing `data/gsc/` snapshots |
| **v5.B** | Roll-up | `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts |
| **v6.A** | Build-time stamping | convention: every sites/* project writes `version.json` at build (commit + built_at) · new conformance: has-version-stamp |
| **v6.B** | HEAD vs deployed | deploy-freshness signal · C13 deploy-fresh · reads `version.json` from live URL |
| **v6.C** | Build status + deploy lag | deploy lag (push → live) · last build status via Cloudflare/Vercel API · last-build-success conformance · *requires platform tokens — major new infra* |

## 6. Conformance rules

portfolio enforces these on sibling sites/* projects via `project status`. Failures show in the `failed` list with optional fix hints. Skipped rules don't apply (e.g. `live-site` for a CLI project that doesn't deploy).

| Rule | Pass condition | Lands in |
|---|---|---|
| `own-git-repo` | `git rev-parse --show-toplevel` resolves to project dir itself | v1.A |
| `in-plan-md` → `has-category` | domain has a category set (originally from plan.md; renamed in v1.D once `portfolio.json` is canonical) | v1.B (renamed in v1.D) |
| `has-prompts-md` | `docs/Prompts.md` exists | v1.B |
| `prompts-md-format` | last H2 matches `^## \d{4}-\d{2}-\d{2}` | v1.B |
| `has-makefile` | `Makefile` with `run` and `build` targets | v1.B |
| `has-ai-agents-md` | `AI_AGENTS.md` exists | v1.B |
| `platform-declared` | filesystem markers identify cloudflare/vercel/netlify, OR project is n/a (CLI/library) | v1.B |
| `live-site` | latest check classification is `live-site` | v1.B |
| `vite-version-ok` | Vite ≥6 for React projects | v4.A |
| `has-prd-md` | `docs/prd.md` exists | v4.A |
| `has-readme` | `README.md` exists at project root | v4.A |
| `has-gitignore` | `.gitignore` exists at project root | v4.A |
| `ai-agents-md-has-building-info` | `AI_AGENTS.md` contains a `## Building info` heading (referencing the central builder at `~/work/projects/builder/` + `../Makefile`) | v4.A |
| `ai-agents-md-has-deployment-info` | `AI_AGENTS.md` contains a `## Deployment info` heading (platform / live URL / deploy trigger) | v4.A |
| `cf-pages-deployable` | frozen-lockfile install OK; no stray gitlinks; no `_redirects` SPA fallback | v4.B |
| `domain-dir-match` | dir name matches a plan.md domain (or in override map) | v4.B |
| `gsc-verified` | dir's eTLD is a verified GSC property | v5.A |
| `has-version-stamp` | project writes `version.json` at build time | v6.A |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v6.B |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v6.C |

## 7. Open questions

Append-only log. Questions get answered (with date) but never deleted.

- *(no open questions at this time — all v1 scoping decisions are locked in AI_AGENTS.md and this PRD)*
