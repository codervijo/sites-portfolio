# bugs.md — sites/portfolio/

Bug journal for `portfolio` / `lamill`. Operator-driven intake;
Claude-maintained entries.

## Workflow

1. **Operator drops a brief report in chat** — a sentence or two, no
   structure required. Examples: "found a bug: X command shows N
   but Y shows M", "this thing is slow", "the help text for `foo`
   is wrong."
2. **Claude writes up the structured entry here.** Assigns the next
   `BUG-NNN` ID (highest existing + 1; see § Entry shape). Investigates
   enough to fill Repro / Expected / Actual / Where / Severity /
   Notes. Asks the operator if anything is ambiguous, but doesn't
   block on a perfect repro — captures what's known and proceeds.
3. **The current shippable phase keeps going.** Bug work doesn't
   interrupt v10.A / v10.B / etc. unless the operator escalates
   ("fix this first" / `blocker` severity).
4. **After a phase (`vN.X`) ships,** Claude reviews `## Open
   bugs` and picks up entries before starting the next phase —
   in this order:
   - any `blocker` severity (always first)
   - bugs whose fix overlaps with the just-shipped or next phase
   - everything else by date (oldest first)
5. **Fix → cut entry from `## Open bugs` → append to `## Fixed
   bugs` with the `**Fixed in**` commit SHA.** Don't delete fixed
   entries; they're the project's known-issue archive.

This file is *not* one of the five canonical doc surfaces (prd.md /
architecture.md / shipping-history.md / decisions/ / CLAUDE.md).
It's a maintained journal — same shape relationship as
`docs/Prompts.md`.

## Entry shape

One bug per H3 entry, carrying a stable `BUG-NNN` ID. Heading:

```
### BUG-NNN · YYYY-MM-DD — <one-line headline>
```

**IDs are stable and never renumbered** — same rule as ADRs. `BUG-NNN`
is the permanent reference for a bug; cite it in commits, chat, and
cross-links (`see BUG-047`). The ID stays with the bug when it moves
from `## Open bugs` to `## Fixed bugs`, so IDs are interleaved with
dates in both sections rather than contiguous — that's expected.

**Assigning the next ID:** new bugs get `max(existing) + 1`. Scan for
the highest `BUG-NNN` in the file (currently the top of `## Open bugs`,
since newest = highest) and increment. Three-digit zero-pad (`BUG-086`).
The date still rides along after the ID; same-day collisions are
disambiguated by the ID, so no letter/word suffix is needed.

Body fields, in this order (skip what isn't useful):

- **Repro** — exact command(s) that trigger it.
- **Expected** — what should happen (one line).
- **Actual** — what does happen, with verbatim error output.
- **Where (guess)** — file / module / area Claude suspects.
- **Severity** — `blocker` / `major` / `minor` / `cosmetic`.
  Default: `minor`.
- **Notes** — anything else (related commits, workaround,
  half-investigated hypothesis).

On fix, append a `**Fixed in**` line referencing the commit SHA +
phase:

```
**Fixed in** — `4395e1d` (v10.A — schema + parser)
```

`**Wontfix** — <reason>` or `**Dup of** YYYY-MM-DD — <headline>`
when applicable. Don't delete.

## Open bugs


### BUG-085 · 2026-07-13 — `fleet seo` grades a fully-unreachable site 🟢 green (hard HTTP error not folded into the overall grade)

- **Repro** — `lamill fleet seo --refresh` with donready.xyz's HTTPS down. Row: `🟢 donready.xyz  🔴 err  ⚪ robots  ⚪ sitemap  … 🟢 gsc  🟢 gsc-sm`. Leftmost overall grade is 🟢 **green** while the HTTP probe hard-errors.
- **Expected** — a site whose HTTP probe hard-fails (unreachable — no status at all) grades 🔴. An unreachable site is never "green," regardless of age or GSC state.
- **Actual** — graded 🟢 green while the HTTP probe hard-errored: `ConnectError: [SSL: WRONG_VERSION_NUMBER]` (port 443 answering in plaintext, not TLS) — confirmed independently via curl (`error:0A00010B:SSL routines::wrong version number`), openssl `s_client`, and `check.py`'s own fetch path (classifies `ssl-broken`). Whatever the *cause* of the unreachability, a hard HTTP error must never grade green — that's the tool bug fixed here. **(NB: the unreachability itself turned out to be an ISP-side block, NOT a real outage — see the diagnosis note below. But the grading bug is real regardless: any hard-unreachable site was being waved through green.)**
- **Root cause** — `overall_status` (`seo_runtime.py`) rolls up only `_OVERALL_KEYS = (imp, pos, robots, sitemap, gsc, gsc_sitemap_health)`; HTTP is deliberately excluded on the documented assumption that *"HTTP failures cascade naturally into robots/sitemap reds."* That assumption breaks for **connection-level** failures: when the root GET raises, `probe_http` returns early with `robots_served=None` / `sitemap_served=None`, which render **⚪ grey, not 🔴** — so they don't cascade. Combined with young-site masking greying out `imp`+`pos`, the only surviving signals were `gsc`🟢 + `gsc_sitemap_health`🟢 → overall 🟢. The one signal that proves the site is down (the HTTP error) wasn't in the rollup at all.
- **Where** — `src/portfolio/seo_runtime.py::overall_status` (rollup); `probe_http` early-return on `httpx.HTTPError` leaves robots/sitemap `None`; render at `check_render.py:641` shows `🔴 err`.
- **Fixed** — `overall_status` now returns 🔴 directly when `row.http_status is None and row.http_error` (hard-unreachable), **before** young-site masking — an unreachable site can't be masked green. Non-hard HTTP states (3xx/4xx/5xx *responses*) still cascade as before; `test_overall_status_ignores_http_status` (500 = reachable server) is intentionally preserved. Regression test `test_overall_status_red_when_http_unreachable` added; 91 seo_runtime tests + 98 grade/overall/seo tests green.
- **Diagnosis note — the `🔴 err` is an ISP-side false positive, NOT a Cloudflare/site outage.** Chased the "CF side" first; it's not CF. Cloudflare Pages deploy is green, DNS points at Cloudflare correctly, and sibling sites on the identical setup (airsucks.com, boxchive.com) serve HTTPS 200 from the same machine. donready.xyz alone is intercepted: `curl http://donready.xyz:443/` returns `302 → https://block.charter-prod.hosted.cujo.io/warn.html?url=…` on **both :80 and :443**. That's **Charter/Spectrum "Security Shield" (CUJO)** transparently blocking the domain on the operator's local network and injecting a plaintext-HTTP block page on :443 — hence `WRONG_VERSION_NUMBER` for any TLS client. Almost certainly a newly-registered-`.xyz` reputation quarantine. **The site is up for the rest of the world; it only reads as down from behind Spectrum's filter.** Remediation is ISP-side (allow-list donready.xyz in the My Spectrum app → Security Shield, or wait for the domain's reputation to clear) — nothing to change in Cloudflare or the site. Verify externally via phone-on-cellular or an off-network uptime checker.
- **Consequence for the tool** — as long as `lamill` runs from behind this ISP filter, donready.xyz will (correctly, post-fix) show `🔴 err`, but that red is a **local-network artifact**, not a real outage. Not worth special-casing in code; noting so future-me doesn't re-chase it as a Cloudflare problem.
- **Severity** — major (the grading bug). A green all-clear on a hard-unreachable site is the worst failure mode for a health dashboard. The donready trigger specifically was an ISP block (benign, external), but the masking bug it exposed was real.


### BUG-084 · 2026-07-13 — `fleet seo` "Last crawl" flickers to "—" between runs (live inspection soft-None + schema-mismatched cache fallback)

- **Repro** — two `lamill fleet seo --refresh` runs ~35 min apart. hybridautopart.com "Last crawl" = `2026-07-11` in run 1, `—` in run 2. Value is non-deterministic across runs for the same domain.
- **Expected** — "Last crawl" is stable: if the live inspection call doesn't return a value this run, fall back to the last known cached crawl date rather than blanking to "—" (which reads as "never crawled").
- **Actual** — the column blanks. Two compounding causes:
    1. `--refresh` sets `row.gsc_last_crawl` from `probe_gsc_last_crawl()` — a single **live** GSC URL-Inspection call that is *soft* (returns `None` on any API error / quota / rate-limit, never raises). hybridautopart is the highest-volume domain and the first row probed, so a transient None here is plausible run-to-run.
    2. The render's cache fallback — `_last_crawl(row)` = `row.gsc_last_crawl or last_crawl_by_domain.get(domain)` — is meant to floor this. But `_last_crawl_by_domain()` (`check_render.py:464`) reads `data["v16c_inspections"][].last_crawl_time`, while hybridautopart's **latest** cache snapshot (`data/gsc/hybridautopart.com/2026-06-06.json`) predates that schema and stores `coverage[].last_crawl_at`. So hybridautopart is **absent from the fallback map** (confirmed: map has 33 entries, hybridautopart not among them) — the floor is empty and the column goes to "—".
- **Where** — `src/portfolio/seo_runtime.py::probe_gsc_last_crawl` (soft-None, no cache floor of its own); `src/portfolio/check_render.py::_last_crawl_by_domain` (reads only the `v16c_inspections` schema; blind to older `coverage[].last_crawl_at` snapshots). Adjacent to the 2026-07-03 "Last crawl stale cache" entry but a distinct failure (flicker, not staleness).
- **Severity** — minor (cosmetic-ish but misleading — "—" reads as "never crawled" on a site Google crawls regularly). **Logged only; not fixed** per operator ("to log for now"). Likely fix: have `_last_crawl_by_domain` also parse the older `coverage[].last_crawl_at` schema, and/or floor `probe_gsc_last_crawl`'s live None against the cached value inside `run_seo`.


### BUG-083 · 2026-07-09 — `project seo <slug>` doesn't normalize arg to full domain → false "not registered / sitemap unreachable" + pollutes data/gsc/

- **Repro** — `lamill project seo calcengine` (project slug `calcengine` ≠ domain `calcengine.site`).
- **Expected** — resolve `calcengine` → `calcengine.site`, then use that domain for the GSC property lookup, the sitemap host, and the snapshot path.
- **Actual** — the bare slug `calcengine` is used throughout, so every downstream step keys off the wrong identifier:
    - GSC lookup finds no property → snapshot `"not_registered": true`, `"property_url": ""` — **false**: `sc-domain:calcengine.site` exists (siteOwner) and the homepage is `submitted_indexed`.
    - Sitemap probe hits `https://calcengine/sitemap_index.xml` (TLD dropped) → ConnectError → false "⛔ Sitemap unreachable" blocker.
    - Writes a bogus snapshot to `data/gsc/calcengine/2026-07-09.json` alongside the real `data/gsc/calcengine.site/` history.
  Net: the whole "blocked / earning no traffic" screen is a false alarm; the site is healthy. Verified by contrasting the two snapshots (bogus `domain:"calcengine"` empty vs real `domain:"calcengine.site"` `submitted_indexed`).
- **Where (guess)** — `project seo` dispatch (`project.py` ~410 "seo" subcommand) passes `resolve_project().matched` (the slug) un-normalized into `seo_diagnose.py` / `project_seo_diagnostics.py` / `gsc_recrawl.py`, which build the GSC property key, sitemap URL, and `data/gsc/<key>/` path from it. `fleet seo` / `gsc sync` are immune because they iterate the GSC property list (full domains).
- **Severity** — major. Inverts the diagnosis (reports a healthy, indexed site as blocked), burns debugging time, and pollutes `data/gsc/`. Bites any site whose project slug ≠ full domain.


### BUG-082 · 2026-07-09 — `project seo` live sitemap probe guesses `sitemap_index.xml` instead of reading robots.txt's declared `Sitemap:`

- **Repro** — `lamill project seo calcengine.site`. Site serves `sitemap-index.xml` (hyphen), declared in robots.txt; lamill probes `sitemap_index.xml` (underscore).
- **Expected** — read the `Sitemap:` URL from `/robots.txt` (`https://calcengine.site/sitemap-index.xml`) and probe that.
- **Actual** — probes a guessed/hardcoded `sitemap_index.xml` filename → 404 → would false-report "sitemap unreachable / 0 URLs" even against the correct host. GSC itself holds the correct hyphenated sitemap (status OK, last downloaded 2026-06-13), so this is purely the live HTTP probe's filename assumption. (Underscore-vs-hyphen is a real convention split across the fleet's SSG outputs.)
- **Where (guess)** — sitemap-URL construction in `gsc_recrawl.py::fetch_sitemap_urls()` / the `project seo` live probe — hardcoded filename candidates rather than parsing robots.txt's `Sitemap:` directive. Same fetch path as the 2026-06-26 "sitemap serves HTML" bug.
- **Severity** — major. False "unreachable" on sites whose sitemap is fine but named per the hyphen convention; masks real sitemap health.


### BUG-081 · 2026-07-03 — static SEO head checks false-fail on Astro pages (layout + `{title}` expression) — parse raw source, not rendered head

- **Repro** — `lamill project check donready.xyz` (Astro; pages do `import Base from "../layouts/Base.astro"` and `<title>{title}</title>` with `title` in frontmatter; `<html>` lives in the layout).
- **Expected** — checks reflect the rendered/live head. The live page is well-formed: title `FIGS vs Mandala Scrubs… | DonReady`, `<html lang="en">`, viewport, good meta description, JSON-LD all present.
- **Actual** — 7 false failures: `CHECK_070` reports `title = '{title}'` (7 chars — the *literal* template expression), `CHECK_074` "no `<html>` tag" (it's in the Base layout, not the page file), and `CHECK_073` viewport / `CHECK_075` robots / `CHECK_076` og / `CHECK_079` json-ld all false-fail — because the static checks read the raw `src/pages/index.astro` and parse `{expr}` literally + never follow the layout. Actively misled a debugging session: the operator thought the rewritten page was broken (it was fine); the *real* issue was `CHECK_095` (FAQ answers only in JSON-LD, not visible HTML).
- **Where** — `checks/seo/check_070…_079`, `_read_index_html`/`_read_head_html` in `checks/seo/__init__.py`. Related to the 2026-06-29 SSR-head fix but **not covered**: `_read_head_html` only *synthesizes* when no static index exists; when `src/pages/index.astro` is present it's read and parsed raw, so `<title>{title}</title>` → literal `{title}` and layout-delegated `<html>`/meta go unseen.
- **Fixed** — `_read_head_html` now **statically resolves Astro pages** (`checks/seo/__init__.py`): `_astro_frontmatter` parses `const NAME = "…"`, `_resolve_astro_exprs` substitutes `attr={const}`→`attr="value"` and `{const}`→value into the head, and `_astro_layout_head` follows the `import … from "…/layouts/…astro"` chain (depth-capped) to merge the layout's `<html>`/`<head>`. 073/074 repointed to `_read_head_html` (070/071/076/077 already were). Verified on real donready: 070/071/073/074 flipped false-fail→pass; 075 (robots) / 076 (og:image) correctly stay flagged (genuinely absent). 6 new tests (`test_astro_head_resolution.py`) + 690 seo/check/ssr regression tests green.
- **Fixed (JSON-LD, follow-up)** — `_jsonld_scripts` now synthesizes parseable `<script>`s from the framework idioms that hide JSON-LD from a raw parse: Astro `set:html={JSON.stringify(…)}` (inline object/array, incl. `@graph`, or a const) and TanStack/unhead `"script:ld+json": …`. Balanced-brace extraction handles `${…}` template literals. 078/079 repointed to `_read_head_html`; `CHECK_079` also now accepts Organization subtypes (ProfessionalService, LocalBusiness, …) since Google treats them as Organizations. Verified: donready 079 pass (Organization, WebSite), lamill.io 079 pass (ProfessionalService) — the latter fixes a warn→false-fail the repoint would otherwise have introduced. 4 more tests; 733 regression green.
- **Fixed (vite-react-ssg, follow-up)** — sites whose `index.html` is a bare mount shell with the head in a React `<Seo>` component (vite-react-ssg's `<Head>`): `_read_head_html` now detects the title-less shell and merges in `_react_ssg_head`, which pulls `title`/`description` from the homepage `<Seo …/>` props, reconstructs the og/twitter tags declared by the head component (values where known, present-placeholder for derived `url`/`ogImage`), and resolves JSON-LD from the `jsonLd={[const, …]}` prop. Verified: isitholiday.today 070/071/076/077/078/079 all flip to pass; cricketfansite.com (same stack) too. 3 more tests; all fleet stacks (Astro / TanStack / vite-react-ssg / plain Vite) now resolve. Head checks no longer false-fail on any stack in the fleet.
- **Severity** — major (resolved for the Astro case). Was false-failing a whole class of Astro pages on core SEO gates and misleading operators into "fixing" well-formed pages.



### BUG-080 · 2026-07-03 — `fleet seo` "Last crawl" column is stale (read from a cache `--refresh` never updates)

- **Repro** — `lamill fleet seo --refresh`, then compare the "Last crawl" column to GSC / a live URL inspection.
- **Expected** — with `--refresh`, "Last crawl" reflects Google's actual latest crawl.
- **Actual** — stale by days. isitholiday.today showed `2026-06-29` while live GSC URL-Inspection said `2026-07-03`; drdebug.dev showed blank though Google had crawled it (`2026-07-01`). Root cause: `_last_crawl_by_domain()` (`check_render.py`) reads `last_crawl_time` from the **per-domain URL-Inspection cache** `data/gsc/<domain>/<latest>.json`, which is only written by `project seo <domain> --refresh` (one domain at a time). `fleet seo --refresh` refreshes the impressions snapshot (`data/seo/`) but never touches that cache — so "Last crawl" is frozen at whenever each domain was last individually inspected, and domains never inspected show blank. Same class as the 2026-07-03 freshness-header bug: two GSC data paths, `--refresh` only touched one.
- **Fixed** — `fleet seo` now fetches the homepage `last_crawl_time` **live** as part of the probe so it rides `--refresh`: new `probe_gsc_last_crawl()` (`seo_runtime.py`) does a homepage URL-Inspection per domain (soft-fail, +~8s over the fleet), stored on `SEORow.gsc_last_crawl` and carried in the SEO snapshot. The renderer prefers `row.gsc_last_crawl`, falling back to the old cache only for pre-field snapshots. (Impl note: the coverage map yields `{'siteUrl': …}` dicts, not strings — the property picker must extract `siteUrl` or every inspection silently returns `None`.) Verified live: isitholiday `2026-07-03`, drdebug `2026-07-01`; 568 seo/render tests green.



### BUG-079 · 2026-07-03 — `fleet seo` labels the roster/classification date as "Snapshot:", making fresh GSC numbers look week-old ("refresh isn't working")

- **Repro** — with a stale `data/checks/<date>.json` (classification not re-run recently) but a same-day GSC fetch:
    ```
    lamill fleet seo --refresh
    ```
- **Expected** — the prominent freshness line reflects the **GSC-data** date (what `--refresh` just fetched). Operator can tell at a glance the numbers are current.
- **Actual** — header printed `Snapshot: 2026-06-26.json · 46 live-site/forwarder domains probed`, with the real GSC-data date buried as `Cached: 2026-07-03.json`. `2026-06-26.json` is the **classification/roster** snapshot (which domains are live-site/forwarder), a week stale because `fleet domains` hadn't re-run — but it *reads* as "the whole table is from June 26." Operator concluded `--refresh` wasn't pulling fresh numbers. It was: every displayed impression matched `data/seo/2026-07-03.json` (that day's fetch), not the 06-26 snapshot (verified: washcalc 601 vs 720, cottagefoodmap 114 vs 46, isitholiday 38 vs 37, etc.). Pure labelling bug — right data, misleading header. Third fleet-seo reporting confusion in this vein.
- **Where** — `src/portfolio/cli.py`, `_run_check_seo_mode`: line ~372 printed `Snapshot: {snap_path.name}` where `snap_path` is the *checks* (roster) snapshot; the GSC-data date came from `fresh_path`/`cache_path` (~411/~387) under the low-key `Cached:` / `Reading cache:` labels.
- **Fixed** — roster line relabelled `Roster: … — classification only; run \`fleet domains\` to refresh`; the GSC-data date is now printed prominently as `GSC data: <date> (fresh · Nd window)` (or `(cached · …)` on the no-refresh path). Data freshness is now the answer to "is this current?", not the roster date.



### BUG-078 · 2026-06-29 — SEO head checks (title / meta-description / OG / twitter) are blind to SSR-head stacks (TanStack Start / Astro / Next), so placeholder metadata ships undetected

- **Repro** — a TanStack Start site (no static `index.html`; head defined in code via a route `head()` / `createRootRoute`). `lamill.io` shipped with the Lovable scaffold's placeholder head — `title: "Lovable App"`, `description: "Lovable Generated Project"`, `author: "Lovable"`, `twitter:site: "@Lovable"`. Run:
    ```
    lamill project check lamill.io
    ```
- **Expected** — the title / meta-description / OG / twitter checks evaluate the head the site *actually serves*, regardless of stack, and flag `title = "Lovable App"` as a missing/placeholder title.
- **Actual** — `CHECK_070` (has-title), `CHECK_071` (meta-description), `CHECK_076` (OG), `CHECK_077` (twitter-card) read **`index.html` on disk only**. A TanStack Start app has no `index.html` (head lives in `src/routes/__root.tsx`), so these checks either skip or pass-by-absence — the `Lovable App` title and `@Lovable` handle sailed through `project check` and only surfaced by eyeball. Same blind spot would hit Astro/Next in-code heads.
- **Where** — `src/portfolio/checks/seo/check_070_has_title.py`, `check_071_…`, `check_076_…`, `check_077_…` — all static `index.html` readers. The framework has no notion of "head lives in code" for SSR stacks. (`lamill.toml [stack].framework` *does* record `tanstack-start`, so the stack is knowable.)
- **Fix** — two complementary moves, **both now landed**: (a) `CHECK_081` (no-placeholder-metadata) **source-scans** `src/**` + `index.html` + `package.json` for known AI-builder placeholder markers — stack-agnostic; (b) the presence/quality checks `070/071/076/077` now resolve the head via `_read_head_html()` (`checks/seo/__init__.py`), which falls back to **synthesizing a `<head>` from the in-code definition** (TanStack Start route `head()` meta-object literals, Astro layouts, Next `metadata`) when no static index exists — so the same bs4 checks evaluate the real head instead of skipping. Homepage route heads are mined before the root fallback so the homepage title wins.
- **Verified** — on real lamill.io the four checks flipped from all-`skipped` to evaluating: CHECK_070 `pass` (found the homepage title), CHECK_071 `warn` (99-char description — genuinely short), CHECK_076 `warn` (`og:url` missing) — real gaps that were previously invisible. 16 new tests (`test_ssr_head_resolution.py`) + 604 seo/check regression tests green.
- **Severity** — major (now resolved). Was a silent false-pass on a core branding/SEO gate for every SSR-head site in the fleet.

### BUG-077 · 2026-06-26 — `project seo` reports `sitemap · reachable · 0 URLs` when /sitemap.xml actually serves HTML (SPA/catch-all fallback) — misdiagnoses cause, gives wrong remediation

- **Repro** — deploy a site whose `/sitemap.xml` route isn't emitted by the build, so the host's catch-all returns `index.html` with `200 text/html` (e.g. bppvcoach.com, Astro/SPA). Then:
    ```
    lamill project seo bppvcoach.com
    ```
- **Expected** — lamill detects the body is **not XML** (Content-Type `text/html`, body starts `<!DOCTYPE html>`, root tag `html` not `urlset`/`sitemapindex`) and reports the *real* cause: "sitemap.xml is serving HTML, not XML — likely an SPA/catch-all fallback; the `/sitemap.xml` route isn't in the build." It should distinguish **"0 URLs because the response isn't a sitemap at all"** from **"0 URLs in an otherwise-valid empty `<urlset>`"**, and the remediation should be "fix the build to emit a real sitemap.xml," not "add routes to the sitemap."
- **Actual** — the probe line says `Sitemap 0 URLs · submitted · reachable` and the Blockers section emits:
    ```
    ⚠ Sitemap lists only 0 URLs
      The site's other routes are undiscoverable — they aren't in the sitemap.
      → Add every indexable route to the sitemap.
    ```
  Wrong remediation — there *is* no sitemap to add routes to; the file is the homepage HTML. lamill calls a 200-HTML body "reachable" with "0 URLs," silently swallowing the parse failure. (Note the internal contradiction: the **GSC Sitemaps** sub-panel in the *same* run correctly shows `✗ ERROR … 1 error(s)`, because Google's parser rejected the HTML — but lamill's own HTTP-side probe reports "reachable.")
- **Where** — `src/portfolio/gsc_recrawl.py`:
  - `_extract_locs()` (167–175) does `ET.fromstring(xml_text)` and on `ET.ParseError` **`return [], []`** — so an HTML body (which fails XML parse) is indistinguishable from a valid-but-empty `<urlset>`. The failure is swallowed with no signal to the caller.
  - `fetch_sitemap_urls()` (197–256) accepts **any `status_code == 200`** candidate as "the sitemap" (215, 227) with no `Content-Type` check and no body sniff, then counts locs from whatever came back.
  - The misleading "reachable / 0 URLs" status + the "Sitemap lists only 0 URLs" blocker are rendered in `src/portfolio/project_seo_diagnostics.py` (sitemap fetch ~247–250; blocker/hint generation in `_generate_hints` ~318) off that empty result.
- **Fix (guess)** — at fetch time, reject a non-sitemap response *before* treating it as empty: skip/raise when `Content-Type` is `text/html` or the body doesn't start with `<?xml`/`<urlset`/`<sitemapindex` (after BOM/whitespace strip). Have `_extract_locs` (or a wrapper) distinguish three outcomes — *valid sitemap with N URLs*, *valid-but-empty sitemap*, *not XML / HTML fallback* — and propagate the third as a typed condition so `project_seo_diagnostics` can render the accurate blocker ("/sitemap.xml serves HTML, not XML — route missing from build; re-deploy with a real sitemap") instead of "add routes." Keeps parity with the GSC-side ERROR the same run already surfaces.
- **Severity** — major. The site genuinely earns no traffic (real blocker), but lamill misdiagnoses *why* and points the operator at the wrong fix ("add routes" vs. "your build isn't emitting sitemap.xml"), which costs real debugging time on a common deploy failure mode. (Underlying site-side issue — bppvcoach.com's build not emitting `/sitemap.xml` — is separate from this diagnostic gap.)

### BUG-076 · 2026-06-24 — `new deploy` pre-flight prints `✓ GitHub auth via token` then dies one line later on a cryptic raw-401 owner lookup

- **Repro** — with a stale/revoked `GITHUB_TOKEN` in `portfolio.env` (and no `gh` CLI installed):
    ```
    lamill new deploy bppvcoach.com --yes
    ```
- **Expected** — the `GitHub auth via token` pre-flight check should validate that the token actually *works* before printing `✓`. If the token is expired/revoked, fail there with a plain-language remediation, e.g. `✗ GitHub token rejected (401 Bad credentials) — it is expired or revoked. Set a fresh PAT: lamill settings apikeys set GITHUB_TOKEN <pat>`. The `✓`/`✗` lines should never contradict each other one line apart.
- **Actual** — pre-flight step 0 prints:
    ```
      ✓ GitHub auth via token
      ✗ Could not resolve GitHub owner: GET /user → HTTP 401: {
      "message": "Bad credentials", ...
      }
    ```
  The `✓` asserts auth is OK when only token *presence* was checked; the *first real validation* is the very next step, which dumps a raw GitHub JSON 401 body. Contradictory + cryptic, and there's no remediation hint at the failure site.
- **Where** — `src/portfolio/gh_repo.py`. `auth_path()` / `ensure_auth()` (lines 83–111) only test that `GITHUB_TOKEN` is present/non-empty — that's what the `✓ GitHub auth via token` line reflects. Validity is first exercised in `_detect_owner_via_token()` (lines 126–146), where a non-200 raises `GhApiError(f"GET /user → HTTP {r.status_code}: {r.text[:200]}")` — the raw-JSON message the operator saw. Root cause: the token path has no validity probe, unlike the CF path which already does one (`cloudflare.py:363` — `GET /user/tokens/verify`, "pre-flight probe to catch under-scoped CF tokens").
- **Fix (guess)** — fold a real probe into the auth pre-flight: in `ensure_auth()` (or a new `verify_token()`), when path == "token", call `GET /user` and treat 401/403 as auth failure, mapping it to a typed `GhAuthError` with the `lamill settings apikeys set GITHUB_TOKEN <pat>` remediation (mirroring `gh_repo.py:106-109`). Only print `✓ GitHub auth via token` after that probe passes. Parse the 401 body to distinguish *expired/revoked* (Bad credentials) from *under-scoped* (403 + `X-Accepted-OAuth-Scopes`) so the message names the right remedy. Same treatment for the `gh-cli` path via `gh api user`.
- **Severity** — minor (UX/error-quality; not data-loss). The pre-flight *does* fail before any write step, so no half-created GH/CF state — but the misleading `✓` + raw-JSON `✗` cost operator time diagnosing.
- **Fixed (working tree, pending commit)** — `gh_repo.py`: `_detect_owner_via_token()` now maps 401/403 to a typed `GhAuthError` via `_token_auth_error()`, which parses the body + `X-{Accepted-,}OAuth-Scopes` headers to name the cause (expired/revoked vs under-scoped) and appends the `lamill settings apikeys set GITHUB_TOKEN <pat>` remediation; the `gh`-CLI path gets the same via `_looks_like_gh_auth_failure()`. `cli.py` pre-flight now resolves the owner *as* the credential probe, so `✓ GitHub auth via {path}` prints only after the token is proven valid (no more contradictory ✓-then-✗). Tests: `test_gh_repo.py` updated (401 → `GhAuthError`) + 3 added (remediation text, 403 scope-naming, 500-stays-`GhApiError`); 62 + 38 deploy tests green. Verified live against the editable-installed `lamill` with a simulated 401.

### BUG-075 · 2026-06-22 — `fleet seo` can't answer "did Google re-crawl after my last update?" — push date isn't shown next to Last crawl
- **Repro** — `lamill fleet seo --refresh`: the table shows a `Last crawl` column (homepage `last_crawl_time` from the GSC inspection cache) but no "when did I last push/update this site" column. To compare you have to run `lamill fleet dashboard` separately (which has the `Last` commit-age column but *not* `Last crawl`) and do the mental math across two commands.
- **Expected** — one glance answers "is my latest content stale in Google's index?" — i.e. did I push *after* Google last crawled.
- **Actual** — the two halves live on two different commands; neither surface shows both side by side.
- **Where** — `check_render.py::_render_seo_table` (renders `fleet seo`). `_last_crawl_by_domain()` already supplies Google's side; the missing half is a per-domain last-commit date from `sites/<domain>/` (local git, mirrors `project.fetch_last_commit`).
- **Severity** — `minor` (feature request / missing column; no incorrect output).
- **Fix** — add an `Updated` column right after `Last crawl` on the `fleet seo` table showing the last local-commit date, with a 🔄 flag (predicate `_is_stale_in_index`) + footer tally. Source = last *commit* (free, local, no network); true `pushed_at` deferred unless commit-vs-push drift becomes real friction. Flag fires when pushed content likely runs ahead of Google's index, across two cases: (a) crawl date present and push newer; (b) **never crawled** (`Last crawl —`) + pushed + no indexing signal. The "—" dash is ambiguous (never-crawled vs homepage-inspection-not-cached), so the no-crawl branch is gated on `indexed = impressions > 0` — heavily-indexed sites with a cache gap (hybridautopart, 22,990 imp) are NOT flagged. **Dark sites** (`robots_intent == "dark"`, e.g. csinorcal.church) are never flagged — intentionally not indexed. Sites with no local repo (carrepairsite — no `Updated` date) have nothing to compare. **Fixed in** `<this commit>`.


### BUG-074 · 2026-06-19 — CF purge-by-URL doesn't evict a DYNAMIC-pinned stale object (earnlog /sitemap.xml)
- **Repro** — `lamill project fix earnlog.xyz --rule CHECK_057 --apply`: reports the purge sent, but `curl -sI https://earnlog.xyz/sitemap.xml` still returns the removed stub (200, body has `<!-- Stub sitemap`, `age` keeps climbing). Cache-busted (`?cb=…`) the same path returns **404** — so origin is correct; only the edge copy is stale.
- **Expected** — `cloudflare.purge_files(zone, ["https://earnlog.xyz/sitemap.xml"])` evicts the cached object; the next fetch re-pulls from origin (404).
- **Actual** — the CF API returns success but the object survives (it was a static `public/sitemap.xml` served with `cache-control: public, s-maxage=604800`; removed in the sitemap sweep + redeployed, but the 7-day edge copy persists). Purge-by-file isn't matching the cached key.
- **Where** — `cloudflare.py::purge_files`. **ROOT CAUSE FOUND (2026-06-20):** it's the **CF Pages asset cache**, NOT the zone/CDN cache. Empirically confirmed both `purge_files([url])` AND `purge_everything` (zone API) return `success=true` but neither evicts — the object keeps serving with a climbing `age` and `cf-cache-status: DYNAMIC` (CDN bypass; the stale copy comes from the Pages layer, pinned by the old static asset's `s-maxage`). The zone purge API cannot touch Pages-layer asset cache.
- **Severity** — `minor` for earnlog itself (nothing references `/sitemap.xml`; robots + GSC use `sitemap-index.xml`; self-expires ~5.7d as of 2026-06-20). The real defect is in **CHECK_057 detection** (see Fix).
- **Fix** — the purge can't be "fixed" (CF limitation); fixed CHECK_057 *detection* + added *prevention* instead. **Fixed in** `<this commit>`: (1) `_is_edge_cached` — a 200 served `DYNAMIC`/`MISS` with no `age` is fresh-from-origin, not stale-cached → stops false-flagging airsucks's fresh `/robots.txt` + `/sitemap.xml` (now PASS). (2) `run()` splits zone-purgeable (HIT/REVALIDATED → fail + "purge") from Pages-pinned (`DYNAMIC + age` → **warn**, "expires as s-maxage runs out; add short Cache-Control via _headers") → earnlog is now an informational warn, not a red call-to-purge-that-can't-work. (3) prevention: bootstrap `CF_HEADERS_TEMPLATE` now gives `/robots.txt`, `/sitemap.xml`, `/sitemap-*.xml` an explicit `max-age=0, must-revalidate` so changed/removed SEO files never pin again. earnlog's existing stale copy self-expires (~5.7d as of 2026-06-20); existing sites get the no-pin headers on their next `project fix` / re-scaffold of `_headers`.
- **Notes** — surfaced 2026-06-19, root-caused + fixed 2026-06-20. Bug 1 (verify false-positive, `8b5f62e`) made the failure honest; this fixed detection + prevention. Residual: existing deployed sites still have the old `/*`-no-cache `_headers` until refreshed.


### BUG-073 · 2026-06-19 — CHECK_057 purge fix false-reports "fixed" when a stale path survives as DYNAMIC
- **Repro** — same as above; before the fix, `project fix … --rule CHECK_057 --apply` printed `✓ purged 1 path(s)` even though `/sitemap.xml` was still the stale stub at the edge.
- **Expected** — if a path is still stale after the purge, report `error`, not `fixed`.
- **Actual** — the post-purge verify computed `still_stale` but then only errored on the subset whose `cf-cache-status` was `HIT`/`REVALIDATED`. A stale object served as `DYNAMIC` (the earnlog case) slipped through ⇒ false `fixed`.
- **Where** — `checks/deploy/check_057_cf_edge_cache_fresh.py::_apply_purge`, the verify block (~L308–321).
- **Severity** — `major` (the remediation silently lied; masks Bug 1 fleet-wide).
- **Fix** — **Fixed in** — `<this commit>` — error on `still_stale` (the same `_stale_paths` criterion used pre-purge), not the narrower HIT/REVALIDATED filter; message now names each surviving path + its cache-status. Regression test: `tests/test_check_057_purge_verify.py`.


### BUG-072 · 2026-06-19 — sub-page canonical 308-redirects to its own served URL; "unknown to Google"; no check catches it
- **Repro** — `curl -sI https://earnlog.xyz/calculator` → `308 → /calculator/`; the served `/calculator/` page declares `<link rel="canonical" href="https://earnlog.xyz/calculator">` (no slash). GSC URL-inspect each sub-page → "URL is unknown to Google" while the homepage is "Submitted and indexed".
- **Expected** — a page's `<link rel="canonical">` is its own final (200, non-redirecting) URL, matching what the sitemap lists.
- **Actual** — Astro's directory format serves `/calculator/` and `@astrojs/sitemap` lists `/calculator/`, but the canonical declares `/calculator`, which 308-redirects back to `/calculator/`. A canonical pointing at a redirecting URL is an indexing-blocker — exactly the sub-pages with the contradiction are "unknown to Google". Confirmed on **donready.xyz** (per-page hardcoded `const url = ${site}/page`) and **earnlog.xyz** (shared `Layout.astro` `${site}${path}`); both scaffolded by `portfolio new bootstrap` ⇒ likely a **bootstrap-template defect**, fleet-wide on multi-page Astro sites (cf. the low index ratios: civictools 1/10, calcengine 2/10, voltloop 2/10…).
- **Where** — gap: **no conformance check** validates this. `CHECK_158 canonical-host-is-apex` fetches every sitemap URL and reads each canonical but checks only the *host* (apex vs www) — it passes our case because the host is correct; the *path/trailing-slash* redirect goes unchecked. Bootstrap source: `bootstrap.py` Astro template canonical generation. Per-site source: each site's `Layout.astro` / page `const url`.
- **Severity** — `major` (silently blocks indexing of every non-home page on affected sites; the fleet's biggest green-but-dead driver).
- **Fix** — (1) ✅ high-severity check `CHECK_161 canonical-resolves-200` (`6438a54`). (2) ✅ bootstrap template: `trailingSlash: 'always'` + trailing-slash canonical pattern in the index. (3) **open** — sweep existing multi-page Astro sites with `CHECK_161` (separates the canonical bug from authority-only cases; e.g. civictools/voltloop already pass = authority, not this). donready + earnlog fixed per-site (`0e07f83`, `2f1d285`).
- **Notes** — same trailing-slash class as the airsucks/whizgraphs canonical fixes. The check is being added now (operator request, high severity).


### BUG-071 · 2026-06-15 — three duplicate sitemap-URL parsers (DRY violation; same bug needed fixing in two of them)

- **Where** — `checks/seo/_live.py::_extract_sitemap_locs` (+ `get_sitemap_urls`), `gsc_recrawl.py::_extract_locs` (+ `fetch_sitemap_urls`), `indexnow.py::_LOC_RE` (regex). Three independent implementations of "extract `<loc>` URLs from a sitemap / sitemap-index."
- **Actual** — the `https://`-namespace bug (see Fixed bugs, same date) existed *identically* in the two ElementTree-based parsers and had to be fixed twice; the first fix (`_live.py`) didn't address the reported symptom because `project seo` uses the *other* parser (`gsc_recrawl`). The regex one (indexnow) was incidentally immune. Consumers are split: ~10 checks (090–095/147/158/159) use `_live`'s; `seo_diagnose`/`project_seo_diagnostics`/cli use `gsc_recrawl`'s; indexnow uses its own.
- **Severity** — `minor` (works now; risk is future drift — the next sitemap bug gets fixed in 1 of 3 places).
- **Fix** — consolidate to a single shared sitemap parser (one util), re-point all ~13 consumers. **Deferred to the next bug-scrub session** (operator decision 2026-06-15 — re-pointing 13 consumers mid-closeout is how the next bug gets introduced).
- **Notes** — surfaced while fixing the `https://`-namespace 0-URL bug. The duplication *is* the root cause; patching N copies is symptom treatment.


### BUG-067 · 2026-06-13 — `project seo` State header ("Sitemap submitted") contradicts the GSC-diagnostics block ("none submitted")

- **Repro** — `lamill project seo airsucks.com`: the v36 State header shows `Sitemap 1 URL · submitted · reachable`, but the GSC-diagnostics block just below shows `📋 Sitemaps none submitted`.
- **Expected** — the two sitemap statements agree (and one of them is authoritative).
- **Actual** — they disagree. The State header is right (`gsc_sitemap_count = 1` from the fleet-seo snapshot ⇒ submitted); the old block overclaims.
- **Where** — `research_render.py` `_render_project_seo_diagnostics`, the empty-`sitemaps` branch (~L322–325) prints a definitive "none submitted". But for airsucks the cached v13.B dict (`data/gsc/airsucks.com/2026-06-12.json`) holds only `v16c_inspections` — it has **no `sitemaps` section** (that file was written by the v16c URL-inspection path, not `build_diagnostics`, which is what populates `sitemaps`). So `sitemaps == []` means "not in this snapshot", not "none submitted" — the block can't actually know.
- **Severity** — `minor` (cosmetic contradiction; the State header is correct). Surfaced by operator on the very-improved v36 output.
- **Notes** — Quick fix: the empty branch should defer to the authoritative State-header Sitemap line rather than assert "none submitted". Deeper (follow-up): the v13.B per-domain cache and the fleet-seo GSC probe are two GSC reads that can disagree; real reconciliation = always source the submitted-count from one place (e.g. `gsc_sitemap_count`, or always run `build_diagnostics`'s `fetch_sitemap_details`). **Fixed (wording)** — 2026-06-13, v36 polish (see commit).

### BUG-066 · 2026-06-13 — `project delegate` dies on the 5-hour usage cap, forcing a manual run→rate-limited→discard→wait→retry loop

- **Repro** — `lamill project delegate <domain> "..."` when the account's 5-hour usage cap is exhausted (stream emits `rate_limit_event` `status: rejected`, `overageDisabledReason: org_level_disabled`, then no `result`).
- **Expected** — quota-aware + self-healing: detect the cap, **wait out the reset by default** with a live spinner counting down to `resetsAt`, revert any partial diff, retry, and complete — no manual back-and-forth. `--no-wait` (or a non-TTY/CI context) restores fail-fast with the reset time + a clean tree.
- **Actual** — after the v33.O debuggability fix the run now *honestly* reports "rate-limited — usage cap reached; resets at <ts>", but the operator still has to: notice it, manually wait hours, re-run, and discard whatever partial diff the doomed run left. Pure manual toil during every cap window.
- **Where (guess)** — `delegate.py` `run_delegate` (pre-flight quota gate + mid-run wait/retry loop) + `DockerBackend` (a cheap host-side `claude -p` quota probe, or read the first `rate_limit_event`); CLI `project_delegate` (`--no-wait`/`--wait`/`--max-wait`/`--max-retries` flags + the Rich `console.status` countdown spinner). Builds directly on the v33.O `rate_limit_event` parsing.
- **Severity** — `major` (operator-felt friction; blocks unattended `delegate` use during cap windows — exactly when you'd want to queue work and walk away).
- **Notes** — Queued as the next delegate tier (**v33.P**). Six requirements per the operator spec (2026-06-13): (1) pre-flight quota probe — don't start a doomed run; (2) **wait-by-default** + `--no-wait` opt-out, bounded by `--max-wait` (6h) / `--max-retries` (2); non-TTY ⇒ behave as `--no-wait` unless explicit `--wait`; (3) live Ctrl-C-interruptible countdown spinner (`console.status`, ~1s refresh, "⠋ rate-limited — waiting for quota · resets 2:10 PM · ~14m left"), suppressed non-TTY, prints "✓ quota reset — resuming…" on reset; (4) **auto-revert before any retry** (pairs with the revert/stash-on-failure work); (5) **honesty** — can check quota to *start*, not to *finish* (the cap depletes continuously); on mid-run exhaustion, revert + wait-retry (or fail fast); optionally refuse to start below a remaining-quota threshold if `rate_limit_info` exposes it; (6) help text + failure output must note that **enabling org-level overage removes the hard stop entirely** (the real fix; wait/retry is the workaround). **DoD** — a rate-limited account, no extra flags: detect → spinner countdown → wait → revert partial → retry → complete; `--no-wait`/non-TTY ⇒ fail-fast with reset time + clean tree; Ctrl-C during the wait aborts cleanly; `--max-wait`/`--max-retries` bound it. **Dependency:** builds on the v33.O change (`2e53209`).
- **Fixed** — 2026-06-13, v33.P. `run_delegate_resilient` + `probe_quota_host` + `revert_tree` + `quota_from_rate_limit`/`parse_resets_at` in `delegate.py`; CLI `--no-wait`/`--wait`/`--max-wait`/`--max-retries` + countdown spinner + Ctrl-C abort in `project_delegate`. 11 unit tests (pure loop; injected sleep/now/backend) incl. the DoD detect→revert→wait→retry→complete path + non-TTY/`--no-wait` fail-fast + bounds. **Live-validation pending** (real-cap end-to-end is operator-machine-only).

### BUG-065 · 2026-06-13 — `project seo <domain>` GSC-diagnostics block is contradictory + value-free on fresh/young sites (airsucks.com)

- **Repro** — `lamill project seo airsucks.com` (young site <90d, 0 imp; GSC diagnostics cached `2026-06-12.json`).
- **Expected** — the diagnostics block either agrees with the 1-row table or stays quiet; for a freshly-deployed site with no GSC sitemap yet, say something actionable ("not yet submitted to GSC — run `project sitemap resubmit`" / "indexing pending, deployed Nd ago") rather than emitting bare negative states.
- **Actual** — the table row says **Sitemap 🟢 / GSC sm 🟢** (sitemap served + submitted-ok), but the diagnostics block immediately below contradicts it:
  ```
    GSC diagnostics
      📋 Sitemaps none submitted
      📊 Coverage  (no URLs inspected — sitemap unreachable)
  ```
  Same command, two sources, opposite answers. "sitemap unreachable" is also suspect — the table's robots/sitemap probe found the sitemap (🟢), so the diagnostics fetch is failing where the table's succeeds. Operator verdict: "this command is also useless."
- **Where (guess)** — drift between `seo_runtime.py` aggregation (feeds the 🟢 table cells: `gsc_sitemap_*`) and `project_seo_diagnostics.py` `fetch_sitemap_details` / `fetch_coverage_details` (feeds the diagnostics block — returns empty + "unreachable"). The two read GSC sitemap state via different paths and disagree. Likely the diagnostics path mis-resolves the property/origin or the cached snapshot lacks the sitemap detail the table cell was computed from.
- **Severity** — `major` → **upgraded to the v36 driver (2026-06-13)**. This isn't just a contradiction; the whole command green-washes a site that earns nothing. Re-scopes `project seo` from a green dashboard into a problem-surfacing diagnostic.
- **Notes** — Directly on the **v36** surface (`project seo` GSC sitemap diagnostics). Two facets: (1) reconcile the table cells with the diagnostics block so they can't disagree; (2) for fresh/young sites with no GSC sitemap yet, render a deployed-Nd-ago / pending-indexing line, not bare "none submitted / unreachable." Fold the reconciliation into v36's `build_diagnostics` work; the young-site messaging pairs with the existing `🌱 young site` freshness masking. Confirm whether "unreachable" is a genuine fetch failure (false negative) or stale-cache artifact (`--refresh` to test).
- **Fuller diagnosis (operator, 2026-06-13)** — airsucks.com is the canonical case for *why the command is useless*, and every symptom is a distinct blocker the command hides:
  1. **Green-by-masking** — `seo_runtime.py` masks imp+pos for sites <90d (`_AGE_MASKED_KEYS`, ~L656–687), so only presence checks remain → young sites grade 🟢 *by construction*. A site with 0 impressions + a not-indexed homepage grades green. The grade must become an explicit **State**: `healthy` (earning traffic) / `unproven` (young, no traffic yet, nothing else wrong) / `blocked` (a detected hard blocker). 0 imp + not-indexed homepage ⇒ **blocked**, never 🟢.
  2. **Index state hidden** — the homepage is **"Crawled – currently not indexed"** in GSC; that's THE headline and it's hidden behind "no URLs inspected." Per-URL inspections are already cached at `data/gsc/<domain>/<date>.json` (`v16c_inspections[].coverage_state`/`verdict`). Surface them as an **Index** column + detail (indexed / Crawled–not-indexed / URL unknown to Google / …).
  3. **Sitemap dishonest + thin** — the Sitemap cell is a `/sitemap.xml`-returns-200 presence check (~L485) that contradicts the GSC diagnostic. It should report **URL count + submitted-to-GSC (y/n) + GSC-reachable (y/n)**; flag "only 1 URL" as suspicious; green only if submitted AND reachable AND >1 URL. The false "unreachable" is a fetch bug — the sitemap is curl-able; must follow `robots.txt` `Sitemap:`, follow redirects, recurse `<sitemapindex>` (mirror rankmill ADR-0014). airsucks's sitemap lists **only the homepage** and isn't submitted.
  4. **No render/crawlability probe** — airsucks's sub-routes **render empty to crawlers (no SSR)** and aren't in the sitemap. Probe each known URL's raw HTML for a non-empty `<title>` + visible body text; flag empty shells as "renders empty to crawlers (no SSR)."
  5. **No Blockers section** — the command must end with a prioritized, explicit list of every detected problem + next action (even when unfixable), e.g. ⛔ homepage Crawled–not-indexed (content/authority, not technical); ⚠ sitemap lists 1 URL; ⚠ sitemap not submitted → submit `https://airsucks.com/sitemap-index.xml`; ⚠ `[content]` unconfigured. **Never end on 🟢 when this list is non-empty.**
  - **DoD** — `project seo airsucks.com` no longer reports green: State = `blocked`, an Index cell "Crawled – not indexed", a Sitemap cell "1 URL · not submitted", and a Blockers section with the real problems + next actions. Test: a young site with 0 imp + not-indexed homepage + 1-URL sitemap surfaces ≥3 blockers and does NOT grade green.

### BUG-064 · 2026-06-06 — `project delegate` reports `✓ agent finished` on a no-op/failed in-container run (false-green)

- **Repro** — `uv run portfolio project delegate dearreels.com "create DELEGATE_SMOKE.md …" --yes --force --budget 0.50` (live smoke test, v33.B).
- **Expected** — either the file is created (✓), or the run is reported as failed/no-op (`✗`/`↷`).
- **Actual** — `✓ agent finished · 33s · $0.00`; `DELEGATE_SMOKE.md` was NOT created (changed-files list = only dearreels' pre-existing dirty files). `$0.00` + zero new changes ⇒ claude never ran a real turn inside the container (suspect in-container auth/exec issue with the mounted `~/.claude`), but the orchestrator treats stream-EOF as success unconditionally.
- **Where (guess)** — `src/portfolio/delegate.py` `run_delegate` (the `else: status="done"` natural-end path) + `DockerBackend.stream`/`start` (claude install/auth in-container). Honesty gap mirrors ADR-0022.
- **Severity** — `major` (false-green defeats the verify posture; surfaced before v33.B is committed).
- **Notes** — Fix in v33.B before commit: parse the terminal `result` event (`is_error`/subtype/`total_cost_usd`), and treat `$0.00` + zero net new changes as `✗`/`↷`, not `done`. Also confirm the in-container claude actually authenticates against the mounted `~/.claude` (root vs non-root home path) and that `--output-format stream-json --verbose` emits the expected events. The sandbox lifecycle itself (container up, mount, supervisor, clean-kill, diff render) worked.
- **Root cause (confirmed live)** — two issues: (1) the container ran as **root**, and claude refuses `--dangerously-skip-permissions` as root → it exited immediately ($0.00, no work); (2) only `~/.claude` (dir) was mounted, not `~/.claude.json` (the auth/config file) → "config file not found." Fix: mount both at a non-root `HOME=/cc` and run the claude exec as the **host user** (`--user uid:gid`). Honesty layer added independently: `run_delegate` now requires a non-error terminal `result` event for `done` (no result ⇒ `error`).
- **Fixed in** — v33.B (host-user exec + both `~/.claude` + `~/.claude.json` mounts + result-event honesty); live-validated 2026-06-06 (file actually created, honest `✓`).

### BUG-063 · 2026-06-06 — pre-existing test failure: `test_check_143_deploy_drift::test_fail_when_declared_vercel_but_actual_is_wordpress`

- **Repro** — `uv run pytest tests/checks/test_check_143_deploy_drift.py::test_fail_when_declared_vercel_but_actual_is_wordpress`.
- **Expected** — assertion passes (severity `fail`).
- **Actual** — `AssertionError: - fail / + warn` at line 179 — the check returns `warn` where the test expects `fail`.
- **Where (guess)** — `checks/.../check_143` severity logic vs the test's expectation; drift between the check and its test. Unrelated to v33 (delegate isn't referenced by any check); fails on a clean tree.
- **Severity** — `minor` (one stale test; rest of suite green at 3188 passed).
- **Notes** — Surfaced while running the full suite during v33.B. Decide whether the check's `warn`-for-this-case is correct (→ update the test) or the test is (→ fix the check).
- **Reconfirmed 2026-06-12** — still fails on a clean tree (verified by stashing unrelated WIP). Precise case: the fixture row is `classification="error", status=500` with a WordPress `<meta generator>` in the body excerpt. The check warn-skips before the WP→`hostgator` fingerprint wins, so genuine drift on an *erroring* WP page is masked (declared `vercel` never gets flagged). Likely fix-or-spec call: should an error/non-200 live row still surface the WP fingerprint (→ `fail`), or is warn-skip-on-error intentional (→ update the test)? The iotnews.today canonical case is exactly a 500-serving WP page, which argues for `fail`.

### BUG-042 · 2026-05-25 — feature request: `lamill project sitemap resubmit <domain>` verb

**Motivation**

When GSC's sitemap fetch errors out (transiently: stale edge cache, sitemap not yet deployed, deploy raced submission), the operator's recovery path today is one of:

1. Open the GSC dashboard → Sitemaps → click the failing entry → Remove → resubmit.
2. Drop into a Python REPL and call `service.sitemaps().submit(siteUrl=..., feedpath=...)` directly.

Both are friction. The first requires leaving the terminal; the second requires knowing the API and importing the lamill GSC service module by hand.

**Proposed shape**

```
$ lamill project sitemap resubmit boxchive.com
  ✓ submitted https://boxchive.com/sitemap.xml to sc-domain:boxchive.com
  ↷ Google will re-fetch within ~24h. Re-run `project seo --refresh` to check.
```

Optional flags:
  - `--feedpath <url>` — override the sitemap URL (default: read from `robots.txt` Sitemap: line, fall back to `https://<domain>/sitemap.xml`).
  - `--property <sc-domain:X | https://X/>` — override the GSC property (default: auto-pick the registered property for this domain).

Underlying call: `service.sitemaps().submit(siteUrl=property_url, feedpath=feedpath).execute()`. Returns empty body on success; HTTP 4xx maps to typed errors (no GSC write scope → `re-auth` hint; sitemap not reachable → `404 — check robots.txt + sitemap URL` hint).

**Where**

New verb under `project sitemap` namespace (parallel to `project seo` / `project check` / `project fix`). Implementation in `src/portfolio/cli.py` + a thin wrapper helper in `src/portfolio/gsc.py`.

**Severity** — `minor` (feature, not bug). Lower priority than the rendering-bug above; mostly an ergonomics win for sites where the sitemap error is transient.

**Notes**

- The GSC OAuth scope is already `webmasters` (write) per v24.B — submission already works; just no CLI surface today.
- Could fold into the same phase as the rendering-bug fix (both touch GSC sitemap diagnostics).
- If the rendering-bug fix lands first, the typical operator workflow becomes: `project seo` shows PENDING → wait or resubmit. If the pending state takes too long, this verb is the resolution. Natural pairing.


### BUG-041 · 2026-05-25 — fleetwide canonical-redirect audit (v26.A scoping baseline) — 29 of 35 probed sites non-conforming

**Trigger**

Triggered by the homeloom.app finding below — operator asked "scan all sites and tell me which ones have the problem." This entry captures the one-off fleetwide probe that established the v26.C audit baseline. The probe logic mirrors what `CHECK_150_apex_canonical_redirect` will enforce automatically once v26.B ships.

**Probe method**

35 candidates probed (60-domain fleet minus 22 "To be deleted immediately" + 3 with `status != Active` + `csinorcal.church` dark/internal). Three HEAD requests per domain, no-follow:
  - `https://<apex>/` (expect 200)
  - `https://www.<apex>/` (expect 308/301 → apex, OR NXDOMAIN)
  - `http://<apex>/` (expect 308/301 → https://apex)

Anything 307 / 302 (temporary) or 200 on non-canonical = fail.

**Results — 29 fail, 6 pass**

Grouped by failure pattern (fix path differs per bucket):

**Bucket A — 307 apex→www + www serves 200 (homeloom.app pattern; SEO-blocking).** Apex's 307 prevents Google from consolidating signals; both URLs end up in indexation limbo. Likely Vercel-hosted with the dashboard's default "www is primary" toggle. Fix: in Vercel project → Domains, set apex as Primary; www auto-308s to apex.
  - calcengine.site
  - homeloom.app
  - keralavotemap.site
  - linkedcsi.live
  - washcalc.app

**Bucket B — 308 apex→www (wrong direction, not signal-breaking).** Apex 308-redirects to www (permanent); www serves 200. Google DOES consolidate signals — just to www, not apex. Functionally fine for SEO; inverts the v26.A apex-as-canonical convention.
  - civictools.app
  - lamill.io

**Bucket C — Split canonical + no HTTPS upgrade (WordPress/HostGator pattern).** Both apex and www serve 200 (no redirect between them) AND HTTP serves content without redirecting to HTTPS. Fix: per-site `.htaccess` edit (force HTTPS + 301 www→apex).
  - iotbastion.com
  - maslist.com
  - streamsgalaxy.com (HostGator/WP, per memory)
  - veezp.com
  - whizgraphs.com
  - yesuinnu.com

**Bucket D — HTTPS upgrade missing (otherwise clean).** Apex serves 200; www either NXDOMAIN or 308→apex. Only failure: `http://<apex>/` returns 200 instead of 308→https. Surprising for CF Pages/Workers — likely "Always Use HTTPS" toggle is off in CF dashboard.
  - agesdk.dev
  - airsucks.com
  - carrepairsite.com
  - cricketfansite.com
  - disclosur.dev
  - donready.xyz
  - dropaudit.co
  - isitholiday.today
  - kwizicle.com

**Bucket E — Not in scope of v26 (site is broken / not live).** Liveness issues, not canonical-redirect issues. Already covered by existing `fleet live` / `fleet seo` classification. Logged here only so the v26.C audit doesn't waste time re-investigating.
  - iotnews.today (apex=500)
  - lamill.us (apex=404; www TLS broken)
  - lamillrentals.com (www TLS broken)
  - navodayansonline.com (apex=405 — server rejects HEAD; needs GET re-probe to classify)
  - nosapta.com (apex=CONNREFUSED)
  - vijocherian.com (apex=CONNREFUSED)
  - virtually.co.in (apex=SSL broken; full chain broken)

**Pass (6)** — apex=200, www=NXDOMAIN-or-308→apex, http=308→https:
  - boxchive.com
  - dunam.co
  - earnlog.xyz
  - hybridautopart.com (HG/WP, but `.htaccess` is clean here — example to mirror for Bucket C)
  - permittruck.xyz
  - voltloop.site

**Severity per bucket** — `major` for Bucket A (5 sites; actively blocking indexation); `minor` for B/D (11 sites; non-conforming but no SEO bleeding); `minor` for C (6 sites; mixed SEO + security signal — Google flags HTTP-served pages as "Not Secure"); `n/a` for E (out of v26 scope).

**Where (guess)**

Platform dashboards (Vercel for Bucket A/B; Cloudflare for Bucket D; HostGator/`.htaccess` for Bucket C). No `lamill` code change is required to fix the affected sites — the v26.B check is the only code-side deliverable; fixes are operator-action per-site.

**Notes — relation to v26**

- This audit IS the v26.C "fleetwide audit" phase data — captured upfront so v26.B (check implementation) can be scoped against a known offender list.
- Recommended ordering: ship v26.B (`CHECK_150` at `warn` severity) → operator fixes Bucket A first → re-probe → fix Bucket D → fix Bucket C → fix Bucket B → re-probe → promote `CHECK_150` to `fail` (v26.C).
- Bucket A is the highest-leverage operator action right now (5 sites × ~2 min in Vercel dashboard each ≈ 10 min total to recover homepage indexation across 5 domains).
- Bucket E sites need separate triage (likely DNS / cert / DNS-only-no-deploy) — outside this entry's scope.


### BUG-040 · 2026-05-25 — homeloom.app apex→www redirect is 307 (temporary), blocks Google indexation; fleetwide canonical-redirect standard needed

**Repro**

```
$ curl -sI https://homeloom.app/
HTTP/2 307
location: https://www.homeloom.app/
```

**Expected**

Apex (or www) is the chosen canonical; the *other* variant 308-redirects to it. The redirect must be permanent (308 or 301), not temporary (307 or 302), so Google consolidates ranking signals onto the canonical URL.

**Actual**

`homeloom.app/` → 307 → `www.homeloom.app/`. GSC reports:

```
Coverage (top 4 inspected — 0/4 indexed, 0%)
  ✗ https://homeloom.app/   page with redirect   verdict=NEUTRAL
```

Google treats 307 as "this redirect might revert" and refuses to consolidate signals. Result: apex stays uncanonicalized AND the www target inherits no rank — both URLs are in indexation limbo.

The other "crawled - currently not indexed" rows (`/about`, `/privacy`, `/terms`) are normal for a <90d-old site (11 imp, 2-13d since crawl) and are NOT in scope of this bug — they'll resolve on their own with time.

**Where (guess)**

Vercel project-domain configuration for homeloom.app. Likely `vercel.json` or the project's Domains dashboard has `homeloom.app` set as a redirect (307) to `www.homeloom.app` (the primary). Two clean fixes:

1. **Flip canonical to apex** (recommended — matches the rest of the fleet): in Vercel → Project Settings → Domains, set `homeloom.app` as the primary domain; mark `www.homeloom.app` as "Redirect to" with permanent (308). This is the fleetwide convention (see below).
2. **Keep www as canonical**: change the 307 to a 308 by editing the redirect type in the Vercel dashboard or via `vercel.json`'s `redirects` block with `permanent: true`.

**Severity** — `major` for homeloom.app SEO (the homepage is non-indexable until fixed; ~zero organic until then).

**Notes — fleetwide canonical-redirect standard**

Adopt this convention across all `sites/<domain>/` projects:

1. **Apex is canonical.** Use the bare domain (`homeloom.app`, `airsucks.com`) as the primary URL. Rationale:
   - Matches Cloudflare Pages/Workers defaults (most of the fleet).
   - Single canonical → single SEO signal pool, no split-rank.
   - HSTS preload requires apex coverage.
   - Cleaner for marketing / link sharing.

2. **`www` subdomain is optional. If present, it MUST 308 → apex.**
   - CF Pages/Workers: typically no www DNS record at all — clean.
   - Vercel: set apex as primary; Vercel auto-308s www → apex.

3. **Redirect status MUST be permanent — 308 or 301, never 307 or 302.**
   - 308/301: Google consolidates ranking signals onto the canonical.
   - 307/302: Google holds signals back; canonical never accrues authority.

4. **HTTPS only.** All HTTP requests 308 → HTTPS. (CF + Vercel both do this by default; verify on any provider that doesn't.)

5. **Trailing-slash policy: no trailing slash on non-root URLs.** `/about`, not `/about/`. Either 308-redirect one form to the other, or set `<link rel="canonical">` to the preferred form. Secondary — only fix if GSC flags duplicates.

**Check candidate (`fleet seo` extension):** add `check_NNN_canonical_redirect.py` that asserts, for every fleet domain:
- apex → 200 OR apex → 308 → www→200 (one variant must 200, the other must 308 to it);
- HTTP → 308 → HTTPS;
- No 307 / 302 on the canonical-redirect chain.

A single check would have flagged homeloom.app in `fleet seo` and could prevent the next inversion. Not in scope to ship as part of this bug fix — log as `for-seo-check-improvements.md` follow-up and resurface when the operator wants a v(N).X bundle.


### BUG-036 · 2026-05-23 — Step 5.5 reports `↷ probe failed` on CF-managed read-only DNS records

**Repro**

Re-deploy a domain whose Workers Custom Domain attach has already
been completed (Step 6 prints `✓ already attached, skipping`). On a
fresh CF zone for that domain, CF auto-injects `read_only=true` DNS
records to manage the Workers route. Step 5.5's purge then tries
to DELETE them and CF responds with HTTP 400.

    $ uv run lamill new deploy agesdk.dev --yes
    ...
    5.5 Purge conflicting DNS records (agesdk.dev)
      ↷ DNS purge probe failed (continuing): DELETE /zones/.../dns_records/efe8e2ad2a5a7433a561e2aba8c7e6e1 → HTTP 400:
    {"result":null,"success":false,"errors":[{"code":1043,"message":"Unable to edit this record as this has been configured as read only."}],"messages":[]}
    6. Custom domain (agesdk.dev → agesdk · surface=workers)
      ✓ agesdk.dev already attached, skipping

**Expected**

When records are `read_only=true` because the Workers Custom Domain
already manages them, Step 5.5 should recognize the system is in a
correct state and print something like:

    5.5 Purge conflicting DNS records (agesdk.dev)
      ✓ no purgable conflicts (N records are CF-managed read-only — Workers Custom Domain manages those)

Operator sees "system is fine" instead of "probe failed (continuing)"
— the current wording reads like a partial failure even though the
deploy succeeds.

**Actual**

`purge_conflicting_root_records` LISTs DNS records, filters to
A/AAAA/CNAME on root/wildcard/www, and DELETEs each. It doesn't
check `read_only` first, so the DELETE returns 400 / code 1043
("Unable to edit this record as this has been configured as read
only"). The pipeline's non-403 catch-all soft-warns and continues —
correct behavior, but operator-facing message is misleading.

**Where (guess)**

- `src/portfolio/cloudflare.py` `purge_conflicting_root_records()` —
  filter out `read_only=True` records before attempting DELETE.
- Requires `DnsRecord` to expose `read_only: bool` (currently not in
  the dataclass — would need adding from the CF API response, which
  includes the field per CF docs).
- Could also skip Step 5.5 entirely when Step 6's custom-domain
  attach already exists. v25.B-style pre-flight detection: if the
  Workers Custom Domain or Pages Custom Domain is already attached,
  there are no parking records to purge — the deploy is steady-state.

**Severity** — `cosmetic`. Pipeline reaches Step 6 cleanly; the
operator-facing message just over-reports failure where the system
is actually in a correct state.

**Notes**

- Surfaced 2026-05-23 PM during operator's v25.B verification run.
- Adjacent to v15.R's pain-removal pattern; same value frame
  (operator-facing clarity on automated steady-state) but lower
  priority than the v25 tier's load-bearing token-scope work.
- Fix is bounded — add `read_only` field to DnsRecord; filter
  before DELETE; add ~2 tests. Could be bundled with the v25.B-era
  cloudflare.py module if picked up mid-v25; otherwise ship between
  phases.


### BUG-029 · 2026-05-20 — `make deps` hits pnpm store version mismatch on new-domain builds

**Repro**

After bootstrapping a new domain + running `make deps` inside
the sites Docker container:

    $ make buildsh
    # inside container:
    $ cd <newdomain>
    $ make deps
    ...
    [ERR_PNPM_UNEXPECTED_STORE] Unexpected store location
    The dependencies at "/usr/src/app/node_modules" are currently
    linked from the store at "/usr/src/app/.pnpm-store/v10".
    pnpm now wants to use the store at "/usr/src/app/.pnpm-store/v11"
    to link dependencies.
    If you want to use the new store location, reinstall your
    dependencies with "pnpm install".
    make: *** [Makefile:38: deps] Error 1

**Expected**

`make deps` for a fresh bootstrap should succeed without operator
intervention — either:
  - The bootstrap process pre-detects store version drift and
    wipes/rebuilds, OR
  - The store-dir is pinned per-project via `.npmrc` so each
    domain owns its store and doesn't inherit cross-domain state

**Actual**

Operator hits the error on every new-domain build because the
sites container's pnpm got bumped (v10 → v11) while pre-existing
`/usr/src/app/.pnpm-store/v10` is still on disk. pnpm refuses
to link against a store from a previous major version.

**Workaround**

```bash
make buildsh
# inside container:
rm -rf /usr/src/app/.pnpm-store
rm -rf /usr/src/app/<newdomain>/node_modules
pnpm install
```

Once cleared, subsequent builds work until the next pnpm major
version bump.

**Where (guess)**

Likely the bootstrap template needs an `.npmrc` with:

    store-dir=./.pnpm-store

(per-project store, isolated from the shared workspace store).

OR the parent `~/work/projects/sites/Makefile` (which `make deps`
forwards to) should detect store-version drift and auto-clean
before installing.

OR bootstrap's git-init step could emit a `.gitignore` entry for
`.pnpm-store/` so stale stores aren't committed.

Cleanest fix: per-project store-dir in `.npmrc` template, so each
sites/<domain>/ has its own `.pnpm-store/v<N>` directory under
the project root. Cross-domain isolation; no global state to
drift.

**Severity** — `major`

Blocks every new-domain bootstrap until operator manually clears
the store. Will hit on every pnpm major-version bump.

**Notes**

Surfaced 2026-05-20 by operator during second-domain bootstrap
session. Tied to the pnpm 10 → 11 transition. v15.S candidate.

The error is rooted in pnpm's design (rejects cross-major-version
stores) so it's not a CF/lamill bug per se — but lamill's bootstrap
emits the template that creates the trap. Fix lives in the
bootstrap template.

---

### BUG-028 · 2026-05-20 — `new bootstrap` should ask whether the frontend is already designed

**Repro**

    lamill new bootstrap agesdk.dev

The Lovable-repo-URL prompt (separate 2026-05-20 bug) jumps
directly to "paste the URL or skip". But the operator's mental
model has a logically-prior question: "have you designed the
frontend yet?" Two operator states:

  (a) **Frontend already designed in Lovable** → operator has a
      GitHub repo with the export. Bootstrap should ask for the
      URL, clone into `genai/`, run `--from-genai` path.
  (b) **Frontend not yet designed** → operator wants the blank
      template scaffold so they can run `make run` and design
      iteratively in the local dev server.

**Expected**

Replace the single "Lovable repo URL?" prompt with a two-step:

```
Is the frontend already designed? [y/N]:
  >: y
  Lovable / GitHub repo URL:
    >: https://github.com/user/agesdk-dev-ui

Is the frontend already designed? [y/N]:
  >: n
  → Will scaffold the blank Astro template; design in local dev.
```

Or as a single question with branching:

```
Frontend status:
  1. Already designed in Lovable — I have a GitHub repo URL
  2. Not yet designed — scaffold the blank template
  >: 2
  → Will scaffold the blank Astro template; design in local dev.
```

**Actual**

Bootstrap currently has only the implicit `--git-url` flag (no
prompt). The pending Lovable-repo-URL prompt (separate bug) doesn't
ask the prior "is the frontend designed?" question.

**Where (guess)**

The Lovable-repo-URL prompt being added in the same bootstrap-UX
session — extend it to the two-step form. Operator decides which
shape they want at implementation time.

**Severity** — `minor`

The current flag flow works fine; this is an interactive-UX
improvement that pairs with the pending Lovable-repo prompt.

**Notes**

Surfaced 2026-05-20 by operator. Both bugs (this + the Lovable-
repo-URL one) should land together in the same bootstrap-UX fix
commit.

---


### BUG-027 · 2026-05-20 — `new bootstrap` prompts don't validate input format

**Repro**

Vague — operator flagged "not understanding input" without a
specific repro. Suspected cases:

  1. Registrar prompt accepts arbitrary free text (`other` is the
     only documented fallback but typos like `porbun` get accepted
     verbatim and written into portfolio.json).
  2. Y/n prompts may not handle whitespace / capitalization
     gracefully — `Yes` or ` y` may behave differently than `y`.
  3. Operator's session output showed the ICP prompt's instruction
     text being LITERALLY captured as the answer in one case
     (operator hit Enter at the prompt header then started typing
     the instruction text from below) — suggests the prompt label
     might span multiple lines confusingly.

**Expected**

Each prompt's accepted input set is documented in the prompt
itself + validated. Whitespace-trimmed; case-insensitive where
appropriate; rejection messages list the accepted values.

**Actual**

Free-text accepted without validation in at least the registrar
prompt; behavior on whitespace / multiline pastes unclear.

**Where (guess)**

`_resolve_inventory_inputs()` / `_collect_operator_inputs()`
prompt logic in `src/portfolio/cli.py`. Add explicit `validate=`
arguments via Click or a custom `_prompt_choice()` wrapper that
loops on invalid input.

**Severity** — `minor`

**Notes**

Needs concrete repros from operator. Pairs with the multi-
paragraph paste bug above — both are part of an overall "the
prompt UX in bootstrap needs hardening" theme.

---

### BUG-026 · 2026-05-20 — `project check` groups `warn` results inconsistently across the rendered sections

**Repro**

    uv run lamill project check airsucks.com

Run against a site whose CHECK_145 (deploy-fresh, severity=warn) and
CHECK_146 (last-build-success, severity=warn) both return `warn`.

**Expected**

Both `warn` results land in the same section (either both under "Conformance
failures" or both under "Skipped"), with consistent glyph treatment.
Distinct sections for `pass` / `warn` / `fail` would also be acceptable.

**Actual**

The same severity (`warn`) renders into two different buckets depending
on the message wording:

```
Conformance failures (7):
  ...
  ✗ CHECK_145 deploy-fresh — can't read live version.json
    (https://airsucks.com/version.json → 404) — CHECK_144 surfaces the
    underlying cause.
...
Skipped (26): ..., CHECK_146
```

CHECK_145 returned `warn` and landed in *Conformance failures* with a
red ✗. CHECK_146 also returned `warn` but landed in *Skipped*. The
only obvious difference: CHECK_146's message contained the literal
substring `"skipped"`, CHECK_145's didn't.

**Where (guess)**

`src/portfolio/cli.py` — the `project check` renderer (search for
"Conformance failures" string in cli.py). Likely keys "skipped"
bucket off the message text rather than off the `CheckResult.status`
field. Should be a simple status-based split:

  - `pass` → "Passed"
  - `warn` → "Warnings" (new section, OR merge with Skipped)
  - `fail` → "Conformance failures"
  - explicit skipped (status=`skip`?) → "Skipped"

Need to confirm whether `CheckResult` even has a separate `skip`
status or whether `warn`-with-"skipped"-in-message is the existing
convention for skips.

**Severity** — `cosmetic`

**Notes**

Surfaced 2026-05-20 during the v15.D/E hand-test on airsucks.com.
Not a v15 regression — pre-existing renderer quirk that v15.D/E made
visible by adding two new warn-severity checks. Renderer fix lifts
all current warns + future warns consistently.

---

### BUG-005 · 2026-05-18 — `settings deploy set` fails for sites/ dirs missing from portfolio.json

**Repro**
    # Site has sites/<domain>/ directory but no entry in portfolio.json:
    uv run lamill settings deploy set hostkit.app vercel --domain hostkit.app --non-interactive

**Expected**
Writes `sites/hostkit.app/lamill.toml`. The site dir exists; the
operator's intent is clear. Drift between sites/ and portfolio.json
is its own concern (`fleet sync` / `fleet drift`), not a
blocker for declaring a deploy target.

**Actual**
Errors with `Domain not found in portfolio.json: 'hostkit.app'`
and exits 1. No file written.

This is a behavior discrepancy with the v10.C migration sweep
(`fleet repos --add-deploy-declarations`), which walks
`list_site_dirs()` and writes for any dir regardless of
portfolio.json membership. Both code paths produce a
`lamill.toml`; only one of them requires inventory presence.

**Where (guess)**
`src/portfolio/project_deploy.py:set_deploy` — uses
`resolve_project(name)` which is portfolio.json-keyed. The
migration sweep in the same module bypasses
`resolve_project` and walks the filesystem directly. Make
`set_deploy` either (a) fall back to the dir-name match when
portfolio.json lookup fails, (b) print a warning + proceed
anyway, or (c) suggest `fleet sync` and exit.

**Severity**
minor — workaround is `fleet sync` to reconcile
portfolio.json first, or hand-edit the JSON. Surfaces real drift
(sites/ dirs without inventory entries) which is useful, but the
hard-block on a write-only command is friction.

**Notes**
Discovered during v10.D walk 2026-05-18 — hostkit.app exists on
disk (has sites/hostkit.app/) but never got added to
portfolio.json. The fix conversation can include "should this
drift be treated as bug vs feature" — surfacing the drift early
might be the right behavior; just needs a clearer error.

---

### BUG-004 · 2026-05-18 — `settings deploy set` doesn't auto-populate `custom_domains` from dir name

**Repro**
    uv run lamill settings deploy set <domain> cf-pages --non-interactive
    cat sites/<domain>/lamill.toml

**Expected**
The resulting `lamill.toml` includes
`custom_domains = ["<domain>"]` — matching the convention the v10.C
migration sweep uses (`_execute_write` in `project_deploy.py`
auto-populates from the directory name).

**Actual**
Without explicit `--domain <X>` flag, `set-deploy` writes no
`custom_domains` entry. Operator has to remember to pass
`--domain <domain>` to match the migration sweep's output.
Inconsistency: `fleet repos --add-deploy-declarations` and
`settings deploy set <name>` produce different
`lamill.toml` shapes for the same input domain.

**Where (guess)**
`src/portfolio/project_deploy.py:set_deploy` —
`_resolve_domain_list()` returns `[]` when no flag and no
existing entry. Default could be `[name]` (the canonical domain
the operator just typed) when the prompt is skipped via
`--non-interactive`.

**Severity**
minor — workaround is one extra flag (`--domain <name>`); files
written without it are still valid `lamill.toml`, just under-
populated. Worth fixing before the v10.D walk gets serious.

**Notes**
Surfaced during v10.D dry-run apply (2026-05-18). Three
`set-deploy` calls (cricketfansite / isitholiday / voltloop) had
to be re-run with `--domain <name>` for parity with the 9 written
by the migration sweep. Fix is ~15 min: in `set_deploy()`, when
`custom_domains` flag is empty AND no existing entry, default to
`[name]`. Tests need updating to expect the auto-populated value.

---

### BUG-013 · 2026-05-19 — `fleet hosting` walkers miss ~9 fleet sites declared as `vercel` / `cf-*` *(diagnosed: data-quality, not walker bug — partial wontfix)*

**Repro**
    lamill fleet hosting --refresh

**Expected**
A row for every fleet site whose `lamill.toml` declares a
v11-supported platform (`vercel` / `cf-pages` / `cf-workers` /
`hostgator`). Per the v10.D scoreboard that's 20 sites (22 minus
the 2 HG ones currently skipped on the 403 issue).

**Actual**
Only 11 rows came back (6 `cloudflare-workers` + 5 `vercel`).
Missing: `agesdk.dev`, `calcengine.site`, `homeloom.app`,
`iotbastion.com`, `iotnews.today`, `lamill.io`, `linkedcsi.live`,
`thoralox.com`, `whizgraphs.com`.

**Diagnosis (2026-05-19, via direct Vercel API query)**

Dumped `GET /v9/projects?limit=100` against operator's Vercel
account (22 projects total). The 9 missing fleet sites split
into three categories:

| Category | Sites | Cause | Operator fix |
|---|---|---|---|
| **A. No Vercel project exists** | agesdk.dev · iotbastion.com · iotnews.today · lamill.io · thoralox.com · whizgraphs.com | Site declared `vercel` in `lamill.toml` but no project is registered in operator's Vercel account. iotnews.today is the canonical CHECK_143 drift case (declared vercel, actually serving WP on HG). The others are likely stale decls or sites never deployed to Vercel. | Either deploy the site to Vercel (then it'll surface), or fix the declaration via `lamill settings deploy set <name> <correct-platform>`. |
| **B. Vercel project exists but custom domain not attached** | calcengine.site (project `calcengine-site` exists, `alias` = only `*.vercel.app` URLs) · linkedcsi.live (project `linkedcsi` exists, `alias` = only `linkedcsi.vercel.app`) | Project deployed to Vercel; custom domain CNAME'd via DNS but never bound at the Vercel project level via the dashboard's Domains pane. Vercel only populates `targets.production.alias` for project-bound domains. | Attach the custom domain in the Vercel dashboard (Project → Settings → Domains → Add) for each. |
| **C. Project name mismatch** | homeloom.app (declared, but only `homeloop-app` exists in Vercel — typo? renamed?) | The Vercel project was either renamed, deleted, or has a different name than the operator's declaration assumes. | Confirm whether `homeloop-app` is the same project and rename in Vercel, OR fix the local declaration. |

**Where**
Not a walker bug — `walk_vercel` correctly reads
`targets.production.alias`. The data reflects reality:
operator has 6 sites with no Vercel project; 2 with project but
no domain binding; 1 likely typo. The walker faithfully reports
what Vercel says.

**Severity**
~~major~~ → **minor (mostly wontfix)** — walker is doing the
right thing. The hand-test "missing rows" is operator-side data
cleanup, not a tool defect. Two small walker enhancements would
help marginally:

1. *(optional)* Add `/v9/projects/{id}/domains` fallback fetch
   for projects whose `targets.production.alias` is empty —
   would catch category B (custom domain attached but not yet
   verified, so not in `alias`). Low priority — operator can
   fix in the dashboard.
2. *(optional)* When the walker can't find a Vercel project for a
   declared `vercel` site, emit a row with `error="no Vercel
   project for declared domain"` so it's visible. Useful for
   surfacing category A in the table without re-running
   diagnostics.

**Notes**
Folds these as future enhancements rather than blockers. Operator
clean-up of stale declarations is the higher-value action.

If the optional enhancements are wanted, both could land as a
small v11.B follow-up commit (the walker already has the right
shape; just needs the fallback fetch + the missing-project
synthesized row).

---

### BUG-012 · 2026-05-19 — HG walker `install_path` empty for every row despite addon-domain doc-roots existing

**Repro**
    lamill fleet hosting --refresh
    # Operator has 10 HG rows; all show disk usage in HG-extra column
    # but no install_path appended.

**Expected**
For addon domains, the walker's `_hg_list_domains` should extract
the `documentroot` field from each entry and pass it as
`install_path` to the HostingRow. v11.D/E/I rendering changes
already added `install_path` to the HG-extra display.

**Actual**
HG rows render `disk 4959MB` but no install_path. Walker's
extraction returns `None` for every addon entry.

**Where (guess)**
`src/portfolio/hosting.py:_hg_list_domains` reads
`entry.get("documentroot")`. Same lesson as the `megabytes_used`
fix from 2026-05-19 — the cPanel field name is likely
`document_root` (with underscore) or `path`. Real cPanel response
shape needs to be checked via curl on
`/execute/DomainInfo/list_domains`. Once the right field name is
confirmed, walker reads both (preferred name first, legacy fallback).

**Severity**
minor — table renders correctly otherwise; install_path is a nice
addition to operator visibility. Fix is one-line once the field
name is confirmed.

**Notes**
Diagnostic curl:

```bash
ACCOUNT="gator3164"
USER=$(grep "^HOSTGATOR_USER_GATOR3164=" portfolio.env | cut -d= -f2-)
TOKEN=$(grep "^HOSTGATOR_TOKEN_GATOR3164=" portfolio.env | cut -d= -f2-)
curl -s -H "Authorization: cpanel ${USER}:${TOKEN}" \
  "https://${ACCOUNT}.hostgator.com:2083/execute/DomainInfo/list_domains" \
  | python3 -m json.tool | head -40
```

---

### BUG-011 · 2026-05-19 — HG walker reports no `wp_version` for any row (WP detection blind)

**Repro**
    lamill fleet hosting --refresh
    # 10 HG rows; none show `WP <version>` in HG-extra column.

**Expected**
For WordPress installs on the HG fleet (operator's known
WP-on-HG sites are `hybridautopart.com` + `streamsgalaxy.com`),
v11.D should report `WP <version>` in HG-extra.

**Actual**
No WP version surfaces. `wp_version` is `None` on every HG row.

**Where (guess)**
`src/portfolio/hosting.py:_hg_list_wp_installs` calls
`WordPressManager/list_installations`. Walker is 404-tolerant — if
the module isn't available (older cPanel, no Softaculous/WP Manager
addon), the function returns `{}` silently. Three possible causes:

1. WordPressManager UAPI module isn't installed on operator's
   cPanel builds — walker correctly reports nothing.
2. Module is available but returns a different response shape
   than the walker expects (look for `installations` array vs
   top-level array, vs `installation_path` vs `path` field).
3. The doc_root match between `WordPressManager` response and
   `DomainInfo` response is failing (different path formats).

**Severity**
minor — table renders correctly; WP version is a nice-to-have
operator signal. Could fix with a different detection path —
e.g., scan `<doc_root>/wp-includes/version.php` via
`Fileman/list_files` or `Fileman/get_file_information`.

**Notes**
Diagnostic curl:

```bash
ACCOUNT="gator3164"
USER=$(grep "^HOSTGATOR_USER_GATOR3164=" portfolio.env | cut -d= -f2-)
TOKEN=$(grep "^HOSTGATOR_TOKEN_GATOR3164=" portfolio.env | cut -d= -f2-)
curl -s -H "Authorization: cpanel ${USER}:${TOKEN}" \
  "https://${ACCOUNT}.hostgator.com:2083/execute/WordPressManager/list_installations" \
  | python3 -m json.tool | head -40
```

If returns 404 → option 3 (alt detection path). If returns JSON
with installations → option 2 (field-name mismatch, fix walker).

---

## Fixed bugs

### BUG-070 · 2026-06-15 — `project seo` over-harsh ⛔ "blocked" verdict on young (<90d) sites

- Within the freshness window, coverage "unknown to Google" states are now softened to `⚠ indexing pending` (expected indexing lag) instead of driving the ⛔ "blocked" verdict; *crawled-but-declined* still surfaces as ⛔ (a real content/authority signal). cricketfansite.com now reads "🌱 unproven"; airsucks stays ⛔ honestly (its homepage is genuinely crawled-but-declined). Validated live on both young sites. **Fixed in** — `3da6dad` (2026-06-15 parallel bug-sweep). [`seo_diagnose.py`]

### BUG-069 · 2026-06-15 — retired obsolete `CHECK_144 has-version-stamp` + `CHECK_146 last-build-success`

- Both checked the abandoned `/version.json` convention (0/39 sites served it; v41.B moved deploy-freshness to the CF deployments API in `CHECK_145`). Deleted both checks + their tests; grep confirmed no dangling refs; `version_stamp.py` kept (still used by cli/hosting). **Fixed in** — `3da6dad`. [`checks/deploy/`]

### BUG-010 · 2026-05-19 — `fleet dashboard` truncated every cell on a standard terminal

- The Domain column is now sized to the longest domain (`no_wrap`) so domains render in full instead of `air…`/`hyb…`; the metric columns flex/abbreviate instead. **Fixed in** — `3da6dad`. [`dashboard.py`]

### BUG-003 · 2026-05-18 — `fleet seo` vs `fleet domains` showed different counts

- Diagnosed as a legitimate scope difference (fleet seo probes live-site/forwarder only). Reconciled in the `fleet seo` footer: `N live-site/forwarder domains probed (K parked/dead/error excluded from M fleet)`. **Fixed in** — `3da6dad`. [`cli.py`, `seo_runtime.py`]

### BUG-068 · 2026-06-15 — `project seo` reports "Sitemap lists only 0 URLs" on a sitemap with 8 URLs (TanStack `https://` namespace)

- **Repro** — `lamill project seo airsucks.com` → State header `Sitemap 0 URLs`; Blockers: `⚠ Sitemap lists only 0 URLs`. The live sitemap has 8 `<url>` and GSC reports `submitted: 8, errors: 0`.
- **Expected** — count the 8 URLs Google sees.
- **Actual** — 0. Root cause: TanStack Start emits the sitemap with the **`https://`** scheme namespace (`xmlns="https://www.sitemaps.org/schemas/sitemap/0.9"`) — a *different* XML namespace (exact-string compare) than the spec's `http://`. lamill's ElementTree parsers were pinned to `{http://…}`, so `findall` matched zero `<url>`. Google is lenient and parsed all 8 (verified via the GSC Sitemaps API: `submitted: 8`); lamill was over-strict.
- **Where** — `checks/seo/_live.py::_extract_sitemap_locs` **and** `gsc_recrawl.py::_extract_locs` (the latter is what `project seo` actually uses — see open dup-parser bug 2026-06-15).
- **Fix** — switched both `_SITEMAP_NS` to the `{*}` wildcard (matches http/https/no-namespace), dropped the now-redundant bare-name fallbacks (they double-counted no-namespace docs). 4 regression tests added.
- **Severity** — `major` (false blocker on every TanStack-Start site; misreports a healthy site as broken).
- **Fixed in** — `2026-06-15` sitemap-namespace `{*}` fix (portfolio).
- **Notes** — first fixed the wrong parser (`_live.py`) by pattern-matching instead of tracing the symptom's call path; the duplication that allowed that is logged as an open bug (same date).

- **Repro** — `lamill new deploy iotbastion.com` Step 4 (registrar NS → Cloudflare): `✗ GoDaddy NS update failed: set nameservers iotbastion.com: HTTP 404 {"code":"NOT_FOUND","message":"Not Found : The requested resource was not found"}`.
- **Expected** — Step 4 points the domain's nameservers at the CF pair (ADR-0015-idempotent), 200 on success.
- **Actual** — 404 on every GoDaddy domain. `GET /v1/domains/{domain}` returns 200 (domain readable, status ACTIVE), but `godaddy.set_nameservers` issued `PUT /v1/domains/{domain}` — GoDaddy's domain resource registers **no PUT route**, so the gateway answered 404 NOT_FOUND. The v31.C NS auto-push thus never actually pushed: the read-side (v31.B inventory) was validated, the write-side was never exercised against the real API.
- **Where** — `godaddy.py:set_nameservers` (`c.put` → `c.patch`).
- **Severity** — `major` (blocks the registrar-NS step of `new deploy` for all ~44 GoDaddy domains).
- **Notes** — Root cause: GoDaddy updates the domain resource via **PATCH** (the DomainUpdate body carries `nameServers`); there is no PUT. The bug shipped green because `test_set_nameservers_puts_expected_body` asserted `method == "PUT"` against an httpx `MockTransport` that accepts any verb — the test validated the wrong method instead of catching it. Fix: `PUT` → `PATCH`; test renamed → asserts `PATCH` (regression guard). Recorded as v31.E.
- **Validated** — code now sends PATCH (GoDaddy's documented update method); **needs live validation** on a real GoDaddy domain whose NS still needs changing — the mock confirms lamill *sends* PATCH, not that GoDaddy *accepts* it. Suite-green (8 godaddy-ns tests).

### BUG-062 · 2026-06-06 — `new deploy` Step 9 runs GSC verify/sitemap against un-propagated DNS + false-greens a deferred sitemap as "submitted" (mathbloom.xyz)

- **Repro** — `lamill new deploy mathbloom.xyz` (no `--watch`) right after the Step 4 NS cutover, before delegation propagated (Step 8: `↷ no DNS answer yet`). Step 9 ran anyway.
- **Expected** — Step 9 (GSC verify + sitemap) needs the deploy reachable; on un-propagated DNS it should defer (transient `↷`) and let the idempotent re-run complete it (ADR-0015). Nothing should be reported submitted that wasn't (ADR-0022 honesty).
- **Actual** — two issues. (1) Without `--watch`, Step 9 was gated only on the watch result, so it ran unconditionally even when Step 8 reported the apex unreachable — burning a GSC verify-poll and emitting a red `✗ verify_domain (DNS_TXT) failed` for a transient state. (2) `_deploy_step9_gsc` returned `"created"` for *both* "sitemap submitted" and "sitemap deferred"; the summary then printed `✓ GSC: … sitemap submitted` even when the sitemap HEAD-probe failed and submission was deferred (false-green in the verify-OK-but-sitemap-unreachable window).
- **Where** — `cli.py:_deploy_cf_unified` (Step 8/9 gating + GSC summary block) + `cli.py:_deploy_step9_gsc` (deferred return status) + `cli.py:_deploy_step8_live_probe`.
- **Severity** — `major` (false-green violates the ADR-0022 deploy-verification-honesty posture; the premature GSC verify is noisy but the sitemap *submission* was already correctly guarded by the v32.G HEAD probe, so no bad sitemap was actually planted in GSC).
- **Notes** — Fix: `_deploy_step8_live_probe` now returns the liveness bool; Step 9 is gated on a confirmed-live apex on *both* the `--watch` (`watch_result == "live"`) and no-watch (Step 8 probe) paths → `↷ deferred` instead of running. `_deploy_step9_gsc` returns distinct `created:sitemap_deferred` / `already-registered:sitemap_deferred` statuses, and the summary renders them as `↷ … sitemap deferred — re-run once live` (no "submitted" claim). Also dropped a dead `skipped:watch_` summary branch. 6 tests (4 Step-8 gate + 2 updated deferred-status asserts); deploy/gsc nets green (530). Surfaced during the v35.A audit / mathbloom.xyz deploy.
- **Validated** — needs operator validation against a real fresh deploy (re-run after propagation should flip the deferred sitemap to submitted). Suite-green only so far.

### BUG-061 · 2026-06-06 — `new deploy` crashes with a raw `httpx.ReadTimeout` traceback when CF Pages-project create times out

- **Repro** — `lamill new deploy retouchlint.com --yes --watch`; Step 5 (`create_pages_project_with_git`) POST to `/accounts/{id}/pages/projects` hit a read timeout.
- **Expected** — a network timeout on a CF call is transient → report `↷` + re-run (ADR-0015), not a crash.
- **Actual** — `ReadTimeout: The read operation timed out` escaped as a full traceback (the caller only caught `CloudflareAPIError`), killing the deploy mid-pipeline.
- **Where** — `cloudflare.py:create_pages_project_with_git` (the `c.post`) + `cli.py:_deploy_cf_unified` Step 5 handler.
- **Severity** — `major` (deploy-pipeline crash; violates ADR-0022 honesty / ADR-0015 resilience).
- **Notes** — Fix: new `CloudflareTransientError(CloudflareAPIError)`; the create-POST catches `httpx.TimeoutException`/`TransportError` → raises it, with a longer 60s POST timeout (Pages create legitimately exceeds the 15s default); Step 5 catches the transient variant first and reports `↷` + re-run guidance (no misleading "GitHub App not connected" block). 2 regression tests.
- **Validated** — operator re-ran `new deploy retouchlint.com --yes --watch` 2026-06-06: all 10 steps completed (Step 5 created the Pages project, build success, HTTP 200).

### BUG-060 · 2026-06-05 — hand-edits to the generated `data/portfolio.json` (mark-for-deletion, autorenew-off) are silently reverted by the next `fleet sync` refresh (iotnews.today, nosapta.com)

**Repro** — `a08eb1b` marked `iotnews.today` `auto_renew On→Off` + `category "Next session"→"To be deleted immediately"` by editing `data/portfolio.json`. A 2026-06-05 refresh (`cleanup()`, `generated_at` → `2026-06-05T10:04`) regenerated the file and **reverted both fields** back to `On` / `"Next session"`; the revert is uncommitted in the tree. `nosapta.com`'s intended deletion edit was lost the same way (now shows `My brand` / `On`).

**Expected** — a domain the operator has marked for deletion (autorenew turned off at the registrar, category "to be deleted") stays that way across refreshes, and stops raising a `🔴` health alarm (intentional death ≠ regression).

**Actual** — `data/portfolio.json` is a **generated** file (`data.py:cleanup()` rebuilds it from registrar CSVs + classification), so direct edits are overwritten. `data/domains/godaddy.csv` still lists both domains `auto_renew "On"` — it's a **manual export not re-pulled** since the operator turned autorenew off at GoDaddy (GoDaddy has no API). `category` is re-derived from the curated classification source, which has no "To be deleted". So the refresh reverts curated edits, and `fleet focus`/`live` keep flagging the (now genuinely dead) domains `🔴`.

**Root cause** — deletion/curation intent was written to the generated OUTPUT with no source layer to carry it. **Same class as the 2026-05-19 thoralox.com bug** (GoDaddy-no-API → stale manual CSV → generated `portfolio.json` reverts curated edits). Compounding: the health view has no notion of "intentionally dying," so it alarms on these regardless of category.

**Where** — `src/portfolio/data.py` `cleanup()` / `_apply_classification` (category) + the `data/domains/godaddy.csv` manual-export path (auto_renew); `src/portfolio/focus.py` + `fleet live` (`🔴` regardless of "to be deleted").

**Severity** — `major`. Curated state is silently lost on every refresh; has now bitten twice (thoralox, then iotnews/nosapta). Low blast radius per-incident but erodes trust in the inventory.

**Fixed in** — durability resolved without the drafted overrides layer (**v34 dropped 2026-06-06** after audit): (1) **`auto_renew`** is now registrar-API truth — **v31** `fleet sync --refresh` pulls GoDaddy `auto_renew` (live-validated `Off` for iotnews/nosapta); the "GoDaddy has no API" premise in *Actual*/*Root cause* above was wrong (see ADR-0021). (2) **`category`** always had a durable home in `plan.md` (re-derived by `cleanup()` every run); the real defect was `plan.md`'s **false "deprecated — editing has no effect" banner**, which sent edits to the generated `portfolio.json`. Banner corrected + `iotnews.today`/`NOSAPTA.COM` moved to `### To be deleted immediately` (2026-06-06). **Accepted limitation:** the `🔴` health-view alarm on intentionally-dying domains stays (v34.C dropped) — cosmetic; the `dark_sites` suppression is the template if it ever earns a fix. See `docs/prd.md § v34`. Related: 2026-05-19 thoralox.com entry.

### BUG-059 · 2026-06-05 — `new deploy` submits `/sitemap.xml` to GSC, but `@astrojs/sitemap` emits `/sitemap-index.xml` → fleet-wide GSC "sitemap parse errors" (drdebug.dev, mdburst.com)

**Repro** — `lamill fleet focus` shows `drdebug.dev` + `mdburst.com` as `🔴 GSC: sitemap parse errors (1)`.

**Diagnosis (confirmed via curl)** — `https://drdebug.dev/sitemap.xml` returns `HTTP 200` but **`content-type: text/html`**: the Astro SPA's catch-all (`not_found_handling: single-page-application`) serves `index.html` for the unmatched `/sitemap.xml` route, so GSC fetches HTML and can't parse it as XML. The **real** sitemap is at `https://drdebug.dev/sitemap-index.xml` (`200`, `application/xml`, valid — that's what `@astrojs/sitemap` emits), and `robots.txt` already points there: `Sitemap: https://drdebug.dev/sitemap-index.xml`. But deploy Step 9 hardcodes `f"https://{domain}/sitemap.xml"` and submits that.

**Expected** — deploy submits the site's *actual* sitemap URL (the one in `robots.txt`), so GSC gets valid XML.

**Actual** — `/sitemap.xml` is assumed. `@astrojs/sitemap` (used across the Astro fleet) emits `sitemap-index.xml` + `sitemap-0.xml`, never `sitemap.xml`, so **every Astro-sitemap site gets a GSC parse error** and its sitemap is effectively unsubmitted.

**Root cause** — sitemap URL is assumed, not derived. The canonical pointer is the live `robots.txt` `Sitemap:` line (which `@astrojs/sitemap` auto-populates).

**Where** — `src/portfolio/cli.py` `_deploy_step9_gsc` (~7855–7894, builds `/sitemap.xml`); `gsc_admin.submit_sitemap(domain, sitemap_url)` takes the URL (fine — caller picks the wrong one); `project_seo_diagnostics` sitemap fetch.

**Severity** — `major`. Fleet-wide false GSC errors; the actual sitemap never gets submitted for Astro-sitemap sites.

**Mitigation (2026-06-05)** — resubmitted the correct `…/sitemap-index.xml` for `drdebug.dev` + `mdburst.com` via `gsc_admin.submit_sitemap`. The broken `/sitemap.xml` entries remain in GSC (no `delete_sitemap` verb yet) until removed manually or by the fix.

**Fix** — **v32.G** (drafted): deploy Step 9 + the GSC sitemap diagnostics read the live `robots.txt` `Sitemap:` line as the submit URL (fallback `/sitemap.xml`); optional `delete_sitemap` to clear the stale entry. Related: 2026-05-25 `project sitemap resubmit` feature request (same robots.txt-feedpath idea).

**Fixed in** — `6127262` (v32.G — `resolve_sitemap_url` reads the robots.txt `Sitemap:` line; `delete_sitemap` clears stale entries).

### BUG-058 · 2026-06-05 — `new deploy` Step 4 trusts Porkbun's `getNs` API over real delegation → reports NS cutover done while the domain is still on Porkbun NS (mdburst.com)

**Repro** — `lamill new deploy mdburst.com --watch --yes` (cf-pages). Step 4 printed:
```
4. Registrar NS (point mdburst.com at Cloudflare)
  ✓ Porkbun NS already match Cloudflare (dom.ns.cloudflare.com, kristina.ns.cloudflare.com)
```
but the domain's authoritative delegation is still Porkbun:
```
$ dig +short mdburst.com NS
curitiba.ns.porkbun.com.
fortaleza.ns.porkbun.com.
maceio.ns.porkbun.com.
salvador.ns.porkbun.com.
$ dig +short mdburst.com A
52.33.207.7
44.230.85.241          # AWS — Porkbun forwarding infra, not Cloudflare
```

**Expected** — Step 4 verifies the *actual* delegation (`dig NS`) and, if the domain isn't really on Cloudflare NS, performs (or clearly reports it can't perform) the cutover — not a green "already match" based solely on the registrar API's stored value.

**Actual** — Step 4 reads NS via Porkbun `getNs` and set-compares to the CF target (`ns_matches`). The API returned the CF NS (someone/something set them in Porkbun's record), so the check passed and skipped the cutover — while the real registry delegation stayed on Porkbun. The deploy "completed" but `mdburst.com` never moved to CF.

**Root cause (confirmed)** — `mdburst.com` has **Porkbun URL Forwarding enabled** (apex serves `HTTP 302 → https://mdburst-com.l.ink/`, `l.ink` = Porkbun's forwarder). Porkbun URL Forwarding pins the domain to Porkbun nameservers regardless of the stored NS value, so the registrar API and the real delegation disagree. lamill never reads or clears URL Forwarding (`porkbun_list.py:143` — *"URL FORWARDS — separate API endpoint; not in scope here"*), so it can't see why the cutover silently no-ops.

**Where** — `src/portfolio/cli.py` Step 4 block (~6747–6812), decision at ~6781 (`ns_matches(current_ns, target_ns)` → "already match"); `src/portfolio/porkbun_dns.py` `get_porkbun_ns()` (55–105, `POST /domain/getNs/<domain>`) + `ns_matches()` (160–165) — neither does an authoritative resolver check. Reusable: `src/portfolio/diagnose.py` `_dig()` (152–163) already does `dig +short` lookups (used by `probe_dns()`).

**Severity** — `major`. A cf-pages deploy can report success + "fully live" while the domain still serves the registrar parking forward; no self-recovery, and the green output actively misleads. Hits any domain with Porkbun URL Forwarding still set.

**Notes** — paired with the live-probe bug below (same deploy run): the false NS "match" is what *let* the run proceed, and the redirect-following probe is what *confirmed* a false "live." Fix scope in chat 2026-06-05. Manual recovery for mdburst: disable URL Forwarding at `https://porkbun.com/account/domain/mdburst.com`, set NS to `dom.ns.cloudflare.com` / `kristina.ns.cloudflare.com`, re-run deploy.

**Fixed in** — `ab37c41` (v32.C — Step 4 reports real `dig NS` delegation vs the registrar API) + `d625335` (v32.D — detect/clear the Porkbun URL Forwarding that pinned NS, the root cause).

### BUG-057 · 2026-06-05 — `new deploy` live probe + `--watch` follow an off-domain 302 to a parking host and report it as `200 OK · fully live` (mdburst.com)

**Repro** — same run (`lamill new deploy mdburst.com --watch --yes`). The watch loop and Step 8 printed:
```
  [00:00] zone=active     build=success        live=200
✓ mdburst.com fully live (zone active · build success · HTTP 200 · 0s)
8. Live probe (https://mdburst.com/)
  ✓ 200 OK (3921 bytes)
```
but the apex actually returns a cross-domain redirect to Porkbun's forwarder:
```
$ curl -sS -I https://mdburst.com/
HTTP/2 302
server: openresty
location: https://mdburst-com.l.ink/
content-length: 142
```

**Expected** — A 3xx to a *different registrable domain* (and especially a known parking/forwarder host like `l.ink`) is **not live**. The probe should report `↷ forwarded to <host>` (or `✗ parked`) and the watch loop should not count it toward "fully live."

**Actual** — `_deploy_step8_live_probe()` (`cli.py:7355–7387`) does `httpx.get(..., follow_redirects=True)` and never inspects `r.url`, so it follows `302 → l.ink`, lands on the 3921-byte parking page, and prints `✓ 200`. The watch loop (`_deploy_watch_loop()`, `cli.py:7412–7548`) HEADs with `follow_redirects=True` and at ~7512 sets `live_ok = live_status.startswith("2") or live_status.startswith("3")` — so even an *un-followed* 3xx counts as live.

**Where** — `src/portfolio/cli.py` `_deploy_step8_live_probe()` (7355–7387, `follow_redirects=True`, ignores final URL) and `_deploy_watch_loop()` (live block ~7486–7496; "fully live" determination ~7510–7520, `startswith("3")`). Reusable: `src/portfolio/check.py` `_classify()` (96–119) already detects forwarders/parking by comparing eTLD+1 of the final URL host vs the domain, with `PARKED_HOST_SUFFIXES` (18–24) — **`l.ink` is not in that list yet**; `_fetch()` captures `final_url = str(resp.url)` (134).

**Severity** — `major`. Turns a non-deployed/parked apex into a green "fully live" — the core false-positive the operator hit. Decoupled from Bug 1 (NS): even with NS correct, any apex that 3xx-redirects off-domain would mis-report.

**Notes** — fix could reuse `check.py`'s classifier rather than reinventing: probe with `follow_redirects=False` (or inspect `resp.url` after following), and if the final host's eTLD+1 ≠ the domain's, treat as not-live with a `↷ forwarded to <host>` line; add `l.ink` to `PARKED_HOST_SUFFIXES`. Watch loop must drop `startswith("3")` from `live_ok`.

**Fixed in** — `ab37c41` (v32.B — `_probe_apex_live` classifies the followed-redirect final host; a forwarded/parked apex is not-live; `l.ink` added to `PARKED_HOST_SUFFIXES`).

### BUG-056 · 2026-05-31 — `new deploy` builds the apex CNAME from `{slug}.pages.dev`, but CF can assign a suffixed project subdomain → permanent `1014` (scopeguard.xyz)

**Repro** — `lamill new deploy scopeguard.xyz` (cf-pages). Pipeline reached `zone=active build=success` but the live probe returned `403` with body `error code: 1014` ("CNAME Cross-User Banned"), and `--watch` timed out after 30 min still at `live=403`. The Pages custom domain sat at `status=pending` forever.

**Root cause (confirmed via the CF dashboard + API)** — `cli.py:7100` sets the apex CNAME target as `target_content = f"{slug}.pages.dev"` (here `scopeguard.pages.dev`). But Cloudflare assigned this project the subdomain **`scopeguard-abu.pages.dev`** (it appends a random suffix when the bare `<slug>.pages.dev` name is already taken globally). So the apex CNAME pointed at a `pages.dev` host that **isn't this project** → CF edge returns `1014`, and the custom-domain verification never completes (it's validating against a wrong target). Not a timing/propagation issue — it would never have resolved.

**Fix applied to scopeguard (2026-05-31, manual)** — read the project's real subdomain (`GET /accounts/{acct}/pages/projects/{proj}` → `result.subdomain` = `scopeguard-abu.pages.dev`), PATCH the apex CNAME content to it, then remove + re-add the custom domain to re-verify against the corrected record. Domain went `pending → active` in ~100s; live is now `HTTP 200`. (Cloudflare infra only — no repo data changed.)

**The lamill defect + fix** — step 6.5 must NOT assume `{slug}.pages.dev`. The Pages project object returned by `create_pages_project_with_git` / `get_pages_project` carries the authoritative `subdomain` field — use **that** as the CNAME target. This is the real fix and prevents the bug for any future site whose slug collides on `pages.dev`.

**Secondary (aggravating) gap** — `new deploy` is idempotent (ADR-0015): step 6 (attach domain) is GET-then-skip and step 6.5 (apex DNS) is create-if-absent, so re-running on the broken state changes nothing and re-stalls at `live=403`. Worth a deploy-resilience follow-up: detect `1014` / `pending`-too-long during the watch and surface a distinct `✗ pending-verification` state with the remediation, plus a `--repair` re-verify path, instead of a generic `watch_timeout`.

**Where** — `src/portfolio/cli.py:7100` (`target_content = f"{slug}.pages.dev"`, in `_deploy_cf_unified` step 6.5); the correct value is on the Pages project object (`subdomain`) from `src/portfolio/cloudflare.py` `create_pages_project_with_git` / `get_pages_project`.

**Severity** — `major`. Any cf-pages deploy whose slug is already taken on `pages.dev` lands permanently broken (`1014`) with no self-recovery. The CNAME-target fix is small and high-value; the resilience improvements are a separate tier.

**Severity** — `major` (a fresh deploy can land in a broken, un-self-healing state) but **situational** (apex cf-pages custom-domain verification path). Tracked for a future deploy-resilience tier.

**Repro** — `thoralox.com` was renewed at GoDaddy (new expiry 2027-05-30) but `lamill fleet focus` showed `⚠️ Expiring in -99 days → renew at registrar before lapse`.

**Root cause (two layers)**
1. **Data staleness.** GoDaddy has no API (ADR — see architecture §6 "Provider API coverage"), so `data/domains/godaddy.csv` (a manual export, last refreshed 2026-04-24) and the materialized `data/portfolio.json` held the *pre-renewal* expiry `2026-02-20`. `lamill fleet sync --refresh` only refreshes Porkbun, so GoDaddy inventory silently goes stale until a manual re-export. (thoralox patched by hand 2026-05-30; the broader staleness remains for other GoDaddy domains.)
2. **Confusing display.** `focus.py:~200` fires the ⚠️ for any `days <= 30` with no lower floor, so a *past* expiry renders as `Expiring in -99 days → renew before lapse` — reads like a future expiry and hides that the data is stale/lapsed.

**Proposed fix (code, deferred — log only per operator)** — for `days < 0`, change the message to e.g. `expired N days ago (per <registrar> inventory, exp <date>) — verify renewal / re-export inventory`. Optionally surface the inventory-export staleness (e.g. `godaddy.csv` mtime) so GoDaddy drift is visible without a per-domain surprise.

**Where** — `src/portfolio/focus.py` (~line 200, expiring signal); `data/domains/godaddy.csv` (manual export); `src/portfolio/data.py` `_load_godaddy`.

**Severity** — `minor`. The display is cosmetic/confusing, not wrong logic; the data half is inherent to GoDaddy-no-API and is mitigated per-domain by hand-patch or full re-export. No code change made yet (operator: log only).

**Fixed in** — `d373077` (v32.E — `_resolve_pages_subdomain` re-fetches the authoritative `*.pages.dev`) + `279e350` (v32.F — `pending_verification` state + `--repair` re-points the CNAME and re-verifies).

### BUG-055 · 2026-05-30 — legacy `lamill.toml` write paths full-rewrite and drop `[content]` + comments

**Repro** — Run a CLI command that writes `lamill.toml` via `lamill_toml.write()` on a site that has a hand-authored `[content]` block (every site does as of the 2026-05-30 fleet migration). `write()` re-serializes the whole file from the parsed `LamillToml` struct; `to_dict` only emits tables it knows, so `[content]` (and any unknown table) is **dropped** along with all inline comments + ordering.

**Investigation (v27.J, 2026-05-31)** — audited the four suspected write paths:
- `set_deploy` (`settings deploy set`, `project_deploy.py:187`) — **real clobber risk.** "Create-or-update": runs on existing files and rebuilt the payload from `deploy/hosting/backend/notes`, so it dropped `[stack]`, `[[todo]]`, AND `[content]`.
- v10.C deploy-declaration migration (`_execute_write`, `project_deploy.py:719`) — **not a risk:** caller skips when `lamill.toml` already exists (new-file-only).
- `hosting` apply-declarations (`hosting.py:1695`) — **not a risk:** explicit `skipped_already` when the file exists (new-file-only).

**Fixed in** — v27.J (2026-05-31). Added a generic surgical `lamill_toml_edit.set_table(repo, name, body|None)` upsert (replace/insert/remove one flat top-level table, byte-preserving the rest). `set_deploy` now upserts only `[deploy]` / `[hosting]` on an existing file (full `write()` reserved for new files); the other two paths keep `write()` since they only ever create new files. 5 tests; suite green. Per ADR-0018, all CLI `lamill.toml` mutations are now upserts.


### BUG-054 · 2026-05-29 — `fleet focus` ignores `[fleet] dark_sites`; csinorcal.church + virtually.co.in surface despite operator-declared exclusion

**Repro** — Add `virtually.co.in` to `[fleet] dark_sites` in
`~/.config/portfolio/config.toml`. Run `lamill fleet focus --all`.
`virtually.co.in` is still listed as `🔴 Site is ssl-broken` (and
`csinorcal.church` too — same issue, never caught because it had no
recent live failure).

**Actual (pre-fix)** — `cli.py focus()` loaded `all_domains` from
`portfolio.json` but never consulted `cfg.dark_sites`. The config knob
was only honored by `fleet fix` (`cli.py:8259`) — `fleet focus` /
`fleet seo` / `fleet dashboard` never read it. The global memory rule
`[[project-dark-sites]]` says dark sites should be ignored across all
public-SEO surfaces; the implementation was narrower than the policy.

**Fix** — `focus()` now loads `load_config().dark_sites` and filters
in two places: (1) `all_domains` is dropped early so the CF cache probe
and signal aggregation skip dark sites; (2) the `items` output from
`build_focus_list` is filtered again to catch any dark site that
surfaces purely from cached snapshot data (build_focus_list iterates
the live/seo snapshots directly). A footer `↷ excluding N dark site(s):
…` surfaces the exclusion (mirrors `fleet fix`'s footer); silent
suppression would hide the wrong-default risk.

**Where** — `src/portfolio/cli.py` `focus()`.

**Severity** — `minor` (operator-visible noise; no data corruption).
`fleet seo` likely has the same gap and should follow up if the noise
recurs there.

**Tests** — covered by existing `test_focus.py` (171 passed unchanged)
+ manual: ran `lamill fleet focus --all` with
`config.toml [fleet] dark_sites = ["csinorcal.church", "virtually.co.in"]`,
confirmed both excluded and footer renders `(edit [fleet] dark_sites in
config.toml to change)`.

**Fixed in** — `5c9f8fc` (fleet focus dark_sites filter)

### BUG-053 · 2026-05-29 — `new bootstrap` smart-paste mis-routes when the pasted reply has bare-label headers (numbers stripped by markdown copy)

**Repro**

1. `lamill new bootstrap vijocherian.com --git-url <url> --budget 5.0`
2. Generate the reply in claude.ai from the copy-paste template, then
   paste it at the full-reply prompt. claude.ai renders `2. Summary` as a
   markdown ordered-list / bold heading; copying the rendered text strips
   the `N.`, so what reaches lamill is bare labels on their own lines
   (`Summary` / `Audience` / …, content beneath).

**Actual (pre-fix)** — `parse_multisection_paste` only recognized
numbered headers (`_HEADER_RE = ^\d+\.`), so bare-label headers matched
nothing → returned `None`, and the whole blob was saved as the Summary
("✓ saved as Summary"), then prompts 3-9 fired empty. (Confirmed against
the operator's screenshot: claude.ai output was correct; the markdown
copy dropped the numbers.)

**Fix** — two layers:
- Parser: `_promote_bare_label_headers` prepends a number to any line
  that is EXACTLY a canonical section label (normalized; full labels
  only, not the fuzzy short aliases), so bare-label replies parse.
  `_strip_code_fences` unwraps a ```…``` block. `is_section_header_line`
  (numbered OR bare label) now also drives the prompt's blob detection,
  and blob mode triggers on a leading ``` fence too.
- Template tuned: asks the LLM to put the whole reply in one fenced code
  block so the `N.` numbers survive copy-paste verbatim.

**Where** — `src/portfolio/bootstrap_paste.py`
(`_promote_bare_label_headers` / `_strip_code_fences` /
`is_section_header_line`), `src/portfolio/cli.py` (`_prompt_multiline`
blob detection + `_render_llm_prompt_template`).

**Severity** — `major` (silent content corruption; the common
copy-from-rendered-markdown path).

**Tests** — `tests/test_bootstrap_smart_paste.py`:
`test_parser_bare_label_headers_route_correctly`,
`test_parser_strips_wrapping_code_fence`,
`test_parser_bare_label_does_not_promote_prose_lines`,
`test_is_section_header_line_detection`,
`test_collect_bare_label_blob_routes_all`.

**Fixed in** — `561bf28` (bare-label smart-paste + code-block template tune)

### BUG-052 · 2026-05-28 — `new bootstrap` smart-paste mis-routes every section when the pasted LLM reply uses blank-line section separators

**Repro**

1. `lamill new bootstrap <domain> --git-url <url> --budget 5.0`
2. At `[2/9] Summary`, paste a full multi-section LLM reply (sections
   2/3/4/5/6/9) where sections are separated by **two consecutive blank
   lines** (some models format their replies this way).

Single-blank-line separation routed correctly — it was specifically ≥2
blank lines *between* sections that triggered the bug.

**Actual (pre-fix)** — `_prompt_multiline` terminated at the first run of
two blank lines, capturing only the Summary block. Smart-paste then saw a
single section → `parse_multisection_paste` returned `None`, and the
remaining buffered lines leaked into the subsequent prompts shifted one
slot (Summary got `2. Summary\n<text>`, Audience got `3. Audience`, ICP
got the Audience content, etc.). Silent content corruption.

**Fix** — `_prompt_multiline` gained a `detect_blob` flag (set on the
first smart-paste-eligible prompt). When the first non-blank line matches
a leading numbered-section header (`_LEADING_SECTION_HEADER_RE`), the
read switches to blob mode: blank lines no longer terminate (they're a
blob's section separators); the capture ends only on EOF (Ctrl-D) or a
run of 3+ blank lines. The whole reply lands in one buffer, so
`parse_multisection_paste` routes every section. Plain prose input (no
leading numbered header) keeps the classic two-blank terminator. The
first-prompt hint now reads "One paragraph → Enter twice. OR paste the
whole multi-section reply → finish with Ctrl-D."

**Where** — `src/portfolio/cli.py` `_prompt_multiline` +
`_collect_operator_inputs`.

**Severity** — `major`.

**Tests** — `tests/test_bootstrap_smart_paste.py`:
`test_prompt_multiline_blob_mode_reads_through_double_blanks`,
`test_prompt_multiline_plain_paragraph_still_ends_on_double_blank`,
`test_collect_smart_paste_double_blank_separators_routes_all`.

**Fixed in** — `c08231d` (new bootstrap smart-paste mis-route + paste-first UX)

### BUG-051 · 2026-05-28 — `new bootstrap` smart-paste positional fallback mis-routes a single section whose content is a numbered list

**Repro** — At `[2/9] Summary`, paste a single section whose body is a
numbered list of ≥4 items preceded by a prose line, e.g. `The site
needs:` then `1. … 2. … 3. … 4. …`.

**Actual (pre-fix)** — `_try_positional_paste` fired (≥4 unique digits
1-9 at line start) and mapped the list items to prompt order
(1→Lovable repo, 2→Summary, 3→Audience, 4→ICP), dropping the preamble and
scattering the list across four slots behind a spurious "Detected a
multi-section paste" banner.

**Fix** — `_try_positional_paste` now requires the paste to *start* with
a numbered block (first non-blank line matches `_HEADER_RE`). A numbered
list embedded after prose no longer trips the fallback; labeled and
genuine positional pastes (which begin with a numbered block) are
unaffected.

**Where** — `src/portfolio/bootstrap_paste.py` `_try_positional_paste`.

**Severity** — `minor`.

**Tests** — `tests/test_bootstrap_smart_paste.py::test_parser_positional_rejects_numbered_list_inside_prose`.

**Fixed in** — `c08231d` (new bootstrap smart-paste mis-route + paste-first UX)

### BUG-050 · 2026-05-28 — `new domain` option 1 row picker rejects full domain names and gives cryptic TLD hint

**Repro**

1. Run `lamill new domain` → shortlist names → run option 7 (decide) → option 1 (pick a row).
2. Type `drdebug.dev` (full domain name) → `'drdebug.dev': expected a row number (e.g. 5 or 5.app)`.
3. Back up and type bare `1` for a row whose `.com` is poisoned → `Row has no recommended TLD (.com poisoned). Use N.tld syntax to override.` — no example of what to type; operator doesn't know which TLDs are valid.

**Severity** — `minor` (UX friction; workaround is to type `1.dev`).

**Fix**

- `_menu_pick` in `cli.py` — added name-lookup fallback: when `parse_pick_input` fails and the input matches `name.tld` or bare `name`, scan `rows` for a matching `row.name` and resolve to the equivalent `N.tld` form. Accepts exact match, then prefix match; ambiguous prefix match surfaces all matches.
- Prompt label updated from `(N or N.tld)` → `(N, N.tld, or name.tld)`.
- `pick_tld is None` error message now shows a concrete example: `— e.g. \`1.dev\` for drdebug.dev` using the first available TLD for that row.

**Fixed in** — `1d9f768` (2026-05-28)

---

### BUG-049 · 2026-05-28 — `fleet seo` results table should order domains alphabetically (not impressions-desc) by default

`fleet seo` sorted its results table by GSC impressions descending — for a mostly-young/zero-impression fleet, that buried most domains in an undifferentiated block and the operator couldn't locate a domain by name.

**Severity** — `minor` (ordering ergonomics).

**Fix** (operator chose the default-change shape)

- `seo_runtime.sort_rows` — added a `"domain"` key (case-insensitive alphabetical) and made it the fall-through default.
- `cli.py:check_seo` (`fleet seo` impl) — `--sort` default flipped `impressions` → `domain`; allow-list + validation message + help text updated. Impressions-desc still available via `--sort impressions` (and `clicks`/`position`/`ctr` unchanged).

**Fixed in** — `d0de306` (2 new tests in `test_seo_runtime.py`: `sort_rows` domain alphabetical + unknown-key falls through to alphabetical)

**Notes**

- `project seo <domain>` is single-domain so ordering is moot there; this is the `fleet seo` table only.

---

### BUG-039 · 2026-05-25 — `project seo` renders pending sitemap re-fetches as `✗ ERROR` (red) when they should be `↷ PENDING` (yellow)

When GSC is mid-refetch (`isPending: true`), the error count is from the PRIOR fetch and may clear on the next download — but `_sitemap_status` checked `errors > 0` before `is_pending`, so the boxchive.com sitemap rendered red `✗ ERROR` and sent the operator chasing a stale error.

**Severity** — `minor`.

**Fix**

`project_seo_diagnostics._sitemap_status` cascade reordered to `pending > error > warn > ok` — `is_pending` now short-circuits to PENDING regardless of the stale error count. The `is_pending` field was already plumbed through `SitemapDetail` + `fetch_sitemap_details` (prior partial work); only the cascade order was wrong. The cli renderer now annotates the stale count on a PENDING row: `N error(s) from prior fetch (clears on next download)`.

**Fixed in** — `d122445` (updated `test_sitemap_status_error_wins` → `_error_wins_when_not_pending`; new `_pending_beats_stale_errors`)

---

### BUG-038 · 2026-05-25 — `project seo` sitemap line renders `"N error(s)  ·  N error(s)"` (duplicate count from two render paths)

The sitemap tail-bits builder appended both `f"{errs} error(s)"` and `error_summary` (which also starts with `"N error(s)"`), so the count rendered twice.

**Severity** — `cosmetic`.

**Fixed in** — `d122445` (doc-drift — the `if errs:` append was already removed before this session; verified 2026-05-28 the cli render path appends only `error_summary` for the error count, no duplicate). No code change in the bundle for this entry.

---

### BUG-025 · 2026-05-20 — v13.B `project seo` GSC diagnostics — 3 rendering/classification issues

Three defects on the v13.B per-project GSC diagnostics surface, surfaced together on a healthy `hybridautopart.com` run.

**Severity** — `minor` (Coverage% misread was the most visible — "0/N indexed" on a healthy site).

**Fix** (per sub-issue)

1. **Coverage misclassified as 0% indexed.** GSC's URL Inspection returns `coverageState` as human text ("Submitted and indexed"), but the renderer + hints key on underscored tokens (`submitted_indexed`). Added `_normalize_coverage_state` mapping the documented GSC strings → canonical keys, applied in `fetch_coverage_details` so the indexed-count, glyph, AND hints all match. Fixed.
2. **`--top N` capped at 10.** The `--top` flag is now plumbed end-to-end (`cli.py:8432` → `build_diagnostics(top_n=)` → `fetch_coverage_details(top_n=)` → `fetch_sitemap_urls(limit=top_n)` + `urls[:top_n]`). Appears resolved since the original report — **verify live** with a real `--top 30` run against a GSC-verified site (depends on URL Inspection daily quota + actual sitemap URL count).
3. **`0y ago` relative-date bug.** `_human_age_from_iso` jumped weeks (<90d) straight to years, so any 90-364 day delta rendered "0y ago" (`secs // (86400*365) == 0`). Added a months branch → `Nmo ago`. Fixed. (The original report guessed "crawled today," but the formatter only emits 0y for the 90-364 day range — the URL was months old, not today.)

**Fixed in** — `d122445` (tests: `_normalize_coverage_state` human-text→canonical + passthrough/edges; `_human_age_from_iso` months branch + no-`0y` regression + year boundary)

---

### BUG-024 · 2026-05-20 — `new bootstrap` prompt layout makes Audience/ICP visually confusable

In the operator's test session, the ICP content got typed into the Audience prompt: the multi-line ICP description rendered immediately after the Audience input with no boundary, so the eye read the ICP description as extra context for the Audience question. Two sections got mis-routed (saved wrong + left the correct slots empty).

**Severity** — `major` (hit on first test session).

**Fix**

`src/portfolio/cli.py:_collect_operator_inputs`:
- Each section prompt now carries an inline `[N/9]` number matching the preflight banner + LLM-template order (`_OPERATOR_SECTION_NUMBERS`: Summary 2, Audience 3, ICP 4, Goals 5, Content strategy 6).
- After a non-empty answer, a `✓ saved as <section>` line prints — the confirmation breaks the visual blend so the next prompt's description can't read as continuation of the prior input.

Combines options 1 (saved-as echo) + 4 (numbering) from the original write-up. Also reinforced by the copy-paste LLM template (`220bbe1`) + smart-paste (`b8b3d40`): when the operator uses the LLM-stage → single-paste flow, the per-prompt typing that triggered this is bypassed entirely.

**Fixed in** — `b02ab6d` (3 new tests in `test_v9b_bootstrap_operator_inputs.py`: prompts carry `[N/9]`, saved-as echo per answered section, no echo for skipped sections)

---

### BUG-023 · 2026-05-20 — `new bootstrap` should generate a copy-paste LLM prompt first

Bootstrap fired the 6 content prompts (Summary / Audience / ICP / Goals / Content strategy / Growth hypothesis) cold — the operator had to compose each freehand or shuttle to ChatGPT manually, one prompt at a time. The original test session showed two sections answered with the *next* section's content because composing in-prompt without context is error-prone.

**Severity** — `major`.

**Fix**

New `_render_llm_prompt_template(domain, topic, ...)` in `cli.py`, printed right after the preflight banner (no-op on `--non-interactive` or when every content section is flag-supplied). Design refinement over the original write-up: the template instructs the LLM to format its reply in the **numbered+labeled** shape (`2. Summary` … `9. Growth hypothesis`) that the smart-paste parser ([[2026-05-25 positional fix]], `b8b3d40`) detects — so the operator pastes the whole reply at the first prompt and every section auto-fills, rather than the original "paste section-by-section" plan. The two fixes now form one LLM-stage → single-paste workflow. Only the 6 LLM-draftable sections are templated (Lovable repo / registered / registrar are omitted).

**Fixed in** — `220bbe1` (6 new tests in `test_bootstrap_prompts_ux.py`: numbered-labeled format, domain+topic interpolation, no-topic placeholder, non-interactive skip, all-content-supplied skip, partial-content prints)

---

### BUG-037 · 2026-05-25 — `new bootstrap` smart-paste misses positional-numbered LLM responses (numbers map to prompt order, not labels)

Operator pastes an LLM response that answers the 9 numbered prompts by reprinting just the digit + content (`2. <summary>` / `3. <audience>` / …) with no header label. Pre-fix, the header-based parser found 0 canonical sections, `len(sections) < 3` returned None, and the whole blob landed in Summary while prompts 3-9 fired empty.

**Severity** — `major`.

**Fixed in** — `b8b3d40` (`portfolio: bugs — paste parser handles positional 2. <answer> LLM responses`). Doc-drift: the fix landed the same day the bug was filed (2026-05-25) but the entry was never moved out of Open bugs. Verified 2026-05-28 against the operator's exact earnlog repro — `bootstrap_paste._try_positional_paste` + `_POSITIONAL_ORDER` (digit→canonical-key) + `_POSITIONAL_MIN_SECTIONS=4` threshold are present and tested (`test_bootstrap_smart_paste.py::test_parser_positional_paste_maps_digits_to_prompt_order` uses the verbatim earnlog paste; 28 paste tests green).

---

### BUG-048 · 2026-05-28 — `new domain` Step 1 brand-collision check (gpt-5-mini) false-negatives same-category niche competitors

**Repro**

```
$ lamill new domain   # topic: "A tool that shows TikTok Shop sellers their
                      #  real per-SKU profit ... subtracting cost."
... shortlist: marginradar, marginready → option 7 (Decide from shortlist)

Step 1/6 — Brand collision check  (gpt-5-mini)
  marginradar    No notable brand match.
  marginready    No notable brand match.
```

`marginready` is an existing product in the operator's exact category (Amazon / e-commerce seller margin tooling). The check returned a clean "No notable brand match" — a false negative on the most dangerous collision class (a direct same-category competitor).

**Actual (pre-fix)**

`assess_brand_collision_via_ai` sent a **topic-agnostic** prompt — `Is "{name}" the name of any well-known company...?` — with two structural flaws: (1) the topic was never passed to Step 1 (only Step 3 extensibility got it), so the model had no category context; (2) the "well-known" framing biased the model to dismiss niche-but-same-vertical competitors, which are exactly the dangerous ones.

**Severity** — `major`. The collision check is a primary due-diligence gate; a false "no match" misleads toward registering a name that collides with a direct competitor (wasted registration + SEO/TM exposure).

**Fix**

`src/portfolio/decide.py`:
- `_AI_COLLISION_PROMPT` reframed: receives a `{topic_block}` (topic + concept anchors) and explicitly instructs the model to weight same/adjacent-category collisions above fame ("a direct competitor in the same vertical is the most dangerous collision even if NOT globally famous").
- New `_collision_topic_block(topic, vocab_terms)` helper — renders the context block; empty string when no topic (degrades to the original category-agnostic prompt for backward compat).
- `assess_brand_collision_via_ai` + `check_brand_collision` gain keyword-only `topic` + `vocab_terms` params.

`src/portfolio/cli.py`:
- `_decide_step1_brand_collision` + its `_menu_decide` caller thread `topic` + `vocab_terms` (Step 3 already had them).

**Fixed in** — `84d8164` (3 new tests in `test_suggest.py`: topic reaches the prompt, no-topic degrades cleanly, `_collision_topic_block` unit)

**Notes**

- Doesn't fully close the niche-recall gap — still AI-only, no live web search (Brave's free tier was dropped 2026-05-08). The deferred decision-aids work ([[project_deferred_decision_aids]] — USPTO/GitHub/social pre-checks) is the path to a live collision backstop if the topic-aware prompt proves insufficient in soak. Topic-awareness is the cheap high-value first step.
- The operator should re-run the marginready decide flow to confirm the model now flags it — the prompt is correct, but model recall of that specific niche brand isn't guaranteed even with category context.

---

### BUG-047 · 2026-05-27 — `fleet fix` auto-toggled `always_use_https` on csinorcal.church (dark sites had no first-class config classification)

**Repro (today's incident)**

```
$ lamill fleet fix --rule CHECK_150 --apply --yes
...
[7/31] ✓ csinorcal.church          1 fix(es)
...
Done: 6 fix(es) applied across 31 project(s)
```

csinorcal.church is documented in global memory as a **dark site** ("internal; ignore its SEO failures"), but the codebase had no first-class concept of dark sites — only narrow `--skip-ga4` help text mentioning it. `_list_fleet_eligible_projects()` had two filters (`ignore_repos`, `to-be-deleted category`); neither caught it. The fleetwide CHECK_150 apply correctly classified it as a failing canonical-redirect site and toggled `always_use_https` on its CF zone.

The write was probably safe (HTTPS-on for an internal site is fine in 99% of cases), but it shouldn't have been auto-applied. The same gap would silently apply other future fleet-fix tier-1 writes to any dark site too.

**Severity** — `minor`. No data loss; reversible via CF dashboard. But the pattern (operator memory mentions a constraint that the code doesn't enforce) is the load-bearing failure shape — would have repeated on the next fleetwide auto-fix.

**Fix**

`src/portfolio/checks/config.py`:
- New `DEFAULT_DARK_SITES = ["csinorcal.church"]` constant.
- `CheckConfig.dark_sites: list[str]` field with that default.
- New `[fleet] dark_sites = [...]` TOML section honored by `load_config`. Mirrors `ignore_repos` semantics: explicit list replaces default; empty list disables; missing section uses default. Values lowercased on load for case-insensitive comparison.

`src/portfolio/cli.py:_list_fleet_eligible_projects()`:
- Third filter alongside `ignore_repos` + delete-category: skip any repo whose name is in `cfg.dark_sites`.

`src/portfolio/cli.py:_run_project_fix_all()` plan banner:
- Surfaces `↷ skipping N dark site(s): <names> (edit [fleet] dark_sites in config.toml to change)` so silent exclusion isn't surprising.

**Fixed in** — `fc415cd` (9 new tests: 7 in `test_config_dark_sites.py` covering loader paths — defaults, missing file, missing section, explicit override, empty disable, lowercasing, factory pattern — plus 2 in `test_v6d_fix_all.py` covering the eligibility filter)

**Notes**

- The csinorcal.church 308 redirect that was applied today (commit `b5na35x0w` runtime, not source) wasn't rolled back — operator can revert from CF dashboard if HTTP-only matters for internal access, otherwise leave it (HTTPS is generally safe even for internal sites).
- Scope of the filter: today's fix only covers `fleet fix`. Other fleet walkers (`fleet check`, `fleet seo`, `fleet focus`) still process dark sites — they're read-only reporters, so the operator can still see dark-site state when they want to. If a future incident surfaces dark sites in read-only output as noise, extend the filter there too.
- This is the same shape as `DEFAULT_IGNORE_REPOS` (portfolio + rankmill self-exclusion) — operator memory describes a constraint, codebase now enforces it via config defaults rather than relying on memory consistency.

---

### BUG-046 · 2026-05-27 — `settings cloudflare check-token` returns ✓ when token lacks Cache Purge / Zone Settings:Edit (only DNS:Edit was probed per zone)

**Repro (pre-fix)**

```
$ lamill settings cloudflare check-token
...
Zones (14 accessible)
  ✓ DNS:Edit   kwizicle.com
  ✓ DNS:Edit   (13 more)
✓ Token has all permissions lamill needs.

$ lamill project fix kwizicle.com --apply
  ✗ CHECK_057  purge call failed: POST purge_cache → HTTP 401: ...
```

The diagnostic reported ✓; CHECK_057's purge_files call immediately 401'd because the token lacked Zone:Cache Purge on that zone. CF returns 401 (not 403) when a token misses a specific zone-scope permission — same shape as a fully-invalid token, which is why `/user/tokens/verify` succeeded.

**Severity** — `major`. The diagnostic exists specifically to prevent mid-pipeline token-scope surprises; a clean ✓ that turns into a 401 mid-fix defeats its purpose. Same shape as the dropaudit.co 2026-05-22 incident that motivated v25.D in the first place.

**Fix (v25.E)**

`src/portfolio/cloudflare.py`:
- New `probe_zone_cache_purge(zone_id)` — POST `/zones/{id}/purge_cache` with `{"files": []}`. 200 or 400 = auth OK + state-neutral; 401/403 = missing.
- New `probe_zone_settings_edit(zone_id)` — PATCH `/zones/{id}/settings/development_mode` with `{"value": "invalid"}`. 400 = auth OK + value rejected; 401/403 = missing. Unexpected 200 raises (defensive: if CF ever normalizes the bogus enum, the probe needs to switch settings before any state risk).
- `ZoneDiag` extended with `has_cache_purge` + `has_zone_settings_edit`.
- `diagnose_token` per-zone loop now calls all three probes; each missing scope appears as its own entry in `missing_zone_permissions`.

`src/portfolio/cli.py`: `settings cloudflare check-token` renderer prints one row per zone with all three marks side-by-side (`✓ DNS:Edit  ✓ Cache Purge  ✓ Zone Settings:Edit`).

**Fixed in** — `50ef776` (16 new tests: 13 in `test_cloudflare_v25e.py` for the two new probes — 200/400/401/403/404/5xx/request-shape paths — plus 3 in `test_v25d_diagnostics.py` covering the kwizicle scenario, zone-settings-missing, and all-three-scopes-missing)

**Notes**

- Zone:Edit (`POST /zones` to create new zones) intentionally NOT probed — it would create a real zone with side effects. The current `new deploy` Step 3 catches that 403 inline with an actionable dashboard link.
- Cost per `check-token` run: now 3 RTTs per zone (was 1). For a 15-zone fleet, ~0.5s additional.
- Same false-confidence shape as CHECK_057's pre-fix purge-as-universal-remedy (also closed 2026-05-27, `27d96ac`). The "diagnostic honesty" framing was real; both halves of it are now shipped.

---

### BUG-045 · 2026-05-27 — CHECK_057 false-fails non-HTML paths served by CF's SPA-fallback handler (originally diagnosed as origin-orphans)

**Repro**

```
$ lamill fleet focus --refresh
  #2  kwizicle.com  🔴 Stale CF edge cache: stale at edge: /sitemap-index.xml (cache=HIT),
      /sitemap-0.xml (cache=HIT) — run 'portfolio project fix <domain> --apply' to purge

$ lamill project fix kwizicle.com --apply
  + CHECK_057  purge stale paths from Cloudflare edge cache
  ✓ CHECK_057  purged 2 path(s)

$ lamill fleet focus --refresh
  #2  kwizicle.com  🔴 Stale CF edge cache: ... (same paths)
```

The fix runs cleanly, reports ✓, then the same stale signal reappears immediately. Loop is indefinite.

**Actual root cause (diagnosed 2026-05-27)**

Not origin orphans — **SPA-fallback misclassification**. kwizicle.com's `wrangler.jsonc` has `not_found_handling: "single-page-application"`, so CF returns the SPA's `index.html` (HTTP 200, `content-type: text/html`) for any unknown path. CHECK_057 trusted status alone:

- `/sitemap-index.xml` HEAD → 200 + `text/html` (NOT XML — SPA fallback).
- `dist/sitemap-index.xml` doesn't exist locally.
- Pre-fix verdict: `(200) AND (not in dist) = stale` → fail.
- Purge clears CF's cached fallback → next request → fallback re-fires → 200 again → re-flagged.

These paths aren't files at all — neither at the edge nor in the origin. The signature is: non-HTML asset suffix (`.xml`, `.txt`, `.json`) served as `text/html`. This shape will trip every Vite/Astro SPA in the fleet, not just kwizicle.com.

**Severity** — `minor`. False-confidence cosmetic: operator runs the fix, sees ✓, then sees the same alert next refresh.

**Fix**

In `check_057_cf_edge_cache_fresh.py`:
- `_probe_one` now captures `content_type` (lowercased, no params).
- New `_is_spa_fallback(row)` helper: returns True iff `path` ends in `.xml`/`.txt`/`.json` AND `content_type` starts with `text/html`.
- `_stale_paths` excludes SPA-fallback rows alongside the existing in-dist / non-200 filters.

Conservative: a missing content-type (older test fixtures, network errors) does NOT trigger the exclusion — falls through to existing verdict logic. The original donready scenario (`/sitemap.xml` actually served as `application/xml` but absent from `dist/`) is still flagged stale.

**Fixed in** — `27d96ac` (3 new tests in `test_check_057_cf_edge_cache_fresh.py`: SPA-fallback kwizicle scenario, donready non-masking regression, `_is_spa_fallback` unit cases)

**Notes**

- The original write-up hypothesized "origin orphans" (the live origin still ships the files from a prior build, so purge is no-op). That root cause is plausible but didn't match the kwizicle.com evidence: HEAD probe showed `content-type: text/html` on the two flagged paths, ruling out a real XML file at the edge. The proposed `_apply_purge` post-purge cache-buster + Tier-2 redeploy fallback weren't shipped — the SPA-fallback discriminator alone clears kwizicle.com.
- True origin-orphan case (paths shipped by old build, content-type still XML) is rare and would still surface correctly under the new logic. If it ever becomes a real fleet signal, ship the post-purge cache-buster from the original write-up.
- Still relevant from the original notes: kwizicle.com is served by a CF Worker, and `wrangler versions upload` asset semantics around orphan deletion are worth verifying separately if a true-origin-orphan case ever appears.
- **Related:** same false-confidence shape as the `check-token` entry directly below — both are diagnostics that return ✓ while the underlying signal persists. The "diagnostic honesty" mini-tier framing from the original notes is still worth bundling.

---

### BUG-044 · 2026-05-27 — `new deploy` fails Step 2 when local origin uses `<domain>` form (e.g. `kwizicle.com`) but slug derivation produces `<short>` form (`kwizicle`)

**Repro**

```
$ lamill new deploy kwizicle.com --yes
v15.I — Deploy kwizicle.com (platform=cf-pages · slug=kwizicle ...)

1. GitHub repo
  ✓ exists, skipping: codervijo/kwizicle (visibility=private; default_branch=master)

2. Git push origin/main
  ✗ git push step failed: origin already points to
    'git@github.com:codervijo/kwizicle.com.git' but expected
    'git@github.com:codervijo/kwizicle.git'. Operator must reconcile
    (e.g. `git remote set-url origin git@github.com:codervijo/kwizicle.git`).
```

**Expected**

`new deploy <domain>` should respect the project's existing `origin` remote naming as the canonical reference for the GH-side of the pipeline. If the local repo already points to `<owner>/<X>` and that repo exists on GitHub, `X` becomes the GH repo target — overriding the TLD-stripped default.

**Actual** (pre-fix)

`bootstrap._project_name(domain)` deterministically returns the TLD-stripped form (`kwizicle.com` → `kwizicle`); the pre-fix pipeline threaded that into Step 1's `ensure_repo` + Step 2's `clone_url` strict-check, hitting the operator's `kwizicle.com.git` origin and raising.

**Severity** — `major`. Blocked operator-initiated re-deploy of any existing repo whose GitHub naming predates lamill's slug convention (a common pre-lamill convention).

**Fix**

Added `read_local_origin()` + `parse_github_remote()` helpers in `gh_repo.py`. In `_deploy_cf_unified` Step 0 (after `gh_owner` resolution), probe the local origin; if it parses as `<gh_owner>/<X>` and `X != slug`, override `gh_repo_target = X` (with a `↷` banner). Step 1 + Step 2 + Step 5's CF Pages source binding all flow through `gh_repo_target`. The CF Pages project name (`slug`) stays as `_project_name(domain)` — CF naming constraints disallow dots — but the GH source binding tracks the operator's actual remote.

**Fixed in** — `ea65347` (slug-mismatch fix; 13 new tests in `test_gh_repo.py`)

**Notes**

- Cleanup of pre-existing orphans (e.g. `codervijo/kwizicle` empty placeholder + the wrong-source CF Pages project it spawned) is out of scope of this fix; operator handles those manually via dashboard. The fix prevents creating new orphans.
- The "fleetwide sweep" command in the original notes is still worth running to confirm no other sites are silently affected:
  `cd ~/work/projects/sites && for d in */; do (cd "$d" && git remote get-url origin 2>/dev/null | grep -oE "codervijo/[^.]+(\.[^.]+)?"); done`

---

### BUG-043 · 2026-05-26 — CHECK_150 fixer post-write verification races CF edge propagation

**Repro**

Run `fix_tier_1.apply(site, dry_run=False, ...)` on a CF-platform domain whose `always_use_https` is currently `off`. The PATCH succeeds; CF persists the setting. The fixer's immediate `HEAD http://<domain>/` probe still returns 200 because CF edges take 5-30s to start serving the new redirect.

Observed during v26.C's first real fleet run (2026-05-26):

```
✗ agesdk.dev             error          set always_use_https → on, but http://agesdk.dev/ still returns 200...
✗ airsucks.com           error          set always_use_https → on, but http://airsucks.com/ still returns 200...
✓ donready.xyz           fixed          set always_use_https → on; http://donready.xyz/ now returns 301
✗ (5 more)               error          (same pattern)
```

7 of 8 CF fixes reported `error` even though the writes had succeeded. A 15-second post-run re-probe confirmed all 8 edges had flipped to 301; the actual fix worked, only the verification step was racing.

**Expected**

Fixer returns `status="fixed"` when the API write succeeds and the edge eventually settles to the expected redirect — even if it takes a few seconds.

**Actual**

Fixer returns `status="error"` with a "still returns 200" message because the single immediate probe ran before propagation completed.

**Where**

`src/portfolio/checks/seo/check_150_apex_canonical_redirect.py:_apply_cf_always_use_https` post-PATCH verification block.

**Severity** — `minor` (false-error cosmetic; the actual fix works; operator can re-probe manually to confirm).

**Notes**

Replaced the single `_http_status(domain)` call with a short backoff poll — up to `_FIX_VERIFY_ATTEMPTS` (5) × `_FIX_VERIFY_INTERVAL_S` (3s) = 15s budget. First 308/301 wins → `status="fixed"`. All probes still 200 → real `status="error"` (genuine conflict). Unreachable → existing `verify manually` path.

Tests updated to monkeypatch `time.sleep` so they don't actually wait; new test `test_fix_cf_apply_post_write_eventually_settles_returns_fixed` proves the backoff works when probes flip mid-window. Suite: 2732 passed.

**Fixed in** — same-commit (2026-05-26; the v26.C polish commit that immediately follows the v26.C ship commit `d0ee313`).


### BUG-035 · 2026-05-22 PM — Step 5.5 false-flags legitimate DNS records as conflicts on re-deploy

**Repro**

    5.5 Purge conflicting DNS records (dropaudit.co)
      ✗ DNS purge denied: DELETE /zones/.../dns_records/... → HTTP 403

(Hit 3 times in a row. Operator had manually deleted the original
4 CF-injected parking records between attempts; the records now
being flagged are NOT parking — they're legitimate Workers-managed
routing DNS that CF created on a prior successful Step 6 Custom
Domain attach.)

**Diagnosis**

`cloudflare.purge_conflicting_root_records()` matches too broadly:

  - type ∈ {A, AAAA, CNAME}
  - name ∈ {<domain>, *.<domain>, www.<domain>}

This was the right pattern for the v15.R original use case (catch
the parking placeholders CF's "Connect a domain" UI injects). But
it ALSO matches legitimate Workers-managed DNS that Step 6 creates
on successful Custom Domain attach. On any re-deploy after Step 6
has succeeded once, Step 5.5 false-positives those records as
conflicts and tries to delete them.

In the operator's case, the legitimate records also can't be
deleted via API (token lacks DNS:Edit on this zone or these
specific managed records); pipeline 403s in a loop.

The "right" detection — checking CF's `meta` field for
`managed_by_apps` / `auto_added` / similar flags — needs verification
against real API responses (DnsRecord dataclass doesn't currently
parse meta). Shipping the safer escape valve first.

**Fixed in** — 2026-05-22 PM: new `--skip-dns-purge` flag on
`lamill new deploy`. When set, Step 5.5 prints a visible
"↷ skipped (--skip-dns-purge) — trusting current DNS records as
legitimate" line and proceeds directly to Step 6. The existing
403 actionable hint now also mentions this flag as an alternative
when the surfaced records look legitimate to the operator.

Smart `meta`-based filtering (skip records flagged as CF-managed)
deserves a follow-up when real CF API response data exists to
design against. Tracked as a future improvement; not blocking
since the escape valve works.

Operator next steps for dropaudit.co specifically:

    uv run lamill new deploy dropaudit.co --yes --skip-dns-purge

Step 5.5 will skip; Step 6's GET-then-PUT idempotency (v15.Q) will
detect any existing Workers Custom Domain attachment and skip
cleanly; if not yet attached, will try to attach and either
succeed (best case) or surface the legitimate Step 6 403 with the
v15.R dashboard URL hint (worst case, operator finishes manually).

Suite stays at 2620/1 skip — change is render + flag-plumbing
only, no new tests added (would need full _deploy_cf_unified
integration test which isn't currently in the suite).

---

### BUG-034 · 2026-05-22 PM — Step 5.5 403 hint doesn't show the actual records that need deletion

**Repro**

    5.5 Purge conflicting DNS records (dropaudit.co)
      ✗ DNS purge denied: DELETE /zones/.../dns_records/... → HTTP 403: ...

      Manual DNS cleanup required:
        1. Open this URL:
           https://dash.cloudflare.com/<acct>/dropaudit.co/dns/records
        2. Delete any A / AAAA / CNAME records matching:
           - dropaudit.co
           - *.dropaudit.co
           - www.dropaudit.co
        3. Re-run lamill new deploy dropaudit.co --yes

Operator hit this 3 times in a row on the same `dropaudit.co`
deploy. The hint is correct but vague — operator has to open the
dashboard, scan ~10 DNS records, mentally filter to A/AAAA/CNAME
on root/wildcard/www, and delete each one. The patterns are
abstract; the actual records (with their content fields showing
what they're pointing at, e.g., parking page IPs) are concrete
and clickable.

**Why the token can't delete**: operator's `lamillio build token`
has `DNS:Edit` on some zones but apparently not on `dropaudit.co`'s
zone. Could be:
  - Zone is on a CF account the token isn't scoped to (different
    from agesdk.dev / disclosur.dev's account).
  - Token's "All zones" scope was actually "Specific zones" with
    an explicit list that didn't include dropaudit.co.
  - CF's permission inheritance for newly-created zones is
    delayed.

**Fixed in** — 2026-05-22 PM: Step 5.5's 403 branch now re-calls
`cloudflare.list_dns_records(zone_id)` (DNS:Read, which still
works) and renders the actual conflicting records in the hint:

      Manual DNS cleanup required:
        1. Open this URL:
           https://dash.cloudflare.com/<acct>/dropaudit.co/dns/records
        2. Delete these 4 record(s):
           • A     dropaudit.co            → 192.0.2.1
           • CNAME *.dropaudit.co          → parking.cloudflare.com
           • A     www.dropaudit.co        → 192.0.2.1
           • AAAA  dropaudit.co            → 2001:db8::1
        3. Re-run lamill new deploy dropaudit.co --yes

Operator sees exactly what to delete + their content fields
(parking-page targets) so they can confirm they're deleting the
right records (vs anything operator-curated that shouldn't be
removed). If LIST also fails (token lacks DNS:Read entirely), the
generic pattern-based hint still renders as a fallback.

Underlying CF permission issue is operator-side (token doesn't
have DNS:Edit on this zone); pipeline can't fix that. The hint
quality is what lamill can improve, and this is it.

No new tests — the change is render-only inside a 403 catch block
that the existing v15.R/22c2c71 tests don't exercise (would need
a full _deploy_cf_unified integration test; current test posture
covers cloudflare.list_dns_records + cloudflare.purge_conflicting_
root_records as unit-level helpers, which still pass). Suite
stays at 2620/1 skip.

---

### BUG-033 · 2026-05-22 PM — v15.S `pnpm-workspace.yaml` format silently broken under pnpm v11.1.3

**Repro**

    root@vijo-Alienware-m15-R7:/usr/src/app# make run proj=dropaudit.co
    (cd dropaudit.co && pnpm install)
    Packages: +399
    ...
    [ERR_PNPM_IGNORED_BUILDS] Ignored build scripts: esbuild@0.25.12, esbuild@0.27.7, sharp@0.34.5
    Run "pnpm approve-builds" to pick which dependencies should be allowed to run scripts.
    make: *** [Makefile:62: run] Error 1

Hit on the first `make run` after fresh bootstrap + translate of
`dropaudit.co`. v15.S was supposed to prevent exactly this — but
its `pnpm-workspace.yaml` content shape is the wrong one for pnpm
v11+.

**Diagnosis**

Inspection of `dropaudit.co/pnpm-workspace.yaml` post-failure:

    allowBuilds:
      esbuild: set this to true or false
      sharp: set this to true or false
    # Generated by lamill v15.S — pre-approved build-script allowlist
    # so `pnpm install` doesn't enter the interactive approve-builds
    # flow on first run. Add packages here if a new dep needs its
    # install scripts to run (rare for Astro+Vite projects).
    onlyBuiltDependencies:
      - esbuild
      - sharp

mtimes:
  - `lamill.toml`           11:23 (bootstrap)
  - `package.json`          11:25 (translate)
  - `pnpm-workspace.yaml`   11:51 (pnpm v11 mutated 26 min later)

Sequence: lamill v15.S wrote the file at 11:25 with our
`onlyBuiltDependencies:` list. Operator ran `make run` at 11:51 →
pnpm v11.1.3's `pnpm install` saw the build scripts in esbuild +
sharp, **didn't recognize our `onlyBuiltDependencies:` field**,
treated the file as "operator hasn't approved any builds," and
INJECTED the `allowBuilds:` placeholder block ABOVE our content.
Now pnpm sees the `allowBuilds:` placeholder strings first, treats
them as "not yet approved," ignores the builds.

Comparison: `disclosur.dev` (operator manually fixed earlier in the
2026-05-22 session) has the actually-working format:

    packages:
      - .
    allowBuilds:
      esbuild: true
      sharp: true

The differences vs v15.S's output:
  1. `packages: [.]` required to declare workspace-root (without
     it pnpm v11 may not honor the file as a config source).
  2. `allowBuilds:` dict-with-booleans is what pnpm v11 reads
     preferentially over `onlyBuiltDependencies:` list.

**Fixed in** — 2026-05-22 PM: `_PNPM_WORKSPACE_CONTENT` in
`stack_translate.py` rewritten to emit the pnpm-v11 format:

    packages:
      - .
    allowBuilds:
      esbuild: true
      sharp: true

`write_pnpm_workspace_yaml()` detection logic extended: in addition
to overwriting pnpm's `set this to true or false` placeholder
stubs, it now also overwrites v15.S-vintage content (recognized
by the `Generated by lamill v15.S` header + absence of
`allowBuilds:`). Operator hand-curated files without the lamill
header are still preserved (no clobbering). 2 new tests:
overwrite-v15s-vintage; preserve-hand-curated-old-format.

Existing sites on the broken format (dropaudit.co et al.) get
healed automatically on next `lamill project translate <domain>`
run. Operator can also delete the file manually + re-run translate.

Suite 2618 → 2620.

---

### BUG-032 · 2026-05-22 PM — `lamill new trends` (no topic) — feature withdrawn after Google API surface dried up

**Repro** (three iterations, three different endpoints):

    ❯ uv run portfolio new trends
    Latest trends fetch failed: pytrends trending_searches failed for region='US': The request failed: Google returned a response with code 404

    ❯ uv run portfolio new trends
    Latest trends fetch failed: pytrends today_searches failed for region='US': The request failed: Google returned a response with code 404

    ❯ uv run portfolio new trends
    Latest trends fetch failed: RSS fetch returned HTTP 404 for region='US': <!doctype html>...

**Diagnosis**

Every no-auth path to Google's daily trending searches is dead:

  - `pytrends.trending_searches(pn=...)` → 404 (`/trends/hottrends/
    visualize/internal/data` deprecated)
  - `pytrends.today_searches(pn=...)` → 404 (`/trends/api/dailytrends`
    also dead or token-gated)
  - `https://trends.google.com/trends/trendingsearches/daily/rss?geo=US`
    → 404 (public RSS feed retired with Google's 2024 trending-
    searches page redesign)

Google's current trending UI at `https://trends.google.com/trending`
uses an undocumented `/_/TrendsUi/data/batchexecute` endpoint with
a proprietary JSON-in-form-encoded RPC format — not consumable
from simple HTTP clients.

**Fixed in** — 2026-05-22 PM, **Option A (drop the feature)**:

Operator chose to revert the no-topic surface after three failed
endpoint attempts. The two viable alternatives — SerpAPI's
`google_trends` engine (Option B, reverses v19.A scope) or a
headless-browser scraper (Option C, heavyweight) — weren't worth
the cost for a "what's trending" discovery surface that the Google
Trends web UI does perfectly well.

Reverted:
  - cli.py `new_trends`: `topic` argument back to required
    (Typer's `...` default); removed the no-topic branch + the
    `_run_latest_trends` / `_render_latest_trends` helpers.
  - gtrends.py: stripped `LatestTrendsPayload`, `fetch_latest_trends`,
    `_fetch_latest_via_rss`, the `_LATEST_REGIONS` allowlist + alias
    map, `latest_*` cache helpers, `latest_payload_age_hours`. Left
    a comment documenting the API state for any future re-evaluation.
  - tests: removed the ~13 latest-trends tests (RSS stubbing
    infrastructure + happy/error/CLI paths). Topic-mode tests
    (the 30 that exercise pytrends + L1 + L3 + typed errors)
    all stay.
  - architecture.md § 12: gtrends.py row reverted to single-mode.

**Kept** — the topic-mode L1 stale-cache + L3 UA rotation +
`GTrendsRateLimitError` typed-error pass from earlier today
(commit `ba1d25b`). Those are real wins that apply to
`lamill new trends <topic>`.

**Resurface conditions**: reopen if (a) Google publishes an
official trending-searches API, OR (b) the operator's workflow
demand justifies the SerpAPI integration cost (~10 calls/month).
Until then, point operators at `https://trends.google.com/trending`
for discovery; this CLI sticks to topic-specific deep-dives.

Total session iterations: 3 endpoint attempts + 1 withdrawal.
Net code change: zero (feature fully reverted). Net knowledge
gained: substantial — captured here for future archeology.

---

### BUG-031 · 2026-05-22 — `lamill new trends <topic>` on HTTP 429 surfaces a cryptic error with no recovery hint

**Repro**

    ❯ uv run portfolio new trends 'nanobanana'
    Trends fetch failed: pytrends fetch failed for 'nanobanana': The request failed: Google returned a response with code 429

**Expected**
Operator-facing message clarifies 429 = transient IP-based rate
limit; suggests wait window (10-30 min); flags that re-running
other topics from same IP won't help.

**Fixed in** — 2026-05-22 PM: gtrends.py `_fetch_from_pytrends`
detects `"429"` or `"Too Many Requests"` in pytrends error message
and raises new `GTrendsRateLimitError(GTrendsError)` subclass with
the actionable hint built in. CLI catches it specifically (yellow,
"Trends fetch rate-limited:" prefix) vs the generic red
GTrendsError. **Plus L1 stale-cache fallback** — fetch_trends
catches GTrendsRateLimitError, looks for ANY cached payload via
new `load_any_cached()` helper (no TTL check), returns it if
present so operator gets data anyway. Renderer surfaces a
yellow "Stale cache fallback — Xh old" warning header in that
case. **Plus L3 UA rotation** — pytrends client gets a randomized
realistic User-Agent (5 modern browser UAs) + Accept-Language
header per call; minor anecdotal help against Google's
rate-limiter. 10 new tests covering all paths. SerpAPI fallback
(L4) intentionally NOT shipped — pinned for later re-litigation
if pytrends becomes chronically unreliable; the v19.A "serp etc
not needed" call stands as long as L1+L3 keep the common cases
working.

---

### BUG-030 · 2026-05-22 — `lamill new trends <topic>` raises `ModuleNotFoundError: No module named 'pytrends'` when running outside the `uv` venv

**Repro**

    portfolio on  main is 📦 v0.1.0 via 🐍 v3.10.12
    ❯ lamill new trends 'ai'
    ...
    ModuleNotFoundError: No module named 'pytrends'

(Operator's `lamill` binary on PATH predates v19.B's pytrends dep;
Python 3.10 install separate from the project's uv venv.)

**Expected**
Typed error with actionable `uv sync` / `pipx reinstall` hint,
not a raw stack trace.

**Fixed in** — 2026-05-22 PM: gtrends.py `_fetch_from_pytrends`
wraps `from pytrends.request import TrendReq` in try/except
ImportError → raises typed GTrendsError with the message:
"pytrends library not installed (...). Run `uv sync` in the
portfolio project root..." CLI's existing `except GTrendsError`
handler at cli.py renders cleanly (red, "Trends fetch failed:"
prefix) and exits 3 — no stack trace reaches the operator.

---

### BUG-022 · 2026-05-20 — tech-debt audit pass

**Expected**
A deliberate pass over the codebase to identify what's worth
cleaning up vs leaving in place, after 22 shipped tiers of rapid
feature work.

**Fixed in** — 2026-05-21: audit done. Major findings landed in
`docs/architecture.md § 11 Tracked refactors`:

  1. **`cli.py` monolith** — 8,782 lines; 4× the next-largest
     module. Proposed split into scope-first modules
     (`cli/project.py`, `cli/fleet.py`, etc.). Trigger: gap between
     feature tiers (post-v23).
  2. **Platform-name enum drift** — three modules with three
     spellings (`cf-pages` vs `cloudflare-pages` etc.); symptom-
     treating translation map added in `project.py` 2026-05-21
     during the bug fix run. Proposed canonical
     `src/portfolio/platforms.py` module.
  3. **v15.K dead-code cleanup confirmed complete** —
     `_deploy_cf_pages_v3c` / `_deploy_cf_workers` /
     `deploy_cf_workers_via_shell` all gone from source. Stale
     comment in `prd.md:546` corrected this commit.

Secondary items from the original wishlist (still valid but lower
priority): cache modules consolidation, render-helpers move,
CHECK_NNN skip-condition decorator, duplicate OpenAI HTTP code,
test-fixture repetition, `stack_translate.py` prompt extraction.
Pick up between feature tiers; none block functionality. Per
`[[feedback_no_self_conformance]]`, use pytest / git hooks for any
tech-debt enforcement on portfolio itself — never new `CHECK_NNN`.

---

### BUG-021 · 2026-05-20 — Deploy Step 5.5 (DNS purge) continues on auth failure instead of pausing for manual cleanup

**Repro**
`uv run lamill new deploy <domain> --yes` on a second-attempt deploy
where CF created parking DNS records that conflict with the target
custom-domain attach, when the operator's token lacks DNS:Edit on
the affected zone.

**Expected**
On `HTTP 403` from `purge_conflicting_root_records`, stop and
surface dashboard URL + records to remove (same gate pattern as
zone-create / Pages-project-create / Workers-custom-domain-attach).

**Actual**
Step 5.5 logged a soft `↷ DNS purge probe failed (continuing): ...`
and proceeded. Step 6 attach then failed (or live probe returned
parking page), leaving operator confused about which step actually
broke. Pre-fix output:

    5.5 Purge conflicting DNS records (disclosur.dev)
      ↷ DNS purge probe failed (continuing): DELETE /zones/.../dns_records/...
      → HTTP 403: {"success":false,"errors":[{"code":10000,...

**Fixed in** — 2026-05-21: `cli.py:6263-6294` Step 5.5 catch now
checks for `"HTTP 403"` in the `CloudflareAPIError` message. On
match, prints red ✗ + bold-yellow "Manual DNS cleanup required:"
block with exact dashboard URL
(`https://dash.cloudflare.com/{cf_account}/{domain}/dns/records`)
and the 3 record patterns to delete (`<domain>`, `*.<domain>`,
`www.<domain>`). Exits 7 (matches Step 6's exit-9 family). Non-403
errors (transient network / 5xx) keep soft-warn behavior — Step 6's
GET-then-PUT idempotency (v15.Q) catches stale records on retry.
No unit test added — `_deploy_cf_unified` orchestration is not
unit-testable today (would need full pipeline mock); fix mirrors
the well-tested Step 6 403 pattern.

---

### BUG-020 · 2026-05-20 — `project check` deploy summary line shows wrong platform for cf-workers sites

**Repro**

    uv run lamill project check airsucks.com

**Expected**
`Deployment: cloudflare-workers` (the platform declared in
`lamill.toml [deploy].platform`).

**Actual**
`Deployment: cloudflare-pages` — `detect_platform()` matched the
`("cloudflare-pages", "wrangler.jsonc")` marker entry and didn't
consult lamill.toml. Marker map predates CFW becoming its own
deploy surface; CFW projects still carry `wrangler.jsonc` for local
`wrangler dev`.

**Fixed in** — 2026-05-21: `project.detect_platform()` now reads
`lamill.toml [deploy].platform` first via `lamill_toml.load()`. New
`_LAMILL_PLATFORM_TO_DETECT` map translates `cf-workers` →
`cloudflare-workers`, `cf-pages` → `cloudflare-pages`, etc.
Evidence trail surfaces `lamill.toml:[deploy].platform` so operators
can see which signal won. ParseError → silent fall-through to
existing marker-based detection (no crash on malformed declarations).
`platform = "none"` also falls through (operator hasn't declared,
markers are still the best guess). 8 new tests in
`tests/test_project_detect_platform.py` (cf-workers beats marker,
cf-pages, vercel, netlify, hostgator-with-hosting, no-file
fallthrough, malformed-toml fallthrough, none-falls-through). Suite
2507 → 2515.

---

### BUG-009 · 2026-05-19 — HG-extra `disk N MB` is account-level total, looks per-domain

**Repro**
    lamill fleet hosting --refresh

**Expected**
Either rename to make the account-level scope clear, or move the
disk info to a footer block ("HG accounts: gator3164 500MB · ...")
so it isn't duplicated per row.

**Actual**
Every HG row from the same account showed the same disk number
(e.g., `disk 4959MB` on all 5 sites under `gator4216`). Operator
reading the table saw "every site uses 4959MB" — misleading; that's
the SHARED account quota, not per-domain usage.

**Fixed in** — 2026-05-21: chose Option 2 (footer aggregation).
Removed `disk N MB` from per-row HG-extra; added new
`_hg_accounts_disk_summary(rows)` helper that aggregates
`disk_used_mb` by `hg_account_id` and emits a single footer line:
`HG accounts: gator3164 500MB · gator4216 4959MB` (sorted by
account name). Suppressed when no HG row has disk data. Updated
`test_fleet_hosting_shows_hg_extra_column_when_hg_row_present` +
added 2 new tests (footer aggregates across multiple accounts;
footer absent without HG disk data). Suite 2505 → 2507.

---

### BUG-002 · 2026-05-18 — `domain suggest` menu has letter-keyed option `s` between numbered 7 and 8

**Repro**
    uv run lamill domain suggest <topic>
    # interactive menu renders after first grid

**Expected**
Every menu option keyed by a number (plus `q` for quit). Reads
top-to-bottom as a single numeric sequence — no interleaved letters.

**Actual**
Option `s` ("Show marked names as full grid") was registered in
`MENU_ITEMS` between numbered items 7 and 8, rendering as a
visually out-of-place letter row.

**Fixed in** — 2026-05-21: renumbered `MENU_ITEMS` to pure numeric.
`s` → `8`, `8` (TLD ref) → `9`, `9` (Rerun fresh) → `10`. Updated
dispatch chain at `cli.py:3040-3052`, `_render_menu` count-suffix
check (`("6", "s")` → `("6", "8")`), and 5 test assertions across
`tests/test_suggest.py` + `tests/test_suggest_show_marked.py`. Suite
stays at 2505 / 1 skip.

---

### BUG-019 · 2026-05-20 — Bootstrap's `package.json` template ships deprecated pnpm field

**Repro**

After `lamill new bootstrap <newdomain> --git-url <url>` (or any
bootstrap that emits the standard Astro+Vite template), running
`make deps` (or `pnpm install`) inside the sites Docker container
prints:

    [WARN] The "pnpm" field in package.json is no longer read by
    pnpm. The following keys were ignored: "pnpm.onlyBuiltDependencies".
    See https://pnpm.io/settings for the new home of each setting.

**Expected**

No deprecation warning. The bootstrap template's `package.json`
either drops the `pnpm.onlyBuiltDependencies` field entirely or
moves the equivalent setting to its new pnpm-9+ home (probably
`.npmrc` or a top-level `onlyBuiltDependencies` field — needs
checking against current pnpm docs).

**Actual**

Bootstrap-generated `package.json` includes:

```json
{
  "pnpm": {
    "onlyBuiltDependencies": ["..."]
  }
}
```

The field is silently ignored by pnpm 9+. Operator sees the noise
every build.

**Where (guess)**

`src/portfolio/bootstrap.py` — the `ASTRO_FILES` / `VITE_FILES`
template emitters. Search for `onlyBuiltDependencies` in the
package.json string templates. Either remove the `pnpm` block
entirely OR figure out the new equivalent and emit that.

**Severity** — `cosmetic`

Warning noise only; doesn't break the build. But every operator
build for every site prints it, so it's worth fixing for hygiene.

**Notes**

Surfaced 2026-05-20 by operator during a second-domain bootstrap
session after v15.M shipped. Likely related: pnpm 9 → 10 → 11
transition has been deprecating/relocating various
`package.json` pnpm.* fields over the past year. v15.S candidate.

**Fixed in** — verified clean 2026-05-21: `_astro_package_json()` at `bootstrap.py:739-764` carries no `pnpm` field; `_vite_package_json()` likewise. `git log -S "onlyBuiltDependencies" -- src/portfolio/bootstrap.py` returns empty — the template never literally emitted it. The deprecation warning the operator saw was pnpm injecting + complaining post-install; resolved by v15.S's `write_pnpm_workspace_yaml()` which puts the allowlist in the new pnpm v11 location (`pnpm-workspace.yaml`).

---

### BUG-018 · 2026-05-20 — All `new` commands leave residue when they fail mid-flight

**Repro**

    lamill new bootstrap agesdk.dev

Operator pasted the multi-section LLM response; smart-paste fired
correctly; the v15.H stack-translation step started; Claude
subprocess hit the `$0.50` budget cap mid-translation
(`error_max_budget_usd` after 22 turns / $0.524). bootstrap raised
`StackTranslationError` and exited. State after:

    sites/agesdk.dev/
    └── genai/              ← the cloned TanStack source

No project scaffolding, no commit, no portfolio.json update — but
the `genai/` clone is sitting there waiting for the operator to
either re-run (which fails because `--git-url` won't clobber an
existing dir) or manually delete it.

**Expected**

Every `new` command (`bootstrap`, `deploy`, future) implements
**transactional rollback**: when any step after the project-dir
creation fails, clean up everything the command wrote so the
operator can re-run from clean state.

For `new bootstrap`:
  - On `BootstrapError` / `StackTranslationError` / KeyboardInterrupt
    raised after `project_dir.mkdir(parents=True)`, remove
    `project_dir` entirely.
  - Pre-existing dirs (operator had something there) detect at
    pre-flight + refuse — already protected today.
  - Smart-paste extras (registrar/registered/growth) that landed in
    `portfolio.json` should also roll back if scaffolding fails
    later in the same run. Cleanest: defer `portfolio.json` write
    until AFTER scaffolding completes successfully.

For `new deploy`:
  - On failure mid-pipeline, the GH repo, CF zone, CF Pages project,
    NS update are NOT trivially reversible (external SaaS state).
    Don't try to delete them — the v15.I pipeline is already
    idempotent so re-running picks up where it left off. Surface
    the partial-state summary on exit.

**Actual**

`new bootstrap`'s failure-path doesn't roll back. Operator must
manually `rm -rf` `sites/<domain>/` to retry. The `genai/` subdir
is the most common residue because translation happens after the
clone step but before the scaffolding step.

**Where (guess)**

`src/portfolio/bootstrap.py` `bootstrap()` function — wrap the
post-`project_dir.mkdir` body in a try/except that on any
exception (other than `BootstrapError("already exists")`):

  1. Logs the failure stage to stderr.
  2. Runs `shutil.rmtree(project_dir, ignore_errors=True)`.
  3. Re-raises.

**Severity** — `major`

Operator's first real-world `--git-url` run hit this. Manual
cleanup is annoying + the failure mode is hidden ("why won't
bootstrap work? oh, there's a `genai/` dir lying around from
yesterday").

**Notes**

Surfaced 2026-05-20 by operator after v15.H + smart-paste shipped.
Pairs with a related concern: the `--budget-usd 0.50` default for
v15.H translations is too low for real-world TanStack→Astro
translations (operator's `agesdk.dev` exceeded $0.524 after 22
turns). Bump default to `2.00` or `5.00` USD, OR add a `--budget`
flag to `new bootstrap` so the operator can override per-run.

Also worth: `genai/node_modules/` is Docker-owned (root-owned from
the host's perspective) and `shutil.rmtree` won't be able to remove
it without `sudo`. Rollback for `genai/` may need to either skip
`node_modules/` (best-effort cleanup) or shell out to a Docker
exec that owns those files.

Tier candidate: v15.K (after wrap) or fold into v17.

**Fixed in** — `3fc0800` (v15.K — resilience pass). `bootstrap()` wraps the post-`project_dir.mkdir` body in try/except; `_rollback_project_dir()` at `bootstrap.py:1645` runs `shutil.rmtree(project_dir, ignore_errors=True)` on any exception and re-raises. Pre-existing dirs detected at pre-flight (raise `BootstrapError("already exists")`) fire BEFORE the dir-tracker flips so they don't trigger rollback. PermissionError fallback for Docker-owned `genai/node_modules/` retries with `ignore_errors=True` and warns the operator with a Docker-cleanup hint.

---

### BUG-017 · 2026-05-20 — `new bootstrap` doesn't prompt for Lovable's GitHub repo URL

**Repro**

    lamill new bootstrap agesdk.dev

Operator's workflow is typically: design the UI in Lovable.dev →
Lovable exports a GitHub repo → clone-and-scaffold that repo as a
new sites/<domain>/ project. Bootstrap already supports this via
the `--git-url <repo-url>` flag (which `git clone`s the URL into
`sites/<domain>/genai/` and runs the `--from-genai` path), but the
interactive flow doesn't ask for it.

**Expected**

Bootstrap interactive flow should ask:

```
Lovable GitHub repo URL (or Enter to skip and scaffold blank):
  >: https://github.com/user/agesdk-dev-ui
```

When provided, bootstrap follows the existing `--git-url` path
(clones into `genai/`, applies CF Pages safety fixes, etc.). When
empty, falls through to the standard blank-scaffold template.

Add as the FIRST prompt (before the AI_AGENTS sections) so the
operator's UI work is already in place before they fill in the
docs that should reference it.

**Actual**

Only the 8 prompts listed above (Summary / Audience / ICP / Goals /
Content strategy / Registered / Registrar / Growth hypothesis).
The `--git-url` flag is documented in `--help` but never
surfaces interactively.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` — add a
9th prompt at the top of the interactive flow (before the
v9.B operator-input sections kick in). Prompt accepts:
  - Empty (Enter) → skip → blank scaffold
  - `https://github.com/...` URL → set `git_url` arg → follow
    the `--from-genai` path
  - Optionally validate URL shape (`re.match(r'^https?://')`).

**Severity** — `major`

Operator's most common bootstrap flow uses Lovable; missing this
prompt forces them to remember the `--git-url` flag or run
bootstrap twice.

**Notes**

Surfaced 2026-05-20 by operator. Pairs with the pre-flight
question listing bug (the upfront list needs to include this new
prompt, becoming 9 questions total). Also adjacent to the multi-
paragraph paste bug (a URL is single-line so isn't hit by the
overflow issue, but the same prompt helper refactor could
benefit).

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). `_resolve_git_url()` helper at `cli.py:3744` prompts FIRST (before any AI_AGENTS section), validates `^https?://` or `^git@`, retries up to 3 times, then warn-skips. Empty input falls through to the standard blank-scaffold template. Skipped when `--git-url <url>` passed explicitly or `--non-interactive` set.

---

### BUG-016 · 2026-05-20 — `new bootstrap` doesn't list all prompts upfront

**Repro**

    lamill new bootstrap agesdk.dev

The CLI starts asking questions one-by-one (Lovable-repo-URL →
Summary → Audience → ICP → Goals → Content strategy → registered?
→ registrar → growth hypothesis = 9 prompts total once the Lovable
prompt lands per the bug above) with no advance notice.

**Expected**

Print a single up-front banner before any prompt fires, listing all
8 questions that will be asked + a hint that any of them can be
`Enter`-skipped (and the `--non-interactive` / `--<section>` flag
escape hatches). Operator can either prep answers or hit Enter for
defaults.

**Actual**

Operator gets ambushed prompt-by-prompt with no idea how many more
are coming or what they cover.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` — between the
`--force` validation step and the first prompt (likely the
`_resolve_inventory_inputs()` / `_collect_operator_inputs()` call
or wherever the orchestrator's interactive phase begins). Print a
formatted table or bulleted list of the 8 upcoming questions before
firing the first prompt.

**Severity** — `minor`

**Notes**

Surfaced 2026-05-20 by operator. Pairs with the input-handling
bugs logged below — knowing what's coming helps the operator
prepare paragraph-length answers in advance.

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). `_render_bootstrap_preflight()` at `cli.py:3790` prints a 9-question banner before the first prompt. Lists each section + length hint + skip-flag. Only fires when at least one prompt would fire (suppressed under `--non-interactive` or when every per-section flag is supplied).

---

### BUG-015 · 2026-05-20 — `new bootstrap` prompt input overflow (multi-paragraph paste leaks to shell)

**Repro**

Run `lamill new bootstrap <domain>`. At the Growth Hypothesis prompt
(or any other paragraph-style prompt), paste multi-paragraph text
that contains literal newlines (e.g., the operator's growth-
hypothesis text from the 2026-05-20 session containing 4
paragraphs separated by blank lines).

**Expected**

The full multi-paragraph paste should be captured as one input
field for that prompt — operator's growth hypothesis should land
verbatim into `docs/growth.md` regardless of how many newlines
it contains.

**Actual**

`typer.prompt(...)` accepts only the first line of the paste; the
remaining paragraphs leak out of the prompt and the shell tries
to execute them as commands:

```
The buyer is a developer or a CTO at a small team. They got a legal email…
Command 'The' not found, did you mean:
  command 'the' from deb the (3.3~rc1-3build1)
…
TAM is not the pitch. There are ~4M apps…
TAM: command not found
```

**Where (guess)**

Default `typer.prompt` / Click's `click.prompt` underlying impl
reads until the first newline. For paragraph-style inputs (growth
hypothesis, ICP, content strategy), we need a multiline editor
or a delimiter-based capture. Three approaches:

  1. **End-with-blank-line:** read lines until two consecutive
     blank lines appear (operator types text, hits Enter twice
     to finish).
  2. **`$EDITOR` invocation:** drop the operator into `vi`/`nano`
     with the prompt as a comment header; capture the buffer on
     save+exit. Heavier, but handles arbitrary length.
  3. **Click's `prompt(default="", show_default=False)` already
     supports `confirmation_prompt`** but not multiline. Custom
     multiline-prompt helper is the cleanest.

`_collect_operator_inputs()` / `_collect_growth_hypothesis()` in
`src/portfolio/cli.py` (or wherever those functions live) needs
the multiline helper.

**Severity** — `major`

**Notes**

Operator's pasted text didn't make it into the project, AND the
shell tried to execute each leaked paragraph as a command. The
bootstrap completed but with empty growth.md / partial AI_AGENTS
sections. Workaround until fixed: pass content via per-section
flags (`--summary "..."` / `--growth-hypothesis "..."`).

**Fixed in** — `ada334c` (bootstrap UX — 4 bugs from 2026-05-20). New `_prompt_multiline()` at `cli.py:3690` reads stdin until two consecutive blank lines OR EOF (Ctrl-D); wired into the four paragraph-style prompts (Summary, ICP, Content strategy, Growth hypothesis). Single-line prompts (Audience, Goals, Y/n Registered) stay on `typer.prompt`. Hint text flags "(hit Enter twice when done, or Ctrl-D)". Sister commit `2bda2b8` adds smart multi-section paste detection that previews the matches and auto-fills remaining prompts from one paste.

---

### BUG-014 · 2026-05-20 — `new bootstrap` accepts unregistered/typo'd domains silently

**Repro**

    lamill new bootstrap ageskd.dev

Operator ran the above (typo for `agesdk.dev`). Operator owns
`agesdk.dev` at Porkbun (registered 2026-05-17; appears in
`data/domains/porkbun.csv` post `fleet sync --refresh`).

**Expected**

Bootstrap should at least *warn* before scaffolding a domain that's
nowhere in the owned-domains inventory — `data/portfolio.json` or
`data/domains/*.csv`. Either reject outright (default) or require
`--force` to proceed.

**Actual**

Silently scaffolded `~/work/projects/sites/ageskd.dev/` (typo'd dir)
+ appended a `registrar=porkbun, status=Active` row to
`data/portfolio.json` for a domain the operator doesn't actually own.

**Where (guess)**

`src/portfolio/cli.py @new_app.command("bootstrap")` + the bootstrap
orchestrator (likely `src/portfolio/bootstrap.py`). The pre-bootstrap
"Is the domain registered? [Y/n]:" prompt accepted Enter (default Y)
without any inventory cross-check. Add a validation step before that
prompt.

**Severity** — `major`

Causes real cleanup work + pollutes portfolio.json. Default `minor`
is wrong here.

**Notes**

Surfaced 2026-05-20 by operator. Sister bug to consider: registrar
prompt accepts free-text without validating against registrars
actually present in `data/domains/`.

**Fixed in** — `738d14c` (v16.B/C/D — bootstrap typo fix folded in). `validate_owned_domain()` pre-flight at `cli.py:3542` exits 2 with "Did you mean: ..." hint unless `--force` is passed. Sister fix (`ada334c` registrar prompt) restricts the registrar field to `porkbun` / `godaddy` / `namecheap` / `other`.

---

### BUG-008 · 2026-05-19 — `fleet hosting` table has no summary footer

**Repro**
    lamill fleet hosting --refresh

**Expected**
Footer beneath the table showing per-provider row counts +
skipped-provider count.

**Actual**
Table rendered, then only the per-skipped-provider lines below
it. No row-count footer; no provider breakdown.

**Fixed in** — v11.I commit (see git log). Renderer now prints a
one-line summary via `hosting.hosting_footer_summary()` right
under the table:

    N rows · M cloudflare-workers · L vercel · K cloudflare-pages
    · J hostgator (X skipped, Y conflicts)

Zero counts surface — they're load-bearing for diagnostics
(silent walkers no longer hide). Skipped + conflict tallies only
appear when non-zero.

---

### BUG-007 · 2026-05-19 — `lamill fleet hosting --provider=X` with 0 matches says only "No hosting rows."

**Repro**
    lamill fleet hosting --provider=cloudflare-pages --refresh

**Expected**
When `--provider` filters every row out, the message should
distinguish "walker returned nothing" from "filtered out".

**Actual**
Always said "No hosting rows." regardless of which case applied.

**Fixed in** — v11.I commit. Renderer now distinguishes the two
cases. When `--provider` filters away non-empty pre-filter rows:

    No `cloudflare-pages` rows. (Filtered from 11 total. Drop the
    --provider flag to see all.)
      Available: 11 rows · 6 cloudflare-workers · 5 vercel ·
      0 cloudflare-pages · 0 hostgator

When walker genuinely returned 0 rows, message stays
"No hosting rows." (no filter to blame).

---

### BUG-006 · 2026-05-19 — `HG-extra` column always rendered, even when no HG rows

**Repro**
    lamill fleet hosting --refresh  (with 0 HG rows)

**Expected**
Hide the column when no row would populate it.

**Actual**
Empty `HG-extra` cell rendered for every Vercel / CF row.

**Fixed in** — v11.I commit. Renderer adds the HG-extra column
only when `any(r.provider == "hostgator" for r in rows)`. Plus
a status-emoji column at the left (✓ recent / ⚠ stale / 💤
dormant / ✗ runaway / 🤐 conflict / — unowned per resolution
11.C). 8 new CLI tests cover the column conditional + emoji
priority cascade.

---

### BUG-001 · 2026-05-18 — `test_serp_fetch.py` not isolated from real `data/serp/_quota.json`

**Repro**
    # With data/serp/_quota.json at queries_used == limit (250/250):
    uv run pytest tests/test_serp_fetch.py -q

**Expected**
All `test_serp_fetch.py` tests pass regardless of the real
quota counter state. Tests should monkeypatch the quota path to
`tmp_path` (mirroring `test_settings_serpapi_cli.py`'s
`_patch_quota_path` fixture pattern).

**Actual**
18 of 21 tests fail with
`portfolio.serpapi_quota.QuotaExhausted: SerpAPI free-tier quota
exhausted for this UTC month.` The failure is at
`src/portfolio/serp_fetch.py:56` calling the production
`is_quota_available()` — confirming the tests hit the real
`data/serp/_quota.json` rather than a mocked one. Triggered
today when the operator's actual SerpAPI quota hit 250/250 mid-
session; previously masked because the counter was at 127/250
and the gate was open.

**Where (guess)**
`tests/test_serp_fetch.py` is missing a `monkeypatch.setattr(
serpapi_quota, "QUOTA_PATH", tmp_path / "_quota.json")` fixture
like the one in `tests/test_settings_serpapi_cli.py:18-20`.
Probably one fixture at the top + per-test inclusion fixes all 18.

**Severity**
major — breaks the test suite when production quota is full.

**Fixed in** — `62376f8` (test — isolate test_serp_fetch from
real quota ledger). Added an `autouse=True` fixture mirroring
the `_patch_quota_path` pattern; full suite back to green.
