"""Tests for v5.B — `portfolio check --git` cross-repo runner."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio.cli import app


def _git_init(path: Path, with_commit: bool = True) -> None:
    """Spin up a fresh git repo at `path`."""
    import os
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "Tester", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "Tester", "GIT_COMMITTER_EMAIL": "t@e.com"}
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    if with_commit:
        (path / "README.md").write_text("# repo\n")
        subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=env)
        subprocess.run(["git", "commit", "-q", "-m", "initial"],
                       cwd=path, check=True, env=env)


def _make_repos_dir(tmp_path: Path, repo_names: list[str]) -> Path:
    """Build a fake repos_dir with the given repo names. Each repo has a
    minimal scaffold (just enough to pass some checks)."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    for name in repo_names:
        d = repos_dir / name
        _git_init(d)
    return repos_dir


def _patch_repos_dir(monkeypatch, repos_dir: Path) -> None:
    """Stub `load_config()` to return a CheckConfig pointing at the test repos_dir.

    `_run_check_git_mode` does `from .checks import load_config` lazily,
    which resolves to `portfolio.checks.load_config` — a name re-exported
    from `portfolio.checks.config`. We patch the re-exported binding so the
    lazy import in cli.py picks up the stub.
    """
    from portfolio.checks.config import CheckConfig
    cfg = CheckConfig(repos_dir=repos_dir, github_token="",
                      skip_checks=[], ignore_repos=[])
    import portfolio.checks as checks_pkg
    monkeypatch.setattr(checks_pkg, "load_config",
                        lambda path=None: cfg)


# ---------- summary mode ----------


def test_v5b_git_summary_mode_lists_repos(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["alpha-repo", "beta-repo"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 0
    out = result.stdout
    assert "alpha-repo" in out
    assert "beta-repo" in out
    # Score column now shows passes/applicable (applicable = total minus
    # checks that returned "skipped" for that repo, e.g. astro-version on
    # a Vite project). The header still names the catalog size in
    # "Running N check(s)" — assert that instead.
    from portfolio.cli import _GIT_FLAG_CATEGORIES
    from portfolio.checks import list_checks
    expected_n = sum(1 for s in list_checks() if s.category in _GIT_FLAG_CATEGORIES)
    assert f"{expected_n} check(s)" in out


def test_v5b_git_summary_skips_hidden_dirs(tmp_path, monkeypatch):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _git_init(repos_dir / "real-repo")
    (repos_dir / ".hidden").mkdir()
    (repos_dir / "node_modules").mkdir()
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 0
    out = result.stdout
    assert "real-repo" in out
    assert ".hidden" not in out
    assert "node_modules" not in out


def test_v5b_git_summary_orders_by_score_ascending(tmp_path, monkeypatch):
    """Worst score first so problems jump out."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    # bare repo (no scaffold files) — low score
    _git_init(repos_dir / "bare")
    # complete repo — high score
    full = repos_dir / "fully-scaffolded"
    _git_init(full)
    (full / "AI_AGENTS.md").write_text("## Building info\n## Deployment info\n")
    (full / "docs").mkdir()
    for fn in ("prd.md", "CLAUDE.md", "Prompts.md", "growth.md"):
        (full / "docs" / fn).write_text("ok")
    (full / ".gitignore").write_text("node_modules\n")
    (full / "tests").mkdir()
    (full / ".env.example").write_text("FOO=bar\n")
    (full / "Makefile").write_text("PROJ := full\n%:\n\t$(MAKE) -C .. $@\n")
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 0
    out = result.stdout
    # bare appears before fully-scaffolded
    assert out.find("bare") < out.find("fully-scaffolded")


# ---------- --check single-check mode ----------


def test_v5b_git_single_check_filter(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a", "b"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--check", "CHECK_001"])
    assert result.exit_code == 0
    out = result.stdout
    # Each repo appears with a status for CHECK_001 specifically
    assert "CHECK_001" in out
    assert "a" in out and "b" in out
    # Other checks should NOT be in the output
    assert "CHECK_005" not in out
    assert "CHECK_020" not in out


def test_v5b_git_unknown_check_id_errors(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--check", "CHECK_999"])
    assert result.exit_code == 2
    assert "Unknown check" in result.stdout


# ---------- --repo single-repo mode ----------


def test_v5b_git_repo_mode_runs_one(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a", "b", "c"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--repo", "b"])
    assert result.exit_code == 0
    out = result.stdout
    # Only "b" should be in the output
    assert "b" in out
    # Every check should appear (full breakdown)
    for cid in ("CHECK_001", "CHECK_002", "CHECK_005", "CHECK_020"):
        assert cid in out


def test_v5b_git_repo_mode_unknown_repo_errors(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--repo", "ghost"])
    assert result.exit_code == 2
    assert "ghost" in result.stdout


# ---------- --domain as a synonym for --repo ----------


def test_git_accepts_domain_as_synonym_for_repo(tmp_path, monkeypatch):
    """`--git --domain=foo` should behave the same as `--git --repo=foo`."""
    repos_dir = _make_repos_dir(tmp_path, ["alpha", "beta"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--domain", "alpha"])
    assert result.exit_code == 0
    out = result.stdout
    # Single-repo detail mode renders the alpha repo's check list.
    assert "alpha" in out
    # Should NOT show the cross-repo summary table title.
    assert "26 repos" not in out  # no cross-repo run
    # Should NOT include 'beta' (we filtered to alpha).
    assert " beta " not in out


def test_git_repo_and_domain_conflict_errors(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, [
        "check", "--git",
        "--repo", "alpha",
        "--domain", "beta",
    ])
    assert result.exit_code == 2
    assert "synonyms" in result.stdout.lower() or "disagree" in result.stdout.lower()


def test_git_repo_equals_domain_does_not_conflict(tmp_path, monkeypatch):
    """Same value passed to both flags is fine — they mean the same thing."""
    repos_dir = _make_repos_dir(tmp_path, ["alpha"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, [
        "check", "--git",
        "--repo", "alpha",
        "--domain", "alpha",
    ])
    assert result.exit_code == 0


# ---------- --detail mode ----------


def test_v5b_git_detail_shows_per_repo_breakdown(tmp_path, monkeypatch):
    repos_dir = _make_repos_dir(tmp_path, ["a", "b"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git", "--detail"])
    assert result.exit_code == 0
    out = result.stdout
    # Each repo gets its own table
    assert out.count("CHECK_001") >= 2  # one per repo
    # Pass/fail counts per repo
    assert "pass" in out


# ---------- error paths ----------


def test_v5b_git_missing_repos_dir_errors(tmp_path, monkeypatch):
    """Configured repos_dir doesn't exist on disk."""
    repos_dir = tmp_path / "nope"
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 2
    assert "repos_dir not found" in result.stdout


def test_v5b_git_empty_repos_dir(tmp_path, monkeypatch):
    repos_dir = tmp_path / "empty"
    repos_dir.mkdir()
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 1
    assert "No repos" in result.stdout


# ---------- iter helper ----------


def test_iterate_repos_filters_hidden_and_special(tmp_path):
    from portfolio.cli import _iterate_repos
    (tmp_path / "real").mkdir()
    (tmp_path / ".git").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "tarball").mkdir()
    (tmp_path / "file.txt").write_text("not a dir")
    repos = _iterate_repos(tmp_path)
    names = [p.name for p in repos]
    assert names == ["real"]


def test_iterate_repos_returns_empty_for_missing_dir(tmp_path):
    from portfolio.cli import _iterate_repos
    assert _iterate_repos(tmp_path / "nope") == []


def test_iterate_repos_honors_ignore_list(tmp_path):
    from portfolio.cli import _iterate_repos
    (tmp_path / "alpha").mkdir()
    (tmp_path / "portfolio").mkdir()
    (tmp_path / "beta").mkdir()
    repos = _iterate_repos(tmp_path, ignore=["portfolio"])
    names = [p.name for p in repos]
    assert names == ["alpha", "beta"]


def test_iterate_repos_ignore_is_case_insensitive(tmp_path):
    from portfolio.cli import _iterate_repos
    (tmp_path / "Portfolio").mkdir()
    (tmp_path / "real").mkdir()
    repos = _iterate_repos(tmp_path, ignore=["portfolio"])
    names = [p.name for p in repos]
    assert names == ["real"]


# ---------- ignore_repos config ----------


def test_v5c_ignore_repos_default_skips_portfolio_repo(tmp_path, monkeypatch):
    """When `ignore_repos` is unset, the portfolio CLI repo itself is skipped."""
    from portfolio.checks.config import CheckConfig
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _git_init(repos_dir / "site-a")
    _git_init(repos_dir / "portfolio")
    cfg = CheckConfig(repos_dir=repos_dir, github_token="", skip_checks=[],
                      ignore_repos=["portfolio"])
    import portfolio.checks as checks_pkg
    monkeypatch.setattr(checks_pkg, "load_config", lambda path=None: cfg)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 0
    assert "site-a" in result.stdout
    # The portfolio dir should not appear as a row in the repo column.
    assert "portfolio " not in result.stdout.lower()


# ---------- aggregate failures view ----------


def test_v5c_aggregate_common_failures_section_present(tmp_path, monkeypatch):
    """`check --git` adds a 'Most common failures' aggregate block."""
    repos_dir = _make_repos_dir(tmp_path, ["a", "b", "c"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "git"])
    assert result.exit_code == 0
    out = result.stdout
    # Aggregate block heading appears.
    assert "Most common failures" in out
    # Bare repos all fail CHECK_005 (docs/prd.md missing) → category Docs.
    assert "Docs" in out


# ---------- v5.F.2 — deprecated `check --git` callback flag still works ----------


def test_v5f2_git_flag_form_still_works_with_deprecation_warning(tmp_path, monkeypatch):
    """`check --git` (the pre-v5.F.2 flag form) keeps running but prints a
    deprecation note pointing at the new `check git` subcommand."""
    repos_dir = _make_repos_dir(tmp_path, ["alpha-repo"])
    _patch_repos_dir(monkeypatch, repos_dir)
    runner = CliRunner()
    result = runner.invoke(app, ["check", "--git"])
    assert result.exit_code == 0
    out = result.stdout
    assert "deprecated" in out.lower()
    assert "check git" in out
    # Functionality still produces the summary table.
    assert "alpha-repo" in out
