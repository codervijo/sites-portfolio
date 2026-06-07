# 0024 — Provider HTTP clients share one lifecycle helper and one transient/permanent error taxonomy

- **Status:** Accepted
- **Date:** 2026-06-06

## Context

lamill talks to seven-plus HTTP APIs (Cloudflare, Vercel, GoDaddy, GA4,
GSC, Porkbun, SerpAPI/OpenAI, GitHub, IndexNow). Each client module grew
independently and re-implemented the same two things:

1. **Client lifecycle.** A *build-or-reuse* client with a *close-only-if-owned*
   dance — `own = client is None; c = ...; try: ... finally: if own: c.close()`
   — repeated ~45 times across the clients (25× in `cloudflare.py` alone), with
   subtly different spellings (`(client, owned)` tuple in `godaddy`, a separate
   `own_client = client is None` in `cloudflare`/`vercel`).

2. **"Is this failure retryable?"** Encoded six different ways: a
   `CloudflareTransientError` class, a `{429, 5xx}` frozenset in `serp.py`, a
   `GTrendsRateLimitError`, an IndexNow permanent-vs-429 split, a
   `"temporary" | "permanent"` *string* in `porkbun_dns.py`, an inline `429`
   check in `godaddy.py`. Most clients had *no* transient notion at all and
   treated every failure as permanent.

The global CLAUDE.md rule "color-code transient (`↷`, retry) vs permanent
(`✗`, operator-action) failures" is only enforceable if there is one place
that decides which is which. Today it is CF-only; every other client flattens
the distinction, so a rate-limit reads identically to a bad credential.

This is the H4 + H7 finding of the v35.A tech-debt audit register.

## Decision

A single internal module `src/portfolio/_httpapi.py` owns both concerns, and
provider clients adopt it incrementally.

- **(a) Lifecycle — `managed_client(client, factory)` context manager.**
  Yields a caller-supplied client untouched (tests, connection reuse), or one
  built by `factory()` that is closed on `with`-exit, including on exception.
  Replaces the per-module close-dance. Clients keep a small `_build_client(...)`
  that just constructs the httpx.Client; ownership is no longer their concern.

- **(b) Taxonomy — `HttpApiError` ⊃ {`TransientHTTPError`, `PermanentHTTPError`}.**
  `HttpApiError` subclasses `RuntimeError`, so existing `except RuntimeError`
  and provider-specific handlers keep catching after adoption. The retryable
  set (`RETRYABLE_STATUSES = {429, 500, 502, 503, 504}`) lives here as the
  canonical source; `serp.py`'s OpenAI retry loop aliases it.

- **(c) Providers keep their typed error classes, reparented onto the taxonomy.**
  `XError(HttpApiError)` for the permanent default, plus
  `XTransientError(XError, TransientHTTPError)` for retryable cases. So
  `except XError` (provider-specific) **and** `except TransientHTTPError`
  (fleet-wide) both work. CF already had this exact shape
  (`CloudflareTransientError(CloudflareAPIError)`); it is now also a
  `TransientHTTPError`.

- **(d) Helpers, not a base class.** `raise_for(resp, what, *, transient_cls,
  permanent_cls)` and `status_is_transient` / `classify_status` /
  `transient_network_errors` are free functions / context managers, matching the
  codebase's functional-module style. No `ApiClient` base class — that would
  fight the per-provider auth/envelope differences (CF wraps `{success,
  errors}`; Vercel/GoDaddy use HTTP status + body) and impose inheritance where
  composition is cleaner.

Migration is incremental and behavior-preserving: a client is "migrated" when
it uses `managed_client` and its error classes subclass the taxonomy. Done so
far (v35.B): `godaddy`, `vercel`, plus `serp` sourcing the retryable set.
Remaining: `cloudflare`, `ga4_admin`, `gsc_admin` (and opportunistically
`gtrends`, `indexnow`, `porkbun_dns`).

## Consequences

- The `↷` vs `✗` operator color-code becomes enforceable across every migrated
  client, not just Cloudflare. A 429 anywhere can be caught as
  `TransientHTTPError` and reported as re-runnable (ADR-0015), not as a hard
  failure or a raw traceback.
- ~45 close-dance repetitions collapse to one context manager; new clients get
  correct lifecycle + taxonomy for free.
- The taxonomy is additive — an un-migrated client keeps working unchanged, so
  there is no fleetwide-migration treadmill (same posture as ADR-0017 for
  `lamill.toml`).
- Message text is preserved per client (each keeps its own `raise_for`/envelope
  wording); only the *class* of the raised error is centralized.

## Alternatives considered

- **A shared `ApiClient` base class.** Rejected — auth headers and error
  envelopes differ enough per provider that a base class accretes flags and
  overrides; the codebase is functional-module-shaped, and a context manager +
  helpers compose better than inheritance.
- **One universal `ProviderError`, drop per-provider classes.** Rejected —
  the provider-specific messages (GoDaddy's "production keys need 1+ domains",
  CF's `errors` array) carry real debugging value; reparenting keeps them while
  still giving the fleet-wide catch.
- **Big-bang migrate all clients in one change.** Rejected — `cloudflare.py` is
  deploy-critical (ADR-0015 idempotency) with the most call sites; isolating it
  to its own increment keeps the blast radius reviewable.
