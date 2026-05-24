# 0016 — GSC verification method ↔ property type are coupled; default to DNS_TXT + Domain

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

Google Search Console (GSC) supports two property types and several
verification methods, but they are **not freely combinable** — each
verification method only verifies one specific property type:

| Property type | URI form | Allowed verification methods |
|---|---|---|
| **URL-prefix** | `https://example.com/` | `FILE`, `META`, `DNS_TXT` |
| **Domain** | `sc-domain:example.com` | `DNS_TXT` or `DNS_CNAME` **only** |

Critically:

- **`FILE` method verifies the URL-prefix property** (and only that
  specific origin — `https://example.com/` is NOT the same property
  as `https://www.example.com/` or `http://example.com/`).
- **`DNS_TXT` method verifies the Domain property** (covers all
  variants — http/https, www/non-www, all subdomains).

Verifying one does NOT grant ownership of the other. Two distinct
records in GSC; two distinct ownership grants.

### How v25.A missed this

v25.A's decision (a) was "HTML-file verification FIRST in Step 9 …
The file-method path doesn't need `DNS:Edit` on the zone at all;
works with any token having the `siteverification` scope." This
captured the *mechanics* of the FILE API call but didn't account for
the property-type coupling — the rest of the GSC pipeline (`add_site`,
`submit_sitemap`) operates on **Domain properties** (`sc-domain:`)
per v24.A decision (c). FILE verification of the URL-prefix property
doesn't transfer to the Domain property.

### How the mismatch surfaced

Operator's permittruck.xyz Step 9 run (2026-05-23 PM, after re-consenting
OAuth + enabling the Site Verification API in GCP):

```
✓ wrote verification file: public/googlec9e24d5b10800113.html
✓ verification file reachable at https://permittruck.xyz/googlec9e24d5b10800113.html
✓ domain ownership verified by Google (FILE method — no DNS:Edit needed)
✓ sc-domain:permittruck.xyz already in GSC (no add)
✗ sitemaps.submit failed: HTTP 403 — "User does not have sufficient
   permission for site 'sc-domain:permittruck.xyz'."
```

The FILE verification *succeeded* (Google verified
`https://permittruck.xyz/` as a URL-prefix property), but
`submit_sitemap` operated on the Domain property which the operator
was NOT the verified owner of. 403 was Google's correct response.

### Why FILE-first was rationalized in v25.A

v25.A reasoned that FILE doesn't need `DNS:Edit` on the zone, so it
avoids the dropaudit.co failure pattern (token has Zone-scope DNS:Edit
"All zones" but the specific zone isn't in the token's account). That
reasoning was sound *if* FILE verified the Domain property — but it
doesn't.

### What changed since v25.A

v25.B shipped Step 3.5, a zone-level DNS:Edit pre-flight probe
(`cloudflare.probe_zone_write_capability`). Step 3.5 EXITS the
pipeline cleanly with `exit 8` if the token can't write DNS records
to the zone. So by the time Step 9 runs, `DNS:Edit` is GUARANTEED
available. The original "FILE-first to avoid DNS:Edit" rationale no
longer applies — DNS_TXT is always reachable.

## Decision

1. **Verification method MUST match property type.** Code must not
   mix-and-match. Specifically:
   - `DNS_TXT` method → use `INET_DOMAIN` site type + `sc-domain:<domain>`
     property URI for any downstream `add_site` / `submit_sitemap`.
   - `FILE` method → use `SITE` site type + `https://<domain>/` URL-prefix
     property URI for any downstream operations.
   - `_site_payload_for_method` in `gsc_admin.py` already builds the
     correct site payload per method; the constraint is now that
     callers must use the *same* property URI throughout the flow.

2. **Default to DNS_TXT + Domain property.** Since v25.B Step 3.5
   guarantees `DNS:Edit` is available when Step 9 runs, and Domain
   properties cover all URL variants (sc-domain wins over URL-prefix
   per v24.A reasoning), DNS_TXT + Domain is the standard path:
   - `gsc_admin.get_verification_token(method=)` defaults to `DNS_TXT`
   - `gsc_admin.verify_domain(method=)` defaults to `DNS_TXT`
   - `_deploy_step9_gsc` orchestration calls `_step9_dns_verify` first

3. **FILE method preserved as fallback.** The FILE-method helpers
   (`write_verification_file`, `wait_for_verification_file_live`,
   `_step9_file_verify`) stay in the codebase as a documented fallback
   path. In practice they are unreachable in the v15.I deploy
   pipeline (Step 3.5 short-circuits on no `DNS:Edit` before Step 9
   runs), but they:
   - Cover URL-prefix property workflows if a future tier needs them
   - Document the API mechanics for posterity
   - Provide a `--skip-step-3.5` opt-out path (hypothetical; not
     wired) where an operator could bypass DNS:Edit gating

## Consequences

**Positive:**
- Step 9 now actually works end-to-end on a fresh deploy: verify
  Domain property → add Domain property → submit sitemap on Domain
  property, all on the same property the operator owns.
- The property-type / method-type coupling is documented; future
  contributors won't make the same v25.A mistake.
- `add_site` and `submit_sitemap` semantics are consistent (they've
  always operated on `sc-domain:` per v24.A; now verification matches).
- Dropping FILE from the default path simplifies the orchestration
  in `_deploy_step9_gsc` (no need to navigate the structural-fallback
  branch in normal flow).

**Negative / accepted trade-offs:**
- Step 9 now requires `DNS:Edit` on the zone. This was an explicit
  constraint v25.A was trying to avoid; the trade-off is now: rely on
  v25.B Step 3.5 to gate this earlier (the gating is already there
  and works in production per the permittruck.xyz run).
- The FILE-method code becomes effectively dead in the deploy path.
  Kept for documentation / future use; small carrying cost.
- For domains where the operator wants to use URL-prefix properties
  (specific subdomain only), a future tier would need to wire FILE
  back into the orchestration with the matching property URI
  (`https://<domain>/`) used throughout `add_site` / `submit_sitemap`.

**Migration note for existing GSC state:**

If an operator's previous deploys ran the v25.A/C FILE-first flow and
verified the URL-prefix property, their `add_site`-added Domain
property may not be ownership-bound to them. They have two options:

1. Re-run `lamill new deploy <domain> --yes` with v25.F — this will
   run `DNS_TXT` verification, which grants Domain ownership; then
   `submit_sitemap` succeeds.
2. Manually verify the Domain property via DNS TXT in the GSC dashboard.

Both produce the same end-state.

## References

- Trigger: operator's permittruck.xyz Step 9 run 2026-05-23 PM,
  sitemap-submit 403 despite successful FILE verification.
- Related ADRs:
  - [ADR-0014](0014-cf-integration-resilience-multi-method-verification-and-zone-level-probe.md)
    — v25.A's multi-method verification + zone-level probe design
    (this ADR doesn't supersede 0014, but corrects its implementation).
  - [ADR-0015](0015-deploy-pipeline-must-remain-idempotent.md) — the
    idempotency invariant that applies to Step 9 just as much.
- v24.A decision (c) — `sc-domain:<domain>` Domain properties chosen
  as the canonical property type for deploys.
- Google Site Verification API docs: each method's verification scope
  (URL-prefix vs Domain) is documented in
  https://developers.google.com/site-verification/v1/getting_started.
