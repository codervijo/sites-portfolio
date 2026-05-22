# SEO check improvements — scoping note

**Date:** 2026-05-21
**Status:** ✅ Decided — **Option 1 (drop entirely)**. v17 moved to operator's separate SEO pipeline project.
**Owner:** Operator.

## Why this file exists

v17 was scoped 2026-05-19 as "SEO check expansion — 14 new universal
checks (foundational-tag enrichment, robustness, live-runtime) plus
a WordPress-specific lane." During 2026-05-21 planning the operator
flagged the concern that *most of these belong in the SEO pipeline,
not in this tool* — the same shape of feature creep that killed
v16's original B/C/E and v18.C-F (audits dropped them as UI
reinvention per `docs/prd.md § 2 Non-goals`).

This file captures the audit so the decision isn't re-debated from
scratch later.

## The framing question

> Does `portfolio` (this CLI) earn its keep on each proposed v17
> check, or are we re-implementing what Lighthouse / Yoast /
> Screaming Frog / Ahrefs / Google PageSpeed Insights already do?

The tool's edge over generic SEO scanners — the only justification
for owning these checks — is:

  1. **Pre-deploy enforcement.** A check that catches a defect *before*
     the site ships beats a post-deploy SEO scanner that surfaces it
     after Google has indexed.
  2. **Cross-fleet rollup.** No third-party SEO tool gives the
     operator a single-table view across all ~30 personal-portfolio
     domains. `fleet check` does.
  3. **Conformance gates with auto-remediation.** `project fix` can
     write back into the codebase. SEO tools just report.

A v17 check earns its place only if it leverages at least one of
those three angles. Otherwise it's a Lighthouse-audit duplicate
with a maintenance burden.

## The 14 v17 checks scored

| Check | Portfolio-unique? | Why / why not |
|---|---|---|
| `CHECK_081` title-length-in-range (30-65) | ❌ | Lighthouse SEO audit catches it post-deploy; no rollup angle |
| `CHECK_082` exactly-one-h1 | ❌ | Lighthouse |
| `CHECK_083` og-completeness | ❌ | Every SEO tool |
| `CHECK_084` json-ld-org-has-logo-and-sameAs | ❌ | Schema.org validator |
| `CHECK_085` canonical-points-to-prod-https | ✅ | **Pre-deploy** matters — catches staging/localhost URLs in canonical before they ship |
| `CHECK_086` no-noindex-on-prod | ✅ | **Pre-deploy** — catches the "left noindex on" footgun before launch |
| `CHECK_087` image-alt-coverage (≥80%) | ❌ | Lighthouse a11y audit |
| `CHECK_088` twitter-card-type-set | ❌ | Every SEO tool |
| `CHECK_096` https-only (no mixed content) | ❌ | Browser DevTools, Lighthouse |
| `CHECK_097` 404 returns proper status (not soft-200) | ❌ | Site audit tools |
| `CHECK_098` sitemap-URLs all return 200 | ⚠️ marginal | Site audit tools do this single-site; cross-fleet rollup is unique |
| `CHECK_099` sitemap-freshness (lastmod ≤90d) | ⚠️ marginal | GSC + sitemap analyzers do single-site; **fleet rollup** is unique |
| `CHECK_100` robots-allows-crawling (no global `Disallow: /`) | ✅ | **Pre-deploy** — catches `Disallow: /` left over from dev |
| `CHECK_101` apex/www redirect symmetry | ✅ | DNS-aware; portfolio already owns DNS context via lamill.toml |
| `CHECK_102` yoast-or-rankmath-present | ❌ | Yoast itself does this |
| `CHECK_103` no-yoast-rankmath-conflict | ❌ | Yoast/RankMath ship the same detection |
| `CHECK_104` wp-jsonld-website-with-searchaction | ❌ | Yoast emits this by default |
| `CHECK_105` wp-oembed-cleanup | ❌ | Standard WP-perf plugin territory |

**Tally:** 4 clear ✅ (085, 086, 100, 101) + 2 marginal ⚠️ (098, 099)
+ 8 clear ❌ (the rest).

## Three reshape options

In order of how aggressively to cut:

### Option 1 — Drop v17 entirely

Same judgment call as v16's original B/C/E and v18.C-F. Tool stays
focused on lifecycle/deploy + the existing 24 checks. SEO surface
validation lives elsewhere — Lighthouse CI in the build pipeline,
Yoast on WP sites, GSC for index status.

  - **Effort saved:** 7-9h
  - **Cost:** the 4 pre-deploy gates (085 / 086 / 100 / 101) don't
    get caught at all — operator relies on memory + reading the code
    before push.

### Option 2 — Slim v17 to the pre-deploy / fleet-unique core (RECOMMENDED)

Rename: "v17 — pre-deploy launch gates" (was "SEO check expansion").
Ship only the checks that exercise portfolio's actual edge:

  - `CHECK_085` canonical-points-to-prod-https
  - `CHECK_086` no-noindex-on-prod
  - `CHECK_100` robots-allows-crawling
  - `CHECK_101` apex/www redirect symmetry
  - Optionally one of `CHECK_098` / `CHECK_099` (the fleet-rollup
    angle is the marginal-but-real argument)

Phases would compress to v17.A (kickoff) + v17.B (the 4-5 checks
together) — drop the per-category split (B/C/D/E) since the slimmed
set doesn't span enough categories to warrant it.

  - **Effort:** ~2h instead of ~7-9h
  - **Cost:** ⅔ of the original 14 checks don't ship. Acceptable
    because they have authoritative implementations elsewhere.

### Option 3 — Keep v17 as currently scoped

Accept the duplication for the sake of having one tool that runs
the whole conformance bar pre-deploy.

  - **Effort:** ~7-9h (per current PRD)
  - **Cost:** Maintenance burden on 14 checks that drift relative
    to Lighthouse / Yoast / GSC over time. Direct contradiction of
    the § 2 Non-goals audit that already killed similar scope in
    v16 and v18.

## Recommendation

**Option 2.** Renames v17 to reflect what it actually is
(pre-deploy launch gates, not generic SEO checks). Preserves
portfolio's stated edge over third-party tools. Falls inside the
§ 2 Non-goals discipline that has already shaped v13, v16, v18.

## Adjacent observation

If the operator is already running Lighthouse CI somewhere in the
build pipeline, `fleet check` could *consume* its output instead of
reimplementing the same scans:

  - Read `dist/lighthouse-report.json` (or similar) emitted by the
    build.
  - Lift the relevant SEO/a11y findings into a `fleet check` column.
  - No new HTTP fetching from portfolio's side; the SEO tool stays
    authoritative.

This is the same compositional posture as v16.D's GSC consumption
(read the GSC API; don't re-implement search-console). Worth a
separate v?-tier proposal if Option 2 ships and the gap remains.

## Decision log

  - 2026-05-19 — v17 scoped as "SEO check expansion · 14 checks"
  - 2026-05-21 — operator flagged "this may be more for the seo
    pipeline, doesn't fit the purpose of this tool"
  - 2026-05-21 — audit done; Option 2 recommended by Claude;
    captured here for the operator's actual call
  - **2026-05-21 — Operator chose Option 1.** Dropped from portfolio
    entirely; moved to operator's separate SEO pipeline project.
    `docs/prd.md § v17` now a reserved/dropped single-line
    placeholder matching the v20 / v22 pattern.
    `docs/architecture.md § Projected CLI surface` had its v17.B-E
    row removed. `docs/bugs.md` had no v17 entries to scrub.

## Resurface conditions

This decision is *not* irreversible. Reopen if any of these become
true:

  - Portfolio gains a pre-deploy framing that earns the 4-5
    portfolio-unique gates back (CHECK_085 canonical-points-to-prod,
    CHECK_086 no-noindex-on-prod, CHECK_100 robots-allows-crawl,
    CHECK_101 apex/www redirect symmetry — all "catch the dev-leftover
    before it ships" checks).
  - The Lighthouse-CI-consumer adjacent posture (consume the build's
    `dist/lighthouse-report.json` into `fleet check` output) gets
    proposed in its own right — that one IS portfolio-shaped (rollup
    over a fleet of single-site reports).
  - The SEO pipeline project lands these and the operator wants
    `fleet check` to surface the pipeline's verdict as a column.

## Next action

None on the SEO-check scoping. SEO check work happens in the operator's
separate pipeline project from here on.

---

## Open question (2026-05-21) — GA4 property creation: portfolio lifecycle or SEO pipeline?

The Google Analytics Admin API supports automated property creation:

```
POST /v1beta/accounts/{account}/properties
  → creates a new GA4 property; returns property ID
POST /v1beta/properties/{property}/dataStreams
  → creates a web data stream; returns measurement ID (G-XXXXXX)
```

Auth shape: OAuth flow with `analytics.edit` scope. Mirrors the
existing GSC pattern at `~/.config/portfolio/gsc/`, but the new
location should be `~/lamill/ga4/` per `feedback_no_hidden_config`.

### The fork

GA4 work splits into three logical pieces:

| Piece | What it does | Natural home |
|---|---|---|
| **(1) Property creation** | Admin API → create property + web stream → return `G-XXXXXX` | Lifecycle — parallels CF zone / GH repo / Porkbun NS creation that `new bootstrap` already orchestrates. **Could** be portfolio. |
| **(2) Markup injection** | Write the gtag `<script>` into the site's Layout/index.html using that ID | SEO pipeline (per 2026-05-21 v17 scoping call). |
| **(3) Verification** | Read GA4 Data API to confirm Google receives data from this property | Already dropped (v18.C-F per § 2 Non-goals). GA4 web UI does this. |

### The cost of splitting (1) from (2)

If portfolio creates the property and SEO pipeline injects the
markup, the measurement ID (`G-XXXXXX`) has to cross project
boundaries. Two ways:

- **A.** Portfolio writes `G-XXXXXX` to a known location
  (`lamill.toml [analytics] ga4_id` or fleet-level
  `data/analytics.json`). SEO pipeline reads it.
- **B.** Both (1) + (2) live in SEO pipeline; portfolio's bootstrap
  fires a hook the SEO pipeline picks up. More decoupled but adds
  a coordination mechanism between two projects.
- **C.** Both (1) + (2) live in portfolio. Inconsistent with the
  2026-05-21 scope call ("rest using it should be in SEO pipeline")
  but reverts to the simplest single-project shape.

### Effort if it lands in portfolio

  - `lamill settings ga4 auth` (one-time OAuth flow; copy GSC's
    setup pattern): ~30 min
  - `ga4_admin.py` module — Admin API client +
    `create_property(name)` + `create_web_stream(property, uri)`:
    ~1h
  - Bootstrap integration: new step between repo-create and deploy;
    writes `G-XXXXXX` somewhere (location depends on A/B/C):
    ~30-45 min
  - Tests (`httpx.MockTransport` for the Admin API): ~30-45 min
  - **Total: ~2-3h** for property creation only.

### The argument each way

**For portfolio (Option A or C):**

  - Lifecycle pattern. Bootstrap already does external-service
    creation calls (CF zone, GH repo, CF Pages project, Porkbun
    NS). GA4 property creation is the same shape.
  - One-shot per domain, at bootstrap time. Not a recurring
    SEO-pipeline concern.
  - Operator has all the context at bootstrap (domain registered,
    just paid for it, knows it's about to ship).

**For SEO pipeline (Option B):**

  - Consistent with the 2026-05-21 scope call. The "no GA4 wiring
    in portfolio" line was drawn cleanly; carving exceptions
    erodes it.
  - Keeps the GA4 toolchain in one project. If SEO pipeline ever
    wants to do something more nuanced (e.g., per-environment data
    streams, or property-config tuning), it owns the whole API.
  - Avoids handing the measurement ID across project boundaries.

### Status

**2026-05-21 — Operator chose Option A.** Portfolio owns GA4
property creation (lifecycle); SEO pipeline owns markup injection
(content-shaping). Measurement ID handoff via per-site
`lamill.toml [analytics] ga4_id`. Decisions captured in
`docs/prd.md § v18` design notes. v18.A shipped same commit.

### What's in v18 (portfolio side)

  - v18.B — static checks (CHECK_148 ID-well-formed + CHECK_149
    script-src-google).
  - v18.C — `ga4_admin.py` Admin API client + OAuth flow + new
    `lamill settings ga4 auth` command. Credentials at
    `~/lamill/ga4/{credentials.json,token.json}`.
  - v18.D — `AnalyticsBlock` schema in `lamill_toml.py` + bootstrap
    auto-create step (writes `G-XXXXXX` to per-site lamill.toml).
    `--skip-ga4` opt-out for dark sites.
  - v18.E — docs sync wrap.

### What's left for SEO pipeline (this project's heir)

  - Read `lamill.toml [analytics] ga4_id` from each site.
  - Render the gtag `<script>` block into the site's
    `<head>` (Astro Layout component / index.html / WP plugin
    depending on stack).
  - `inject-ga4` Tier-2-fixer remediation for sites missing markup.
  - `Analytics.astro` partial-template component for the Astro
    stack majority.
  - GTM container support if/when a fleet use-case emerges.
  - Plausible / CF Web Analytics / Umami auto-setup if those become
    operator's preferred providers.

---

## Open question (2026-05-22) — v21 Indexing API hook: drop entirely?

The original v21 scope was a `lamill new deploy --reindex` hook that
calls `POST /v3/urlNotifications:publish` on the Google Indexing API
to ping Google about new/updated URLs at deploy time. The motivation:
post-deploy Google indexing takes days-to-weeks organically; an
explicit ping can compress that to hours.

### The catch

Google's docs explicitly limit the Indexing API to `JobPosting` and
`BroadcastEvent` (livestream) schema types:

> Currently, the Indexing API can only be used to crawl pages with
> either `JobPosting` or `BroadcastEvent` embedded in a `VideoObject`.

Most SEO practitioners use it for arbitrary URLs anyway and report
that it *seems* to work — but it's:

  - Not officially supported for the use case operator wants
    (general-purpose post-deploy ping).
  - Anecdotally effective; could break or stop working at any time
    when Google enforces the documented restriction.
  - 200 calls/day quota; would require service-account OAuth setup
    on top of the existing GSC OAuth.

### The official alternative

**v23.B — GSC Sitemaps API wrapper** is Google's officially sanctioned
path to ping about new content. The API's `POST /webmasters/v3/sites/
{site}/sitemaps/{feedpath}` submits a sitemap; Google crawls the URLs
it lists. Less aggressive than per-URL Indexing API pings (Google
decides crawl priority based on sitemap freshness rather than
explicit per-URL signals), but officially supported. v23.B was
already on portfolio's roadmap and stays there.

### Status

**2026-05-22 — Operator chose: drop v21 entirely. Move to SEO
pipeline project.** Same shape of call as v17 + the markup-injection
half of v18: when the work is borderline / unofficial / overlapping
with adjacent tools, defer to the SEO pipeline rather than commit
portfolio's surface area to it.

### What this means

  - **portfolio** retains `v23.B` (the official sitemap-submission
    path) as the post-deploy indexing automation.
  - **SEO pipeline** inherits the v21 Indexing API ping work if/when
    operator decides empirical effectiveness justifies the
    unofficial-API risk. Recommended sub-plan if they pick it up:
    one manual empirical test on 2-3 recently-launched URLs that
    aren't yet indexed; submit them via curl + service-account
    token; check GSC 24-48h later for differential indexing speed.
    Build the wrapper only on positive empirical result.

### Resurface conditions for portfolio

Reopen v21 in portfolio if:

  - Google opens the Indexing API officially for general URLs.
  - SEO pipeline empirically validates effectiveness AND decides not
    to own the wrapper (e.g., because the wrapper is deploy-time
    specific and the SEO pipeline doesn't run at deploy time).

### Decision log

  - 2026-05-19 — v21 scoped as "Indexing API hook" (when v23.B
    wasn't yet locked as the official alternative).
  - 2026-05-22 — operator asked "what is v21? why necessary?";
    audit surfaced the unofficial-API + anecdotal-effectiveness
    catch.
  - **2026-05-22 — Operator chose: drop entirely. Move to SEO
    pipeline project.** v23.B kept as the official indexing-ping
    path. `docs/prd.md § v21` collapsed to a reserved/dropped
    single-line placeholder matching the v17 / v20 / v22 pattern.
    `docs/architecture.md § Projected CLI surface` had its v21.B row
    removed.
