# AI_AGENTS.md — sites/portfolio/

## Raison d'être

`portfolio` exists to make the many sibling projects under `sites/` **uniform enough to manage at scale**. As the number of sites/* projects grows, it stops being feasible to remember per-project state, deploy quirks, build conventions, or where each one is in its lifecycle. portfolio is the single place to:

1. **Ask "what is the status of project X?"** and get an answer drawn from git, project docs (Prompts.md, prd.md), the curated `plan.md`, and — in later phases — live HTTP checks, GSC analytics, and deploy verification.
2. **Detect and flag deviations from sites/* conventions** so the workspace stays uniform rather than drifting into N bespoke setups. portfolio's status output is also a conformance report: each project is checked against the standards every sites/* project should follow (own git repo, Prompts.md, Makefile targets, Vite/uv versions, etc.) and gaps are surfaced.
3. **Manage the domain portfolio itself** — categorize, track expirations, cross-reference with Google Search Console, snapshot live HTTP classifications. This was the original purpose; the uniformity-enforcement role is layered on top.

In short: portfolio is the **inventory + standards enforcer** for the sites/ workspace.

## Current capabilities (CLI)

Run from `sites/portfolio/`:

- `make run ARGS="summary"` — portfolio overview (counts, plan categories, CSV/plan drift)
- `make run ARGS="list"` — all domains with expiry, status, value
- `make run ARGS="expiring --within 90"` — domains expiring soon
- `make run ARGS="category 'My brand'"` — domains in a plan category
- `make run ARGS="wip"` — work-in-progress domains (My brand + SEO + Next session)
- `make run ARGS="check --only wip"` — fetch each domain, classify, snapshot to `data/checks/YYYY-MM-DD.json`
- `make run ARGS="status"` — latest check snapshot with diff vs. previous
- `make run ARGS="gsc auth | list | sync | compare"` — Google Search Console integration

## Versioning + roadmap conventions

portfolio is the canonical source for sites/* versioning conventions. The taxonomy is two-level and applies to every sites/* project:

- **`vN`** — major capability tier. Each major version is a coherent shipped capability and may break compat with the previous tier. SemVer-MAJOR semantics.
- **`vN.X`** — phase within a tier (letter, A/B/C/…). Internal slicing of build work; signals "order/scope can shift." Each phase still ships independently.

Why two-level: keeps **external version** (vN — what consumers see) cleanly separate from **internal phasing** (vN.X — how the team slices build work). Three layers (`v1.1.A`) is over-engineered; one layer (`v1, v2, v3`) loses phase granularity.

### Uniform PRD template (for sites/* projects)

Every sites/* project's `docs/prd.md` should follow this skeleton (frontmatter + ordered sections):

```yaml
---
project: <name>
prd_version: 1               # version of this PRD document (not the project)
project_version: vN.X        # current target phase
status: planned | in-progress | shipped | deprecated
owner: Vijo
last_updated: YYYY-MM-DD
---
```

Required sections, in order:

1. **Purpose** — one paragraph; why the project exists
2. **Audience** — who uses it
3. **Goals & non-goals** — in scope / explicitly out
4. **Versions** — table of `vN` rows: theme + acceptance criteria
5. **Phases** — table of `vN.X` rows: features shipped, status
6. **Conformance rules** *(if applicable)* — for projects that enforce conventions on others (currently only portfolio)
7. **Open questions** — append-only log; questions get marked answered with date, never deleted

For portfolio itself, this AI_AGENTS.md serves as both the agent-orientation doc *and* the PRD — the master phase table below stands in for `docs/prd.md`. When v2.A's `has-prd-md` conformance rule lands, portfolio is the rule's first conscious exception (CLI projects with consolidated docs in AI_AGENTS.md).

Sibling rollout (other sites/* projects adopting this taxonomy + PRD template) is a later, opt-in phase — not blocking on v1.

## Roadmap (master phase table)

Sequence: **strict by version** (option a). 15 phases total; v1.A and v1.B shipped.

Note on read/write boundary: portfolio is **read-only** through v2.C — it observes filesystem, git, snapshots, and reports. **v2.D is the read→write transition**: it gains the ability to scaffold convention files and migrate parent-tracked dirs into their own repos (with explicit per-step confirmations). Every later version stays mostly read-only except where otherwise noted.

| Phase | Theme | Features |
|---|---|---|
| **v1.A** ✅ | Skeleton + repo-isolation gate | `portfolio project status <name>` subcommand · fuzzy resolver against plan.md · `--json` schema_version=1 · C1 own-git-repo gate · last commit (sha, subject, age, author) · binary verdict (Misconfigured / Active) |
| **v1.B** ✅ | Full git pulse + Prompts.md + deploy-detect + live | activity rate (7d/30d) · branch + clean/dirty · uncommitted count · last Prompts.md entry (dated-H2 parser) · plan category · full verdict ladder (Active / Quiet / Stalled / Dormant / Fresh / Misconfigured) · C2 in-plan-md · C3 has-prompts-md · C4 prompts-md-format · C5 has-makefile · C6 has-ai-agents-md · deploy-platform detection (cloudflare / vercel / netlify / unknown / n/a) via filesystem markers · live-site HTTP class joined from `data/checks/` · platform-declared + live-site conformance · rich TTY view |
| **v1.C** | Registrar consolidation | `data/domains/{godaddy,namecheap,porkbun}.csv` · 3 adapters with format normalization (dates: 3 formats; auto-renew: yes/no/ON/OFF) · Porkbun disclaimer-line skip · `Domain` schema gains `registrar` (required), `privacy`, `transfer_locked` · `domain_to_registrar()` shared lookup · `summary` warns on missing renewal_price rather than under-counting · Porkbun rows excluded from value rollups (low-value TLDs) |
| **v1.D** | NLP skill | `.claude/skills/project-status.md` — routes "what's the status of X" → CLI → JSON → prose · disambiguation handled in skill |
| **v2.A** | Stack detection | stack identifier (React+Vite / Astro / Python+uv / Go+Fiber / scaffold-only) · C7 vite-version-ok · C9 has-prd-md |
| **v2.B** | Drift + mapping | plan-drift signal · C10 domain-dir-match (override map for harmonia / levents / lamill-events / etc.) · C8 cf-pages-deployable |
| **v2.C** | Per-stack rules | placeholder for emerging conventions: pnpm-lockfile-only · no-package-lock-json · gitignore-covers-build-output · python-uses-uv |
| **v2.D** | Remediation (**read→write boundary**) | `portfolio project fix <name>` subcommand · dry-run by default; `--apply` required to write · `--rule R` for surgical fixes · all fixes idempotent · auto-fixes: has-prompts-md (scaffold dated H2 starter) · has-ai-agents-md (template) · has-makefile (per-stack baseline; depends on v2.A) · prompts-md-format (migrate first H2 to today's date) · **own-git-repo guided migration** (multi-step: parent `git rm --cached` + parent `.gitignore` entry + project `git init` + initial commit; explicit confirmation at each step touching parent repo) · `--yes` skips prompts for scripted runs · templates embedded in `src/portfolio/templates.py` · `platform-declared` and `in-plan-md` deferred (require user choice / curation) |
| **v3.A** | Brainstorm + score + already-own | `portfolio domain suggest <topic>` · OpenAI gpt-4o-mini brainstorm (~30 candidates) · 7-day cache by topic-hash · already-own search across 3 registrars (depends on v1.C) · SEO-weighted scoring (TLD tier · length · keyword · hyphen/digit penalty) · top-8 stdout |
| **v3.B** | RDAP availability | opt-in `--check-availability` · RDAP per candidate, rate-limited ~5/sec · ✓ / ✗ / ? · per-TLD endpoint cache |
| **v4.A** | GSC trend correlation | GSC trend per project (28d clicks/imp/pos, w/w delta) · C12 gsc-verified · reads existing `data/gsc/` snapshots |
| **v4.B** | Roll-up | `portfolio project list` · `--stale N` filter · `--json` · aggregate verdict counts |
| **v5.A** | Build-time stamping | convention: every sites/* project writes `version.json` at build (commit + built_at) — *cross-project work, not portfolio-only* · new conformance: has-version-stamp |
| **v5.B** | HEAD vs deployed | deploy-freshness signal · C13 deploy-fresh · reads `version.json` from live URL |
| **v5.C** | Build status + deploy lag | deploy lag (push → live) · last build status via Cloudflare/Vercel API · last-build-success conformance · *requires platform tokens — major new infra* |

Strict sequence: `v1.A ✅ → v1.B ✅ → v1.C → v1.D → v2.A → v2.B → v2.C → v2.D → v3.A → v3.B → v4.A → v4.B → v5.A → v5.B → v5.C`

### Out of scope (intentionally never)

| Item | Why |
|---|---|
| Real SEO analytics (Ahrefs/SEMrush/Moz) | $$ APIs; manual remains best |
| Trademark search (USPTO) | manual at purchase time |
| Domain history (Wayback parsing) | niche |
| Social handle availability | different problem domain |
| Wide registrar API auto-sync | dropped — manual CSV exports cover it |
| Live Porkbun pricing API | dropped — low-value TLDs anyway |
| Pricing as a v3 feature | dropped — manual at purchase |

## Conventions this project enforces on siblings

These are the things `project status` will check (rules grow over time):

- Each `sites/<project>/` is its own git repo (`.git` present, toplevel == dir). Parent `sites/` should not track project files.
- `docs/Prompts.md` exists and uses dated H2 headings (`## YYYY-MM-DD`).
- Project is listed in `plan.md` under a category.
- Stack matches sites/* baseline (React+Vite ≥6 for web, Python+uv for CLIs, etc.).
- Cloudflare Pages constraints satisfied for deployable projects (frozen-lockfile install, no stray gitlinks, no SPA `_redirects` fallback).
- `Makefile` present with the standard targets (`deps`, `build`, `run`, `test`, `clean`) — mirrors parent `sites/Makefile`.

When portfolio reports a project's status, it will surface which of these the project passes and which it doesn't.

## Stack

- Python ≥3.11, managed by [uv](https://docs.astral.sh/uv/).
- typer (CLI), rich (tables), httpx (async HTTP for site checks), tldextract (domain parsing), google-api-python-client (GSC).
- Source layout: `src/portfolio/` (hatchling-packaged). Entry point: `portfolio.cli:app`.

## How to run

```bash
cd sites/portfolio
make deps                                # uv sync (auto-installs uv if missing)
make run ARGS="summary"                  # any subcommand via ARGS
```

**Do not** invoke `../Makefile`'s `make run proj=portfolio` — that target is hardcoded for pnpm/Vite projects and will fail here.

## Key files

- `domains.csv` — registrar export; source of truth for which domains are owned, expiry dates, prices.
- `plan.md` — curated categorization (To be deleted / SEO under way / My brand / Next session / Under build). Drives `category`, `wip`, and (future) `project status` resolution.
- `data/checks/*.json` — site-check snapshots (one per run).
- `data/gsc/*.json` — GSC totals snapshots (one per run).
- `src/portfolio/cli.py` — typer entry point.
- `src/portfolio/check.py` — site classification logic.
- `src/portfolio/gsc.py` — Search Console integration.
- `src/portfolio/data.py` — CSV + plan.md loaders.
