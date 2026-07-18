"""Tests for v46.D — Step 6.7 `www → apex` provisioning in `new deploy`.

Step 6.7 is extracted as `cli._deploy_step_www_redirect(domain, zone_id, *,
dry_run)`, so these unit-test the branch behavior directly (created / partial /
already-present / dry-run / soft-fail-on-403) by stubbing
`cloudflare.ensure_www_redirects_to_apex` and capturing console output.
"""
from __future__ import annotations

import pytest

from portfolio import cli, cloudflare
from portfolio.cloudflare import WwwProvision


def _norm(capsys) -> str:
    """Collapse whitespace/newlines so rich soft-wraps don't split phrases."""
    return " ".join(capsys.readouterr().out.split())


def test_dry_run_reports_intent_without_calling(monkeypatch, capsys):
    monkeypatch.setattr(cloudflare, "ensure_www_redirects_to_apex",
                        lambda *a, **k: pytest.fail("provisioned in dry-run!"))
    cli._deploy_step_www_redirect("example.com", "z", dry_run=True)
    out = _norm(capsys)
    assert "would" in out
    assert "www→apex 301 redirect rule" in out


def test_both_created_prints_both(monkeypatch, capsys):
    monkeypatch.setattr(cloudflare, "ensure_www_redirects_to_apex",
                        lambda zid, apex, **k: WwwProvision(dns_created=True, rule_created=True))
    cli._deploy_step_www_redirect("example.com", "z", dry_run=False)
    out = _norm(capsys)
    assert "created proxied CNAME www→apex" in out
    assert "added www→apex 301 rule" in out


def test_partial_rule_only(monkeypatch, capsys):
    monkeypatch.setattr(cloudflare, "ensure_www_redirects_to_apex",
                        lambda zid, apex, **k: WwwProvision(dns_created=False, rule_created=True))
    cli._deploy_step_www_redirect("example.com", "z", dry_run=False)
    out = _norm(capsys)
    assert "added www→apex 301 rule" in out
    assert "created proxied CNAME" not in out


def test_already_in_place_idempotent(monkeypatch, capsys):
    monkeypatch.setattr(cloudflare, "ensure_www_redirects_to_apex",
                        lambda zid, apex, **k: WwwProvision(dns_created=False, rule_created=False))
    cli._deploy_step_www_redirect("example.com", "z", dry_run=False)
    out = _norm(capsys)
    assert "already in place" in out


def test_api_error_soft_fails_with_scope_hint(monkeypatch, capsys):
    """A 403 (or any CF API error) must NOT raise — the deploy continues; a
    scope hint + the api-tokens URL are surfaced."""
    def _raise(zid, apex, **k):
        raise cloudflare.CloudflareAPIError("PUT dynamic_redirect entrypoint → HTTP 403")
    monkeypatch.setattr(cloudflare, "ensure_www_redirects_to_apex", _raise)

    cli._deploy_step_www_redirect("example.com", "z", dry_run=False)  # no raise
    out = _norm(capsys)
    assert "not provisioned" in out
    assert "Dynamic Redirect" in out
    assert "api-tokens" in out
