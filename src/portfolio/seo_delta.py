"""View-time Δ between dated SEO snapshots (`data/seo/<date>.json`).

Read-only over the snapshots `check seo` already keeps — no new storage.
Pairs the current snapshot against the nearest baseline on-or-before
today−N days and computes per-domain deltas for position + impressions.

Two consumers: `fleet seo --since` (renders the Δ column) and, later, the
weekly report. Both reuse `pick_baseline` + `compute_deltas`; rendering
(arrows / k-formatting / flat) lives in `check_render`, so the numeric
core here stays presentation-free and import-light (no `httpx`).

GSC is a 28-day rolling window, so two snapshots 7 days apart still share
~21 days of data — the Δ is a directional signal (is this site moving up
or down?), not an independent-period comparison.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

# Noise bands — a move smaller than this reads as "= flat" rather than a
# real trend. Position is an absolute rank; impressions need a relative
# band (a ±10 swing is noise at 8k imp, signal at 50) with an absolute
# floor so tiny-traffic sites don't show spurious arrows.
POS_FLAT_BAND = 0.5      # GSC average position (ranks)
IMP_FLAT_ABS = 5         # impressions: absolute floor
IMP_FLAT_REL = 0.05      # impressions: 5% of the baseline

_DATE_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\.json$")


@dataclass(frozen=True)
class BaselinePick:
    """The snapshot chosen as the Δ baseline, plus how far back it sits."""
    path: Path
    snapshot_date: date
    gap_days: int          # current_date − snapshot_date (the lookback actually used)
    exact: bool            # snapshot_date == current_date − since_days
    since_days: int        # what was requested


@dataclass(frozen=True)
class DomainDelta:
    """Per-domain Δ. Positive == improvement for BOTH metrics (position
    improvement is a *drop* in rank; impression improvement is a *rise* in
    count), so the renderer applies one ▲/▼ convention to either. A domain
    absent from the baseline is `is_new` — never a fake 0."""
    is_new: bool
    pos_delta: float | None    # baseline_pos − current_pos  (>0 == improved)
    imp_delta: float | None    # current_imp − baseline_imp  (>0 == improved)
    pos_flat: bool
    imp_flat: bool


def _date_from_path(p: Path) -> date | None:
    m = _DATE_RE.search(p.name)
    if not m:
        return None
    y, mo, d = (int(x) for x in m.group(1).split("-"))
    return date(y, mo, d)


def snapshot_dates(paths) -> list[tuple[date, Path]]:
    """`[(date, path), …]` for every `YYYY-MM-DD.json` in `paths`, ascending."""
    dated = [(d, p) for p in paths if (d := _date_from_path(p)) is not None]
    dated.sort(key=lambda x: x[0])
    return dated


def pick_baseline(paths, *, since_days: int, current_date: date) -> BaselinePick | None:
    """Pick the Δ baseline snapshot from `paths`.

    Primary rule: the nearest snapshot on-or-before `current_date − since_days`
    (closest-earlier when the exact date is missing). If no snapshot reaches
    that far back yet, fall back to the *oldest* snapshot available and report
    the smaller `gap_days` actually used — so a fresh history degrades to "5d
    actual" rather than no Δ at all. The current snapshot itself is excluded
    (a baseline must predate it). Returns None when there is no earlier
    snapshot to diff against.
    """
    dated = [(d, p) for d, p in snapshot_dates(paths) if d < current_date]
    if not dated:
        return None
    ideal = current_date - timedelta(days=since_days)
    on_or_before = [(d, p) for d, p in dated if d <= ideal]
    if on_or_before:
        chosen_date, chosen_path = max(on_or_before, key=lambda x: x[0])
    else:
        # No history reaches back N days — use the oldest we have.
        chosen_date, chosen_path = min(dated, key=lambda x: x[0])
    return BaselinePick(
        path=chosen_path,
        snapshot_date=chosen_date,
        gap_days=(current_date - chosen_date).days,
        exact=(chosen_date == ideal),
        since_days=since_days,
    )


def _imp_band(baseline_imp: float) -> float:
    return max(IMP_FLAT_ABS, IMP_FLAT_REL * (baseline_imp or 0))


def compute_deltas(current_rows, baseline_rows) -> dict[str, DomainDelta]:
    """Map `domain (lower) → DomainDelta`, current vs baseline.

    `current_rows` / `baseline_rows` are any objects exposing `.domain`,
    `.gsc_position`, `.gsc_impressions` (SEORow or a stand-in). Domains in
    `current_rows` but not `baseline_rows` get `is_new=True`. A None on
    either side of position yields `pos_delta=None` (rendered `—`).
    """
    base = {r.domain.lower(): r for r in baseline_rows}
    out: dict[str, DomainDelta] = {}
    for r in current_rows:
        b = base.get(r.domain.lower())
        if b is None:
            out[r.domain.lower()] = DomainDelta(
                is_new=True, pos_delta=None, imp_delta=None,
                pos_flat=False, imp_flat=False,
            )
            continue

        pos_delta: float | None = None
        pos_flat = False
        if r.gsc_position is not None and b.gsc_position is not None:
            pos_delta = b.gsc_position - r.gsc_position
            pos_flat = abs(pos_delta) < POS_FLAT_BAND

        cur_imp = r.gsc_impressions or 0
        base_imp = b.gsc_impressions or 0
        imp_delta = float(cur_imp - base_imp)
        imp_flat = abs(imp_delta) <= _imp_band(base_imp)

        out[r.domain.lower()] = DomainDelta(
            is_new=False, pos_delta=pos_delta, imp_delta=imp_delta,
            pos_flat=pos_flat, imp_flat=imp_flat,
        )
    return out


def load_baseline_rows(pick: BaselinePick):
    """Read + deserialize the baseline snapshot's SEORow list.

    Lazy-imports `seo_cache` (which pulls `seo_runtime`/`httpx`) so the
    numeric core above stays usable without the runtime deps installed.
    """
    from . import seo_cache
    return seo_cache.rows_from_snapshot(seo_cache.load_snapshot(pick.path))
