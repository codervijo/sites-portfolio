"""Tests for `settings serpapi-quota {show,sync}` CLI surface.

Mirrors test_settings_cloudflare_cli.py shape: Typer CliRunner +
monkeypatched module state so no test touches the operator's real
data/serp/_quota.json or fires a real SerpAPI HTTP call.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest
from typer.testing import CliRunner

from portfolio.cli import app


def _patch_quota_path(monkeypatch, tmp_path):
    from portfolio import serpapi_quota
    monkeypatch.setattr(serpapi_quota, "QUOTA_PATH", tmp_path / "_quota.json")


def _seed_quota(used: int, limit: int = 250, synced: bool = False) -> dict:
    from portfolio import serpapi_quota
    payload = {
        "schema": serpapi_quota.SCHEMA,
        "month": datetime.now(timezone.utc).strftime("%Y-%m"),
        "queries_used": used,
        "limit": limit,
        "last_updated": "2026-05-16T22:00:00+00:00",
    }
    if synced:
        payload["synced_with_serpapi_at"] = "2026-05-16T22:00:00+00:00"
    serpapi_quota._save(payload)
    return payload


# ---------- settings serpapi-quota show ----------


def test_show_prints_local_ledger_state(monkeypatch, tmp_path):
    _patch_quota_path(monkeypatch, tmp_path)
    _seed_quota(used=42)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "show"])
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    assert "42/250" in flat
    assert "16%" in flat or "17%" in flat   # 42/250 = 16.8%
    assert "ledger" in flat.lower() or "month" in flat.lower()


def test_show_hints_at_sync_when_never_synced(monkeypatch, tmp_path):
    _patch_quota_path(monkeypatch, tmp_path)
    _seed_quota(used=10, synced=False)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "show"])
    flat = " ".join(result.stdout.split())
    assert "never been synced" in flat or "settings serpapi-quota sync" in flat


def test_show_uses_red_color_indicator_at_high_usage(monkeypatch, tmp_path):
    """At 95%+ the renderer should signal that quota's nearly out.
    We don't assert ANSI color (CliRunner strips terminal codes), but
    the percentage should show as 95+ — the visual signal is in the
    color marker that wraps it, which we'd see in real terminal."""
    _patch_quota_path(monkeypatch, tmp_path)
    _seed_quota(used=240)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "show"])
    flat = " ".join(result.stdout.split())
    assert "240/250" in flat
    assert "96%" in flat   # 240/250 = 96%


# ---------- settings serpapi-quota sync ----------


def _patch_sync_success(monkeypatch, *, used: int, limit: int = 250):
    """Replace sync_with_serpapi with a stub that pretends SerpAPI
    returned `used` / `limit` and persists locally — same as the real
    helper would do on success."""
    from portfolio import serpapi_quota

    def fake_sync(api_key, **kw):
        payload = {
            "schema": serpapi_quota.SCHEMA,
            "month": datetime.now(timezone.utc).strftime("%Y-%m"),
            "queries_used": used,
            "limit": limit,
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "synced_with_serpapi_at": datetime.now(timezone.utc).isoformat(),
        }
        serpapi_quota._save(payload)
        return payload
    monkeypatch.setattr(serpapi_quota, "sync_with_serpapi", fake_sync)


def _patch_apikey(monkeypatch, key: str | None = "fake-key"):
    """Stub `apikeys.get_key` so the CLI doesn't try to read the
    operator's real portfolio.env."""
    from portfolio import apikeys
    monkeypatch.setattr(apikeys, "get_key", lambda name: key)


def test_sync_overwrites_local_ledger_when_drifted(monkeypatch, tmp_path):
    """The donready-style drift scenario: local thinks 250/250, SerpAPI
    actually has 16 used. After sync, local should match SerpAPI."""
    _patch_quota_path(monkeypatch, tmp_path)
    _patch_apikey(monkeypatch)
    _seed_quota(used=250)
    _patch_sync_success(monkeypatch, used=16)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "sync"])
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    assert "Synced" in flat or "✓" in flat
    # Over-counting drift surfaced explicitly so the operator knows
    # something was wrong.
    assert "over-counting" in flat or "234" in flat
    # Persisted file matches the synced value.
    from portfolio import serpapi_quota
    after = serpapi_quota.read_quota()
    assert after["queries_used"] == 16


def test_sync_reports_under_counting_drift(monkeypatch, tmp_path):
    """The opposite drift — local says 5 used, SerpAPI knows it's 50.
    Less likely but still possible (manual API use outside this tool).
    The renderer should call this out too."""
    _patch_quota_path(monkeypatch, tmp_path)
    _patch_apikey(monkeypatch)
    _seed_quota(used=5)
    _patch_sync_success(monkeypatch, used=50)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "sync"])
    assert result.exit_code == 0
    flat = " ".join(result.stdout.split())
    assert "under-counting" in flat or "45" in flat


def test_sync_no_drift_message_when_aligned(monkeypatch, tmp_path):
    """If local and SerpAPI already agree, the drift-callout line is
    omitted — the sync just confirms the state."""
    _patch_quota_path(monkeypatch, tmp_path)
    _patch_apikey(monkeypatch)
    _seed_quota(used=42)
    _patch_sync_success(monkeypatch, used=42)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "sync"])
    assert result.exit_code == 0
    flat = " ".join(result.stdout.split())
    # No drift mention.
    assert "over-counting" not in flat
    assert "under-counting" not in flat


def test_sync_refuses_when_no_api_key(monkeypatch, tmp_path):
    """Without SERPAPI_KEY there's nothing to sync against. Must exit
    non-zero with a clear pointer to `apikeys set`."""
    _patch_quota_path(monkeypatch, tmp_path)
    _patch_apikey(monkeypatch, key=None)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "sync"])
    assert result.exit_code != 0
    flat = " ".join(result.stdout.split())
    assert "SERPAPI_KEY" in flat
    assert "apikeys set" in flat


def test_sync_surfaces_api_error(monkeypatch, tmp_path):
    """When SerpAPI returns auth failure / HTTP error, sync must exit
    non-zero with the underlying error visible."""
    _patch_quota_path(monkeypatch, tmp_path)
    _patch_apikey(monkeypatch)
    _seed_quota(used=10)

    from portfolio import serpapi_quota

    def fake_sync_fails(api_key, **kw):
        raise serpapi_quota.QuotaSyncError("SerpAPI 401 — check SERPAPI_KEY")
    monkeypatch.setattr(serpapi_quota, "sync_with_serpapi", fake_sync_fails)

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "sync"])
    assert result.exit_code != 0
    flat = " ".join(result.stdout.split())
    assert "Sync failed" in flat
    assert "401" in flat


# ---------- help / registration ----------


def test_settings_serpapi_quota_appears_in_settings_help():
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "--help"])
    assert result.exit_code == 0
    assert "serpapi-quota" in result.stdout


def test_show_and_sync_subcommands_appear_in_help():
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "serpapi-quota", "--help"])
    assert result.exit_code == 0
    assert "show" in result.stdout
    assert "sync" in result.stdout
