# AI_AGENTS.md — sites/portfolio/

> **Spec, roadmap, and conformance rules live in [`docs/prd.md`](docs/prd.md)** — not duplicated here. This file is for agents entering the project: what it is, how to run it, where to look.

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
- `make run ARGS="project status <name>"` — single-project status (v1.A/v1.B); fuzzy resolves against plan.md; `--json` for machine consumption

## Conventions this project enforces on siblings

`project status` reports each sibling's pass/fail/skip against a growing list of conformance rules. **The full rule catalog with pass conditions and which phase each lands in is in `docs/prd.md` § Conformance rules.** Headlines:

- Each `sites/<project>/` is its own git repo (no parent-tracking)
- Standard scaffolding present: `AI_AGENTS.md`, `README.md`, `.gitignore`, `docs/prd.md`, `docs/Prompts.md` (dated H2 entries), `Makefile` with `run`+`build` targets
- Project listed in `plan.md` under a category
- Stack matches sites/* baseline (React+Vite ≥6 for web, Python+uv for CLIs, etc.)
- Deploy platform declared (wrangler.toml / vercel.json / netlify.toml) for web projects
- Cloudflare Pages deploy constraints satisfied where applicable

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

- `data/domains/{godaddy,namecheap,porkbun}.csv` — per-registrar inventory exports; v1.C consolidates these into a unified `Domain` schema with `registrar` field.
- `plan.md` — curated categorization (To be deleted / SEO under way / My brand / Next session / Under build). Drives `category`, `wip`, and `project status` resolution.
- `data/checks/*.json` — site-check snapshots (one per run).
- `data/gsc/*.json` — GSC totals snapshots (one per run).
- `docs/prd.md` — canonical product spec, roadmap, and conformance rules.
- `src/portfolio/cli.py` — typer entry point.
- `src/portfolio/project.py` — `project status` implementation.
- `src/portfolio/check.py` — site classification logic.
- `src/portfolio/gsc.py` — Search Console integration.
- `src/portfolio/data.py` — multi-registrar CSV adapters + plan.md loader.
