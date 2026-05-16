"""Tests for v8.D — `lamill settings operator show` CLI surface."""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio.cli import app


def _write_lamill_toml(tmp_path: Path, content: str) -> Path:
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent(content).strip() + "\n")
    return f


def _patch_lamill_path(monkeypatch, path: Path) -> None:
    import portfolio.operator_profile as op
    monkeypatch.setattr(op, "LAMILL_TOML", path)


def test_show_reports_no_profile_when_file_missing(monkeypatch, tmp_path):
    _patch_lamill_path(monkeypatch, tmp_path / "lamill.toml")
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    assert "No operator profile configured" in result.stdout


def test_show_reports_no_profile_when_only_defaults(monkeypatch, tmp_path):
    """A file with all-default enum values + empty expertise still reads
    as 'no profile' — operator hasn't actually said anything yet."""
    f = _write_lamill_toml(tmp_path, """
        [operator]
        workflow_preference = "mixed"
        motivation_cadence = "monthly"
    """)
    _patch_lamill_path(monkeypatch, f)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    assert "No operator profile configured" in result.stdout


def test_show_prints_full_profile(monkeypatch, tmp_path):
    f = _write_lamill_toml(tmp_path, """
        [operator]
        expertise = ["SEO and programmatic content", "Python CLI tooling"]
        workflow_preference = "builder"
        motivation_cadence = "weekly"
    """)
    _patch_lamill_path(monkeypatch, f)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Operator profile" in out
    assert "SEO and programmatic content" in out
    assert "Python CLI tooling" in out
    assert "builder" in out
    assert "weekly" in out


def test_show_prints_partial_profile_with_defaults(monkeypatch, tmp_path):
    """Only expertise set — other fields render at their defaults."""
    f = _write_lamill_toml(tmp_path, """
        [operator]
        expertise = ["Python"]
    """)
    _patch_lamill_path(monkeypatch, f)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Python" in out
    assert "mixed" in out
    assert "monthly" in out


def test_show_renders_no_expertise_when_only_enums_set(monkeypatch, tmp_path):
    f = _write_lamill_toml(tmp_path, """
        [operator]
        workflow_preference = "writer"
        motivation_cadence = "quarterly"
    """)
    _patch_lamill_path(monkeypatch, f)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    out = result.stdout
    assert "Operator profile" in out
    assert "writer" in out
    assert "quarterly" in out


def test_show_lists_each_expertise_item_on_own_line(monkeypatch, tmp_path):
    f = _write_lamill_toml(tmp_path, """
        [operator]
        expertise = ["alpha", "beta", "gamma"]
    """)
    _patch_lamill_path(monkeypatch, f)
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "operator", "show"])
    assert result.exit_code == 0
    for item in ("alpha", "beta", "gamma"):
        assert item in result.stdout
