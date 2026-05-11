"""Tests for src/portfolio/dashboard.py — pure unit tests for the
helpers; the integration paths (snapshot reads + build_status) are
covered by the existing seo_cache + project_status tests."""
from __future__ import annotations

from portfolio.dashboard import (
    DashRow,
    _git_dot,
    _live_dot,
    _rollup,
    sort_rows,
)


def test_live_dot_classification():
    assert _live_dot("live-site") == "🟢"
    assert _live_dot("forwarder") == "🟢"
    assert _live_dot("parked") == "🟡"
    assert _live_dot("dead") == "🔴"
    assert _live_dot("error") == "🔴"
    assert _live_dot("ssl-broken") == "🔴"
    assert _live_dot(None) == "—"
    assert _live_dot("unknown-thing") == "—"


def test_git_dot_no_dir_is_grey():
    assert _git_dot(has_dir=False, own_repo=False,
                    age_days=None, conf_pct=None) == "—"


def test_git_dot_no_own_repo_is_red():
    """Has a dir but not its own .git → fail."""
    assert _git_dot(has_dir=True, own_repo=False,
                    age_days=5, conf_pct=0.95) == "🔴"


def test_git_dot_healthy_is_green():
    """own repo + recent commit + high conf% → green."""
    assert _git_dot(has_dir=True, own_repo=True,
                    age_days=5, conf_pct=0.95) == "🟢"


def test_git_dot_stale_or_low_conf_is_yellow():
    # Recent commit, mediocre conformance → yellow
    assert _git_dot(has_dir=True, own_repo=True,
                    age_days=5, conf_pct=0.70) == "🟡"
    # Good conformance, stale commit → yellow
    assert _git_dot(has_dir=True, own_repo=True,
                    age_days=60, conf_pct=0.95) == "🟡"


def test_git_dot_both_bad_is_red():
    """Stale commit AND low conformance → red."""
    assert _git_dot(has_dir=True, own_repo=True,
                    age_days=200, conf_pct=0.30) == "🔴"


def test_rollup_worst_wins():
    assert _rollup("🟢", "🟢", "🟢") == "🟢"
    assert _rollup("🟢", "🟡", "🟢") == "🟡"
    assert _rollup("🟢", "🟡", "🔴") == "🔴"
    assert _rollup("🟢", "—", "🟡") == "🟡"  # grey ignored
    assert _rollup("—", "—", "—") == "—"     # all grey → grey


def test_sort_attention_puts_red_first():
    rows = [
        DashRow(domain="a", rollup_dot="🟢"),
        DashRow(domain="b", rollup_dot="🔴"),
        DashRow(domain="c", rollup_dot="🟡"),
        DashRow(domain="d", rollup_dot="—"),
    ]
    out = sort_rows(rows, "attention")
    assert [r.domain for r in out] == ["b", "c", "a", "d"]


def test_sort_by_impressions():
    rows = [
        DashRow(domain="a", gsc_impressions=10),
        DashRow(domain="b", gsc_impressions=None),
        DashRow(domain="c", gsc_impressions=1000),
    ]
    out = sort_rows(rows, "imp")
    assert [r.domain for r in out] == ["c", "a", "b"]


def test_sort_by_name():
    rows = [
        DashRow(domain="zebra"),
        DashRow(domain="alpha"),
        DashRow(domain="mango"),
    ]
    out = sort_rows(rows, "name")
    assert [r.domain for r in out] == ["alpha", "mango", "zebra"]


def test_sort_by_age_newest_first_missing_last():
    rows = [
        DashRow(domain="old", last_commit_age_days=200),
        DashRow(domain="fresh", last_commit_age_days=2),
        DashRow(domain="none", last_commit_age_days=None),
        DashRow(domain="medium", last_commit_age_days=30),
    ]
    out = sort_rows(rows, "age")
    assert [r.domain for r in out] == ["fresh", "medium", "old", "none"]
