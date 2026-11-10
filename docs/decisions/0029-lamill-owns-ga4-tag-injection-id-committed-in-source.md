# 0029 — lamill owns GA4 tag injection; the measurement ID is committed in site source

- **Status:** Accepted
- **Date:** 2026-11-09
- **Supersedes:** — (reverses the v18.A (a) scope decision "markup injection
  belongs to the SEO pipeline", which was never recorded as an ADR)

## Context

v18 (2026-05-21) split GA4 work in two: lamill creates the GA4 property at
bootstrap and writes the measurement ID to `lamill.toml [analytics] ga4_id`;
the SEO pipeline (rankmill) reads that ID and injects the tag into site code.

A fleet audit on 2026-11-08 found the split never produced a tagged site:

- GA4 was live on only 4 of ~50 sites, all hand-wired before v18.
- Six more sites had tag code reading `PUBLIC_GA_ID` / `VITE_GA_ID`, but the
  build env var was unset on the hosting platform, so nothing loaded.
- No `lamill.toml` had an `[analytics]` block. v18.D's bootstrap
  auto-create had skipped on every site because GA4 OAuth and
  `GA4_ACCOUNT_ID` were never configured.
- rankmill has only a detector (`check_240_analytics_present`); it never
  injected anything.

## Decision

1. **lamill owns GA4 end to end:** property creation, tag injection, and
   live verification. Injection is delivered as checks + fixers
   (CHECK_162–164) plus the `lamill fleet ga` rollout runner, consistent
   with the check+fix delivery preference.
2. **The measurement ID is committed in site source**, not supplied by a
   build-time env var. GA4 measurement IDs are public (they ship in every
   page), so there is nothing to hide; committing keeps the repo the
   source of truth, makes builds reproducible, and removes the per-platform
   dashboard state (Cloudflare Pages, Workers, Vercel) that left six sites
   silently untracked. Sites that already read `PUBLIC_GA_ID` / `VITE_GA_ID`
   get the committed ID as the default value.
3. **`lamill.toml [analytics] ga4_id` stays the per-site record** that the
   checks compare source and live HTML against.

## Consequences

- rankmill no longer needs a GA4 injection feature; its detector may stay.
- Changing a site's GA4 property means a code commit (by design: visible
  in history, deployed through the normal push path).
- One Google identity (`foundervijo@gmail.com`) and one OAuth client
  (`vijos-portfolio` project, shared with GSC) cover all sites; per-site
  separation is one GA4 property per site under the LaMill Sites account
  (per-client accounts for client-owned sites).

## Amendment — 2026-11-09 (v49.F)

Decision (g) of v49.A planned to consolidate pre-existing properties into
LaMill Sites with GA4's "Move property". The Admin API has no method for
that (checked v1beta + v1alpha discovery docs), so the operator chose a
**clean switch** instead: `lamill fleet ga --switch-old` gives each such
site a fresh LaMill Sites property, replaces the old ID in source, and
deletes hosting env vars that would override the committed ID. The old
properties keep their history, readable in their old accounts. Applied to
calcengine.site, civictools.app, keralavotemap.site, lamillrentals.com
and washcalc.app.
