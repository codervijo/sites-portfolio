# bugs.md — sites/portfolio/

Bug journal for `portfolio` / `lamill`. Operator-driven intake;
Claude-maintained entries.

## Workflow

1. **Operator drops a brief report in chat** — a sentence or two, no
   structure required. Examples: "found a bug: X command shows N
   but Y shows M", "this thing is slow", "the help text for `foo`
   is wrong."
2. **Claude writes up the structured entry here.** Investigates
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

One bug per dated H3 entry. Heading:

```
### YYYY-MM-DD — <one-line headline>
```

Add a sequence suffix on same-day collisions:
`### 2026-05-18 — second-bug` / `### 2026-05-18 — third-bug`.

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


### 2026-05-25 — `project seo` renders pending sitemap re-fetches as `✗ ERROR` (red) when they should be `↷ PENDING` (yellow)

**Repro**

Submit a sitemap to GSC; before Google finishes processing the new fetch (`isPending: true`, no `lastDownloaded` timestamp yet), run:

```
$ lamill project seo boxchive.com --refresh
...
  GSC diagnostics
    📋 Sitemaps (1 submitted)
      ✗ ERROR    https://boxchive.com/sitemap.xml 1 error(s)
```

The raw GSC Sitemaps API response shows:

```json
{
  "path": "https://boxchive.com/sitemap.xml",
  "lastSubmitted": "2026-05-26T00:19:14.441Z",
  "isPending": true,
  "isSitemapsIndex": false,
  "warnings": "0",
  "errors": "1"
}
```

**Expected**

When `isPending: true`, lamill renders a distinct in-progress status (e.g., `↷ PENDING` yellow) and notes that the error count is from a previous fetch:

```
      ↷ PENDING  https://boxchive.com/sitemap.xml submitted 1h ago · errors (1) from prior fetch, will update on next download
```

**Actual**

Renders `✗ ERROR` red — operator reads it as "your sitemap is broken right now," which prompts wasted investigation. The actual situation is "Google's still processing; the error count is stale and may drop to 0 when the next fetch completes."

**Where (guess)**

`src/portfolio/project_seo_diagnostics.py:_sitemap_status()` cascade. Currently it's `error > warn > pending > ok` — but with `errors > 0 AND isPending: true`, the operator's mental model is closer to `pending > error` (the pending state invalidates the trust in the error count). Reorder so `is_pending=True` short-circuits to `pending` regardless of stale error count, OR introduce a new `pending_with_stale_errors` state and render it distinctly.

Also need to pass `isPending` through the SitemapDetail dataclass — current shape captures errors/warnings but discards `isPending`. Adjust `fetch_sitemap_details()` to set `is_pending`, and propagate to the renderer.

**Severity** — `minor`. Operator can read past it once they know the pattern, but the misclassification cost real investigation time on boxchive.com 2026-05-25 (operator had to ask "what is the sitemap parse error?" and we had to query the raw API to discover `isPending: true` was the actual story).

**Notes**

- Closely related: GSC's Sitemaps API doesn't include the textual error reason in the response — even when `isPending` is false, the operator can't see *what* the error was without going to the dashboard. Separate diagnostic gap (could fold into the same fix: when errors > 0 AND not pending, surface "open GSC → Sitemaps → click for textual reason"; today that hint is implicit via the generic `💡 Hints` text).
- This bug + the `lamill project sitemap resubmit <domain>` feature request below + the existing 2026-05-25 dup-rendering bug below are three improvements to the same diagnostic surface — could bundle as a single small phase if/when they're addressed together.


### 2026-05-25 — feature request: `lamill project sitemap resubmit <domain>` verb

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


### 2026-05-25 — `project seo` sitemap line renders `"N error(s)  ·  N error(s)"` (duplicate count from two render paths)

**Repro**

```
$ lamill project seo boxchive.com --refresh
...
  GSC diagnostics
    Property: sc-domain:boxchive.com
    📋 Sitemaps (1 submitted)
      ✗ ERROR    https://boxchive.com/sitemap.xml 1 error(s)  ·  1 error(s)
```

**Expected**

The error count appears once in the tail-bits, e.g.:

```
      ✗ ERROR    https://boxchive.com/sitemap.xml 1 error(s)
```

Or, when the API returns enough detail, the more informative `error_summary` form:

```
      ✗ ERROR    https://boxchive.com/sitemap.xml 1 error(s) across 1 URL(s)
```

But never both.

**Actual**

`"1 error(s)  ·  1 error(s)"` — the count is rendered twice, separated by ` · `.

**Where**

`src/portfolio/cli.py:5500-5507` (the `📋 Sitemaps` per-row tail-bits builder). The current code unconditionally appends two strings that both convey the error count:

```python
if errs:
    tail_bits.append(f"{errs} error(s)")        # ← first append
if warns:
    tail_bits.append(f"{warns} warning(s)")
if last_dl:
    tail_bits.append(f"fetched {_human_age_from_iso(last_dl)}")
if summary:
    tail_bits.append(summary)                   # ← second append (same text)
```

`summary` comes from `project_seo_diagnostics._summarize_error()`, which returns either `"N error(s)"` (when GSC didn't include `contents`) or `"N error(s) across M URL(s)"` (when it did). In both branches, the text starts with the same `"N error(s)"` as the first append → visible duplication.

**Severity** — `cosmetic`. Operator can read past it; no functional impact on the diagnostic decision.

**Notes**

- Fix: remove the `if errs:` branch (lines 5500-5501). `error_summary` already conveys the count more informatively — preserves the "across M URL(s)" variant when GSC provides it.
- The warnings branch (`if warns:`) stays — there's no `_summarize_warning()` counterpart.
- Separate-but-adjacent gap (NOT this bug — log later if it bites): the GSC Sitemaps list API doesn't include the textual error reason ("Couldn't fetch", "Parse error", etc.). The diagnostic could call URL Inspection on the sitemap URL to surface the actual cause; today it just says "N error(s)" with a generic hint. Feature, not bug.
- Real boxchive.com sitemap.xml is valid (manually `curl`-checked 2026-05-25 — 200, valid XML, single URL). The GSC error is likely a stale snapshot from before the deploy completed; resubmitting the sitemap in GSC should clear it. Not in scope of this bug entry.


### 2026-05-25 — fleetwide canonical-redirect audit (v26.A scoping baseline) — 29 of 35 probed sites non-conforming

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


### 2026-05-25 — homeloom.app apex→www redirect is 307 (temporary), blocks Google indexation; fleetwide canonical-redirect standard needed

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


### 2026-05-25 — `new bootstrap` smart-paste misses positional-numbered LLM responses (numbers map to prompt order, not labels)

**Repro**

At the Summary prompt of `lamill new bootstrap <domain> --git-url <url> --budget 5.0`, paste an LLM response where each section is numbered to match the 9-prompt order *without* a header label — the answer follows the number directly:

    2. Earnlog is a mobile-first earnings intelligence platform for California rideshare and delivery drivers navigating the new collective bargaining rights created by AB 1340. ...

    3. Full-time and part-time rideshare and delivery drivers in California ...

    4. A full-time Uber or Lyft driver in California doing 35+ hours per week ...
    ... (sections 5–9 follow the same pattern)

(The prompt template that produces this shape is the operator's own LLM-staging prompt — it answers the 9 numbered prompts shown in the bootstrap intro by re-printing the digit before each answer.)

**Expected**

Smart-paste detects the multi-section paste and offers to auto-fill all remaining prompts (same UX as the labeled `2. Summary\n<content>` form): preview banner appears, operator hits Enter, prompts 3-9 skip.

**Actual**

Smart-paste does NOT fire. The entire paste lands in the Summary field and prompts 3-9 fire empty. Operator session for earnlog.xyz showed prompt 3 (Audience) re-prompting after the paste:

    Paragraph prompts (1, 2, 4, 6, 9): finish with Enter twice or Ctrl-D.
    2. Earnlog is a mobile-first ...
    ... (rest of paste consumed as Summary)

      Audience — one sentence: who this is for (broad demographic)
      >:

**Where (guess)**

`src/portfolio/bootstrap_paste.py:_HEADER_RE` + `_match_header()`. The header regex captures the entire line after `\d+\. ` as the header text. When the operator omits the label (because the number alone references the prompt order), `_match_header()` falls through to `None` and the section is skipped. With all 8 sections (#2–9) skipped, `len(sections) < 3` returns None and the paste is treated as single-section.

**Severity** — `major` (a primary smart-paste UX path silently regresses depending on how the operator's LLM formats the answer; the operator gets re-prompted for every section after pasting).

**Notes**

- The labeled form (`2. Summary\n<content>`) still works — this is an additive gap, not a break.
- Fix shape: positional fallback. When header-based parse yields <3 canonical sections but ≥4 sequentially-numbered blocks exist with unique digits in 1-9, map digit → canonical key via the prompt order (1→lovable_repo, 2→summary, …, 9→growth_hypothesis) and use the full line content as the section body. Threshold ≥4 (not ≥3) reduces false positives on stray numbered lists in plain prose.


### 2026-05-23 — Step 5.5 reports `↷ probe failed` on CF-managed read-only DNS records

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


### 2026-05-20 — `make deps` hits pnpm store version mismatch on new-domain builds

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

### 2026-05-20 — `new bootstrap` should generate a copy-paste LLM prompt first

**Repro**

    lamill new bootstrap agesdk.dev

Operator runs bootstrap → faced with 5+ paragraph-style prompts
(Summary / Audience / ICP / Goals / Content strategy / Growth
hypothesis) cold. Has to compose each answer in-prompt without
any AI assistance, OR open ChatGPT/Claude in a separate window
and manually feed each prompt one at a time.

**Expected**

BEFORE firing the first interactive prompt, bootstrap renders a
ready-to-paste prompt template the operator can drop into
chatgpt.com / claude.ai. The template asks for all the section
contents at once + the growth hypothesis, organized clearly so
the LLM's response can be split section-by-section into the
bootstrap prompts.

Something like:

```
─── Copy-paste prompt for ChatGPT / claude.ai ─────────────────

I'm scaffolding a new site at agesdk.dev. Topic: <prompt me or use
--topic flag if supplied>.

Please draft the following for me. Keep each section under
the indicated length. Put each section under its labeled H2
heading so I can copy-paste them one at a time:

## Summary
One paragraph (3-5 sentences). What this site IS and what it
DOES. Concrete, not aspirational.

## Audience
One sentence. The broad demographic (e.g. "homeowners with EV
chargers" / "RN/Expo developers shipping consumer apps").

## ICP
One paragraph. The SPECIFIC targetable subset — demographics,
pain points, what they use today. More precise than Audience.
Concrete enough you could write an ad-targeting brief from it.

## Goals
1-2 sentences. The primary business / product goal. Time-bound
if there's a relevant deadline.

## Content strategy
One paragraph. Page types this site needs · initial topics ·
format mix (long-form vs reference vs tool).

## Growth hypothesis
One paragraph. Your bet for how this site reaches its audience.
Distribution channel + why it's defensible + the timing window.

──────────────────────────────────────────────────────────────

When you have the response, the next prompts will ask for each
section one at a time. Paste each one in.
```

The operator can either:
  (a) Type answers freehand (current behavior — preserved); OR
  (b) Open the LLM, paste this template, copy the structured
      response, then paste section-by-section into each prompt.

**Actual**

Bootstrap fires the prompts cold. Operator either composes each
one freehand (slow) or shuttles between windows manually.

**Where (guess)**

Print the template right after the pre-flight question list
banner (the other 2026-05-20 bug). New helper
`_render_llm_prompt_template(domain, topic)` in bootstrap-orchestrator
code. Skip when `--non-interactive` set.

**Severity** — `major`

The cold-prompt experience is a real friction point — operator's
test session showed two sections answered with content from the
NEXT section over (Summary got the Goals content, Audience got the
ICP content), because composing in-prompt without context is hard.
An LLM-staged response makes section-to-prompt mapping mechanical.

**Notes**

Surfaced 2026-05-20 by operator. Pairs naturally with the multi-
paragraph paste fix (also 2026-05-20) — together they make the
LLM-stage → paste-each-section workflow clean.

---

### 2026-05-20 — `new bootstrap` should ask whether the frontend is already designed

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

### 2026-05-20 — `new bootstrap` prompt layout makes Audience/ICP visually confusable

**Repro**

    lamill new bootstrap agesdk.dev

The operator's 2026-05-20 test session captured this exact
behavior:

```
  Audience — one sentence: who this is for (broad demographic)
  >: ICP: RN/Expo developer or small-team CTO at a consumer app
     with California users. Never dealt with age compliance before.
     Found the law via a legal email or Twitter. Will self-serve,
     will not talk to sales.

  ICP — the specific ideal customer — demographics, pain points,
  what they use today. More detail than Audience: Audience is the
  broad demo ("homeowners with EV chargers"), ICP is the specific
  targetable subset ("Tesla owners in CA who installed in last 90d,
  paid $2k+")
  >: <empty>
```

Operator typed the ICP content into the AUDIENCE prompt because:

  1. Each prompt's instruction text wraps onto multiple lines.
  2. The ICP prompt header (`ICP — the specific ideal customer
     — demographics, pain points, what they use today.`) starts
     immediately after the operator's Audience input.
  3. Operator's eye treated the ICP description text as additional
     context for the Audience question — natural pattern-matching
     failure on the visual hierarchy.

**Expected**

Each prompt is visually distinct enough that the operator can't
accidentally type a later prompt's content into an earlier one.
Concrete options (combinable):

  1. Echo the operator's input back after each prompt with a
     "[saved as <section>]" confirmation before moving on.
  2. Add a visual separator (rule line / blank line / bold
     heading) between sections so the next prompt's intro doesn't
     blend into the prior section's input area.
  3. Show only the H2-name + the `>:` line, with full description
     printed BEFORE the input field rather than between sections.
  4. Number each prompt (`[2/9] Audience:`) so operator can track
     which one they're on without re-reading the surrounding text.

**Actual**

Two operator sections got mis-routed in real testing. Bootstrap
saved incorrect content + left the correct slots empty (rendered
as `(to be filled in)` placeholders, requiring manual edit later).

**Where (guess)**

Whichever function in `src/portfolio/cli.py` /
`src/portfolio/bootstrap.py` orchestrates the v9.B AI_AGENTS
section prompts. The visual layout fix is the same place; the
"[saved as X]" confirmation is the same pattern.

Pairs with the cut-and-paste LLM prompt fix above — when operator
uses the LLM-staged flow (paste structured response section-by-
section), this confusion mostly disappears because each section
is already pre-labeled by the LLM.

**Severity** — `major`

Operator hit it on their first test session.

**Notes**

Surfaced 2026-05-20 by operator during the same test session that
surfaced the multi-paragraph paste + Lovable repo + pre-flight
listing bugs.

---

### 2026-05-20 — `new bootstrap` prompts don't validate input format

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

### 2026-05-20 — `project check` groups `warn` results inconsistently across the rendered sections

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

### 2026-05-20 — v13.B `project seo` GSC diagnostics — 3 rendering/classification issues

**Repro**
    lamill project seo hybridautopart.com --top 30

Run against a live, GSC-verified site. One operator run surfaced
all three sub-issues at once.

**Expected**
- Coverage section accurately reflects GSC URL Inspection verdicts
  (URLs reported as "submitted and indexed" should count as
  indexed and render with a pass marker).
- `--top N` is honored beyond 10 — `--top 30` should inspect up to
  30 URLs.
- Relative-date formatter renders sub-day deltas as "today" or
  "~0d ago", never "0y ago".

**Actual**
Three rendering/classification defects in one run, captured below:

1. **Coverage state misclassified.** Every URL in the output was
   labeled "submitted and indexed" by the GSC URL Inspection API,
   but the renderer marked them all with ✗ (red cross) and counted
   them as **0/10 indexed (0%)**. The classifier likely expects the
   GSC verdict token `submitted_indexed` (underscored) but the API
   is returning `submitted and indexed` (human text), so nothing
   matches the pass case and everything falls through to the fail
   rendering. The header `📊 Coverage (top 10 inspected — 0/10
   indexed, 0%)` is therefore wrong on a healthy site.

2. **`--top N` not honored beyond 10.** Operator passed `--top 30`
   but only 10 URLs were shown. Either the API call caps at 10, or
   the top-N truncation happens before the user's value is applied,
   or both. Either way the flag is silently capped.

3. **Relative-date formatter unit bug.** One row reads `crawled 0y
   ago` — "0 years ago" — for a URL crawled today (or very
   recently). The relative-time formatter is picking the wrong unit
   at the low end. Should read "today" or "~0d ago".

Full operator terminal output:

```
$ lamill project seo hybridautopart.com --top 30
Probing 1 domain(s) — HTTP + GSC (28d) + CrUX...
  [1/1] hybridautopart.com
check --seo · 1 domains · GSC 28d · sort=impressions
 SEO  Domain              HTTP    Robots  Sitemap  GSC  GSC sm     Imp  Clicks   CTR   Pos
 🟡   hybridautopart.com  🟢 200    🟢      🟢     🟢     🟡    26,378     117  0.4%  13.3

  GSC diagnostics
    Property: https://hybridautopart.com/
    📋 Sitemaps (1 submitted)
      ⚠ WARN     /sitemap_index.xml               3 warning(s)  ·  fetched 17h ago
    📊 Coverage (top 10 inspected — 0/10 indexed, 0%)
      ✗ https://hybridautopart.com/            submitted and indexed     crawled 4d ago
      ✗ https://hybridauto…-en/subaru-hybrids/ submitted and indexed     crawled 5d ago
      ✗ https://hybridauto…blog-en/phev-guide/ crawled - currently not indexed  verdict=NEUTRAL · crawled 0y ago
      ✗ https://hybridauto…rgy-drive-problems/ submitted and indexed     crawled 4d ago
      ✗ https://hybridauto…-en/prius-charging/ submitted and indexed     crawled 3w ago
      ✗ https://hybridauto…ing-courses-online/ submitted and indexed     crawled 3w ago
      ✗ https://hybridauto…og-en/mhev-vs-phev/ submitted and indexed     crawled 9d ago
      ✗ https://hybridauto…power-split-device/ submitted and indexed     crawled 9d ago
      ✗ https://hybridauto…ible-link-assembly/ submitted and indexed     crawled 8w ago
      ✗ https://hybridauto…tion-engine-heater/ submitted and indexed     crawled 3d ago
```

**Where (guess)**
`src/portfolio/project_seo_diagnostics.py` — the coverage
classifier + renderer + relative-date formatter all live here (or
in a helper module called from here). Suggested fix directions:

- *Issue 1:* Normalize the GSC verdict string before matching
  against the pass case (`submitted_indexed` / `submitted and
  indexed` → same key). Case-fold + collapse spaces/underscores
  before comparison.
- *Issue 2:* Check the URL Inspection API call's `top_n` path;
  ensure `top_n=30` is plumbed all the way through (from CLI flag
  → diagnostics entry point → API call → result truncation).
  Default cap may be hardcoded to 10 somewhere along the chain.
- *Issue 3:* In the relative-date formatter, add a "today" / "0d"
  branch before the years/weeks/days cascade falls through to
  years for sub-1d deltas. Likely an integer-divide ordering issue
  where `delta_days // 365 == 0` is being formatted as "0y" instead
  of falling through to the days/hours/today branch.

**Severity**
minor — cosmetic + small accuracy issue. The Coverage% misread is
the most visible (operator can't trust the "0/10 indexed" header
on a healthy site), but no data loss; underlying GSC data is
correct, just rendered wrong.

**Notes**
All three issues surfaced in v13.B (per-project GSC diagnostics as
`project seo` default — shipped in commit `a693d96`). Likely
shippable as one small follow-up phase (v13.C?) since they share
a file and a renderer. Self-contained — full repro output captured
above so the bug record stands alone.

---

### 2026-05-18 — `settings deploy set` fails for sites/ dirs missing from portfolio.json

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

### 2026-05-18 — `settings deploy set` doesn't auto-populate `custom_domains` from dir name

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

### 2026-05-19 — `fleet hosting` walkers miss ~9 fleet sites declared as `vercel` / `cf-*` *(diagnosed: data-quality, not walker bug — partial wontfix)*

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

### 2026-05-19 — HG walker `install_path` empty for every row despite addon-domain doc-roots existing

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

### 2026-05-19 — HG walker reports no `wp_version` for any row (WP detection blind)

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

### 2026-05-19 — `fleet dashboard` truncates every cell on standard terminal width

**Repro**
    lamill fleet dashboard
    # Standard 80-col-ish terminal; output shows `hyb…`, `iot…`, `air…`
    # for every domain.

**Expected**
Domain column wide enough to render the actual domain in the
common-fleet-size case. Other columns either widen or accept
narrower rendering — but domain (the row identifier) should never
be truncated to "_xyz…_" unreadable form.

**Actual**
With 15 columns (12 original + Host + Prov added in v11.K + Site +
Domain age), rich.Table squeezes every column to fit terminal
width. Result: `hyb…` instead of `hybridautopart.com`.

**Where (guess)**
`src/portfolio/dashboard.py:render_dashboard` adds 13-15 columns
with default sizing. Rich uses proportional shrinking. Options:

1. Mark `Domain` as `no_wrap=True` + `min_width=25` so it gets
   priority space.
2. Drop the Live + Conf columns (less actionable than the dots)
   when terminal width is < 120 columns.
3. Default sort changes — surface most-actionable-first (already
   sort=attention default) AND limit display to top-N by default
   with --all to render everything.

**Severity**
minor — predates v11.K (was already truncating columns; v11.K just
made it slightly worse by adding 2 more). Information is in the
rendered cells, just unreadably narrow at standard width.

**Notes**
Pick up in a future v11 polish phase. Probably fold into v11.L
docs sync if there's slack, or its own commit.

---

### 2026-05-18 — `fleet seo --refresh` and `fleet domains` show different domain counts

**Repro**
    uv run lamill fleet seo --refresh
    uv run lamill fleet domains

**Expected**
The two commands should show consistent fleet sizes, or — if the
scope differs — surface that in the output footer so the operator
can see *why* the counts diverge.

**Actual**
`fleet seo --refresh` shows 22 domains; `fleet domains` shows 36.
No visible explanation for the 14-domain gap.

**Where (guess)**
`src/portfolio/cli.py:5324` (`fleet_domains`) and `cli.py:5334`
(`fleet_seo`). Both default `--only wip` but `fleet_seo` calls
through `check_seo` which additionally filters to
`live-site`/`forwarder` classification (the SEO probe skips
parked / dead / archived sites by design). The filter is silent
— the operator sees only the final count.

**Severity**
minor — likely an intentional scope filter, but the silent
discrepancy is a usability gap.

**Notes**
Two fix paths worth considering when this is picked up:
(a) Show a footer note when SEO is filtering: "Showing N of M
WIP domains (excluded: K parked / J dead / I archived)."
(b) Add an explicit `--scope` flag to both commands so the
operator can match scopes when comparing counts.

Either path is small (≤30 min). Defer until after v10.A-D ships,
or fold in alongside v11.A's `fleet hosting` (which has the same
"WIP vs live-site" filter question per resolution 11.B).

## Fixed bugs

### 2026-05-28 — `new domain` Step 1 brand-collision check (gpt-5-mini) false-negatives same-category niche competitors

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

**Fixed in** — `<SHA on commit>` (3 new tests in `test_suggest.py`: topic reaches the prompt, no-topic degrades cleanly, `_collision_topic_block` unit)

**Notes**

- Doesn't fully close the niche-recall gap — still AI-only, no live web search (Brave's free tier was dropped 2026-05-08). The deferred decision-aids work ([[project_deferred_decision_aids]] — USPTO/GitHub/social pre-checks) is the path to a live collision backstop if the topic-aware prompt proves insufficient in soak. Topic-awareness is the cheap high-value first step.
- The operator should re-run the marginready decide flow to confirm the model now flags it — the prompt is correct, but model recall of that specific niche brand isn't guaranteed even with category context.

---

### 2026-05-27 — `fleet fix` auto-toggled `always_use_https` on csinorcal.church (dark sites had no first-class config classification)

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

### 2026-05-27 — `settings cloudflare check-token` returns ✓ when token lacks Cache Purge / Zone Settings:Edit (only DNS:Edit was probed per zone)

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

### 2026-05-27 — CHECK_057 false-fails non-HTML paths served by CF's SPA-fallback handler (originally diagnosed as origin-orphans)

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

### 2026-05-27 — `new deploy` fails Step 2 when local origin uses `<domain>` form (e.g. `kwizicle.com`) but slug derivation produces `<short>` form (`kwizicle`)

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

### 2026-05-26 — CHECK_150 fixer post-write verification races CF edge propagation

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


### 2026-05-22 PM — Step 5.5 false-flags legitimate DNS records as conflicts on re-deploy

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

### 2026-05-22 PM — Step 5.5 403 hint doesn't show the actual records that need deletion

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

### 2026-05-22 PM — v15.S `pnpm-workspace.yaml` format silently broken under pnpm v11.1.3

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

### 2026-05-22 PM — `lamill new trends` (no topic) — feature withdrawn after Google API surface dried up

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

### 2026-05-22 — `lamill new trends <topic>` on HTTP 429 surfaces a cryptic error with no recovery hint

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

### 2026-05-22 — `lamill new trends <topic>` raises `ModuleNotFoundError: No module named 'pytrends'` when running outside the `uv` venv

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

### 2026-05-20 — tech-debt audit pass

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

### 2026-05-20 — Deploy Step 5.5 (DNS purge) continues on auth failure instead of pausing for manual cleanup

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

### 2026-05-20 — `project check` deploy summary line shows wrong platform for cf-workers sites

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

### 2026-05-19 — HG-extra `disk N MB` is account-level total, looks per-domain

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

### 2026-05-18 — `domain suggest` menu has letter-keyed option `s` between numbered 7 and 8

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

### 2026-05-20 — Bootstrap's `package.json` template ships deprecated pnpm field

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

### 2026-05-20 — All `new` commands leave residue when they fail mid-flight

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

### 2026-05-20 — `new bootstrap` doesn't prompt for Lovable's GitHub repo URL

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

### 2026-05-20 — `new bootstrap` doesn't list all prompts upfront

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

### 2026-05-20 — `new bootstrap` prompt input overflow (multi-paragraph paste leaks to shell)

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

### 2026-05-20 — `new bootstrap` accepts unregistered/typo'd domains silently

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

### 2026-05-19 — `fleet hosting` table has no summary footer

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

### 2026-05-19 — `lamill fleet hosting --provider=X` with 0 matches says only "No hosting rows."

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

### 2026-05-19 — `HG-extra` column always rendered, even when no HG rows

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

### 2026-05-18 — `test_serp_fetch.py` not isolated from real `data/serp/_quota.json`

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
