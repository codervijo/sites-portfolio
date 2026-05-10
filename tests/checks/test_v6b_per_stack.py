"""Tests for v6.B — per-stack rules added beyond v5.C.

CHECK_141 no-git-submodules     (deploy/error)
CHECK_142 gitignore-covers-build-output   (stack/warn) + Tier 1 fixer
"""
from __future__ import annotations

import json
import subprocess

import pytest

from portfolio.checks import run_check


# ---------- CHECK_141 — no-git-submodules ----------


def _git_init(path):
    """Set up a fresh git repo at `path` with a single committed file."""
    import os
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.com"}
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=path, check=True, env=env)
    (path / "README.md").write_text("# r\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True, env=env)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=path, check=True, env=env)


def test_check_141_pass_no_submodules(tmp_path):
    _git_init(tmp_path)
    assert run_check("CHECK_141", str(tmp_path)).status == "pass"


def test_check_141_warn_not_a_git_repo(tmp_path):
    """Plain dir without .git → skipped, not failed."""
    r = run_check("CHECK_141", str(tmp_path))
    assert r.status == "warn"
    assert "not a git repo" in r.message


def test_check_141_fail_with_submodule(tmp_path):
    """Add a submodule and verify CHECK_141 fails."""
    _git_init(tmp_path)
    sub = tmp_path / "_sub"
    sub.mkdir()
    _git_init(sub)
    # Add the inner repo as a submodule of the outer.
    import os
    env = {**os.environ,
           "GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@e.com",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@e.com"}
    result = subprocess.run(
        ["git", "-c", "protocol.file.allow=always", "submodule", "add",
         "--quiet", str(sub), "vendored"],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.skip(f"submodule add failed in test env: {result.stderr}")
    r = run_check("CHECK_141", str(tmp_path))
    assert r.status == "fail"
    assert "submodule" in r.message.lower()


# ---------- CHECK_142 — gitignore-covers-build-output ----------


def _make_web_project(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))


def test_check_142_pass_when_dist_in_gitignore(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n")
    assert run_check("CHECK_142", str(tmp_path)).status == "pass"


def test_check_142_pass_when_dist_no_trailing_slash(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules\ndist\n")
    assert run_check("CHECK_142", str(tmp_path)).status == "pass"


def test_check_142_fail_when_dist_missing(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    assert run_check("CHECK_142", str(tmp_path)).status == "fail"


def test_check_142_warn_when_no_gitignore(tmp_path):
    _make_web_project(tmp_path)
    r = run_check("CHECK_142", str(tmp_path))
    assert r.status == "warn"
    assert "skipped" in r.message


def test_check_142_warn_when_not_web_project(tmp_path):
    """No package.json → skipped, not failed."""
    (tmp_path / ".gitignore").write_text("")
    assert run_check("CHECK_142", str(tmp_path)).status == "warn"


# ---------- CHECK_142 fixer — append missing build-output entries ----------


def test_check_142_fix_appends_entries(tmp_path):
    from portfolio.fix_registry import get_tier_1
    _make_web_project(tmp_path)
    (tmp_path / ".gitignore").write_text("node_modules/\n")
    fixer = get_tier_1("CHECK_142")
    assert fixer is not None
    result = fixer.apply(tmp_path, dry_run=False, assume_yes=True)
    assert result.status == "fixed"
    text = (tmp_path / ".gitignore").read_text()
    assert "dist/" in text
    # Idempotent — re-running is a no-op.
    second = fixer.apply(tmp_path, dry_run=False, assume_yes=True)
    assert second.status == "nothing-to-do"


def test_check_142_fix_dry_run_writes_nothing(tmp_path):
    from portfolio.fix_registry import get_tier_1
    _make_web_project(tmp_path)
    original = "node_modules/\n"
    (tmp_path / ".gitignore").write_text(original)
    fixer = get_tier_1("CHECK_142")
    result = fixer.apply(tmp_path, dry_run=True, assume_yes=False)
    assert result.status == "would-fix"
    assert (tmp_path / ".gitignore").read_text() == original


def test_check_142_fix_manual_when_no_gitignore(tmp_path):
    from portfolio.fix_registry import get_tier_1
    _make_web_project(tmp_path)
    fixer = get_tier_1("CHECK_142")
    result = fixer.apply(tmp_path, dry_run=False, assume_yes=False)
    assert result.status == "manual"
    assert "CHECK_009" in result.summary
