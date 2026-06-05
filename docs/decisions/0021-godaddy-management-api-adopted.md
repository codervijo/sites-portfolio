# 0021 — GoDaddy Management API adopted for inventory (supersedes the manual-CSV deferral)

- **Status:** Accepted
- **Date:** 2026-06-05

## Context

For most of the project, GoDaddy was treated as **manual-CSV-only**:
`fleet sync --refresh` pulls Porkbun live but leaves GoDaddy to a
hand-exported `data/domains/godaddy.csv`, and `architecture.md § Provider
API coverage` recorded GoDaddy as "Not API-driven." The stated reason had
hardened into "GoDaddy has no API."

That reason is **wrong**. GoDaddy has a Domains API
(`https://api.godaddy.com`), and after the 2024 access-policy change its
**Management + DNS APIs are available to accounts with 1+ domains** (the
threshold dropped from 10 to 1). Only the *Availability*/search API still
requires 50+ domains or ~$20/mo spend. The operator's **44 GoDaddy domains**
(of 68 fleet) qualify for Management outright.

The cost of the wrong premise is real and recurring: GoDaddy inventory goes
stale between manual exports, which produced the 2026-05-19 thoralox.com
expiry bug, the 2026-06-05 iotnews/nosapta deletion-revert (v34), and the
lamill.us/lamillrentals.com refresh friction — each patched separately.

## Decision

**Adopt the GoDaddy Management API as a first-class inventory source,
reversing the "GoDaddy not API-driven" deferral.**

- A new `godaddy.py` httpx-direct client (matching `cloudflare.py` /
  `gh_repo.py`), `sso-key <KEY>:<SECRET>` auth against `api.godaddy.com`,
  `httpx.MockTransport` tests. `list_domains()` + `get_domain()` (details
  incl. `nameServers` / `renewAuto` / `expires` / `status`).
- **Management API only.** We use list + per-domain detail (and, in v31.C,
  nameserver writes). We deliberately do **not** touch the Availability
  /search API, so the 50-domain Availability gate never applies — buying
  stays on Porkbun (the existing default registrar).
- Credentials `GODADDY_API_KEY` + `GODADDY_API_SECRET` join `KNOWN_KEYS`
  with an `apikeys` connectivity probe (`GET /v1/domains?limit=1`).
- The data still **materializes to `data/domains/godaddy.csv`** in today's
  shape (v31.B), so `cleanup()` / classification / every consumer is
  unchanged — only *how the CSV is produced* changes (API vs hand-export),
  exactly like the v15.F Porkbun refresh.

## Consequences

- **The manual-CSV treadmill ends for 44/68 domains.** `fleet sync
  --refresh` (v31.B) auto-refreshes GoDaddy expiry/status/NS, retiring the
  staleness class instead of patching each symptom.
- **A new credential pair + provider dependency enters the tool.** Soft-
  fail when absent (warn, keep the existing CSV), like the Porkbun path.
- **Complementary to v34 (overrides), not redundant.** The API refreshes
  registrar-truth fields (expiry/status/auto_renew/NS); v34's overrides
  layer still owns curated intent the API can't carry (e.g. category =
  "To be deleted immediately"). API for facts, overrides for curation.
- **`architecture.md § Provider API coverage` must be corrected** (GoDaddy
  → API-driven) — done in v31.D; the "GoDaddy has no API" framing is
  retired here as the record of why.

## See also

- `docs/prd.md § v31` — phases + design notes
- `src/portfolio/godaddy.py`, `src/portfolio/apikeys.py`
- GoDaddy API access policy: <https://www.godaddy.com/help/how-do-i-access-domain-related-apis-42424>
- ADR-0024 (v34) — curated overrides (the complementary curation layer)
