"""Tests for v18.D — schema + bootstrap integration.

Two surfaces:
  1. `AnalyticsBlock` schema in `lamill_toml.py` — parse, serialize,
     validate, round-trip.
  2. Bootstrap `_maybe_create_ga4_property()` helper + integration
     into `_bootstrap_inner()` — auto-create happy path + 4 soft-skip
     paths (--skip-ga4, no OAuth, no account ID, Admin API failure).

GA4 Admin API calls are mocked via the `httpx.MockTransport` pattern
inherited from v18.C — bootstrap injects `httpx.Client` via the
`client=` kwarg on `ga4_admin.create_*` helpers, so tests can stub
those at the function level.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest


# ---- AnalyticsBlock schema ------------------------------------------


def test_analytics_block_parses_valid_ga4_id(tmp_path: Path):
    from portfolio.lamill_toml import load

    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n'
        '[deploy]\nplatform = "cf-workers"\n\n'
        '[analytics]\nga4_id = "G-HP39MQPM2M"\n'
    )

    payload = load(tmp_path)
    assert payload is not None
    assert payload.analytics is not None
    assert payload.analytics.ga4_id == "G-HP39MQPM2M"


def test_analytics_block_missing_means_none(tmp_path: Path):
    """No [analytics] block in TOML → `analytics` field is None (not
    a default AnalyticsBlock with `ga4_id=None`). This matters because
    `to_dict()` only emits the block when `analytics is not None AND
    .ga4_id is not None`, keeping round-trip determinism."""
    from portfolio.lamill_toml import load

    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n'
        '[deploy]\nplatform = "cf-workers"\n'
    )

    payload = load(tmp_path)
    assert payload is not None
    assert payload.analytics is None


def test_analytics_block_rejects_malformed_ga4_id(tmp_path: Path):
    from portfolio.lamill_toml import ParseError, load

    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n'
        '[deploy]\nplatform = "cf-workers"\n\n'
        '[analytics]\nga4_id = "G-bad-lowercase"\n'
    )

    with pytest.raises(ParseError, match="GA4 shape"):
        load(tmp_path)


def test_analytics_block_rejects_non_string_ga4_id(tmp_path: Path):
    from portfolio.lamill_toml import ParseError, load

    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n'
        '[deploy]\nplatform = "cf-workers"\n\n'
        '[analytics]\nga4_id = 123456789\n'
    )

    with pytest.raises(ParseError, match="must be a string"):
        load(tmp_path)


def test_analytics_block_round_trips(tmp_path: Path):
    """Write → read → write should produce identical [analytics]
    content."""
    from portfolio.lamill_toml import (
        AnalyticsBlock, DeployBlock, LamillToml, load,
    )
    from portfolio.lamill_toml import write as write_lamill_toml

    payload = LamillToml(
        deploy=DeployBlock(platform="cf-workers"),
        analytics=AnalyticsBlock(ga4_id="G-QG4CYZ7MXE"),
    )
    write_lamill_toml(tmp_path, payload)

    reloaded = load(tmp_path)
    assert reloaded is not None
    assert reloaded.analytics is not None
    assert reloaded.analytics.ga4_id == "G-QG4CYZ7MXE"


def test_analytics_block_omitted_when_ga4_id_none(tmp_path: Path):
    """`AnalyticsBlock(ga4_id=None)` should serialize to NO [analytics]
    section in the TOML — minimal-file principle. Otherwise every
    bootstrap that skips GA4 would leave a noisy empty block."""
    from portfolio.lamill_toml import (
        AnalyticsBlock, DeployBlock, LamillToml,
    )
    from portfolio.lamill_toml import write as write_lamill_toml

    payload = LamillToml(
        deploy=DeployBlock(platform="cf-workers"),
        analytics=AnalyticsBlock(ga4_id=None),
    )
    write_lamill_toml(tmp_path, payload)

    raw = (tmp_path / "lamill.toml").read_text()
    assert "[analytics]" not in raw


# ---- _maybe_create_ga4_property helper ------------------------------


def test_maybe_create_skips_when_skip_ga4_flag(monkeypatch):
    """--skip-ga4 short-circuits before any GA4 lookups."""
    from portfolio.bootstrap import _maybe_create_ga4_property

    measurement_id, status = _maybe_create_ga4_property(
        "x.com", skip_ga4=True,
    )
    assert measurement_id is None
    assert status == "skipped:--skip-ga4"


def test_maybe_create_skips_when_no_token(monkeypatch):
    """Without `~/lamill/ga4/token.json`, helper soft-skips with the
    actionable "run `lamill settings ga4 auth`" hint."""
    from portfolio import bootstrap

    monkeypatch.setattr(
        "portfolio.ga4_admin.has_token", lambda: False,
    )

    measurement_id, status = bootstrap._maybe_create_ga4_property(
        "x.com", skip_ga4=False,
    )
    assert measurement_id is None
    assert "OAuth not configured" in status
    assert "settings ga4 auth" in status


def test_maybe_create_skips_when_no_account_id(monkeypatch):
    """Token exists but GA4_ACCOUNT_ID not in apikeys → soft-skip
    with the actionable apikeys set hint."""
    from portfolio import bootstrap

    monkeypatch.setattr("portfolio.ga4_admin.has_token", lambda: True)
    monkeypatch.setattr("portfolio.apikeys.get_key", lambda k: None)

    measurement_id, status = bootstrap._maybe_create_ga4_property(
        "x.com", skip_ga4=False,
    )
    assert measurement_id is None
    assert "GA4_ACCOUNT_ID" in status
    assert "settings apikeys set" in status


def test_maybe_create_soft_fails_on_admin_api_error(monkeypatch):
    """When Admin API raises GA4AdminError, helper catches + returns
    'failed:...' so bootstrap can continue without GA4 wired."""
    from portfolio import bootstrap, ga4_admin

    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr(
        "portfolio.apikeys.get_key",
        lambda k: "42" if k == "GA4_ACCOUNT_ID" else None,
    )

    def fake_create_property(account_id, display_name, **kwargs):
        raise ga4_admin.GA4AdminError(
            "POST /properties → HTTP 403: scope error"
        )

    monkeypatch.setattr(ga4_admin, "create_property", fake_create_property)

    measurement_id, status = bootstrap._maybe_create_ga4_property(
        "x.com", skip_ga4=False,
    )
    assert measurement_id is None
    assert status.startswith("failed:")
    assert "403" in status


def test_maybe_create_happy_path(monkeypatch):
    """All prerequisites met → property + stream created → returns
    `(measurement_id, "created")`."""
    from portfolio import bootstrap, ga4_admin

    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr(
        "portfolio.apikeys.get_key",
        lambda k: "42" if k == "GA4_ACCOUNT_ID" else None,
    )

    captured: dict = {}

    def fake_create_property(account_id, display_name, **kwargs):
        captured["property_args"] = (account_id, display_name)
        return "987654321"

    def fake_create_web_stream(property_id, default_uri, **kwargs):
        captured["stream_args"] = (property_id, default_uri)
        return ("stream-7", "G-NEWSITE99")

    monkeypatch.setattr(ga4_admin, "create_property", fake_create_property)
    monkeypatch.setattr(ga4_admin, "create_web_stream", fake_create_web_stream)

    measurement_id, status = bootstrap._maybe_create_ga4_property(
        "newsite.dev", skip_ga4=False,
    )

    assert measurement_id == "G-NEWSITE99"
    assert status == "created"
    assert captured["property_args"] == ("42", "newsite.dev")
    assert captured["stream_args"] == ("987654321", "https://newsite.dev/")


# ---- Bootstrap integration -----------------------------------------


def _stub_bootstrap_for_ga4_tests(monkeypatch, tmp_path):
    """Minimal stubbing to make `bootstrap()` run end-to-end without
    real git / file-system contention with the operator's sites dir.
    Returns the project dir under `tmp_path`. Passes `sites_root=`
    explicitly to keep test isolation off the real ~/work tree."""
    # Stub git init so bootstrap doesn't try to make a real commit.
    monkeypatch.setattr(
        "portfolio.bootstrap._git_init_and_commit",
        lambda project_dir, msg: (True, "0123456"),
    )
    sites_dir = tmp_path / "sites"
    sites_dir.mkdir(parents=True)
    return sites_dir


def test_bootstrap_writes_ga4_id_into_lamill_toml_on_success(
    monkeypatch, tmp_path,
):
    """End-to-end: bootstrap calls the helper → gets G-XXX →
    writes [analytics] ga4_id into the new site's lamill.toml."""
    from portfolio import bootstrap, ga4_admin

    sites_dir = _stub_bootstrap_for_ga4_tests(monkeypatch, tmp_path)
    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr(
        "portfolio.apikeys.get_key",
        lambda k: "42" if k == "GA4_ACCOUNT_ID" else None,
    )
    monkeypatch.setattr(
        ga4_admin, "create_property",
        lambda account_id, display_name, **kw: "111222333",
    )
    monkeypatch.setattr(
        ga4_admin, "create_web_stream",
        lambda property_id, default_uri, **kw: ("s-1", "G-BOOTNEW99"),
    )

    result = bootstrap.bootstrap(
        "newsite.dev", stack="astro",
        operator_inputs={}, today_iso="2026-05-21",
        sites_root=sites_dir,
    )

    assert result.ga4_status == "created"
    assert result.ga4_measurement_id == "G-BOOTNEW99"

    lamill_path = result.project_dir / "lamill.toml"
    assert lamill_path.exists()
    raw = lamill_path.read_text()
    assert "[analytics]" in raw
    assert "G-BOOTNEW99" in raw


def test_bootstrap_skips_ga4_when_flag_set(monkeypatch, tmp_path):
    from portfolio import bootstrap, ga4_admin

    sites_dir = _stub_bootstrap_for_ga4_tests(monkeypatch, tmp_path)
    # OAuth + account ID are set, but --skip-ga4 wins.
    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr(
        "portfolio.apikeys.get_key",
        lambda k: "42" if k == "GA4_ACCOUNT_ID" else None,
    )
    # Sentinel: if create_property is called, the test would fail.
    monkeypatch.setattr(
        ga4_admin, "create_property",
        lambda *a, **kw: pytest.fail("create_property must not run with --skip-ga4"),
    )

    result = bootstrap.bootstrap(
        "newsite.dev", stack="astro",
        operator_inputs={}, today_iso="2026-05-21",
        skip_ga4=True,
        sites_root=sites_dir,
    )

    assert result.ga4_status == "skipped:--skip-ga4"
    assert result.ga4_measurement_id is None
    raw = (result.project_dir / "lamill.toml").read_text()
    assert "[analytics]" not in raw


def test_bootstrap_continues_when_admin_api_fails(monkeypatch, tmp_path):
    """If Admin API raises mid-bootstrap, bootstrap completes (no
    rollback, no exception bubbling) — GA4 is non-blocking."""
    from portfolio import bootstrap, ga4_admin

    sites_dir = _stub_bootstrap_for_ga4_tests(monkeypatch, tmp_path)
    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr(
        "portfolio.apikeys.get_key",
        lambda k: "42" if k == "GA4_ACCOUNT_ID" else None,
    )

    def boom(*a, **kw):
        raise ga4_admin.GA4AdminError("HTTP 500: server error")

    monkeypatch.setattr(ga4_admin, "create_property", boom)

    result = bootstrap.bootstrap(
        "newsite.dev", stack="astro",
        operator_inputs={}, today_iso="2026-05-21",
        sites_root=sites_dir,
    )

    assert result.ga4_status.startswith("failed:")
    assert "500" in result.ga4_status
    assert result.ga4_measurement_id is None
    # Bootstrap still produced lamill.toml — without [analytics].
    raw = (result.project_dir / "lamill.toml").read_text()
    assert "[analytics]" not in raw
