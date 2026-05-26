# shipping-history.md — sites/portfolio/

**Archived design rationale for shipped phases.**

Companion to `docs/prd.md` (current spec) and `docs/architecture.md`
(current mechanisms). This document is **append-only** — entries are
moved here when a phase ships, never deleted.

Entry format:

```
## vN.X · <theme> — shipped YYYY-MM-DD
### Problem
### Design rationale
### Resolved open questions
### User journey
### Approval
```

Listed reverse-chronologically (newest first).

> **Entries marked `(TBD — migrate from prd.md)` need content moved
> over from the corresponding detailed-PRD body in the legacy `prd.md`.**

---

## v26.A-B — fleetwide canonical-redirect conformance — shipped 2026-05-25

### Problem

homeloom.app's apex returned a 307 (temporary) redirect to www. GSC's URL Inspection refused to index either variant — Google holds signal-transfer indefinitely on temporary redirects, so the apex stayed uncanonicalized AND the www target inherited no rank. The homepage was non-indexable until the redirect type flipped.

The shape was structurally likely to recur as the fleet grows: Vercel and other PaaS providers expose apex/www and 307/308 as separate dashboard controls with operator-friendly-but-SEO-suboptimal defaults. A fleetwide audit (see `docs/bugs.md` 2026-05-25 entry) confirmed 29 of 35 probed sites were non-conforming on the same axis — making this a fleetwide check candidate, not a per-site fix.

### Design rationale

**Why apex as canonical (vs www).** Three reasons aligned with the existing fleet shape and SEO best practices:

  1. **Matches the existing fleet default.** CF Pages and CF Workers serve the apex natively; most sites already land on apex.
  2. **HSTS preload requires apex.** Future preload-list submission can't be done meaningfully with a www-canonical site.
  3. **Single canonical = single signal pool.** Apex consolidates onto the shorter / cleaner share URL; Google treats apex vs www identically for ranking, so the marketing axis breaks the tie.

**Why 308 specifically (vs 301).** Both 301 and 308 are permanent redirects; Google treats them identically for SEO signal transfer. The check accepts BOTH as pass. Refusing 307/302 is the actual gate — those are temporary and hold signals back.

**Why scope-narrow (no HSTS / trailing-slash / canonical-tag check).** v26 covers ONE network-behavior axis (redirect-chain status codes + targets). Folding in HSTS preload status or trailing-slash policy would overload one check ID; separate checks at separate IDs are cleaner to audit, fix, and report on independently.

**Why warn-then-fail (not fail from day one).** Per the global `feedback_quick_idempotent_default_over_blocking_waits.md` posture and the v25 dropaudit.co lesson: a new failing check that flips the fleet dashboard red overnight is operator-hostile, even when the finding is legitimate. The warn cycle gives the operator one soak window to audit, plan fixes per affected domain, and ship them calmly. Promoting to `fail` in v26.C is a one-line change once the fleet is clean.

**Why httpx (not requests as the v26.A spec said).** Inspection during v26.B revealed `seo/_live.py` already uses `httpx` for its runtime SEO probes. Aligning CHECK_150 on the same library was free; switching to `requests` would have introduced a second HTTP client dependency for zero gain. v26.A's mention of `requests` is preserved as an authored-as-spec quirk rather than retconned.

### Decisions locked in v26.A

  - (a) Canonical = apex (the bare domain); www-as-canonical is non-conformant.
  - (b) Required redirect type = 308 OR 301; 307/302 fail.
  - (c) HTTP→HTTPS is in scope of the same check.
  - (d) Trailing-slash policy is OUT of scope (separate check, separate future tier).
  - (e) HSTS preload is OUT of scope.
  - (f) www NXDOMAIN = pass (no www = no possibility of split-canonical).
  - (g) Severity ramp: ship at `warn` for the soak cycle (v26.B); promote to `fail` in v26.C after offenders are fixed.
  - (h) Check ID = 150 (next available; previous high was CHECK_149).
  - (i) Category = `seo/` (runs as part of `fleet seo` / `project seo`).
  - (j) No ADR required — the convention itself goes in `docs/CLAUDE.md § Locked target shapes` after v26.C lands.

### Conformance checks added

  - `CHECK_150` (`seo` / `apex-canonical-redirect`, severity `warn`) — three HEAD probes per domain (`https://<apex>/`, `https://www.<apex>/`, `http://<apex>/`), classifies the redirect chain against the v26.A rules. ~3 HEAD requests per repo; flaky-network resilient (apex unreachable → `warn` skip; www unreachable → pass-as-no-www).

### Tests

  - `tests/test_check_150_apex_canonical_redirect.py` — 15 cases, `httpx.MockTransport`-stubbed. Covers every bucket from the 2026-05-25 audit (Bucket A homeloom.app pattern, Bucket B 308-wrong-direction, Bucket C split + no-HTTPS, Bucket D HTTP-200, Bucket E unreachable) plus the skip paths (archived sites, non-domain dirs, metadata-constants sanity).

### Per-phase commits

  - `v26 — canonical-redirect spec + audit baseline (29/35 fail)` — 705896e
  - `v26.B — ship CHECK_150 at warn severity` — TBD

### Open follow-ups (not gated on this tier)

  - v26.C — fleetwide audit + fix offenders + promote `CHECK_150` to `fail`. Bucket A (5 Vercel sites) is the highest-leverage operator action; deferred to operator-pace dashboard work.
  - Once v26.C lands, add the apex-canonical + 308-permanent invariant to `docs/CLAUDE.md § Locked target shapes`.

---

## v16 — GSC fleet-level intelligence (v16.A-D) — shipped 2026-05-20

### Problem

v13.B (per-project GSC diagnostics) gave the operator a per-domain
diagnostics block — sitemaps + per-URL coverage + hints. Two adjacent
gaps remained:

  * **Per-URL coverage wasn't a binary conformance signal.** v13.B
    rendered the data; `project check` didn't fire a fail when
    Google had stopped indexing a sitemap-submitted URL. A
    `crawled_not_indexed` URL is a silent ranking failure — invisible
    to every other check.
  * **GSC's web UI is one-property-at-a-time.** Operator with
    20+ sites couldn't easily ask "across all my properties, what
    are the top queries? where are the page-2 opportunities? which
    sites have the worst index coverage?" GSC's data is there;
    aggregation isn't.

### Design rationale

Three threads:

  1. **Cache-first** — every per-domain GSC fetch (v13.B sitemap
     details, v16.C URL Inspections, v16.B query/page dim data) writes
     to the same `data/gsc/<domain>/<UTC-today>.json` cache (the v13.B
     file). v16.B/C/D layer their data into new sections of the same
     JSON. Single read-side aggregation (`gsc_rollup.py`) reads any
     section that's there, gracefully degrades when sections are
     absent (renders `—` in dashboards).
  2. **Binary check, not chart-rendering** — v16.C's `CHECK_147
     url-indexed` is a pass/fail conformance assertion, not a rich
     UI. The pass condition (`coverageState ∈ {"Submitted and
     indexed", "Indexed, not submitted in sitemap"}`) matches GSC's
     actual API response strings — the v13.B-era assumption that the
     API returned enum-style tokens (`submitted_indexed`) was wrong
     and got logged as a bug 2026-05-20.
  3. **Fleet aggregation = the actual unique value** — single-property
     dim views (queries / pages / devices / trend / opportunities)
     were dropped in the 2026-05-20 audit because GSC's web UI
     already does them well. What it CAN'T do is aggregate across
     properties. v16.D ships only the cross-property summaries.

### Locked → as-shipped deltas

  * **v16.D's `W/w impressions Δ` column** was dropped from the
    `fleet dashboard` row in this tier — it needs comparing across
    multi-day snapshots, and the per-domain GSC cache (introduced
    in v13.B) only has the current-day snapshot. Will land once
    snapshot history exists.
  * **Cache-population hook on `project seo`** wasn't added in v16.D
    — gsc_rollup ships the *read* side; the *write* side
    (populating `v16b_queries`/`v16b_pages` per-domain) is a
    follow-up. Most dashboard columns render `—` until per-domain
    caches are filled in.
  * **Test file name `tests/test_v16c_bootstrap_owned_domain_check.py`**
    is misleadingly tagged v16.C — the bug fix it covers is
    unrelated to v16 (bootstrap-side, not GSC-side). Background
    agent named it that way because the fix happened during v16
    work. Worth renaming in a future cleanup.

### Conformance checks added

  * **CHECK_147 `url-indexed`** (deploy/warn) — fetches the live URL's
    top-N pages ranked by GSC impressions (sitemap fallback for
    zero-imp), runs `urlInspection.index:inspect` on each, fires
    `fail` when any URL is in a non-indexed `coverageState`. Cache-
    aware; mobile-usability data renders but doesn't trigger fail.

### CLI surface added

  * **`fleet dashboard`** gains 3 columns: `Cov %`, `Crawl-err`,
    `P2-opp` — read from per-domain GSC cache; render `—` when
    absent.
  * **`fleet seo --detail`** — appends three fleet-aggregated
    sections (🔎 Top queries, 📄 Top pages, 💡 Page-2
    opportunities) below the per-site table. Sections render
    "(empty)" when no domains have cached GSC data yet.
  * **`gsc.query_with_dims(service, site_url, *, dimensions, row_limit)`**
    — dimension-aware searchAnalytics wrapper. Internal API used by
    v16.C and the future cache-populator.
  * **`gsc_rollup` module** — read-only fleet aggregation helpers.
    Internal API; powers the dashboard columns and `fleet seo
    --detail`.

### Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 16.A | URL Inspection cap — bound the per-day quota burn how? | Top-N pages from sitemap, ranked by GSC impressions desc with alphabetical fallback (default top 10). 2000 URL-Inspection calls/day; a 30-site fleet sweep at top-10 = ~300 calls. |
| 16.B | Per-project GSC cache TTL? | 24h default, matches `hosting_cache` / `seo_cache`. GSC's 2-3 day publishing lag dominates. |
| 16.C | Cache directory shape? | Per-domain subdir `data/gsc/<domain>/<UTC-today>.json` — already adopted in v13.B's `gsc_detail_cache.py`. |
| 16.D | Fleet-aggregated views — single `--detail` flag or compositional section flags? | Single `--detail` flag. Coherent unit; simpler flag surface. |
| 16.E | CHECK_147 failure semantics — indexing only or also mobile usability? | Indexing only. One assertion per CHECK_NNN. Mobile-friendliness could be a separate check later. |

### Parked / deferred

  * **Cache-population hook** (writing `v16b_queries`/`v16b_pages`
    per-domain) — add to `project seo` as either a side effect or a
    new `--populate-cache` flag.
  * **`W/w impressions Δ` dashboard column** — needs snapshot history;
    revisit once per-domain caches accumulate multiple days' worth.
  * **`--refresh` flag wiring** on `fleet seo --detail` — currently
    reads cache only; doesn't refetch. Add when cache-population
    hook lands.
  * **Stretch goal: `project seo --coverage`** flag that supersedes
    v13.B's existing top-10 block with full v16.C URL Inspection
    detail — operator-facing nice-to-have, not in v16 tier scope.

### User journey

```
$ lamill project check airsucks.com
…
  ✗ url-indexed     8/10 top URLs indexed · 2 non-indexed:
                    /old (Crawled - currently not indexed);
                    /gone (Not found (404)).

$ lamill fleet dashboard
 Domain               …   Cov %   Crawl-err   P2-opp
 airsucks.com         …    80%        2          —    (no page cache yet)
 lamillrentals.com    …      —        —          —    (no v16c cache)
 homeloom.app         …    75%        3          5

$ lamill fleet seo --detail
…<per-site table>…

🔎 Top queries (fleet-aggregated, 28d) (empty — no cached query data)
📄 Top pages (fleet-aggregated, 28d) (empty — no cached page data)
💡 Page-2 opportunities (fleet-summed) (empty — no qualifying pages...)
```

### Approval

2026-05-20 — operator-driven design pass + same-day implementation
across all four sub-phases. v16.A kickoff in the morning;
v16.B/C/D shipped in one bundled commit late afternoon. Hard cutover
on dropped per-property single-site dim views. Suite stayed green
throughout (2303 → 2347; net +44 tests across the tier + an unrelated
bootstrap typo-validation fix that ran in parallel).

### Per-phase commits

  * **v16.A** (`c56e390`) — Kickoff planning, five locked decisions.
  * **v16.B/C/D** (`738d14c`) — Bundled implementation. Also
    includes the unrelated bootstrap typo-validation bug fix and
    the porkbun.csv refresh (4 newly-added domains).

### Operational follow-ups (not gated on this tier)

  * Populate per-domain GSC analytics cache (run `project seo` per
    site, or wait for a cache-population hook in a follow-up phase).
  * Once snapshot history accrues, add the `W/w impressions Δ`
    dashboard column that was deferred.
  * Rename `tests/test_v16c_bootstrap_owned_domain_check.py` →
    `tests/test_bootstrap_owned_domain_check.py` (the v16c prefix
    is misleading; the fix is unrelated to v16.C).

---

## v15.G-J addendum — deploy pipeline rewrite — shipped 2026-05-20

Same-day extension of v15. v15.A-F (deploy *verification*) wrapped
earlier; the operator's testing surfaced a deeper need —
**deploy itself** for cf-workers/cf-pages was split between two
divergent paths (`_deploy_cf_pages_v3c()` for git-integrated CF Pages;
`_deploy_cf_workers()` for `wrangler deploy` one-shot). The split was
a mismatch with the operator's actual fleet (all 6 CF sites are
git-integrated). v15.G-J unifies them.

### Problem

Two adjacent gaps:

1. **`new deploy` for cf-workers didn't do CD.** It ran `pnpm run
   deploy` → `wrangler deploy` as a one-shot. Future re-deploys
   required either re-running the command or hand-wiring GitHub
   Actions. Inconsistent with cf-pages (which got git-integrated
   CD on first deploy).

2. **`agesdk.dev` came in as TanStack Start** (via Lovable's
   default export). The operator's "Astro + Vite only" policy
   wasn't enforced — `_copy_from_genai()` blindly copied any stack
   verbatim to root. Without policy, every Lovable export quirk
   surfaced as a per-project edge case.

### Design rationale

Three threads:

1. **Unify CF deploys onto one Pages-API pipeline.** CF unified
   Workers + Pages in 2024-2026 (same dashboard, same API surface
   for git-integrated builds). The `/accounts/{id}/pages/projects`
   endpoint serves both static Pages and Workers Static Assets
   projects with `source.type=github`. No `wrangler` involvement
   needed; CF builds in its infrastructure on push.

2. **Astro+Vite as the stack policy** for `sites/*`. The v3.A blank
   template already produces this shape; the gap is `--git-url`'s
   blind-copy behavior. Solution: spawn `claude` subprocess to
   translate non-Astro repos. Same Tier-2-fixer pattern as ADR-0006.

3. **No new commands.** Everything happens under `new deploy`. No
   `project migrate-platform <domain>`, no `cf zone create`. The
   pipeline is idempotent at every step, so re-running on a partially-
   deployed site picks up where it left off.

Two ADRs codify these:
  - **ADR-0012** — No `wrangler deploy`; git-integrated CF Pages-API
  - **ADR-0013** — Astro+Vite only stack; Claude-subprocess translation

### Locked → as-shipped deltas

  * **v15.H translation budget**: locked at `$0.50` default; operator's
    `agesdk.dev` (real-world TanStack→Astro) hit `error_max_budget_usd`
    after 22 turns / $0.524. Default needs bumping; budget-flag
    addition logged in `docs/bugs.md` as v15.K candidate.
  * **Failure rollback**: v15.H added the translation step but didn't
    add `shutil.rmtree(project_dir)` on `StackTranslationError`. v15.G
    plan didn't call this out explicitly; operator surfaced it in
    testing. Logged in `docs/bugs.md` as v15.K candidate too.
  * **`_deploy_cf_pages_v3c()` + `_deploy_cf_workers()` deletion**:
    v15.I planned to "delete and replace"; shipped as
    "leave-as-dead-code". Safe to clean up later; not a functional
    issue.

### CLI surface added

  * **`new deploy --yes`** — auto-confirm NS update at registrar.
    Non-interactive mode for CI/scripts.
  * **Bootstrap default platform**: `cf-pages` → `cf-workers` (per
    ADR-0012). Existing `lamill.toml`s with `platform = "cf-pages"`
    still work — they route through the same unified pipeline.

### Conformance checks added

None. v15.G-J is plumbing, not assertion.

### Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 15.G.1 | Migrate the 5 existing cf-pages sites? | Leave as-is. They already match the new model (git-integrated, same Pages-API). Relabel optional. |
| 15.G.2 | airsucks.com (cf-workers TanStack)? | Leave. Predates the Astro-only policy. |
| 15.G.3 | What does `new deploy` do when CF GitHub App isn't installed? | Pre-flight detects via the `pages/projects` create response; surface a clear "install once at <dashboard URL>" message + exit. |
| 15.G.4 | Multi-stack support pathway? | New ADR per stack. Don't pre-bolt N-stack scaffolding into v15.H. |
| 15.G.5 | TanStack server.ts translation? | Drop with `TODO:` markers in `src/lib/server-todo.md`. Operator hand-ports server logic outside the translation. |

### Parked / deferred (logged in `docs/bugs.md`)

  * **Failure-rollback for all `new` commands** — major. Operator
    hit this on `agesdk.dev`. v15.K candidate.
  * **Translation budget cap** — bump default + add `--budget` flag.
  * **`genai/node_modules` Docker-ownership** — `shutil.rmtree` from
    host can't delete Docker-created files. Needs best-effort skip
    or Docker exec.
  * **Old `_deploy_cf_pages_v3c` / `_deploy_cf_workers` cleanup** —
    safe to delete; left in tree for now.

### User journey

```
# Fresh bootstrap from a Lovable TanStack export:
$ lamill new bootstrap agesdk.dev --git-url git@github.com:user/lovable-ui.git
About to bootstrap agesdk.dev. You'll be asked 9 questions: ...
<smart-paste 9-section response>
genai/ stack is `tanstack-start` (...); translating to Astro+Vite
via Claude subprocess (ADR-0013)...
[Claude runs ~$0.20-0.50 for translation]
v15.H validator: ✓ astro dep + astro.config + src/pages + no banned
Bootstrap complete.

# Then deploy end-to-end:
$ lamill new deploy agesdk.dev
v15.I — Deploy agesdk.dev (platform=cf-workers · git-integrated CF Pages-API)
0. Pre-flight     ✓ CF creds · ✓ GitHub auth via token · ✓ Porkbun creds
1. GitHub repo    ✓ created: codervijo/agesdk-dev (public, default_branch=main)
2. Git push       ✓ pushed local commits to origin/main
3. CF zone        ✓ created: agesdk.dev (status=pending)
                  Cloudflare NS: dom.ns.cloudflare.com kristina.ns.cloudflare.com
4. Registrar NS   porkbun · NS mismatch · Update NS at Porkbun? [Y/n]: Y
                  ✓ NS updated at Porkbun
5. CF Pages       ✓ project agesdk-dev created (source=codervijo/agesdk-dev@main)
6. Custom domain  ✓ agesdk.dev attached to agesdk-dev
7. Build poll     · queued: idle · build: active · deploy: success
                  ✓ build complete — deployment a1b2c3d4
8. Live probe     ↷ 0 — likely NS propagation in flight, re-probe in 5-30 min

Deploy complete. https://agesdk.dev/ should resolve once DNS + SSL settle.
```

### Approval

Operator-driven across one session 2026-05-20. v15.G kickoff
locked 6 decisions; v15.H built stack-translation; v15.I built the
deploy pipeline; v15.J wrapped docs. Two ADRs written + decisions/
README.md indexed. Suite stayed green throughout (+74 new tests:
26 stack_translate + 48 unified deploy).

### Per-phase commits

  * **v15.G** (`ad8739d` + `152897b`) — Doc plan + ADRs + ✅ mark.
  * **v15.H** (`2ac4d21`) — Stack translation via Claude subprocess.
  * **v15.I** (`fde446c`) — Unified deploy pipeline (gh_repo +
    porkbun_dns + extended cloudflare + `_deploy_cf_unified`).
  * **v15.J** — This commit (docs wrap).

### Operational follow-ups (not gated on this tier)

  * Set `GITHUB_TOKEN` via `lamill settings apikeys set GITHUB_TOKEN
    <pat>` (or have `gh auth login` done — fallback works).
  * Install Cloudflare GitHub App at
    `https://dash.cloudflare.com/?to=/:account/workers-and-pages/
    create/connect-to-git` (one-time per CF account).
  * `agesdk.dev` re-bootstrap pending — operator's last attempt hit
    the budget cap; v15.K should fix that before retry.

---

## v15 — deploy verification (v15.A-F) — shipped 2026-05-20

### Problem

After v11's read-only hosting walker shipped (Vercel + CF Pages +
CF Workers + HostGator), the operator could see deploy state across
the fleet — but only at the platform level. Two adjacent gaps
remained:

  * **Deploy freshness was invisible.** A site could look "deployed"
    via `fleet hosting` while the live build was three commits
    behind local HEAD. No way to detect that drift from the CLI;
    operator had to manually visit the site or compare commit SHAs
    in the platform UI.
  * **Build-success was hidden in a column most users skim past.**
    The existing `Failures` column on `fleet hosting` showed
    consecutive-build-failure counts but didn't fail-grade a site
    at the per-project conformance layer.

Plus an unrelated one v14 absorbed:

  * **Registrar CSV churn.** `fleet sync` ran the merge but the
    Porkbun CSV had to be manually re-exported when ownership
    changed. No live-pull option.

### Design rationale

Five threads:

  1. **Build artifact convention** (v15.C) — every Vite-based
     `sites/*` build emits `dist/version.json` with `{schema, commit,
     built_at}`. Plugin source canonical at `~/work/projects/builder/
     vite-version-stamp.ts`; sites *inline a copy* in their own
     `vite.config.{ts,js,mjs}` because CF Pages + Vercel build
     environments clone only the site repo (no symlinked or shared
     plugin file). One-time per-site cost; protects every
     downstream check.
  2. **Per-site verb symmetry** (v15.B) — `project hosting <domain>`
     restored the `project X ↔ fleet X` shape that v14.B already
     enforces for `check`, `seo`, `fix`. `fleet hosting --only`
     was a fleet verb pretending to be per-project; hard cutover.
  3. **Read-side helper centralization** (v15.D) — `version_stamp.py`
     owns `/version.json` fetch + parse + HEAD-vs-live comparison;
     CHECK_144/145/146 + the project-hosting renderer all read
     from one place.
  4. **No new platform infra** (v15.E) — `last-build-success`
     reads the `fleet hosting` snapshot's `latest_deploy_status`.
     Folding rather than adding new API tokens / clients.
  5. **Light watch tooling** (v15.F) — mtime polling instead of
     a `watchdog` dependency. Good enough for CSV-edit cadence;
     the simplest thing that works.

### Locked → as-shipped deltas

A few decisions resolved differently between v15.A kickoff and the
v15.E ship:

  * v15.A locked: "v15.E adds a `Last build` column to `fleet
    hosting` + a `Last build` row to `project hosting`." 
    Shipped: **neither** — both surfaces already showed the signal
    via the existing `Deploy state` / `Last Success` / `Failures`
    columns and the 📦 Deploy block respectively. Adding dedicated
    framing would duplicate the same data. Operator can revisit.
  * v15.A locked: "v15.E folds into the `_fleet_hosting_impl`
    walker via a `last_build_success: bool` field on `HostingRow`."
    Shipped: **derived live in CHECK_146 from the existing
    `latest_deploy_status` field** rather than added as a new
    HostingRow field — equivalent signal, no schema churn.
  * v15.A locked: "`--watch` uses `watchdog`." 
    Shipped: **mtime polling at 2s default interval** — avoids
    the new dependency for a feature whose cadence doesn't need
    real-time fidelity.

### Locked target shape (post-v15.B)

`lamill project hosting <domain>` renders:

```
$ lamill project hosting airsucks.com

  Property: airsucks.com  ·  platform: cloudflare-workers
  Account: vijo  ·  branch: main

  📦 Deploy           (v15.B)
    ✓ DEPLOYED       2026-05-19 08:34 (12h ago)
    Commit:          a693d96
    Deploy ID:       abc-123

  📋 Freshness        (v15.D)
    HEAD @           a693d96
    Live @           a693d96    ✓ in sync

  📌 Domains          (v15.B)
    airsucks.com (canonical)
```

### Conformance checks added

  * **CHECK_144 `has-version-stamp`** (deploy/warn) — fetches
    `/version.json`, validates shape. Fails on 404 / non-200 /
    non-JSON / missing fields. Warns on transport errors.
  * **CHECK_145 `deploy-fresh`** (deploy/warn) — compares local
    HEAD to live commit. Fails on drift; warns when one side
    undetermined.
  * **CHECK_146 `last-build-success`** (deploy/warn) — reads the
    `fleet hosting` cache. Passes on READY/SUCCESS/ACTIVE; fails
    on ERROR/CANCELED with consecutive-failures count; warns on
    in-flight or provider-has-no-build-pipeline.

### CLI surface added

  * `lamill project hosting <domain>` — new per-project verb.
  * `lamill fleet hosting --only <domain>` — **removed** (hard
    cutover; symmetry-restoring).
  * `lamill fleet sync --refresh` — Porkbun live pull.
  * `lamill fleet sync --watch [--interval N]` — mtime watcher.

### Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 15.A.1 | `project hosting <domain>` layout — table or vertical sections? | Vertical sections — matches v13.B's `project seo` GSC-diagnostics pattern. |
| 15.A.2 | v15.E source — new platform-API infra or fold into existing walker? | Fold into existing walker. Derived live in CHECK_146 rather than added as a HostingRow field. |
| 15.A.3 | v15.F flag wiring — both `--refresh` + `--watch`? | Both shipped. `--watch` uses mtime polling (no `watchdog` dep). |
| 15.A.4 | Execution order | Sequential A→B→C→D→E→F. |
| 15.B.1 | Plugin distribution — published npm package, shared file, or inline? | Inline source in each site's vite.config. Canonical reference at `~/work/projects/builder/vite-version-stamp.ts`. |

### Parked / deferred

  * **Per-site rollout of the v15.C inline plugin.** Only
    `airsucks.com` got the inline plugin in this tier. Remaining
    12 vite-config sites need the same edit + a redeploy before
    CHECK_144 passes. Operational follow-up, not a phase.
  * **GoDaddy + Namecheap `--refresh`.** Both need their account-
    side API setup before `fleet sync --refresh` can pull them.
    Porkbun is the only registrar with a working pull today.
  * **Vendoring the v15.C plugin as a published npm package
    (`@lamill/version-stamp`).** Would simplify per-site updates
    once drift becomes a real cost. Currently inline-per-site is
    fine for a one-operator fleet of ~13 vite sites.
  * **Dedicated `Last build` column on `fleet hosting` and 🔧
    Build section on `project hosting`.** Skipped because the
    existing surfaces already carry the signal. Revisit if a
    different framing proves valuable.

### User journey

```
# Before v15: operator knows the site is "deployed" but not whether
# it's the latest commit or whether the last build succeeded.

# After v15:

$ lamill project check airsucks.com
…
  ✓ has-version-stamp      version.json served · commit a693d96 · built 2026-05-20T...
  ✓ deploy-fresh           HEAD matches live · a693d96
  ✓ last-build-success     last build READY · 2026-05-20T08:31:00+00:00

$ lamill project hosting airsucks.com
  <renders 📦 Deploy + 📋 Freshness + 📌 Domains>

$ lamill fleet sync --refresh
  Porkbun listAll → data/domains/porkbun.csv ...
  ✓ wrote 54 rows to porkbun.csv
  <continues with the regular merge>

$ lamill fleet sync --watch
  Watching data/domains/ for CSV changes (interval=2.0s) — Ctrl-C to exit.
  <runs continuously, re-merging on change>
```

### Approval

2026-05-20 — operator-driven design pass + same-day implementation
across all six sub-phases (v15.A kickoff in the morning; v15.B
shipped mid-day; v15.C-F shipped late afternoon). Hard cutover for
the `--only` removal. Suite stayed green throughout (2261 → 2303,
net +42 tests across the tier).

### Per-phase commits

  * **v15.A** (`e3f4e28`) — Kickoff planning, four locked decisions.
  * **v15.B** (`39a52bf`) — `project hosting` verb + drop
    `fleet hosting --only`. 11 new tests; suite 2251 → 2261.
  * **v15.C** (`d594a6b`) — build-time stamping convention +
    CHECK_144. Paired with builder repo commit `53a09d8`
    (canonical plugin source). 14 new tests; suite 2261 → 2275.
  * **v15.D/E/F** (`7c4736e`) — bundled three sub-phases:
    CHECK_145 + 📋 Freshness section · CHECK_146 · `fleet sync`
    `--refresh` / `--watch` flags. 28 new tests; suite 2275 → 2303.

### Operational follow-ups (not gated on this tier)

  * Inline the v15.C plugin in the remaining 12 vite-config sites:
    `civictools.app`, `cricketfansite.com`, `csinorcal.church`,
    `homeloom.app`, `isitholiday.today`, `keralavotemap.site`,
    `kwizicle.com`, `lamill.io`, `lamillrentals.com`, `levents`,
    `voltloop.site`, `washcalc.app`. Each needs the same vite.config
    edit pattern as `airsucks.com` (commit `90a5f9e` in that
    repo's git).
  * Redeploy each migrated site so `/version.json` actually
    appears on the live URL.
  * Run `lamill project check` per site to verify CHECK_144 /
    CHECK_145 / CHECK_146 land green.

---

## v14 — CLI rethink after drift (v14.A-C) — shipped 2026-05-20

### Problem

The v7.A scope-first design (`project` / `fleet` / `new` /
`settings`) was locked 2026-05-10 and shipped across v7.A.1-3.
Between then and v13, the CLI accreted nodes opportunistically —
`fleet hosting`, `fleet dashboard`, `fleet domains`, `fleet repos`,
`settings operator`, `settings cloudflare`, `settings serpapi-quota`,
`settings project`, `gsc recrawl` — without re-validating against
the v7.A intent.

By 2026-05-20 the drift was visible enough to warrant a tier:

  * `settings project` collided with the top-level `project` group
    (same word, different scope) — the worst offense.
  * `fleet info cleanup` was a write surface (rebuilds
    `data/portfolio.json` from CSVs) misplaced under a read-only
    inventory subgroup.
  * `fleet live` (v7.A canonical) had silently disappeared, its
    function moved into `fleet domains`, leaving the inventory-style
    name attached to a runtime-probe verb.
  * Several v7.A.2 deprecation aliases (`info status`, `check git`,
    etc.) had been stripped without records.
  * `new suggest` and `new research` were method-described
    (suggest a domain by brainstorming; research SEO) rather than
    intent-described (find a domain; validate winnability).

### Design rationale

Audit + re-alignment, not a rewrite. Two principles:

  * **Hard cutover.** Operator's own tool, no third-party consumers;
    deprecation aliases would accrue rot faster than muscle memory
    would adapt. Old paths return typer's standard "no such command"
    after v14.B — no nudges, no forwarders.
  * **Verbs say what to do; the namespace says where you are.**
    `settings deploy set` rather than `settings deploy set-deploy`
    (redundancy). `set-launched` retained its compound form because
    it's the lone outlier in the subgroup; rename it later if a
    sibling lifecycle verb appears.

The `fleet domains` flag-overload (`--summary` / `--expiring N`) was
the most-debated piece. The operator confirmed `fleet domains` is
the right noun-group container — different flag-views of the fleet
*at the domain level* — and approved the mode-switching design over
a separate inventory subgroup.

### Locked tree

See `docs/architecture.md § Projected CLI surface` for the current
shape with phase annotations.

### Migration map (8 renames)

| Today | After v14.B |
|---|---|
| `new suggest <topic>` | `new domain <topic>` |
| `new research <topic>` | `new validate <topic>` |
| `fleet info summary [--verbose]` | `fleet domains --summary [--verbose]` |
| `fleet info expiring N` | `fleet domains --expiring N` |
| `fleet info cleanup [--refresh-rdap]` | `fleet sync [--refresh-rdap]` |
| `settings project set-deploy <d> <p>` | `settings deploy set <d> <p>` |
| `settings project show-deploy <d>` | `settings deploy show <d>` |
| `settings project set-launched <d>` | `settings deploy set-launched <d>` |

### Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 14.A | Verb trim under `settings deploy`? | Trim `set-deploy`→`set`, `show-deploy`→`show`. The subgroup already carries the noun. |
| 14.B | Where does `set-launched` belong long-term? | Stays under `settings deploy` despite mild lifecycle-vs-deploy mismatch. Revisit if a 2nd lifecycle verb appears (then split into `settings lifecycle`). |
| 14.C | Cutover style — deprecation aliases or hard? | **Hard cutover.** Single operator, daily-driver workflow adjusts in days. |
| 14.D | Free `fleet domains` slot for inventory flags, or move inventory elsewhere? | Operator confirmed `fleet domains` is the right noun-group container. Mode-switch via flags. |

### Parked for v14+

  * **Data/cache namespace promotion** — `fleet sync` is one step;
    long-term may become `lamill data sync` with sub-verbs per
    source (registrar / gsc / crux / serpapi / cloudflare / vercel).
    Observe `fleet sync` usage first.
  * **Settings split** (`settings creds` vs `settings status`) —
    currently mixes credentials with status views. Worth splitting
    later or promoting status verbs to top-level `lamill status`.
  * **`fleet repos` vs `fleet check` fold** — either `repos`
    becomes `check --git`, or `repos` renames to `fleet git-status`.
    Revisit at v14+ if overlap creates real friction.

### User journey

Before:

```
$ lamill new suggest "ev charger"        # find a domain
$ lamill new research "ev charger"       # validate winnability
$ lamill fleet info summary --verbose    # portfolio rollup
$ lamill fleet info expiring 90
$ lamill fleet info cleanup
$ lamill settings project set-deploy airsucks.com cf-pages
```

After:

```
$ lamill new domain "ev charger"
$ lamill new validate "ev charger"
$ lamill fleet domains --summary --verbose
$ lamill fleet domains --expiring 90
$ lamill fleet sync
$ lamill settings deploy set airsucks.com cf-pages
```

Same workflows, intent-described verbs, no namespace collisions.

### Approval

2026-05-20 — operator-driven design pass + same-day implementation
across all three sub-phases. Hard cutover committed; suite stayed at
2251 passed / 1 skipped throughout.

### Per-phase entries

  * **v14.A — kickoff planning** (doc-only commit `b493468`).
    Locked the target tree from the 2026-05-20 design pass. Three
    decisions resolved: trim verbs, keep `set-launched`, hard
    cutover. Captured migration map + parked items in `prd.md §
    v14 #### Design notes`.
  * **v14.B — apply renames + namespace moves** (`41004e5`, 28
    files). Wired the locked tree into `cli.py`; folded `fleet info
    summary/expiring` into `fleet domains` flags with mutual-exclusion
    guard; deleted the `fleet_info_app` typer; renamed
    `settings_project_app`→`settings_deploy_app`; swept
    `menu.py` CmdSpec entries + every test + every help string +
    check messages + bootstrap hints + diagnose root-cause text.
    No deprecation aliases.
  * **v14.C — docs sync** (this commit). Rewrote
    `architecture.md § Projected CLI surface` with the v14.B-shipped
    tree + planned-by-phase annotations. Marked the v7.A locked-
    target-shape section in `CLAUDE.md` as superseded (preserved as
    archeology). Updated `AI_AGENTS.md` capability lines + usage
    examples. Migrated v14 design notes from `prd.md` to this
    entry. Phase-table rows in `prd.md` updated to reflect new
    names where they describe planned/active work; historical
    entries (v7.A, v8.A, v10.B) annotated rather than rewritten.

---

## v12 — adversarial audit pass + reconciliation (v12.A-G) — shipped 2026-05-17 → 2026-05-19

The full v12 tier shipped across three days. v12.A (audit prompt
rendering) landed 2026-05-17 alongside v8.J (audit payload builder)
as the foundation for the audit arc. v12.B-G shipped 2026-05-19 in
a single session — parser, runner, reconciliation, CLI wiring +
renderer, polish (cost ledger / `verify_by_default` / granular
invalidate), and this docs sync.

End-state: `lamill new research <topic> --verify` runs the primary
interpretive pass (Claude CLI subprocess) **and** the adversarial
audit pass (OpenAI gpt-4o by default; configurable via
`--audit-model`). The two model verdicts are reconciled into a
final verdict + confidence the operator sees:

  * **Full agreement** → primary's verdict + confidence preserved.
  * **Partial agreement** → primary's verdict kept, confidence
    downgraded one notch (HIGH→MEDIUM→LOW→LOW saturates), caveats
    from the audit's specific concerns surfaced.
  * **Disagreement** → `REVIEW_REQUIRED` — a fourth verdict token
    beyond the primary's {GO, NICHE-DOWN, NO-GO}. Both verdicts
    rendered side-by-side; intentionally NO auto-resolution per
    the human-tiebreaker principle.

Cost: ~$0.01-0.02 per `--verify` invocation (gpt-4o pricing × ~2k
input + ~500 output tokens). Operator profile can flip
`verify_by_default = true` in `[operator]` so audit runs without
the flag; `--no-verify` overrides per-run.

Both verdicts persist on the cluster snapshot (`primary_verdict`,
`primary_pass_meta`, `audit`, `audit_pass_meta`, `reconciliation`,
`costs`). Cache short-circuits skip the LLM passes when a cached
snapshot has them already; `--invalidate {interpretive, audit, all}`
selectively re-runs individual passes against the same cached SERP
data (different from `--no-cache`, which bypasses the SerpAPI
cluster cache entirely).

### Problem statement

The mechanical gates (Phase 1/2/3) plus the primary interpretive
pass (v8.I) catch many bad-niche signals, but both share blind
spots — a SERP where 3 of 10 results are programmatic-template
URLs that don't quite match the v2 regex library; intent
misclassification when SERP features (Local Pack vs transactional
snippets) contradict the surface-level read; the "KD trap" (low
keyword difficulty + a top-3 entirely owned by incumbents);
unfalsifiable moats passing the human-input gate.

The empirical claim: different model families have different blind
spots. Catching the disagreement is the signal — a second LLM in
adversarial mode that steel-mans the opposite conclusion surfaces
what the primary missed.

### Goals (all delivered)

- **Adversarial audit pass** using a different model family
  (gpt-4o default) that steel-mans the opposite verdict.
  ✅ v12.A prompt + v12.B parser + v12.C runner.
- **Reconciliation surfaces disagreement** rather than auto-picking
  a winner. `REVIEW_REQUIRED` is a first-class verdict for the
  disagree case (alongside GO / NICHE-DOWN / NO-GO).
  ✅ v12.D.
- **Opt-in cost.** Default is primary-only. Audit pass + recon
  gated behind `--verify`.
  ✅ v12.E.
- **Versioned prompts.** Both prompts at `prompts/`,
  versioned (`_v1.md`, `_v2.md`, …); snapshots record which
  version produced their verdict.
  ✅ v8.F + v12.A both honor `prompt_version`.
- **Both verdicts always cached.** Even if `--verify` was off,
  re-running on cached data with `--verify` produces an audit
  without re-fetching SERP.
  ✅ v12.E + v12.F (cache short-circuit + `--invalidate`).

### Non-goals (scope-managed)

- Three-model consensus / N-way voting. Two perspectives + honest
  disagreement is the point; adding a third dilutes the signal.
  (v22 reserved for future Gemini integration if revisited.)
- Auto-resolution of disagreement. No "if audit confidence >
  primary confidence, audit wins" rules — those manufacture false
  certainty. The operator is the tiebreaker.
- Prompt-version A/B testing harness. Versioning lets us track
  which prompt produced what, but empirical comparison is a future
  feature.
- Audit-only mode (no primary, only adversarial). Audit's
  steel-man-the-opposite role doesn't make sense without a primary.

### User journey scenarios

```text
# Default (primary only) — ~$0.04 per run
$ lamill new research "ev charger installation cost"
  ... gate output ...
  Interpretive verdict (Claude)
  Verdict:    NICHE-DOWN
  Confidence: MEDIUM
  LLM cost: $0.0423

# Verify mode — audit fully agrees (+ ~$0.012)
$ lamill new research "ev charger installation cost" --verify
  ✓ Interpretive verdict: NICHE-DOWN (MEDIUM)
  ✓ Audit: full → final: NICHE-DOWN (MEDIUM)
  LLM cost: $0.0543 (primary $0.0423, audit $0.0120)

# Verify mode — audit partially disagrees
  ✓ Interpretive verdict: NICHE-DOWN (HIGH)
  ✓ Audit: partial → final: NICHE-DOWN (MEDIUM)    ← downgraded
    Caveats from audit:
      · INCUMBENT UNDER-DETECTION: notateslaapp.com pattern missed
      · TAM OVER-COUNTING: muscle-car pollution unadjusted
  LLM cost: $0.0543

# Verify mode — models disagree (high signal)
  ✓ Audit: disagree → final: REVIEW_REQUIRED (LOW)
    Caveats from audit: [...]
    REVIEW_REQUIRED — verdicts side-by-side:
      Primary (Claude):  NICHE-DOWN
      Audit (gpt-4o):    NO-GO — programmatic templates own the top-3
    Audit self-check:
      I may be over-indexing on URL patterns; intent could still be
      informational despite the templated structures.

# Re-run audit against cached primary (no SerpAPI burn)
$ lamill new research "ev charger installation cost" \
    --verify --invalidate audit
  (Reads cached cluster + cached primary; re-runs audit; re-reconciles.)

# Verify-by-default profile (lamill.toml [operator])
$ cat sites/portfolio/lamill.toml
  [operator]
  verify_by_default = true

$ lamill new research "ev charger installation cost"  # audit runs implicitly
$ lamill new research "ev charger installation cost" --no-verify  # opts out
```

### Resolved open questions (12.A-J — answered 2026-05-16; pinned for archeology)

| # | Question | Resolution |
|---|---|---|
| 12.A | Where do `prompts/` live? | **`prompts/` at repo root** (option 2). First-class status alongside `tests/` and `docs/`. |
| 12.B | Audit model default — GPT-4o / Gemini / operator's choice? | **gpt-4o default.** No Gemini in v1 (defer third-provider HTTP wrapper). Different-model invariant met with Claude (CLI) + OpenAI. |
| 12.C | Does the audit see the primary's `blind_spot_self_report`? | **Blind to it.** Anti-anchoring. Field still stored on the snapshot. |
| 12.D | `--verify` default-on in operator profile? | **Yes, via `verify_by_default: bool` in `lamill.toml [operator]`** (not a sticky state file). CLI `--verify` opts in; `--no-verify` overrides. |
| 12.E | Audit failure handling — fail / proceed primary-only / block verdict? | **Proceed primary-only** with a yellow "audit pass skipped: <reason>" line. Snapshot still has the primary verdict. |
| 12.F | Snapshot retention for audit — same as primary (kept forever, git-tracked)? | **Yes.** Audit responses are part of the verdict's provenance. |
| 12.G | Template-substitution engine — Jinja2 / `str.format()` / custom regex? | **Custom `{{var}}` regex.** Stdlib; no curly-brace collision with code-block examples; substitution validator doubles as no-unfilled-placeholders check. |
| 12.H | `--model` + `--audit-model` same-model behavior? | **Reject loudly** with a helpful suggestion. Same-model audit defeats model-family-diversity goal. |
| 12.I | Prompt versioning policy — when does `_v1.md` become `_v2.md`? | **Bump only when the change would meaningfully alter the verdict on cached data.** Typo / wording stays at `_v1.md`; new failure-mode checks bump. Snapshots store `prompt_version`; mismatch with current `_vN.md` is "stale verdict — re-render via `--invalidate interpretive`." |
| 12.J | Cumulative cost-tracking field on snapshots? | **Yes** — `primary_pass_meta.cost_usd` + `audit_pass_meta.cost_usd`, rolled up into a `costs` block (v12.F). Unblocks a future cost-ledger aggregation. |

### Effort and approval

Plan approved 2026-05-16. Effort estimate at plan-time: v12.A 2h
(shipped 2026-05-17); v12.B-G ~13-18h. Actual: v12.A-G shipped over
two productive sessions (2026-05-17 + 2026-05-19), well within the
estimate.

---

## v11 — active hosting layer (v11.A-N) — shipped 2026-05-18 to 2026-05-19

The full v11 tier shipped across 2026-05-18 → 2026-05-19 — 14
sub-phases over two days. Two halves:

  * **Read-only walker (v11.A-L).** Multi-provider walker (Vercel +
    CF Pages + CF Workers + HostGator) feeding
    `data/hosting/<date>.json` via the new `lamill fleet hosting`
    command, plus integrations into `fleet dashboard` and `project
    diagnose`, plus the `--apply-declarations` writer that closes
    the v10.F use case (HG sites without local repos / declarations).

  * **Active deploy verb (v11.M-N).** `new deploy <domain>` becomes
    polymorphic — reads `lamill.toml` and dispatches by platform.
    `cf-pages` reuses the v3.C `CloudflarePagesDeploy` first-time
    flow. `cf-workers` and `vercel` shell out to the canonical CLIs
    (`pnpm run deploy` / `vercel deploy --prod`) rather than
    re-implementing wrangler's asset pipeline or vercel's
    file-hashing pipeline against raw HTTP. `hostgator` / `custom`
    push to the cPanel host via UAPI `Fileman/upload_files` +
    `Fileman/rename` with stage-then-rename atomicity (upload to
    `<path>.next/` → rename current to `.prev/` → swap `.next/` to
    current → delete `.prev/`); dry-run default, `--apply` required.
    Adds a third deploy verb surface; ADR-0011 establishes
    remote-host writes as a separate category from ADR-0003's
    local-FS write scope.

Real-fleet hand test on 2026-05-19 verified the read-only cluster
end-to-end: walker walked operator's actual Vercel + CF + HG
accounts; surfaced several post-ship bugs that landed as small patch
commits while the tier was still being built (`cb5f4cf` v11.C
pagination, `42bb98b` v11.A HG auth username decoupling, `d3bae51`
v11.D/E/I megabytes_used + same-provider conflict + install_path
render). The active deploy half (v11.M-N) had not yet been
hand-tested against the live fleet at tier close — canonical first
target is `iotnews.today` (the v10.E drift case once the operator
runs `settings project set-deploy iotnews.today hostgator`).

Tier-level design rationale follows (moved from `prd.md § 6 → v11 →
Design notes` per the canonical-docs synchronization rule).

### Problem statement

v10 closed the *declaration* gap (every applicable sibling repo now
declares its deploy target in `lamill.toml`, and CHECK_143 surfaces
drift between declaration and live reality). The active-hosting gap
was still wide open:

1. The tool couldn't ask Vercel / CF Pages / HostGator directly
   whether a deploy succeeded — it inferred from filesystem markers
   and DNS heuristics in `project diagnose`, missing stale deploys,
   forgotten projects, and build regressions (a clean `vercel.json`
   checked in, but the project hadn't built successfully in months
   and the platform quietly left the previous version live).
2. There was no programmatic inventory for HostGator-hosted sites —
   the operator had to log into two cPanel accounts to enumerate
   domains, disk usage, WordPress versions. The v10.E classifier
   could tell when a site *is* HG-hosted; it couldn't enumerate the
   inverse ("what's on this HG account that I haven't declared yet?").
3. There was no `new deploy` path for HG/custom sites — bringing up
   a new HG-hosted site meant manual SFTP outside the tool, and
   updating a deployed HG site required the same manual workflow
   each time.

### Goals (all delivered)

Read-only inventory (v11.A-L):
- `lamill fleet hosting` as a peer of `fleet seo` — same shape:
  read-only, cached, refreshable, emoji table.
- Walk Vercel + Cloudflare Pages + Cloudflare Workers + HostGator
  UAPI using stored tokens.
- Match each provider's project/account to a fleet domain by
  configured custom domain (Vercel/CF) or cPanel addon-domain list
  (HG) — server-side truth, not local-file inference.
- Persist results to `data/hosting/<YYYY-MM-DD>.json` mirroring the
  `data/seo/` shape. Snapshot is git-tracked.
- Surface a deploy-platform conflict signal when the same domain
  appears across providers (drift) — strengthens v10.E's CHECK_143.
- `--apply-declarations` closes the original v10.F use case: writes
  `lamill.toml` for HG sites that have a local repo but no
  declaration yet.

Active deploy (v11.M-N):
- `lamill new deploy <domain>` becomes a polymorphic dispatch verb.
  `cf-pages` reuses v3.C's `CloudflarePagesDeploy`; `cf-workers`
  shells out to `pnpm run deploy` (wrangler); `vercel` shells out
  to `vercel deploy --prod`; `hostgator` / `custom` push via the
  v11.N UAPI uploader; `none` rejects; `netlify` / `github-pages`
  exit with "not yet implemented."
- UAPI file-upload deploy for `hostgator` / `custom` —
  operator-configurable `[hosting].deploy_source` (default `dist/`)
  uploaded to `public_html_path` via cPanel `Fileman/upload_files`
  with stage-then-rename atomicity. Dry-run default; `--apply`
  required. Adds the third deploy verb surface (ADR-0011).

### Non-goals (scope-managed)

- Triggering deploys on CF Pages / Vercel via portfolio's own API
  client — v11 reads their state but never POSTs a redeploy. For
  cf-workers + vercel, `new deploy` delegates to the canonical
  CLIs (`pnpm run deploy` / `vercel deploy --prod`) rather than
  re-implementing wrangler's asset pipeline or vercel's file
  pipeline. `git push` remains the contract for cf-pages.
- Walkers for Netlify / GH Pages / direct-Worker / Render —
  everything outside Vercel + CF Pages + CF Workers + HostGator
  is "skip" with a rendered "—" row.
- Cost / pricing reports.
- Auto-flagging consecutive failures as a `fleet focus` signal.
- Real-time webhooks.
- WordPress-specific deploy ops (theme/plugin/uploads). v11.N is
  static-SFTP-only; WP-aware deploy is a later phase.
- Auto-rewriting drifted `lamill.toml` declarations.
  `--apply-declarations` is scoped to "site has no declaration yet"
  per 11.N; drift remediation stays manual (operator runs
  `lamill settings project set-deploy <domain> <correct-platform>`
  after CHECK_143 fires).
- Fleet-wide remote-host writes. ADR-0011 caps `new deploy` at
  one site per invocation; a "deploy everything that's changed"
  command would need an ADR amendment.

### User journey scenarios

```text
$ lamill fleet hosting
Reading data/hosting/2026-05-19.json (1.2h old · use --refresh to re-fetch)

Domain                Provider          Status  Last Success           Failures
airsucks.com          cloudflare-workers ✓      2026-05-14 16:12 UTC   0
civictools.dev        vercel            ✓       2026-05-13 09:44 UTC   0
hybridautopart.com    hostgator         —       —                      —     [disk 1.4 GB · WP 6.7]
iotnews.today         hostgator         —       —                      —     [disk 89 MB · drift!]
linkedcsi.live        vercel            ✗       —                      5
kwizicle.com          cloudflare-workers 💤     2026-02-08 22:01 UTC   0

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
Deploy iotnews.today  (platform=hostgator · cPanel UAPI · DRY-RUN)
  project dir:    /home/vijo/work/projects/sites/iotnews.today
  deploy_source:  dist/
  public_html:    /home4/foundervijo/public_html/iotnews.today
  account:        gator4216  (user=foundervijo)

  ↷ DRY-RUN  47 files · 2.3 MB
  would upload to /home4/.../iotnews.today.next, then rename + swap …

Re-run with `--apply` to actually push.

$ lamill new deploy iotnews.today --apply
…
  ✓ Deployed  47 files · 2.3 MB
  uploaded 47 files (2.3 MB) → /home4/foundervijo/public_html/iotnews.today
```

### Resolved open questions

v11.A-L read-only walker (answered 2026-05-18):

| # | Question | Resolution |
|---|---|---|
| 11.A | `VERCEL_TOKEN` scope — personal token only, multi-token, or single-token + team-list config? | **Personal token only.** Operator-scale tool, single user. |
| 11.B | `--only` flag name collision with `fleet seo --only wip\|all`? | **Drop the scope flag entirely** — always operate on live-site + forwarder. `--only DOMAIN` is the single-domain probe. |
| 11.C | `RECENT_DAYS` / `STALE_DAYS` thresholds — configurable or hardcoded? | **Hardcoded constants** (shipped v11.A foundation). Revisit if real fleet data shows the thresholds are wrong. |
| 11.D | Deployment history lookback — cap or unbounded? | **Two-tier (option 3)** — stop at 10, mark ≥10 consecutive failures. |
| 11.E | Domain ↔ project matching — bare-host normalize or exact match? | **Bare-host normalize.** Matches user intent. |
| 11.F | Provider conflict (same domain on both)? | **Two rows in the snapshot** — one per provider — make drift visible. Rollup counts treat as a single conflict. |
| 11.G | Hosting snapshot — new file or join existing? | **New file** `data/hosting/<date>.json`. Mirrors every other layer. |
| 11.H | Walker error surfaces — 401 vs 5xx? | **Skip-affected-provider on 401**; per-row `error` on 5xx / rate-limit (option 1). |
| 11.I | Snapshot retention? | **Keep forever, git-tracked.** Same as every other layer. |
| 11.J | Test strategy? | **Mock at `httpx`/`requests` layer; no CI calls to real APIs.** Same pattern as `tests/test_gsc_recrawl.py`. |
| 11.K | HG token storage shape? | **Two named env vars in `apikeys.KNOWN_KEYS`** — `HOSTGATOR_TOKEN_GATOR3164` + `HOSTGATOR_TOKEN_GATOR4216`. Add more when a third account appears. Matches `PORKBUN_API_KEY` + `PORKBUN_SECRET_API_KEY` precedent. |
| 11.L | cPanel host derivation? | **Auto-derive host from env-var suffix; cPanel username separately overridable.** `HOSTGATOR_TOKEN_GATOR3164` → host `https://gator3164.hostgator.com:2083`. Username defaults to the same `gator3164` (back-compat with unmanaged HG shared hosting where username==server) but is overridable via paired `HOSTGATOR_USER_GATOR3164` env var. Patched 2026-05-19 after the operator's 403 hand test surfaced that their cPanel `Current User: foundervijo` differs from the server slug. |
| 11.M | `HostingRow` schema — typed optional fields vs `extra: dict` blob? | **Typed optional fields.** `disk_used_mb: int \| None`, `wp_version: str \| None`, `install_path: str \| None`. Matches every other dataclass in the codebase. |
| 11.N | `--apply-declarations` scope — only fix missing, or also rewrite drift? | **Only fix missing.** Matches `fleet repos --add-deploy-declarations` (v10.C) safety posture. Drift remediation stays manual via CHECK_143 + `settings project set-deploy`. |

v11.M-N deploy verb (answered 2026-05-19):

| # | Question | Resolution |
|---|---|---|
| 11.O | Verb split — one polymorphic `new deploy` or split into `new deploy` + `project push`? | **One polymorphic `new deploy <domain>`** (shipped v11.M). Reads `lamill.toml` and dispatches by platform. CF/Vercel/Workers paths are first-time-or-redeploy as the underlying tooling dictates; HG/custom path runs every time. |
| 11.P | What gets pushed — `dist/`, source files, or configured path? | **`[hosting].deploy_source` (default `dist/`)** — operator-configurable per site so a static-build site (`dist/`), a raw-PHP site (`.`), or a WP child theme each declare what to upload without inventing three verbs. |
| 11.Q | Auth — SSH key, cPanel password, or UAPI upload? | **cPanel UAPI `Fileman/upload_files`** — reuses v11.D's `HOSTGATOR_TOKEN_<account>` + `HOSTGATOR_USER_<account>` auth. No new auth surface, no SFTP library dependency. Per-file POST is slower than batch SFTP for many small files; acceptable for static-site payloads. |
| 11.R | WordPress in or out for v11.N? | **Static-only.** WP-on-HG sites (`hybridautopart.com`, `streamsgalaxy.com`) get a `skipped_wp` action with a clear note. WP-aware deploy (theme/plugin sync) is a later phase. |
| 11.S | Third write surface — reverse or refine ADR-0003? | **Write new ADR-0011** (next available — ADR-0009 / ADR-0010 already taken; PRD's original "ADR-0009" reference was stale). Establishes remote-host writes as a separate category from ADR-0003's local-FS write scope, with its own constraints. ADR-0003 stays intact. |
| 11.T | Atomicity — file-by-file, stage-then-rename, or maintenance mode? | **Stage-then-rename pair via cPanel Fileman/rename.** Upload to `<path>.next/` → rename current to `.prev/` → rename `.next/` to current → delete `.prev/`. Brief downtime window (ms) between renames — fine for static sites (WP excluded per 11.R). Failed upload leaves prod untouched; failed swap rolls back to `.prev/`. |

### Effort and approval

Read-only walker (v11.A-K) effort estimate at design time was
≈ 16-22h total, spread across 11 granular sub-phases:

| Phase | Scope | Effort |
|---|---|---|
| v11.A | Foundation (apikeys + dataclass) | ✅ shipped 2026-05-18 (~2h) |
| v11.B | Vercel walker | ~2-3h |
| v11.C | CF Pages walker | ~2-3h |
| v11.D | HostGator walker (net-new) | ~3-4h |
| v11.E | Orchestrator + match | ~2h |
| v11.F | Snapshot cache | ~1-2h |
| v11.G | CLI shell + flags | ~1-2h |
| v11.H | Renderer + error surfaces | ~2h (+CF Workers walker inserted) |
| v11.I | `--apply-declarations` writer | ~1-2h |
| v11.J | Dashboard + diagnose | ~2h |
| v11.K | Docs update | ~1h |

Active deploy (v11.M-N) shipped 2026-05-19 — both phases in one
session after the 11.O-T design pass. v11.M ~30min (small dispatcher
+ shell-outs). v11.N ~3h (UAPI helpers + orchestrator + ADR-0011
+ ~35 tests). Well under the 14-20h estimate; the shell-out choice
for cf-workers/vercel + the simple UAPI POST contract for HG kept
scope tight.

Approval: v11.A-K CLI shape + 11.K-N answers approved 2026-05-18;
v11.A shipped same day. v11.M dispatcher answers approved
2026-05-19, shipped same day. v11.N (11.O-T answers + ADR-0011)
approved and shipped 2026-05-19 — tier v11 complete.

## v11.N · UAPI file-upload deploy for hostgator/custom — shipped 2026-05-19

Closes the v11 tier. Active half of `new deploy <domain>` for the
`hostgator` and `custom` platforms — pushes the configured payload
(`sites/<domain>/<[hosting].deploy_source>/`, default `dist/`) to
the declared `public_html_path` on the cPanel host via UAPI.

Adds a third deploy verb surface — gated on **ADR-0011** (new),
which establishes remote-host writes as a separate write-surface
category from ADR-0003's local-FS scope. ADR-0003 stays in force,
unchanged; ADR-0011 carries its own constraints (idempotent,
dry-run default, per-site allowlist via `[hosting]` block,
stage-then-rename atomicity). The PRD's original gate said
"ADR-0009" but that slot was already taken by
`0009-makefile-forwards-to-central-builder` — ADR-0011 is the next
free number.

`HostingBlock` (lamill_toml.py) gains
`deploy_source: str = "dist/"` — operator-configurable per site;
serializer omits when default for round-trip determinism.

UAPI helpers in `hosting.py` (multipart POST for upload, GET for
everything else via existing `_call_hg_uapi`): `_hg_upload_file`
(`Fileman/upload_files`), `_hg_mkdir`, `_hg_rename`,
`_hg_delete_dir`. Orchestrator `deploy_hg_files(row, *,
lamill_toml, token, cpanel_user, sites_root, dry_run, client)
-> HgDeployRow` is single-row by design (ADR-0011's per-site
allowlist).

Stage-then-rename atomicity per resolution 11.T:

  1. mkdir `<public_html_path>.next/`
  2. upload every file (lazy subdir mkdirs)
  3. rename current → `.prev/`  (benign-failure on first-time deploy)
  4. swap `.next/` → current      ← the load-bearing rename
  5. delete `.prev/`              (best-effort, non-fatal)

On step-4 failure: rename `.prev/` back to current so prod stays up.

CLI wired in `cli.py::_deploy_hostgator_v11n` (replaces the v11.M
placeholder). Reads token via
`apikeys.get_key("HOSTGATOR_TOKEN_<account>")`, cpanel_user via
`apikeys.hg_user_for_account()`, matching `HostingRow` from
`hosting_cache.latest_snapshot()` (refuses without a snapshot —
hints to run `fleet hosting --refresh`). New `--apply` flag on
`new deploy` flips dry-run-default → push for the hostgator/custom
branches.

`HgDeployRow.action` vocabulary mirrors `HgApplyRow`:
`would_deploy` / `deployed` / `skipped_wp` / `skipped_no_source` /
`skipped_no_path` / `failed`. WP-skip fires when the snapshot row's
`wp_version` is set (resolution 11.R: static-only).

Ref `ee863f2`. 40 new tests (4 lamill_toml `deploy_source` + 31
in `test_hosting_deploy.py` + 5 CLI integration in
`test_new_deploy_dispatch.py`).

**Not yet hand-tested against the live fleet** — canonical first
target is `iotnews.today` (the v10.E drift case once the operator
runs `settings project set-deploy iotnews.today hostgator`).

## v11.M · `new deploy` polymorphic dispatch — shipped 2026-05-19

Refactors `new deploy <domain>` from CF-Pages-only (v3.C) into a
polymorphic dispatcher that reads `lamill.toml` and routes to the
right deploy path per platform.

Dispatcher branches in `cli.py::new_deploy`:

| `platform` | Path |
|---|---|
| `cf-pages` | Existing `CloudflarePagesDeploy` flow, extracted into private `_deploy_cf_pages_v3c()` (behavior unchanged from v3.C) |
| `cf-workers` | `deploy_cf_workers_via_shell()` runs `pnpm run deploy` in the project dir (delegates to wrangler) |
| `vercel` | `deploy_vercel_via_shell()` runs `vercel deploy --prod` |
| `hostgator` / `custom` | v11.N placeholder (replaced by the real UAPI uploader in `ee863f2`) |
| `netlify` / `github-pages` | "Not implemented yet" exit |
| `none` | Reject with `settings project set-deploy` hint |
| (missing `lamill.toml`) | Assume `cf-pages` (legacy default) with an explicit notice |

Shell-out (not direct API) for cf-workers and vercel is deliberate:
wrangler's assets-upload pipeline and vercel's file-hashing pipeline
are nontrivial to replicate against raw HTTP, and the operator
already has the canonical CLIs installed. The new helpers
(`deploy_cf_workers_via_shell`, `deploy_vercel_via_shell` in
`deploy.py`) take a `runner=` injection seam so tests don't fork
real subprocesses.

11.O resolved: one polymorphic verb (vs split into separate
`new deploy` + `project push` for first-time vs recurring). The
asymmetry — "do the deploy" means different things per platform
(first-time interactive for CF Pages; immediate for cf-workers and
vercel via their CLIs; staged + apply for HG) — is acceptable;
splitting the verb would add cognitive overhead without operational
benefit at this scale.

Ref `84ca891`. 22 new tests (8 shell-helper + 14 CLI dispatcher).

## v11.K · `fleet dashboard` + `project diagnose` integrations — shipped 2026-05-19

Brings v11.A-J walker output into two existing fleet-level operator
surfaces. Dashboard (v7.B) gains Host (🟢/🟡/🔴/—) + Prov
(VC/CFP/CFW/HG, `+` suffix on conflict) columns plus a `host=`
entry in the freshness footer; rollup widens to 4 dimensions.
Diagnose (v7.F) gains a sixth `HostingLayer` (snapshot-read only —
never re-walks); renders provider / project_slug / hg_account_id /
status / last_ok date / failures / disk / WP per matching row;
surfaces 🤐 conflict on multi-row drift.

Both reuse v11.F's `hosting_cache.result_from_snapshot()`. New
`_host_dot()` cascade mirrors `hosting_status_emoji` but maps to
the dashboard's color-dot vocabulary. Hand test confirmed all three
integration signals: `HG+` column for hybridautopart conflict,
🤐 markers in diagnose for the same domain (showing both gator3164
and gator4216 rows), and iotnews.today diagnose layer showing
`provider=hostgator` despite the lamill.toml declaring `vercel`
(visible drift case from v10.E now surfacing in diagnose too).
Ref `afa2031`. 19 tests.

## v11.J · `fleet hosting --apply-declarations` writer — shipped 2026-05-19

Closes the original v10.F use case (HG cPanel integration writes
`lamill.toml` for HG sites without a declaration) inside v11's
unified design. Mirrors v10.C's `fleet repos --add-deploy-
declarations` migration-sweep convention — dry-run by default,
`--apply` writes. Scoped HG-only (CF/Vercel already inferable via
v10.C). New `apply_hg_declarations()` data-layer function +
`HgApplyRow` per-domain action shape (would_write / wrote /
skipped_already / skipped_no_site_dir / skipped_archived).
Resolution 11.N — never overwrites an existing `lamill.toml`.

Real-fleet dry-run on 2026-05-19: against 10 HG-walker rows, 4 were
`skipped_already` (existing declarations including the drift-case
`iotnews.today`), 6 were `skipped_no_site_dir` (HG-hosted but no
local repo: `carrepairsite.com`, `thakinaam.com`, `lamill.us`,
`maslist.com`, `virtually.co.in`, `winmacbook.com`). 0 would-write
— current fleet is in equilibrium. Two of the surfaced no-repo
sites (`virtually.co.in`, `winmacbook.com`) operator decided to
delete from HG entirely after seeing them in the dry-run. Ref
`47e77f4`. 15 tests.

## v11.I · `fleet hosting` renderer upgrade (status emoji, footer, conditional HG-extra) — shipped 2026-05-19

Renderer polish for the v11.A-H walker cluster. Closes three bugs
surfaced during the 2026-05-19 real-fleet hand test:

- Status emoji column at left of the table per resolution 11.C's
  age cascade (✓ recent / ⚠ stale / 💤 dormant / ✗ runaway-fail /
  🤐 conflict / — unowned). `hosting.hosting_status_emoji(row)` is
  the public helper that the dashboard + diagnose integrations
  in v11.K reuse.
- Conditional `HG-extra` column — only rendered when ≥1 HG row.
  Previously the empty column rendered for every Vercel/CF row,
  padding the table with visual noise.
- One-line footer summary via `hosting.hosting_footer_summary()` —
  `N rows · M cloudflare-workers · L vercel · K cloudflare-pages
  · J hostgator (X skipped, Y conflicts)`. Zero counts surface
  for diagnostic visibility.
- `--provider X` zero-rows distinguishes (a) walker returned
  nothing vs (b) filter dropped everything — the latter shows the
  pre-filter breakdown. Operator-visible improvement after the
  hand test where `--provider=cloudflare-pages` showed only "No
  hosting rows" despite the walker returning 11 rows under other
  providers.

Public helpers `hosting_status_emoji` / `hosting_provider_counts`
/ `hosting_footer_summary` reusable by the v11.K dashboard +
diagnose integrations + any future renderers. Ref `44fe8dc`. 28
tests (20 emoji/footer unit + 8 CLI integration).

## v11.H · CF Workers walker — shipped 2026-05-19

Net-new phase inserted 2026-05-19 after a real-fleet hand test
showed operator's CF sites deploy as **Workers (Static Assets)**,
not legacy CF Pages — `/accounts/{id}/pages/projects` returned
`result: []` while `/workers/scripts` returned the actual sites
(airsucks, cricketfansite, donready, isitholiday, kwizicle, voltloop).

`walk_cf_workers()` hits two endpoints (both single-shot per
v11.C's lesson — these CF endpoints reject `?page=N&per_page=N`):

- `/accounts/{id}/workers/scripts` — script metadata, `modified_on`
- `/accounts/{id}/workers/domains` — hostname → service mapping

Filters to `environment="production"`. Workers deploys are atomic
so `consecutive_failures=0` always and
`last_successful_deploy_at == latest_deploy_at == script.modified_on`.

Adds `PROVIDER_CF_WORKERS = "cloudflare-workers"` to the
PROVIDERS tuple. Orchestrator (v11.E) spawns both `walk_cf_pages`
and `walk_cf_workers` against the same CF account. Inserting v11.H
shifted the planned v11.H-M to v11.I-N. Ref `570bcd5`. 19 tests.

## v11.G · `lamill fleet hosting` CLI shell + cache eligibility — shipped 2026-05-18

`fleet hosting` Typer command + `--refresh` / `--only DOMAIN` /
`--provider {vercel|cloudflare-pages|cloudflare-workers|hostgator}`
/ `--json` flags. Cache-eligibility: re-use latest snapshot if fresh
(<24h) unless `--refresh` or `--only` is set; fleet-wide walks
persist; single-domain probes never overwrite the fleet snapshot.
Minimal renderer in place; v11.I upgrades it with status emoji +
footer rollups. Ref `1e2c0d3`. 11 CliRunner tests.

## v11.F · fleet hosting snapshot cache — shipped 2026-05-18

`src/portfolio/hosting_cache.py` mirroring `seo_cache.py`. Writes
`data/hosting/<UTC-today>.json` with rows + skipped + fetched_at;
public `save_snapshot` / `list_snapshots` / `latest_snapshot` /
`load_snapshot` / `result_from_snapshot` / `is_stale(path,
max_age_hours=24)`. Forward-compat — unknown row keys dropped on
load so a newer `HostingRow` field doesn't break older snapshots.
Ref `edbbae1`. 14 tests.

## v11.E · fleet hosting orchestrator + provider-conflict detection — shipped 2026-05-18

`run_hosting(fleet_domains, *, only_domain) -> HostingResult`.
ThreadPoolExecutor fan-out across all walker tasks. Reads tokens
via `apikeys.get_key`; pre-checks each provider's required keys and
records skip-reasons (`HostingResult.skipped`) when missing.
Catches `*AuthError` / `*WalkError` per walker without crashing
the run. `_flag_provider_conflicts` post-pass sets
`provider_conflict=True` on every row whose domain matches under
≥2 distinct providers (resolution 11.F). Ref `cb62027`. 15 tests.

## v11.D · HostGator walker (cPanel UAPI) — shipped 2026-05-18 *(+post-ship fixes 2026-05-19)*

`walk_hostgator(token, account_id, fleet_domains, *, only_domain,
cpanel_user)`. cPanel UAPI calls: `DomainInfo/list_domains` (main +
addon + parked + sub with `documentroot` extraction),
`Quota/get_quota_info` (account-level `disk_used_mb`),
`WordPressManager/list_installations` (`wp_version` + `install_path`,
404-tolerant — WPM plugin isn't on every cPanel). Custom
`cpanel <user>:<token>` auth scheme. Closes the v10.F use case.
Ref `7158868`. 16 tests + 1 added in post-ship fix.

**Post-ship fixes (real-fleet hand test 2026-05-19):**

- `42bb98b` v11.A patch — Decoupled cPanel username from server
  hostname. Original 11.L resolution assumed username==server-
  hostname (true for unmanaged HG shared hosting where
  `HOSTGATOR_TOKEN_GATOR3164` implies cPanel user `gator3164`).
  Operator's account 403'd because their cPanel `Current User:
  foundervijo` differs from the server slug. Added paired
  `HOSTGATOR_USER_<account>` env vars to `apikeys.KNOWN_KEYS` +
  `apikeys.hg_user_for_account()` helper. Walker takes a
  `cpanel_user=` kwarg; falls back to `account_id` when None for
  back-compat with shared-hosting setups.

- `d3bae51` v11.D/E/I patch — Three real-fleet bugs:
  (a) `disk_used_mb` empty because cPanel returns `megabytes_used`,
  not the `disk_used` key I'd guessed; walker now reads both with
  preference for the real-API key.
  (b) `_flag_provider_conflicts` extended to flag any domain with
  ≥2 rows (not just cross-PROVIDER ones) — catches the operator's
  hybridautopart.com appearing as an addon on BOTH gator3164 AND
  gator4216.
  (c) Renderer adds `install_path` to the HG-extra cell when set
  (truncates to last 30 chars on long paths).

## v11.C · Cloudflare Pages walker — shipped 2026-05-18 *(post-ship fix: single-shot pagination 2026-05-19, ref cb5f4cf)*

`walk_cf_pages(api_token, account_id, fleet_domains, *, only_domain)`.
Mirrors v11.B's contract against CF Pages API
(`/accounts/{id}/pages/projects` + `/.../deployments`). CF-specific
deploy classification — SUCCESS only when `latest_stage =
(deploy, success)`; FAILURE when `stage.status == failure`;
everything else IN_PROGRESS. Single-shot — the projects-list
endpoint doesn't accept `?page=N&per_page=N` (real-fleet hand test
surfaced API error `8000024 "Invalid list options provided"` on
2026-05-19; fixed in `cb5f4cf`). Ref `5048be0` + `cb5f4cf`. 25 tests.

## v11.B · Vercel walker — shipped 2026-05-18

`walk_vercel(token, fleet_domains, *, only_domain)`. Paginates
`/v9/projects`, extracts `targets.production.alias` custom domains,
bare-host-normalizes (resolution 11.E), matches against
`fleet_domains`, walks deploy history via `/v6/deployments` up to
`MAX_DEPLOY_LOOKBACK=10`. State classification: READY=success;
ERROR/CANCELED=failure; BUILDING/INITIALIZING/QUEUED=in-flight
(resolution 11.D). `VercelAuthError` on 401 (orchestrator skips);
per-project deploy failures attach to row `error`. Ref `0cd3194`.
25 tests.

(Note: hand test 2026-05-19 surfaced ~9 fleet sites missing — see
`docs/bugs.md`. Diagnosis: operator-side data-quality, not walker
bug. Walker accurately reflects what Vercel's API reports.)

## v11.A · foundation — apikeys plumbing + HostingRow dataclass + constants — shipped 2026-05-18

Two slices under one phase letter (the "foundation" bundle):

- Apikeys plumbing — added `VERCEL_TOKEN` +
  `HOSTGATOR_TOKEN_GATOR3164` + `HOSTGATOR_TOKEN_GATOR4216` to
  `apikeys.KNOWN_KEYS`; new `_probe_vercel()` (5s timeout, /v2/user)
  and `_probe_hostgator()` (8s timeout, cPanel UAPI
  Variables/get_user_information, cPanel custom auth scheme).
  cPanel host auto-derived from env-var suffix (resolution 11.L).
  Ref `139fb63`. 14 tests.

- `HostingRow` dataclass + constants — typed optional fields
  including HG-specific (`hg_account_id`, `disk_used_mb`,
  `wp_version`, `install_path`) per resolution 11.M.
  Constants: `PROVIDERS`, `RECENT_DAYS=30`, `STALE_DAYS=90`,
  `MAX_DEPLOY_LOOKBACK=10`. New `src/portfolio/hosting.py` module.
  Ref `1b59e85`. 11 tests.

---

## v10 tier · per-site deploy declarations — wrapped 2026-05-18

The full v10 tier (A-E) shipped on 2026-05-18 across the day. The
originally-planned v10.F (HostGator cPanel integration) was absorbed
into v11.A, and v10.G (SFTP deploy abstraction) was renumbered v11.B
on the same day — both belong with the active-hosting cluster, not
the declaration mechanism. Tier-level design rationale follows
(moved from `prd.md § 6 → v10 → Design notes` per the canonical-docs
synchronization rule).

### Problem statement

Determining "what platform does this site deploy to?" pre-v10
required triangulating three separate signals — repo config files
(`wrangler.jsonc` / `vercel.json` / `netlify.toml`), DNS lookup,
HTTP probe — and reconciling disagreement manually. There was no
declaration mechanism for HostGator, WordPress, custom VPS, or
static FTP-deployed sites; drift between intent and actual was
invisible until probed; cross-site queries ("show me all sites on
Vercel") couldn't be answered. A canonical declaration in the repo
closed all three gaps.

### Goals (all delivered)

- Schema for `lamill.toml` covering common platforms + an extension
  slot for HostGator / custom hosts — *v10.A*.
- `LamillToml` parser/writer module reused by future tools — *v10.A*.
- `lamill settings project set-deploy <name> <platform>` to manually
  create or update on existing sites — *v10.B*.
- `lamill settings project show-deploy <name>` to inspect — *v10.B*.
- `lamill new bootstrap` writes the file as part of scaffolding —
  inferred from `--stack` with `cf-pages` default — *v10.C*.
- `lamill fleet repos --add-deploy-declarations` migration — safe-
  by-default, refuses ambiguous cases — *v10.C*.
- Real-fleet rollout: every applicable sibling repo carries a
  committed `lamill.toml` — *v10.D* (22 of 23 fleet sites; 5
  NO_GIT sites pending v6.F).
- Drift detection + conformance checks (`has-lamill-toml` /
  `lamill-toml-valid` / `deploy-drift`) — *v10.E*.

### Non-goals (scope-managed)

Originally deferred to v10.F-G: HostGator API integration, SFTP
deploy abstraction. Both reassigned to v11 on 2026-05-18 (v11.A
unified hosting walker absorbs the HG inventory case; v11.B
polymorphic `new deploy` absorbs the SFTP deploy case). v10's
contract closed at "declare + validate + detect drift" — active
hosting ops are v11's job.

Also deferred (still): multi-platform site declarations (apex on
A, `www.*` on B), validation against live state beyond CHECK_143's
classifier heuristic.

### User journey scenarios

1. *Bootstrapping a new site* (v10.C) — `lamill new bootstrap
   newdomain.com --stack astro` writes `lamill.toml` with
   `platform=cf-pages` inferred from `--stack`. Operator edits
   before `new deploy`.
2. *Manually setting deploy on an existing site* (v10.B) — `lamill
   settings project set-deploy hybridautopart.com hostgator`
   prompts for cPanel + FTP breadcrumbs, writes `lamill.toml`.
   Tool writes to working tree only — operator commits when ready.
3. *Reading the declaration* (v10.B) — `lamill settings project
   show-deploy hybridautopart.com` renders platform / account /
   branch / domains / hosting block as a human table.
4. *Bulk migration of existing sites* (v10.C) — `lamill fleet repos
   --add-deploy-declarations --dry-run` walks every `sites/<dir>/`,
   classifies into unambiguous / manual-review / manual-entry /
   archived, surfaces a plan. Re-run without `--dry-run` writes
   the unambiguous cases.
5. *Real-fleet rollout* (v10.D) — operator ran the migration
   against ~22 fleet domains; reviewed the plan; applied safe
   cases; handled edge cases interactively. End state: 22 of 23
   fleet sites carry `lamill.toml` (17 committed in own-git-repos;
   5 NO_GIT sites have file in working tree pending v6.F).
6. *Drift detection* (v10.E) — `lamill project check
   iotnews.today` surfaces CHECK_143 fail when declared platform
   diverges from classified-actual (the iotnews case: declared=
   vercel, classifier saw WordPress installer title in body
   excerpt → hostgator).

### Resolved open questions

| # | Question | Resolution |
|---|---|---|
| 10.A | TOML writer library — `tomllib` + manual write, `tomli-w`, or `tomlkit`? | **`tomli-w`** — operator edits go through `$EDITOR`; tool-side writes happen on fresh files or full re-renders, so comment preservation isn't load-bearing. Tomlkit heavier than its value at personal scale. |
| 10.B | Inference priority when multiple platform configs exist? | **Refuse — surface for manual review.** Migration is a one-time op; ambiguous cases manageable manually. `--include-ambiguous` lets the operator skip the manual step at the cost of a possibly-wrong default. |
| 10.C | Bootstrap default platform — `cf-pages`, `vercel`, or no default? | **Kept `cf-pages`** for v10.C. Existing convention; bootstrap output stable. |
| 10.D | Should `set-deploy` commit + push automatically? | **Just write the file.** Same posture as `settings project set-launched`. Operator decides when to commit + push. |
| 10.E | Schema version handling on bumps (`lamill-toml-v1` → `v2`)? | **Read-with-fallback / never-write-v1.** Operator-friendly without complex migration paths. Schema bumps should be rare. |
| 10.F | WordPress sites with no project directory under `sites/`? | **Skipped in v10.C migration.** Sites without a local repo can't carry `lamill.toml` in the repo. v11.A surfaces them differently via the HG walker. |
| 10.G | Multi-deploy declarations (apex on A, `www.*` on B)? | **Not in v10.** YAGNI. Schema extension if a real case ever appears. |
| 10.H | Where does `account` come from for new bootstraps? | **Left blank** for v10.C — operator profile wasn't shipped yet. v11.A may populate from cPanel-account context for HG cases. |

### Approval

Approved 2026-05-18 per session reorg. All five sub-phases (v10.A-E)
landed the same day; tier closed 2026-05-18 evening when v10.E
shipped and v10.F + v10.G were folded into v11.

---

## v10.E · drift detection + lamill.toml conformance checks — shipped 2026-05-18

Three deploy-category checks closed the v10.A-E loop. Commit
`cda9e28`. 26 new tests; suite at 1827 passed / 1 skipped.

- *`CHECK_058 has-lamill-toml`* (severity: error). Fails when
  `<repo>/lamill.toml` is missing. Skip on archived. 5 NO_GIT
  sibling repos baseline-fail until v6.F runs — known and
  accepted.
- *`CHECK_059 lamill-toml-valid`* (severity: error). Round-trips
  the file through `lamill_toml.load()`; surfaces TOML syntax
  errors, missing `[deploy]`, unknown enum values, missing
  `[hosting]` when platform requires it.
- *`CHECK_143 deploy-drift`* (severity: warn). Best-effort
  classification of the latest `data/checks/<date>.json` row vs
  declared platform. WordPress fingerprints (generator-meta /
  `<title>WordPress*` / `wp-(includes|content|admin)` paths) →
  `hostgator`; provider-suffix hostnames in `final_url` or
  `redirect_chain` → that provider. Honest about uncertainty —
  `warn`s when no strong signal, only `fail`s when declared ≠
  classified-actual. The canonical drift case `iotnews.today`
  (declared=vercel, classifier saw WP installer error page) →
  fail.

Classifier inlined in `check_143_deploy_drift.py`, not extracted.
Single call site for now; if v11.A's hosting walker needs a
similar cross-check, extract then.

## v10.D · real-fleet validation sweep — shipped 2026-05-18

Operator-driven rollout against the actual fleet. Ran
`lamill fleet repos --add-deploy-declarations` (dry-run → apply)
against ~22 sibling repos; reviewed plan; resolved edge cases
interactively via `lamill settings project set-deploy`.

**Per-bucket end state** — 22 of 23 fleet sites carry `lamill.toml`:

| Bucket | Count | Sites |
|---|---|---|
| Migration `--apply` (unambiguous via config) | 9 | agesdk.dev · airsucks.com · calcengine.site · donready.xyz · keralavotemap.site · kwizicle.com · lamill.io · lamillrentals.com · washcalc.app |
| `set-deploy cf-pages` (CF dashboard, no wrangler config) | 3 | cricketfansite.com · isitholiday.today · voltloop.site |
| `set-deploy vercel` (unclassified-but-vercel per operator) | 7 | civictools.app · csinorcal.church · iotbastion.com · iotnews.today · linkedcsi.live · thoralox.com · whizgraphs.com |
| `set-deploy vercel` (resolved ambiguous) | 1 | homeloom.app |
| `set-deploy hostgator` (full breadcrumbs) | 2 | hybridautopart.com · streamsgalaxy.com |

**Per-sibling-repo commit state** (17 own-git-repo + 5 NO_GIT):

- *Pushed:* 15 — airsucks · calcengine · civictools · cricketfansite ·
  csinorcal · donready · homeloom · hybridautopart · isitholiday ·
  keralavotemap · kwizicle · lamill.io · lamillrentals · voltloop ·
  washcalc.
- *Committed locally, no remote yet:* 2 — agesdk.dev · iotbastion.com
  (need `origin` setup + push).
- *NO_GIT (own `.git` missing) — `lamill.toml` untracked:* 5 —
  iotnews.today · linkedcsi.live · streamsgalaxy.com · thoralox.com ·
  whizgraphs.com. v6.F (own-git-repo guided migration) closes this;
  these 5 baseline-fail `CHECK_058 has-lamill-toml` from v10.E until
  v6.F runs — known and accepted.

**Out of v10/v11 scope:** `hostkit.app` (unregistered domain; stale
`sites/` dir), `carrepairsite.com` (HG account 1, no local repo —
v11.D walker surfaces), `thakinaam.com` (HG account 2, no local repo
— v11.D walker surfaces), `newiniot.com` (dead — invalid CF
nameservers; `portfolio.json` cleanup pending).

Two minor bugs surfaced and were logged to `docs/bugs.md`:
`set-deploy` failing for sites/ dirs missing from portfolio.json,
and `set-deploy` not auto-populating `custom_domains` from dir
name. Both deferred — they didn't block the sweep.

Refs commit `46ef8fa` (data refresh — fleet info cleanup +
checks/seo snapshots).

## v10.A · `lamill.toml` foundation (schema + parser + writer + infer) — shipped 2026-05-18

Three commits delivered the library half — `src/portfolio/lamill_toml.py`
(dataclasses, `load()`, `write()`, `infer_from_existing_configs()`,
`detect_platform_signals()`, `to_dict()`) + `tests/test_lamill_toml.py`
(70 tests). New dep `tomli-w`. Refs `4395e1d` → `c9d543b` → `be10787`.

Tier-level design rationale at top of v10 section above.

## v10.C · `new bootstrap` writes lamill.toml + `fleet repos --add-deploy-declarations` migration sweep — shipped 2026-05-18

Two-slice auto-write integration. `new bootstrap` writes `lamill.toml`
as part of scaffolding (platform priority: `--platform` flag → infer-
from-existing-configs → `cf-pages` default; hostgator/custom rejected
at bootstrap). `fleet repos --add-deploy-declarations [--dry-run/
--apply] [--include-ambiguous]` migration sweep walks every
`sites/<dir>/`, classifies into already_declared / archived /
unambiguous / ambiguous / manual, writes safe cases. Refs `fd725ff`
(bootstrap writes) + migration-sweep commit.

Detection logic enhanced — `_wrangler_platform` now recognizes the
modern CF Pages spec (`"assets":` / `[assets]` blocks) alongside the
legacy `pages_build_output_dir` field, so both bootstrap-generated
and historical wrangler files classify correctly.

Tier-level design rationale at top of v10 section above.

## v10.B · `settings project set-deploy` + `show-deploy` CLI — shipped 2026-05-18

Two CLI commands for managing `lamill.toml`. Refs `d28c516` (set-deploy
implementation + 17 tests), `890841e` (namespace move from `project` to
`settings project`), `<this commit>` (show-deploy + 12 tests).

Per operator-direction 2026-05-18: per-project metadata commands live
under `settings project`, not the `project` namespace (which is
reserved for project-code ops — check / fix / seo / diagnose).
`set-launched` (originally shipped v7.C as `project set-launched`)
moved into the same `settings project` namespace for consistency.

Tier-level design rationale at top of v10 section above.

## v12.F · cost ledger + verify_by_default + granular invalidate — shipped 2026-05-19

Three polish concerns shipped together: (a) `costs` block on the
cluster snapshot (`{primary_usd, audit_usd, total_usd, currency}`),
populated idempotently by `_update_cost_summary(payload)`; (b)
`verify_by_default: bool` field on `OperatorProfile`, loaded from
`lamill.toml [operator]`, with new `--no-verify` CLI flag overriding
per-run; (c) `--invalidate {none, interpretive, audit, all}` for
granular per-pass cache short-circuit (different from `--no-cache`,
which bypasses the SerpAPI cluster cache wholesale).

Effective-verify resolution:
`(verify or profile.verify_by_default) and not no_verify`. Truth
table covers all eight combinations; 30 tests pin it. Render-footer
line shows the breakdown when both passes contributed; omitted on
zero-cost or pre-v12.F snapshots to avoid noise.

## v12.E · Wire --verify into `new research` orchestrator — shipped 2026-05-19

First user-visible audit-pass surface. Two new typer options on
`new research`: `--verify` (default off) and `--audit-model gpt-4o`
(default). New `_run_audit_pass_and_reconcile()` helper mirrors
v8.I's primary-pass wiring pattern — load operator profile, call
`run_audit_pass`, rebuild `ParsedVerdict` from the persisted flat
dict, call `reconcile()`, persist into snapshot.

Same-model rejection: errors with exit 2 when `--audit-model`
matches the primary's `model_id` (today: `claude-cli`). The audit's
value is model-family diversity; same-model audit collapses that
into "ask twice and hope for variance," defeating the verdict-gate.

New `_render_reconciliation_block()` renders below the primary
block — three shapes keyed on `agreement_level`: full (terse
one-line), partial (caveats list), disagree (REVIEW_REQUIRED banner
+ both verdicts side-by-side + audit's self-check). `_VERDICT_COLOR`
extended with `REVIEW_REQUIRED → magenta` to distinguish from
`NO-GO → red` (they mean very different things to the operator).

Cache-aware: snapshot's `audit` + `audit_pass_meta` + `reconciliation`
blocks short-circuit re-running the audit on cache hits. 17 tests.

## v12.D · Reconciliation + REVIEW_REQUIRED first-class verdict — shipped 2026-05-19

New `src/portfolio/reconciliation.py` module — pure-logic combiner
for `(ParsedVerdict, ParsedAudit) → Reconciliation`. No LLM calls,
no I/O. Three reconciliation paths keyed on `audit.agreement_level`:

  - **full**: primary's verdict + confidence preserved, caveats empty
  - **partial**: primary's verdict kept, confidence downgraded one
    notch (`HIGH→MEDIUM, MEDIUM→LOW, LOW→LOW` saturates), caveats
    populated from `audit.specific_concerns`
  - **disagree**: `REVIEW_REQUIRED` (new fourth verdict token),
    confidence `LOW`, caveats surfaced. No auto-resolution per
    PRD §6 v12 — the operator is the tiebreaker.

`REVIEW_REQUIRED` is reserved for reconciliation; it does NOT
appear in the primary's verdict set ({GO, NICHE-DOWN, NO-GO}) or
the audit's agreement-level set ({full, partial, disagree}).
Renderer dispatches on the token.

Why no auto-resolution: the audit's value is catching something the
primary missed. Mechanically picking a side (e.g., "audit wins on
HIGH-confidence disagree") would erode the human's judgment loop
the verdict-gate exists to support. 20 tests.

## v12.C · Adversarial audit pass runner — shipped 2026-05-19

`run_audit_pass(cluster, *, primary_verdict, operator_profile, ...)
→ AuditPassResult` + `AuditPassError`. Parallel to v8.H's
`run_primary_pass` — different LLM provider (OpenAI Responses API
vs Claude CLI) but same orchestration shape:

  1. build_audit_payload → render_audit_prompt → split on `\n---\n`
     into (system, user)
  2. openai_caller(system, user, model) → OpenAIChatResult
  3. parse_audit → ParsedAudit
  4. Compute cost from token usage × per-model pricing table

Default model `gpt-4o` per PRD §6 v12 (different family from the
Claude-CLI primary by design — audit's value is model disagreement,
not a second opinion from the same family). Override via `model=`.
`openai_caller=` is the test seam; production gets
`_call_openai_chat` (posts to `/v1/responses`, returns text + token
usage).

Pricing table covers `gpt-4o` / `gpt-4o-mini` / `gpt-4-turbo` /
`gpt-4.1`, with prefix match for dated aliases (`gpt-4o-2024-08-06`
→ `gpt-4o`). Unknown models record cost=0 rather than crash.

OpenAI HTTP code duplicated from `serp.call_openai` rather than
refactored — `serp.call_openai` discards token usage (which the
audit pass needs for cost), and refactoring would force re-
validation of 5 existing callers. 20 lines of boilerplate duplicate
is cheaper. v12.F could consolidate if cost-ledger work needs the
same shape elsewhere. 19 tests.

## v12.B · Adversarial audit response parser — shipped 2026-05-19

`audit_pass.parse_audit(markdown) → ParsedAudit` plus
`AuditParseError`, parallel to v8.E's `parse_verdict` but enforcing
a different schema per `prompts/adversarial_audit_v1.md`:

  - required `### agreement_level` ∈ {full, partial, disagree}
  - required `### confidence` ∈ {HIGH, MEDIUM, LOW}
  - required `### specific_concerns` with ≥1 bullet
  - optional `### counter_verdict` (required on disagree; split
    into `counter_verdict_token` + `counter_verdict_reasoning` so
    v12.D's reconciliation can compare tokens directly)
  - optional `### audit_self_check`

Reuses interpretive_pass's `_split_sections`, `_parse_bullets`,
`_normalize_verdict_token`, `_VALID_VERDICTS` rather than
duplicating — the section/bullet primitives are stable and
identical across the two pass parsers.

Strict on `agreement_level=disagree` + missing/malformed
`counter_verdict`; permissive on off-spec counter on full/partial
(raw body falls into reasoning, token stays empty). 24 tests.

## v12.A · Adversarial audit prompt rendering — shipped 2026-05-17

`audit_pass.render_audit_prompt(payload)` — loads
`prompts/adversarial_audit_v1.md` (H1 stripped by `load_prompt`),
runs it through `render_prompt(template)` with no substitutions
(drift guard — future `{{var}}` additions raise
`UnfilledPlaceholderError` at rendering rather than burning a token
budget on an unfilled prompt), appends the audit payload JSON
(built by v8.J's `build_audit_payload`) inside a fenced block.

Parallel to v8.F's `render_primary_prompt`, but the audit prompt
today carries no `{{var}}` placeholders — operator context flows
through the payload's `operator_profile_summary` and `operator_fit`
fields rather than via prompt-level template vars. The audit
doesn't tailor instructions to operator type; it reasons about the
data. 12 tests.

## v9.E · Canonical-sections TOML-driven SSOT — shipped 2026-05-17

(TBD — minimal; brief rationale only.)

## v9.D · `new bootstrap` growth-hypothesis prompt — shipped 2026-05-17

(TBD.)

## v9.C · `new bootstrap` domain-registration prompt + portfolio.json auto-update — shipped 2026-05-17

(TBD.)

## v9.B · `new bootstrap` interactive operator-input prompts — shipped 2026-05-17

(TBD.)

## v9.A · Canonical AI_AGENTS section schema + conformance check + tier-1 fix — shipped 2026-05-17

(TBD.)

## v8.J · Adversarial audit payload builder — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.I · Wire primary pass into `new research` orchestrator — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.H · Primary interpretive pass runner — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.G · Primary-pass response parser — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.F · Primary-pass prompt rendering — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.E · Primary-pass payload assembly — shipped 2026-05-17

(TBD — migrate from prd.md § 8.2.)

## v8.D · Research module v2 — shipped 2026-05-14

*Originally inlined as detailed PRD § 8.1 in `docs/prd.md`. Migrated to `shipping-history.md` 2026-05-18 as part of the canonical-doc restructure (ADR-0010).*



### 1. Problem statement

**Current state.** `lamill new research <topic>` asks gpt-4o-mini to
synthesize a SERP analysis from training data. The output looks
authoritative — ranked domains, content patterns, suggested angles,
ship/mixed/skip decision — but the underlying data is the LLM's guess
about what was ranking at training time, biased toward famous domains,
and blind to AI Overview, Reddit threads, news cycles, programmatic
incumbents, and anything that's appeared since the cutoff.

**What's broken.**
1. **Wrong verdicts in real use.** Four recent niche evaluations got
   verdicts that didn't match what the operator (me) discovered when
   I looked at the SERP myself. The tool was telling me "MIXED" on
   niches that should have been NO-GO, and "SKIP" on niches with
   clear lanes available.
2. **Three-state decision conflates different situations.** A SERP
   dominated by a programmatic incumbent reads the same as a SERP
   where Reddit ranks #3 with a discussion-locked intent. Materially
   different verdicts; current output renders them identically as
   "competition is high."
3. **"Suggested angles" generates content ideas, not moats.** First-
   instinct LLM ideas like "focus on regional cost variations" survive
   no scrutiny when tested against the structural-moat question.
4. **Operator constraints absent.** The tool gives the same verdict to
   a writer with credentialed expertise and to a builder running a
   weekly-cadence portfolio. They face different versions of the same
   niche.

**What good looks like.**
- Real SERP data (organic + SERP features) is the input, with a clearly-
  labeled GPT-synthesis fallback for the missing-key / no-budget path.
- Verdicts come from explicit, separately-reasoned gates, not a single
  LLM judgment.
- The operator profile is read on every run and constrains the verdict.
- The output is honest about uncertainty: "Gate 2 fails" is a different
  message from "Gate 2 fails because of programmatic incumbent X," and
  "operator lacks expertise" is a different message from "SERP is too
  competitive."
- When a niche fails, the tool suggests *how to narrow it* (axes:
  segment / geography / persona / use case / depth / moment) rather
  than just rejecting the topic.

---

### 2. Goals and non-goals

**Goals**

- Replace synthesis-as-primary with **real-SERP-as-primary** via
  SerpAPI; keep synthesis as an explicitly-labeled fallback.
- Encode the three-gate framework (Market / SERP / Moat) as the
  decision engine, not a single LLM judgment.
- Add an **operator profile** read at the start of every research run.
- Introduce a three-state verdict (**GO / NICHE-DOWN / NO-GO**) that
  forces the "narrow the wedge" answer to be a first-class output.
- All three phases land behind the existing `lamill new research`
  command — no new top-level surface.

**Non-goals** (deferred — listed for forward-reference, not designed
in v2)

- DR / domain-authority scoring (manual eyeballing is fine at n=1)
- Cross-niche comparison mode (run two probes back-to-back)
- SERP diff / change-over-time snapshots
- Cost-ceiling / revenue projection math
- Auto-generated moat sentences (requires human judgment)
- Cluster generation from real keyword tools (LLM is the cluster source
  for v2; revisit if the limitation bites)

These are explicitly out-of-scope. If they get added later they get
their own PRD.

---

### 3. User journey (me running this on a new niche idea)

```text
$ lamill new research "ev charger installation cost"

[reads operator.yaml from ~/.lamill/operator.yaml]
[loads SERPAPI_KEY from portfolio.env via load_env()]
[LLM expands "ev charger installation cost" into 5 cluster queries]
[for each query: SerpAPI top-10 organic + SERP features]
[runs Gate 1, Gate 2 against the real SERP data]
[Gate 2 detects specialty incumbent — prompts me interactively for Gate 3]
[applies operator-profile constraints]
[emits verdict + suggested reductions]

  Gate 1 (Market):  ✓ PASS  · 12.4K SV after pollution adjustment
                            · 1 of 5 queries polluted (muscle-car spam)

  Gate 2 (SERP):    ✗ FAIL  · notateslaapp.com programmatic incumbent
                              (Tesla updates) — ranks 5/5 cluster queries
                            · reddit.com #3 (discussion intent locked)
                            · 2 results potentially beatable

  Gate 3 (Moat):    Required because Gate 2 detected programmatic incumbent.
                    Enter a one-sentence testable moat (or press Enter to skip):
                    > _

  Operator fit:     ⚠ WARN  · Builder profile + niche rewards content writing
                            · narrow to tool/data wedge instead

  Verdict: NICHE-DOWN
  Suggested reductions:
    1. By segment: drop Tesla, lead with Rivian/Ford (less programmatic crowding)
    2. By depth: focus only on diagnostic-flow integration (tool wedge)
    3. By moment: trigger-based (post-fault) instead of browse-based

  Source: SerpAPI · 5 queries · cached as data/serp/2026-05-14/<hash>.json
```

The interactive Gate 3 prompt is the **only** interactive moment.
Everything else is non-interactive output. The `--json` mode skips
Gate 3's prompt entirely and emits `moat_required: true, moat_provided: null`
so a script can handle it.

---

### 4. Functional requirements (the three phases)

#### Phase 1 — Real SERP data

**P1.1** Add `SERPAPI_KEY` to the `portfolio.env` template **and** to
`apikeys.KNOWN_KEYS` so `lamill settings apikeys list/set` covers it.
Add a `_probe_serpapi()` connectivity check alongside the existing
OpenAI / CrUX / Porkbun / CF probes.

**P1.2** New module `src/portfolio/serp_fetch.py` (or extend `serp.py`)
with `fetch_serp(query: str) -> dict` returning the SerpAPI response
normalized to a stable shape:
```json
{
  "query": "...",
  "fetched_at": "2026-05-14T...",
  "organic_results": [
    {"position": 1, "domain": "...", "url": "...", "title": "...",
     "snippet": "...", "displayed_link": "..."}
  ],
  "features": {
    "ai_overview": {"present": true, "cited_domains": ["..."]},
    "people_also_ask": ["...", "..."],
    "featured_snippet": {"present": false},
    "image_pack": {"present": true},
    "video_pack": {"present": false},
    "local_pack": {"present": false},
    "reddit_card": {"present": true, "position": 3}
  }
}
```

**P1.3** Cache per-query SerpAPI responses to
`data/serp/<YYYY-MM-DD>/<query-hash>.json` (date subdir, hash per query)
so a day's worth of probes cluster naturally and old days can be
archived/dropped. The cluster-level analysis lives at
`data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json` and references
the per-query files. **Schema-version field on every file.**

**P1.4** `--no-cache` re-fetches; default TTL = **30 days** (was 7 in
the original draft — bumped per §8.G.1 to stretch the SerpAPI free-
tier quota; SERPs change but gate-level verdicts don't move weekly).

**P1.5** `--synthesis-only` flag short-circuits to the existing GPT
path. Output banner must say:
```
⚠  source: GPT synthesis (fallback) — NOT REAL SERP DATA
   knowledge cutoff applies, verdicts are heuristic only
```
…and the gates still run, but their results are explicitly tagged
`[from LLM guess]` in the rendered output.

**P1.6** If `SERPAPI_KEY` is missing AND `--synthesis-only` is not set,
emit a one-line error pointing at `lamill settings apikeys set
SERPAPI_KEY` and exit 2. Don't silently fall back — that's the bug
the current tool has.

**P1.7** If SerpAPI request fails (rate limit, network, 5xx), retry
once, then fall back to synthesis-only mode with a loud warning. The
cached output of the failed query path is NOT written, so the next
run retries.

#### Phase 2 — Three-gate decision logic

**P2.1** New module `src/portfolio/research_gates.py`. Pure logic —
takes a cluster-level dict (output of Phase 1's fetch + LLM cluster
expansion) and returns a `GateResults` dataclass:

```python
@dataclass
class GateResult:
    passed: bool | None    # None = "pending input" (Gate 3 before prompt)
    label: str             # "PASS" | "FAIL" | "PENDING"
    findings: list[str]    # bullet-point reasons, rendered in output
    raw: dict              # debug / json mode

@dataclass
class GateResults:
    gate_1_market: GateResult
    gate_2_serp: GateResult
    gate_3_moat: GateResult
    operator_fit: OperatorFitResult
    verdict: str           # "GO" | "NICHE-DOWN" | "NO-GO"
    suggested_reductions: list[str]
    moat_required: bool
    moat_provided: str | None
```

**P2.2 — Gate 1 (Market):**
- For each cluster query, get a per-query volume estimate (see Open
  Question §8.A — we don't have real volume out of the box).
- **Pollution detection:** for each query, check whether the top-3
  organic result titles contain at least one keyword stem from the
  cluster (defined as: tokenized cluster query, lowercased, stopwords
  removed, simple Porter-stem-equivalent — implementation may use a
  light-weight `re`-based stemmer rather than nltk).
- A query is "polluted" if 0/3 of its top results stem-match the
  cluster.
- `pollution_adjusted_volume = sum_of_unpolluted_query_volumes`
- **Gate 1 PASS** if pollution-adjusted ≥ 5K SV/month. **FAIL** else.

**P2.3 — Gate 2 (SERP):** Classify each top-10 domain in the merged
cluster:

| Classifier | Detection rule |
|---|---|
| `SPECIALTY_INCUMBENT` | Domain ranks for ≥1 query AND URL matches programmatic-pattern regex (`/(?:19\|20)\d{2}/`, `/v\d+\b/`, `/[A-Z]{2}/(?:state)/`, `/[a-z\-]+(?:city\|town)/`, `/(?:model\|version)/[a-z0-9\-]+`) AND domain is not media/Reddit/manufacturer (see §8.D for the major-media allow-list resolution) |
| `PROGRAMMATIC_AT_SCALE` | Same domain in 3+ cluster queries' top-10 with similar URL templates |
| `MEDIA_LOCKED` | ≥2 cluster queries return a result from the major-industry-media list (§8.D) in top 10 |
| `REDDIT_PRESENT` | `reddit.com` in any cluster query's top 10 |
| `BRANDED_LOCKED` | For branded queries (detected via the cluster including a known brand term), the brand's own domain is top 3 |
| `AI_OVERVIEW_DOMINANT` | `ai_overview.present == True` on ≥2 cluster queries |
| `POTENTIALLY_BEATABLE` | A ranking domain not matching any of the above, with weak signals (no `wikipedia.org` link in their SERP entry, no obvious institutional name) |

**Gate 2 FAIL** if ANY of the following:
- `SPECIALTY_INCUMBENT` or `PROGRAMMATIC_AT_SCALE` detected
- `REDDIT_PRESENT` AND `MEDIA_LOCKED` (both intents locked)
- `AI_OVERVIEW_DOMINANT` alone

**Gate 2 PASS** if ≥3 `POTENTIALLY_BEATABLE` results AND no kill-tier
classifiers fire.

Otherwise: **WEAK PASS** — passes but the findings list flags the
specific lock that would force a niche-down.

**P2.4 — Gate 3 (Moat):** Only required if Gate 2 detected
`SPECIALTY_INCUMBENT` or `PROGRAMMATIC_AT_SCALE`. The tool prints:

```
Gate 3 (Moat): Required because Gate 2 detected a specialty incumbent.
Format: "I will win on [query pattern] because [incumbent gap], and the
incumbent cannot close this gap in 6 months because [structural reason]."

Enter your moat sentence (or press Enter to skip and accept NO-GO):
> _
```

If the user enters a sentence, Gate 3 = PASS and the sentence is
stored in the snapshot. If the user presses Enter, Gate 3 = FAIL.

In `--non-interactive` or `--json` mode, Gate 3 = `PENDING` and the
verdict accounts for it as if it had failed (the user can re-run
without `--non-interactive` to fill in).

**P2.5 — Verdict synthesis:**

| Gates | Verdict |
|---|---|
| Gate 1 FAIL | **NO-GO** (market too small) |
| Gate 2 FAIL AND Gate 3 PROVIDED | **NICHE-DOWN** (moat acknowledged, narrow the scope) |
| Gate 2 FAIL AND no moat | **NO-GO** |
| Gate 1 PASS + Gate 2 WEAK-PASS + Gate 3 not required | **NICHE-DOWN** (the "weak pass" findings drive the reductions) |
| All gates PASS | **GO** |

**P2.6 — Suggested reductions** (when verdict = NICHE-DOWN): emit 2-3
concrete reductions across these axes, generated by the LLM given the
gate findings as context:

- segment (drop a brand, vertical, sub-category)
- geography (regional only)
- persona (specific role / experience level)
- use case (one task vs the full workflow)
- depth (tool vs content, data vs explanation)
- moment (triggered vs evergreen, post-event vs browse)

**P2.7** Remove the existing `ship | mixed | skip | unclear` decision
field from snapshots. Mark this as a breaking schema change; the
schema version bumps from `v8.B` to `v8.C-research-v2`. Old caches
become invalid and get re-fetched on next access.

#### Phase 3 — Operator profile

**Location decided 2026-05-16:** profile lives at
`sites/portfolio/lamill.toml` under an `[operator]` section (same TOML
file v9.A specifies for per-site deploy declarations — see §8.3 §4.1
for the schema). NOT at `~/.lamill/operator.yaml`. Visible, in-repo,
one file per operator. Loader reads `[operator]` keys from the
portfolio repo's `lamill.toml`; absent file or section → defaults
(`expertise=[], workflow_preference="mixed", motivation_cadence="monthly"`).
The original P3.1 spec below is preserved for historical context; the
TOML schema replaces the YAML one.

**Three fields actually wired** (rest from the original spec dropped
as unused): `expertise[]`, `workflow_preference`, `motivation_cadence`.
`hours_per_week`, `budget_monthly`, and `existing_fleet[]` from the
original spec are dropped — never referenced by any gate, and
`existing_fleet` is already derivable from `data/portfolio.json`.

**P3.1** ~~New file at `~/.lamill/operator.yaml`~~ (or alternative — see
Open Question §8.B). Schema (proposed):

```yaml
expertise:
  - SEO and programmatic content
  - Python and CLI tooling
  - Domain portfolio management
workflow_preference: builder    # builder | writer | mixed
motivation_cadence: weekly      # weekly | monthly | quarterly
hours_per_week: 10
budget_monthly: 100
existing_fleet:
  - hybridautopart.com
  - voltloop.site
  - lamill.io
```

**P3.2** `OperatorProfile` dataclass + loader in
`src/portfolio/operator_profile.py`. Loader returns an empty profile
(all fields = None / empty lists) if the file is missing — tool still
runs, just without operator-fit gates.

**P3.3** New CLI surface: `lamill settings operator show | edit`.
- `show` prints the loaded profile (or "no profile configured").
- `edit` opens the file in `$EDITOR` (creates it from a template if
  absent).

**P3.4 — Operator-fit constraints (applied after Gate 2):**

- **Expertise check:** if the cluster's primary intent is `informational`
  (≥3/5 queries) AND the SERP rewards E-E-A-T (heuristic: ≥3/10 top
  organic results are institutional or publisher-listicle with named
  authors visible in snippet) AND none of the cluster's primary topic
  terms (extracted via simple noun-phrase split) appear in
  `operator.expertise[]`, then **auto-fail Gate 2** with the finding:
  > "Operator lacks declared expertise; narrow to tool/data wedge."

- **Workflow check:** if `workflow_preference == "builder"` AND the
  cluster has ≥3/5 queries returning publisher-listicle-dominant SERPs
  (content writing rewarded), emit a warning (doesn't fail Gate 2 by
  itself, but adds a `niche-down` finding):
  > "Builder profile + niche rewards content. Narrow to tool wedge."

- **Cadence check:** if `motivation_cadence == "weekly"` AND the
  cluster's intent is "evergreen reference" (proxy: top results are
  >2 years old by visible date), warn:
  > "Cadence: weekly. Niche metrics move monthly+. Watch motivation."

- **Fleet adjacency:** for each of `operator.existing_fleet`, check
  whether the SERP's top-10 includes that domain or whether its
  `lamill fleet info summary` category matches the cluster's topic.
  If yes, surface as a finding:
  > "Adjacent to your existing hybridautopart.com (DR-equivalent in
  >  the auto-repair vertical). Consider extending vs starting fresh."

**P3.5** All operator-fit findings render under a separate
"Operator fit" section in the output, between Gate 3 and the verdict.
They influence the verdict (auto-fail Gate 2 or add reductions) but
don't replace Gate 2.

---

### 5. Data model changes

#### Per-query SerpAPI snapshot (new, Phase 1)

`data/serp/<YYYY-MM-DD>/<query-hash>.json`:
```json
{
  "schema": "serp-query-v1",
  "query": "ev charger installation cost",
  "query_hash": "<12-char-sha256>",
  "fetched_at": "2026-05-14T19:00:00+00:00",
  "source": "serpapi",
  "organic_results": [ /* see P1.2 */ ],
  "features": { /* see P1.2 */ }
}
```

#### Cluster analysis snapshot (refactor, Phase 1+2)

`data/serp/<YYYY-MM-DD>/clusters/<cluster-hash>.json`:
```json
{
  "schema": "research-cluster-v2",
  "topic": "ev charger installation cost",
  "topic_hash": "...",
  "fetched_at": "...",
  "source": "serpapi",                     // or "gpt-synthesis-fallback"
  "knowledge_caveat": "...",               // present only if source = gpt-...
  "cluster_queries": [...],
  "per_query_files": ["<query-hash>.json", ...],
  "operator_snapshot": { /* copy of operator.yaml at probe time */ },
  "gates": {
    "gate_1_market": {
      "passed": true,
      "label": "PASS",
      "findings": ["12.4K SV after pollution adjustment", "..."],
      "raw": {"pollution_adjusted_volume": 12400, "polluted_queries": [...]}
    },
    "gate_2_serp": {
      "passed": false,
      "label": "FAIL",
      "findings": [...],
      "raw": {"classifications": {...}}
    },
    "gate_3_moat": {
      "passed": null,
      "label": "PENDING",
      "findings": [],
      "raw": {}
    }
  },
  "operator_fit": {
    "warnings": [...],
    "auto_fail_gate_2": false
  },
  "verdict": "NICHE-DOWN",                 // GO | NICHE-DOWN | NO-GO
  "suggested_reductions": [...],
  "moat_required": true,
  "moat_provided": null
}
```

#### Removed fields

These v8.B fields disappear from the cluster snapshot:
- `analysis.decision` (replaced by `verdict`)
- `analysis.top_likely_rankers` (replaced by per-query files +
  classifications)
- `analysis.competitive_signal` (replaced by gate findings)
- `analysis.suggested_angles` (replaced by `suggested_reductions`
  which is only present when verdict = NICHE-DOWN)
- `mode` (no more `cluster | strict`; cluster is the only mode)

Old caches are invalidated on schema-version mismatch (see P2.7).

---

### 6. Config schema

#### portfolio.env (existing, additive)

Append to the auto-generated template in `suggest.py:ensure_portfolio_env()`:
```
## v8.C — SerpAPI key for real-SERP research (lamill new research).
## Plan: $50/mo for SerpAPI's "Bronze" tier (5000 queries/mo). Sign up
## at https://serpapi.com/. Leave blank to use --synthesis-only fallback.
SERPAPI_KEY=
```

#### ~/.lamill/operator.yaml (new, Phase 3)

See P3.1 above. Defaults if the file is missing:

```python
OperatorProfile(
    expertise=[],
    workflow_preference="mixed",   # least-opinionated default
    motivation_cadence="monthly",  # mid
    hours_per_week=None,
    budget_monthly=None,
    existing_fleet=[],             # loaded separately from portfolio.json fallback
)
```

If `existing_fleet` is empty in operator.yaml, the loader falls back to
the canonical inventory (every domain in `data/portfolio.json` whose
category is NOT in `IGNORE_CATEGORIES`).

---

### 7. Output format (target state)

Example output reproduced from §3 above, structurally:

```
SERP research — "<topic>"
  source: SerpAPI · 5 queries · cached 0d ago

  Topic cluster:
    → 1. <literal>
      2. <expanded>
      ... (5 queries total)

  Gate 1 (Market):  ✓ PASS  · <volume> SV after pollution adjustment
                            · <N> of 5 queries polluted (<reason>)

  Gate 2 (SERP):    ✗ FAIL  · <classifier-finding-1>
                            · <classifier-finding-2>
                            · <N> results potentially beatable

  Gate 3 (Moat):    [pending operator input | PASS | FAIL]
                    [moat sentence echoed back if provided]

  Operator fit:     ⚠ WARN  · <fit-finding-1>
                            · <fit-finding-2>

  Verdict: <GO | NICHE-DOWN | NO-GO>

  Suggested reductions:  (only if verdict = NICHE-DOWN)
    1. <reduction-1>
    2. <reduction-2>
    3. <reduction-3>

  Source: SerpAPI · cached as data/serp/<date>/<hash>.json
```

`--brief` collapses to one-line per gate + verdict + 2 reductions.
`--json` emits the full cluster-snapshot JSON shape from §5.

---

### 8. Open questions to resolve before implementation

These are questions where the prompt's spec is under-specified or where
existing-code constraints conflict with the spec. **Resolve these
before any code lands.**

#### 8.A — Volume data source

The spec requires Gate 1 to fail when "pollution-adjusted volume <
5K SV/month." **SerpAPI's organic-search endpoint does not return
search volume.** Three options:

1. **Skip real volume entirely.** Use LLM volume estimates as proxy
   (acknowledged unreliable). Gate 1 becomes "LLM estimates X SV;
   confidence: low."
2. **SerpAPI's keyword research add-on** (~+$100/mo). Real volume data
   from Google Ads-style sources. Doubles SerpAPI bill.
3. **Use a free volume proxy** — e.g., the count of unique organic
   results in top 100 (deep results = high-volume signal), or Google
   autocomplete suggestion count, or Reddit/forum mention count via
   SerpAPI's Reddit search. Heuristic, but free.

**My recommendation: option 3 + label honestly as a proxy.** Avoids
the cost bump and gives a usable signal. Real volume becomes a future
upgrade with its own PRD.

**Your call:** which option?

#### 8.B — Operator config location

Spec says `~/.lamill/operator.yaml`. Existing convention is per-project
config in `portfolio.env` at the repo root. Three options:

1. **Global at `~/.lamill/operator.yaml`** (per the spec) — fits the
   "this is about me, not the repo" framing, but breaks the
   everything-in-the-repo pattern.
2. **Per-project at `<repo>/operator.yaml`** — fits existing pattern,
   makes the config part of the lamill repo, easier to version.
3. **Hybrid: load `<repo>/operator.yaml` if present, else fall back to
   `~/.lamill/operator.yaml`** — supports both patterns.

**My recommendation: option 1 (global at `~/.lamill/`).** Operator
profile is genuinely about the person, not the repo. Lives outside the
repo for a reason. The existing per-project pattern is the right
default for things like API keys; operator-profile is a different kind
of config.

#### 8.C — Config file format (YAML vs TOML vs JSON)

No YAML lib in the codebase today. Adding pyyaml is a new dep.

1. **YAML** (per spec) — most human-friendly, but adds pyyaml dep
2. **TOML** — Python 3.11+ stdlib via `tomllib` (read-only), no new
   dep. Reasonable for read-many-write-rare config.
3. **JSON** — no new dep, no nice config syntax (no comments).

**My recommendation: TOML.** Stdlib, no new dep, supports comments,
and we only need read at runtime (writes happen via `$EDITOR`).

**Your call:** YAML (per spec), TOML, or JSON?

#### 8.D — "Major industry publication" classification source

Gate 2's `MEDIA_LOCKED` classifier requires identifying when a SERP
result is from a major industry publication. Three options:

1. **Static allow-list per topic.** `data/research/media_publications.toml`
   with entries like `automotive: [caranddriver.com, motortrend.com,
   autoweek.com, ...]`. Pro: deterministic. Con: requires curation; new
   topics need updates.
2. **LLM classification.** Send each ranking domain to gpt-4o-mini:
   "Is <domain> a major industry publication in <topic-vertical>?
   yes/no." Pro: flexible. Con: reintroduces LLM at a critical signal
   point, adds ~10 calls per research run.
3. **Heuristic:** check domain via `tldextract` + `data/portfolio.json`
   manual flags + Wikipedia API "does this domain have a Wikipedia
   article?" Pro: free, structural. Con: not all major pubs have WP
   articles; complex.

**My recommendation: option 1 (static allow-list).** It's the
operator's tool, the operator can maintain it. Seeded with ~20 verticals
covering my fleet (automotive, EV, HVAC, indoor air, cricket, …); add
more as new verticals appear. List is data, not code; lives in
`data/research/media_publications.toml`.

**Your call:** confirm option 1 or pick differently.

#### 8.E — Snapshot retention policy

Per-query files at `data/serp/<YYYY-MM-DD>/<query-hash>.json` could
accumulate quickly. Three options:

1. **Keep forever.** Same as `data/checks/` and `data/seo/`. Disk usage
   is fine at personal scale (probably < 100MB/yr).
2. **Auto-trim after N days.** Delete date subdirs older than 90 days.
3. **No git-tracking.** Add `data/serp/` to `.gitignore`. Snapshots
   become local-only.

The current `data/checks/`, `data/seo/`, and `data/serp/` are all
git-tracked (we explicitly chose this for v8.A so trend analysis can
read history).

**My recommendation: option 1 (keep forever, git-tracked).** Disk
isn't a constraint; trend data is valuable when a future feature wants
"how has the SERP for X changed in 6 months?"

**Your call:** confirm or change.

#### 8.F — `--synthesis-only` and the three-gate logic

Synthesis-only mode runs the gates from LLM-guessed data instead of
real SERP. Gate 2's URL-pattern detection collapses (LLM doesn't return
real URLs — just domain names). Two options:

1. **Run gates anyway** with a loud "[from LLM guess]" tag on every
   finding. Gate 2 mostly skips URL-pattern detection, relies more on
   LLM's qualitative judgment of "is this a programmatic incumbent
   pattern?"
2. **Skip Gate 2 entirely in synthesis-only mode** and emit only Gate
   1 + Gate 3 + operator fit. Verdict becomes mostly operator-fit-driven.

**My recommendation: option 1.** Synthesis-only is for ideation, not
go/no-go. Running degraded gates with explicit tags is better than
hiding them — the user is reminded that the synthesis output is less
trustworthy.

#### 8.G — SerpAPI tier / cost expectations  *(RESOLVED 2026-05-14)*

**Decision:** SerpAPI **free tier** (250 queries/month, no cost).

At 5 queries per cluster, that's ~50 research runs/month. Sufficient
for personal portfolio operator scale (a few cluster runs per week).

Three implications flow from this choice — applied to the PRD below:

**8.G.1 — Cache TTL:** Bumped from 7 days → **30 days** (PRD §P1.4
amended below). SERPs move weekly, but the gate-level verdict
they drive doesn't move with them. A weekly re-fetch would burn
quota without changing the call. `--no-cache` still forces a
fresh probe when needed.

**8.G.2 — Quota tracking:** New ledger at `data/serp/_quota.json`
tracks queries used in the current UTC month. The tool:
  - Soft-warns at 80% (200/250): "⚠ SerpAPI quota: 200/250 this month"
  - Hard-refuses at 100% (250/250): "✗ SerpAPI quota exhausted —
    falling back to synthesis-only mode for this run."
  - Resets at the first day of each UTC month.
  - `lamill settings cost report` (future ledger feature) can read
    this file later.

**8.G.3 — Auto-fallback when quota exhausted:** When the quota refuses
a fresh fetch AND `--no-cache` was not passed AND a v2 cache is
unavailable, the tool **automatically falls back to synthesis-only
mode** with a loud banner:

```
⚠  SerpAPI quota exhausted (250/250 this UTC month).
   Falling back to GPT synthesis — NOT REAL SERP DATA.
   Quota resets <YYYY-MM-01>.
```

Better than failing the run; the operator sees what happened and
gets a degraded-but-useful answer. The synthesis-only result is
cached under a separate cache key so it doesn't pollute the
real-SERP cache when quota returns.

These three implementation details are now part of P1 scope.

#### 8.H — Cache invalidation on schema bump

When the cluster snapshot schema changes from v8.B → v2 (P2.7), the
existing `data/serp/*.json` files become unreadable. Options:

1. **Delete `data/serp/*.json` on first v2 run** with a one-line
   migration note. Cleanest.
2. **Move them to `data/serp/_archive_v8b/`** for forensics.
3. **Try to migrate** the old shape forward. Most fields don't have
   v2 equivalents; this is mostly a no-op.

**My recommendation: option 2.** Move, don't delete. Zero data loss
risk; the archive can be removed later by hand.

#### 8.I — Existing v8.A `--strict` mode

The v8.A literal-topic-only mode (`--strict`) currently exists. The v2
spec doesn't mention it, and the new framework assumes cluster mode
always. Options:

1. **Drop `--strict`** in v2 — cluster is the only mode.
2. **Keep `--strict`** as a parallel path that runs only literal-topic
   SerpAPI + gates on 1 query instead of 5.

**My recommendation: drop `--strict`.** The cluster mode is more useful;
keeping strict around for the rare case adds maintenance burden. If
someone wants literal-topic SerpAPI, they can pass a `--depth 1` flag
later — but for now, drop.

#### 8.J — Volume data fallback when SerpAPI proxy fails

When Gate 1 uses the proxy from Option 3 above (organic-count heuristic
or autocomplete), and the proxy fails for a specific query (e.g.,
SerpAPI returned 0 results — query is too niche), Gate 1 needs a
behavior. Options:

1. **Treat 0-results queries as 0 SV.** Pollution-adjusted volume
   drops; Gate 1 may fail. Honest behavior.
2. **Treat 0-results queries as "unknown SV"** and pass the gate if
   ≥3 of 5 queries have data. Less honest but more forgiving.

**My recommendation: option 1.** Honest about the gap.

---

### 9. Implementation plan (commit-by-commit, with smoke tests)

#### Preamble commit (zero-risk refactor)

**Commit P0** — Move `data/serp/*.json` and `data/serp/_index.json`
into `data/serp/_archive_v8b/`. Update `serp.py` to point at the
archive read-only for `lamill new research --replay-cache <topic>` (a
debugging flag — not user-facing). Sets up the migration path before
schema changes.

*Smoke test:* `lamill new research "anything" --synthesis-only` still
works (uses LLM, doesn't touch the archived caches).

---

#### Phase 1 commits

**Add `SERPAPI_KEY` to `KNOWN_KEYS` + portfolio.env
template + connectivity probe in `apikeys.py`. Update
`lamill settings apikeys list` to report it.

*Smoke test:* `lamill settings apikeys list` shows SERPAPI_KEY as
"unset" or "set + connectivity ✓".

**`src/portfolio/serp_fetch.py` with `fetch_serp(query)`
returning the normalized shape from P1.2. Includes retry logic,
SerpAPI-error to ResearchError mapping. No CLI wiring yet.

*Smoke test:* `python -c "from portfolio.serp_fetch import fetch_serp;
import json; print(json.dumps(fetch_serp('ev charger installation cost'),
indent=2)[:500])"` returns a real SERP. Required: SERPAPI_KEY set.

**Per-query caching to `data/serp/<YYYY-MM-DD>/<query-
hash>.json` with `schema: serp-query-v1`. `load_cached_query(query,
ttl_days=7)`, `save_cached_query(...)`. Tests against tmp_path.

*Smoke test:* `pytest tests/test_serp_fetch.py -q` (~10 new tests).

**Refactor `serp.py:research()` to: (a) load the
cluster query list from gpt-4o-mini (existing code), (b) for each
query, call `fetch_serp()`, (c) cache + return a NEW cluster snapshot
shape that's just the per-query results merged (no gates yet, no
verdict — that's Phase 2). Synthesis-only path preserved behind
flag, marked clearly.

*Smoke test:* `lamill new research "ev charger installation cost"`
runs end-to-end against SerpAPI, writes one cluster file + 5 per-query
files, output shows raw SERP data (no gates).

**`--synthesis-only` flag wired with loud banner.
`--no-cache` re-fetches both LLM cluster expansion AND per-query SERPs.
Error paths (missing key, SerpAPI 5xx, rate limit) tested.

*Smoke test:* `lamill new research "test" --synthesis-only` shows
banner; `lamill new research "test" --no-cache` re-fetches; missing
SERPAPI_KEY errors with the right pointer.

**Quota ledger at `data/serp/_quota.json` (per §8.G.2).
Tracks queries used in the current UTC month; auto-resets on
month-boundary. Soft-warns at 200/250; hard-refuses at 250/250 with
auto-fallback to synthesis-only mode (loud banner per §8.G.3). New
helper `lamill settings serpapi-quota` shows current usage.

*Smoke test:* Mock a 251st-query call → fallback banner shown,
synthesis-only output produced; ledger reset on simulated month
change.

#### Phase 2 commits

**`src/portfolio/research_gates.py` skeleton:
dataclasses (`GateResult`, `GateResults`), `evaluate_gate_1(cluster)`,
`evaluate_gate_2(cluster)`, `evaluate_gate_3(cluster, moat_input)`.
Pure logic, no CLI. Unit tests with synthetic cluster fixtures.

*Smoke test:* `pytest tests/test_research_gates.py -q` (~25 tests).

**Gate 1 (Market) — volume estimate via the chosen
proxy (§8.A), pollution detection, pollution-adjusted volume math.
Unit tests for: clean cluster, polluted cluster, mixed cluster, edge
cases (0 results, all polluted).

*Smoke test:* `lamill new research "ev charger installation cost"
--debug-gates` shows Gate 1 output but skips 2 and 3.

**Gate 2 (SERP) — classifiers in priority order.
Static `media_publications.toml` (§8.D — assuming option 1 chosen)
seeded with ~20 verticals. Programmatic-URL regex library. Tests
cover each classifier individually + combinations.

*Smoke test:* Cluster with known programmatic incumbent (e.g.,
`notateslaapp.com`) → classifier fires; cluster without one → doesn't.

**Gate 3 (Moat) — interactive prompt, snapshot
storage, `--non-interactive`/`--json` mode handling.

*Smoke test:* Running interactively on a cluster that fails Gate 2
prompts for moat; entering text → PASS; Enter → FAIL; `--json` skips.

**Verdict synthesis (§5 table) + suggested-reductions
generator (LLM call with the gate findings as context). Renderer
updated to show gates + verdict + reductions.

*Smoke test:* `lamill new research "ev charger installation cost"`
end-to-end produces the target output from §3.

**Snapshot schema migrated to v2 (`research-cluster-v2`).
Old `data/serp/*.json` were already archived in P0. Cache invalidation
on schema mismatch. Tests confirm v1 cache is treated as miss.

*Smoke test:* `lamill new research "<previously-cached topic>"` does
NOT serve from a v1 cache; re-fetches fresh.

#### Phase 3 commits

**`src/portfolio/operator_profile.py`:
`OperatorProfile` dataclass, `load_profile()`, `default_profile()`,
TOML-or-YAML reader (§8.C decided). Tests against tmp_path with
synthetic profiles.

*Smoke test:* `pytest tests/test_operator_profile.py -q` (~12 tests).

**`lamill settings operator show` + `edit` CLI
commands.

*Smoke test:* `lamill settings operator show` prints the profile (or
"no profile configured"); `lamill settings operator edit` opens
`$EDITOR`.

**Operator-fit constraints wired into
`research_gates.py`:
- Expertise check (auto-fail Gate 2)
- Workflow check (warning + niche-down trigger)
- Cadence check (warning)
- Fleet adjacency (finding)

Tests for each constraint individually + integration test on a known
cluster + profile combination.

*Smoke test:* `lamill new research "ev charger installation cost"`
with `workflow_preference: builder` in operator.yaml emits the
"Builder profile + niche rewards content" warning.

#### Final commits

**Documentation update:**
- `docs/CLAUDE.md`: brief on the new `new research` flow + operator
  profile location
- `AI_AGENTS.md`: note the v8.C → v2-research-module migration
- `docs/Prompts.md`: dated H2 entry
- `docs/prd.md`: mark v8.C in v8 tier table as ✅ (renamed from the
  dropped one — see PRD note on the redefinition)

*Smoke test:* `lamill project check sites/portfolio` passes the docs
checks; full suite still passes.

**PRD update** — `docs/prd.md` reflects v8.C shipped, feature-table
entries refreshed.

*Smoke test:* manual review.

---

### 10. Effort estimate

Honest reading, not padded, not shrunk:

| Phase | Commits | Estimated hours | Key risks |
|---|---|---|---|
| Preamble | P0 | 1h | Archive migration script |
| Phase 1 |  9–11h | SerpAPI integration, quota ledger + auto-fallback, error paths, retry logic, test coverage |
| Phase 2 |  10–14h | Gate 2 classifier rules, programmatic-URL regex (hard to get right), verdict-synthesis LLM call wired correctly, schema migration |
| Phase 3 |  5–7h | Operator-fit heuristics, especially the expertise check |
| Docs + cleanup | P4 | 1–2h | |
| **Total** | **16 commits** | **26–35h** | (+1h vs original estimate for quota ledger work) |

The wider range comes from Gate 2 — the classifier rules will need
iteration once real-SERP data shows edge cases. Plan for ≥2 rounds
of refinement after the verdict-synthesis commit lands.

Critique-suggested 12–15h was optimistic. It didn't account for the
volume-data problem (§8.A), the operator-profile gates (Phase 3), or
test work proper.

---

### 11. Future considerations (deferred, named only)

For forward-reference, in case any of these become relevant later:

- Real-time keyword volume via SerpAPI keyword add-on or DataForSEO
- DR / domain-authority scoring (Ahrefs / Moz API)
- Cross-niche comparison mode
- SERP diff / snapshot tracking over time
- Cost-ceiling / revenue projection math
- Auto-generated moat sentences (would need a moat-validator LLM step)
- Cluster generation from real keyword tools (Google autocomplete,
  Ahrefs related terms, People Also Ask scraping)
- Operator-profile inference from `data/portfolio.json` (auto-detect
  existing fleet, infer expertise from `docs/CLAUDE.md` files across
  the fleet)
- A `lamill new research --watch <topic>` mode that re-runs weekly and
  surfaces SERP changes

These are explicitly NOT designed in v2.

---

### 12. Recommended preamble refactor (NOT part of v2)

While reading the existing code I noticed a small refactor that would
make v2 cleaner but is NOT required:

- `src/portfolio/serp.py` is 673 LOC and mixes: prompt building, OpenAI
  HTTP, cache I/O, response parsing, orchestrator. Could be split into
  `serp_llm.py` (prompt + OpenAI), `serp_cache.py` (I/O), and
  `research.py` (orchestrator + the new gates module). This would
  parallel the existing pattern of `seo_runtime.py` + `seo_cache.py`.

Not required for v2 to ship — the existing code is workable. But if
the v2 work gets close to ~900 LOC in one file, the split becomes
worth doing.

---

### 13. Approval

This PRD is **draft, awaiting review**. Before any code lands:

1. Resolve the 10 open questions in §8.
2. Confirm the 3-phase scope is right (no expansion).
3. Confirm the effort estimate is acceptable for the value delivered.
4. Confirm the snapshot retention policy (§8.E).

Sign off below when reviewed:

- [ ] Open questions §8.A–J resolved
- [ ] Effort estimate accepted
- [ ] Preamble refactor (§12) — yes or no
- [ ] Author signoff

---

---

## v8.B · Multi-keyword cluster mode — absorbed by v8.D 2026-05-14

(One-line note; full rationale archived under v8.D.)

## v8.A · `new research <topic>` core command — absorbed by v8.D 2026-05-14

(One-line note; full rationale archived under v8.D.)

## v7.H · GSC sitemap health + dark-site detection + CF edge-cache — shipped 2026-05-16

(TBD — brief rationale; this phase shipped as a tight cluster around
the donready.xyz sitemap-could-not-be-read incident.)

## v7.G · Tool rename `portfolio` → `lamill` (light) — shipped 2026-05-13

(TBD — entry point alias decision; heavier rename deferred.)

## v7.F · `project diagnose <domain>` — shipped 2026-05-13

(TBD.)

## v7.E · `fleet repos` audit + naming-consistency cluster — shipped 2026-05-12

(TBD.)

## v7.D · `fleet focus` enhancements + age-aware SEO grading — shipped 2026-05-11

(TBD.)

## v7.C · Age tracking (launched + RDAP) — shipped 2026-05-11

(TBD.)

## v7.B · `fleet dashboard` — unified live + SEO + git view — shipped 2026-05-10

(TBD.)

## v7.A · CLI restructure to scope-first — shipped 2026-05-10

(TBD — major restructure aligned across two design sessions; rename
map from old `info status` / `check git` / `focus` etc. into the
new `project` / `fleet` / `new` / `settings` namespaces.)

## v6.G · Fleetwide `project fix --all` — shipped 2026-05-09

(TBD.)

## v6.E · Remediation Tier 2 + co-located fixer architecture — shipped 2026-05-09

(TBD — two pieces: architecture migration from centralized
`fixers.py` / `ai_fixers.py` to per-check co-location; Tier 2 wired
live with Claude subprocess.)

## v6.D · Remediation Tier 1 (second project-dir write surface) — shipped 2026-05-09

(TBD — 16 templated fixers; dry-run by default; `--apply` to write;
idempotent.)

## v6.C · Per-stack rules — submodules + gitignore-build-output — shipped 2026-05-09

(TBD.)

## v6.B · Catalog↔bootstrap reconciliation — shipped 2026-05-09

(TBD — CHECK_013 added; seven day-zero failure gaps closed in
bootstrap output.)

## v6.A · Drift detection (`info drift`) — shipped 2026-05-09

(TBD.)

## v5.I · Content-pipeline checks (CHECK_130–137) — shipped 2026-05-09

(TBD.)

## v5.H · check live/git/seo as real subcommands — shipped 2026-05-09

(TBD.)

## v5.G · focus + SEO cache + menu-trim follow-ups — shipped 2026-05-09

(TBD.)

## v5.F · CLI structure four-group rename — shipped 2026-05-09

(TBD.)

## v5.E · Refactor `project status` onto catalog — shipped 2026-05-09

(TBD.)

## v5.D · `check --seo` (live HTTP + GSC + CrUX) — shipped 2026-05-09

(TBD.)

## v5.C · Stack/deploy/SEO checks (CHECK_025–080) — shipped 2026-05-09

(TBD.)

## v5.B · `check --git` command — shipped 2026-05-09

(TBD.)

## v5.A · Universal check catalog foundation — shipped 2026-05-09

(TBD — absorbed old v6 GSC integration and old v7 stack detection.)

## v4 phases (v4.A–v4.D) — shipped 2026-05-08

(TBD — bundled entry covering the validation-pipeline arc:
shortlist, decide-from-shortlist, widen + ask AI, interactive launcher.)

## v3 phases (v3.A–v3.E) — shipped 2026-05-07 / 2026-05-08

(TBD — bootstrap + SEO baseline + deploy abstraction + validation-mode
suggest + post-grid menu polish.)

## v2 phases (v2.A–v2.B) — shipped 2026-05-04

(TBD — multi-strategy brainstorm + Porkbun availability/pricing.)

## v1 phases (v1.A–v1.F) — shipped 2026-04-28 / 2026-05-04

(TBD — bundled entry covering the skeleton, full git pulse, registrar
consolidation, cleanup migration, NLP skill, parked-detection.)

---

## See also

- `docs/prd.md` — current spec (active phases only).
- `docs/architecture.md` — current mechanisms, schemas, modules.
- `docs/CLAUDE.md` — Claude-specific decisions.
- `AI_AGENTS.md` — agent orientation; canonical versioning rule.
