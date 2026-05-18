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
│   ├── suggest.py                # `new suggest` (Power 1 — domain brainstorm)
│   ├── decide.py                 # validation-mode shortlist + decide
│   ├── availability.py           # RDAP + Porkbun availability/pricing
│   ├── cloudflare.py             # CF API client (Pages + Workers)
│   ├── gsc.py                    # Google Search Console OAuth + queries
│   ├── gsc_recrawl.py            # GSC sitemap-resubmit flow
│   ├── seo_runtime.py            # live HTTP SEO probe orchestrator
│   ├── seo_cache.py              # snapshot save/load for `data/seo/`
│   ├── serp.py                   # cluster builder for `new research`
│   ├── serp_fetch.py             # SerpAPI client
│   ├── serp_query_cache.py       # per-query snapshot cache under `data/serp/`
│   ├── serpapi_quota.py          # SerpAPI monthly-quota counter
│   ├── research_v2.py            # `new research` orchestrator (Phases 1-3 mechanical)
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

Per ADR-0003, `portfolio` has **two write surfaces only**. Adding a
third needs an explicit operator decision and a new ADR.

| Surface | Purpose | Operator gate |
|---|---|---|
| `new bootstrap <domain>` | Creates a new `sites/<domain>/` project dir — `git init`, scaffolds AI_AGENTS.md / docs / Makefile / public assets / `lamill.toml`, sets up the central-builder forward | Required positional arg; no implicit-create flow |
| `project fix <domain> --apply` | Modifies an existing project dir to close conformance gaps — runs Tier 1 templated fixers, optionally Tier 2 Claude subprocess | `--apply` required (default is dry-run); `--yes` skips confirmation |

Read-only commands: everything else. `new deploy`, `new suggest`,
`fleet *`, `project check`, `project diagnose`, `settings *` —
none write to project dirs. Snapshot files under `data/` and
credential rotation through `settings apikeys` are not project-dir
writes; they're tool-local state.

The two-surface constraint is *load-bearing* for trust: an operator
can run `lamill <anything>` against an unrelated repo and know it
won't be modified.

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

Pluggable per-provider walker pattern in `src/portfolio/hosting.py`:

- `walk_vercel(token, only_domain=None) -> list[HostingRow]`
- `walk_cf_pages(api_token, account_id, only_domain=None) -> list[HostingRow]`

Each walker:
1. Paginates the provider's projects-list endpoint.
2. For each project, reads the latest deploy + walks deployment
   history (capped at `MAX_DEPLOY_LOOKBACK=10`; two-tier — stop at 10
   and mark "≥10 consecutive failures").
3. Maps each project's configured custom domains to fleet domains via
   bare-host match (strips leading `www.`).
4. Returns one `HostingRow` per matched fleet domain; unmatched
   projects drop silently (they're not in the fleet).

`run_hosting(domains)` orchestrator calls both walkers in parallel
(`ThreadPoolExecutor`, mirrors `seo_runtime.run_seo`). Domains
matched by BOTH providers emit a row with `provider_conflict=True`
in `notes[]` — drift signal.

Provider error surfaces follow `prd.md` v11 Design notes — resolution 11.H:
- 401 (auth) → skip the affected walker entirely; footer says
  "Vercel skipped: token missing/invalid."
- 5xx / rate-limit → per-row `error` field on affected domains;
  renders with `?` glyph.

### Research module (v8.E–v8.J + v12.A onward)

Three-stage pipeline added to `new research`:

1. **Phase 4a — Primary interpretive pass** (`interpretive_pass.py`).
   Renders `prompts/niche_evaluation_v1.md` with operator-profile +
   mechanical-gates payload, calls `run_claude_text()` (Claude CLI
   subprocess, not the Anthropic SDK — avoids a second API-key
   surface, rides the operator's existing Claude subscription quota).
   Parses markdown response into `ParsedVerdict`.

2. **Phase 4b — Adversarial audit pass** (`audit_pass.py`). Renders
   `prompts/adversarial_audit_v1.md`. Calls OpenAI (GPT-4o default;
   `ANTHROPIC_API_KEY`-style strict-different-model invariant —
   `--model X --audit-model X` is rejected loudly with the
   correlated-blind-spot rationale). Parses into `ParsedAudit`.

3. **Phase 4c — Reconciliation** (no LLM call). Pure-logic
   reconciliation per the truth table:
   - `agreement_level=full` → primary verdict; confidence = min(primary, audit)
   - `agreement_level=partial` → primary verdict; confidence
     downgraded one notch (HIGH→MEDIUM, MEDIUM→LOW, LOW→LOW)
   - `agreement_level=disagree` → `REVIEW_REQUIRED` (first-class
     verdict alongside GO / NICHE-DOWN / NO-GO)

Both prompts live at repo-root `prompts/` (first-class, alongside
`tests/` and `docs/`). Versioned `<purpose>_v<N>.md`. Snapshots
record `prompt_version`; mismatch with the current `_vN.md` is
"stale verdict — re-render via `--no-cache=interpretive`."

The audit pass is **opt-in** behind `--verify`. Default mode is
primary-only (cost ~$0.01-0.02/run); verify mode adds GPT-4o
(~$0.05-0.10/run). Operator-profile flag `verify_by_default` (in
`sites/portfolio/lamill.toml [operator]`) flips the default;
`--no-verify` overrides.

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

- `OPENAI_API_KEY` — `new suggest`, `audit_pass`
- `PORKBUN_API_KEY`, `PORKBUN_SECRET_API_KEY` — availability +
  registration
- `CF_API_TOKEN`, `CF_ACCOUNT_ID` — Pages + Workers walker
- `CRUX_API_KEY` — `seo_runtime` field-data probe
- `SERPAPI_KEY` — `new research` real SERP fetch
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
verify_by_default = false            # v12 — flips `new research --verify` default
```

**Defaults applied if section absent:**
- `[deploy]` required.
- `[hosting]` optional; required if `platform ∈ {hostgator, custom}`.
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

Research-cluster snapshot. Schema `research-cluster-v2.1` (additive
bump from v2):

```json
{
  "schema": "research-cluster-v2.1",
  "cluster_queries": ["..."],
  "operator_profile_snapshot": { /* ... */ },
  "gates": { /* Phase 1/2/3 mechanical outputs */ },
  "raw_top_10_per_query": [ /* ... */ ],

  "interpretive_pass": {
    "model": "claude-sonnet-4-7",
    "prompt_version": "niche_evaluation_v1",
    "rendered_prompt_hash": "<sha256-prefix>",
    "raw_response": "<full markdown response, verbatim>",
    "estimated_cost_usd": 0.012,
    "parsed": {
      "verdict": "NICHE-DOWN",
      "confidence": "MEDIUM",
      "reasoning": "...",
      "moat_required": true,
      "moat_prompt": "...",
      "reductions": ["..."],
      "operator_fit_warnings": ["..."],
      "blind_spot_self_report": "..."
    }
  },

  "audit_pass": {
    "ran": true,
    "model": "gpt-4o",
    "prompt_version": "adversarial_audit_v1",
    "rendered_prompt_hash": "<sha256-prefix>",
    "raw_response": "<full markdown response, verbatim>",
    "estimated_cost_usd": 0.043,
    "error": null,
    "parsed": {
      "agreement_level": "partial",
      "confidence": "MEDIUM",
      "specific_concerns": ["..."],
      "counter_verdict": null,
      "audit_self_check": "..."
    }
  },

  "reconciliation": {
    "ran": true,
    "final_verdict": "NICHE-DOWN",
    "final_confidence": "LOW",
    "disagreement_surfaced": false,
    "review_required": false
  }
}
```

Schema bump v2 → v2.1 is additive; existing v2 readers ignore new
fields. Caches written by v2-only research load without re-fetch.

`audit_pass.ran=true` with `audit_pass.error="..."` and
`reconciliation.ran=false` records audit-failure cases (audit API
down / unparseable response / refusal). Primary verdict is still
valid signal.

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

#### `HostingRow` (v11.A — `src/portfolio/hosting.py`, planned)

```python
@dataclass
class HostingRow:
    """One domain's deploy state across Vercel + Cloudflare Pages."""
    domain: str
    provider: str | None              # "vercel" | "cloudflare-pages" | None
    project_slug: str | None
    project_id: str | None
    latest_deploy_status: str | None  # READY | ERROR | BUILDING | CANCELED
    latest_deploy_at: str | None      # ISO 8601 UTC
    last_successful_deploy_at: str | None
    consecutive_failures: int = 0
    provider_conflict: bool = False
    error: str | None = None
    notes: list[str] = field(default_factory=list)
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

```
lamill
├── project                                          # ops on one project
│   ├── check <name>                                 ✅ v7.A
│   ├── fix <name>                                   ✅ v6.D
│   ├── seo <name>                                   ✅ v7.A
│   ├── diagnose <name>                              ✅ v7.F
│   ├── version <name>                               ⏳ v14.A — read local
│   │                                                          version.json
│   └── deploy-status <name>                         ⏳ v14.B — HEAD vs deployed
│                                                              SHA (or fold into
│                                                              `diagnose`?)
│
├── fleet                                            # cross-portfolio ops
│   ├── focus                                        ✅ v7.D
│   ├── domains                                      ✅ v5.G
│   ├── seo                                          ✅ v5.D
│   ├── check                                        ✅ v5.B
│   ├── fix                                          ✅ v6.G
│   ├── drift                                        ✅ v6.A
│   ├── repos [--add-deploy-declarations]            ✅ v7.E (flag in v10.C)
│   ├── dashboard                                    ✅ v7.B
│   ├── hosting                                      ⏳ v11.A — Vercel + CF
│   │                                                          deploy state
│   ├── trends                                       ⏳ v13.A — namespace
│   │                                                          deferred (`fleet`
│   │                                                          vs `settings gsc`)
│   ├── (HostGator surface)                          ⏳ v10.F — design open;
│   │                                                          first proposal
│   │                                                          rejected, awaiting
│   │                                                          rethink
│   └── info
│       ├── summary                                  ✅ v7.A
│       ├── expiring                                 ✅ v7.A
│       ├── cleanup                                  ✅ v7.A
│       └── list                                     ⏳ v13.B — aggregate
│                                                              verdict-counts
│                                                              view
│
├── new                                              # create work
│   ├── suggest                                      ✅ v2.A
│   ├── bootstrap                                    ✅ v3.A
│   │                                                   (writes lamill.toml in
│   │                                                   v10.C)
│   ├── deploy                                       ✅ v3.C
│   │                                                   (reads lamill.toml +
│   │                                                   routes CF Pages or SFTP
│   │                                                   in v10.G)
│   └── research [--verify]                          ✅ v8.D
│                                                       (flag added in v12.E)
│
└── settings                                         # setup / debug
    ├── catalog {list, describe, run}                ✅ v7.A
    ├── gsc {auth, status}                           ✅ v7.A
    ├── apikeys {list, set, delete}                  ✅ v7.A
    ├── operator {show}                              ✅ v8.D
    ├── cloudflare {token, status}                   ✅ v7.H
    ├── serpapi-quota {show, sync}                   ✅ v8.D
    ├── project                                      # per-project metadata
    │   ├── set-launched <name> <date>               ✅ v7.C (moved here from
    │   │                                                    `project set-launched`
    │   │                                                    2026-05-18 — per-project
    │   │                                                    metadata fits settings)
    │   ├── set-deploy <name> <platform>             ✅ v10.B
    │   └── show-deploy <name>                       ✅ v10.B
    ├── (HostGator credentials)                      ⏳ v10.F — design open
    └── cost report                                  ⏳ v12.F (deferred) — LLM
                                                                cost ledger
```

#### Net additions by phase

| Phase | New CLI surface |
|---|---|
| v10.B | `settings project set-deploy` ✅ · `settings project show-deploy` ✅. Also moved `set-launched` (v7.C) into the `settings project` namespace for consistency — per-project metadata stays together; `project` namespace reserved for project-code ops. |
| v10.C | `fleet repos --add-deploy-declarations` flag · `new bootstrap` writes `lamill.toml` (no surface change) |
| v10.D | None (validation phase — uses existing CLIs) |
| v10.E | None (CHECK_xxx series — surfaced via existing `project check` / `fleet check`) |
| v10.F | HostGator surface — design open (first proposal `settings hostgator` + `fleet hostgator` split was **rejected** 2026-05-18; needs rethink before v10.F starts) |
| v10.G | `new deploy` extended (no new node — transparently picks target from `lamill.toml`) |
| v11.A | `fleet hosting` |
| v12.B-G | `new research --verify` / `--no-verify` / `--audit-model <id>` / `--no-cache=audit` flags (no new node) |
| v13.A | GSC trend correlation — namespace deferred (`fleet trends` vs `settings gsc trends`) |
| v13.B | `fleet info list` (or `project list` — naming TBD) |
| v13.C | LLM content seeding — postponed indefinitely; no surface change |
| v14.A | `project version` |
| v14.B | `project deploy-status` (or fold into `diagnose`?) |
| v14.C | (deploy lag / build status surfaced via existing `fleet hosting`?) |
| v14.D | `cleanup --refresh` / `--watch` flags (no new node) |

#### Open CLI design questions

These are deliberate non-decisions — resolve before the relevant
phase ships. The operator either gates these in a planning session
or signals "decide it when you get there" per-phase.

1. **v10.F HostGator surface (design open).** First proposal —
   `settings hostgator {token, accounts}` for creds + `fleet
   hostgator {pull, status, sync}` for data — was rejected by the
   operator 2026-05-18 ("don't like that CLI at all"). The
   HostGator-shape question is parked until v10.F gets picked up.
   Until then: no new `hostgator` commands land anywhere.
2. **v13.A GSC trends namespace.** `fleet trends` (scope-first;
   reuses `data/gsc/` snapshots; sits next to `fleet seo`) vs
   `settings gsc trends` (keeps all GSC stuff together; sits
   next to existing `settings gsc auth`/`status`). Deferred until
   v13.A starts.
3. **v13.B roll-up listing.** `fleet info list` (matches existing
   inventory views; clean fit) vs `project list` (matches
   pre-v7.A name; was deprecated). Leaning `fleet info list` —
   confirm at v13.B kickoff.
4. **v14.B deploy-status placement.** Standalone `project
   deploy-status <name>` vs fold the HEAD-vs-deployed check into
   the existing `project diagnose <name>` 5-layer probe. The
   diagnose path is closer to the existing UX shape; standalone
   adds a discoverable verb. Defer until v14.B starts.

### `--verify` semantics (v12)

`lamill new research <topic>`:
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
| **OpenAI** | `new suggest` brainstorm; `audit_pass` (v12) | `OPENAI_API_KEY` (Bearer) | 429 with `Retry-After` |
| **Anthropic (Claude CLI subprocess)** | `interpretive_pass` primary (v8); Tier 2 fixers (v6.E) | Operator's existing Claude subscription via local CLI | Different I/O shape from direct API; cost model per local subscription, not per-token |
| **Anthropic API** | Reserved — direct-API switch path for primary pass | `ANTHROPIC_API_KEY` (header `x-api-key` + `anthropic-version`) | Per-provider rate-limit dialect; not currently exercised |
| **Cloudflare** | Pages projects, Workers, DNS lookups | `CF_API_TOKEN` + `CF_ACCOUNT_ID` | Pagination on Pages projects list |
| **Vercel** | v11.A `fleet hosting` walker | `VERCEL_TOKEN` (Bearer) | Personal token sees only personal account; multi-team out of scope (`prd.md` v11 Design notes — 11.A) |
| **CrUX (Chrome UX Report)** | `seo_runtime` field data | `CRUX_API_KEY` | `no-data` for personal-portfolio-scale origins (expected; not a bug) |
| **SerpAPI** | `new research` real SERP fetch | `SERPAPI_KEY` | Monthly quota tracked in `data/serp/_quota.json` |
| **Google Search Console** | `gsc.py` ranking + impressions | OAuth (`GOOGLE_OAUTH_*`) | 28-day rolling window for the operator's verified properties |
| **Porkbun** | Availability + pricing + registration | `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` | Registration is the only registrar API the tool calls; GoDaddy/Namecheap are CSV-export only |
| **RDAP** | Availability fallback | Anonymous | Authoritative WHOIS replacement |
| **GitHub** | Repo creation in `new deploy` | `gh` CLI delegation | The tool shells out to `gh`; no direct API client |

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
| `suggest.py` | `new suggest <topic>` Power 1 brainstorm | `suggest_domains` |
| `decide.py` | Validation-mode shortlist + decide | `mark_shortlist`, `decide_from_shortlist` |
| `availability.py` | RDAP + Porkbun availability + pricing | `check_availability` |
| `cloudflare.py` | CF API client (Pages, Workers, DNS) | `walk_pages_projects`, `dns_lookup` |
| `gsc.py` | GSC OAuth + queries + sync | `gsc_auth`, `gsc_status` |
| `gsc_recrawl.py` | Sitemap resubmit flow | `recrawl_property` |
| `seo_runtime.py` | Live HTTP SEO probe orchestrator | `run_seo(domains)` |
| `seo_cache.py` | Snapshot save/load for `data/seo/` | `save_snapshot`, `latest_snapshot`, `is_stale` |
| `serp.py` | Cluster builder for `new research` | `build_cluster` |
| `serp_fetch.py` | SerpAPI client | `fetch_serp_for_query` |
| `serp_query_cache.py` | Per-query snapshot cache under `data/serp/` | `save_query_snapshot`, `load_query_snapshot` |
| `serpapi_quota.py` | SerpAPI monthly-quota counter | `bump_quota`, `quota_remaining` |
| `research_v2.py` | `new research` orchestrator (Phases 1-3) | `run_research(topic, *, verify)` |
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

When v10.D ships, the v10 Design notes move to
`docs/shipping-history.md` and these slices land as a single
`## v10.A · ... — shipped 2026-05-18` entry there.

### v10.B — operator CLI surfaces ✅ (shipped 2026-05-18)

Two slices delivered the CLI half of `lamill.toml`:

- *`settings project set-deploy <name> <platform>`* — interactive
  by default; hostgator/custom walks cpanel + FTP breadcrumbs.
  `--non-interactive` + flags (`--account`/`--branch`/
  `--auto-deploy`/`--no-auto-deploy`/`--domain` repeatable/
  `--cpanel-user`/.../`--public-html-path`) for scripted use. Writes
  via `lamill_toml.write()` (atomic). 17 tests at
  `tests/test_settings_project_set_deploy.py`.
- *`settings project show-deploy <name>`* — rich-table renderer +
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
v10.D ships and the whole tier moves to `shipping-history.md`.

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

v10.D (validation phase) runs this against the actual fleet
next; design notes stay in `prd.md` until v10.D ships and the
whole tier moves to `shipping-history.md`.

### v10.D — validation phase (planned)

~2-3h. Real-fleet rollout. Operator-driven, not code-heavy:

- Run `lamill fleet repos --add-deploy-declarations --dry-run`
  against the actual 22-ish-domain fleet.
- Review the plan; resolve any v10.A/B/C bugs that surface (real
  config files in the wild often have edge cases the test fixtures
  don't cover).
- `--apply` the unambiguous cases.
- For each ambiguous / manual-entry case, run `lamill project
  set-deploy <name> <platform>` interactively.
- Each sibling `sites/<domain>/` repo gets a `lamill.toml`
  committed in (each repo's own commit, not bundled into
  `sites/portfolio`).
- End state: every applicable sibling repo carries a valid
  `lamill.toml`; v10.E (drift detection) can now read declarations.

Validation phase exit criterion: every sibling repo classified as
`live-site` or `forwarder` in the latest `data/checks/<date>.json`
has a committed `lamill.toml`. Archived / parked / dead sites
skipped per the migration's archived-detection rules.

### v11.A — `fleet hosting` — fleet-wide Vercel/CF deploy state

~12-17h, twelve commits. Mirrors `fleet seo` shape: read-only,
cached, refreshable, emoji table. Each commit subject is
`portfolio: v11.A — <slice>`.

Sequential slices, in commit order:

- *`VERCEL_TOKEN` API-keys plumbing.* Add to `apikeys.KNOWN_KEYS`
  + `_probe_vercel()` (`GET /v2/user`, 5s timeout). One new test.
- *Dataclass + constants.* New `src/portfolio/hosting.py` with
  `HostingRow` dataclass; constants `RECENT_DAYS=30`,
  `STALE_DAYS=90`, `MAX_DEPLOY_LOOKBACK=10`.
- *Vercel walker.* `walk_vercel()` — paginated projects list +
  per-project deployments. Mocked unit tests.
- *Cloudflare Pages walker.* `walk_cf_pages()` — same shape against
  the CF API.
- *Orchestrator + match logic.* `run_hosting()` + domain-match
  bare-host normalize + provider-conflict detection.
- *Snapshot cache.* `hosting_cache.py` mirroring `seo_cache.py`.
- *CLI shell + cache-eligibility.* `fleet hosting` Typer command +
  cache-eligibility logic + `--refresh` / `--only` / `--json`
  flags.
- *Table renderer.* `_render_hosting_table()` + status-emoji helper.
  Five columns: Domain · Provider · Status · Last Success ·
  Failures. Footer with rollup counts.
- *Walker error surfaces.* Token-missing surface + per-row 5xx /
  rate-limit rendering (per `prd.md` v11 Design notes — resolution
  11.H).
- *Dashboard join.* `dashboard.py`: new `Hosting` column joining
  the latest `data/hosting/` snapshot.
- *Diagnose integration.* `diagnose.py`: optional "Hosting:"
  section when a hosting snapshot covers the diagnosed domain.
- *Docs update.* `docs/CLAUDE.md`, `AI_AGENTS.md`,
  `docs/Prompts.md`, prd v11.A row → ✅, v11.A Design notes →
  `shipping-history.md`.

**Test strategy** (`prd.md` v11 Design notes — resolution 11.J): all
real API calls mocked at the `httpx`/`requests` layer (same pattern
as `tests/test_gsc_recrawl.py`). No CI calls to real Vercel or
Cloudflare APIs.

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
  guidance added to `lamill new research --help`.

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

*(None active right now.)*

The `LLMClient` protocol — `{call(system, user) -> str}` with
`AnthropicClient` / `OpenAIClient` / `GeminiClient` implementations
— is named as a candidate refactor (see §10 Research module risks —
rate-limit handling differs by provider) but not scheduled. Trigger:
a third LLM provider lands.

---

## See also

- `docs/prd.md` — purpose, problem statement, target user,
  versions/phases, conformance rules, open questions.
- `docs/shipping-history.md` — archived design rationale for shipped
  phases.
- `docs/decisions/` — ADRs for load-bearing architectural decisions.
- `docs/CLAUDE.md` — Claude-specific decisions and conventions.
- `AI_AGENTS.md` — agent orientation; canonical versioning rule.
