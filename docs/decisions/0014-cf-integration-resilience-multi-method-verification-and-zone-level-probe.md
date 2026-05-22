# 0014 — Multi-method verification (HTML file before DNS TXT) + zone-level pre-flight probe pattern

- **Status:** Accepted
- **Date:** 2026-05-22

## Context

The deploy pipeline (`_deploy_cf_unified` in `cli.py`) has been
accumulating friction at two surfaces where the operator's
Cloudflare token permissions don't match what the pipeline needs:

  - **Step 5.5 (DNS purge)**: needs `DNS:Edit` on the specific zone
    to delete parking placeholders. Operator's `lamillio build
    token` has zone-scoped DNS:Edit on the established fleet zones
    but not on newly-created ones (CF's permission propagation,
    "Specific zones" scope gaps, or zones landing on a different
    CF account). Pre-v25 the pipeline 403'd mid-Step 5.5.
  - **Step 9 (GSC property + sitemap)**: needs `DNS:Edit` again to
    write the verification TXT record. Same root cause; same 403
    failure mode. Compounded by GCP-project-level "Site Verification
    API not enabled" issues which also surfaced as 403 but with a
    different fix path.

Both failures had to be addressed reactively (v15.R surfaced
dashboard URLs for manual completion; v15.S+ added per-step
`--skip-*` flags). Each fix improved the operator-action gate
clarity but didn't reduce the failure frequency.

v25 (kicked off 2026-05-22 PM after the dropaudit.co session)
addresses the **upstream pattern**: both failure modes can be
prevented by:

  1. Choosing verification methods that don't require the missing
     scope (e.g., HTML-file GSC verification doesn't need
     `DNS:Edit` at all — it works with any token having the
     `siteverification` scope, which the operator's already has).
  2. Surfacing the scope gap at the cheapest moment via a
     zone-level pre-flight probe, BEFORE the multi-step pipeline
     reaches the dependent write operations.

This ADR makes those two posture choices load-bearing for future
work.

## Decision

Two intertwined commitments.

### Multi-method verification for GSC (and future external services)

Where an external service offers **multiple ownership-verification
methods**, lamill prefers methods that don't require operator-side
permissions outside what lamill controls.

For GSC specifically:

  - **Primary**: `siteVerification.insert(method="FILE")`. lamill
    writes `<project_dir>/public/google<token>.html`, commits + pushes,
    waits for CF auto-deploy to make it reachable, then triggers
    Google's verification check. Works with any token having the
    `siteverification` OAuth scope (which the operator's already has)
    + DNS records already pointing at lamill-deployed infrastructure
    (which is the case post-Step-6).
  - **Fallback**: `siteVerification.insert(method="DNS_TXT")`.
    Requires `DNS:Edit` on the zone. Used only when the FILE method
    can't apply (e.g., projects that don't expose a buildable
    `public/` dir — currently no fleet members but possible for
    future HG-static or raw-PHP sites).

The choice is made automatically by `_deploy_step9_gsc`; operator
doesn't see method selection unless the FILE path soft-fails and
falls through to DNS TXT.

### Zone-level write capability probe at Step 3.5

After `cloudflare.ensure_zone` resolves or creates the zone, BEFORE
any subsequent pipeline step attempts DNS writes, lamill runs a
**read-cost / write-capability** probe specifically scoped to the
just-resolved zone:

  - The probe is a deliberately-invalid write attempt (e.g., POST
    with content guaranteed to 400 if writes were allowed) so the
    response distinguishes "token can write here" (400, payload
    rejected) from "token can't write here" (403). lamill never
    actually modifies state.
  - On `can_write=False`: surface clearly as an operator-action gate
    BEFORE Steps 5.5 + 9 attempt the dependent writes and fail in
    less-diagnostically-clear ways.
  - On `can_write=True`: log a short ✓ and proceed.

This pattern (post-resource-create, pre-resource-write, scope-
specific probe) generalizes to any future pipeline that creates a
resource then writes to it under separate permissions. Future
candidates: Workers Routes:Edit after Workers Service create;
GA4 stream creation after GA4 property create.

## Consequences

### Positive

  - **Reduces dropaudit.co-class failure modes.** Both Step 5.5 and
    Step 9 of the deploy pipeline used to 403 on the same root
    cause (token zone-scope gap). The HTML-file GSC path removes
    Step 9's dependency on DNS:Edit entirely; the Step 3.5 probe
    surfaces the gap once at the cheapest moment instead of twice
    in two distinct failure modes mid-pipeline.
  - **Operator gets a clear actionable gate** at one place (Step
    3.5) rather than two (Steps 5.5 + 9).
  - **Future external integrations can adopt the pattern.** Any new
    Google Admin API integration (GA4 enhancement, Indexing API
    re-evaluation per v21's resurface conditions, etc.) can use the
    same multi-method-preferred-first posture.
  - **ADR makes the decisions discoverable**. Future contributors
    auditing the code know the FILE-then-DNS_TXT ordering wasn't an
    accident; the zone-level probe at Step 3.5 isn't dead-cost.

### Negative

  - **HTML-file verification has a different latency profile.** The
    FILE method waits for CF to auto-deploy (typically 30-60s)
    before Google can verify. The DNS TXT method needs DNS
    propagation (5-30s on CF). Both are similar in practice; the
    FILE method may feel slower for operators watching the pipeline
    interactively.
  - **A junk `public/google<token>.html` file persists in the
    project's `public/` dir.** Standard SEO practice keeps it
    (Google re-checks ownership periodically; removal un-verifies).
    Operators reviewing the project's file tree see a hash-named
    file with no obvious purpose without inspecting its content.
    Mitigation: lamill writes a comment in the file body explaining
    its purpose + the date created.
  - **The zone-level probe adds one API call per deploy.** Cheap
    (~50-100ms typical CF API latency) but non-zero.

### Neutral

  - **The v15.N pre-flight probe at Step 0 stays intact.** v15.N
    catches generic token issues (token missing, expired,
    insufficient overall scope) before any zone is resolved. v25.B's
    Step 3.5 probe is additive — it catches the zone-specific gap
    that Step 0 can't see (because the zone doesn't exist yet).
  - **DNS TXT fallback path stays in code.** Reverting to the DNS
    method is one line of branch logic if HTML-file ever stops
    working or operator's deploy infrastructure changes shape.

## Alternatives considered

  - **Just fix the operator's CF token (v25.D check-token verb
    only, without HTML-file / zone-probe work).** Insufficient
    because it doesn't address future operators with similarly-
    misconfigured tokens; the resilience patterns generalize.
  - **Require operators to regenerate tokens with documented full
    scopes before first deploy.** Already partially required (v15.N
    probe gates on the basics). But token-permission UX gotchas
    will keep surfacing (CF changes permission group names; new
    operator setups discover gaps the hard way). Defense in depth:
    document + probe + use resilient methods anyway.
  - **Use Google Analytics-based GSC verification.** GSC supports
    "verify via the Analytics property attached to the same site."
    Would work for operators with v18.D-installed GA4 + same Google
    account. Doesn't generalize — requires GA4 install which not
    all operators want. HTML-file is the universal path.

## See also

  - **ADR-0011** — Remote write surfaces are a separate category
    (deploys to cPanel via UAPI). The v25 patterns also apply
    in spirit there: prefer methods that work with the operator's
    minimal-scope token; probe write capability before attempting
    writes; surface gaps cleanly.
  - **ADR-0012** — Unified CF Pages-API git-integrated deploy
    pipeline. v25 extends `_deploy_cf_unified` with the new Step 3.5
    probe + Step 9 HTML-file path.
  - `docs/prd.md § v25 — CF integration resilience` for the phase-
    level shipping plan.
