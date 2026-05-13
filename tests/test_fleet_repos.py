"""Tests for fleet_repos.py — state classification + CHECK_040.

Uses tmp_path fixtures to build the four real-world states from scratch
without touching the actual user fleet.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.fleet_repos import (
    RepoState,
    _fix_plan,
    _remote_basename,
    audit,
    classify_site,
    list_site_dirs,
)


def _run_git(args: list[str], cwd: Path) -> None:
    subprocess.run(["git"] + args, cwd=cwd, check=True,
                   capture_output=True, text=True)


def _make_outer_repo(tmp_path: Path) -> Path:
    """Initialize a parent 'sites/' monorepo."""
    sites = tmp_path / "sites"
    sites.mkdir()
    _run_git(["init", "-q", "-b", "main"], cwd=sites)
    _run_git(["config", "user.email", "test@test"], cwd=sites)
    _run_git(["config", "user.name", "test"], cwd=sites)
    return sites


def _make_inner_repo(site_dir: Path, *, remote_url: str | None = None) -> None:
    """Initialize a standalone repo inside a site dir."""
    site_dir.mkdir(parents=True, exist_ok=True)
    _run_git(["init", "-q", "-b", "main"], cwd=site_dir)
    _run_git(["config", "user.email", "test@test"], cwd=site_dir)
    _run_git(["config", "user.name", "test"], cwd=site_dir)
    if remote_url:
        _run_git(["remote", "add", "origin", remote_url], cwd=site_dir)


# ---------- _remote_basename ----------


def test_remote_basename_ssh():
    assert _remote_basename("git@github.com:codervijo/airsucks.com.git") == "airsucks.com"


def test_remote_basename_https():
    assert _remote_basename("https://github.com/codervijo/lamill.io.git") == "lamill.io"


def test_remote_basename_no_git_suffix():
    assert _remote_basename("git@github.com:foo/bar") == "bar"


def test_remote_basename_trailing_slash():
    assert _remote_basename("https://github.com/foo/bar/") == "bar"


def test_remote_basename_garbage():
    assert _remote_basename("") is None
    # No `/` or `:` separator → returns None (parser only handles URLs).
    assert _remote_basename("not-a-url") is None


# ---------- classifier states ----------


def test_classify_clean_standalone(tmp_path: Path):
    """Own .git, remote, not tracked by outer → 'clean'."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "example.com"
    _make_inner_repo(site, remote_url="git@github.com:owner/example.com.git")
    (site / "README.md").write_text("hi\n")
    rs = classify_site(site, sites_root=sites)
    assert rs.state == "clean"
    assert rs.inner_git is True
    assert rs.naming_ok is True
    assert rs.outer_tracked == 0


def test_classify_unpublished(tmp_path: Path):
    """Own .git, no origin → 'unpublished'."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "fresh.com"
    _make_inner_repo(site)  # no remote
    (site / "README.md").write_text("hi\n")
    rs = classify_site(site, sites_root=sites)
    assert rs.state == "unpublished"
    assert rs.inner_remote is None
    assert rs.naming_ok is None


def test_classify_nested_anti_pattern(tmp_path: Path):
    """Own .git AND outer tracks files at the same path → 'nested'."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "double.com"
    site.mkdir()
    # First: outer tracks a file at this path.
    (site / "stale.txt").write_text("from before standalone\n")
    _run_git(["add", "double.com/stale.txt"], cwd=sites)
    _run_git(["commit", "-q", "-m", "track stale"], cwd=sites)
    # Now: also init a standalone repo there.
    _make_inner_repo(site, remote_url="git@github.com:owner/double.com.git")

    rs = classify_site(site, sites_root=sites)
    assert rs.state == "nested"
    assert rs.outer_tracked == 1


def test_classify_monorepo_only(tmp_path: Path):
    """Outer tracks the dir, no inner .git → 'monorepo'."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "tracked-only.com"
    site.mkdir()
    (site / "code.py").write_text("print('hi')\n")
    _run_git(["add", "tracked-only.com/code.py"], cwd=sites)
    _run_git(["commit", "-q", "-m", "add tracked content"], cwd=sites)
    rs = classify_site(site, sites_root=sites)
    assert rs.state == "monorepo"
    assert rs.inner_git is False
    assert rs.outer_tracked == 1


def test_classify_unversioned(tmp_path: Path):
    """Has content, no .git anywhere → 'unversioned'."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "orphan.com"
    site.mkdir()
    # Write enough real content that the stub heuristic doesn't match.
    (site / "index.html").write_text("<html></html>")
    (site / "main.js").write_text("console.log()")
    (site / "style.css").write_text("body{}")
    rs = classify_site(site, sites_root=sites)
    assert rs.state == "unversioned"


def test_classify_stub(tmp_path: Path):
    """Directory has only a doc placeholder — too thin for promotion."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "placeholder.com"
    site.mkdir()
    (site / "README.md").write_text("# stub\n")
    rs = classify_site(site, sites_root=sites)
    assert rs.state == "stub"


# ---------- naming-convention flag ----------


def test_naming_ok_true_when_remote_matches(tmp_path: Path):
    sites = _make_outer_repo(tmp_path)
    site = sites / "x.com"
    _make_inner_repo(site, remote_url="git@github.com:owner/x.com.git")
    rs = classify_site(site, sites_root=sites)
    assert rs.naming_ok is True


def test_naming_ok_false_when_remote_truncates(tmp_path: Path):
    """The csinorcal.church case — remote name drops the TLD."""
    sites = _make_outer_repo(tmp_path)
    site = sites / "x.church"
    _make_inner_repo(site, remote_url="git@github.com:owner/x.git")
    rs = classify_site(site, sites_root=sites)
    assert rs.naming_ok is False
    assert rs.inner_remote_basename == "x"
    # Notes surface the failure explicitly.
    assert any("truncates" in n.lower() for n in rs.notes)


def test_naming_ok_none_when_no_remote(tmp_path: Path):
    sites = _make_outer_repo(tmp_path)
    site = sites / "x.com"
    _make_inner_repo(site)  # no remote
    rs = classify_site(site, sites_root=sites)
    assert rs.naming_ok is None


# ---------- list_site_dirs ----------


def test_list_site_dirs_skips_non_projects(tmp_path: Path):
    sites = _make_outer_repo(tmp_path)
    (sites / "real.com").mkdir()
    (sites / "another.io").mkdir()
    (sites / "portfolio").mkdir()       # skipped by exclude-list
    (sites / "node_modules").mkdir()    # skipped
    (sites / ".hidden").mkdir()         # skipped (dot-prefix)
    (sites / "loose-file").write_text("not a project")
    out = list_site_dirs(sites)
    names = [p.name for p in out]
    assert names == ["another.io", "real.com"]


def test_audit_returns_one_repostate_per_site(tmp_path: Path):
    sites = _make_outer_repo(tmp_path)
    (sites / "a.com").mkdir()
    (sites / "a.com" / "README.md").write_text("a")
    (sites / "b.com").mkdir()
    (sites / "b.com" / "README.md").write_text("b")
    rows = audit(sites_root=sites)
    assert len(rows) == 2
    assert all(isinstance(r, RepoState) for r in rows)


# ---------- fix-plan text ----------


def test_fix_plan_nested_includes_rm_cached():
    r = RepoState(name="x.com", path=Path("/"), state="nested")
    plan = _fix_plan(r)
    assert any("rm --cached -r x.com" in line for line in plan)
    assert any(".gitignore" in line for line in plan)


def test_fix_plan_unpublished_uses_gh():
    r = RepoState(name="x.com", path=Path("/"), state="unpublished")
    plan = _fix_plan(r)
    assert any("gh repo create" in line for line in plan)


def test_fix_plan_clean_is_empty():
    r = RepoState(name="x.com", path=Path("/"), state="clean")
    assert _fix_plan(r) == []


# ---------- CHECK_040 ----------


def test_check_040_passes_on_matching_remote(tmp_path: Path):
    from portfolio.checks.git.check_040_git_remote_name_matches_domain import run
    site = tmp_path / "airsucks.com"
    _make_inner_repo(site, remote_url="git@github.com:codervijo/airsucks.com.git")
    result = run(str(site))
    assert result.status == "pass"


def test_check_040_fails_on_truncated_remote(tmp_path: Path):
    from portfolio.checks.git.check_040_git_remote_name_matches_domain import run
    site = tmp_path / "csinorcal.church"
    _make_inner_repo(site, remote_url="git@github.com:codervijo/csinorcal.git")
    result = run(str(site))
    assert result.status == "fail"
    assert "csinorcal.church" in result.message  # mentions the expected name


def test_check_040_warn_when_no_origin(tmp_path: Path):
    from portfolio.checks.git.check_040_git_remote_name_matches_domain import run
    site = tmp_path / "x.com"
    _make_inner_repo(site)  # no remote
    result = run(str(site))
    assert result.status == "warn"


def test_check_040_warn_when_no_git(tmp_path: Path):
    from portfolio.checks.git.check_040_git_remote_name_matches_domain import run
    site = tmp_path / "x.com"
    site.mkdir()
    result = run(str(site))
    assert result.status == "warn"
    assert "no .git" in result.message
