# 0030 — lamill manages per-site email routing (`hello@<site>` via Cloudflare Email Routing)

- **Status:** Accepted
- **Date:** 2026-11-25 (decisions taken 2026-11-10/11 in v50.A; built v50.B–G)
- **Supersedes:** —

## Context

A fleet audit on 2026-11-10 found that none of the 41 Cloudflare zones
could receive mail: no MX records, Email Routing `unconfigured`
everywhere. Every `mailto:` on a Cloudflare-hosted site bounced,
including `security@dropaudit.co`. A few domains already had mail
elsewhere: Zoho (lamill.io), Google Workspace (lamillrentals.com),
Namecheap eForward (six sites), HostGator's own mail (five sites) and
Proton (one client site).

Before v50, lamill never touched a site's mail. The operator asked for
it to (2026-11-10): use the Cloudflare Email Routing API, keep existing
mail setups, never overwrite MX on a domain that uses another provider,
make it reusable and idempotent, and give **every** operator-owned site
an address, not just the ones that already publish one.

## Decision

1. **lamill manages inbound mail routing for operator-owned sites.**
   Every such site gets `hello@<site>`, forwarded by Cloudflare Email
   Routing to `hello@lamill.io`. This applies to the whole fleet,
   existing sites included. Routing is receive-only; sending as the site
   is configured by the operator in the mailbox provider, outside lamill.
2. **Declaration: an optional `lamill.toml [email]` table**
   (additive-optional, ADR-0017), read raw with no schema change.
   `forward_to` overrides the destination. `addresses` adds local parts
   (e.g. `["security"]`); `hello` is always included.
3. **Existing mail is never touched.** A domain whose MX belongs to
   another provider is reported as "managed elsewhere" and left alone.
   lamill never replaces an apex SPF record that lacks Cloudflare's
   include; the operator merges it by hand. lamill never rewrites a rule
   that already forwards the address somewhere else. The catch-all is
   not touched: only explicit per-address rules are added.
4. **Scope:** client-owned sites are out of scope until the operator
   decides separately (see v50.A (b)). Dark sites, HostGator sites and
   archived dirs are n/a. If DNS isn't on Cloudflare, or the zone isn't
   `active`, lamill reports it and writes nothing.
5. **Delivery is check + fix, with no new verb.** CHECK_165
   `email-routing-ready` and its fixer (Cloudflare API, two passes around
   the destination's verification click) cover routing. CHECK_166
   `email-footer-link` and its fixer put a `mailto:` link in the shared
   footer. `fleet fix` rolls both out. `new deploy` runs the CHECK_165
   fixer as an idempotent step (ADR-0015): a pending zone gives `↷`
   "re-run when active" and never blocks. `new bootstrap` adds the footer
   link before the initial commit.
6. **Never publish an address that bounces.** On existing sites the
   footer fixer adds the link only once CHECK_165 is ✓, or once mail is
   on another provider and the source already uses an own-domain address.
   New sites get the link at bootstrap, because they aren't public until
   `new deploy` turns routing on.
7. **Source edits are build-gated.** Fixers that edit site source are
   marked `edits_source`. After `project fix` / `fleet fix --apply`, such
   a site builds in the container. If the build fails, the edited files
   are restored. Commit and push stay with the operator (ADR-0003
   unchanged).

## Consequences

- Delivery depends on one mailbox (`hello@lamill.io`, Zoho). Forwarded
  mail is SRS-rewritten by Cloudflare. Replies sent as `hello@<site>` are
  DMARC-unaligned. The operator accepted this in the v50.E pilot.
  Per-site DKIM is parked until replies start landing in spam.
- The Cloudflare token needs Email Routing edit scopes. Missing scopes
  surface as plain-words hints (`email_routing._PERM_HINT`).
- A new site's footer advertises `hello@` before routing is on. This is
  safe only because the site isn't public until `new deploy`, which turns
  routing on in the same run (or warns `↷` while the zone is pending).
- Contact forms that actually deliver (Workers `send_email` to verified
  destinations) can now be planned on top of this. They are out of v50.

## References

- `docs/prd.md § v50` (v50.A decisions, v50.E pilot)
- `src/portfolio/email_routing.py`, `checks/deploy/check_165_email_routing_ready.py`,
  `checks/deploy/check_166_email_footer_link.py`, `fix_build.py`
- ADR-0003 (write surfaces), ADR-0015 (deploy idempotency), ADR-0017
  (additive-optional `lamill.toml`), ADR-0020 (check+fix delivery
  precedent)
