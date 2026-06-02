"""v28.D — topical-fit recommendation + premium-not-highlighted.

Operator rule (2026-06-01): a topic-matched TLD available UNDER the price
cap is recommended (beats the generic cheap lane); a topic-matched TLD
OVER the cap is shown + manually pickable but never the auto-recommendation
(operator picks it only in rare cases).
"""
from __future__ import annotations

from portfolio.suggest import (
    CellState,
    GridRow,
    _decide_pick,
    filter_pickable_rows,
)


def _cell(tld: str, available, *, over_max=False, price=10.0) -> CellState:
    return CellState(domain=f"x{tld}", available=available, price=price,
                     renewal=price, over_max=over_max)


# ---- _decide_pick ----------------------------------------------------


def test_undercap_topical_beats_cheap():
    cols = [".com", ".app", ".dev", ".xyz", ".family"]
    cells = {
        ".com": _cell(".com", False), ".app": _cell(".app", False),
        ".dev": _cell(".dev", False),
        ".xyz": _cell(".xyz", True),            # cheap, available
        ".family": _cell(".family", True),       # topical, under cap
    }
    pick, label, why = _decide_pick("x", cells, cols, None, 20.0)
    assert pick == ".family" and "topical fit" in why


def test_premium_com_still_wins_over_topical():
    cols = [".com", ".family"]
    cells = {".com": _cell(".com", True), ".family": _cell(".family", True)}
    pick, _, why = _decide_pick("x", cells, cols, None, 20.0)
    assert pick == ".com"


def test_overcap_topical_is_not_auto_picked():
    cols = [".com", ".xyz", ".fm"]
    cells = {
        ".com": _cell(".com", False), ".xyz": _cell(".xyz", False),
        ".fm": _cell(".fm", True, over_max=True, price=88.0),  # premium topical
    }
    pick, label, why = _decide_pick("x", cells, cols, None, 20.0)
    assert pick is None              # NOT recommended
    assert label == "—"
    assert "pick manually" in why    # shown as a note, not a highlight


def test_undercap_topical_picked_even_when_overcap_topical_also_present():
    cols = [".family", ".fm"]
    cells = {
        ".family": _cell(".family", True),                      # under cap
        ".fm": _cell(".fm", True, over_max=True, price=88.0),    # premium
    }
    pick, _, why = _decide_pick("x", cells, cols, None, 20.0)
    assert pick == ".family" and "topical fit" in why


# ---- filter_pickable_rows -------------------------------------------


def _row(cells: dict) -> GridRow:
    return GridRow(name="x", strategy="s", cells=cells)


def test_row_with_only_overcap_topical_is_kept():
    row = _row({".fm": _cell(".fm", True, over_max=True, price=88.0)})
    assert filter_pickable_rows([row]) == [row]   # premium topical → still shown


def test_row_with_only_overcap_nontopical_is_dropped():
    # .shop is over cap and NOT topical → row has no actionable pick → dropped
    row = _row({".shop": _cell(".shop", True, over_max=True, price=40.0)})
    assert filter_pickable_rows([row]) == []


def test_row_with_undercap_available_is_kept():
    row = _row({".xyz": _cell(".xyz", True)})
    assert filter_pickable_rows([row]) == [row]
