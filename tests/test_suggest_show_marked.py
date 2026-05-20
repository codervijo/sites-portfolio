"""Tests for the new `s. Show marked names as full grid` menu option
in `lamill new domain`'s post-grid menu.

Renders the shortlist as a full registrar grid (same columns as the
main grid) so the operator can compare marked names side-by-side
with per-TLD cells / anchors / picks / rationale. Distinct from the
brief "Shortlist (N):" lines printed inside `_menu_shortlist` after
each mark — that one's just name + pick + price.
"""
from __future__ import annotations

import io

from rich.console import Console

from portfolio import cli as cli_mod
from portfolio.suggest import GridRow


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=140, force_terminal=False)


def _row(name: str) -> GridRow:
    """Smallest GridRow that `_render_grid` reads without erroring."""
    return GridRow(name=name, strategy="anchor", cells={},
                   pick_tld=None, pick_label="", why="",
                   anchors_matched=[])


def _patch_console(monkeypatch) -> Console:
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    return cap


# ---------- happy path ----------


def test_show_marked_renders_only_shortlisted_rows(monkeypatch):
    """Only names in `shortlist` end up in the rendered grid, in the
    order they were marked (the shortlist's order is preserved)."""
    cap = _patch_console(monkeypatch)
    all_rows = [_row(n) for n in ["alpha", "beta", "gamma", "delta", "epsilon"]]
    shortlist = ["gamma", "alpha", "epsilon"]

    cli_mod._menu_show_marked(all_rows, shortlist, [".com"],
                              show_renewal=False)
    out = cap.file.getvalue()
    # Marked names appear.
    assert "gamma" in out
    assert "alpha" in out
    assert "epsilon" in out
    # Unmarked names do NOT appear.
    assert "beta" not in out
    assert "delta" not in out
    # Order preserved — gamma was first in shortlist.
    gamma_idx = out.index("gamma")
    alpha_idx = out.index("alpha")
    assert gamma_idx < alpha_idx


def test_show_marked_passes_topic_to_grid(monkeypatch):
    """When `topic` is passed, the renderer's Topic-line affordance
    (added earlier this session) fires above the marked grid too."""
    cap = _patch_console(monkeypatch)
    cli_mod._menu_show_marked(
        [_row("alpha"), _row("beta")], ["alpha"], [".com"],
        show_renewal=False, topic="annuity compliance saas",
    )
    out = cap.file.getvalue()
    assert "Topic:" in out
    assert "annuity compliance saas" in out


# ---------- edge cases ----------


def test_show_marked_empty_shortlist_explains_what_to_do(monkeypatch):
    """No marks → tell the operator to use option 6, don't render an
    empty grid (Rich would print just a header row, which is uglier
    than a clear "mark first" message)."""
    cap = _patch_console(monkeypatch)
    cli_mod._menu_show_marked(
        [_row("alpha")], [], [".com"], show_renewal=False,
    )
    out = cap.file.getvalue()
    assert "empty" in out.lower()
    assert "option 6" in out


def test_show_marked_all_names_missing_explains_re_mark(monkeypatch):
    """If the shortlist holds names that aren't in current rows (e.g.
    a widen pass replaced them), tell the operator to re-mark — don't
    render an empty grid."""
    cap = _patch_console(monkeypatch)
    cli_mod._menu_show_marked(
        [_row("alpha")],            # current grid has alpha only
        ["beta", "gamma"],          # neither marked name is in grid
        [".com"], show_renewal=False,
    )
    out = cap.file.getvalue()
    # "None of the N marked names are in the current grid..."
    assert "None of" in out
    assert "current grid" in out
    assert "Re-mark" in out


def test_show_marked_partial_missing_renders_what_it_can(monkeypatch):
    """Some marked names in current grid, some missing → render the
    ones we have and footnote the missing names so the operator knows
    they were dropped (rather than silently showing fewer rows than
    they marked)."""
    cap = _patch_console(monkeypatch)
    cli_mod._menu_show_marked(
        [_row("alpha"), _row("beta")],
        ["alpha", "gamma", "delta"],   # gamma + delta missing
        [".com"], show_renewal=False,
    )
    out = cap.file.getvalue()
    # The one match renders.
    assert "alpha" in out
    # And the missing ones get called out.
    assert "Note:" in out
    assert "gamma" in out
    assert "delta" in out


def test_show_marked_caps_missing_sample_at_5(monkeypatch):
    """When many marked names are missing, the footnote shows the
    first 5 + a "+ N more" count — keeps the message tractable."""
    cap = _patch_console(monkeypatch)
    cli_mod._menu_show_marked(
        [_row("alpha")],
        ["alpha"] + [f"missing-{i}" for i in range(8)],
        [".com"], show_renewal=False,
    )
    out = cap.file.getvalue()
    assert "+ 3 more" in out


# ---------- menu wiring sanity ----------


def test_menu_items_contains_s_key():
    """The `s. Show marked names as full grid` entry is registered
    in MENU_ITEMS so `_render_menu` lists it. Position is between 7
    and 8 — between the two shortlist-related actions and the static
    info options — but the exact position is render-time only;
    the contract is that the key exists with the expected label."""
    keys = {key: label for key, label, _ in cli_mod.MENU_ITEMS}
    assert "s" in keys
    assert "Show marked" in keys["s"]


def test_render_menu_appends_count_suffix_on_s_when_shortlist_nonempty(monkeypatch):
    """Same suffix the existing item 6 gets — `(N marked)` — appears
    on item `s` too when the shortlist is non-empty."""
    cap = _patch_console(monkeypatch)
    cli_mod._render_menu(shortlist_count=12)
    out = cap.file.getvalue()
    # Item `s` line carries the count.
    s_line = next(line for line in out.split("\n") if line.lstrip().startswith("s."))
    assert "12 marked" in s_line


def test_render_menu_no_suffix_on_s_when_shortlist_empty(monkeypatch):
    cap = _patch_console(monkeypatch)
    cli_mod._render_menu(shortlist_count=0)
    out = cap.file.getvalue()
    s_line = next(line for line in out.split("\n") if line.lstrip().startswith("s."))
    # The label itself contains the word "marked" ("Show marked names
    # as full grid"); what we want to assert is that no `(N marked)`
    # suffix has been appended on top of the label.
    import re
    assert re.search(r"\(\d+ marked\)", s_line) is None
