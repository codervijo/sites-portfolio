"""Tests for v24.C — Step 9 GSC block inside `_deploy_cf_unified`.

Direct unit tests against `_deploy_step9_gsc()` (the helper). Testing
the full `_deploy_cf_unified` would require stubbing 8 other steps;
the helper carries the v24.C scope (verify + add + submit + soft-fail
semantics) so testing it covers the same surface.

Mocked surfaces:
  - `gsc_admin.*` API helpers (get_verification_token, verify_domain,
    add_site, submit_sitemap) via monkeypatch
  - `cloudflare.list_dns_records` + `cloudflare.create_dns_record`
  - `httpx.head` for the sitemap reachability probe
  - GSC token-file presence via patching `gsc.TOKEN_PATH`
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio import cloudflare, gsc_admin
from portfolio.cli import _deploy_step9_gsc
from portfolio.cloudflare import DnsRecord, ZoneInfo


@pytest.fixture
def stub_zone():
    return ZoneInfo(
        zone_id="z1",
        name="example.com",
        name_servers=["alice.ns.cloudflare.com", "bob.ns.cloudflare.com"],
        status="active",
        created=False,
    )


@pytest.fixture
def stub_token_present(monkeypatch, tmp_path):
    """Make GSC_TOKEN_PATH.exists() True so step 9 doesn't pre-flight skip."""
    fake_token = tmp_path / "token.json"
    fake_token.write_text('{"token":"stub"}')
    monkeypatch.setattr("portfolio.gsc.TOKEN_PATH", fake_token)


@pytest.fixture
def stub_token_absent(monkeypatch, tmp_path):
    """GSC_TOKEN_PATH.exists() returns False."""
    monkeypatch.setattr("portfolio.gsc.TOKEN_PATH", tmp_path / "missing.json")


@pytest.fixture
def happy_path_stubs(monkeypatch):
    """Stub every gsc_admin + cloudflare + httpx call to succeed."""
    monkeypatch.setattr(
        gsc_admin, "get_verification_token",
        lambda domain, **kw: "google-site-verification=stub-token",
    )
    monkeypatch.setattr(
        cloudflare, "list_dns_records",
        lambda zone_id, **kw: [],
    )
    monkeypatch.setattr(
        cloudflare, "create_dns_record",
        lambda zone_id, **kw: DnsRecord(
            record_id="r1", type="TXT", name="example.com",
            content="google-site-verification=stub-token", proxied=False,
        ),
    )
    monkeypatch.setattr(gsc_admin, "verify_domain", lambda domain, **kw: None)
    monkeypatch.setattr(gsc_admin, "add_site", lambda domain, **kw: True)
    monkeypatch.setattr(
        gsc_admin, "submit_sitemap",
        lambda domain, sitemap_url, **kw: True,
    )

    # Sitemap HEAD probe — return 200.
    class _Resp:
        status_code = 200
    monkeypatch.setattr("httpx.head", lambda url, **kw: _Resp())


# ---- skip paths ----------------------------------------------------


def test_skip_gsc_flag_short_circuits(stub_zone, tmp_path):
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=True,
    )
    assert status == "skipped:--skip-gsc"


def test_dry_run_short_circuits(stub_zone, tmp_path):
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=True, skip_gsc=False,
    )
    assert status == "skipped:--dry-run"


def test_skips_when_gsc_oauth_not_configured(stub_zone, stub_token_absent, tmp_path):
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "skipped:GSC OAuth not configured"


# ---- happy path ---------------------------------------------------


def test_happy_path_returns_created(
    stub_zone, stub_token_present, happy_path_stubs, tmp_path,
):
    status, detail = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "created"


def test_txt_record_already_in_zone_skips_create(
    stub_zone, stub_token_present, monkeypatch, happy_path_stubs, tmp_path,
):
    """When the verification TXT already exists with the expected value,
    don't call create_dns_record again (idempotency probe)."""
    existing = [
        DnsRecord(
            record_id="r-existing", type="TXT", name="example.com",
            content="google-site-verification=stub-token", proxied=False,
        ),
    ]
    monkeypatch.setattr(
        cloudflare, "list_dns_records",
        lambda zone_id, **kw: existing,
    )
    create_calls = {"n": 0}

    def fail_if_called(*a, **kw):
        create_calls["n"] += 1
        raise AssertionError("create_dns_record must not run when TXT present")

    monkeypatch.setattr(cloudflare, "create_dns_record", fail_if_called)

    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "created"
    assert create_calls["n"] == 0


# ---- scope-bump pending -------------------------------------------


def test_get_token_403_insufficient_scope_skips(
    stub_zone, stub_token_present, monkeypatch, tmp_path,
):
    """v24.B scope bump pending — old `webmasters.readonly` token can't
    call siteVerification. Surface as soft skip with re-consent hint."""
    monkeypatch.setattr(
        gsc_admin, "get_verification_token",
        MagicMock(side_effect=gsc_admin.GSCAdminError(
            "POST siteVerification/v1/token (domain=example.com) → "
            "HTTP 403: insufficient_scope"
        )),
    )
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "skipped:insufficient_scope"


def test_verify_domain_insufficient_scope_skips(
    stub_zone, stub_token_present, monkeypatch, tmp_path,
):
    """Same 403-on-verify branch — also surfaces as skip, not fail."""
    monkeypatch.setattr(
        gsc_admin, "get_verification_token",
        lambda domain, **kw: "google-site-verification=stub-token",
    )
    monkeypatch.setattr(
        cloudflare, "list_dns_records", lambda zone_id, **kw: [],
    )
    monkeypatch.setattr(
        cloudflare, "create_dns_record",
        lambda zone_id, **kw: DnsRecord(
            record_id="r1", type="TXT", name="example.com",
            content="google-site-verification=stub-token", proxied=False,
        ),
    )
    monkeypatch.setattr(
        gsc_admin, "verify_domain",
        MagicMock(side_effect=gsc_admin.GSCAdminError(
            "siteVerification.insert (domain=example.com) → HTTP 403 "
            "insufficient_scope. Run `lamill settings gsc auth --force`."
        )),
    )
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "skipped:insufficient_scope"


# ---- soft-fail paths ----------------------------------------------


def test_verification_timeout_returns_failed(
    stub_zone, stub_token_present, monkeypatch, tmp_path,
):
    """DNS propagation budget exhausted (TXT not visible to Google
    after 60s of polling) → fail status; deploy continues."""
    monkeypatch.setattr(
        gsc_admin, "get_verification_token",
        lambda domain, **kw: "google-site-verification=stub-token",
    )
    monkeypatch.setattr(
        cloudflare, "list_dns_records", lambda zone_id, **kw: [],
    )
    monkeypatch.setattr(
        cloudflare, "create_dns_record",
        lambda zone_id, **kw: DnsRecord(
            record_id="r1", type="TXT", name="example.com",
            content="google-site-verification=stub-token", proxied=False,
        ),
    )
    monkeypatch.setattr(
        gsc_admin, "verify_domain",
        MagicMock(side_effect=gsc_admin.VerificationFailedError(
            "DNS verification for example.com didn't complete after 60s..."
        )),
    )
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "failed:verify_dns:propagation_timeout"


def test_cf_dns_list_failure_returns_failed(
    stub_zone, stub_token_present, monkeypatch, tmp_path,
):
    """CF API outage on dns list → fail status; deploy continues
    (the live probe at Step 8 already succeeded, so site IS deployed
    even if GSC registration breaks)."""
    monkeypatch.setattr(
        gsc_admin, "get_verification_token",
        lambda domain, **kw: "google-site-verification=stub-token",
    )
    monkeypatch.setattr(
        cloudflare, "list_dns_records",
        MagicMock(side_effect=cloudflare.CloudflareAPIError("HTTP 500")),
    )
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status.startswith("failed:dns_list:")


# ---- idempotency: add_site + submit_sitemap return False ---------


def test_add_site_already_exists_still_returns_created(
    stub_zone, stub_token_present, monkeypatch, happy_path_stubs, tmp_path,
):
    """add_site returns False (property already in GSC). Step continues
    to sitemap; final status still 'created' if newly_submitted=True."""
    monkeypatch.setattr(gsc_admin, "add_site", lambda domain, **kw: False)
    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    # newly_added=False + newly_submitted=True → 'created' (sitemap was new).
    assert status == "created"


def test_fully_idempotent_run_returns_already_registered(
    stub_zone, stub_token_present, monkeypatch, happy_path_stubs, tmp_path,
):
    """Both add_site and submit_sitemap return False (fully idempotent
    re-run on already-registered site). Status = already-registered."""
    monkeypatch.setattr(gsc_admin, "add_site", lambda domain, **kw: False)
    monkeypatch.setattr(
        gsc_admin, "submit_sitemap",
        lambda domain, sitemap_url, **kw: False,
    )
    status, detail = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "already-registered"


# ---- sitemap not reachable ----------------------------------------


def test_sitemap_404_defers_submission(
    stub_zone, stub_token_present, monkeypatch, happy_path_stubs, tmp_path,
):
    """HEAD https://<domain>/sitemap.xml returns 404 → defer the
    sitemap submission with a soft-skip note. Verify + add half still
    counts as 'created'."""
    class _Resp404:
        status_code = 404

    monkeypatch.setattr("httpx.head", lambda url, **kw: _Resp404())

    submit_calls = {"n": 0}

    def fail_if_called(*a, **kw):
        submit_calls["n"] += 1
        raise AssertionError("submit_sitemap must not run when sitemap unreachable")

    monkeypatch.setattr(gsc_admin, "submit_sitemap", fail_if_called)

    status, detail = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "created"
    assert "sitemap deferred" in detail
    assert submit_calls["n"] == 0


def test_sitemap_network_error_defers_submission(
    stub_zone, stub_token_present, monkeypatch, happy_path_stubs, tmp_path,
):
    """HEAD raises httpx.ConnectError (DNS / SSL not yet propagated) →
    treat as unreachable + defer submission."""
    import httpx

    def boom(url, **kw):
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr("httpx.head", boom)

    submit_calls = {"n": 0}

    def fail_if_called(*a, **kw):
        submit_calls["n"] += 1

    monkeypatch.setattr(gsc_admin, "submit_sitemap", fail_if_called)

    status, _ = _deploy_step9_gsc(
        domain="example.com", zone=stub_zone, project_dir=tmp_path, dry_run=False, skip_gsc=False,
    )
    assert status == "created"
    assert submit_calls["n"] == 0


# ---- new_deploy command surface -----------------------------------


def test_new_deploy_command_has_skip_gsc_flag():
    """v24.A locked decision (j) — `--skip-gsc` flag on `new deploy`."""
    from typer.testing import CliRunner
    from portfolio.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["new", "deploy", "--help"])
    assert result.exit_code == 0
    assert "--skip-gsc" in result.output


# ---- cloudflare.create_dns_record direct wire-format tests ---------


def test_create_dns_record_posts_correct_body_and_returns_record():
    """Wire-format check: POST /zones/{id}/dns_records with the
    expected JSON body; parse the returned record. Used directly by
    v24.C Step 9 to write the GSC verification TXT."""
    import json
    import httpx

    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.path
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "success": True,
                "errors": [],
                "result": {
                    "id": "rec-new-123",
                    "type": "TXT",
                    "name": "example.com",
                    "content": "google-site-verification=stub",
                    "proxied": False,
                },
            },
        )

    client = httpx.Client(
        base_url="https://api.cloudflare.com/client/v4",
        transport=httpx.MockTransport(handler),
    )
    rec = cloudflare.create_dns_record(
        "z1",
        type="TXT", name="example.com",
        content="google-site-verification=stub",
        client=client,
    )

    assert captured["method"] == "POST"
    assert captured["path"] == "/client/v4/zones/z1/dns_records"
    assert captured["body"] == {
        "type": "TXT",
        "name": "example.com",
        "content": "google-site-verification=stub",
        "ttl": 1,
        "proxied": False,
    }
    assert rec.record_id == "rec-new-123"
    assert rec.type == "TXT"


def test_create_dns_record_raises_on_403():
    """Token lacks DNS:Edit on zone → 403. Caller surfaces as
    deploy-pipeline soft-fail."""
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            json={
                "success": False,
                "errors": [{"code": 10000, "message": "Authentication error"}],
                "result": None,
            },
        )

    client = httpx.Client(
        base_url="https://api.cloudflare.com/client/v4",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(cloudflare.CloudflareAPIError, match="HTTP 403"):
        cloudflare.create_dns_record(
            "z1",
            type="TXT", name="example.com",
            content="stub",
            client=client,
        )
