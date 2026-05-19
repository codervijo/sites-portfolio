"""Tests for v11.I — status-emoji + footer-summary helpers.

The helpers live in `hosting.py` (data layer) so the renderer in
`cli.py` and any future dashboard integration share one priority
cascade. Tests inject a fixed `now=...` so age comparisons are
deterministic.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from portfolio.hosting import (
    MAX_DEPLOY_LOOKBACK,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    RECENT_DAYS,
    STALE_DAYS,
    HostingRow,
    hosting_footer_summary,
    hosting_provider_counts,
    hosting_status_emoji,
)


# Pin a `now` so tests don't drift over time. All age fixtures below
# compute relative to this anchor.
_NOW = datetime(2026, 6, 1, 12, 0, 0, tzinfo=timezone.utc)


def _iso_days_ago(days: float) -> str:
    return (_NOW - timedelta(days=days)).isoformat()


# ---- hosting_status_emoji cascade --------------------------------


def test_emoji_unowned_when_provider_is_none():
    row = HostingRow(domain="x.com", provider=None)
    assert hosting_status_emoji(row, now=_NOW) == "—"


def test_emoji_conflict_overrides_age():
    """Conflict beats everything except `provider=None`."""
    row = HostingRow(
        domain="x.com",
        provider=PROVIDER_VERCEL,
        provider_conflict=True,
        last_successful_deploy_at=_iso_days_ago(1),  # otherwise would be ✓
    )
    assert hosting_status_emoji(row, now=_NOW) == "🤐"


def test_emoji_runaway_failures_overrides_age():
    """consecutive_failures >= MAX_DEPLOY_LOOKBACK is the runaway-fail
    signal — visible regardless of how recent the last_successful was."""
    row = HostingRow(
        domain="x.com",
        provider=PROVIDER_VERCEL,
        consecutive_failures=MAX_DEPLOY_LOOKBACK,
        last_successful_deploy_at=_iso_days_ago(1),
    )
    assert hosting_status_emoji(row, now=_NOW) == "✗"


def test_emoji_runaway_threshold_is_strict_greater_equal():
    """Exactly MAX_DEPLOY_LOOKBACK consecutive failures triggers ✗;
    one less doesn't (still shows age-based glyph)."""
    edge = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        consecutive_failures=MAX_DEPLOY_LOOKBACK,
        last_successful_deploy_at=_iso_days_ago(1),
    )
    assert hosting_status_emoji(edge, now=_NOW) == "✗"
    nearly = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        consecutive_failures=MAX_DEPLOY_LOOKBACK - 1,
        last_successful_deploy_at=_iso_days_ago(1),
    )
    assert hosting_status_emoji(nearly, now=_NOW) == "✓"


def test_emoji_recent_for_fresh_success():
    """Last success <RECENT_DAYS old → ✓."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at=_iso_days_ago(RECENT_DAYS - 1),
    )
    assert hosting_status_emoji(row, now=_NOW) == "✓"


def test_emoji_stale_at_threshold():
    """At RECENT_DAYS exactly → ⚠ (boundary: age ≥ RECENT_DAYS)."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at=_iso_days_ago(RECENT_DAYS),
    )
    assert hosting_status_emoji(row, now=_NOW) == "⚠"


def test_emoji_dormant_when_old():
    """Last success ≥STALE_DAYS old → 💤."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at=_iso_days_ago(STALE_DAYS + 30),
    )
    assert hosting_status_emoji(row, now=_NOW) == "💤"


def test_emoji_unowned_when_last_successful_missing():
    """HG case — no build pipeline, so last_successful_deploy_at is
    None. Render as `—` (unknown deploy state, not dormant)."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_HOSTGATOR,
        hg_account_id="gator3164",
        last_successful_deploy_at=None,
    )
    assert hosting_status_emoji(row, now=_NOW) == "—"


def test_emoji_unowned_when_timestamp_malformed():
    """Defensive — a corrupt timestamp (shouldn't happen, but) maps to
    unknown rather than crashing."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at="not-a-date",
    )
    assert hosting_status_emoji(row, now=_NOW) == "—"


def test_emoji_cf_workers_recent():
    """v11.H rows (Workers) set last_successful_deploy_at to
    `script.modified_on` — works through the cascade normally."""
    row = HostingRow(
        domain="airsucks.com", provider=PROVIDER_CF_WORKERS,
        project_slug="airsucks",
        last_successful_deploy_at=_iso_days_ago(5),
    )
    assert hosting_status_emoji(row, now=_NOW) == "✓"


def test_emoji_default_now_uses_utc_today():
    """When `now` isn't passed, `datetime.now(timezone.utc)` is used —
    smoke check that the call doesn't crash with the default."""
    row = HostingRow(
        domain="x.com", provider=PROVIDER_VERCEL,
        last_successful_deploy_at=(
            datetime.now(timezone.utc) - timedelta(days=1)
        ).isoformat(),
    )
    assert hosting_status_emoji(row) == "✓"


# ---- hosting_provider_counts ------------------------------------


def test_provider_counts_includes_zero_buckets_for_every_known_provider():
    """Resolution 11.C / 11.H — zero counts surface in the footer so a
    silent walker (matched nothing) is visible at a glance."""
    counts = hosting_provider_counts([
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_WORKERS),
    ])
    assert counts["vercel"] == 1
    assert counts["cloudflare-workers"] == 1
    assert counts["cloudflare-pages"] == 0
    assert counts["hostgator"] == 0


def test_provider_counts_buckets_unowned_under_dash():
    """provider=None rows roll up under the literal `—` key — the
    renderer reads this for the "unowned" tally without re-checking
    each row."""
    counts = hosting_provider_counts([
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="lost.com", provider=None),
    ])
    assert counts["—"] == 1
    assert counts["vercel"] == 1


def test_provider_counts_empty_input():
    counts = hosting_provider_counts([])
    assert all(v == 0 for v in counts.values())
    assert set(counts.keys()) == {
        "vercel", "cloudflare-pages", "cloudflare-workers", "hostgator",
    }


# ---- hosting_footer_summary -------------------------------------


def test_footer_summary_no_skipped_no_conflicts():
    """Footer omits the parenthetical suffix when there are no skipped
    providers and no conflicts — clean output for the happy path."""
    rows = [
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_WORKERS),
    ]
    line = hosting_footer_summary(rows, {})
    assert line.startswith("2 rows · ")
    assert "vercel" in line
    assert "1 vercel" in line
    assert "1 cloudflare-workers" in line
    assert "0 cloudflare-pages" in line
    assert "(" not in line  # no skipped/conflict suffix


def test_footer_summary_with_skipped_appears_in_suffix():
    """Skipped providers tallied in parens for a quick visual."""
    rows = [HostingRow(domain="a.com", provider=PROVIDER_VERCEL)]
    line = hosting_footer_summary(rows, {
        "hostgator:gator3164": "walker — 403",
        "hostgator:gator4216": "walker — 403",
    })
    assert "(2 skipped)" in line


def test_footer_summary_with_conflicts_tallied():
    rows = [
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL,
                   provider_conflict=True),
        HostingRow(domain="x.com", provider=PROVIDER_CF_PAGES,
                   provider_conflict=True),
    ]
    line = hosting_footer_summary(rows, {})
    assert "2 conflicts" in line


def test_footer_summary_skipped_and_conflicts_combine():
    rows = [
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL,
                   provider_conflict=True),
        HostingRow(domain="x.com", provider=PROVIDER_HOSTGATOR,
                   provider_conflict=True),
    ]
    line = hosting_footer_summary(rows, {"foo": "bar"})
    # Order inside the parens isn't load-bearing; just check both present.
    assert "1 skipped" in line
    assert "2 conflicts" in line


def test_footer_summary_empty_rows_still_shows_zero_per_provider():
    """0 rows total but the per-provider tallies still render — this is
    the diagnostic for 'walker ran, matched nothing'."""
    line = hosting_footer_summary([], {})
    assert line.startswith("0 rows · ")
    assert "0 vercel" in line
    assert "0 cloudflare-workers" in line


def test_footer_summary_singular_grammar_for_one_row():
    line = hosting_footer_summary(
        [HostingRow(domain="a.com", provider=PROVIDER_VERCEL)], {},
    )
    assert line.startswith("1 row · ")   # no "s"
