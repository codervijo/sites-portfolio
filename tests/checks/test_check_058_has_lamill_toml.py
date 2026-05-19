"""Tests for CHECK_058 — has-lamill-toml (v10.E)."""
from __future__ import annotations

from pathlib import Path

from portfolio.checks.deploy.check_058_has_lamill_toml import run


def _make_site(tmp_path: Path, name: str = "example.com") -> Path:
    site = tmp_path / name
    site.mkdir()
    return site


def test_passes_when_lamill_toml_present(tmp_path: Path):
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'
    )
    result = run(str(site))
    assert result.status == "pass"
    assert "lamill.toml" in result.message


def test_fails_when_lamill_toml_missing(tmp_path: Path):
    site = _make_site(tmp_path)
    result = run(str(site))
    assert result.status == "fail"
    assert "missing lamill.toml" in result.message
    # Failure message points the operator at the fix command.
    assert "set-deploy" in result.message


def test_warn_when_archived_tombstone(tmp_path: Path):
    site = _make_site(tmp_path, "archived.example")
    (site / "TOMBSTONE.md").write_text("# archived\n")
    # File is absent; without the archive skip this would fail.
    result = run(str(site))
    assert result.status == "warn"
    assert "archived" in result.message
