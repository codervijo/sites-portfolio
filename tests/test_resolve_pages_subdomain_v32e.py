"""v32.E — the apex custom-domain CNAME must target the project's ACTUAL
`*.pages.dev` subdomain. CF appends a random suffix when `<slug>.pages.dev`
collides globally (`scopeguard-abu.pages.dev`), and the create response's
`subdomain` is often empty until CF assigns it — so guessing `<slug>.pages.dev`
produced a permanent `1014`. `_resolve_pages_subdomain` prefers the project's
subdomain, re-fetches when absent, and flags a guess. See bugs.md 2026-05-31.
"""
from __future__ import annotations

import pytest

from portfolio import cli, cloudflare
from portfolio.cloudflare import PagesProject


def _proj(subdomain):
    return PagesProject(
        name="scopeguard", domains=[], source_owner="me", source_repo="r",
        production_branch="main", latest_deployment_id=None,
        subdomain=subdomain, created=True,
    )


def test_uses_project_subdomain_when_present_no_refetch(monkeypatch):
    def _should_not_fetch(*a, **kw):
        raise AssertionError("must not re-fetch when subdomain is present")
    monkeypatch.setattr(cloudflare, "get_pages_project", _should_not_fetch)

    target, authoritative = cli._resolve_pages_subdomain(
        _proj("scopeguard-abu.pages.dev"), "scopeguard", "acct1")
    assert target == "scopeguard-abu.pages.dev"
    assert authoritative is True


def test_refetches_when_create_response_subdomain_empty(monkeypatch):
    # Fresh-create object has no subdomain yet → re-fetch gets the suffixed one.
    monkeypatch.setattr(
        cloudflare, "get_pages_project",
        lambda slug, **kw: _proj("scopeguard-abu.pages.dev"))
    target, authoritative = cli._resolve_pages_subdomain(
        _proj(None), "scopeguard", "acct1")
    assert target == "scopeguard-abu.pages.dev"
    assert authoritative is True


def test_falls_back_to_slug_guess_when_unreadable(monkeypatch):
    # Re-fetch returns a project still missing the subdomain → guess + flag.
    monkeypatch.setattr(
        cloudflare, "get_pages_project", lambda slug, **kw: _proj(None))
    target, authoritative = cli._resolve_pages_subdomain(
        _proj(None), "scopeguard", "acct1")
    assert target == "scopeguard.pages.dev"
    assert authoritative is False


def test_guess_when_refetch_errors(monkeypatch):
    def _boom(*a, **kw):
        raise cloudflare.CloudflareAPIError("500")
    monkeypatch.setattr(cloudflare, "get_pages_project", _boom)
    target, authoritative = cli._resolve_pages_subdomain(
        _proj(None), "scopeguard", "acct1")
    assert target == "scopeguard.pages.dev"
    assert authoritative is False


def test_guess_when_refetch_returns_none(monkeypatch):
    monkeypatch.setattr(
        cloudflare, "get_pages_project", lambda slug, **kw: None)
    target, authoritative = cli._resolve_pages_subdomain(
        _proj(None), "scopeguard", "acct1")
    assert target == "scopeguard.pages.dev"
    assert authoritative is False
