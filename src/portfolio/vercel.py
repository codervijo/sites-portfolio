"""Vercel API write-side client for v26.D apex-canonical-redirect fixer.

Provides the helpers CHECK_150's `fix_tier_1` vercel branch needs:
locate the project that owns a domain, read each domain's current
redirect config, and PATCH/POST to flip apex to primary + configure
www→apex 308 redirect.

Read-side Vercel helpers used by `fleet hosting` live in `hosting.py`
under `_list_vercel_projects` etc. The two layers stay separate until
a deliberate refactor consolidates them (v26 doesn't take that on).

Auth pattern mirrors `cloudflare.py`:
  portfolio.env  VERCEL_TOKEN  ← API token (KNOWN_KEYS slot since v11.A)

Endpoints used:
  GET   /v9/projects?limit=100&until=…             — list projects (paginated; filter by domain attachment)
  GET   /v9/projects/{id}/domains/{name}           — read one domain's current config
  POST  /v10/projects/{id}/domains                 — add a domain to the project
  PATCH /v9/projects/{id}/domains/{name}           — update redirect / redirectStatusCode

"Primary domain" in Vercel-speak is implicit — whichever attached
domain has no `redirect` set serves as primary. To make apex primary
+ www 308→apex: ensure apex has redirect=None, www has
redirect="<apex>" + redirectStatusCode=308.
"""
from __future__ import annotations

from dataclasses import dataclass

import httpx

API_BASE = "https://api.vercel.com"
HTTP_TIMEOUT = 15.0


class MissingCredentialsError(RuntimeError):
    """VERCEL_TOKEN not set in portfolio.env."""


class VercelAPIError(RuntimeError):
    """Non-success response from Vercel."""


def _read_token() -> str:
    """Env-first token lookup via `apikeys.get_key`. Same posture as
    cloudflare.py — error surfaces the `lamill settings apikeys set`
    breadcrumb."""
    from . import apikeys

    token = (apikeys.get_key("VERCEL_TOKEN") or "").strip()
    if not token:
        raise MissingCredentialsError(
            "VERCEL_TOKEN not set in portfolio.env.\n"
            "  Get a token at https://vercel.com/account/tokens\n"
            "  (Full Account scope is sufficient for canonical-redirect "
            "fixes.)\n"
            "  Then run: lamill settings apikeys set VERCEL_TOKEN <value>"
        )
    return token


def _client(token: str | None = None, *,
            client: httpx.Client | None = None) -> httpx.Client:
    """Build an httpx.Client bound to the Vercel API with the token.
    Caller-injected clients pass through unchanged — tests inject
    MockTransport-wired clients here."""
    if client is not None:
        return client
    if token is None:
        token = _read_token()
    return httpx.Client(
        base_url=API_BASE,
        timeout=HTTP_TIMEOUT,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
    )


def _raise_for_status(resp: httpx.Response, verb_url: str) -> None:
    """Common error path — surface non-2xx with the API's error body
    so debugging doesn't require log-spelunking."""
    if 200 <= resp.status_code < 300:
        return
    raise VercelAPIError(
        f"{verb_url} → HTTP {resp.status_code}: {resp.text[:400]}"
    )


# ---------- domain → project lookup ----------


@dataclass
class ProjectRef:
    """Minimal project identity captured during the
    find-project-by-domain walk."""
    project_id: str
    name: str


def find_project_by_domain(
    domain: str, *,
    client: httpx.Client | None = None,
    page_size: int = 100,
    max_pages: int = 20,
) -> ProjectRef:
    """Locate the Vercel project that has `domain` attached.

    Walks `/v9/projects` paginated. Each project's `targets.production.alias`
    list is the canonical "domains served by this project's production
    deployment" source — same one `hosting.py`'s walker uses. Matches
    when any alias equals `domain` exactly (lowercased compare).

    Raises:
      - `MissingCredentialsError` if VERCEL_TOKEN unset.
      - `VercelAPIError` if the API errors, returns no match in any
        page, or pagination overflows `max_pages` (defensive cap so
        the fixer can't hang on a misshaped response).
    """
    own_client = client is None
    c = _client(client=client)
    target = domain.lower()
    try:
        until: int | None = None
        for _ in range(max_pages):
            params: dict = {"limit": page_size}
            if until is not None:
                params["until"] = until
            resp = c.get("/v9/projects", params=params)
            _raise_for_status(resp, "GET /v9/projects")
            body = resp.json()
            for proj in body.get("projects", []) or []:
                aliases = _production_aliases(proj)
                if target in {a.lower() for a in aliases}:
                    return ProjectRef(
                        project_id=str(proj.get("id") or ""),
                        name=str(proj.get("name") or ""),
                    )
            pagination = body.get("pagination") or {}
            next_until = pagination.get("next")
            if not next_until:
                break
            until = int(next_until)
        raise VercelAPIError(
            f"no Vercel project attaches {domain!r} "
            f"(searched up to {max_pages} pages of {page_size})"
        )
    finally:
        if own_client:
            c.close()


def _production_aliases(project: dict) -> list[str]:
    """Extract `targets.production.alias` from a project payload —
    mirrors `hosting._project_custom_domains`'s extraction but lives
    here so vercel.py is self-contained."""
    targets = project.get("targets") or {}
    prod = targets.get("production") or {}
    alias = prod.get("alias") or []
    if not isinstance(alias, list):
        return []
    return [a for a in alias if isinstance(a, str) and a]


# ---------- per-domain config ----------


@dataclass
class DomainConfig:
    """One project-domain attachment as Vercel currently has it.

    `redirect` is None when the domain serves directly (i.e. is the
    project's primary). `redirect_status_code` is None when no
    redirect is configured.
    """
    name: str
    redirect: str | None
    redirect_status_code: int | None
    verified: bool


def get_project_domain(
    project_id: str, domain: str, *,
    client: httpx.Client | None = None,
) -> DomainConfig | None:
    """Read one domain's attachment on a project.

    Returns None when the domain isn't attached (HTTP 404). Raises
    `VercelAPIError` on any other non-200.
    """
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get(f"/v9/projects/{project_id}/domains/{domain}")
    finally:
        if own_client:
            c.close()
    if resp.status_code == 404:
        return None
    _raise_for_status(resp, f"GET /v9/projects/{project_id}/domains/{domain}")
    body = resp.json()
    return DomainConfig(
        name=str(body.get("name") or domain),
        redirect=(body.get("redirect") or None),
        redirect_status_code=(
            int(body["redirectStatusCode"])
            if isinstance(body.get("redirectStatusCode"), int)
            else None
        ),
        verified=bool(body.get("verified", True)),
    )


def update_domain_redirect(
    project_id: str, domain: str, *,
    redirect_to: str | None,
    status_code: int = 308,
    client: httpx.Client | None = None,
) -> None:
    """PATCH the redirect config on a domain attachment.

    `redirect_to=None` clears the redirect (the domain starts serving
    directly — i.e. becomes "primary" in operator-speak).
    `redirect_to="<apex>"` + `status_code=308` makes `domain` a
    permanent redirect to `<apex>`. Idempotent on Vercel's side: a
    PATCH that sets the same redirect succeeds without state change.
    """
    body: dict = {"redirect": redirect_to}
    if redirect_to is not None:
        body["redirectStatusCode"] = status_code
    else:
        body["redirectStatusCode"] = None
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.patch(f"/v9/projects/{project_id}/domains/{domain}",
                       json=body)
    finally:
        if own_client:
            c.close()
    _raise_for_status(
        resp,
        f"PATCH /v9/projects/{project_id}/domains/{domain}",
    )


def add_domain_to_project(
    project_id: str, name: str, *,
    redirect_to: str | None = None,
    status_code: int = 308,
    client: httpx.Client | None = None,
) -> None:
    """Attach a new domain to the project. Used when www isn't already
    in the project's domain list.

    Vercel may return 409 if the domain already belongs to a different
    project on the account — surface as `VercelAPIError` so the caller
    can route to a `manual` FixResult."""
    body: dict = {"name": name}
    if redirect_to is not None:
        body["redirect"] = redirect_to
        body["redirectStatusCode"] = status_code
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.post(f"/v10/projects/{project_id}/domains", json=body)
    finally:
        if own_client:
            c.close()
    _raise_for_status(resp, f"POST /v10/projects/{project_id}/domains")


def verify_token(*, client: httpx.Client | None = None) -> dict:
    """GET /v2/user — same probe `apikeys._probe_vercel` uses; returned
    here as a typed wrapper so the v26.D fixer can do its own pre-flight
    check before walking projects. Raises `VercelAPIError` on non-200."""
    own_client = client is None
    c = _client(client=client)
    try:
        resp = c.get("/v2/user")
    finally:
        if own_client:
            c.close()
    _raise_for_status(resp, "GET /v2/user")
    return resp.json()
