# 0025 — lamill is the producer of the GSC Exchange v1 file contract

- **Status:** Accepted
- **Date:** 2026-06-13

## Context

`rankmill` (the sibling SEO-policy CLI) needs Google Search Console
per-URL index state — "is this page indexed, and if not why?" — to
answer questions its on-page audit can't ("B-grade page, but Google says
*Crawled — not indexed*: the problem is authority, not markup").

That data lives only in GSC, and **lamill already owns the entire Google
relationship**: GSC OAuth (`webmasters.readonly`), the URL-Inspection
API, quota management, and the per-domain inspection snapshots written by
`settings gsc recrawl` (`UrlInspection` / `data/gsc/<domain>/`). rankmill
runs read-only inside a per-domain Docker sandbox with no host access and
no Google credentials (rankmill ADR-0003/0005).

The two repos agreed a **versioned file contract**, `gsc-exchange-v1`
(canonical: `sites/rankmill/docs/contracts/gsc-exchange.md`, rankmill
ADR-0015): lamill writes a small JSON file per domain; rankmill reads it.
This ADR records **lamill's side** (the producer).

## Decision

1. **lamill produces, rankmill consumes; the file is the entire
   interface.** Neither side imports the other's code. lamill writes
   `sites/<domain>/.lamill/gsc.json`; rankmill reads it read-only through
   its existing `sites/<domain>:ro` mount. rankmill never gets Google
   credentials and never calls Google.

2. **Write on a successful `settings gsc recrawl --site <domain>`.** The
   data is the `UrlInspection` set `run_recrawl` already computes — this
   is a **mapping + a guarded write**, not new plumbing. `v16c`-style
   `UrlInspection` fields map 1:1 to `pages[]` (the internal `status`
   field is dropped); the envelope adds `schema` / `domain` / `property`
   / `fetched_at` (UTC `Z`) / `source` (`"url-inspection"`) / `error`.

3. **Atomic write** (temp file + `os.replace`) so a crash never leaves a
   partial file a reader could observe (contract L5).

4. **`.lamill/` is gitignored per site** — the file is transient,
   refreshed per crawl, never committed.

5. **No-data is a degrade, not a crash (P6):** if the domain isn't a
   verified GSC property, `run_recrawl` raises and the command exits with
   its existing clear error — **no exchange file is written**. rankmill
   sees the absent file and emits its refresh hint.

6. **Vendoring:** lamill keeps byte-identical copies of
   `gsc-exchange.md` + `gsc-exchange.schema.json` under
   `docs/contracts/`; the producer test validates emitted files against
   the vendored schema. The `schema` version string is the source of
   truth if the copies ever drift.

The producer code is `gsc_recrawl.py` (`build_exchange_payload` /
`write_exchange_file` / `ensure_lamill_gitignored` / `export_exchange_file`),
wired into the `settings gsc recrawl` CLI command.

## Consequences

- A fourth lamill→site write surface, but a narrow one: a single
  transient, gitignored JSON file in lamill's own `.lamill/` namespace
  (alongside the established `docs/growth.md` write). It does not touch
  committed site content.
- rankmill gains GSC index reality with zero Google integration of its
  own — the division of labor (lamill = method/owns-creds; rankmill =
  policy/interprets) holds, with one owner of the Google auth.
- Schema evolution is governed by the contract's major-version rule:
  additive fields stay within `v1` (consumer ignores unknown keys); a
  breaking change is a new major both sides adopt together. The vendored
  copies + schema must be bumped in lockstep with rankmill.
- A future direct rankmill→lamill refresh call is explicitly out of
  scope — the emit-the-command flow (contract §3b) is the trigger
  contract.
