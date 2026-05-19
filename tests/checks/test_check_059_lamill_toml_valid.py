"""Tests for CHECK_059 — lamill-toml-valid (v10.E)."""
from __future__ import annotations

from pathlib import Path

from portfolio.checks.deploy.check_059_lamill_toml_valid import run


def _make_site(tmp_path: Path, name: str = "example.com") -> Path:
    site = tmp_path / name
    site.mkdir()
    return site


def test_passes_on_clean_v1_file(tmp_path: Path):
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'
    )
    result = run(str(site))
    assert result.status == "pass"
    assert "cf-pages" in result.message


def test_fails_on_unknown_platform_enum(tmp_path: Path):
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "made-up"\n'
    )
    result = run(str(site))
    assert result.status == "fail"
    assert "invalid" in result.message
    assert "made-up" in result.message


def test_fails_on_missing_deploy_block(tmp_path: Path):
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text('schema = "lamill-toml-v1"\n')
    result = run(str(site))
    assert result.status == "fail"
    assert "deploy" in result.message


def test_fails_on_invalid_toml_syntax(tmp_path: Path):
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text("this = is not [valid")
    result = run(str(site))
    assert result.status == "fail"
    assert "invalid" in result.message


def test_fails_when_hostgator_missing_hosting_block(tmp_path: Path):
    """Platform=hostgator requires a [hosting] section — same error as load()."""
    site = _make_site(tmp_path)
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "hostgator"\n'
    )
    result = run(str(site))
    assert result.status == "fail"
    assert "hosting" in result.message.lower()


def test_warn_when_file_missing(tmp_path: Path):
    """CHECK_058 owns the presence verdict; this check warn-skips."""
    site = _make_site(tmp_path)
    result = run(str(site))
    assert result.status == "warn"
    assert "CHECK_058" in result.message


def test_warn_when_archived(tmp_path: Path):
    site = _make_site(tmp_path, "archived.example")
    (site / "TOMBSTONE.md").write_text("# archived\n")
    # Even with an invalid file, archived sites are skipped.
    (site / "lamill.toml").write_text("garbage = not valid")
    result = run(str(site))
    assert result.status == "warn"
    assert "archived" in result.message
