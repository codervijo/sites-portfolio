# 0027 — Apex stays canonical, but `www` is required and permanently redirects to it (no more absent-www)

- **Status:** Accepted
- **Date:** 2026-07-16
- **Supersedes:** — (formalizes + tightens the previously doc-only
  `🔒 apex-canonical` locked shape in `docs/CLAUDE.md`; the "v26.F formal
  lock pending" note is discharged here)

## Context

The fleet standard is **apex-canonical**: the bare apex (`example.com`) is
the one canonical host, and `www` / `http` variants permanently redirect to
it. That shape has been enforced by `CHECK_150 apex-canonical-redirect`
(`error` severity since 2026-06-13) and lived as a locked target shape in
`docs/CLAUDE.md`, but was never promoted to an ADR.

BUG-087 (2026-07-15) exposed a hole in how "apex-canonical" was implemented.
The latest `fleet check` snapshot showed **34 of 51 CF domains are bare-apex
only** — their `www` variant is `dead` / `ssl-broken` / absent, i.e.
`www.<domain>` returns **NXDOMAIN**. Only 15 have a working `www`. The fleet
is both **broken** (a user, inbound link, or email tool hitting `www.` gets
nothing — not a redirect) and **inconsistent** (34 apex-only vs 15 with www).

The root cause is a design allowance in `CHECK_150` itself: Rule 2 treats
**"no www (NXDOMAIN / connrefused) = pass"**, on the documented reasoning
that apex-only is "the common case for CF Pages sites without a www DNS
record." That conflated two different things — *`www` is canonical* (never
allowed) with *`www` doesn't exist* (silently allowed). Absent-www is **not**
apex-canonical; it is broken-www that happens not to split ranking signals
because there is no second host to split to.

Two facts made this a real (not cosmetic) gap:

- The current CF fixer (`_apply_cf_always_use_https`) only flips the zone
  `always_use_https` toggle. It has **zero** www-provisioning capability.
- `cloudflare.py` has DNS create/delete and custom-domain attach, but **no
  redirect-rule mechanism at all** — so there is currently no code path that
  can make `www` *redirect* rather than *serve* or *not exist*.

## Decision

**Apex remains the sole canonical host — this is not reversed. But `www` is
now *required* to exist and to permanently (301/308) redirect to the apex,
fleet-wide. Absent-www (NXDOMAIN) is no longer conformant.**

The universal target state for every fleet domain is exactly:

```
https://<apex>/          → 200            (apex is canonical)
https://www.<apex>/      → 301 → https://<apex>/
http://<apex>/           → 301 → https://<apex>/
```

Applied *universally*: the 34 NXDOMAIN sites get a `www` record + redirect
created; any of the 15 with a live `www` that currently serves `200` (a
second canonical) get `www` converted to a redirect. One shape, all 51.

Concrete commitments:

- **(a) `CHECK_150` tightens — but the flip lands LAST (fix-first,
  enforce-last).** Rule 2's `www.status is None → pass` becomes `→ fail`;
  `www` must resolve and 301/308→apex; severity stays `error`. Flipping it
  the moment the fixer lands would turn ~33 sites 🔴 before they're
  backfilled — expected red, not actionable-in-the-moment. So the order is
  capability → fixer → deploy → **gated backfill (fleet goes green)** → *then*
  flip the check (v46.F). The check tightens only once the fleet is already
  conformant, so it surfaces genuine residual gaps, never a wall of expected
  red. The exact work-list is already known from the snapshot, so the red is
  not needed to *drive* the fix.

- **(b) Cloudflare mechanism: per-zone proxied `www` DNS record + a
  zone-level Single Redirect Rule.** For each zone: create a **proxied**
  `www` DNS record (reuse `create_dns_record`) so CF's edge terminates the
  request, then install a **Single Redirect Rule** via the Rulesets API
  (`http_request_dynamic_redirect` phase) matching
  `http.host == "www.<apex>"` → `concat("https://<apex>", http.request.uri.path)`,
  status **301**, preserve query string. This is a net-new `cloudflare.py`
  capability (`ensure_www_redirect` over a get-or-create ruleset helper),
  written GET-then-PUT / idempotent per the existing CF-fixer pattern.

  **Chosen over** an account-level Bulk Redirect list because a per-zone rule
  makes each zone a **self-contained, idempotent unit** for both `fleet fix`
  backfill and `new deploy` — one domain = one reasoning unit — and mirrors
  how the existing Vercel fixer branch already provisions `www→apex`
  per-project. A single fleet-global Bulk Redirect object is harder to reason
  about per-site and still needs the per-zone proxied `www` DNS record
  anyway. (Status code **301** per operator; `CHECK_150` accepts `{301, 308}`
  and the `http→https` upgrade already emits 301, so 301 is consistent
  fleet-wide.)

- **(c) `new deploy` births sites conformant.** `_deploy_cf_unified` gains
  the same www-record + redirect step, idempotent per **ADR-0015** (probe
  before act; "already exists" → no-op). New sites never enter the fleet in
  the broken-www state.

- **(d) Rollout is gated, never auto-run.** Backfilling the 34 live zones is
  an outward-facing write on production DNS + redirect config. It runs as a
  `fleet fix` backfill: **dry-run first → operator reviews the diff →
  explicit go.** No auto-apply.

- **(e) Scope + exclusions: live apex sites only; parked/archived/dark are
  out.** The mandate fires only where the apex is a live `200` — if there's
  no served apex, there's nothing to redirect *to*. Parked / archived / dark
  sites are excluded via the **existing `fleet fix` skip seams**
  (`[fleet] dark_sites` + archived category); **v46 adds no new exclusion
  list.** Concretely, the three broken outliers from the snapshot are out:
  `lamill.us` (apex 404) and `virtually.co.in` (apex SSL-broken) self-exclude
  under the apex-must-be-200 rule; `lamillrentals.com` (apex 200, www broken,
  parked) is excluded explicitly via `dark_sites`.

Non-CF platforms are unchanged: the Vercel branch already does `www→apex`
308; HostGator / `custom` remain manual-hint until a platform fixer is
written.

**Real fleet state (for the record).** The BUG-087 "34 apex-only" figure was
loose. Of the 51 CF domains: **33** genuinely have no `www` (NXDOMAIN — the
true "no www" set), **11** already redirect `www→apex` (already conformant;
one of them is the reference for the v46.B rule shape), **4** serve `www` as
a second `200` (already fail today → convert to redirect), and **3** have a
`www` record with broken SSL (the parked outliers, excluded).

## Consequences

- **The `🔒 apex-canonical` locked shape tightens** from "www optional /
  absent OK" to "www required, 301/308→apex." `docs/CLAUDE.md § Locked
  target shapes` and agent memory (`project_apex_canonical_locked`) update to
  match. This is the formal lock the "v26.F pending" note referred to — now
  an ADR, not a doc-only convention.
- **A net-new `cloudflare.py` capability** (Rulesets-API redirect-rule
  provisioning) enters the codebase. Reads are cheap; the rule + DNS writes
  are opt-in (dry-run default in the fixer, idempotent in deploy).
- **No surprise-red window.** Because the check flip lands last (after the
  gated backfill greens the fleet), CHECK_150 never shows a wall of expected
  red. The ~33 in-scope NXDOMAIN sites are fixed *before* the rule tightens;
  the flip then catches only genuine residual gaps.
- **`www` becomes a maintained surface fleet-wide.** Every future zone
  carries a proxied `www` record + redirect rule; deploy and the fixer keep
  them in sync idempotently.
- **Secondary payoff:** absent/dead `www` was also a source of probe noise
  and false "site down" signals (see BUG-085's donready.xyz case); a
  redirecting `www` removes that class of noise.
- **Does not touch apex canonicality.** Markup/sitemap host-consistency
  (CHECK_158 / CHECK_159, apex-only) are unaffected — apex is still the only
  `<loc>` / `<link rel=canonical>` host. This ADR only closes the
  network-layer absent-www hole.

## See also

- `docs/prd.md § v46` — phases + design notes
- `docs/CLAUDE.md § Locked target shapes → 🔒 apex-canonical` — the tightened
  shape text
- ADR-0015 (`new deploy` idempotency + `--watch` opt-in) — the deploy-step
  and fixer idempotency posture the www provisioning inherits
- `src/portfolio/checks/seo/check_150_apex_canonical_redirect.py` (Rule 2 +
  the CF fixer branch), `src/portfolio/cloudflare.py` (new redirect-rule
  helper + `create_dns_record`), `src/portfolio/cli.py`
  (`_deploy_cf_unified`)
- CHECK_158 / CHECK_159 (apex-host markup + sitemap consistency — unchanged)
- `docs/bugs.md` — BUG-087 (this hole), BUG-085 (dead-www probe noise)
