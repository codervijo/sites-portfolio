# 0012 — No `wrangler deploy`; git-integrated Cloudflare Pages API for all CF deploys

- **Status:** Accepted
- **Date:** 2026-05-20

## Context

`lamill new deploy <domain>` historically routed Cloudflare-platform
sites through one of two paths:

- `platform=cf-pages` → `_deploy_cf_pages_v3c()` — creates the GitHub
  repo (via `gh` CLI), creates the CF Pages project via API, and
  hands the wiring off to Cloudflare's GitHub-integration so every
  subsequent push to `main` auto-deploys.
- `platform=cf-workers` → `_deploy_cf_workers()` — calls
  `pnpm run deploy` in the project dir, which under the hood runs
  `wrangler deploy` and ships the worker as a one-shot.

The two paths diverged on the **CD posture**:

- cf-pages is git-integrated (push-to-deploy; CF builds in their
  infrastructure on every commit).
- cf-workers via `wrangler deploy` is **one-shot manual**. The
  operator re-runs the deploy command each time. No CI/CD by default
  unless the operator wires up a GitHub Action.

Adjacent observations driving this decision:

1. **The operator's actual fleet** is uniformly git-integrated. The
   CF Workers & Pages dashboard for `cricketfansite` / `donready` /
   `isitholiday` / `kwizicle` / `voltloop` / `airsucks` all use the
   git-connected build flow. Push-to-deploy is the operator's
   mental model; `wrangler deploy` was an exception driven by
   `airsucks`'s earlier setup.
2. **Cloudflare unified Workers + Pages.** As of 2026 the same
   `/accounts/{account_id}/pages/projects` API endpoint serves
   both traditional Pages projects AND Workers Static Assets
   projects. There is no separate public "Workers Builds" API for
   creating git-integrated Worker projects programmatically; the
   Pages projects API is the supported path.
3. **Bootstrap default flip** to `platform = "cf-workers"` (per
   ADR-0013) means the new-default deploy path needs CD on day one.
   Shipping a default that requires `wrangler login` + remembered
   re-runs is the wrong shape.

Two options surfaced during the v15.G-J planning session:

- **Option A — Keep `wrangler deploy` for cf-workers.** Cleaner
  separation: each platform handled by its tool of choice. But
  requires the operator to set up GitHub Actions (or manually
  re-run) for every cf-workers site. Loses CD on the new default.
- **Option B — Unify all CF deploys onto the Pages-API +
  git-integration path.** Same single pipeline serves cf-pages AND
  cf-workers, with CD on day one. Removes `wrangler` from the
  `lamill` deploy code path entirely.

Operator picked Option B 2026-05-20 with the directive: *"i prefer
not to use the wrangler route; all other projects are setup such
that it is connected to github, and commits automatically deploy."*

## Decision

`lamill new deploy <domain>` for `platform ∈ {cf-pages, cf-workers}`
**always** goes through the Cloudflare Pages-API git-integrated
flow. `wrangler deploy` is not invoked from any code path in
`portfolio` / `lamill`.

Concretely:

- The Pages-API endpoint is
  `POST /accounts/{account_id}/pages/projects` with a `source.type =
  "github"` block at create-time. CF queues a build from the
  connected repo immediately; subsequent pushes auto-deploy.
- The same endpoint serves Workers Static Assets projects (via
  unified Workers & Pages). No separate Workers-Builds API call.
- `_deploy_cf_workers()` and `_deploy_cf_pages_v3c()` collapse into
  one `_deploy_cf_unified()` orchestrator. Both platform values
  route here.
- The deploy pipeline (v15.I) becomes idempotent: every step (GH
  repo, CF zone, registrar NS, CF project, custom domain, build
  poll) probes existing state before mutating.

### Permitted CF deploy surfaces (as of 2026-05-20)

1. `lamill new deploy <domain>` for `platform ∈ {cf-pages,
   cf-workers}` — goes through `_deploy_cf_unified()` (v15.I).

### What's NOT happening

- **No `wrangler deploy` calls** in the deploy pipeline.
- **No CLI-only deploys for CF sites.** Every CF deploy creates or
  uses an existing git-integrated CF project; CF builds in its
  infrastructure from the connected GH repo. The operator can still
  use `wrangler` locally for development (`wrangler dev`,
  `wrangler tail`); this ADR only constrains the `lamill new deploy`
  path.
- **No Workers Builds API surface.** That API isn't documented for
  public use as of 2026-05-20 (only dashboard configuration). The
  Pages projects API is the supported substitute.

## Consequences

### Positive

- **One pipeline, one mental model.** Every CF deploy is
  git-integrated; every push to `main` auto-deploys. Operator no
  longer needs to remember which sites are wrangler-driven vs which
  are git-driven.
- **No `wrangler login` dependency.** New operators (or fresh CI
  machines) only need GitHub auth + a Cloudflare API token, not the
  full wrangler OAuth dance.
- **Idempotency by design.** The Pages-API exposes GET endpoints
  for every CREATE — every step in the pipeline can probe existing
  state before mutating, so re-running `new deploy` on a
  partially-deployed site picks up where it left off.
- **Single audit surface.** All CF deploys produce activity on the
  CF Pages projects + git history of the connected repo. No
  out-of-band `wrangler` deploys to reconcile against.

### Negative / Constraints

- **CF GitHub App must be installed once per Cloudflare account.**
  This is a one-time dashboard step (`https://dash.cloudflare.com/?
  to=/:account/workers-and-pages/create/connect-to-git`) that
  `lamill` cannot automate via the public API. Pipeline pre-flight
  surfaces an instructive error if missing.
- **Loss of one-shot deploy.** Edge cases where the operator wants
  to ship a hand-built `dist/` without going through a git commit
  are not supported by this pipeline. The operator would need to
  use `wrangler deploy` manually outside `lamill` — accepted
  trade-off; that path was rarely-if-ever used in practice.
- **Migration of `airsucks.com`.** The site is currently deployed
  via `wrangler deploy` and labeled `platform = "cf-workers"`. It
  stays untouched per operator 2026-05-20; future re-deploys go
  through the new pipeline (which creates the git-integrated
  project on first run).
- **Pages-API gaps for Workers-specific features.** Workers Bindings
  (KV / D1 / Durable Objects / R2 / queues) can be configured via
  `deployment_configs.production.bindings` in the Pages-API project
  shape. Workers-only features without Pages-API equivalents
  (`event` triggers like `cron`, `email`) are not supported by this
  pipeline; sites needing those must remain on `wrangler deploy`
  outside `lamill`.

## Status & supersession

Accepted 2026-05-20. Pairs with ADR-0013 (Astro+Vite as the only
supported stack, with Claude-subprocess translation for non-Astro
`--git-url` repos). Future supersession candidates: a CF Workers
Builds public API endpoint that obsoletes the Pages-API workaround,
OR a re-discovered need for one-shot `wrangler deploy` flows that
the operator wants `lamill` to drive directly.
