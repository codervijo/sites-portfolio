"""Tests for `settings cloudflare {token, status}` CLI surface.

Mirrors `test_settings_operator_cli.py` shape: Typer CliRunner + monkeypatched
TOKEN_PATH/ZONES_CACHE so no test touches the operator's real config dir.
The token verification path is patched at the function level (verify_token,
save_token) — we test that the CLI wires those correctly, not that the
underlying HTTP works (that's covered by test_cloudflare.py).
"""
from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from portfolio.cli import app


def _patch_cf_paths(monkeypatch, tmp_path):
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", tmp_path / "cf" / "token")
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", tmp_path / "cf" / "zones.json")


# ---------- settings cloudflare token ----------


def test_token_command_saves_and_verifies(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "verify_token",
                        lambda **kw: {"id": "tok-1", "status": "active",
                                      "expires_on": None})

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "token"],
                           input="my-test-token\n")
    assert result.exit_code == 0, result.stdout
    assert "Saved token" in result.stdout
    assert "Verified" in result.stdout
    assert "active" in result.stdout

    # File written + locked down.
    assert (tmp_path / "cf" / "token").read_text() == "my-test-token"
    assert oct((tmp_path / "cf" / "token").stat().st_mode & 0o777) == "0o600"


def test_token_command_no_verify_flag_skips_network(monkeypatch, tmp_path):
    """--no-verify must NOT call verify_token. The test patches verify_token
    to a sentinel that fails loud if invoked — proves we short-circuit."""
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare

    def must_not_call(**kw):
        raise AssertionError("verify_token was called despite --no-verify")
    monkeypatch.setattr(cloudflare, "verify_token", must_not_call)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "token", "--no-verify"],
                           input="raw-token\n")
    assert result.exit_code == 0, result.stdout
    assert "Saved token" in result.stdout
    assert "skipped verification" in result.stdout
    assert (tmp_path / "cf" / "token").read_text() == "raw-token"


def test_token_command_rejects_empty_input(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "token"],
                           input="   \n")
    assert result.exit_code != 0
    assert "Empty token" in result.stdout
    # No file written on empty input.
    assert not (tmp_path / "cf" / "token").exists()


def test_token_command_surfaces_verification_failure(monkeypatch, tmp_path):
    """Token saved but CF rejects it → command exits non-zero with a
    diagnostic hint so the operator knows to re-check permissions."""
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare

    def reject(**kw):
        raise cloudflare.CloudflareAPIError("HTTP 401: invalid token")
    monkeypatch.setattr(cloudflare, "verify_token", reject)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "token"],
                           input="wrong-permissions-token\n")
    assert result.exit_code != 0
    assert "verification failed" in result.stdout
    assert "Zone:Cache Purge" in result.stdout
    # Token IS written even on verify failure (operator can fix
    # permissions on the CF dashboard without re-pasting).
    assert (tmp_path / "cf" / "token").read_text() == "wrong-permissions-token"


# ---------- settings cloudflare status ----------


def test_status_when_no_token_configured(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "status"])
    assert result.exit_code == 0
    assert "Token present" in result.stdout
    assert "no" in result.stdout
    # Hint at how to fix it.
    assert "settings cloudflare token" in result.stdout


def test_status_when_token_present(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare
    cloudflare.save_token("a-saved-token")
    # Seed two cached zones to exercise the count.
    (tmp_path / "cf" / "zones.json").write_text(
        json.dumps({"x.com": "z1", "y.com": "z2"}))

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "status"])
    assert result.exit_code == 0
    assert "yes" in result.stdout
    assert "0o600" in result.stdout
    # Don't leak the token itself in status output.
    assert "a-saved-token" not in result.stdout
    # Rich may wrap "(2 domain(s) cached)" across lines on narrow widths;
    # normalize whitespace for the assertion.
    flattened = " ".join(result.stdout.split())
    assert "2 domain(s) cached" in flattened


def test_status_with_verify_flag_hits_cf(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare
    cloudflare.save_token("a-saved-token")
    monkeypatch.setattr(cloudflare, "verify_token",
                        lambda **kw: {"id": "tok-7", "status": "active",
                                      "expires_on": None})

    runner = CliRunner()
    result = runner.invoke(app,
                           ["settings", "cloudflare", "status", "--verify"])
    assert result.exit_code == 0
    assert "Token OK" in result.stdout
    assert "tok-7" in result.stdout


def test_status_verify_without_token_exits_nonzero(monkeypatch, tmp_path):
    _patch_cf_paths(monkeypatch, tmp_path)
    runner = CliRunner()
    result = runner.invoke(app,
                           ["settings", "cloudflare", "status", "--verify"])
    assert result.exit_code != 0
    assert "no token saved" in result.stdout.lower()


def test_status_verify_when_cf_rejects_token(monkeypatch, tmp_path):
    """Token saved but expired / revoked on CF side → status --verify
    exits non-zero so scripts can detect it."""
    _patch_cf_paths(monkeypatch, tmp_path)
    from portfolio import cloudflare
    cloudflare.save_token("expired-token")

    def reject(**kw):
        raise cloudflare.CloudflareAPIError("HTTP 401: expired")
    monkeypatch.setattr(cloudflare, "verify_token", reject)

    runner = CliRunner()
    result = runner.invoke(app,
                           ["settings", "cloudflare", "status", "--verify"])
    assert result.exit_code != 0
    assert "rejected" in result.stdout.lower() or "expired" in result.stdout.lower()


# ---------- registration sanity ----------


def test_settings_cloudflare_appears_in_help():
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "--help"])
    assert result.exit_code == 0
    assert "cloudflare" in result.stdout


def test_token_and_status_subcommands_appear_in_help():
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "cloudflare", "--help"])
    assert result.exit_code == 0
    assert "token" in result.stdout
    assert "status" in result.stdout
