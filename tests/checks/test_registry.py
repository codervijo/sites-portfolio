"""Tests for v5.A — universal check registry."""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio.checks import (
    CheckResult,
    CheckSpec,
    get_check,
    list_checks,
    reset_cache,
    run_check,
    run_checks,
)
from portfolio.checks.config import CheckConfig, load_config


def test_discovery_finds_initial_checks():
    """v5.A ships 17 checks: 12 scaffold + 5 git."""
    specs = list_checks()
    ids = [s.id for s in specs]
    # All expected scaffold IDs
    for n in range(1, 13):
        assert f"CHECK_{n:03d}" in ids
    # All expected git IDs
    for n in (20, 21, 22, 23, 24):
        assert f"CHECK_{n:03d}" in ids
    # Sorted by ID
    assert ids == sorted(ids)


def test_check_specs_have_required_fields():
    for s in list_checks():
        assert isinstance(s, CheckSpec)
        assert s.id.startswith("CHECK_")
        assert s.name
        assert s.category in ("scaffold", "docs", "git", "ci", "stack",
                              "deploy", "seo", "content", "live")
        assert s.severity in ("error", "warn", "info")
        assert callable(s.run)
        assert s.module_name.startswith("portfolio.checks.")


def test_list_checks_filter_by_category():
    scaffold = list_checks(category="scaffold")
    git = list_checks(category="git")
    docs = list_checks(category="docs")
    ci = list_checks(category="ci")
    # CHECK_005-008 moved to docs; CHECK_024 moved to ci.
    # v6.A.1: CHECK_013 ai-agents-versioning added to scaffold (now 9).
    # CHECK_040 (git-remote-name), CHECK_041 (dir-matches-portfolio),
    # CHECK_042 (live-final-url-matches) added to git (now 8).
    assert len(scaffold) == 9
    assert len(git) == 8
    assert len(docs) >= 4
    assert len(ci) == 1
    for s in scaffold:
        assert s.category == "scaffold"
    for s in git:
        assert s.category == "git"


def test_list_checks_filter_by_ids():
    out = list_checks(ids=["CHECK_001", "CHECK_020"])
    assert [s.id for s in out] == ["CHECK_001", "CHECK_020"]


def test_get_check_known_id():
    spec = get_check("CHECK_001")
    assert spec.name == "has-readme"
    assert spec.category == "scaffold"


def test_get_check_unknown_id_raises():
    with pytest.raises(KeyError):
        get_check("CHECK_999")


def test_run_check_returns_check_result(tmp_path):
    # tmp_path has no README.md — CHECK_001 fails
    result = run_check("CHECK_001", str(tmp_path))
    assert isinstance(result, CheckResult)
    assert result.status == "fail"


def test_run_check_traps_exceptions(tmp_path, monkeypatch):
    """If a check's run() raises, registry returns a warn-status result."""
    # Patch the source module's `run` — discovery captures it by reference at
    # cache time, so we also need to patch the cached CheckSpec by rebuilding
    # the cache. Simpler: reset_cache, patch the module, then re-run.
    import portfolio.checks.scaffold.check_001_has_readme as src
    def boom(_path):
        raise RuntimeError("synthetic")
    monkeypatch.setattr(src, "run", boom)
    reset_cache()
    result = run_check("CHECK_001", str(tmp_path))
    assert result.status == "warn"
    assert "synthetic" in result.message or "RuntimeError" in result.message
    # Tidy up so subsequent tests get a fresh cache.
    reset_cache()


def test_run_checks_multiple(tmp_path):
    out = run_checks(str(tmp_path), category="scaffold")
    # All scaffold checks ran (count derived from registry to avoid drift)
    from portfolio.checks import list_checks as _list
    expected = len(_list(category="scaffold"))
    assert len(out) == expected
    # All return CheckResult
    for cid, r in out.items():
        assert isinstance(r, CheckResult)


def test_run_checks_skip_filter(tmp_path):
    out = run_checks(str(tmp_path), category="scaffold",
                     skip_checks=["CHECK_001", "CHECK_002"])
    assert out["CHECK_001"].status == "warn"
    assert "skipped" in out["CHECK_001"].message.lower()
    assert out["CHECK_002"].status == "warn"
    # Others actually ran
    assert "skipped" not in out["CHECK_003"].message.lower() or out["CHECK_003"].status == "fail"


def test_reset_cache_re_discovers():
    """reset_cache() forces re-discovery on next access (used in tests
    that monkey with the catalog)."""
    n_before = len(list_checks())
    reset_cache()
    n_after = len(list_checks())
    assert n_before == n_after  # idempotent


# ---------- config.toml ----------


def test_load_config_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "no.toml")
    assert isinstance(cfg, CheckConfig)
    assert cfg.repos_dir.name == "sites"  # default ~/work/projects/sites
    assert cfg.github_token == ""
    assert cfg.skip_checks == []


def test_load_config_parses_toml(tmp_path):
    p = tmp_path / "config.toml"
    p.write_text(
        '[git]\n'
        'repos_dir = "/tmp/repos"\n'
        'github_token = "ghp_xxx"\n'
        'skip_checks = ["CHECK_024", "CHECK_011"]\n'
    )
    cfg = load_config(p)
    assert cfg.repos_dir == Path("/tmp/repos")
    assert cfg.github_token == "ghp_xxx"
    assert cfg.skip_checks == ["CHECK_024", "CHECK_011"]


def test_load_config_expanduser():
    """`~/...` paths get expanded on load."""
    import tempfile, os
    with tempfile.NamedTemporaryFile(mode="w", suffix=".toml", delete=False) as f:
        f.write('[git]\nrepos_dir = "~/somedir"\n')
        f.flush()
        cfg = load_config(Path(f.name))
    os.unlink(f.name)
    assert "~" not in str(cfg.repos_dir)
    assert "somedir" in str(cfg.repos_dir)


def test_load_config_malformed_toml_returns_defaults(tmp_path):
    p = tmp_path / "broken.toml"
    p.write_text("this is = not [valid toml")
    cfg = load_config(p)
    # Doesn't raise — falls back to defaults
    assert cfg.github_token == ""


# ---------- portfolio checks {list, describe, run} CLI ----------


def test_cli_checks_list_shows_all(capsys):
    """`portfolio checks list` enumerates every catalog entry."""
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "list"])
    assert result.exit_code == 0
    out = result.stdout
    # All 17 IDs appear
    for n in (1, 2, 3, 12, 20, 21, 24):
        assert f"CHECK_{n:03d}" in out


def test_cli_checks_list_filters_by_category():
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "list", "--category", "git"])
    assert result.exit_code == 0
    out = result.stdout
    assert "CHECK_020" in out
    assert "CHECK_001" not in out  # scaffold filtered out


def test_cli_checks_list_json():
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "list", "--json"])
    assert result.exit_code == 0
    import json as _json
    parsed = _json.loads(result.stdout)
    assert isinstance(parsed, list)
    assert all("id" in e and "name" in e and "severity" in e for e in parsed)
    ids = [e["id"] for e in parsed]
    assert "CHECK_001" in ids


def test_cli_checks_describe_known_id():
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "describe", "CHECK_006"])
    assert result.exit_code == 0
    out = result.stdout
    assert "CHECK_006" in out
    assert "has-docs-claude" in out
    assert "scaffold" in out


def test_cli_checks_describe_unknown_id():
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "describe", "CHECK_999"])
    assert result.exit_code == 1
    assert "Unknown check" in result.stdout


def test_cli_checks_run_against_tmp(tmp_path):
    from typer.testing import CliRunner

    from portfolio.cli import app
    (tmp_path / "README.md").write_text("# x")
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "run", str(tmp_path),
                                  "--category", "scaffold"])
    assert result.exit_code == 0
    out = result.stdout
    # CHECK_001 passes (we wrote README.md)
    assert "CHECK_001" in out
    assert "pass" in out
    # CHECK_002 fails (no AI_AGENTS.md)
    assert "CHECK_002" in out
    assert "fail" in out


def test_cli_checks_run_single_check_filter(tmp_path):
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "run", str(tmp_path),
                                  "--check", "CHECK_001"])
    assert result.exit_code == 0
    out = result.stdout
    assert "CHECK_001" in out
    # No other checks ran
    assert "CHECK_002" not in out
    assert "CHECK_020" not in out


def test_cli_checks_run_json(tmp_path):
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "run", str(tmp_path),
                                  "--check", "CHECK_001", "--json"])
    assert result.exit_code == 0
    import json as _json
    parsed = _json.loads(result.stdout)
    assert "CHECK_001" in parsed
    assert parsed["CHECK_001"]["status"] == "fail"


def test_cli_checks_run_missing_path_errors():
    from typer.testing import CliRunner

    from portfolio.cli import app
    runner = CliRunner()
    result = runner.invoke(app, ["settings", "catalog", "run", "/nonexistent/path/xyz"])
    assert result.exit_code == 2
    assert "not found" in result.stdout.lower()
