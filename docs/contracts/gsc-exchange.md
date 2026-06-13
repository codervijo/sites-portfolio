# Contract: GSC Exchange v1 — lamill → rankmill

**Status:** Proposed (rankmill consumer side pending; lamill producer side = the hand-off below)
**Version:** `gsc-exchange-v1`
**Canonical home:** `sites/rankmill/docs/contracts/gsc-exchange.md` (rankmill repo).
**lamill MUST vendor a copy** at `sites/portfolio/docs/contracts/gsc-exchange.md` and keep it byte-identical; the version string in `schema` is the source of truth if they ever drift.
**Decision record:** rankmill ADR-0015. **Machine schema:** [`gsc-exchange.schema.json`](gsc-exchange.schema.json). **Golden example:** [`gsc-exchange.example.json`](gsc-exchange.example.json).

---

## 1. Why this exists

rankmill is the SEO **policy** brain (audits on-page state, decides fixes). It needs to know **Google's actual index reality** — "is this page indexed, and if not, why?" — to answer questions its on-page audit can't (e.g. "B-grade page, but Google says *Crawled — not indexed*: the problem is authority, not markup").

That data lives only in **Google Search Console**, and **lamill already owns the entire Google relationship**: GSC OAuth (`webmasters.readonly`), GA4 Admin, the URL-Inspection API, and quota management (`lamill settings gsc auth | recrawl | status`). It already writes per-domain inspection snapshots.

So: **lamill produces, rankmill consumes.** rankmill never gets Google credentials, never calls Google, and never duplicates lamill's integration. This preserves the division of labor (lamill = method/owns-creds; rankmill = policy/interprets) and keeps a single owner of the Google auth.

## 2. Roles & ownership

| | **lamill** (producer) | **rankmill** (consumer) |
|---|---|---|
| Owns | Google OAuth creds, GSC/GA4 API calls, quota, the data fetch | Reading the exchange file, interpreting, rendering, recommending |
| Writes | the exchange file | **nothing** (read-only against sites — rankmill ADR-0005) |
| Calls Google | yes | **never** |
| Trigger | runs the fetch (host, interactive OAuth) | **emits** the refresh command; never calls lamill directly |

## 3. The two flows

### 3a. Data exchange (lamill → rankmill) — file-based

lamill writes a JSON **exchange file** into the site directory it already owns:

```
sites/<domain>/.lamill/gsc.json
```

- rankmill reads it **read-only** through its existing per-domain Docker mount (`sites/<domain>` is already mounted `:ro` — rankmill ADR-0003). **No new mount, no launcher change, no cross-repo coupling.**
- `.lamill/` is lamill's namespace for consumer-facing data in a site repo (future: `.lamill/ga4.json`). lamill already writes into site dirs (`docs/growth.md`), so this is the established pattern.
- The file is the entire interface. Neither side imports the other's code.

### 3b. Refresh trigger (rankmill → lamill) — emit-based

rankmill runs inside a per-domain Docker container with no host access and no browser; lamill needs the host + interactive OAuth. So rankmill **cannot call lamill directly**. Instead — exactly like rankmill's fix delegation (ADR-0010) — when the exchange file is missing or stale, rankmill **prints the exact command** for the operator to run on the host:

```
↷ no fresh GSC data for donready.xyz — refresh it with:
    lamill settings gsc recrawl --site donready.xyz
  then re-run this command.
```

lamill runs host-side, (re)writes the exchange file; rankmill re-reads on the next run. A future direct call (rankmill `--apply`-style) is explicitly **out of scope** — emit is the contract.

## 4. The exchange file

**Path:** `sites/<domain>/.lamill/gsc.json` · **Encoding:** UTF-8 JSON · **Schema id:** `gsc-exchange-v1`

```json
{
  "schema": "gsc-exchange-v1",
  "domain": "donready.xyz",
  "property": "sc-domain:donready.xyz",
  "fetched_at": "2026-06-12T23:31:20Z",
  "source": "url-inspection",
  "error": null,
  "pages": [
    {
      "url": "https://donready.xyz/",
      "verdict": "PASS",
      "coverage_state": "Submitted and indexed",
      "indexing_state": "INDEXING_ALLOWED",
      "page_fetch_state": "SUCCESSFUL",
      "last_crawl_time": "2026-06-11T08:22:00Z",
      "error": null
    }
  ]
}
```

### Field semantics

| Field | Req | Notes |
|---|---|---|
| `schema` | ✓ | Const `"gsc-exchange-v1"`. The major (`v1`) is the compatibility key. |
| `domain` | ✓ | Bare domain; **MUST equal the site dir name** (rankmill rejects a mismatch). |
| `property` | ✓ | GSC property used (`sc-domain:…` or URL-prefix) — provenance. |
| `fetched_at` | ✓ | UTC ISO-8601 with `Z`. Drives freshness. |
| `source` | ✓ | Enum; v1 = `"url-inspection"`. |
| `error` | – | Top-level string when the whole pull failed (e.g. not a verified property). Then `pages` MAY be empty. |
| `pages[]` | ✓ | One record per inspected URL. **MAY be empty** (a degrade, never an error to the consumer). |
| `pages[].url` | ✓ | Absolute https URL. |
| `pages[].verdict` | ✓ | `PASS \| PARTIAL \| FAIL \| NEUTRAL`. |
| `pages[].coverage_state` | ✓ | GSC's human string (see schema for the common set). **Open string** — consumer handles unknown values gracefully. |
| `pages[].indexing_state` | – | e.g. `INDEXING_ALLOWED`, `BLOCKED_BY_META_TAG`, … (nullable). |
| `pages[].page_fetch_state` | – | e.g. `SUCCESSFUL`, `SOFT_404`, `NOT_FOUND`, … (nullable). |
| `pages[].last_crawl_time` | – | UTC ISO-8601 or `null` (never crawled). |
| `pages[].error` | – | Per-URL inspection error or `null`. |

### Versioning & change protocol

- `schema` = `gsc-exchange-v<major>`. **Additive** fields (new optional keys) stay within the same major — the consumer ignores unknown fields (forward-compatible).
- A **breaking** change (rename/remove/retype a required field, change an enum's meaning) = a **new major**. Both sides update together; the consumer MUST reject an unrecognized major and degrade (R2 below), never mis-parse.
- This doc + `gsc-exchange.schema.json` are bumped together; the example file is updated to validate against the new schema.

## 5. Producer (lamill) — responsibilities & conformance checks

**Hand this section to lamill's Claude Code.** lamill already computes the data (internal `v16c_inspections` from `gsc recrawl`); the work is a **mapping + a guarded write**, not new plumbing.

### Deliverables

- **P1.** On `lamill settings gsc recrawl --site <domain>` (and/or a dedicated `lamill settings gsc export --site <domain>`), in addition to the existing report, **write `sites/<domain>/.lamill/gsc.json`** conforming to `gsc-exchange-v1`.
- **P2.** Map internal `v16c_inspections[]` → contract `pages[]`: `url → url`, `verdict → verdict`, `coverage_state → coverage_state`, `indexing_state → indexing_state`, `page_fetch_state → page_fetch_state`, `last_crawl_time → last_crawl_time`, `error → error`. (Same field names already; the contract just fixes them as the public interface, decoupled from `v16cinspections` internal naming.)
- **P3.** Set `schema`, `domain` (= `--site`), `property` (the GSC property used), `fetched_at` (UTC now, `Z`), `source` = `"url-inspection"`.
- **P4.** **Atomic write** — temp file + rename — so a crash never leaves a partial `gsc.json`.
- **P5.** Add `.lamill/` to the site repo's `.gitignore` (transient, refreshed per crawl — not committed).
- **P6.** **Not-a-property / no-data is not a crash:** if `<domain>` isn't a verified GSC property, write **no file** (and keep the existing clear `recrawl` error). Optionally write a file with `error` set + `pages: []`. Either way rankmill degrades cleanly.

### Producer conformance checks (lamill MUST self-verify)

| ID | Check |
|---|---|
| **L1** | The written file validates against `gsc-exchange.schema.json`. |
| **L2** | `schema == "gsc-exchange-v1"` and `domain == <--site>`. |
| **L3** | `fetched_at` is UTC ISO-8601 ending in `Z`. |
| **L4** | Every `pages[].url` is an absolute `https://` URL on `<domain>`. |
| **L5** | Write is atomic (no reader can observe a partial file). |

**Producer test (required):** a unit test that feeds a known set of inspections and asserts the emitted `gsc.json` **validates against `gsc-exchange.schema.json`** and round-trips L2–L4. Vendor `gsc-exchange.schema.json` into the lamill repo for this test.

## 6. Consumer (rankmill) — responsibilities & conformance checks

### Deliverables

- **C1.** Read `sites/<domain>/.lamill/gsc.json` **read-only** (never write/refresh it).
- **C2.** Join: match each audited/crawled page URL → its `pages[]` entry (normalize trailing slash + scheme) and surface `coverage_state`/`verdict` next to the on-page grade. Audit pages absent from `pages[]` → render `not inspected`.
- **C3.** When data is missing or stale, **emit** the `lamill settings gsc recrawl --site <domain>` line (flow 3b) — never crash, never call Google.

### Consumer conformance checks (rankmill MUST verify on read)

| ID | Check | On failure |
|---|---|---|
| **R1** | File present? | Absent → degrade: "no GSC data" + emit refresh command. |
| **R2** | Parses as JSON and `schema` major is supported (`v1`)? | Unknown major → degrade: "GSC exchange schema unsupported — upgrade rankmill". |
| **R3** | Required fields present (validate against schema); unknown extra fields tolerated. | Malformed → degrade + name the offending field. |
| **R4** | `domain` equals the audited domain. | Mismatch → refuse this file (wrong site). |
| **R5** | Freshness: age from `fetched_at` ≤ `GSC_STALE_DAYS` (default 7). | Stale → still use it, flag `↷ GSC data N days old — refresh with lamill settings gsc recrawl`. |

**Consumer test (required):** golden-fixture tests against `gsc-exchange.example.json` asserting parse + join + the R1/R2/R5 degrade paths (missing file, bad-major schema, stale `fetched_at`).

## 7. Failure / degrade matrix (both sides)

| Condition | lamill (producer) | rankmill (consumer) |
|---|---|---|
| `<domain>` not a verified GSC property | clear `recrawl` error; **no exchange file** (P6) | file absent → degrade + emit refresh cmd (R1) |
| OAuth expired | `recrawl` tells operator to run `gsc auth` | sees stale/absent file → emit refresh cmd |
| One URL's inspection failed | that `pages[].error` set, `verdict` reflects it | render the per-URL error; rest of report unaffected |
| Schema major bumped, consumer old | writes new major | rejects unknown major, degrades (R2) |
| File older than `GSC_STALE_DAYS` | (re-run refreshes) | uses it, flags the age (R5) |
| `pages: []` (no URLs / all unknown) | valid file | "no GSC coverage yet" — not an error |

## 8. Worked example (the donready.xyz case this contract was born from)

`gsc-exchange.example.json` is real data lamill pulled on 2026-06-12. rankmill, joining it to its 6-page audit, would report:

```
GSC index state (fetched 2026-06-12, 0d old)
  ✅ /                       Submitted and indexed
  ⚪ /figs-vs-mandala/       Crawled - currently not indexed   → authority/content, not markup
  ⚪ /best-scrubs/           URL is unknown to Google          → submit sitemap; discovery gap
  ⚪ /compare/               URL is unknown to Google
  ⚪ /dress-code-checker/    URL is unknown to Google
  ⚪ /scrub-fit-quiz/        URL is unknown to Google
```

— the one view that answers "why isn't Google showing this site" without three separate tools.
