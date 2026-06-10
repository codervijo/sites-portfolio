"""Tests for v15.I — `gh_repo.py` (GitHub REST API + gh CLI fallback)."""
from __future__ import annotations

import subprocess
from unittest.mock import patch, MagicMock

import httpx
import pytest

from portfolio.gh_repo import (
    GhApiError,
    GhAuthError,
    GhCliError,
    GhError,
    ParsedRemote,
    RepoInfo,
    auth_path,
    detect_gh_owner,
    ensure_auth,
    ensure_origin_remote,
    ensure_repo,
    get_repo,
    parse_github_remote,
    push_to_origin,
    read_local_origin,
)


# ---- auth_path / ensure_auth ----


def test_auth_path_token(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key",
                        lambda k: "ghp_xxx" if k == "GITHUB_TOKEN" else "")
    assert auth_path() == "token"


def test_auth_path_gh_cli(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key", lambda k: "")
    monkeypatch.setattr("portfolio.gh_repo.shutil.which", lambda x: "/usr/bin/gh")
    assert auth_path() == "gh-cli"


def test_auth_path_none(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key", lambda k: "")
    monkeypatch.setattr("portfolio.gh_repo.shutil.which", lambda x: None)
    assert auth_path() == "none"


def test_ensure_auth_raises_when_none(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key", lambda k: "")
    monkeypatch.setattr("portfolio.gh_repo.shutil.which", lambda x: None)
    with pytest.raises(GhAuthError, match="Neither GITHUB_TOKEN nor"):
        ensure_auth()


# ---- detect_gh_owner (token path) ----


def test_detect_owner_via_token_happy(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key",
                        lambda k: "ghp_xxx" if k == "GITHUB_TOKEN" else "")
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(200, json={"login": "codervijo"}))
    assert detect_gh_owner() == "codervijo"


def test_detect_owner_via_token_401(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key",
                        lambda k: "bad" if k == "GITHUB_TOKEN" else "")
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(401, text="bad creds"))
    with pytest.raises(GhApiError, match="HTTP 401"):
        detect_gh_owner()


# ---- get_repo / ensure_repo (token path) ----


def _stub_token_path(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key",
                        lambda k: "ghp_xxx" if k == "GITHUB_TOKEN" else "")


def test_get_repo_exists(monkeypatch):
    _stub_token_path(monkeypatch)
    payload = {
        "name": "agesdk-dev",
        "owner": {"login": "codervijo"},
        "full_name": "codervijo/agesdk-dev",
        "clone_url": "https://github.com/codervijo/agesdk-dev.git",
        "ssh_url": "git@github.com:codervijo/agesdk-dev.git",
        "private": False,
        "default_branch": "main",
    }
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(200, json=payload))
    r = get_repo("codervijo", "agesdk-dev")
    assert r is not None
    assert r.full_name == "codervijo/agesdk-dev"
    assert r.created is False


def test_get_repo_404(monkeypatch):
    _stub_token_path(monkeypatch)
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(404, text="not found"))
    assert get_repo("codervijo", "missing") is None


def test_get_repo_non_200(monkeypatch):
    _stub_token_path(monkeypatch)
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(500, text="oops"))
    with pytest.raises(GhApiError):
        get_repo("codervijo", "agesdk-dev")


def test_ensure_repo_idempotent(monkeypatch):
    """ensure_repo should detect the existing repo and skip create."""
    _stub_token_path(monkeypatch)
    payload = {
        "name": "agesdk-dev",
        "owner": {"login": "codervijo"},
        "full_name": "codervijo/agesdk-dev",
        "clone_url": "https://github.com/codervijo/agesdk-dev.git",
        "ssh_url": "git@github.com:codervijo/agesdk-dev.git",
        "private": False,
        "default_branch": "main",
    }
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(200, json=payload))
    # If create were called, this fake POST would be invoked; verify
    # it's NOT by patching to raise.
    post_called = {"n": 0}

    def post_should_not_be_called(*a, **kw):
        post_called["n"] += 1
        return httpx.Response(500)

    monkeypatch.setattr(httpx, "post", post_should_not_be_called)
    r = ensure_repo("agesdk-dev", owner="codervijo")
    assert r.full_name == "codervijo/agesdk-dev"
    assert r.created is False
    assert post_called["n"] == 0


def test_ensure_repo_creates_new(monkeypatch):
    """ensure_repo should POST /user/repos when GET returns 404."""
    _stub_token_path(monkeypatch)
    payload = {
        "name": "agesdk-dev",
        "owner": {"login": "codervijo"},
        "full_name": "codervijo/agesdk-dev",
        "clone_url": "https://github.com/codervijo/agesdk-dev.git",
        "ssh_url": "git@github.com:codervijo/agesdk-dev.git",
        "private": True,
        "default_branch": "main",
    }
    monkeypatch.setattr(httpx, "get",
                        lambda url, **kw: httpx.Response(404, text=""))
    captured = {}

    def post_handler(url, json=None, **kw):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(201, json=payload)

    monkeypatch.setattr(httpx, "post", post_handler)
    r = ensure_repo("agesdk-dev", owner="codervijo", private=True)
    assert r.created is True
    assert r.private is True
    # Guard the endpoint, not just the body (GoDaddy-class blind spot):
    # a wrong path/verb here would otherwise ship green.
    assert captured["url"].endswith("/user/repos")
    assert captured["json"]["name"] == "agesdk-dev"
    assert captured["json"]["private"] is True


def test_create_repo_422_recovers_via_refetch(monkeypatch):
    """If POST returns 422 (name conflict in a race), we re-fetch via
    GET and treat as detection."""
    _stub_token_path(monkeypatch)
    payload = {
        "name": "agesdk-dev",
        "owner": {"login": "codervijo"},
        "full_name": "codervijo/agesdk-dev",
        "clone_url": "https://github.com/codervijo/agesdk-dev.git",
        "ssh_url": "git@github.com:codervijo/agesdk-dev.git",
        "private": False,
        "default_branch": "main",
    }
    get_calls = {"n": 0}

    def get_handler(url, **kw):
        get_calls["n"] += 1
        # First call (in ensure_repo) → 404. Second (recovery) → 200.
        if get_calls["n"] == 1:
            return httpx.Response(404)
        return httpx.Response(200, json=payload)

    monkeypatch.setattr(httpx, "get", get_handler)
    monkeypatch.setattr(httpx, "post",
                        lambda url, json=None, **kw: httpx.Response(422, text="conflict"))
    r = ensure_repo("agesdk-dev", owner="codervijo")
    assert r is not None
    assert r.full_name == "codervijo/agesdk-dev"


# ---- gh CLI fallback (subprocess) ----


def test_detect_owner_via_cli(monkeypatch):
    """When GITHUB_TOKEN unset but gh on PATH, owner comes from
    `gh api user -q .login`."""
    monkeypatch.setattr("portfolio.gh_repo.get_key", lambda k: "")
    monkeypatch.setattr("portfolio.gh_repo.shutil.which", lambda x: "/usr/bin/gh")
    proc_result = MagicMock(returncode=0, stdout="codervijo\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc_result)
    assert detect_gh_owner() == "codervijo"


def test_get_repo_via_cli_not_found(monkeypatch):
    monkeypatch.setattr("portfolio.gh_repo.get_key", lambda k: "")
    monkeypatch.setattr("portfolio.gh_repo.shutil.which", lambda x: "/usr/bin/gh")
    proc_result = MagicMock(
        returncode=1, stdout="",
        stderr="Could not resolve to a Repository with the name 'codervijo/missing'.",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc_result)
    assert get_repo("codervijo", "missing") is None


# ---- ensure_origin_remote ----


def test_ensure_origin_remote_already_correct(monkeypatch, tmp_path):
    proc = MagicMock(returncode=0, stdout="git@github.com:user/repo.git\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    added = ensure_origin_remote(tmp_path, "git@github.com:user/repo.git")
    assert added is False


def test_ensure_origin_remote_adds_when_absent(monkeypatch, tmp_path):
    call_history = []

    def runner(cmd, **kw):
        call_history.append(cmd)
        if "get-url" in cmd:
            return MagicMock(returncode=1, stdout="", stderr="no such remote")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", runner)
    added = ensure_origin_remote(tmp_path, "git@github.com:user/repo.git")
    assert added is True
    # Should have been: 1) get-url 2) remote add
    assert any("add" in c for c in call_history)


def test_ensure_origin_remote_mismatch_raises(monkeypatch, tmp_path):
    proc = MagicMock(returncode=0, stdout="git@github.com:wrong/repo.git\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    with pytest.raises(GhError, match="origin already points to"):
        ensure_origin_remote(tmp_path, "git@github.com:user/repo.git")


# ---- push_to_origin ----


def test_push_happy(monkeypatch, tmp_path):
    proc = MagicMock(returncode=0, stdout="", stderr="To github.com:user/repo.git\n   abc..def main -> main")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    assert push_to_origin(tmp_path) is True


def test_push_already_up_to_date(monkeypatch, tmp_path):
    proc = MagicMock(returncode=0, stdout="Everything up-to-date\n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    assert push_to_origin(tmp_path) is False


def test_push_failure(monkeypatch, tmp_path):
    proc = MagicMock(returncode=1, stdout="", stderr="fatal: refusing")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    with pytest.raises(GhError, match="git push"):
        push_to_origin(tmp_path)


# ---- read_local_origin (slug-mismatch fix; 2026-05-27) ----


def test_read_local_origin_returns_url(monkeypatch, tmp_path):
    proc = MagicMock(
        returncode=0,
        stdout="git@github.com:codervijo/kwizicle.com.git\n",
        stderr="",
    )
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    assert read_local_origin(tmp_path) == "git@github.com:codervijo/kwizicle.com.git"


def test_read_local_origin_returns_none_when_no_origin(monkeypatch, tmp_path):
    proc = MagicMock(returncode=1, stdout="", stderr="error: No such remote 'origin'")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    assert read_local_origin(tmp_path) is None


def test_read_local_origin_returns_none_when_git_missing(monkeypatch, tmp_path):
    def runner(*a, **kw):
        raise FileNotFoundError("git: command not found")
    monkeypatch.setattr(subprocess, "run", runner)
    assert read_local_origin(tmp_path) is None


def test_read_local_origin_returns_none_on_timeout(monkeypatch, tmp_path):
    def runner(*a, **kw):
        raise subprocess.TimeoutExpired(cmd="git", timeout=10.0)
    monkeypatch.setattr(subprocess, "run", runner)
    assert read_local_origin(tmp_path) is None


def test_read_local_origin_strips_blank_returns_none(monkeypatch, tmp_path):
    proc = MagicMock(returncode=0, stdout="   \n", stderr="")
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)
    assert read_local_origin(tmp_path) is None


# ---- parse_github_remote (slug-mismatch fix; 2026-05-27) ----


def test_parse_github_remote_ssh_shorthand():
    p = parse_github_remote("git@github.com:codervijo/kwizicle.com.git")
    assert p == ParsedRemote(owner="codervijo", name="kwizicle.com")


def test_parse_github_remote_ssh_full():
    p = parse_github_remote("ssh://git@github.com/codervijo/kwizicle.git")
    assert p == ParsedRemote(owner="codervijo", name="kwizicle")


def test_parse_github_remote_https():
    p = parse_github_remote("https://github.com/codervijo/kwizicle.com.git")
    assert p == ParsedRemote(owner="codervijo", name="kwizicle.com")


def test_parse_github_remote_https_without_dot_git_suffix():
    p = parse_github_remote("https://github.com/codervijo/airsucks.com")
    assert p == ParsedRemote(owner="codervijo", name="airsucks.com")


def test_parse_github_remote_http():
    p = parse_github_remote("http://github.com/codervijo/repo.git")
    assert p == ParsedRemote(owner="codervijo", name="repo")


def test_parse_github_remote_non_github_returns_none():
    assert parse_github_remote("git@gitlab.com:owner/repo.git") is None
    assert parse_github_remote("https://bitbucket.org/owner/repo.git") is None


def test_parse_github_remote_empty_returns_none():
    assert parse_github_remote("") is None


def test_parse_github_remote_malformed_returns_none():
    # Missing owner.
    assert parse_github_remote("git@github.com:/repo.git") is None
    # Missing repo.
    assert parse_github_remote("git@github.com:owner/.git") is None
    # Extra path segments (e.g. enterprise URLs / subdirs).
    assert parse_github_remote("https://github.com/owner/repo/extra") is None
    # No path at all.
    assert parse_github_remote("https://github.com/") is None
