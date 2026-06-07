"""v35.B — shared httpx client lifecycle + transient/permanent error taxonomy.

Every provider client (`cloudflare`, `vercel`, `godaddy`, `ga4_admin`,
`gsc_admin`, ...) re-implemented the same two things:

  1. A build-or-reuse client with a *close-only-if-owned* dance
     (``own = client is None; c = ...; try: ... finally: if own: c.close()``).
  2. An ad-hoc "is this failure retryable?" decision, encoded six different
     ways (a `CloudflareTransientError` here, a `{429, 5xx}` frozenset there,
     a ``"temporary" | "permanent"`` string elsewhere).

This module is the single home for both, so the operator-facing distinction —
``↷`` (transient, safe to retry / re-run per ADR-0015) vs ``✗`` (permanent,
operator-action-needed) — is consistent fleet-wide instead of drifting per
client. See ADR-0024.

Providers keep their own typed error classes for message clarity, but those
classes subclass the taxonomy here, so a caller can ``except TransientHTTPError``
across any provider while existing ``except <Provider>Error`` / ``except
RuntimeError`` handlers keep catching.
"""
from __future__ import annotations

from contextlib import contextmanager
from typing import Callable, Iterator

import httpx

# Retryable HTTP statuses: rate-limit + the standard transient 5xx family.
# Canonical source — `serp.py` and any future retry loop import this rather
# than redefining their own set.
RETRYABLE_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504})


class HttpApiError(RuntimeError):
    """Base for any provider HTTP API failure. Subclasses ``RuntimeError`` so
    existing ``except RuntimeError`` and provider-specific handlers still
    catch it after a client adopts the taxonomy."""


class TransientHTTPError(HttpApiError):
    """Retryable failure — rate-limit (429), transient 5xx, or a network-level
    timeout/transport error. Operator-facing: report ``↷`` + re-run (ADR-0015),
    never a hard ``✗``."""


class PermanentHTTPError(HttpApiError):
    """Operator-action-needed failure — auth / scope / bad-request / not-found.
    Operator-facing: report ``✗`` with a specific remediation."""


def status_is_transient(status: int) -> bool:
    """True when an HTTP status is in the retryable set (429 / 5xx family)."""
    return status in RETRYABLE_STATUSES


def classify_status(status: int) -> type[HttpApiError]:
    """Return the error *kind* for an HTTP status — `TransientHTTPError` for a
    retryable status, `PermanentHTTPError` otherwise."""
    return TransientHTTPError if status in RETRYABLE_STATUSES else PermanentHTTPError


@contextmanager
def managed_client(
    client: httpx.Client | None,
    factory: Callable[[], httpx.Client],
) -> Iterator[httpx.Client]:
    """Yield a client and close it iff this scope built it.

    Replaces the per-module ``own = client is None; c = ...; try: ... finally:
    if own: c.close()`` dance. A caller-supplied ``client`` (tests, connection
    reuse) is yielded untouched; otherwise ``factory()`` builds one that's
    closed on exit — including when the body raises."""
    if client is not None:
        yield client
        return
    built = factory()
    try:
        yield built
    finally:
        built.close()


@contextmanager
def transient_network_errors(what: str) -> Iterator[None]:
    """Map httpx network-level failures (timeout / transport error) to
    `TransientHTTPError`, so a flaky connection reads as ``↷``-retryable
    rather than a raw traceback escaping the client.

    HTTP *responses* (a 4xx/5xx that actually arrived) are handled by
    `raise_for` or a provider's envelope check — not here; this only catches
    failures where no response was received."""
    try:
        yield
    except (httpx.TimeoutException, httpx.TransportError) as e:
        raise TransientHTTPError(
            f"{what}: network error ({type(e).__name__}: {e})"
        ) from e


def raise_for(
    resp: httpx.Response,
    what: str,
    *,
    transient_cls: type[Exception] = TransientHTTPError,
    permanent_cls: type[Exception] = PermanentHTTPError,
    retryable: frozenset[int] = RETRYABLE_STATUSES,
    body_chars: int = 300,
) -> None:
    """Raise on a non-2xx response, choosing transient vs permanent by status.

    A 2xx returns silently. Providers pass their own typed classes (which
    subclass the taxonomy) so messages stay provider-specific while the
    transient/permanent split stays centralized. The response body is included
    (truncated to ``body_chars``) so debugging doesn't require log-spelunking —
    matches the existing per-client error messages."""
    if 200 <= resp.status_code < 300:
        return
    cls = transient_cls if resp.status_code in retryable else permanent_cls
    raise cls(f"{what}: HTTP {resp.status_code} {resp.text[:body_chars]}")
