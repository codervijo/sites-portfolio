# AI_AGENTS.md — sites/portfolio/

> **Spec, roadmap, and conformance rules live in [`docs/prd.md`](docs/prd.md)** — not duplicated here. This file is for agents entering the project: what it is, how to run it, where to look.

## Summary

External snapshot for planning / orientation. Operational detail follows in later sections; canonical spec is `docs/prd.md`.

**What it is.** A Python+uv CLI (`portfolio`) that manages a personal domain portfolio plus a sibling `sites/<domain>/` workspace. Single user (Vijo), CLI-only, no public surface.

**Why it exists.** As the number of sibling site projects grows, it stops being feasible to remember per-project state, deploy quirks, or where each one is in its lifecycle. portfolio is the single place to ask "what's the status of X?", enforce uniform conventions across all sites, manage the multi-registrar domain inventory, and (the scaling lever) turn "I have an idea" into "indexed live site" in under an hour.

**Scope today.**
  - 54 domains across 3 registrars (GoDaddy 44, Namecheap 7, Porkbun 4)
  - 34 sibling projects under `sites/`
  - Goal: 30 commercial sites
  - Read sources: registrar CSV exports, `data/portfolio.json` (canonical), Google Search Console (28-day window), CrUX (where it has data), HTTP live-probe, git logs, project conformance scan

**Five powers.**
  1. *Status reporting* — `project check <domain>`: git pulse + Prompts.md parsing + deploy detection + live-site state + conformance grade.
  2. *Conformance enforcement* — universal check catalog (~85 rules) covering scaffolding, git hygiene, stack baselines (pnpm-only, Vite ≥6, Astro ≥5), SEO baseline (robots, sitemap, OG, JSON-LD, favicon), Cloudflare Pages deploy constraints.
  3. *Domain inventory* — multi-registrar consolidation, expiry tracking, GSC cross-reference, drift detection.
  4. *Domain acquisition* — `new suggest <topic>`: OpenAI brainstorm + RDAP availability + Porkbun pricing → interactive shortlist → register.
  5. *Project bootstrap* — `new bootstrap <domain>`: scaffolds a new `sites/<domain>/` project at full conformance (Astro/Vite stack via central builder, SEO pack, deploy-target abstraction, CF Pages default). `new deploy` creates the GitHub repo + CF Pages project.

**Architecture.**
  - Two local-FS write surfaces only (ADR-0003): `new bootstrap` (creates project dirs) and `project fix` (remediates existing ones). Remote-host writes (v11.N `new deploy` for `hostgator`/`custom` via cPanel UAPI) are a separate category under ADR-0011 — same dry-run-default safety posture. Everything else is read-only.
  - Scope-first CLI namespaces (post-v7.A): `project` / `fleet` / `new` / `settings`.
  - Check catalog is file-per-check, auto-discovered.
  - Atomic env-file IO for credentials; HTTP connectivity probes built in.

**Roadmap status.** 28 of 34 phases shipped.

| | Status | Theme |
|---|---|---|
| v1 | ✅ | project status + multi-registrar inventory |
| v2 | ✅ | domain suggest (Power 1) |
| v3 | ✅ | bootstrap + deploy abstraction + interactive launcher (Power 2) |
| v4 | ✅ | validation pipeline + finalists workflow |
| v5 | ✅ | universal check catalog + check flags + GSC integration |
| v6 | ✅ | drift detection + per-stack rules + remediation (`fix`) + fleetwide `fleet fix` |
| v6.F | ⏳ | guided own-git-repo migration |
| v7.A | ✅ | CLI restructure to scope-first |
| v7.B | ⏳ | GSC trend correlation over persisted snapshots |
| v7.C | ⏳ | roll-up aggregate view |
| v7.D | ⏸ | LLM content seeding (postponed indefinitely) |
| v8 | ⏳ | deploy verification (build-time stamping + HEAD-vs-deployed + Pages/Vercel APIs) |

**Conventions enforced on siblings.** pnpm-only (other lockfiles fail conformance), Makefile forwards to central builder (`$(MAKE) -C ..`), own git repo (no parent-tracking), required scaffolding (`AI_AGENTS.md`, `README.md`, `docs/prd.md`, dated-H2 `docs/Prompts.md`, `Makefile` with `run`+`build`).

**Stack.** Python ≥3.11 / uv / typer / rich / httpx / tldextract / google-api-python-client. Self-contained build (does **not** use the central builder).

**Canonical docs.** `docs/prd.md` (spec, roadmap, conformance rules), `docs/architecture.md` (how it's built — mechanisms, schemas, modules, CLI/UX), `docs/shipping-history.md` (archived design rationale for shipped phases), `docs/decisions/` (ADRs — load-bearing architectural decisions, see ADR-0001), `docs/CLAUDE.md` (Claude-specific decisions + locked target shapes), `AI_AGENTS.md` (agent orientation — this file).

## Canonical docs

The five canonical doc surfaces in this repo, by purpose. **Spec discipline (per `docs/prd.md` § Spec discipline) requires that reality + code + all five surfaces match.** If you change a mechanism, schema, or decision, update the matching surface in the right doc — in the same commit.

| Doc / surface | Holds | Update when |
|---|---|---|
| `docs/prd.md` | WHY (purpose, problem, target user) + WHAT (goals, conformance rules) + WHEN (versions/phases, open questions) | Goals shift, a new phase is planned, an open question is resolved, conformance rules change |
| `docs/architecture.md` | HOW (project layout, mechanisms, schemas, modules, CLI/UX, integrations, stack baselines, active implementation plans, risks, tracked refactors) | A schema changes, a module is added/removed/renamed, a mechanism is altered, a new external integration lands |
| `docs/shipping-history.md` | Archived design rationale + resolved open questions for shipped phases (append-only) | A phase ships — move its design notes + resolved opens here |
| `docs/decisions/` (ADRs) | Load-bearing architectural decisions (Nygard format, see ADR-0001). Cross-cutting "why we chose X over Y" with consequences | A **new load-bearing decision** is made (write a new ADR); an existing decision is **superseded** (write a superseding ADR; mark the old one `Superseded by ADR-NNNN`) |
| `docs/CLAUDE.md` | Claude-specific orientation: decisions, locked target shapes, deferred decisions, heading hygiene rule, ADR workflow | A Claude-specific convention changes, a target shape is locked/unlocked, a decision is deferred or revisited |

Plus this file (`AI_AGENTS.md`) — general agent orientation; canonical versioning rule (per ADR-0004).

**Rule of thumb when editing code:**
1. If the change touches a *mechanism* or *schema*, update `architecture.md` in the same commit.
2. If the change *ships a phase*, move that phase's design notes from `prd.md` → `shipping-history.md`, update the phase row's status to `✅ done`, and tick the architecture sections it affects.
3. If the change *resolves an open question*, edit the question in `prd.md` (or move it to `shipping-history.md` if shipped).
4. **If the change introduces or reverses a *load-bearing architectural decision*, write an ADR in `docs/decisions/` in the same commit** (use next sequential number; lightweight Nygard format; see `docs/decisions/README.md` for the heuristic + template). Forward commitment: ADRs are part of the shipping unit, not a backlog item.
5. Never let docs drift "to be updated later." Stale docs are a conformance failure.

## Versioning

This project uses a **two-level `vN.X` convention** for tracking work.
The convention is enforced across all `sites/*` projects (see CHECK_013).

- **`vN`** — major capability tier (SemVer-MAJOR semantics).
- **`vN.X`** — phase letter within a tier (A, B, C, ...). Each phase
  is a shippable slice.

**Two levels only. Never `vN.X.Y`.** When follow-up work emerges inside
an existing tier, push subsequent phase letters down to make room.
Renumbered rows carry a lineage marker formatted as
`*(renumbered YYYY-MM-DD; was vN.X.Y)*`, so the history is preserved
in the row that replaced them. (Lineage markers belong only on rows
inside this repo's `docs/prd.md`; sibling projects don't introduce
them.)

This standard applies to:
- The `## 5. Phases` table in `docs/prd.md`.
- The roadmap-status table in `AI_AGENTS.md` (this file).
- Phase references in `docs/Prompts.md` and commit subjects.
- The `feature-table` skill (renders rows in this exact convention).

Don't introduce parallel schemes (no `0.1.0`, no `Sprint 3`, no
`Phase 1.A`). Don't introduce three-level identifiers under any
circumstance. The canonical statement is this section.

## Raison d'être

`portfolio` is the **inventory + standards enforcer** for the sites/ workspace. It exists because as the number of sibling projects under `sites/` grows, it stops being feasible to remember per-project state, deploy quirks, build conventions, or where each one is in its lifecycle. portfolio is the single place to:

1. Ask "what is the status of project X?" and get an answer drawn from git, project docs, plan.md, live HTTP checks, and (later) deploy verification.
2. Detect and flag deviations from sites/* conventions (own git repo, dated H2 Prompts.md, Makefile targets, Vite/uv versions, etc.).
3. Manage the multi-registrar domain inventory and (later) help acquire new domains via SEO-scored brainstorming.

For the full purpose statement, scope decisions, version/phase plan, conformance rule catalog, and out-of-scope list, read `docs/prd.md`.

## Current capabilities (CLI)

Run from `sites/portfolio/`:

- `make run ARGS="summary"` — portfolio overview (counts, registrar breakdown, plan categories, registrar/plan drift)
- `make run ARGS="list"` — all domains with expiry, status, value
- `make run ARGS="expiring --within 90"` — domains expiring soon
- `make run ARGS="category 'My brand'"` — domains in a plan category
- `make run ARGS="wip"` — work-in-progress domains
- `make run ARGS="check --only wip"` — fetch each domain, classify, snapshot to `data/checks/YYYY-MM-DD.json`
- `make run ARGS="status"` — latest check snapshot with diff vs. previous
- `make run ARGS="gsc auth | list | sync | compare"` — Google Search Console integration
- `make run ARGS="cleanup"` — rebuild `data/portfolio.json` from registrar CSVs + plan.md (v1.D; classification migration)
- `make run ARGS="project status <name>"` — single-project status (v1.A/v1.B); fuzzy resolves against `data/portfolio.json`; `--json` for machine consumption
- `make run ARGS="domain suggest <topic>"` — multi-strategy LLM brainstorm + RDAP/Porkbun availability + price (v2.A/v2.B; Power 1)
- `make run ARGS='bootstrap <domain>'` — scaffold a sites/* project to ship-ready; `--from-genai` copies a Lovable-style export from `<domain>/genai/` up; `--git-url=<url>` clones first; CF Pages safety fixes auto-applied (v3.A; Power 2)

## Conventions this project enforces on siblings

`project status` reports each sibling's pass/fail/skip against a growing list of conformance rules. **The full rule catalog with pass conditions and which phase each lands in is in `docs/prd.md` § Conformance rules.** Headlines:

- Each `sites/<project>/` is its own git repo (no parent-tracking)
- Standard scaffolding present: `AI_AGENTS.md`, `README.md`, `.gitignore`, `docs/prd.md`, `docs/Prompts.md` (dated H2 entries), `Makefile` with `run`+`build` targets
- Project has a category set in `data/portfolio.json` (was plan.md pre-v1.D)
- Stack matches sites/* baseline (React+Vite ≥6 for web, Python+uv for CLIs, etc.)
- Deploy platform declared (wrangler.toml / vercel.json / netlify.toml) for web projects
- Cloudflare Pages deploy constraints satisfied where applicable

## Stack

- Python ≥3.11, managed by [uv](https://docs.astral.sh/uv/).
- typer (CLI), rich (tables), httpx (async HTTP for site checks), tldextract (domain parsing), google-api-python-client (GSC).
- Source layout: `src/portfolio/` (hatchling-packaged). Entry point: `portfolio.cli:app`.

## Building info

**Stack: Python ≥3.11 with uv. Does NOT use the central builder repo** (this is a deliberate exception — see `reference_builder_repo.md` in agent memory). The central multi-stack builder at `~/work/projects/builder/` is geared toward web app stacks (react / tauri / expo / etc.); portfolio is a CLI that lives in Python land with its own self-contained `Makefile` using `uv` directly.

To build / run from this dir:

```bash
cd sites/portfolio
make deps                  # uv sync (auto-installs uv if missing)
make build                 # uv build → wheel
make run ARGS="summary"    # invoke the CLI; pass args via ARGS=
make test                  # uv run pytest
make clean                 # remove .venv, dist, *.egg-info, __pycache__
```

**Do not** invoke `../Makefile`'s `make run proj=portfolio` — that target is hardcoded for pnpm/Vite projects (which is what the rest of sites/* uses through the builder) and will fail here.

## Deployment info

- **Platform**: n/a — portfolio is a CLI, not a deployable web app.
- **Live URL**: none.
- **Last deployed commit**: n/a.
- **Deploy trigger**: n/a — runs locally on the user's machine.
- **Notes**: this project's `platform-declared` conformance rule resolves to `n/a` based on its `kind = cli` (detected from `pyproject.toml`).

## Key files

- `data/domains/{godaddy,namecheap,porkbun}.csv` — per-registrar inventory exports; v1.C consolidates these into a unified `Domain` schema with `registrar` field.
- `data/portfolio.json` — canonical inventory + classifications, generated by `portfolio fleet info cleanup` (v7.A; was `portfolio info cleanup`). Each domain has `name, registrar, category, expires, ...`. Drives `fleet info summary --verbose` and `project check` resolution.
- `plan.md` — DEPRECATED post-v1.D; kept for historical reference; will be deleted in a future cleanup commit.
- `data/checks/*.json` — site-check snapshots (one per run).
- `data/gsc/*.json` — GSC totals snapshots (one per run).
- `docs/prd.md` — canonical product spec, roadmap, and conformance rules.
- `src/portfolio/cli.py` — typer entry point.
- `src/portfolio/project.py` — `project status` implementation.
- `src/portfolio/check.py` — site classification logic.
- `src/portfolio/gsc.py` — Search Console integration.
- `src/portfolio/data.py` — multi-registrar CSV adapters + plan.md loader.
