"""Tests for the `Topic:` title line on the `new suggest` registrar grid.

Operator-facing affordance — when scanning the grid, the topic is on
its own one-liner just above the table (same shape as `new research`).
Mirrors the renderer tests in test_synthesis_guardrails.py; the
fixture builds a single minimal GridRow so the renderer has something
to draw.
"""
from __future__ import annotations

import io

from rich.console import Console

from portfolio import cli as cli_mod
from portfolio.suggest import GridRow


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


def _one_row() -> GridRow:
    """Smallest GridRow that satisfies `_render_grid`'s field reads —
    `cells.get(c)`, `anchors_matched`, `pick_label`, `why`, `name`."""
    return GridRow(name="example.com", strategy="anchor",
                   cells={}, pick_tld=None, pick_label="",
                   why="", anchors_matched=[])


def _patch_capturing_console(monkeypatch) -> Console:
    """`_render_grid` writes to `cli.console` (module-level Console),
    not a passed-in handle. Monkeypatch the global with a StringIO-
    backed Console so the tests can read the rendered output."""
    cap = _capturing_console()
    monkeypatch.setattr(cli_mod, "console", cap)
    return cap


def test_render_grid_with_topic_shows_topic_line_above_table(monkeypatch):
    """When `topic` is passed, the renderer emits a `Topic: <value>`
    line immediately above the grid table."""
    cap = _patch_capturing_console(monkeypatch)
    cli_mod._render_grid([_one_row()], [".com"],
                         topic="cordless drill comparison")
    out = cap.file.getvalue()
    assert "Topic:" in out
    assert "cordless drill comparison" in out
    # The Topic line must precede the row content (the example name
    # appears in the table body).
    topic_idx = out.index("Topic:")
    row_idx = out.index("example.com")
    assert topic_idx < row_idx


def test_render_grid_without_topic_omits_topic_line(monkeypatch):
    """No `topic` kwarg → no Topic line. Preserves backward
    compatibility with any caller that doesn't have the topic in
    scope (and keeps test runs that exercise the renderer in isolation
    from spraying an extra label)."""
    cap = _patch_capturing_console(monkeypatch)
    cli_mod._render_grid([_one_row()], [".com"])   # no topic
    out = cap.file.getvalue()
    assert "Topic:" not in out
    # The row still renders.
    assert "example.com" in out


def test_render_grid_empty_topic_string_omits_topic_line(monkeypatch):
    """An empty/whitespace topic shouldn't print a `Topic:` line with
    no value beside it — falsy string is treated the same as None."""
    cap = _patch_capturing_console(monkeypatch)
    cli_mod._render_grid([_one_row()], [".com"], topic="")
    out = cap.file.getvalue()
    assert "Topic:" not in out
