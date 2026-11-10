"""BUG-104 — a 0-byte GSC token silently blanked `fleet seo` GSC columns."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from portfolio import gsc


def test_load_token_empty_file_raises_typed_error_with_fix(tmp_path):
    tok = tmp_path / "token.json"
    tok.write_text("")
    with pytest.raises(gsc.MissingCredentialsError) as ei:
        gsc.load_token(tok, gsc.SCOPES, "lamill settings gsc auth --force")
    msg = str(ei.value)
    assert "0 bytes" in msg and "lamill settings gsc auth --force" in msg


def test_write_token_atomic_replaces_and_chmods(tmp_path):
    tok = tmp_path / "sub" / "token.json"
    creds = MagicMock()
    creds.to_json.return_value = json.dumps({"refresh_token": "r"})
    gsc.write_token_atomic(tok, creds)
    assert json.loads(tok.read_text()) == {"refresh_token": "r"}
    assert tok.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "sub" / "token.json.tmp").exists()


def test_write_token_atomic_failure_keeps_old_token(tmp_path):
    tok = tmp_path / "token.json"
    tok.write_text('{"refresh_token": "old"}')
    creds = MagicMock()
    creds.to_json.side_effect = RuntimeError("boom")
    with pytest.raises(RuntimeError):
        gsc.write_token_atomic(tok, creds)
    assert json.loads(tok.read_text()) == {"refresh_token": "old"}


def test_run_seo_records_auth_cause(monkeypatch):
    from portfolio import seo_runtime

    def bad_auth(*a, **k):
        raise gsc.MissingCredentialsError("token unreadable (0 bytes)")

    monkeypatch.setattr(gsc, "authenticate", bad_auth)
    monkeypatch.setattr(seo_runtime, "probe_http", lambda d: {
        "status": 200, "error": None, "hsts": False,
        "robots_served": True, "sitemap_served": True})
    monkeypatch.setattr(seo_runtime, "probe_crux",
                        lambda d, k: {"status": "no-key"})
    rows = seo_runtime.run_seo(["a.com"], days=28, crux_api_key="")
    assert rows[0].gsc_status == "auth-skipped"
    assert any(n.startswith("gsc-auth: MissingCredentialsError") and "0 bytes" in n
               for n in rows[0].notes)


def test_authenticate_noninteractive_never_opens_browser(tmp_path, monkeypatch):
    cred = tmp_path / "credentials.json"
    cred.write_text("{}")
    monkeypatch.setattr(gsc, "CREDENTIALS_PATH", cred)
    monkeypatch.setattr(gsc, "TOKEN_PATH", tmp_path / "token.json")  # absent
    monkeypatch.setattr(gsc, "_interactive_flow",
                        lambda: pytest.fail("opened a browser"))
    with pytest.raises(gsc.MissingCredentialsError, match="settings gsc auth --force"):
        gsc.authenticate(interactive=False)


def test_preflight_plain_words_on_bad_token(monkeypatch):
    from portfolio import seo_runtime
    monkeypatch.setattr(seo_runtime, "_reach", lambda url, timeout=5.0: None)

    def bad(**k):
        raise gsc.MissingCredentialsError("OAuth token is unreadable (0 bytes)")
    monkeypatch.setattr(gsc, "authenticate", bad)
    with pytest.raises(seo_runtime.GscPreflightError, match="0 bytes"):
        seo_runtime.gsc_preflight()


def test_preflight_zero_properties_is_an_error(monkeypatch):
    from portfolio import seo_runtime
    monkeypatch.setattr(seo_runtime, "_reach", lambda url, timeout=5.0: None)
    monkeypatch.setattr(gsc, "authenticate", lambda **k: object())
    monkeypatch.setattr(gsc, "get_service", lambda c: object())
    monkeypatch.setattr(gsc, "list_properties", lambda svc: [])
    with pytest.raises(seo_runtime.GscPreflightError, match="wrong account"):
        seo_runtime.gsc_preflight()


def test_fleet_seo_stops_before_probing_when_preflight_fails(monkeypatch):
    from typer.testing import CliRunner
    from portfolio import seo_runtime
    from portfolio.cli import app

    def bad():
        raise seo_runtime.GscPreflightError("Not logged in to Google Search Console")
    monkeypatch.setattr(seo_runtime, "gsc_preflight", bad)
    monkeypatch.setattr(seo_runtime, "run_seo",
                        lambda *a, **k: pytest.fail("probed despite failed preflight"))
    res = CliRunner().invoke(app, ["fleet", "seo", "--refresh"])
    assert res.exit_code == 1
    assert "Preflight" in res.output and "Not logged in" in res.output


@pytest.mark.parametrize("argv", [["fleet", "focus", "--refresh"],
                                  ["fleet", "dashboard", "--refresh"]])
def test_focus_and_dashboard_refresh_stop_on_failed_preflight(monkeypatch, argv):
    from typer.testing import CliRunner
    from portfolio import check, seo_runtime
    from portfolio.cli import app

    def bad():
        raise seo_runtime.GscPreflightError("Not logged in to Google Search Console")
    monkeypatch.setattr(seo_runtime, "gsc_preflight", bad)
    monkeypatch.setattr(check, "run_check",
                        lambda *a, **k: pytest.fail("probed despite failed preflight"))
    res = CliRunner().invoke(app, argv)
    assert res.exit_code == 1, res.output
    assert "Preflight" in res.output and "Not logged in" in res.output


def test_report_gsc_problems_blocks_save_on_total_auth_failure():
    from rich.console import Console
    from portfolio.seo_runtime import SEORow, report_gsc_problems
    r = SEORow(domain="a.com"); r.gsc_status = "auth-skipped"
    r.notes.append("gsc-auth: MissingCredentialsError: 0 bytes")
    c = Console(record=True, width=200)
    assert report_gsc_problems([r], c) is False
    assert "GSC auth failed" in c.export_text()
    ok = SEORow(domain="b.com"); ok.gsc_status = "error"
    ok.notes.append("gsc-error: HttpError 500")
    c2 = Console(record=True, width=200)
    assert report_gsc_problems([ok], c2) is True
    assert "GSC query failed for 1 domain" in c2.export_text()


def test_preflight_no_internet_fails_first(monkeypatch):
    from portfolio import seo_runtime
    monkeypatch.setattr(seo_runtime, "_reach", lambda url, timeout=5.0: "DNS lookup failed")
    monkeypatch.setattr(gsc, "authenticate",
                        lambda **k: pytest.fail("checked login with no internet"))
    with pytest.raises(seo_runtime.GscPreflightError, match="no internet.*DNS lookup failed"):
        seo_runtime.gsc_preflight()


def test_preflight_gsc_api_unreachable(monkeypatch):
    from portfolio import seo_runtime
    monkeypatch.setattr(seo_runtime, "_reach", lambda url, timeout=5.0:
                        None if url == seo_runtime._NET_PROBE_URL else "no answer within 5s")
    monkeypatch.setattr(gsc, "authenticate",
                        lambda **k: pytest.fail("checked login with GSC unreachable"))
    with pytest.raises(seo_runtime.GscPreflightError,
                       match="Search Console API isn't reachable.*no answer"):
        seo_runtime.gsc_preflight()


def test_reach_reports_dns_failure():
    from portfolio.seo_runtime import _reach
    assert _reach("https://does-not-exist.invalid/", timeout=3) is not None
