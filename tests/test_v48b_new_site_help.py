"""v48.B — `lamill new --help` carries the start-a-new-site walkthrough."""
from __future__ import annotations

from typer.testing import CliRunner

from portfolio.cli import LOVABLE_PLACEHOLDERS, NEW_SITE_STEPS, app

runner = CliRunner()


def _plain(out: str) -> str:
    return " ".join(out.split())


def test_new_help_lists_every_step_in_order():
    res = runner.invoke(app, ["new", "--help"], env={"COLUMNS": "200"})
    assert res.exit_code == 0
    out = _plain(res.output)
    assert "Start a new site" in out
    positions = [out.index(cmd) for cmd, _ in NEW_SITE_STEPS]
    assert positions == sorted(positions)
    for ph in LOVABLE_PLACEHOLDERS:
        assert ph in out


def test_root_help_points_at_walkthrough():
    res = runner.invoke(app, ["--help"], env={"COLUMNS": "200"})
    assert res.exit_code == 0
    assert "lamill new --help" in _plain(res.output)
