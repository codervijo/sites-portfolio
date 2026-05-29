# CLAUDE.md — sites/portfolio/

Per-project orientation for Claude. Read this first when picking up work
on this repo. Index of decisions, conventions, and deliberate non-features
that aren't obvious from the code or git history.

## Project

`portfolio` is a Python+uv CLI for managing a personal domain portfolio
plus a sibling `sites/<domain>/` workspace. It does three big things:

  1. Domain lifecycle — `domain suggest` (brainstorm + price/availability
     + interactive shortlist + decision aid + register via Porkbun).
  2. Project bootstrap — `bootstrap <domain>` scaffolds a Vite/Astro site
     under `sites/<domain>/` (first project-dir write surface). `deploy
     <domain>` creates the GitHub repo + Cloudflare Pages project.
  3. Universal check catalog — `fleet live` (classify domains), `fleet check`
     (cross-repo catalog), `fleet seo` and `project seo` (runtime SEO probe).
     Checks live in `src/portfolio/checks/<category>/check_NNN_<slug>.py`
     with auto-discovery via the registry.

`docs/prd.md` is the canonical spec; `docs/Prompts.md` is the prompt log
(parsed by `portfolio project check`); `docs/CLAUDE.md` is this file.

## Commands

CLI restructured in v7.A to scope-first (`project` / `fleet` / `new` /
`settings`). Old top-level names (`info status`, `check git`, `focus`,
`project fix`, etc.) still work as additive paths in v7.A.1; they'll
become deprecation aliases in v7.A.2.

```bash
# Test
uv run pytest -q

# Per-project status
uv run portfolio project check <domain>

# Per-project remediation
uv run portfolio project fix <domain> --apply --yes

# Cross-repo health
uv run portfolio fleet check

# Where to focus today
uv run portfolio fleet focus

# Cross-source drift report
uv run portfolio fleet drift

# Fleetwide SEO probe
uv run portfolio fleet seo --refresh

# Fleetwide remediation
uv run portfolio fleet fix --apply --yes

# Setup / debug
uv run portfolio settings apikeys list
uv run portfolio settings catalog list

# Bootstrap a new sites/<domain>/ project
uv run portfolio new bootstrap <domain>
```

## Conventions

  - **pnpm-only** for all `sites/*` projects. `package-lock.json` /
    `bun.lockb` / `yarn.lock` are conformance failures. Vite ≥6, Astro ≥5
    (CF Pages bun-detection trap was hit on Vite 5).
  - **Makefile forwards to parent** — every `sites/*` project's Makefile
    delegates to `~/work/projects/builder/`'s `Makefile` via
    `$(MAKE) -C ..` (CHECK_012). Don't duplicate build logic per-site.
  - **Two local-FS write surfaces only** (ADR-0003): v3 bootstrap
    (creates new project dirs) and v6.D remediation (modifies
    existing project dirs to fix conformance gaps). Everything else
    is read-only on the local FS. **Remote-host writes** (v11.N's
    UAPI deploy to cPanel) are a separate category governed by
    ADR-0011 — they don't touch sibling project dirs.
  - **`portfolio` + `rankmill` repos are excluded from `check --git`** by
    default (`[git] ignore_repos = ["portfolio", "rankmill"]`) — they're
    sibling Python CLI tools, not websites, so the SEO/stack checks would
    all skip and create noise. Same dirs also live in
    `fleet_repos._NON_PROJECT_NAMES` so `fleet repos` doesn't audit them.
  - **Five canonical doc surfaces** (all must match reality + code
    per `docs/prd.md § Spec discipline`):
    - `docs/prd.md` — WHY / WHAT / WHEN (purpose, problem, target
      user, goals, versions/phases, conformance rules, open questions)
    - `docs/architecture.md` — HOW (project layout, mechanisms,
      schemas, modules, CLI/UX, integrations, stack baselines,
      active implementation plans, risks, tracked refactors)
    - `docs/shipping-history.md` — archived design rationale for
      shipped phases (append-only)
    - `docs/decisions/` (ADRs) — load-bearing architectural
      decisions (Nygard format; see ADR-0001 and `decisions/README.md`)
    - `docs/CLAUDE.md` — this file; Claude-specific decisions,
      locked target shapes, deferred decisions, heading hygiene rule,
      ADR workflow
    - Plus `AI_AGENTS.md` (at repo root) — agent orientation +
      canonical `vN.X` versioning rule (per ADR-0004).

## Canonical docs — when to update which

| If you're changing… | …update this doc | …in the same commit |
|---|---|---|
| A mechanism, schema, or module | `docs/architecture.md` | yes |
| Phase status (planned → in-progress → shipped) | `docs/prd.md` phase row | yes |
| A phase has just shipped | move its design notes from `prd.md` to `docs/shipping-history.md` | yes |
| Goals, target user, conformance rule, open question | `docs/prd.md` | yes |
| **A load-bearing architectural decision** (new or reversed) | **write a new ADR in `docs/decisions/`** | **yes** |
| A Claude-specific convention or locked target shape | `docs/CLAUDE.md` (this file) | yes |
| Agent-orientation summary or versioning rule | `AI_AGENTS.md` | yes |

**Stale docs are a conformance failure, not a backlog item.** Never let
docs drift "to be updated later" — fix in the same commit as the code
change that made them stale.

## ADR workflow

`docs/decisions/` holds **Architecture Decision Records** (ADRs) for
load-bearing architectural decisions. See `docs/decisions/README.md`
for the full format spec. Quick reference:

**Write an ADR when** a decision is load-bearing — i.e., future
re-evaluation would hinge on knowing *why* this was chosen. Heuristic:
"would someone six months from now ask 'why is it this way?' and need
the rationale beyond what the code shows?"

- ✅ ADR: language/runtime, write-surface constraints, catalog
  shape, model-family choices, lockfile policy, build conventions,
  doc-structure choices.
- ❌ Not ADR: small implementation details (parser library, default
  flag values, log format). Those belong in `shipping-history.md` or
  code comments.

**Forward commitment.** When working on a new phase that introduces a
load-bearing decision, **an ADR is part of the shipping unit** —
written alongside the code and the doc updates, not deferred. The
PRD's § Spec discipline rule treats missing ADRs as drift.

**Naming.** `NNNN-kebab-case-title.md`, four-digit zero-padded,
sequentially numbered. Never re-number. The ID is the stable
reference.

**Supersession.** Don't edit accepted ADRs. To reverse a decision:
1. Write a new ADR with the next available number capturing the new
   decision; frontmatter says `Supersedes: ADR-NNNN`.
2. Update the old ADR's frontmatter: `Status: Superseded by ADR-MMMM`.
3. Update `docs/decisions/README.md` index for both rows.
4. Old ADR body stays intact — historical record.

**Status values:** `Proposed` | `Accepted` | `Deprecated` |
`Superseded by ADR-NNNN`.

**Scope: portfolio only.** Sibling `sites/<domain>/` projects do NOT
use ADRs — they're consumer projects without architectural
complexity to warrant the overhead.

## Heading hygiene

**Before adding any section, subsection, or heading to a Markdown
file, output the file's current heading outline first:**

```bash
grep -nE '^#+ ' path/to/file.md
```

Then confirm — in the chat — that the planned new heading's:

1. **Depth** (`#`, `##`, `###`, …) is the intended depth, not
   accidentally one level too shallow.
2. **Label** doesn't collide with existing headings — no duplicate
   `## 1. <title>`, no `### N.X` subsection labels that look like
   `vN.X` phase identifiers.

Only after that confirmation, write.

Applies especially to long-lived docs:
`docs/prd.md`, `AI_AGENTS.md`, `docs/architecture.md`, `docs/CLAUDE.md`.

**Why:** `docs/prd.md` accumulated four detailed-PRD bodies inlined
at `##` depth instead of `###` under a parent `## 8. Detailed PRDs`.
Each one created another `## 1. Problem statement` at the same depth
as the file's top-level `## 1. Purpose`. The drift was invisible in
any single design session — only visible in the aggregate (VS Code
outline view showed a flat column with repeating numbers). The
pre-edit outline ritual catches this at the point of writing, not
at quarterly cleanup time.

## Locked target shapes

Designs aligned and load-bearing. When picked up, no need to re-debate.
**These are invariants** — changes here need a deliberate ADR-level decision, not a casual edit.

### 🔒 `new deploy` idempotency invariant (ADR-0015, accepted 2026-05-23)

**Every step in `_deploy_cf_unified` (cli.py) MUST be idempotent.**
Re-running `lamill new deploy <domain>` on a fully or partially
deployed domain MUST succeed cleanly without modifying state.

If you're touching anything in the deploy pipeline:

1. **Probe before act.** Every state-changing API call needs a
   `get_X()` / `list_X()` / `status_X()` probe first; skip the
   write when state already matches the target.
2. **Catch "already exists" responses.** CF / GitHub / Porkbun /
   Google APIs surface duplicates variously — HTTP 200 with flags,
   HTTP 409, or provider-specific HTTP 400 + error codes (e.g.,
   CF code 8000018 for "custom domain already added"). Each must
   map to a success outcome (return `False` for "no change"), not
   a raised exception.
3. **Soft-fail non-load-bearing failures.** Auxiliary integrations
   (GSC, analytics) should capture failure in a status field and
   let the pipeline continue.
4. **Default is quick + idempotent.** The pipeline does NOT block
   waiting for external state to settle (NS propagation can take
   minutes to hours). It reports `↷ <state>` and tells the operator
   how to recover.
5. **`--watch` is the only opt-in blocking flag.** Don't add other
   wait-by-default behaviors.

**Why this is load-bearing:** the pipeline runs against external
state that settles over 5-30 min (NS propagation, CF build, SSL).
Operator confirmed 2026-05-23 PM that quick + idempotent default is
the right shape — re-running is cheap (idempotent steps skip),
blocking the shell for half an hour to absorb propagation is the
anti-pattern. The full reasoning is in
[ADR-0015](decisions/0015-deploy-pipeline-must-remain-idempotent.md).

**Self-check for any deploy-step change:** "If the operator re-runs
this exact command immediately, does the second run succeed cleanly
without modifying state?" If no, the change isn't ready.

### 🔒 `lamill.toml` additive-optional invariant (v27 — accepted 2026-05-29)

**Any optional table in `lamill.toml` must remain optional everywhere —
no parser, check, or consumer may require it.**

If you're adding or touching a `lamill.toml` consumer, this is
non-negotiable:

1. **Loader defaults missing tables; never errors.** `_parse_doc` treats
   an absent optional table as its empty/`None` form (e.g. `todos == []`,
   `stack is None`). Missing tables are not a `ParseError`; they're the
   baseline state for every existing file. CHECK_059 must stay green on
   a `lamill.toml` that has only `schema` + `[deploy]`.

2. **Consumers fall back; no warn-just-because-missing.** Every reader
   (`fleet check`, `project check`, deploy pipeline, hosting, focus,
   `new bootstrap`, `settings deploy set`, dashboards) must function on
   a file that has neither the new table nor any historical version of
   it. Stack-aware checks fall back to file-system heuristics; todo-
   aware surfaces simply have nothing to render. Emitting a `warn` /
   `fail` *solely because* an optional table is absent is a bug.

3. **Drift checks skip quietly when the declaration is absent.** A drift
   check (e.g. `stack-drift`) compares *declared vs detected*. With no
   declaration there is nothing to compare — return `pass` (or `warn`
   with "no declaration to drift from") rather than failing.

4. **Test plans cover the "neither table present" baseline.** Every PR
   that adds or touches an optional-table consumer ships at least one
   test that loads a minimal `lamill.toml` (just `schema` + `[deploy]`)
   and exercises the consumer's happy path. If that baseline isn't
   tested, the invariant isn't shipped.

5. **Schema string doesn't bump on additive-optional changes.** Adding
   an optional table is backward-compatible in both directions (old
   files parse; old readers ignore the new table), so
   `schema = "lamill-toml-v1"` stays. Bumping to v2 is reserved for
   genuinely breaking changes — the v27.A ADR captures this posture.

**Why this is load-bearing:** the fleet has 30+ sites and only a handful
will carry any given optional table at any given moment. Making a table
mandatory forces a fleetwide migration treadmill for every new piece of
metadata *and* breaks every old `lamill.toml` in unrelated tooling.
`lamill.toml` evolves additively — new tables surface new capabilities
without imposing them on files that don't need them yet.

**Self-check for any change touching `lamill.toml` consumers:** "If I
delete `[[todo]]` and `[stack]` (and any future optional table) from
every file in the fleet, does my code still work?" If no, the change
isn't ready.

### 🔒 `lamill.toml` `[[todo]]` shape (v27 — accepted 2026-05-29)

Per-site work tracker. Array-of-tables.

**Required fields:** `status` (`"done"` | `"open"`); `task` (non-empty
string).
**Optional field:** `priority` (`"high"` | `"medium"` | `"low"`) — only
valid on `open` items; `priority` on a `done` item is a `ParseError`.

The writer (`lamill_toml.write()`) regenerates a canonical `#` header
comment above the `[[todo]]` array on every round-trip:

```
# Tracked todos for <site>. status: "done" | "open".
# Optional context line about gating/conventions for this site.
```

Operator freeform comments above or inside the array are NOT preserved
verbatim — `tomli_w` doesn't carry them. If preserving them becomes
operator-felt friction, switch to `tomlkit` (deferred per v27 design
notes).

**CLI: plural symmetric** — `lamill project todos <domain>` and `lamill
fleet todos`. No singular form (`todo` reads as a mutation verb and
breaks the cross-scope symmetry rule).

**Why this is load-bearing:** todos are operator-authored content. The
writer's round-trip must preserve every item or `settings deploy set`
silently erases work. The field schema (especially `priority`-on-`open`-
only) is the contract every consumer reads against — `fleet focus`,
`project todos`, fleet aggregates.

See: ADR-0017 (additive-optional posture), `🔒 lamill.toml
additive-optional invariant` (above), `src/portfolio/lamill_toml.py`.

### 🔒 `lamill.toml` `[stack]` shape (v27 — accepted 2026-05-29)

Frontend-stack declaration. Single table (not an array).

**Required field:** `framework`, an enum:

```
astro · vite-react · tanstack · nextjs · sveltekit ·
wordpress · static · none
```

**Optional field:** `build_tool` (e.g. `vite` under astro/tanstack) —
free string for now; tighten to an enum later if it earns its keep.

**No operator-facing CLI.** `[stack]` is tooling-internal: `new
bootstrap` writes it from the detector, v27.C backfills it fleetwide,
the stack-aware checks (`CHECK_035 vite-version-ok` / `CHECK_036
astro-version-ok` / `CHECK_037 build-dev-scripts` / …) read it, and
`CHECK_xxx stack-drift` surfaces declared-vs-detected mismatches via
the existing `project check` / `fleet check` surfaces. Operators
inspect / edit the value by reading the file directly; declarations
change rarely enough that a dedicated `--stack` write verb hasn't
earned its keep.

**Why this is load-bearing:** today the frontend stack is re-inferred
in four places (`checks/stack/__init__.py` heuristics,
`bootstrap.detect_stack_from_pkg`, `stack_translate.detect_stack`,
`hosting.py` for WP-via-cPanel) with three different vocabularies
(`vite` vs `vite-react`, no `wordpress` constant outside hosting).
Declaration is the single source of truth — checks read it first, fall
back to the file-system heuristic only when absent (per the
additive-optional invariant).

See: ADR-0017 (additive-optional posture), `🔒 lamill.toml
additive-optional invariant` (above), `docs/prd.md` § v27.B/C/E,
`src/portfolio/lamill_toml.py`.

### v7.A — CLI restructure to scope-first (`project` / `fleet`) + `settings` *(SHIPPED — superseded by v14)*

> **Status: SUPERSEDED.** v7.A shipped 2026-05-10; v14.B (2026-05-20)
> further restructured the CLI — renamed `new suggest`→`new domain`,
> `new research`→`new validate`, folded `fleet info {summary,
> expiring}` into `fleet domains --summary/--expiring`, renamed
> `fleet info cleanup`→`fleet sync`, deleted `fleet info` subgroup,
> renamed `settings project`→`settings deploy` with trimmed verbs.
> See `docs/architecture.md § Projected CLI surface` for the current
> command tree and `docs/shipping-history.md § v14` for the design
> rationale. The content below is preserved as the original v7.A
> design record — do not edit; treat as archeology.

Aligned 2026-05-10 across two design sessions. Replaces the current
mixed-namespace tree with a scope-first model. `project` for ops on
one project; `fleet` for cross-portfolio. `info` group dies (its
members split: per-project status → `project check`; inventory views
→ `fleet info`). `check`-as-noun-with-modes goes away (each mode
becomes its own verb under the appropriate scope). `--all` and
`--domain` flags retire (scope is in the namespace, not the flag).

Setup / debug consolidates under a new `settings` top-level
(catalog, gsc, apikeys). Daily-ops users see four primary namespaces;
"everything else" lives under settings.

Final tree:

```
portfolio
├── project
│   ├── check <name>
│   ├── fix <name>
│   └── seo <name>
├── fleet
│   ├── focus
│   ├── live
│   ├── seo
│   ├── check
│   ├── fix
│   ├── drift
│   └── info             (inventory views — pragmatically grouped)
│       ├── summary      (--verbose replaces old `info list`)
│       ├── expiring
│       └── cleanup
├── new
│   ├── suggest
│   ├── bootstrap
│   └── deploy
└── settings
    ├── catalog
    │   ├── list
    │   ├── describe <id>
    │   └── run <path> <id>
    ├── gsc                  (simplified from auth/list/sync/compare)
    │   ├── auth
    │   └── status           (--refresh folds in old `sync`)
    └── apikeys              (NEW — replaces manual portfolio.env editing)
        ├── list             (names + set/not-set + connectivity tick)
        ├── set <key> <value>   (strict known-list; --force to override)
        └── delete <key>     (confirm; --yes to skip)
```

Rename map: `info status <name>` → `project check <name>`;
`check git --domain X` → `project check X --catalog-only`;
`check seo --domain X` → `project seo X`; `check git` → `fleet check`;
`check live` → `fleet live`; `check seo` → `fleet seo`;
`project fix --all` → `fleet fix`; `focus` → `fleet focus`;
`info summary` → `fleet domains --summary`; `info list` →
`fleet domains --summary --verbose`; `info expiring` → `fleet domains --expiring`;
`info cleanup` → `fleet sync`; `info drift` → `fleet drift`;
`check {catalog,describe,run}` → `settings catalog {list,describe,run}`;
`gsc auth` → `settings gsc auth`; `gsc list/sync/compare` →
`settings gsc status [--refresh]`.

`settings apikeys` design:
  - `list` — shape A (name + set/not-set) plus a connectivity tick
    per provider (✓ valid / ✗ failed / dim if not testable). Tests
    each provider's API on each call (OpenAI models.list, CrUX
    queryRecord, Porkbun ping, CF /user). Adds ~3-5s; the tradeoff
    is worth it for "did I paste the right key?" signal.
  - `set` — strict; only accepts known key names
    (OPENAI_API_KEY, PORKBUN_API_KEY, PORKBUN_SECRET_API_KEY,
    CF_API_TOKEN, CF_ACCOUNT_ID, CRUX_API_KEY). `--force` to
    accept arbitrary names. Atomic write (preserves other lines,
    comments, ordering of portfolio.env).
  - `delete` — confirms by default; `--yes` skips.

Phasing (single phase, all in):
  - **v7.A.1** (additive): new commands stand alongside old; both work
  - **v7.A.2** (deprecate): old paths become deprecation aliases
  - **v7.A.3** (docs + soak): cleanup, mark removal target = v8.A

Triggers to actually execute (none yet):
  - Muscle memory has shifted (you reflexively type the new shape)
  - A new per-project read command needs a home
  - A second contributor onboards
  - 6+ months pass without churn pressure

If none happen: leave it. Action plan in `check git --domain` already
bridges discoverability for the project-check half. `apikeys` is the
one piece that's net-new functionality — could carve as separate
phase if v7.A timing slips.

## Deferred decisions

Things deliberately *not* shipped — don't re-propose without new context.

### PageSpeed Insights / Lighthouse lab fallback for `check --seo`

CrUX returns `no-data` for personal-portfolio-scale origins (below the
~10k+ monthly Chrome-visits threshold). The empty LCP/INP/CLS columns
on `check --seo` are *expected*, not a tool problem. The footer message
explains this clearly.

Considered: adding a `--lab` flag that calls PageSpeed Insights to run
Lighthouse synthetically against any URL regardless of traffic.

Rejected because:
  - ~15–30s per origin × ~22 domains ≈ 5–10 min per run; makes
    `check --seo` feel heavy.
  - Lab data ≠ field data Google actually ranks on. Synthetic numbers
    would mislead more than help.
  - `check --git`'s static-source SEO category already surfaces what's
    actionable without traffic.

Don't reopen unless: user explicitly asks for synthetic metrics, or a
use-case for them appears (e.g. comparing pre-deploy performance
across staged builds where field data is unavailable by definition).

Decision date: 2026-05-09 (after v5.D shipped).
