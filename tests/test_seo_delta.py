"""v40 — snapshot pairing + Δ computation for `fleet seo --since`."""
from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from portfolio.seo_delta import (
    DomainDelta,
    compute_deltas,
    pick_baseline,
)


def _paths(*dates: str) -> list[Path]:
    return [Path(f"data/seo/{d}.json") for d in dates]


def _row(domain, pos, imp):
    return SimpleNamespace(domain=domain, gsc_position=pos, gsc_impressions=imp)


# ---- pick_baseline ----------------------------------------------------

def test_exact_baseline_on_or_before():
    pick = pick_baseline(
        _paths("2026-06-01", "2026-06-06", "2026-06-13"),
        since_days=7, current_date=date(2026, 6, 13),
    )
    assert pick is not None
    assert pick.snapshot_date == date(2026, 6, 6)
    assert pick.gap_days == 7
    assert pick.exact is True


def test_missing_exact_falls_back_to_closest_earlier():
    # No 06-06 snapshot; nearest on-or-before is 06-04.
    pick = pick_baseline(
        _paths("2026-06-04", "2026-06-09", "2026-06-13"),
        since_days=7, current_date=date(2026, 6, 13),
    )
    assert pick.snapshot_date == date(2026, 6, 4)
    assert pick.gap_days == 9
    assert pick.exact is False


def test_history_shorter_than_window_uses_oldest_and_notes_gap():
    # Only 5 days of history; --since 7d degrades to the oldest snapshot.
    pick = pick_baseline(
        _paths("2026-06-08", "2026-06-10", "2026-06-13"),
        since_days=7, current_date=date(2026, 6, 13),
    )
    assert pick.snapshot_date == date(2026, 6, 8)
    assert pick.gap_days == 5
    assert pick.exact is False


def test_current_snapshot_excluded_from_baseline():
    pick = pick_baseline(
        _paths("2026-06-06", "2026-06-13"),
        since_days=7, current_date=date(2026, 6, 13),
    )
    assert pick.snapshot_date == date(2026, 6, 6)


def test_no_earlier_snapshot_returns_none():
    pick = pick_baseline(
        _paths("2026-06-13"), since_days=7, current_date=date(2026, 6, 13),
    )
    assert pick is None


def test_since_28d():
    pick = pick_baseline(
        _paths("2026-05-16", "2026-06-06", "2026-06-13"),
        since_days=28, current_date=date(2026, 6, 13),
    )
    assert pick.snapshot_date == date(2026, 5, 16)
    assert pick.exact is True


# ---- compute_deltas ---------------------------------------------------

def test_delta_signs_normalized_to_improvement():
    cur = [_row("a.com", pos=16.4, imp=8000)]
    base = [_row("a.com", pos=18.5, imp=0)]
    d = compute_deltas(cur, base)["a.com"]
    # pos improved (18.5 → 16.4): positive
    assert round(d.pos_delta, 1) == 2.1
    # imp rose 0 → 8000: positive
    assert d.imp_delta == 8000.0
    assert not d.pos_flat and not d.imp_flat


def test_regression_is_negative():
    cur = [_row("a.com", pos=20.0, imp=100)]
    base = [_row("a.com", pos=15.0, imp=900)]
    d = compute_deltas(cur, base)["a.com"]
    assert d.pos_delta == -5.0       # rank got worse
    assert d.imp_delta == -800.0


def test_new_domain_flagged_not_zero():
    cur = [_row("new.com", pos=10.0, imp=50)]
    d = compute_deltas(cur, baseline_rows=[])["new.com"]
    assert d.is_new is True
    assert d.pos_delta is None and d.imp_delta is None


def test_flat_within_noise_band():
    cur = [_row("a.com", pos=12.2, imp=1010)]
    base = [_row("a.com", pos=12.0, imp=1000)]  # +0.2 pos, +10 imp (1%)
    d = compute_deltas(cur, base)["a.com"]
    assert d.pos_flat is True       # < 0.5 band
    assert d.imp_flat is True       # < 5% of 1000


def test_imp_absolute_floor_keeps_tiny_moves_flat():
    cur = [_row("a.com", pos=5.0, imp=12)]
    base = [_row("a.com", pos=5.0, imp=8)]   # +4 imp; below abs floor of 5
    d = compute_deltas(cur, base)["a.com"]
    assert d.imp_flat is True


def test_missing_position_yields_none_pos_delta():
    cur = [_row("a.com", pos=None, imp=100)]
    base = [_row("a.com", pos=12.0, imp=80)]
    d = compute_deltas(cur, base)["a.com"]
    assert d.pos_delta is None
    assert d.imp_delta == 20.0
