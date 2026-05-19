"""Tests for v11.A slice 2 — `src/portfolio/hosting.py` dataclass + constants.

Slice 2 is the data shape only. Walker tests come in slices 3-5;
orchestrator tests in slice 6; snapshot persistence in slice 7.
"""
from __future__ import annotations

from portfolio.hosting import (
    MAX_DEPLOY_LOOKBACK,
    PROVIDER_CF_PAGES,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    PROVIDERS,
    RECENT_DAYS,
    STALE_DAYS,
    HostingRow,
)


# ---- constants -----------------------------------------------------


def test_provider_enum_values_match_spec():
    """Resolution 11.C / 11.F — provider strings are stable across the
    walker + renderer + --provider flag normalization."""
    assert PROVIDER_VERCEL == "vercel"
    assert PROVIDER_CF_PAGES == "cloudflare-pages"
    assert PROVIDER_HOSTGATOR == "hostgator"
    assert PROVIDERS == ("vercel", "cloudflare-pages", "hostgator")


def test_age_thresholds_match_resolution_11c():
    """Hardcoded 30 / 90 day thresholds per resolution 11.C."""
    assert RECENT_DAYS == 30
    assert STALE_DAYS == 90


def test_deploy_lookback_cap_matches_resolution_11d():
    """Two-tier cap at 10 per resolution 11.D."""
    assert MAX_DEPLOY_LOOKBACK == 10


# ---- dataclass field shape ----------------------------------------


def test_hosting_row_minimal_construction():
    """Only `domain` is required; every other field has a sensible
    default so walker code can build a row incrementally."""
    row = HostingRow(domain="example.com")
    assert row.domain == "example.com"
    assert row.provider is None
    assert row.consecutive_failures == 0
    assert row.provider_conflict is False
    assert row.error is None
    assert row.notes == []


def test_hosting_row_vercel_shape():
    """Vercel rows fill the build-pipeline fields; HG fields stay None."""
    row = HostingRow(
        domain="example.com",
        provider=PROVIDER_VERCEL,
        project_slug="example-com",
        project_id="prj_abc123",
        latest_deploy_status="READY",
        latest_deploy_at="2026-05-18T16:12:00Z",
        last_successful_deploy_at="2026-05-18T16:12:00Z",
    )
    assert row.provider == "vercel"
    assert row.project_id == "prj_abc123"
    # HG-only fields untouched.
    assert row.hg_account_id is None
    assert row.disk_used_mb is None
    assert row.wp_version is None
    assert row.install_path is None


def test_hosting_row_cf_pages_shape():
    row = HostingRow(
        domain="airsucks.com",
        provider=PROVIDER_CF_PAGES,
        project_slug="airsucks",
        latest_deploy_status="READY",
    )
    assert row.provider == "cloudflare-pages"
    assert row.hg_account_id is None


def test_hosting_row_hostgator_shape():
    """HG rows fill the HG-specific fields; build-pipeline fields stay None."""
    row = HostingRow(
        domain="hybridautopart.com",
        provider=PROVIDER_HOSTGATOR,
        hg_account_id="gator3164",
        disk_used_mb=1430,
        wp_version="6.7.1",
        install_path="/home1/user/public_html/hybridautopart.com",
    )
    assert row.provider == "hostgator"
    assert row.hg_account_id == "gator3164"
    assert row.disk_used_mb == 1430
    assert row.wp_version == "6.7.1"
    # Build-pipeline fields untouched — HG has no build pipeline.
    assert row.project_id is None
    assert row.latest_deploy_status is None
    assert row.last_successful_deploy_at is None
    assert row.consecutive_failures == 0


def test_hosting_row_provider_conflict_default_false():
    """Resolution 11.F — conflict flag opt-in; orchestrator sets it
    when the same domain shows up in multiple walker outputs."""
    row = HostingRow(domain="x.com", provider=PROVIDER_VERCEL)
    assert row.provider_conflict is False


def test_hosting_row_error_surface_default_none():
    """Resolution 11.H — per-row error stays None unless a 5xx /
    rate-limit happened during the walker pass."""
    row = HostingRow(domain="x.com")
    assert row.error is None


def test_hosting_row_notes_is_per_instance_list():
    """Field-default `list` must not share state across instances —
    otherwise appending to one row's notes would leak to others."""
    a = HostingRow(domain="a.com")
    b = HostingRow(domain="b.com")
    a.notes.append("only-on-a")
    assert b.notes == []


def test_hosting_row_provider_none_when_unowned():
    """An unowned domain (not matched by any walker) renders with
    `provider=None` — surfaced as `—` in the table."""
    row = HostingRow(domain="csinorcal.church", provider=None)
    assert row.provider is None
