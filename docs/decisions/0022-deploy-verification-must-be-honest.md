# 0022 — Deploy verification must be honest: report only what was confirmed, never false-green

- **Status:** Accepted
- **Date:** 2026-06-05

## Context

`lamill new deploy <domain> --watch` reported `✓ fully live` for
**mdburst.com** while the apex was still a Porkbun URL-forward
(`302 → l.ink`) on Porkbun nameservers — the deployed site was not serving
at all. The same week, **scopeguard.xyz** sat in CF custom-domain
`pending-verification` / error `1014` with the watch loop unable to name
the state, eventually printing a generic timeout.

Three independent gaps let a deploy go green on a non-deployed apex:

1. **Live probe follows an off-domain redirect.** `_deploy_step8_live_probe`
   / `_deploy_watch_loop` follow a `302` to a parking/forwarder host
   (`l.ink`) and count the resulting `200` as live — `live_ok` even treats a
   bare `3xx` as success via `startswith("3")`.
2. **Registrar API state is mistaken for real delegation.** Step 4 trusts
   Porkbun `getNs` ("NS *stored* at the registrar") instead of `dig NS`
   ("NS *actually delegated*"). A domain pinned to Porkbun NS by **URL
   Forwarding** reads as `✓ already match` even though it never delegated to
   Cloudflare.
3. **No named state for CF `pending`/`1014`.** The watch loop has no way to
   distinguish a custom-domain pending-verification / `1014` from a generic
   timeout, so it can neither remediate nor report it.

The common theme across all three: **the pipeline claimed more than it
verified.** This is the inverse failure of ADR-0015 (which keeps the
pipeline non-blocking) — here the pipeline is non-blocking *and* dishonest,
painting unconfirmed state as success.

## Decision

**Deploy verification reports only the state it can actually confirm, names
the real blocker when it can't, and never paints a parked / forwarded /
pending apex as live.** "Live" means *this domain serves the deployed site
itself* — not "some host returned 200," not "the registrar stored our NS."

Concretely, the verification surfaces commit to four honesty rules:

- **(a) A live apex must serve the site itself.** A `3xx` whose final host's
  eTLD+1 differs from the domain — especially known parking/forwarder
  suffixes (`l.ink`, …) — is **not live**; report `↷ forwarded to <host>`.
  *Same-site* redirects (apex→www, http→https; same eTLD+1) stay live. Reuse
  `check.py:_classify()` (the existing eTLD+1-vs-final-host classifier),
  don't hand-roll redirect logic. Drop `startswith("3")` from `live_ok`.
- **(b) Registrar API ≠ delegation.** "NS set at the registrar" (`getNs`) and
  "NS actually delegated" (`dig NS`) are *distinct states*. Step 4 reports
  them separately (`requested` vs `delegated`) and never prints `✓ match`
  off the registrar API alone. The check is propagation-aware: a just-set
  domain whose `dig` still lags reads `↷ NS set, awaiting delegation`, not a
  false failure (ADR-0015 convergence posture).
- **(c) URL Forwarding is detected; cleared only on opt-in.** lamill reads
  Porkbun URL Forwarding (`getUrlForwarding`) and surfaces an active
  forward as the cutover blocker. A `--clear-forwarding` flag performs the
  registrar write (`deleteUrlForward`) — confirm-gated and idempotent, never
  silent.
- **(d) `pending`/`1014` is a named state.** The watch loop distinguishes CF
  custom-domain pending-verification / `1014` from a generic timeout,
  surfaces a distinct `✗ pending-verification` state + remediation, and a
  `--repair` path re-PATCHes the apex CNAME to the project's authoritative
  `subdomain` and re-adds the custom domain to re-verify.

All four honor the **ADR-0015 quick-idempotent invariant**: they *report*
state and let re-runs converge; they do not introduce new always-on blocking
waits. `--clear-forwarding` and `--repair` are explicit opt-in
registrar/CF writes (confirm-gated), consistent with the existing
remote-side-effect precedent (deploy Steps 4–9, CHECK fixers).

## Consequences

- **No more false-green deploys.** A forwarded / parked / pending apex
  reports the truth; the operator sees the real blocker (`forwarded to
  l.ink`, `awaiting delegation`, `URL Forwarding active`, `pending-
  verification`) instead of `✓ fully live`.
- **A second source of truth (`dig`) enters Step 4.** Delegation is read
  from DNS, not only the registrar API — `diagnose._dig()` is reused. This
  adds a resolver round-trip but is the only way to tell *stored* from
  *delegated*.
- **A net-new registrar capability (Porkbun URL Forwarding read/clear)**
  joins `porkbun_dns.py`. Reads are free; the clear write is opt-in only.
- **`--watch` semantics get stricter, not looser.** It can now end on a
  *named failure* (`pending-verification`) rather than only timeout/success,
  which is more honest but means some runs that previously timed out now
  exit with a specific `✗` state + remediation.
- **The honesty rule generalizes.** Future deploy steps inherit the posture:
  *report only confirmed state.* If a step can't verify an outcome, it says
  so (`↷ <unconfirmed state>`), it does not assume success.

## See also

- `docs/prd.md § v32` — phases + design notes
- ADR-0015 (`new deploy` idempotency + `--watch` opt-in) — the complementary
  invariant; v32 is non-blocking *and* honest
- `src/portfolio/cli.py` (`_deploy_step8_live_probe`, `_deploy_watch_loop`,
  Step 4 / Step 6.5), `src/portfolio/check.py` (`_classify`,
  `PARKED_HOST_SUFFIXES`), `src/portfolio/diagnose.py` (`_dig`),
  `src/portfolio/porkbun_dns.py` (URL-forwarding read/clear)
- `docs/bugs.md` — 2026-06-05 ×2 (mdburst false-green, Astro sitemap) +
  2026-05-31 (scopeguard `1014`)
