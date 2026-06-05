# Indexing module — investigation + plan

**Date:** 2026-06-05
**Status:** Plan only. No production code in this pass (per operator's handoff).
**Trigger:** Evaluate a post-publish indexing module for `lamill`, inspired by
IndexerHub (indexerhub.com). Notify search engines about new/changed URLs on
deploy (or on a schedule), and track index status portfolio-wide.

This doc has three parts: (1) what the tool already has and can reuse, (2) what
the external APIs actually constrain us to, (3) the capability/build-vs-skip
table, the delivery design (no new CLI — checks + fixes + one deploy hook), data
model, idempotency design, and sequencing.

---

## 1. What lamill already has (reuse, don't duplicate)

The single biggest finding: **the URL Inspection API is already wired**, and so
is sitemap submission. Most "index status checking" is a thin new surface over
existing code, not a new integration.

### 1.1 Google auth — OAuth user credentials (NOT service account)

`src/portfolio/gsc.py`:

- **Mechanism:** OAuth 2.0 *user* credentials via `google-auth-oauthlib`
  (`InstalledAppFlow.from_client_secrets_file`), refresh-token flow,
  auto-refresh on expiry, interactive re-consent on failure.
- **Scopes currently held** (`gsc.py:29-32`, v24.B scope bump):
  ```python
  SCOPES = [
      "https://www.googleapis.com/auth/webmasters",
      "https://www.googleapis.com/auth/siteverification",
  ]
  ```
- **`https://www.googleapis.com/auth/indexing` is NOT held.** Deliberately —
  `gsc_recrawl.py` notes the Indexing API is restricted to JobPosting/
  BroadcastEvent and using it for general pages violates Google's ToS.
- **Credential storage:** `~/.config/portfolio/gsc/credentials.json` (operator
  places the GCP OAuth client secret) and `~/.config/portfolio/gsc/token.json`
  (cached refresh token, chmod 0o600, written by `_save_token`).
  - Note: GA4 uses a *different* path (`~/lamill/ga4/`) per the no-hidden-config
    preference. New work should follow `~/lamill/` for any net-new cred dir, but
    GSC's existing `~/.config/portfolio/gsc/` is the one we reuse here.

**Scope implication for this module:**

| API we'd want | Scope needed | Held today? |
|---|---|---|
| GSC URL Inspection (`urlInspection.index.inspect`) | `webmasters` (or `.readonly`) | ✅ yes |
| GSC Sitemaps submit | `webmasters` | ✅ yes |
| Google Indexing API (`urlNotifications:publish`) | `indexing` + **service account** | ❌ no (and different auth model) |
| IndexNow | none (no Google auth at all) | n/a |

So: **status-checking and IndexNow need zero new auth.** Only the
(unrecommended) Google Indexing API would require both a new scope *and* a
service-account credential path that doesn't exist yet.

### 1.2 URL Inspection API — already implemented

`src/portfolio/gsc_recrawl.py:290-310`, `inspect_one_url(service, site_url, url)`:

- Calls `service.urlInspection().index().inspect(body={"inspectionUrl": url,
  "siteUrl": site_url})` via the `googleapiclient` service from `gsc.get_service()`.
- Parses out: `lastCrawlTime`, `pageFetchState`, `indexingState`,
  `coverageState`, `verdict` → `UrlInspection` dataclass.
- Already consumed by `checks/deploy/check_147_url_indexed.py` and
  `project_seo_diagnostics.py:fetch_coverage_details()` (which also normalizes
  coverage strings → canonical tokens like `submitted_indexed`,
  `crawled_not_indexed`, `not_found_404`, `soft_404`).

**This is the entire backbone of `index status` and 404/deindex monitoring.** We
reuse `inspect_one_url` verbatim.

### 1.3 Sitemap submission — already implemented

`src/portfolio/gsc_admin.py:599-642`, `submit_sitemap(domain, sitemap_url)`:

- httpx-direct `PUT https://www.googleapis.com/webmasters/v3/sites/{site}/sitemaps/{feed}`.
- Idempotent: pre-checks `list_sitemaps()`, returns `False` if already present.
- Called from deploy Step 9 (`_deploy_step9_gsc`, `cli.py:7772-7894`).

We reuse this for sitemap (re)submission; the *new* piece is **sitemap-diff**
(detecting which URLs are new since last run), which the tool does not do today.

### 1.4 GSC property provisioning at deploy — already implemented

`_deploy_step9_gsc` (`cli.py:7772-7894`): DNS_TXT verification → `add_site`
(`sc-domain:<domain>`) → `submit_sitemap`. All idempotent, with 403
disambiguation (`classify_403`: insufficient-scope / service-disabled /
invalid-grant). A post-deploy indexing ping slots in right after this as
"Step 10".

### 1.5 Conventions a new `index` surface must match

- **CLI:** Typer, scope-first (`project` / `fleet` / `new` / `settings`),
  registered in `src/portfolio/cli.py` (~10.5k lines — see the tracked CLI-split
  refactor). Plural symmetric nouns; write verbs hang off a read command as
  flags (the v27 `project todos --add/--done` pattern).
- **Credentials:** `apikeys.get_key("NAME")` reads `portfolio.env` at repo root.
  `KNOWN_KEYS` is a strict allow-list. Atomic write via tmpfile+rename.
- **Data storage:** date-stamped JSON snapshots, two shapes:
  - flat per-date: `data/checks/2026-06-05.json` (`check.py`), `data/seo/…`.
  - per-domain per-date: `data/gsc/<domain>/2026-06-05.json`
    (`gsc_detail_cache.py:save_snapshot`) — **this is the shape a per-site index
    store should match.**
  - All snapshots carry `fetched_at` (ISO-8601 UTC) and use atomic
    tmpfile-replace. Staleness via `is_stale(path, max_age_hours=24)`.
- **Per-site config:** `lamill.toml` additive-optional tables, surgical upsert
  via `lamill_toml_edit.set_table` (ADR-0018, never a full rewrite).
- **HTTP + tests:** httpx + `httpx.MockTransport(handler)`; tests in `tests/`,
  run with `uv run pytest -q`.

---

## 2. External API constraints (from the docs)

### 2.1 IndexNow — clean, free, sanctioned. Google does NOT participate.

- **Participating engines (2025/2026):** Microsoft Bing, Yandex, Naver,
  Seznam.cz, Yep. **Google has never adopted it** (tested 2021, declined).
  IndexerHub's "LLM/AI indexing" marketing is IndexNow→Bing rebranding — treat
  as one channel, not a separate one.
- **One ping → all engines.** Submit to any one participating endpoint (or the
  generic `https://api.indexnow.org/indexnow`) and it's shared to the rest.
- **Key file hosting:** a UTF-8 text file at the domain root,
  `https://<domain>/<key>.txt`, whose contents are the key itself. Key = 8–128
  chars `[a-zA-Z0-9-]`. (Optional `keyLocation` lets you host elsewhere, scoped
  to a path prefix — we don't need it.)
- **Submit formats:**
  - Single (GET): `https://<engine>/indexnow?url=<url>&key=<key>`
  - Bulk (POST): `POST https://<engine>/indexnow`, JSON
    `{"host","key","keyLocation","urlList":[...]}`, up to 10,000 URLs/request.
- **Rate behavior:** no documented daily quota; `429` if you submit "too often."
  Practically generous for a portfolio-scale fleet.
- **Cloudflare angle (relevant — the fleet is CF Pages):**
  - The key file is trivially served: drop `public/<key>.txt` in the site repo;
    CF Pages serves it at `https://<domain>/<key>.txt`. No special config.
  - CF *also* has native IndexNow via Crawler Hints (one-click, expanded to all
    paid plans in Q4 2025). That's an alternative to us pinging at all — but it
    fires on CF's own crawl signals, not on our deploy event, and gives us no
    portfolio-wide ledger. Our explicit ping is more controllable; worth a note,
    not a dependency.

### 2.2 Google Indexing API — the arms-race piece. Skeptical by design.

- **Endpoint:** `POST https://indexing.googleapis.com/v3/urlNotifications:publish`
- **Scope:** `https://www.googleapis.com/auth/indexing` (not held) **and it
  requires a service account** — a different auth model from the OAuth user flow
  the tool uses everywhere else. Net-new credential path.
- **Officially sanctioned use:** *only* pages with `JobPosting` or
  `BroadcastEvent` (livestream `VideoObject`) structured data. **General web
  pages are out of scope per Google's own docs.** None of the fleet's sites are
  job boards or livestream pages.
- **Quota:** default **200 publish requests/day per GCP project**, across all
  sites. Batching does not save quota (10-in-1 still counts as 10). Reset at
  midnight PT.
- **Quota-exhausted error:** HTTP `429`, body `"Quota exceeded for quota metric
  'Publish requests' and limit 'Publish requests per day' of service
  'indexing.googleapis.com'"`.
- **The "key rotation" arms race:** IndexerHub multiplies the 200/day by
  spreading submissions across *many service accounts in many GCP projects*.
  This exists solely to circumvent a documented per-project quota, for a use case
  Google documents as unsupported. **Effectiveness for general pages is anecdotal
  at best, and the whole construct is a ToS-gray treadmill.** Flagged below as
  opt-in / not-default / risk-acknowledged.

### 2.3 GSC URL Inspection API — the sanctioned status channel.

- **Endpoint:** `POST https://searchconsole.googleapis.com/v1/urlInspection/index:inspect`
  (already called via the `googleapiclient` service).
- **Scope:** `webmasters` or `webmasters.readonly` — **we hold `webmasters`.** ✅
- **Quota:** **2,000 queries/day and 600/minute, per property** (project ceiling
  10M QPD / 15k QPM — irrelevant at our scale). 2k/site/day is far above what a
  portfolio site needs.
- **Index-status fields:** `verdict`, `coverageState`, `indexingState`,
  `lastCrawlTime`, `pageFetchState`, `robotsTxtState`, `googleCanonical`,
  `userCanonical`. (The tool already parses the first five.)
- **Latency:** ~seconds per URL (live call against Google's index); this is the
  real cost driver, so status runs must be cached/snapshotted, not live every time.

---

## 3. Capability table — IndexerHub feature → can lamill do it?

| # | IndexerHub feature | lamill can? | Effort | Dependency | Risk | Verdict → home |
|---|---|---|---|---|---|---|
| 1 | Google Indexing API submission (key rotation) | Technically yes | High | New `indexing` scope + service-account auth + multi-project rotation | **High** — unsanctioned use, ToS-gray, anecdotal value | **SKIP** (opt-in flag only) |
| 2 | IndexNow pings (Bing/Yandex/+partners) | Yes | Low–Med | Key file in `public/`; httpx POST | Low — sanctioned, free | **BUILD** → fix on the `indexnow-submitted` check + deploy hook |
| 3 | Sitemap discovery + new-URL detection | Yes | Med | Reuse sitemap fetch; new "last-seen URL set" snapshot | Low | **BUILD** → inside the `indexnow-submitted` check/fix |
| 4 | GSC URL Inspection status checking | Yes (already wired) | Low | Reuse `gsc_recrawl.inspect_one_url` | Low | **EXISTS** → CHECK_147 url-indexed |
| 5 | Smart retry / exponential backoff | Yes | Low | Reuse existing backoff patterns (`gsc_admin` polling) | Low | **BUILD** (folded into the ping fixer) |
| 6 | 404 / deindex monitoring | Yes | Low–Med | Reuse URL Inspection (`pageFetchState`, `indexingState`) | Low | **BUILD** → new `index-regression` check (no fix) |
| 7 | Dashboard: indexed vs pending | Yes | Med | Reuse `fleet dashboard` / snapshot rollup | Low | **BUILD** → `fleet check` rollup columns |

### Build-vs-skip, one line each

1. **Google Indexing API + key rotation — SKIP (opt-in, flagged).** Its only
   purpose is circumventing a documented 200/day quota for a use Google says is
   JobPosting/BroadcastEvent-only; none of the fleet qualifies. Present as a
   risk-acknowledged, default-off escape hatch at most — never wire it on.
2. **IndexNow ping — BUILD first.** Free, sanctioned, one POST reaches
   Bing/Yandex/Naver/Seznam/Yep; key file is a static file CF Pages already serves.
3. **Sitemap-diff / new-URL detection — BUILD.** The genuinely-new, genuinely-
   useful primitive: it's the autopilot input that feeds both ping and status.
4. **GSC URL Inspection status — ALREADY EXISTS.** CHECK_147 url-indexed already
   inspects top-N URLs and caches to `data/gsc/<domain>/`. Nothing new to build;
   we extend it for regression (item 6).
5. **Smart retry/backoff — BUILD (folded in).** Not a feature, a property; reuse
   the existing polling/backoff helpers inside the ping fixer.
6. **404/deindex monitoring — BUILD.** Falls out of URL Inspection for free:
   a new `index-regression` check flags a known URL flipping to `NOT_INDEXED` /
   `pageFetchState=NOT_FOUND`. Monitoring only — no fixer (deindexing isn't
   auto-fixable; it's a `fail` to surface, not remediate).
7. **Indexed-vs-pending dashboard — BUILD.** Rollup columns on the existing
   `fleet check` / dashboard, fed by the CHECK_147 snapshots.

**Net:** build the clean free sanctioned pieces (2,3,5,6,7) as checks + fixes;
reuse the existing url-indexed check (4); skip the quota-circumvention piece (1).
This matches the operator's stated bias exactly — and adds **zero new CLI**.

---

## 4. Delivery — no new CLI: checks + fixes + one deploy hook

**Decision (operator, 2026-06-05): no new `index` command surface.** The whole
capability rides existing surfaces — the CHECK catalog (`project check` /
`fleet check`), the FIX system (`project fix` / `fleet fix`), and the deploy
pipeline. This also gives us the backfill mechanism for free: `fleet fix` *is*
the fleetwide autopilot.

### 4.1 Why a remote ping fits inside a fix (no new write-surface ADR)

Fixers already perform remote API side effects and re-probe to verify:

- `checks/seo/check_057_cf_edge_cache_fresh.py` — its `fix_tier_1` calls
  `cloudflare.set_zone_setting(...)` then HEAD-probes to confirm.
- `checks/seo/check_150_apex_canonical_redirect.py` — its fixer calls Cloudflare
  *or* Vercel APIs (`update_domain_redirect`, `add_domain_to_project`) then
  re-probes.

So an IndexNow POST as a fix action is an established pattern, not a new
write-surface category — ADR-0003's local-FS surfaces and ADR-0011's remote-host
writes already coexist with "fixers may call external APIs." No new ADR needed
for the *mechanism*. (An ADR is still warranted for the *posture* — "indexing
notification belongs in the conformance/fix loop" — written in the kickoff phase.)

### 4.2 The new checks (all in `checks/deploy/`, next free NNN)

Each follows the canonical contract: module-level `CHECK_ID` / `CHECK_NAME` /
`CATEGORY` / `SEVERITY` / `DESCRIPTION` + `run(repo_path) -> CheckResult`,
auto-discovered by `checks/registry.py`. Fixable ones export a `fix_tier_1 =
FixerSpec(apply=...)`.

| Check (proposed) | `run()` asserts | `fix_tier_1` | Backfills via |
|---|---|---|---|
| **`indexnow-key-present`** (e.g. CHECK_152) | web project has `[index].indexnow_key` in `lamill.toml` **and** `public/<key>.txt` exists matching it | **yes** — generate key, write `public/<key>.txt` (`file_writer`), upsert `[index]` table (`lamill_toml_edit.set_table`). Pure local-FS write. | `fleet fix --apply` |
| **`indexnow-submitted`** (e.g. CHECK_153) | every live-sitemap URL is present in the submission ledger (no new/unsubmitted URLs) — sitemap-diff vs `_ledger.json` | **yes** — pre-flight: GET `https://<domain>/<key>.txt` == key; then IndexNow POST the new/changed URLs, append ledger, re-probe. Remote side effect (precedent: CHECK_057/150), ledger-gated. | `fleet fix --apply` |
| **`index-regression`** (e.g. CHECK_154, or fold into CHECK_147) | no previously-indexed URL flipped to `NOT_INDEXED` / `pageFetchState=NOT_FOUND` (snapshot diff over URL Inspection) | **none** — monitoring only; deindexing isn't auto-fixable | n/a (report) |

`CHECK_147 url-indexed` stays as-is (the indexed-vs-pending status); item 7's
dashboard columns read its snapshots.

### 4.3 The one existing-functionality hook (no new command)

- **Deploy Step 10.** `new deploy` calls the *same* ping helper `indexnow-submitted`'s
  fixer uses, right after GSC Step 9 (`_deploy_step9_gsc`), soft-fail. New sites
  ping on publish; everything else is caught by `fleet fix`.
- **Bootstrap.** `new bootstrap` writes `public/<key>.txt` + the `[index]` table
  via the same helper as the `indexnow-key-present` fixer, so new sites are born
  compliant; the check+fix backfills the rest of the fleet.

### 4.4 Backfill story (the whole point)

Two passes, because the key file must be **live** before a ping can verify:

1. `fleet fix --apply` → `indexnow-key-present` provisions `public/<key>.txt` +
   `[index]` on every site missing it (local-FS writes). Operator commits +
   deploys → key files go live.
2. `fleet fix --apply` again → `indexnow-submitted` now passes pre-flight and
   pings each site's sitemap URLs, writing the ledger.

`indexnow-submitted` is `SEVERITY = "warn"` (not `error`) so it doesn't nag a
site whose key isn't live yet — it just reports "key not live, redeploy" until
pass 1's changes ship. Dry-run (default, no `--apply`) lists "would ping N URLs"
per site; `--apply` actually pings; re-runs are ledger-gated no-ops.

### 4.5 `lamill.toml` `[index]` table (additive-optional)

```toml
[index]
indexnow_key = "a1b2c3...f9"     # also lives at public/<key>.txt
indexnow_enabled = true          # default true; per-site opt-out
# google_indexing = false        # explicit opt-in only; absent == off
```

Honors the additive-optional invariant: absent table == IndexNow off-by-config,
everything else still works; no check/fix/consumer may *require* it. The
`indexnow-key-present` check returns `pass`/skip on a site that has deliberately
set `indexnow_enabled = false`.

---

## 5. Data model (append-only JSON, matches existing crawl storage)

New tree `data/index/<domain>/`, mirroring `data/gsc/<domain>/`:

```
data/index/<domain>/
├── 2026-06-05.json        # per-date status snapshot (URL Inspection results)
├── _ledger.json           # append-only submission ledger (what we've pinged)
└── _sitemap-seen.json     # last-seen sitemap URL set (for new-URL diffing)
```

**Status snapshot** `data/index/<domain>/<YYYY-MM-DD>.json` (same shape as
`gsc_detail_cache.save_snapshot`):

```json
{
  "fetched_at": "2026-06-05T12:00:00+00:00",
  "domain": "example.com",
  "urls": [
    {
      "url": "https://example.com/",
      "indexing_state": "INDEXED",
      "coverage_state": "submitted_indexed",
      "page_fetch_state": "SUCCESS",
      "last_crawl_time": "2026-06-01T03:11:00+00:00",
      "verdict": "PASS"
    }
  ]
}
```

**Submission ledger** `_ledger.json` (append-only — the audit trail of pings):

```json
{
  "entries": [
    {
      "url": "https://example.com/new-page",
      "submitted_at": "2026-06-05T12:00:00+00:00",
      "channel": "indexnow",
      "engine_endpoint": "https://api.indexnow.org/indexnow",
      "result": "ok",
      "content_hash": "sha256:…"
    }
  ]
}
```

**Sitemap-seen** `_sitemap-seen.json` — the prior URL set (+ optional `lastmod`
or content hash per URL) so a run can compute `new_or_changed = current −
last_seen`. Updated only after a successful ping (so an interrupted run re-diffs
cleanly).

All writes: atomic tmpfile+replace, `fetched_at` UTC, exactly like `serp.py` /
`gsc_detail_cache.py`.

---

## 6. Idempotency / re-runnability design

The fix framework already gives us the spine: **dry-run by default, `--apply`
required, idempotent re-runs** (the locked `new deploy` invariant, ADR-0015).
The `indexnow-submitted` fixer layers on ledger-gating so it's safe to run in a
`fleet fix` loop as often as the operator likes.

### 6.1 Pre-flight probe (inside the fixer's `apply`, before any submit)

- **IndexNow key live:** GET `https://<domain>/<key>.txt`; assert body == key.
  Not-live is **expected** before pass-1's key file deploys, so the fixer returns
  `FixResult("manual", "key not live — deploy public/<key>.txt first", [])` (a
  warn-style deferral with the remediation), **never a hard error**. Don't submit
  against a key the engines can't verify.
- **URL Inspection (for the status checks):** `gsc.TOKEN_PATH.exists()`; reuse
  `classify_403` for scope/service-disabled/invalid-grant disambiguation. `warn`
  + `settings gsc auth` hint if absent (same as deploy Step 9 + CHECK_147).
- **Google Indexing (only if opted in):** probe the service-account JSON + the
  `indexing` scope; absent → skip, never silently fall through.

### 6.2 Safe re-submission (ledger-gated) — what makes `fleet fix` re-runnable

- A URL is pinged **only if** it's not in `_ledger.json`, *or* its
  content-hash/`lastmod` changed since the last entry. A `fleet fix` over an
  unchanged fleet pings nothing: every site's fixer returns
  `FixResult("nothing-to-do", "ledger current", [])`.
- Dry-run (default): `FixResult("would-fix", "would ping N new URLs", [...])`.
  `--apply`: actually POSTs, then re-probes. Standard `✓ / ↷ / ✗` markers in the
  `project fix` / `fleet fix` output.

### 6.3 Checkpoint resume

- The ledger is written **incrementally** (append after each engine ack), so an
  interrupted ping resumes from the first un-ledgered URL on the next run.
- `_sitemap-seen.json` is updated **only after** the batch fully succeeds, so a
  mid-run failure leaves the diff intact for a clean retry.

### 6.4 Smart retry / backoff

- `429`/network → transient, exponential backoff (reuse the
  `_PROPAGATION_INTERVALS_S` pattern from `gsc_admin`). `4xx`-permanent (bad key,
  malformed) → `error`, operator action. Mirrors how CHECK_057/150 fixers treat
  transient-vs-permanent remote failures.

### 6.5 Quota awareness (status checks)

- The `index-regression` / CHECK_147 inspections respect the
  2,000/day-per-property ceiling: cap per-run inspections, prefer the cached
  `data/gsc/<domain>/<date>.json` snapshot, and surface what was skipped (no
  silent truncation). The check reads the latest snapshot by default; a live
  re-inspect is the explicit "spend quota now" path (e.g. a `--refresh`-style
  flag on `fleet check`, reusing CHECK_147's existing cache-or-fetch logic).

---

## 7. Sequencing — what to build first, optional, deferred

Framed as check/fix shipping units (a future `vN` tier; phases `vN.A…`).

**Phase A — kickoff + `[index]` table + `indexnow-key-present` check & fix.**
Lock decisions, add the additive-optional `[index]` table to `lamill_toml.py`,
write the key-provisioning helper (key-gen + `public/<key>.txt` + `set_table`),
ship CHECK `indexnow-key-present` with its `fix_tier_1`. After this, `fleet fix
--apply` backfills key files across the whole fleet. Zero new auth, zero new CLI.

**Phase B — sitemap-diff + IndexNow POST client.**
`_sitemap-seen.json` + `new_or_changed` computation; the IndexNow POST client
(httpx + MockTransport tests, ledger writer). No check yet — just the reusable
ping helper. Feeds Phase C and the deploy hook.

**Phase C — `indexnow-submitted` check & fix.**
The check (sitemap-diff vs ledger) + its remote-side-effect `fix_tier_1` (the
Phase B helper), `warn`-severity, ledger-gated. Now `fleet fix --apply` pings new
URLs fleetwide — the autopilot. This is the second backfill pass.

**Phase D — `new deploy` Step 10 hook.**
Deploy calls the Phase B ping helper after GSC Step 9, soft-fail; `new bootstrap`
calls the Phase A provisioning helper. New sites born compliant + pinged on
publish.

**Phase E — `index-regression` check + dashboard columns.**
Snapshot-diff over URL Inspection (`INDEXED → NOT_INDEXED`, `NOT_FOUND`),
`fail`-severity, no fixer; indexed-vs-pending rollup columns on `fleet check` /
dashboard fed by CHECK_147 snapshots.

**Deferred / opt-in only — Google Indexing API.**
Not in the default build. If ever revisited: service-account auth path,
`indexing` scope, single-project (no rotation), and *only* gated behind an
explicit `[index] google_indexing = true`. Document the JobPosting/BroadcastEvent
restriction at the call site. Resurface only if (a) Google opens the API for
general URLs, or (b) the operator has an actual JobPosting/livestream site.

**Non-goal reminder:** this overlaps the operator's separate SEO-pipeline
project's territory (see the v17/v21 drops + `docs/for-seo-check-improvements.md`).
The portfolio-side framing that justifies it: **lifecycle orchestration at deploy
time** (provision key, ping on publish, track status fleetwide) — the same
bootstrap-orchestration pattern that justified GSC/GA4 provisioning. Pure
analytics consumption stays out.

---

## 8. References

- Existing code: `gsc.py` (auth/scopes), `gsc_recrawl.py:inspect_one_url`
  (URL Inspection), `gsc_admin.py:submit_sitemap` (sitemaps),
  `_deploy_step9_gsc` in `cli.py` (deploy GSC step), `gsc_detail_cache.py`
  (per-domain snapshot pattern), `apikeys.py` (`portfolio.env` / `get_key`),
  `lamill_toml_edit.py` (additive-optional upsert, ADR-0018).
- IndexNow: <https://www.indexnow.org/documentation>,
  <https://www.indexnow.org/searchengines>
- Google Indexing API: <https://developers.google.com/search/apis/indexing-api/v3/quickstart>,
  <https://developers.google.com/search/apis/indexing-api/v3/core-errors>
- GSC URL Inspection API: <https://developers.google.com/webmaster-tools/v1/urlInspection.index/inspect>,
  usage limits <https://developers.google.com/webmaster-tools/limits>
