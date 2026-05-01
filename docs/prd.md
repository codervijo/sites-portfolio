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

`portfolio` is the inventory + standards enforcer for the sites/ workspace. As the number of sibling projects under `sites/` grows, it becomes infeasible to remember per-project state, deploy quirks, build conventions, or where each one is in its lifecycle. portfolio is the single place to:

1. **Ask "what is the status of project X?"** and get an answer drawn from git, project docs (Prompts.md, prd.md), the curated `plan.md`, live HTTP checks, GSC analytics, and (later) deploy verification.
2. **Detect and flag deviations from sites/* conventions** so the workspace stays uniform rather than drifting into N bespoke setups. portfolio's status output is a conformance report; gaps are surfaced and (from v2.D) optionally fixed.
3. **Manage the domain portfolio itself** — categorize, track expirations across multiple registrars (GoDaddy, Namecheap, Porkbun), cross-reference with Google Search Console.
4. **Help acquire new domains** (v3) — brainstorm SEO-quality candidates from a topic, score them, check availability via RDAP.

## 2. Audience

Sole user: Vijo. No multi-tenancy, no permissions, no public surface. CLI-only.

## 3. Goals & non-goals

**Goals**:

- Single CLI surface for status, conformance, drift, and (later) remediation across all sites/* projects.
- Multi-registrar consolidation with normalization (GoDaddy, Namecheap, Porkbun).
- Skill-friendly JSON outputs for natural-language wrapping (v1.D ships the project-status skill).
- Read-only through v2.C; write operations gated behind `--apply` from v2.D onward.
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
| Live Porkbun pricing API | dropped — low-value TLDs anyway |
| Pricing as a v3 feature | dropped — manual at purchase |

## 4. Versions

| Version | Theme | Acceptance |
|---|---|---|
| **v1** | project status + multi-registrar inventory | `portfolio project status <name>` ships with full git pulse, Prompts.md parsing, deploy detection, live-site join, conformance reporting; multi-registrar CSVs consolidated; NLP skill wraps the JSON output |
| **v2** | conformance + drift + stack + remediation | stack identifier, plan-drift signal, dir↔domain mapping; v2.D crosses read→write boundary with `portfolio project fix <name>` |
| **v3** | acquisition (domain suggest) | `portfolio domain suggest <topic>` with OpenAI brainstorm + SEO scoring + RDAP availability |
| **v4** | live correlation + roll-up | GSC trend join; `portfolio project list` aggregate view |
| **v5** | deploy verification | build-time stamping convention + HEAD vs deployed SHA + Pages/Vercel API integration |

## 5. Phases

Strict sequence (option a). 16 phases total; v1.A, v1.B, v1.C, and v1.D shipped.

Note on read/write boundary: portfolio is **read-only** through v2.C. **v2.D is the read→write transition** — it gains the ability to scaffold convention files and migrate parent-tracked dirs into their own repos (with explicit per-step confirmations). Every later version stays mostly read-only except where otherwise noted.

| Phase | Theme | Features |
|---|---|---|
| **v1.A** ✅ | Skeleton + repo-isolation gate | `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active) |
| **v1.B** ✅ | Full git pulse + Prompts.md + deploy-detect + live | activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view |
| **v1.C** ✅ | Registrar consolidation | `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (3 date formats; auto-renew yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price · Porkbun rows excluded from value rollups (low-value TLDs) |
| **v1.D** ✅ | Cleanup + classification migration (plan.md → portfolio.json) | `portfolio cleanup` subcommand · reads raw registrar CSVs + plan.md · writes `data/portfolio.json` (single canonical record per domain: name, registrar, category, expires, created, auto_renew, renewal_price, estimated_value, privacy, transfer_locked, nameservers, forwarding_url, raw passthrough for forensics) · auto-classification rules: Namecheap rows → "Under build", Porkbun rows → "Under build", GoDaddy rows → plan.md category (or warn if uncategorized) · `load_domains()` pivots to read from `portfolio.json` after cleanup · `load_plan()` is removed (categories now come from `domain.category` directly) · plan.md gets a deprecation comment in v1.D; actual file deletion happens in a later cleanup commit · drift output surfaces uncategorized domains as warnings · resolver in `project status` continues to fuzzy-match, just against `portfolio.json` keys instead of plan.md · typo / fuzzy-similar-name detection deferred to v2.B |
| **v1.E** | NLP skill | `.claude/skills/project-status.md` — routes "what's the status of X" → CLI → JSON → prose · disambiguation handled in skill |
| **v2.A** | Stack detection + scaffold completeness | stack identifier (React+Vite / Astro / Python+uv / Go+Fiber / scaffold-only) · C7 vite-version-ok · C9 has-prd-md · **scaffolding-required rules: has-readme · has-gitignore** (every sites/* project must have the standard scaffolding produced by the `/project-init` slash command: `docs/`, `docs/prd.md`, `docs/Prompts.md`, `AI_AGENTS.md`, `README.md`, `.gitignore`) |
| **v2.B** | Drift + mapping | plan-drift signal · C10 domain-dir-match (override map for harmonia / levents / lamill-events / etc.) · C8 cf-pages-deployable |
| **v2.C** | Per-stack rules | placeholder for emerging conventions: pnpm-lockfile-only · no-package-lock-json · gitignore-covers-build-output · python-uses-uv |
| **v2.D** | Remediation (read→write boundary) | `portfolio project fix <name>` subcommand · dry-run by default; `--apply` required to write · `--rule R` for surgical fixes · all fixes idempotent · auto-fixes: has-prompts-md (scaffold dated H2 starter) · has-ai-agents-md (template) · has-makefile (per-stack baseline; depends on v2.A) · prompts-md-format (migrate first H2 to today's date) · own-git-repo guided migration (multi-step: parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit; explicit confirmation at each step touching parent repo) · `--yes` skips prompts for scripted runs · templates embedded in `src/portfolio/templates.py` · `platform-declared` and `in-plan-md` deferred (require user choice / curation) |
| **v3.A** | Brainstorm + score + already-own | `portfolio domain suggest <topic>` · OpenAI gpt-4o-mini brainstorm (~30 candidates) · 7-day cache by topic-hash · already-own search across 3 registrars (depends on v1.C) · SEO-weighted scoring (TLD tier · length · keyword · hyphen/digit penalty) · top-8 stdout |
| **v3.B** | RDAP availability | opt-in `--check-availability` · RDAP per candidate, rate-limited ~5/sec · ✓ / ✗ / ? · per-TLD endpoint cache |
| **v4.A** | GSC trend correlation | GSC trend per project (28d clicks/imp/pos, w/w delta) · C12 gsc-verified · reads existing `data/gsc/` snapshots |
| **v4.B** | Roll-up | `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts |
| **v5.A** | Build-time stamping | convention: every sites/* project writes `version.json` at build (commit + built_at) — *cross-project work, not portfolio-only* · new conformance: has-version-stamp |
| **v5.B** | HEAD vs deployed | deploy-freshness signal · C13 deploy-fresh · reads `version.json` from live URL |
| **v5.C** | Build status + deploy lag | deploy lag (push → live) · last build status via Cloudflare/Vercel API · last-build-success conformance · *requires platform tokens — major new infra* |

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
| `vite-version-ok` | Vite ≥6 for React projects | v2.A |
| `has-prd-md` | `docs/prd.md` exists | v2.A |
| `has-readme` | `README.md` exists at project root | v2.A |
| `has-gitignore` | `.gitignore` exists at project root | v2.A |
| `cf-pages-deployable` | frozen-lockfile install OK; no stray gitlinks; no `_redirects` SPA fallback | v2.B |
| `domain-dir-match` | dir name matches a plan.md domain (or in override map) | v2.B |
| `gsc-verified` | dir's eTLD is a verified GSC property | v4.A |
| `has-version-stamp` | project writes `version.json` at build time | v5.A |
| `deploy-fresh` | HEAD SHA matches deployed SHA | v5.B |
| `last-build-success` | last Cloudflare/Vercel build succeeded | v5.C |

## 7. Open questions

Append-only log. Questions get answered (with date) but never deleted.

- *(no open questions at this time — all v1 scoping decisions are locked in AI_AGENTS.md and this PRD)*
