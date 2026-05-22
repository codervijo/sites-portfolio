# architecture.md — sites/portfolio/

**Canonical "how it's built" doc for `portfolio` / `lamill`.**

Companion to `docs/prd.md` (the WHY / WHAT / WHEN) and
`docs/shipping-history.md` (archived design rationale for shipped phases).

This document is the **single source of truth for current mechanisms,
schemas, modules, and CLI/UX conventions**. Per `prd.md § Spec
discipline`: reality + code + docs must match. If you change a
mechanism or schema in code, update the matching section here in the
same commit.

## 1. Project layout

```
sites/portfolio/
├── src/portfolio/                # Python package (hatchling-built)
│   ├── cli.py                    # typer app — entry point (portfolio.cli:app)
│   ├── project.py                # `project check` / `project fix` runner
│   ├── check.py                  # site classification
│   ├── data.py                   # multi-registrar CSV adapters + portfolio.json
│   ├── bootstrap.py              # `new bootstrap` write surface
│   ├── deploy.py                 # `new deploy` (GitHub repo + CF Pages project)
│   ├── suggest.py                # `new domain` (Power 1 — domain brainstorm)
│   ├── decide.py                 # validation-mode shortlist + decide
│   ├── availability.py           # RDAP + Porkbun availability/pricing
│   ├── cloudflare.py             # CF API client (Pages + Workers)
│   ├── gsc.py                    # Google Search Console OAuth + queries
│   ├── gsc_recrawl.py            # GSC sitemap-resubmit flow
│   ├── ga4_admin.py              # GA4 Admin API client + OAuth (v18.C)
│   ├── gtrends.py                # Google Trends via pytrends (v19.B)
│   ├── seo_runtime.py            # live HTTP SEO probe orchestrator
│   ├── seo_cache.py              # snapshot save/load for `data/seo/`
│   ├── serp.py                   # cluster builder for `new validate`
│   ├── serp_fetch.py             # SerpAPI client
│   ├── serp_query_cache.py       # per-query snapshot cache under `data/serp/`
│   ├── serpapi_quota.py          # SerpAPI monthly-quota counter
│   ├── research_v2.py            # `new validate` orchestrator (Phases 1-3 mechanical)
│   ├── research_gates.py         # gate classification (Gate 1/2/3)
│   ├── interpretive_pass.py      # Phase 4a — primary verdict (Claude Sonnet)
│   ├── audit_pass.py             # Phase 4b — adversarial audit (GPT-4o)
│   ├── operator_profile.py       # `[operator]` block reader (lamill.toml)
│   ├── prompt_loader.py          # load + {{var}} render of `prompts/*.md`
│   ├── canonical_sections.py     # v9.A/v9.E AI_AGENTS section schema (JSON-driven)
│   ├── templates.py              # bootstrap template source + section emitters
│   ├── fleet_repos.py            # `fleet repos` audit + naming-consistency
│   ├── dashboard.py              # `fleet dashboard` unified view
│   ├── focus.py                  # `fleet focus` priority ranker
│   ├── drift.py                  # `fleet drift` cross-source comparator
│   ├── diagnose.py               # `project diagnose <domain>` 5-layer
│   ├── menu.py                   # interactive launcher
│   ├── apikeys.py                # `settings apikeys` (KNOWN_KEYS + probes)
│   ├── fix_helpers.py            # Tier 1 fixer factories + `run_claude_text`
│   ├── fix_registry.py           # fixer discovery + tier dispatch
│   └── checks/                   # universal check catalog
│       ├── registry.py           # auto-discovery + run() entry
│       ├── result.py             # CheckResult dataclass
│       ├── config.py             # per-check metadata helpers
│       ├── scaffold/             # CHECK_001-019 scaffold files
│       ├── git/                  # CHECK_020-024 git hygiene
│       ├── stack/                # CHECK_025-039 pnpm/Vite/Astro baselines
│       ├── deploy/               # CHECK_040-049 deploy declarations
│       ├── seo/                  # CHECK_050-099 robots/sitemap/OG/JSON-LD/CrUX
│       └── content/              # CHECK_130-137 content-pipeline
├── data/
│   ├── portfolio.json            # canonical inventory + classifications
│   ├── domains/{godaddy,namecheap,porkbun}.csv  # per-registrar exports
│   ├── checks/<YYYY-MM-DD>.json  # one site-classification snapshot per run
│   ├── seo/<YYYY-MM-DD>.json     # SEO probe snapshots
│   ├── gsc/<YYYY-MM-DD>.json     # GSC totals
│   ├── serp/<YYYY-MM-DD>/        # SerpAPI cache per day
│   │   ├── _quota.json           # monthly-quota counter
│   │   └── clusters/<hash>.json  # cluster analysis (research-cluster-v2.1)
│   └── hosting/<YYYY-MM-DD>.json # fleet hosting (v11.A; planned)
├── prompts/                      # first-class, edited by operator (v8.E)
│   ├── README.md
│   ├── niche_evaluation_v1.md    # primary interpretive prompt
│   └── adversarial_audit_v1.md   # audit pass prompt
├── docs/                         # canonical doc surfaces (see §Canonical docs)
├── tests/                        # pytest tests, mirrors src/portfolio layout
├── pyproject.toml                # hatchling + uv
├── Makefile                      # self-contained (does NOT delegate to builder)
└── lamill.toml                   # this repo's own deploy + [operator] decl
```

Sibling projects under `sites/<domain>/` follow a separate conventions
contract — they are managed BY this tool, not part of its package. See
§7 Stack baselines for the per-site shape.

## 2. Write surfaces

Two categories, governed by separate ADRs.

### 2.1 Local-FS writes (ADR-0003)

**Two surfaces only** into sibling `sites/<domain>/` project dirs.
Adding a third needs an explicit operator decision and a superseding
ADR.

| Surface | Purpose | Operator gate |
|---|---|---|
| `new bootstrap <domain>` | Creates a new `sites/<domain>/` project dir — `git init`, scaffolds AI_AGENTS.md / docs / Makefile / public assets / `lamill.toml`, sets up the central-builder forward | Required positional arg; no implicit-create flow |
| `project fix <domain> --apply` | Modifies an existing project dir to close conformance gaps — runs Tier 1 templated fixers, optionally Tier 2 Claude subprocess | `--apply` required (default is dry-run); `--yes` skips confirmation |

Read-only against `sites/<domain>/`: everything else — `new domain`,
`fleet *`, `project check`, `project diagnose`, `settings *`, and
`new deploy` (which reads the project dir but writes to
remote hosts, never back to the local FS). Snapshot files under
`data/` and credential rotation through `settings apikeys` are not
project-dir writes; they're tool-local state.

The two-surface constraint is *load-bearing* for trust: an operator
can run `lamill <anything>` against an unrelated repo and know it
won't be modified locally.

### 2.2 Remote-host writes (ADR-0011 — v11.N)

A separate category for writes that push bytes to an external host.
Currently one surface; future remote write surfaces inherit
ADR-0011's constraints.

| Surface | Purpose | Operator gate |
|---|---|---|
| `new deploy <domain> --apply` *(hostgator / custom only)* | Uploads `sites/<domain>/<[hosting].deploy_source>/` to `[hosting].public_html_path` on the cPanel host via UAPI. Stage-then-rename atomicity (see §3 Active deploy verb). | `--apply` required (default is dry-run); per-site allowlist via `lamill.toml` `[hosting]` block; one site per invocation |

ADR-0011 constraints, applied via code review (not the conformance
catalog): idempotent payload, dry-run default, per-site allowlist,
stage-then-rename where the platform allows it, no credentials in
the payload.

### 2.3 External API state changes (cf-pages / cf-workers / vercel deploys)

The cf-pages / cf-workers / vercel branches of `new deploy` trigger
remote-side state changes (per ADR-0012 + the v15.I unified pipeline):

- **CF zone create** via `POST /zones`
- **Registrar NS update** via `POST /domain/updateNs` (Porkbun only;
  other registrars warn-instruct)
- **GitHub repo create** via `POST /user/repos` (or `gh` CLI fallback)
- **CF Pages project create** via `POST /accounts/{id}/pages/projects`
  with `source.type=github` — registers the GH repo with CF; future
  pushes auto-deploy
- **CF custom-domain attach** via `POST /accounts/{id}/pages/projects/
  {name}/domains`
- **Git push** (`git push -u origin main`) for the initial commit
- **Vercel deploy** via `vercel deploy --prod` shell-out (vercel
  platform only)

None of these write to sibling `sites/<domain>/` project directories
(ADR-0003 scope) or to a cPanel host (ADR-0011 scope). They mutate
external SaaS state, which is its own audit surface — each step is
logged to stdout with the API path / state change, and each step is
idempotent (re-running detects existing state and prints
`✓ exists, skipping`).

## 3. Mechanisms

### Check catalog

Universal conformance catalog at `src/portfolio/checks/<category>/check_NNN_<slug>.py`.

- **File-per-check** (ADR-0005). Each check is its own module with a
  module-level `check(repo_path) -> CheckResult` function plus
  metadata constants (`ID`, `TITLE`, `CATEGORY`, `SEVERITY`).
- **Registry** (`checks/registry.py`) auto-discovers every
  `check_*.py` at import time. No central list to maintain.
- **`CheckResult`** dataclass (`checks/result.py`): `id`, `status`
  (`pass` / `fail` / `skip`), `title`, `category`, `severity`,
  `message`, `details` (optional dict).
- **Category taxonomy**: `scaffold`, `git`, `stack`, `deploy`, `seo`,
  `content`. Numbered ranges per category (e.g. SEO is CHECK_050+).
- **Runner**: `project.py:run_checks(repo_path, *, filters)` invokes
  the registry against one repo. `fleet check` invokes it across
  every `sites/<domain>/` not in `ignore_repos`.
- **Fleet exclusions**: `[git] ignore_repos = ["portfolio"]` in
  `~/.config/portfolio/config.toml` keeps the tool's own repo out of
  the per-site SEO/stack checks (Python CLI, not a website).

### Fix-tier

Each check module can co-locate two attributes:

- **`fix_tier_1`** — a callable `(repo_path) -> FixResult`. Templated
  fixer built via factories in `src/portfolio/fix_helpers.py` (atomic
  file write, idempotent, deterministic). Examples: add a missing
  `robots.txt`, append a missing canonical-section to AI_AGENTS.md.
- **`fix_tier_2`** — a callable that runs an LLM subprocess via
  `run_claude_text()` (ADR-0006). Used when the fix requires reading
  surrounding code/content and applying a context-aware edit. Restricted
  tools, capped runtime, output captured for the run summary.

`fix_registry.py` discovers fixers by inspecting each check module
for these attributes. `project fix --tier 1` runs only Tier 1;
`--tier 2` includes Tier 2; default runs both.

### Provider walkers (v11.A — `fleet hosting`)

Pluggable per-provider walker pattern in `src/portfolio/hosting.py`.
v11.A absorbed v10.F on 2026-05-18; HostGator UAPI walker joins
Vercel + CF Pages as the third provider:

- `walk_vercel(token, only_domain=None) -> list[HostingRow]`
- `walk_cf_pages(api_token, account_id, only_domain=None) -> list[HostingRow]`
- `walk_hostgator(token, account_id, only_domain=None) -> list[HostingRow]`

The first two walkers have a build-pipeline shape — projects, deploys,
deploy history. The HG walker has a different shape — no build-deploy
concept, so `latest_deploy_status` / `latest_deploy_at` /
`last_successful_deploy_at` / `consecutive_failures` all stay None.
HG fills the typed-optional fields `disk_used_mb`, `wp_version`,
`install_path` (per resolution 11.M) which the renderer surfaces as
a compact `[disk · WP]` suffix.

Each Vercel/CF walker:
1. Paginates the provider's projects-list endpoint.
2. For each project, reads the latest deploy + walks deployment
   history (capped at `MAX_DEPLOY_LOOKBACK=10`; two-tier — stop at 10
   and mark "≥10 consecutive failures").
3. Maps each project's configured custom domains to fleet domains via
   bare-host match (strips leading `www.`).
4. Returns one `HostingRow` per matched fleet domain; unmatched
   projects drop silently (they're not in the fleet).

The HG walker:
1. Calls cPanel UAPI per account (two accounts in the fleet:
   `gator3164`, `gator4216`). cPanel host auto-derived from the
   account_id — `https://<account_id>.hostgator.com:2083` —
   authenticated as `<account_id>:<HOSTGATOR_TOKEN_<ACCOUNT_ID>>`
   via HTTP Basic per resolution 11.L. No separate
   `HOSTGATOR_HOST_*` override env var (add later if a custom-host
   case appears).
2. `DomainInfo/list_domains` enumerates addon domains;
   `Quota/get_quota_info` gets disk-used (account-level, not
   per-domain — disk_used_mb is per-account, attached to all rows
   from that account for now).
3. WP detection: `WordPressManager/list_installations` if the
   plugin is available, else fallback to `Fileman/list_files` and
   look for `wp-includes/version.php` under each addon-domain's
   document root.
4. Returns one `HostingRow` per addon domain matched to the fleet.

`run_hosting(domains)` orchestrator calls all three walker families
in parallel (`ThreadPoolExecutor`, mirrors `seo_runtime.run_seo`).
Per-account HG walks happen as two parallel tasks within the
orchestrator. Domains matched by MULTIPLE providers emit one row
per provider with `provider_conflict=True` in `notes[]` — drift
signal (e.g. an apex on CF Pages + an addon-domain entry on HG).

Provider error surfaces follow `prd.md` v11 Design notes — resolution 11.H:
- 401 (auth) → skip the affected walker (or per-account HG walker)
  entirely; footer says "<Provider> skipped: token missing/invalid."
- 5xx / rate-limit → per-row `error` field on affected domains;
  renders with `?` glyph.

### Active deploy verb (v11.M-N — `new deploy <domain>`; v15.I unification per ADR-0012)

`new deploy` is a polymorphic dispatcher in `cli.py::new_deploy` —
reads `<sites/<domain>/lamill.toml>.deploy.platform` and routes to
the right deploy implementation. Branches:

| `platform` | Mechanism | Module |
|---|---|---|
| `cf-pages` / `cf-workers` (v15.I+) | **Unified git-integrated CF Pages-API pipeline** per ADR-0012. Creates GH repo via `POST /user/repos` (or `gh` CLI fallback) → creates CF zone via `POST /zones` → updates registrar NS (Porkbun via `POST /domain/updateNs`; other registrars warn-instruct) → creates CF Pages project with `source.type=github` git source via `POST /accounts/{id}/pages/projects` → attaches custom domain via `POST /accounts/{id}/pages/projects/{name}/domains` → polls build status via `GET /accounts/{id}/pages/projects/{name}/deployments?per_page=1` (`latest_stage.status`). Idempotent at every step; honors `--dry-run` and `--yes`. **No `wrangler deploy` call.** | `cli.py::_deploy_cf_unified` + `cloudflare.py` (extended) + `gh_repo.py` + `porkbun_dns.py` |
| `vercel` | Shells out to `vercel deploy --prod` | `deploy.py::deploy_vercel_via_shell` |
| `hostgator` / `custom` | cPanel UAPI uploader with stage-then-rename atomicity (ADR-0011) | `cli.py::_deploy_hostgator_v11n` + `hosting.py::deploy_hg_files` |
| `netlify` / `github-pages` | Not yet implemented — exits with a clear "track in a future v11.X" message | — |
| `none` | Rejects with a `settings deploy set` hint | — |
| (missing `lamill.toml`) | Assumes `cf-workers` (v15.I bootstrap default; was `cf-pages` pre-v15.I) with a notice — backward-compat with pre-v10.A repos | — |

**v15.I changed the CF deploy story** (ADR-0012). The v11.M era had
two separate CF branches (`cf-pages` → first-time-setup orchestrator;
`cf-workers` → `pnpm run deploy` wrangler one-shot). The split was a
mismatch with the operator's actual fleet, which is uniformly
git-integrated. The new unified pipeline serves both platform values
via the same CF Pages-API endpoints (CF unified Workers & Pages
under one API surface in 2024-2026). No `wrangler` call appears in
the deploy code path anymore — pure REST + git push.

The vercel branch still shells out to `vercel deploy --prod` for
its CLI's hash-and-upload pipeline; this stays per-platform because
replicating Vercel's file-hashing logic against raw HTTP is a
maintenance trap. The shell helpers take a `runner=` injection seam
so tests don't fork real subprocesses.

The HostGator / custom branch is the only one that adds a new
remote-host write surface (ADR-0011). It runs through three layers:

1. **CLI shim** (`cli.py::_deploy_hostgator_v11n`) — reads token via
   `apikeys.get_key("HOSTGATOR_TOKEN_<account>")`, cpanel_user via
   `apikeys.hg_user_for_account()`, latest `HostingRow` for the
   domain via `hosting_cache.latest_snapshot()` (refuses to deploy
   without a snapshot — hints to `fleet hosting --refresh`).
2. **Orchestrator** (`hosting.py::deploy_hg_files`) — single-row by
   design (ADR-0011 per-site allowlist). Walks
   `sites/<domain>/<deploy_source>/` for the payload (where
   `deploy_source` defaults to `"dist/"`, configurable in
   `[hosting]`). Coordinates the stage-then-rename dance.
3. **UAPI helpers** (`hosting.py::_hg_upload_file`, `_hg_mkdir`,
   `_hg_rename`, `_hg_delete_dir`) — wrap the corresponding cPanel
   Fileman endpoints. `upload_file` is a multipart POST; the others
   are GET via the existing `_call_hg_uapi`.

Stage-then-rename atomicity (per resolution 11.T):

```
1. mkdir <public_html_path>.next/
2. upload every file from sites/<domain>/<deploy_source>/
   (lazy mkdir of subdirs as needed)
3. rename current → .prev/       (benign-failure on first-time deploy)
4. swap .next/  → current        ← the load-bearing rename
5. delete .prev/                 (best-effort, non-fatal)
```

Brief downtime window between renames 3 and 4 — acceptable for
static sites (WP excluded per resolution 11.R). On step-4 failure,
the orchestrator renames `.prev/` back to current so prod stays up.

`HgDeployRow.action` vocabulary mirrors `HgApplyRow` from v11.J:
`would_deploy` / `deployed` / `skipped_wp` / `skipped_no_source` /
`skipped_no_path` / `failed`. WP-skip fires when the snapshot row's
`wp_version` field is set — uploading a static `dist/` over a
WordPress install would clobber it.

`new deploy <hg-domain>` defaults to dry-run for the hostgator /
custom branches (prints file count + bytes + target path).
`--apply` is required to actually push. Other branches keep their
existing flag semantics (cf-pages has its own per-step interactive
confirms; cf-workers + vercel apply immediately).

### Research module (v8.E–v8.J + v12.A–G — tier complete 2026-05-19)

Three-stage pipeline added to `new validate`:

1. **Phase 4a — Primary interpretive pass** (`interpretive_pass.py`).
   Renders `prompts/niche_evaluation_v1.md` with operator-profile +
   mechanical-gates payload, calls `run_claude_text()` (Claude CLI
   subprocess, not the Anthropic SDK — avoids a second API-key
   surface, rides the operator's existing Claude subscription quota).
   Parses markdown response into `ParsedVerdict`. Cost on cluster
   snapshot at `primary_pass_meta.cost_usd` (typically ~$0.04).

2. **Phase 4b — Adversarial audit pass** (`audit_pass.py`). Renders
   `prompts/adversarial_audit_v1.md`. Calls OpenAI Responses API
   (`POST /v1/responses`; gpt-4o default; override via
   `--audit-model`). Strict-different-model invariant:
   `--audit-model X` matching the primary's `model_id` is rejected
   loudly (exit 2) with the correlated-blind-spot rationale. Parses
   into `ParsedAudit` (different schema than primary —
   agreement_level / confidence / specific_concerns /
   counter_verdict / audit_self_check). Cost computed from token
   usage × per-model pricing table (gpt-4o / gpt-4o-mini /
   gpt-4-turbo / gpt-4.1; dated aliases prefix-match the base
   model). Cost on snapshot at `audit_pass_meta.cost_usd` (typically
   ~$0.012).

3. **Phase 4c — Reconciliation** (`reconciliation.py`, no LLM call).
   Pure-logic reconciliation per `agreement_level`:
   - `full` → primary verdict; confidence preserved verbatim (no
     min-aggregation — audit confirming a primary's LOW-confidence
     call doesn't make the underlying data stronger)
   - `partial` → primary verdict; confidence downgraded one notch
     (HIGH→MEDIUM, MEDIUM→LOW, LOW→LOW saturates); caveats from
     `audit.specific_concerns`
   - `disagree` → `REVIEW_REQUIRED` (first-class verdict alongside
     GO / NICHE-DOWN / NO-GO; confidence LOW); caveats surfaced; no
     auto-resolution per the human-tiebreaker principle.

Both prompts live at repo-root `prompts/` (first-class, alongside
`tests/` and `docs/`). Versioned `<purpose>_v<N>.md`. Snapshots
record `prompt_version`; mismatch with the current `_vN.md` is
"stale verdict — re-render via `--invalidate interpretive`."

The audit pass is **opt-in** behind `--verify`. Default mode is
primary-only (cost ~$0.04/run); verify mode adds the audit pass
(~$0.012 at gpt-4o pricing → total ~$0.05/run). Operator-profile
flag `verify_by_default` (in `sites/portfolio/lamill.toml
[operator]`) flips the default to verify-always;
`--no-verify` overrides per-run.

Granular cache invalidation via `--invalidate {interpretive, audit,
all}` skips the per-pass cache short-circuit while keeping the
SerpAPI cluster cache (different from `--no-cache`, which bypasses
that cache entirely). Lets the operator re-tune prompts against
the same SERP data without re-burning SerpAPI quota.

Render-footer summary shows total LLM cost (and per-pass breakdown
when both passes contributed) from the snapshot's `costs` block
(v12.F).

ADR-0011 governs remote-host writes (v11.N's UAPI uploader);
v12's audit pass is a read-only LLM call against an external API
and does NOT touch any write surface — no ADR was needed for v12.

### Prompt loader

`src/portfolio/prompt_loader.py` provides:

- `load_prompt(name) -> str` — reads `prompts/<name>.md`.
- `render_prompt(template, **vars) -> str` — custom `{{var}}` regex
  substitution. Stdlib only; no Jinja2 dep; no curly-brace collision
  with code-block examples in prompts.
- **Substitution validator** raises on any `{{placeholder}}` left
  unfilled in the rendered prompt — fails before any LLM call.

Loader-level invariant: every prompt sent to an LLM is captured
verbatim in the snapshot (rendered text + prompt version + model id),
so old caches can be re-rendered with their original prompt for
audit/comparison.

### Snapshot lifecycle

All snapshots are JSON files under `data/<layer>/<YYYY-MM-DD>.json`,
written atomically (tmpfile + rename). Each layer has its own cache
helper module (`seo_cache.py`, `hosting_cache.py` planned). Pattern:

- `save_snapshot(rows, *, scope) -> Path`
- `latest_snapshot() -> Path | None`
- `load_snapshot(path) -> dict`
- `rows_from_snapshot(path) -> list[Row]`
- `is_stale(path, max_age_hours=24) -> bool`

Snapshots are **git-tracked** (ADR-0009 territory; same convention
as v8.D — see `docs/shipping-history.md` v8.D §8.E for the retention
rationale). Disk isn't a constraint at personal scale; the trend
analysis benefit is real.

## 4. Schemas

### Config schemas

#### `portfolio.env`

Lives in repo root, gitignored. KNOWN_KEYS (enforced by
`settings apikeys`):

- `OPENAI_API_KEY` — `new domain`, `audit_pass`
- `PORKBUN_API_KEY`, `PORKBUN_SECRET_API_KEY` — availability +
  registration
- `CF_API_TOKEN`, `CF_ACCOUNT_ID` — Pages + Workers walker
- `CRUX_API_KEY` — `seo_runtime` field-data probe
- `SERPAPI_KEY` — `new validate` real SERP fetch
- `GOOGLE_OAUTH_*` — GSC integration
- `VERCEL_TOKEN` — v11.A `fleet hosting` (planned)
- `ANTHROPIC_API_KEY` — reserved; current implementation uses the
  Claude CLI subprocess, so this is only required if the operator
  switches the primary pass to direct-API mode.

`settings apikeys list` shows name + set/not-set + per-provider
connectivity tick (✓ / ✗ / dim). `set` is strict — only KNOWN_KEYS
unless `--force`.

#### `sites/<domain>/lamill.toml` (v10.A — planned)

```toml
schema = "lamill-toml-v1"

[deploy]
# REQUIRED — one of:
#   cf-pages | vercel | netlify | cf-workers | hostgator
#   github-pages | custom | none
platform = "cf-pages"

# OPTIONAL
account = "vik@personal"             # disambiguate multi-account setups
production_branch = "main"
auto_deploy = true                   # default: true for git-native platforms,
                                     # false for hostgator/custom
custom_domains = ["example.com"]

[hosting]
# Required when platform ∈ {hostgator, custom}. Optional otherwise.
cpanel_user = "vikt"
cpanel_url = "https://gator4045.hostgator.com:2083"
ftp_host = "ftp.example.com"
ftp_user = "vikt@example.com"
ftp_port = 21
public_html_path = "/home/vikt/public_html/example.com/"

[analytics]
# v18.D — written by `new bootstrap` when GA4 auto-create succeeds.
# `ga4_id` is the measurement ID returned by the Admin API (matches
# `G-[A-Z0-9]{6,12}` shape). The SEO pipeline (separate project)
# reads this and handles markup injection — portfolio owns the
# property creation lifecycle, not the gtag block in the site's
# Layout.
ga4_id = "G-HP39MQPM2M"

[notes]
text = """
Free-form prose for transition states, deploy quirks, etc.
"""

[operator]
# Filled only on sites/portfolio/lamill.toml (the tool's own repo).
# Other sites omit this section.
expertise = ["SEO and programmatic content", "Python CLI tooling"]
workflow_preference = "builder"      # builder | writer | mixed
motivation_cadence  = "weekly"       # weekly | monthly | quarterly
verify_by_default = false            # v12 — flips `new validate --verify` default
```

**Defaults applied if section absent:**
- `[deploy]` required.
- `[hosting]` optional; required if `platform ∈ {hostgator, custom}`.
- `[analytics]` optional; bootstrap omits the block when GA4 auto-create
  is skipped (`--skip-ga4`, OAuth not configured, or Admin API failure).
- `[notes]`, `[operator]` optional.
- Operator-profile defaults when section/file is missing:
  `expertise=[]`, `workflow_preference="mixed"`,
  `motivation_cadence="monthly"`, `verify_by_default=false`.

Schema versioning: tolerant-on-read / strict-on-write (per `prd.md`
v10 Design notes — resolution 10.E). Tool reads v1 with fallback
defaults; never writes v1 once schema bumps.

**Backend section (v10 expansion, 2026-05-17):** scope extended
to include a `[backend]` block for non-JS-rendering server stacks
(DB + server framework + backend-hosting target). Schema details
land when the first such site exercises the slot.

#### Platform enum (v10.A)

| Value | Canonical config in repo | Notes |
|---|---|---|
| `cf-pages` | `wrangler.toml` / `wrangler.jsonc` | Cloudflare Pages |
| `cf-workers` | `wrangler.jsonc` | Cloudflare Workers (server mode) |
| `vercel` | `vercel.json` (optional) | Vercel auto-deploy from Git |
| `netlify` | `netlify.toml` | Netlify auto-deploy |
| `github-pages` | (none — GH-side config) | Static via repo settings |
| `hostgator` | (none) | Shared hosting; requires `[hosting]` |
| `custom` | (none) | VPS / dedicated / unusual; requires `[hosting]` |
| `none` | (none) | CLI / library / scratch project (not deployed) |

#### `~/.config/portfolio/config.toml`

Tool-local config. Currently holds `[git] ignore_repos` (list of repo
names excluded from `fleet check`).

### Snapshot schemas

#### `data/seo/<YYYY-MM-DD>.json`

Per-fleet-domain SEO probe results: live HTTP probe (robots, sitemap,
OG, JSON-LD, favicon, response shape), GSC totals (28-day window),
CrUX field-data (LCP/INP/CLS where available).

#### `data/checks/<YYYY-MM-DD>.json`

Site-classification snapshot: domain → category mapping
(`live-site` / `forwarder` / `parked` / `archived` / ...). Drives
the `--scope` filter on every fleet command.

#### `data/gsc/<YYYY-MM-DD>.json`

Google Search Console totals + per-domain query/page slices.
Authoritative ranking source where it has data (Google's actual
search corpus).

#### `data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json`

Research-cluster snapshot. Cumulative shape across v8.D (cluster +
gates), v8.I (primary pass), v12.E (audit + reconciliation), v12.F
(costs). All fields are additive — old readers ignore unknown keys,
new readers tolerate missing keys (snapshots pre-dating a phase
don't carry that phase's fields).

```json
{
  "topic":              "<operator-supplied topic>",
  "cluster_queries":    ["..."],
  "per_query_results":  [ /* SerpAPI raw — top-10 organic + features */ ],
  "from_cache":         false,
  "fetched_at":         "2026-05-19T07:02:23+00:00",

  /* v8.D Phase 2 — mechanical gates + verdict */
  "gates": {
    "gate_1_market":  { "status": "PASS" /* ... */ },
    "gate_2_serp":    { /* ... */ },
    "gate_3_moat":    { /* ... */ }
  },
  "operator_fit":             { /* ... */ },
  "verdict":                  "GO",       /* mechanical verdict */
  "suggested_reductions":     [],
  "moat_required":            false,
  "moat_provided":            null,

  /* v8.I — primary interpretive pass (Claude CLI) */
  "primary_verdict": {
    "verdict":               "NICHE-DOWN",
    "confidence":            "MEDIUM",
    "reasoning":             "...",
    "moat_required":         true,
    "moat_prompt":           "...",
    "reductions":            ["..."],
    "operator_fit_warnings": ["..."],
    "blind_spot_self_report":"..."
  },
  "primary_pass_meta": {
    "prompt_version":  "v1",            /* matches niche_evaluation_v1.md */
    "model_id":        "claude-cli",
    "rendered_prompt": "<full text sent>",
    "cost_usd":        0.0423,
    "duration_s":      5.2
  },

  /* v12.E — adversarial audit pass (OpenAI; optional, --verify-gated) */
  "audit": {
    "agreement_level":           "partial",        /* full | partial | disagree */
    "confidence":                "MEDIUM",         /* audit's own confidence */
    "specific_concerns":         ["..."],
    "counter_verdict_token":     "",               /* only on disagree */
    "counter_verdict_reasoning": "",
    "audit_self_check":          "..."
  },
  "audit_pass_meta": {
    "prompt_version":  "v1",            /* matches adversarial_audit_v1.md */
    "model_id":        "gpt-4o",
    "rendered_prompt": "<full text sent>",
    "cost_usd":        0.0120,
    "duration_s":      8.4
  },

  /* v12.D + v12.E — reconciliation (computed; no LLM call) */
  "reconciliation": {
    "final_verdict":    "NICHE-DOWN",   /* GO | NICHE-DOWN | NO-GO | REVIEW_REQUIRED */
    "final_confidence": "LOW",
    "caveats":          ["..."]         /* populated on partial + disagree */
  },

  /* v12.F — rolled-up LLM cost ledger */
  "costs": {
    "primary_usd": 0.0423,
    "audit_usd":   0.0120,
    "total_usd":   0.0543,
    "currency":    "USD"
  }
}
```

**Forward / backward compat.** The schema has no embedded `"schema":
"vN.X"` field; consumers tolerate the additive evolution by checking
`field in payload` before reading. Snapshots from before any phase
shipped simply lack that phase's keys; the renderer skips the
corresponding section.

**Audit-failure semantics.** When `--verify` is set but the audit
pass throws `AuditPassError` (network error / parse failure /
unexpected response shape), the wiring logs a yellow warning and
returns without populating `audit` / `audit_pass_meta` /
`reconciliation`. Primary verdict + `primary_pass_meta` + (partial)
`costs` are still valid signal — the operator gets the primary's
read; only the second opinion is missing.

#### `data/hosting/<YYYY-MM-DD>.json` (v11.A — planned)

```json
{
  "schema": "hosting-v1",
  "fetched_at": "2026-05-15T...",
  "providers_walked": ["vercel", "cloudflare-pages"],
  "scope": "live-site",
  "rows": [
    {
      "domain": "calcengine.site",
      "provider": "vercel",
      "project_slug": "calcengine-site",
      "project_id": "prj_abc123",
      "latest_deploy_status": "READY",
      "latest_deploy_at": "2026-05-15T09:44:00+00:00",
      "last_successful_deploy_at": "2026-05-15T09:44:00+00:00",
      "consecutive_failures": 0,
      "provider_conflict": false,
      "error": null,
      "notes": []
    }
  ]
}
```

Status glyph is **derived at render time**, not stored on disk
(cheaper to update rendering than migrate snapshots). Rules:

| Glyph | Condition |
|---|---|
| `✓` | `latest_deploy_status == "READY"` AND `latest_deploy_at` within `RECENT_DAYS` (30) |
| `⚠` | `latest_deploy_status == "ERROR"` AND `last_successful_deploy_at` non-null AND within 30d |
| `✗` | `latest_deploy_status == "ERROR"` AND no successful deploy in last 30d (or never) |
| `💤` | `latest_deploy_at` older than `STALE_DAYS` (90), regardless of status |
| `—` | `provider is None` |
| `?` | walker `error` populated (token, rate-limit, 5xx) |

`BUILDING` and `CANCELED` render as `⏳` / `⊘` with the deploy
timestamp; skipped from rollup counts.

### Data model

#### `Domain`

Per-row entry in `data/portfolio.json`. Fields: `name`,
`registrar` (godaddy/namecheap/porkbun), `category`,
`expires`, `status`, `value`, plus optional `launched`,
`gsc_property`, `notes`. Cross-source drift detected by `fleet drift`.

#### `CheckResult` (`checks/result.py`)

```python
@dataclass
class CheckResult:
    id: str               # CHECK_NNN
    status: str           # pass | fail | skip
    title: str
    category: str         # scaffold | git | stack | deploy | seo | content
    severity: str         # error | warn | info
    message: str
    details: dict = field(default_factory=dict)
```

#### `LamillToml` (v10.A — `src/portfolio/lamill_toml.py`)

Dataclasses (parser + dataclass shape shipped with v10.A's first
slice; `write()` + `infer_from_existing_configs()` arrive in
subsequent slices):

```python
@dataclass
class DeployBlock:
    platform: str
    account: str | None = None
    production_branch: str = "main"
    auto_deploy: bool | None = None  # None → effective default by platform
    custom_domains: list[str] = field(default_factory=list)

    def effective_auto_deploy(self) -> bool: ...
        # True for cf-pages / vercel / netlify / github-pages;
        # False for the rest. Explicit value in the file wins.

@dataclass
class HostingBlock:
    cpanel_user: str | None = None
    cpanel_url: str | None = None
    ftp_host: str | None = None
    ftp_user: str | None = None
    ftp_port: int | None = None
    public_html_path: str | None = None
    # v11.N — local path inside the project dir to upload from.
    # Default `dist/` matches CF-Pages / Vite convention. Raw-PHP
    # operators set `"."`; serializer omits when default for
    # round-trip determinism.
    deploy_source: str = "dist/"

@dataclass
class BackendBlock:
    db: str = "none"          # postgres | sqlite | duckdb | redis | none
    framework: str = "none"   # go-fiber | fastapi | express |
                              # node-bare | rust-axum | none
    hosting: str = "none"     # fly.io | managed-provider | none

@dataclass
class LamillToml:
    deploy: DeployBlock
    schema: str = "lamill-toml-v1"
    hosting: HostingBlock | None = None
    backend: BackendBlock | None = None
    notes: str | None = None
```

Module API:

```python
class ParseError(Exception): ...

def load(repo_path: Path) -> LamillToml | None: ...
def write(repo_path: Path, payload: LamillToml) -> None: ...
def infer_from_existing_configs(repo_path: Path) -> DeployBlock | None: ...
def detect_platform_signals(repo_path: Path) -> dict[str, bool]: ...
```

`load()` returns `None` if `<repo_path>/lamill.toml` doesn't exist;
raises `ParseError` on TOML syntax errors, missing required fields
(`[deploy]`, `platform`), invalid enum values (`platform` not in
`PLATFORM_VALUES`; backend fields not in their enum tuples), wrong
types (`auto_deploy` non-bool, `custom_domains` non-list, etc.), or
missing `[hosting]` when `platform ∈ {hostgator, custom}`. The
`[operator]` section is silently ignored — owned by
`operator_profile.py`.

`write()` is atomic (tmpfile + `shutil.move`); `production_branch`
is always written, other None/empty fields are omitted; `[hosting]`
/ `[backend]` / `[notes]` blocks only appear when the corresponding
`LamillToml` field is non-None. Round-trip determinism: `write →
load → write` produces byte-identical output.

`infer_from_existing_configs()` returns a `DeployBlock | None` from
filesystem markers. Detection rules:

| Marker | Inferred platform |
|---|---|
| `wrangler.jsonc` or `wrangler.toml` with `pages_build_output_dir` | `cf-pages` |
| `wrangler.jsonc` or `wrangler.toml` without `pages_build_output_dir` | `cf-workers` |
| `vercel.json` present | `vercel` |
| `netlify.toml` present | `netlify` |

Returns `None` when zero markers match OR when multiple platforms
conflict (the drift case — e.g. `wrangler.jsonc + vercel.json`
co-existing). `detect_platform_signals()` returns the underlying
per-platform presence dict so the migration command (later v10.A
slice) can differentiate "no signals" (manual entry required) from
"multiple signals" (manual review required).

Format: TOML via stdlib `tomllib`. Round-trip write via `tomli-w`
(small dep, no transitive deps). **No comment preservation on
round-trip** — accepted; operator edits go through `$EDITOR`, which
doesn't pass through the writer.

#### `HostingRow` (v11.A — `src/portfolio/hosting.py`)

```python
@dataclass
class HostingRow:
    """One domain's deploy state across Vercel + CF Pages + HostGator."""
    domain: str
    provider: str | None              # "vercel" | "cloudflare-pages" | "hostgator" | None
    project_slug: str | None
    project_id: str | None
    latest_deploy_status: str | None  # READY | ERROR | BUILDING | CANCELED | None for HG
    latest_deploy_at: str | None      # ISO 8601 UTC (None for HG — no build pipeline)
    last_successful_deploy_at: str | None
    consecutive_failures: int = 0
    provider_conflict: bool = False
    error: str | None = None
    notes: list[str] = field(default_factory=list)
    # HG-specific optional fields (None for non-HG rows). Typed
    # explicitly rather than nested in an `extra: dict` blob per
    # resolution 11.M — matches every other dataclass in the codebase.
    hg_account_id: str | None = None   # "gator3164" / "gator4216"
    disk_used_mb: int | None = None
    wp_version: str | None = None      # `None` if not a WordPress install
    install_path: str | None = None    # absolute path on cPanel host
```

#### `HgDeployRow` (v11.N — `src/portfolio/hosting.py`)

```python
@dataclass
class HgDeployRow:
    """One row of the `new deploy <hg-domain>` report (single-row
    per invocation — ADR-0011's per-site allowlist)."""
    domain: str
    hg_account_id: str
    public_html_path: str | None = None
    deploy_source: str | None = None
    # Verb describing the deploy's intent / outcome:
    #   would_deploy / deployed     — dry-run vs apply, happy path
    #   skipped_wp                  — wp_version set on snapshot row
    #   skipped_no_source           — sites/<domain>/<deploy_source>/
    #                                 missing or empty
    #   skipped_no_path             — lamill.toml missing
    #                                 [hosting].public_html_path
    #   failed                      — UAPI call failed mid-flight
    action: str = ""
    file_count: int = 0
    total_bytes: int = 0
    error: str | None = None
    notes: str | None = None
```

#### `ParsedVerdict` / `ParsedAudit` / reconciliation result

Defined in `interpretive_pass.py` and `audit_pass.py`. Field shape
mirrors the markdown prompt headers (`verdict`, `confidence`,
`reasoning`, `moat_required`, `moat_prompt`, `reductions`,
`operator_fit_warnings`, `blind_spot_self_report` on the primary;
`agreement_level`, `confidence`, `specific_concerns`,
`counter_verdict`, `audit_self_check` on the audit). Parser splits
on `### <header>` boundaries; required sections raise on missing,
optional sections default empty.

## 5. CLI / UX design

### Scope-first verb model (post-v7.A)

Four top-level namespaces:

```
lamill
├── project    # ops on one project
├── fleet      # cross-portfolio ops
├── new        # create work (suggest / bootstrap / deploy / research)
└── settings   # config + debug (catalog / gsc / apikeys)
```

Daily-ops users see the first three. "Everything else" lives under
`settings`. See `docs/CLAUDE.md § v7.A` for the full rename map and
phased rollout — three slices under `v7.A`: additive paths, then
deprecation aliases, then cleanup.

### Standard flags

| Flag | Semantics |
|---|---|
| `--json` | Emit machine-readable JSON instead of the rich table |
| `--refresh` | Force re-fetch / re-walk, overwrite snapshot |
| `--only <X>` | Single-domain probe (bypasses snapshot) |
| `--scope wip\|all\|live-site\|forwarder` | Scope filter on fleet commands |
| `--apply` | Required for write surfaces — default is dry-run |
| `--yes` | Skip interactive confirmations |
| `--non-interactive` | Refuse prompts; fail if a required field is missing |

### Output conventions

- Rich tables with emoji status (✓ / ⚠ / ✗ / 💤 / — / ⏳ / ⊘ / ?).
- Color via `rich` (`[green]ok[/]`, `[yellow]warn[/]`, `[red]fail[/]`).
- Footer rollup counts after every fleet table.
- Snapshot path printed: `Snapshot: data/<layer>/<YYYY-MM-DD>.json`.
- Cache-age note when reading from cache:
  `Reading data/<layer>/<date>.json (Xh old · use --refresh to re-fetch)`.

### Write-surface confirmation gates

Both write surfaces follow the same pattern:

1. Run a dry-run pass that prints a summary of every planned write.
2. Wait for explicit confirmation (`--yes` to skip).
3. Execute writes atomically (per-file tmpfile + rename).

`new deploy` follows a similar pattern for GitHub repo + CF Pages
project creation (not a project-dir write, but irreversible).

### Projected CLI surface (current + planned)

Full command tree at the end of v14, with shipped nodes marked ✅
and planned nodes labeled with the phase that introduces them.
**v14.B (2026-05-20) was the most recent CLI restructure** — renamed
several verbs and deleted the `fleet info` subgroup; supersedes the
v7.A locked target shape in `docs/CLAUDE.md`.

```
lamill
├── project                                          # ops on one project
│   ├── check <name>                                 ✅ v7.A
│   ├── fix <name>                                   ✅ v6.D
│   ├── seo <name>                                   ✅ v7.A (+ v13.B GSC diagnostics)
│   ├── diagnose <name>                              ✅ v7.F
│   ├── version <name>                               ⏳ v15.B — read local
│   │                                                          version.json
│   └── deploy-status <name>                         ⏳ v15.C — HEAD vs deployed
│                                                              SHA (or fold into
│                                                              `diagnose`?)
│
├── fleet                                            # cross-portfolio ops
│   ├── focus                                        ✅ v7.D
│   ├── domains [--summary [--verbose]]              ✅ v5.G; flag-overload v14.B
│   │           [--expiring N]                                 (was `fleet info
│   │                                                          summary/expiring`)
│   ├── seo                                          ✅ v5.D
│   ├── hosting [--refresh] [--only DOMAIN]          ✅ v11.A — unified 4-provider
│   │           [--provider {vercel|cf-pages|                  walker (Vercel + CF
│   │                       cf-workers|hostgator}]             Pages + Workers + HG)
│   │           [--apply-declarations [--dry-run]]
│   ├── check                                        ✅ v5.B
│   ├── fix                                          ✅ v6.G
│   ├── drift                                        ✅ v6.A
│   ├── repos [--add-deploy-declarations]            ✅ v7.E (flag in v10.C)
│   ├── dashboard                                    ✅ v7.B
│   └── sync [--refresh-rdap]                        ✅ v7.A; renamed v14.B
│                                                                (was `fleet info
│                                                                cleanup`)
│
├── new                                              # create work
│   ├── validate <topic> [--verify] [...]            ✅ v8.D; renamed v14.B
│   │                                                              (was `new research`)
│   ├── domain <topic>                               ✅ v2.A; renamed v14.B
│   │                                                              (was `new suggest`)
│   ├── trends <topic>                               ✅ v19.B
│   │           [-t {7d|30d|90d|12m|5y|all}]                    (Google Trends via
│   │           [-r REGION] [--json] [--refresh]                 pytrends; 24h cache)
│   ├── bootstrap                                    ✅ v3.A
│   │                                                              (writes lamill.toml
│   │                                                              in v10.C)
│   └── deploy <name>                                ✅ v3.C → v11.M polymorphic
│                                                              (reads lamill.toml,
│                                                              dispatches CF Pages /
│                                                              Workers / Vercel /
│                                                              HostGator)
│
└── settings                                         # setup / debug
    ├── catalog {list, describe, run}                ✅ v7.A
    ├── gsc {auth, recrawl, status}                  ✅ v7.A (+ recrawl post-v7.A)
    ├── ga4 {auth}                                   ✅ v18.C
    ├── apikeys {list, set, delete}                  ✅ v7.A
    ├── operator {show}                              ✅ v8.D
    ├── cloudflare {token, status}                   ✅ v7.H
    ├── serpapi-quota {show, sync}                   ✅ v8.D
    └── deploy                                       ✅ v10.B; renamed v14.B
        ├── set <name> <platform>                                  (was `settings
        ├── show <name>                                            project set-deploy
        └── set-launched <name> <date>                             / show-deploy /
                                                                   set-launched`)
```

#### Net additions by phase (recent + planned)

| Phase | New CLI surface |
|---|---|
| v10.B | Original `settings project {set-deploy, show-deploy, set-launched}` — all renamed in v14.B (see above). |
| v10.C | `fleet repos --add-deploy-declarations` flag · `new bootstrap` writes `lamill.toml` (no surface change) |
| v10.D-E | None (validation + drift detection — uses existing CLIs) |
| v11.A | `fleet hosting` — unified Vercel + CF Pages + Workers + HostGator walker (absorbed v10.F + v10.G). |
| v11.M | `new deploy <domain>` becomes polymorphic — reads `lamill.toml [deploy].platform`, dispatches CF Pages (v3.C) / CF Workers / Vercel / HostGator. |
| v12.B-G | `new validate --verify` / `--no-verify` / `--audit-model <id>` / `--invalidate {none, interpretive, audit, all}` flags (no new node) |
| v13.B | `project seo <domain>` gains the GSC-diagnostics default block (sitemaps + coverage + hints). |
| **v14.B** | **Hard-cutover CLI rename — see tree above. No new functionality; reshape only.** |
| v15.B | `project hosting <domain>` (new verb) + drop `fleet hosting --only` flag (hard cutover, matches v14.B precedent). Restores `project X ↔ fleet X` symmetry. |
| v15.C | `has-version-stamp` conformance check (no new verb; build artifact convention). |
| v15.D | `deploy-fresh` conformance check + 📋 Freshness section in `project hosting <domain>`. |
| v15.E | `Last build` column on `fleet hosting` + 🔧 Build section on `project hosting <domain>` (folds into existing `_fleet_hosting_impl` walker — no new platform-API infra). |
| v15.F | `fleet sync --refresh` (live Porkbun pull) + `--watch` (filesystem watcher) flags (no new node). |
| v15.G | Kickoff doc-only (extends v15 tier with G-J; locks decisions captured in ADR-0012 + ADR-0013). |
| v15.H | Bootstrap stack normalization (no new CLI verb — internal `bootstrap.py` translation hook on `--git-url` path; ADR-0013). |
| v15.I | **`new deploy <domain>` end-to-end automation (no `wrangler deploy`; git-integrated CF Pages-API; ADR-0012).** Unified `_deploy_cf_unified()` orchestrator replaces `_deploy_cf_pages_v3c` + `_deploy_cf_workers`. New `--yes` flag on `new deploy` for auto-confirming NS updates. Bootstrap default platform flips `cf-pages` → `cf-workers`. |
| v15.J | Docs-sync wrap (no CLI surface change). |
| v16.C | URL Inspection API wrapper + binary check_NNN (`project check` fails when URL not indexed). |
| v16.D | Fleet-level GSC rollup — new `fleet dashboard` columns (Coverage % / Crawl errors / W/w imp Δ / Page-2 opp count) + `fleet seo --detail` mode for fleet-aggregated top queries / top pages. |
| v18.B | `new bootstrap --ga4 G-XXXXXX` flag · `project fix` gains `inject-ga4` remediation. |
| v19.B | `lamill trends <topic>` (standalone test invocation; later composes into `new validate`). |
| v21.B | `new deploy --reindex [<url>...]` flag (Google Indexing API). |
| v23.B-C | `project seo --sitemaps` section flag · `fleet dashboard` indexed/submitted column augmentation. |

#### Open CLI design questions

Resolve before the relevant phase ships.

1. **v15.C deploy-status placement.** Standalone `project
   deploy-status <name>` vs fold the HEAD-vs-deployed check into
   the existing `project diagnose <name>` 5-layer probe. The
   diagnose path is closer to the existing UX shape; standalone
   adds a discoverable verb. Defer until v15.C starts.

### `--verify` semantics (v12)

`lamill new validate <topic>`:
- Default → primary only (Phase 4a). Cost ~$0.01-0.02/run.
- `--verify` → primary + audit + reconciliation (Phases 4a-c). Cost ~$0.05-0.10/run.
- `--no-verify` → primary only, even if `verify_by_default=true`.
- `--model <id>` → override primary; default `claude-sonnet-4-7`.
- `--audit-model <id>` → override audit; default `gpt-4o`.
  Same-model rejected with the correlated-blind-spot rationale.
- `--no-cache=interpretive` → re-run Phase 4a on cached SERP data.
- `--no-cache=audit` → re-run Phase 4b only.

## 6. External integrations

| Provider | Used for | Auth | Quirks |
|---|---|---|---|
| **OpenAI** | `new domain` brainstorm; `audit_pass` (v12) | `OPENAI_API_KEY` (Bearer) | 429 with `Retry-After` |
| **Anthropic (Claude CLI subprocess)** | `interpretive_pass` primary (v8); Tier 2 fixers (v6.E) | Operator's existing Claude subscription via local CLI | Different I/O shape from direct API; cost model per local subscription, not per-token |
| **Anthropic API** | Reserved — direct-API switch path for primary pass | `ANTHROPIC_API_KEY` (header `x-api-key` + `anthropic-version`) | Per-provider rate-limit dialect; not currently exercised |
| **Cloudflare — fleet walker** | v11.A `fleet hosting` walker — `/accounts/{id}/pages/projects`, `/workers/scripts`, `/workers/domains` | `CF_API_TOKEN` + `CF_ACCOUNT_ID` | Pagination on Pages projects list |
| **Cloudflare — zones** | v11/v15.I — `resolve_zone_id` (existing) · `ensure_zone` (v15.I; `POST /zones` for create) | `CF_API_TOKEN` + `CF_ACCOUNT_ID` | Zone create returns `name_servers` array for operator to set at registrar |
| **Cloudflare — Pages-API (v15.I unified deploy)** | `new deploy` for `platform ∈ {cf-pages, cf-workers}` per ADR-0012 — `POST /accounts/{id}/pages/projects` with `source.type=github` for git-integrated create · `GET /accounts/{id}/pages/projects/{name}` idempotency probe · `POST /accounts/{id}/pages/projects/{name}/domains` custom-domain attach (GET-then-POST, no documented idempotency) · `GET /accounts/{id}/pages/projects/{name}/deployments?per_page=1` for build poll (`latest_stage.status` ∈ {success, idle, active, failure, canceled}) | `CF_API_TOKEN` + `CF_ACCOUNT_ID` | **CF GitHub App** must be installed once per CF account at `https://dash.cloudflare.com/?to=/:account/workers-and-pages/create/connect-to-git` (one-time dashboard step; not API-automatable). Pipeline detects + surfaces clear error when missing. |
| **Vercel** | v11.A `fleet hosting` walker | `VERCEL_TOKEN` (Bearer) | Personal token sees only personal account; multi-team out of scope (`prd.md` v11 Design notes — 11.A) |
| **CrUX (Chrome UX Report)** | `seo_runtime` field data | `CRUX_API_KEY` | `no-data` for personal-portfolio-scale origins (expected; not a bug) |
| **SerpAPI** | `new validate` real SERP fetch | `SERPAPI_KEY` | Monthly quota tracked in `data/serp/_quota.json` |
| **Google Search Console** | `gsc.py` ranking + impressions; URL Inspection (v16.C) | OAuth (`GOOGLE_OAUTH_*`) | 28-day rolling window; URL Inspection 2000/day quota |
| **GitHub REST API** | v15.I — `POST /user/repos` repo create (primary path; Bearer auth via `GITHUB_TOKEN`); `GET /repos/{owner}/{repo}` idempotency probe; `gh` CLI fallback when `GITHUB_TOKEN` missing | `GITHUB_TOKEN` (Bearer; `Accept: application/vnd.github+json` + `X-GitHub-Api-Version`) | Personal-account repos via `/user/repos`; org repos via `/orgs/{org}/repos` (not currently exercised) |
| **Porkbun — availability** | `new domain` brainstorm — domain check + price | `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` | `/domain/checkAvailability` returns 404 — uses `/pricing/get` + RDAP fallback instead |
| **Porkbun — registrar inventory** | v15.F — `fleet sync --refresh` — `POST /domain/listAll` | Same | Returns up to 1000 domains per page; pagination via `start` |
| **Porkbun — DNS (v15.I)** | `new deploy` — `POST /domain/getNs/{domain}` + `POST /domain/updateNs/{domain}` for NS read + push per ADR-0012's registrar-NS-automation step | Same | Idempotency NOT documented for `updateNs`; pipeline does GET-then-update-if-mismatch |
| **RDAP** | Availability fallback | Anonymous | Authoritative WHOIS replacement |

### Rate-limit handling

Each provider has its own dialect. Pattern (per the v12 audit-pass
design — rate-limit risk; see §10 below):

- **OpenAI**: `429` with `Retry-After` header → exponential backoff to a cap.
- **Anthropic API**: `429` with lowercase `retry-after` + their own
  rate-limit-tokens header → same pattern, different header names.
- **Cloudflare / Vercel**: 5xx + retry-after; sliding-window quotas.

The HTTP wrappers ride `httpx`. No central rate-limit abstraction yet
— each module handles its own. Per the v12 audit-pass design (§10
below — Research module risks), an `LLMClient` protocol is a
candidate refactor if a third LLM provider lands.

## 7. Stack baselines

### Portfolio itself

- **Python ≥3.11**, managed by [`uv`](https://docs.astral.sh/uv/).
- **typer** (CLI), **rich** (tables/output), **httpx** (HTTP),
  **tldextract** (domain parsing), **google-api-python-client** (GSC),
  **tomli-w** (planned, v10.A — for `lamill.toml` writer).
- Source layout: `src/portfolio/` (hatchling-packaged). Entry point:
  `portfolio.cli:app`.
- **Self-contained build** — does **NOT** use the central builder at
  `~/work/projects/builder/`. The central builder is geared toward
  web app stacks (React / Tauri / Expo); portfolio is a Python CLI
  with its own `Makefile` using `uv` directly.
- `portfolio` is excluded from `fleet check` by default
  (`[git] ignore_repos = ["portfolio"]`) — SEO/stack checks would all
  skip anyway and create noise.

### Sibling `sites/*` projects (per ADR-0008)

- **pnpm-only**. `package-lock.json` / `bun.lockb` / `yarn.lock` are
  conformance failures (CF Pages bun-detection trap was hit on
  Vite 5).
- **Vite ≥6**, **Astro ≥5** for web stacks.
- **Makefile forwards to parent** — every `sites/*` Makefile
  delegates to `~/work/projects/builder/`'s `Makefile` via
  `$(MAKE) -C ..` (CHECK_012). Build logic is centralized.
- Standard scaffolding required: `AI_AGENTS.md` (10 canonical
  sections per v9.A/v9.E), `README.md`, `.gitignore`, `docs/prd.md`,
  `docs/Prompts.md` (dated H2 entries), `Makefile` with `run`+`build`
  targets, `lamill.toml` declaring deploy target (v10.A).

## 8. Module index

| Module | Purpose | Notable public API |
|---|---|---|
| `cli.py` | `typer` app — top-level commands + namespace wiring | `app` (entry point) |
| `project.py` | `project check` / `project fix` runner | `run_checks`, `apply_fixes` |
| `check.py` | Site classification (live-site / forwarder / parked / archived) | `classify_domain` |
| `data.py` | Multi-registrar CSV adapters + `portfolio.json` IO | `load_inventory`, `rebuild_portfolio_json` |
| `bootstrap.py` | `new bootstrap <domain>` write surface | `bootstrap_domain` |
| `deploy.py` | `new deploy` (GitHub repo + CF Pages project) | `deploy_domain` |
| `suggest.py` | `new domain <topic>` Power 1 brainstorm | `suggest_domains` |
| `decide.py` | Validation-mode shortlist + decide | `mark_shortlist`, `decide_from_shortlist` |
| `availability.py` | RDAP + Porkbun availability + pricing | `check_availability` |
| `cloudflare.py` | CF API client (Pages, Workers, DNS) | `walk_pages_projects`, `dns_lookup` |
| `gsc.py` | GSC OAuth + queries + sync | `gsc_auth`, `gsc_status` |
| `gsc_recrawl.py` | Sitemap resubmit flow | `recrawl_property` |
| `ga4_admin.py` (v18.C) | GA4 Admin API client + OAuth (`analytics.edit` scope). httpx-direct (no `googleapiclient.discovery.build`). Used by `new bootstrap` to auto-create per-site GA4 properties + web data streams; measurement ID lands in `lamill.toml [analytics] ga4_id`. Credentials at `~/lamill/ga4/{credentials.json,token.json}` (chmod 600). | `create_property`, `create_web_stream`, `authenticate`, `has_token` |
| `gtrends.py` (v19.B) | Google Trends via `pytrends`. Standalone `lamill new trends <topic>` data fetcher; no cluster integration. Per-topic cache at `data/gtrends/<topic-hash>.json` keyed by (topic, timeframe, region); 24h TTL. pytrends boundary inside `_fetch_from_pytrends` for test isolation. `TIMEFRAME_MAP` translates CLI flags (`7d`/`30d`/`90d`/`12m`/`5y`/`all`) to pytrends strings. | `fetch_trends`, `load_cached`, `save_cached`, `is_stale`, `TrendsPayload` |
| `seo_runtime.py` | Live HTTP SEO probe orchestrator | `run_seo(domains)` |
| `seo_cache.py` | Snapshot save/load for `data/seo/` | `save_snapshot`, `latest_snapshot`, `is_stale` |
| `serp.py` | Cluster builder for `new validate` | `build_cluster` |
| `serp_fetch.py` | SerpAPI client | `fetch_serp_for_query` |
| `serp_query_cache.py` | Per-query snapshot cache under `data/serp/` | `save_query_snapshot`, `load_query_snapshot` |
| `serpapi_quota.py` | SerpAPI monthly-quota counter | `bump_quota`, `quota_remaining` |
| `research_v2.py` | `new validate` orchestrator (Phases 1-3) | `run_research(topic, *, verify)` |
| `research_gates.py` | Gate 1/2/3 mechanical classification | `run_gates(cluster)` |
| `interpretive_pass.py` | Phase 4a — primary verdict | `build_payload`, `parse_verdict`, `run_primary_pass` |
| `audit_pass.py` | Phase 4b — adversarial audit | `build_audit_payload`, `parse_audit`, `run_audit_pass` |
| `operator_profile.py` | `[operator]` block reader (lamill.toml) | `load_operator_profile` |
| `prompt_loader.py` | Load + `{{var}}` render of `prompts/*.md` | `load_prompt`, `render_prompt` |
| `canonical_sections.py` | v9.A/v9.E canonical-section schema (JSON-driven) | `load_canonical_sections`, `enforce_sections` |
| `templates.py` | Bootstrap template source + section emitters | `bootstrap_template`, `<doc>_section_<key>()` factories |
| `fleet_repos.py` | `fleet repos` audit + naming consistency | `audit_repos` |
| `dashboard.py` | `fleet dashboard` unified view | `render_dashboard` |
| `focus.py` | `fleet focus` priority ranker | `compute_focus` |
| `drift.py` | `fleet drift` cross-source comparator | `compute_drift` |
| `diagnose.py` | `project diagnose <domain>` 5-layer auto-investigate | `diagnose_domain` |
| `menu.py` | Interactive launcher | `launch_menu` |
| `apikeys.py` | `settings apikeys` + provider probes | `KNOWN_KEYS`, `_probe_<provider>` |
| `fix_helpers.py` | Tier 1 factories + `run_claude_text()` Claude CLI subprocess | `run_claude_text`, `make_file_fixer`, `make_section_injector` |
| `fix_registry.py` | Fixer discovery + tier dispatch | `discover_fixers`, `apply_fixer` |
| `checks/registry.py` | Auto-discovery of `check_*.py` modules | `iter_checks`, `run_check` |
| `checks/result.py` | `CheckResult` dataclass | `CheckResult` |
| `checks/config.py` | Per-check metadata helpers | `check_metadata` |

**Planned modules (unshipped phases):**

| Module | Phase | Purpose |
|---|---|---|
| `lamill_toml.py` | v10.A | `LamillToml` dataclasses + `load`/`write`/`infer_from_existing_configs` |
| `hosting.py` | v11.A | `HostingRow` + `walk_vercel`/`walk_cf_pages`/`run_hosting` orchestrator |
| `hosting_cache.py` | v11.A | Snapshot save/load mirroring `seo_cache.py` |
| `reconciliation.py` | v12.E (or co-located in `research_v2.py`) | Phase 4c pure-logic reconciliation |

## 9. Active implementation plans

Commit-by-commit plans for unshipped phases. Each plan moves to
`docs/shipping-history.md` when its phase ships. Plans here are the
HOW companion to `prd.md`'s `### vN #### Design notes` (the WHY).

### v10.A — `lamill.toml` foundation ✅ (shipped 2026-05-18)

Three commits delivered the library half — schema, parser, atomic
writer, inference. Tests at `tests/test_lamill_toml.py` (70 tests).
Module API documented in §4 Schemas → `LamillToml` above.

- `4395e1d` schema + parser; `BackendBlock` + dataclasses + `load()`
- `c9d543b` atomic `write()` + round-trip determinism
- `be10787` `infer_from_existing_configs()` + `detect_platform_signals()`

When the full v10 tier wraps (after v10.G ships), the tier's
Design notes block in `prd.md` moves to `docs/shipping-history.md`
and these slices land there as per-phase entries. Per-phase notes
stay inline above for now — v10.F and v10.G are still planned, so
the tier-level design context remains load-bearing in `prd.md`.

### v10.B — operator CLI surfaces ✅ (shipped 2026-05-18)

Two slices delivered the CLI half of `lamill.toml`:

- *`settings deploy set <name> <platform>`* — interactive
  by default; hostgator/custom walks cpanel + FTP breadcrumbs.
  `--non-interactive` + flags (`--account`/`--branch`/
  `--auto-deploy`/`--no-auto-deploy`/`--domain` repeatable/
  `--cpanel-user`/.../`--public-html-path`) for scripted use. Writes
  via `lamill_toml.write()` (atomic). 17 tests at
  `tests/test_settings_project_set_deploy.py`.
- *`settings deploy show <name>`* — rich-table renderer +
  `--json` (uses `lamill_toml.to_dict()`). Shows "no deploy
  declaration" hint + `set-deploy` invocation when no
  `lamill.toml` exists. Long notes truncated. 12 tests at
  `tests/test_settings_project_show_deploy.py`.

Also moved `set-launched` (originally shipped v7.C as `project
set-launched`) into the same `settings project` namespace for
consistency. Per-project metadata stays together under settings;
the `project` namespace is reserved for project-code ops
(`check`/`fix`/`seo`/`diagnose`).

Full design notes stay in `prd.md § 6 → v10 → Design notes` until
the full v10 tier wraps (post-v10.G) and the whole tier moves to
`shipping-history.md`.

### v10.C — auto-write integration ✅ (shipped 2026-05-18)

Two slices delivered the auto-write half of `lamill.toml`:

- *`new bootstrap` writes `lamill.toml`* (commit `fd725ff`).
  After common files + CF safety fixes, bootstrap writes
  `lamill.toml` if not already present. Platform priority:
  explicit `--platform <X>` flag → `infer_from_existing_configs()`
  on what's in the dir (CF safety fixes have just written
  `wrangler.jsonc` so template-path bootstrap detects `cf-pages`
  on its own) → `cf-pages` default. `--platform hostgator|custom`
  rejects at bootstrap with a pointer to `settings project
  set-deploy` — bootstrap doesn't prompt for the `[hosting]`
  fields those platforms require. `custom_domains` set to
  `[<domain>]`. Bootstrap doesn't clobber a pre-existing
  `lamill.toml` (matters for `--from-genai` if the Lovable export
  brought one along). Detection updated to recognize modern CF
  Pages config (`assets` block) alongside legacy
  `pages_build_output_dir`.
- *`fleet repos --add-deploy-declarations`* (migration-sweep
  commit). Walks every `sites/<dir>/` (reusing
  `fleet_repos.list_site_dirs`), calls
  `detect_platform_signals()` per repo, classifies as:
  `already_declared` (lamill.toml exists), `archived`
  (TOMBSTONE.md or portfolio.json category in archived set),
  `unambiguous` (single signal — writes), `ambiguous`
  (multiple signals — refused unless `--include-ambiguous`),
  `manual` (no signals — operator follows up via `settings
  project set-deploy`). `--dry-run` is the default; `--apply`
  commits writes. `--include-ambiguous` picks via priority
  `vercel > cf-pages > cf-workers > netlify` and embeds a
  `[notes].text` warning in the generated file so the operator
  sees the conflict on next inspection. Implementation in
  `project_deploy.py:migrate_deploy_declarations()` returning a
  list of `MigrationRow` structs; renderer
  `render_migration_summary()` groups output by classification
  with footer counts.

v10.D ran this against the actual fleet on 2026-05-18 — 22 of 23
sites carry a `lamill.toml`; v10.E checks (above) now read those
declarations. Design notes stay in `prd.md` until the full v10
tier wraps (post-v10.G) and migrates to `shipping-history.md`.

### v10.D — validation phase ✅ (shipped 2026-05-18)

Real-fleet rollout. Operator-driven, not code-heavy:

- Ran `lamill fleet repos --add-deploy-declarations --dry-run`
  against the actual fleet; reviewed plan; resolved edge cases
  via `lamill settings deploy set` interactively.
- 22 of 23 fleet sites now carry a `lamill.toml`. 17 of 22
  committed in own-git-repos; 5 NO_GIT sites have the file in
  working tree pending v6.F (own-git-repo guided migration).
- See `docs/shipping-history.md § v10.D` for the per-bucket
  breakdown.

### v10.E — drift detection + `lamill.toml` conformance ✅ (shipped 2026-05-18)

Three deploy-category checks closed the v10.A-E loop:

- *`CHECK_058 has-lamill-toml`* (severity: error). Fails when
  `<repo>/lamill.toml` is missing. Skip on archived / tombstoned.
  The 5 NO_GIT sibling repos baseline-fail this until v6.F runs —
  known and accepted (see `docs/shipping-history.md § v10.D`).
- *`CHECK_059 lamill-toml-valid`* (severity: error). Round-trips
  the file through `lamill_toml.load()`; surfaces TOML syntax
  errors, missing `[deploy]`, unknown enum values, missing
  `[hosting]` when platform requires it. Warn-skip when file
  missing (CHECK_058 owns presence).
- *`CHECK_143 deploy-drift`* (severity: warn). Compares declared
  platform against best-effort classification of the latest
  `data/checks/<date>.json` row. Classification heuristic:
  WordPress generator-meta / `<title>WordPress*` /
  `/wp-(includes|content|admin)/` URL paths → `hostgator`;
  provider-suffix hostnames in `final_url` or `redirect_chain`
  (`*.vercel.app` → `vercel`, `*.pages.dev` → `cf-pages`,
  `*.netlify.app` → `netlify`, `*.workers.dev` → `cf-workers`).
  Honest about uncertainty — `warn`s when no strong signal,
  only `fail`s when declared ≠ classified-actual. Canonical
  drift case `iotnews.today` (declared=vercel, classified=
  hostgator via WP installer title) → fail. Site fingerprint
  pattern catches the WP `<title>WordPress &rsaquo; Error</title>`
  the install-incomplete server returns before any generator
  meta is emitted.

26 new tests (3 + 7 + 16). Suite at 1827 passed / 1 skipped.

The classifier is inlined in `check_143_deploy_drift.py` rather
than extracted — single call site, no current need for reuse.
If v11.A's hosting walker needs a similar cross-check, extract
then.

### v11.A — `fleet hosting` — unified 3-provider walker

~16-22h, ~14 commits. Mirrors `fleet seo` shape: read-only, cached,
refreshable, emoji table. Each commit subject is
`portfolio: v11.A — <slice>`. Scope expanded 2026-05-18 to absorb
v10.F (HG cPanel integration); HG walker is the net-new chunk
relative to the original 2-provider design.

Sequential slices, in commit order:

- *API-keys plumbing — Vercel + HG tokens.* Add `VERCEL_TOKEN`,
  `HOSTGATOR_TOKEN_GATOR3164`, `HOSTGATOR_TOKEN_GATOR4216` to
  `apikeys.KNOWN_KEYS`. `_probe_vercel()` (`GET /v2/user`, 5s
  timeout); `_probe_hostgator(token, account_id)` (cPanel UAPI
  `/execute/Variables/get_user_information`, 8s timeout — cPanel
  is slower than CF/Vercel). cPanel host auto-derived from
  account_id (per `prd.md` v11 — resolution 11.L). 3 new tests.
- *Dataclass + constants.* New `src/portfolio/hosting.py` with
  `HostingRow` dataclass (typed optional fields including
  `disk_used_mb`, `wp_version`, `install_path` per resolution
  11.M); constants `RECENT_DAYS=30`, `STALE_DAYS=90`,
  `MAX_DEPLOY_LOOKBACK=10`.
- *Vercel walker.* `walk_vercel()` — paginated projects list +
  per-project deployments. Mocked unit tests.
- *Cloudflare Pages walker.* `walk_cf_pages()` — same shape against
  the CF API.
- *HostGator walker.* `walk_hostgator(account_id)` — cPanel UAPI:
  `DomainInfo/list_domains` for addon-domain enumeration,
  `Quota/get_quota_info` for disk usage, `WordPressManager/
  list_installations` (or scan `~/public_html/*/wp-includes/`
  via UAPI `Fileman/list_files` fallback) for WP version + path.
  Two account walks (gator3164, gator4216) per fleet refresh.
- *Orchestrator + match logic.* `run_hosting()` joining all three
  walker outputs + domain-match (bare-host normalize per 11.E) +
  provider-conflict detection (two rows in snapshot per 11.F).
- *Snapshot cache.* `hosting_cache.py` mirroring `seo_cache.py`.
- *CLI shell + cache-eligibility.* `fleet hosting` Typer command +
  cache-eligibility logic + `--refresh` / `--only DOMAIN` /
  `--provider {vercel|cf-pages|hostgator}` / `--json` flags.
- *Table renderer.* `_render_hosting_table()` + status-emoji helper.
  Columns: Domain · Provider · Status · Last Success · Failures ·
  HG-extra (compact `[disk · WP]` for HG rows). Footer with rollup
  counts.
- *Walker error surfaces.* Token-missing surface + per-row 5xx /
  rate-limit rendering per resolution 11.H. HG-specific: account-
  scoped 401 skips that account but leaves the other walker
  results visible.
- *`--apply-declarations` writer.* For HG sites that have a local
  `sites/<domain>/` directory but no committed `lamill.toml`,
  write the file using v10.A's `lamill_toml.write()` —
  `platform=hostgator`, `[hosting]` filled from the walker's
  cPanel-account context. Dry-run by default per the v10.C
  migration-sweep convention. Scoped to "missing only" per
  resolution 11.N — no drift remediation.
- *Dashboard join.* `dashboard.py`: new `Hosting` column joining
  the latest `data/hosting/` snapshot.
- *Diagnose integration.* `diagnose.py`: optional "Hosting:"
  section when a hosting snapshot covers the diagnosed domain.
- *Docs update.* `docs/CLAUDE.md`, `AI_AGENTS.md`,
  `docs/Prompts.md`, prd v11.A row → ✅, v11 Design notes →
  `shipping-history.md`.

**Test strategy** (resolution 11.J): all real API calls mocked at
the `httpx`/`requests` layer (same pattern as
`tests/test_gsc_recrawl.py`). No CI calls to real Vercel /
Cloudflare / cPanel UAPI.

### v11.B — `new deploy` polymorphic dispatch + SFTP push (planned)

~14-20h. Adds the active-deploy half of v11 — `lamill new deploy
<domain>` reads `lamill.toml` and dispatches by `[deploy].platform`:

- `cf-pages` → existing v3.C `CloudflarePagesDeploy` impl.
- `vercel` → existing-equivalent (verify what was shipped in v3.C
  vs only CF; backfill if Vercel deploy verb is stub-only).
- `hostgator` / `custom` → NEW SFTP push flow.
- `none` → reject with a `lamill settings deploy set` hint.

The SFTP path is a third write surface (the first being `new
bootstrap` for fresh project dirs per ADR-0001 / ADR-0003, the
second being `project fix` for in-place remediation). ADR-0009
needed before code lands — either reverse ADR-0003's "two write
surfaces only" with the new SFTP-to-remote-host argument, or
argue external-host writes are categorically distinct from local-FS
writes.

**Design open** — gating questions in `prd.md § 6 → v11 → Open
questions (v11.B)`: verb-split shape (one polymorphic verb vs
split init/push), what gets pushed (`dist/` parity vs source vs
operator-configured), auth surface (SSH key vs cPanel password vs
UAPI file-upload), WordPress in/out, atomicity / staging strategy.

### v12.B onward — Adversarial audit response parser → docs

v12.A (audit prompt rendering) shipped 2026-05-17. The remaining
v12.B-G wedges:

- **v12.B — adversarial audit response parser** (~2-3h). Same parser
  shape as Phase 4a's `parse_verdict`: split on `### <header>`
  boundaries, strict on `agreement_level` / `confidence` /
  `specific_concerns`, permissive on `counter_verdict` /
  `audit_self_check`. Parser must be permissive about format
  variation across model styles: accept `### foo`, `**foo:**`,
  `# foo`, `## foo` as section headers; strip leading preamble.
- **v12.C — OpenAI audit-pass runner** (~3-4h). Calls the existing
  OpenAI client. Same-model rejection (`--model X --audit-model X`
  errors early with the correlated-blind-spot rationale).
- **v12.D — `--verify` flag + output rendering** (~2-3h). Three
  reconciliation branches (agree / partial / disagree) each get
  their own rendering path. REVIEW_REQUIRED is the high-signal path.
- **v12.E — Reconciliation logic** (~2-3h). Pure-logic per §3
  Mechanisms. Unit tests per branch.
- **v12.F — Polish: cost-estimate fields + `verify_by_default` +
  granular cache** (~3-4h). `--no-cache=interpretive` and
  `--no-cache=audit` for re-running individual passes on cached
  SERP data.
- **v12.G — Docs** (~1h). `docs/CLAUDE.md`, `AI_AGENTS.md`,
  `docs/Prompts.md`, prd v12 rows → ✅; "when to use --verify"
  guidance added to `lamill new validate --help`.

Total v12.B-G: ~13-18h.

## 10. Implementation risks

Technical risks surfaced during phase design. Each moves to
`shipping-history.md` when its phase ships.

### Research module (v8.E + v12)

**Cross-provider API setup.** Codebase was OpenAI-only pre-v8.E. The
primary-pass decision uses the Claude CLI subprocess (not the
Anthropic API), which sidesteps a second API-key surface but limits
to the operator's local Claude subscription. The `ANTHROPIC_API_KEY`
slot in `apikeys.KNOWN_KEYS` is reserved for the eventual direct-API
mode if local-subprocess constraints surface.

**Rate-limit handling differs by provider.** OpenAI uses 429 +
`Retry-After`; Anthropic uses 429 + lowercase `retry-after` + a
tokens-remaining header. Each module currently handles its own
dialect; an `LLMClient` protocol is a candidate refactor if a third
LLM provider lands.

**Cost surprise.** `--verify` is **not sticky** — every invocation
specifies it explicitly. The output banner with `--verify` says
"verify mode (Sonnet + GPT-4o, ~$0.05/run)" so cost is visible per
call. A cost ledger (v12.F polish — `estimated_cost_usd` per pass)
unblocks a future `lamill settings cost report` aggregation without
re-fetching.

**Response parsing across model styles.** Different model families
have different markdown habits — Claude consistent, GPT-4o sometimes
uses `**header:**` or wraps in fences, Gemini even less predictable.
Parser is permissive about format variation (accepts `### foo`,
`**foo:**`, `# foo`, `## foo`). Test fixtures must include real-world
malformed responses captured during dev.

**Audit failure modes.** API down, unparseable response, or
content-filter refusal — all fall back to primary-only with a
clearly-surfaced caveat. Snapshot records
`audit_pass.ran=true, audit_pass.error="..."` and
`reconciliation.ran=false`. Don't waste the primary's verdict on a
transient audit issue.

**Markdown vs JSON mode tradeoff.** Spec recommends markdown over
JSON mode. Markdown wins on schema evolution (add a section without
breaking parse) and truncation robustness (JSON truncation breaks
everything; markdown truncation loses tail content but earlier
sections still parse). Re-evaluate if parser maintenance becomes a
burden — introducing `responses.parse` JSON mode is a small refactor.

**Prompt template substitution.** Custom `{{var}}` regex (stdlib,
no Jinja2 dep, no curly-brace collision with code-block examples in
prompts). Substitution validator raises before any LLM call if any
`{{placeholder}}` remains unfilled.

### Per-site deploy declaration (v10.A)

**TOML round-trip determinism.** `tomli-w` is the writer (`tomlkit`
is heavier than its value at personal scale). No comment preservation
on round-trip — operator edits go through `$EDITOR` directly.

**Inference logic on multiple platform configs.** Migration refuses
to auto-write when `wrangler.jsonc` + `vercel.json` (or any two)
co-exist. `--include-ambiguous` lets the operator skip the manual
step at the cost of a possibly-wrong default (priority order
`vercel.json > wrangler.jsonc > netlify.toml`, with a `notes.text`
warning).

**Interactive prompt UX for hostgator.** `set-deploy hostgator`
requires cpanel + FTP breadcrumbs. Prompts are sequential with
clear-Enter-to-skip semantics; `--non-interactive` mode rejects if
any required field is missing.

### Fleet hosting (v11.A)

**Pagination + deploy-history variability.** Each provider paginates
differently; deploy history depth varies. The `MAX_DEPLOY_LOOKBACK=10`
cap with the two-tier "≥10 consecutive failures" signal preserves
the runaway-failures case while bounding API calls (~50 calls for a
25-domain fleet, well within rate limits).

**Domain ↔ project matching edge cases.** Bare-host normalize (strip
leading `www.` from both sides). `calcengine.site` matches both
`["www.calcengine.site"]` and `["calcengine.site"]`.

**Provider conflict (same domain on both).** Two rows in the
snapshot — one per provider — make the drift visible. Rollup counts
treat as a single conflict; renderer can deduplicate visually with
the conflict glyph.

**Partial-coverage rendering.** A 401 from one walker skips that
walker entirely (footer: "Vercel skipped: token missing"); a 5xx /
rate-limit becomes a per-row `error` field with `?` glyph. The other
provider's rows still render normally.

## 11. Tracked refactors

Refactors recommended during design but not yet scheduled. Carried
here so they don't get lost.

### `cli.py` monolith — split into scope-first modules

**Current state.** `src/portfolio/cli.py` is **8,782 lines** as of
2026-05-21 — 4× the next-largest module (`hosting.py` at 2,054).
Nearly every phase touches it; today's bug-fix run alone hit four
unrelated stretches (MENU_ITEMS at line 2079, Step 5.5 DNS purge at
6263, HG-extra column at 7782, footer aggregation at 7943).
Grep+offset Read is the only navigation that works at this size.

**Proposed split.** Mirrors the existing scope-first CLI structure
(`project` / `fleet` / `new` / `settings`):

```
src/portfolio/cli/__init__.py     ← typer app registration + global flags
src/portfolio/cli/project.py      ← project {check, fix, seo, hosting, translate}
src/portfolio/cli/fleet.py        ← fleet {check, focus, live, seo, hosting, sync, dashboard, fix}
src/portfolio/cli/new.py          ← new {bootstrap, deploy, domain, validate}
src/portfolio/cli/settings.py     ← settings {catalog, gsc, apikeys, deploy}
src/portfolio/cli/domain.py       ← domain suggest + the menu loop
src/portfolio/cli/_render.py      ← shared renderers (_render_menu, _render_bootstrap_preflight, _hg_accounts_disk_summary, ...)
```

**Trigger.** Don't undertake mid-tier. Schedule for a clear gap —
after v23 wraps and before the next feature tier kicks off. v14.B's
hard-cutover CLI restructure proved this style of work is tractable;
this is a larger cousin of that pattern.

**Risk.** High (lots of cross-references inside one file; helper
functions used by multiple command groups need careful placement in
`_render.py` vs. specific modules). Test discovery needs to follow.

### Platform-name enum drift

**Current state.** Three modules with three spellings for the same
deploy-platform values:

| Module | Spelling | Origin |
|---|---|---|
| `lamill_toml.PLATFORM_VALUES` | `cf-pages` / `cf-workers` | v10.A schema |
| `hosting.PROVIDER_*` constants | `cloudflare-pages` / `cloudflare-workers` | v11.A walkers |
| `project.PLATFORM_MARKERS` | `cloudflare-pages` only (no workers row) | pre-v15 marker map |

v15.S-followup added a `_LAMILL_PLATFORM_TO_DETECT` translation map
in `project.py` (2026-05-21) to patch the cf-workers `project check`
deploy-summary bug — but that's symptom-treating. Every new deploy-
platform addition will hit the same drift.

**Proposed fix.** One canonical `src/portfolio/platforms.py` module
exposing:

  - A single `PLATFORM` enum / constants list.
  - One short-form (lamill.toml `cf-pages` style) and one long-form
    (`cloudflare-pages` style) per platform, plus the translation.
  - The marker map (file → platform), keyed off the same enum.

`lamill_toml.py`, `hosting.py`, `project.py`, `dashboard.py` all
import from `platforms.py` instead of defining their own constants.

**Trigger.** Either (a) a new deploy platform lands (`fly.io`,
`render.com`, etc.) and the drift bites again, or (b) folded into
the cli.py monolith split since `project.py` would already be
opened during that work.

**Cost.** ~2-3h careful renaming + cross-module audit + test pass.
Low risk per-file but breadth is wide.

### `LLMClient` protocol (existing carryover)

`{call(system, user) -> str}` with `AnthropicClient` /
`OpenAIClient` / `GeminiClient` implementations — named as a
candidate refactor (see §10 Research module risks — rate-limit
handling differs by provider) but not scheduled. Trigger: a third
LLM provider lands.

---

## See also

- `docs/prd.md` — purpose, problem statement, target user,
  versions/phases, conformance rules, open questions.
- `docs/shipping-history.md` — archived design rationale for shipped
  phases.
- `docs/decisions/` — ADRs for load-bearing architectural decisions.
- `docs/CLAUDE.md` — Claude-specific decisions and conventions.
- `AI_AGENTS.md` — agent orientation; canonical versioning rule.
