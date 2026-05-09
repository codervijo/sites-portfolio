"""Tests for v5.A git-category checks (CHECK_020–CHECK_024).

Uses real `git init`-based tmp repos. `git` must be on PATH (always true in
the dev/test environment).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio.checks import run_check


def _run(cmd: list[str], cwd: Path) -> None:
    """Run a git command with no-op user/email so commits work in CI."""
    env_setup = {
        "GIT_AUTHOR_NAME": "Tester",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "Tester",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    import os
    env = {**os.environ, **env_setup}
    subprocess.run(cmd, cwd=cwd, check=True, capture_output=True, env=env)


def _init_repo(path: Path, with_commit: bool = True) -> None:
    """Set up a fresh git repo at `path`, optionally with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-q", "-b", "main"], path)
    if with_commit:
        (path / "README.md").write_text("test\n")
        _run(["git", "add", "README.md"], path)
        _run(["git", "commit", "-q", "-m", "initial"], path)


# CHECK_020 — own-git-repo

def test_check_020_pass(tmp_path):
    _init_repo(tmp_path)
    r = run_check("CHECK_020", str(tmp_path))
    assert r.status == "pass"


def test_check_020_fail_no_git(tmp_path):
    """No .git → fail."""
    r = run_check("CHECK_020", str(tmp_path))
    assert r.status == "fail"
    assert ".git" in r.message.lower() or "not" in r.message.lower()


def test_check_020_fail_tracked_by_parent(tmp_path):
    """Project dir lives inside a parent git repo, has no own .git."""
    _init_repo(tmp_path)  # parent has .git
    sub = tmp_path / "subproject"
    sub.mkdir()
    (sub / "marker.txt").write_text("x")
    r = run_check("CHECK_020", str(sub))
    assert r.status == "fail"
    assert "tracked by parent" in r.message.lower() or "no .git" in r.message.lower()


# CHECK_021 — last-commit-30d

def test_check_021_pass_recent_commit(tmp_path):
    _init_repo(tmp_path)
    r = run_check("CHECK_021", str(tmp_path))
    assert r.status == "pass"
    assert "0d ago" in r.message or "1d ago" in r.message


def test_check_021_fail_no_commits(tmp_path):
    _init_repo(tmp_path, with_commit=False)
    r = run_check("CHECK_021", str(tmp_path))
    assert r.status == "fail"
    assert "no commits" in r.message.lower()


def test_check_021_warn_no_git(tmp_path):
    """No .git → warn (can't check)."""
    r = run_check("CHECK_021", str(tmp_path))
    assert r.status == "warn"


# CHECK_022 — clean-working-tree

def test_check_022_pass_clean(tmp_path):
    _init_repo(tmp_path)
    r = run_check("CHECK_022", str(tmp_path))
    assert r.status == "pass"


def test_check_022_warn_dirty_modified(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "README.md").write_text("modified content\n")
    r = run_check("CHECK_022", str(tmp_path))
    assert r.status == "warn"
    assert "uncommitted" in r.message.lower() or "1" in r.message


def test_check_022_warn_dirty_untracked(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "newfile.txt").write_text("new\n")
    r = run_check("CHECK_022", str(tmp_path))
    assert r.status == "warn"


# CHECK_023 — on-main-branch

def test_check_023_pass_main(tmp_path):
    _init_repo(tmp_path)
    r = run_check("CHECK_023", str(tmp_path))
    assert r.status == "pass"
    assert "main" in r.message


def test_check_023_warn_feature_branch(tmp_path):
    _init_repo(tmp_path)
    _run(["git", "checkout", "-b", "feature/foo"], tmp_path)
    r = run_check("CHECK_023", str(tmp_path))
    assert r.status == "warn"
    assert "feature/foo" in r.message


# CHECK_024 — has-ci-workflow

def test_check_024_pass(tmp_path):
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("name: CI\non: push\n")
    r = run_check("CHECK_024", str(tmp_path))
    assert r.status == "pass"


def test_check_024_warn_no_dir(tmp_path):
    r = run_check("CHECK_024", str(tmp_path))
    assert r.status == "warn"


def test_check_024_warn_empty_dir(tmp_path):
    """workflows/ exists but contains no *.yml — still warn."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "README.txt").write_text("placeholder")
    r = run_check("CHECK_024", str(tmp_path))
    assert r.status == "warn"
