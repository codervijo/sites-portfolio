"""Tests for src/portfolio/deploy.py — verify, github repo creation, CF Pages project creation.

All network + subprocess calls are mocked. No real deploys in tests.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from portfolio.deploy import (
    CloudflarePagesDeploy,
    StepResult,
    VerifyResult,
    _strip_jsonc_comments,
    detect_gh_owner,
)


# ---------- helpers ----------


def _mk_clean_project(tmp_path: Path, domain: str = "kwizicle.com") -> Path:
    """Create a project dir with everything verify_local_config expects."""
    project = tmp_path / domain
    project.mkdir()
    (project / "wrangler.jsonc").write_text(json.dumps({
        "name": "kwizicle",
        "compatibility_date": "2026-05-04",
        "assets": {"directory": "./dist", "not_found_handling": "single-page-application"},
    }, indent=2))
    (project / "package.json").write_text(json.dumps({
        "name": "kwizicle",
        "scripts": {"dev": "vite", "build": "vite build"},
        "devDependencies": {"vite": "^6.0.0"},
    }, indent=2))
    (project / "pnpm-lock.yaml").write_text("lockfileVersion: 9\n")
    (project / "public").mkdir()
    (project / "public" / "_headers").write_text("/*\n  X-Frame-Options: DENY\n")
    (project / ".git").mkdir()  # fake .git dir; verify_local_config just checks existence
    return project


# ---------- _strip_jsonc_comments ----------


def test_strip_jsonc_line_comments():
    src = '''{
  // line comment
  "name": "x",  // trailing
  "value": 1
}'''
    out = _strip_jsonc_comments(src)
    assert "// line comment" not in out
    assert "// trailing" not in out
    assert json.loads(out) == {"name": "x", "value": 1}


def test_strip_jsonc_block_comments():
    src = '{"name": "x", /* block */ "value": 2}'
    out = _strip_jsonc_comments(src)
    assert "/* block */" not in out
    assert json.loads(out) == {"name": "x", "value": 2}


def test_strip_jsonc_preserves_string_with_slashes():
    """A `//` inside a string literal is not a comment."""
    src = '{"url": "https://example.com/a"}'
    out = _strip_jsonc_comments(src)
    assert json.loads(out) == {"url": "https://example.com/a"}


# ---------- verify_local_config ----------


def test_verify_passes_on_clean_project(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")
    v = cf.verify_local_config(project)
    assert v.ok
    assert v.missing == []
    # Notes should mention the wrangler name we wrote
    assert any("kwizicle" in n for n in v.notes)


def test_verify_fails_when_wrangler_missing(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "wrangler.jsonc").unlink()
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert "wrangler.jsonc" in v.missing


def test_verify_fails_when_pnpm_lock_missing(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "pnpm-lock.yaml").unlink()
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert any("pnpm-lock" in m for m in v.missing)


def test_verify_fails_when_bun_lockfile_present(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "bun.lockb").write_bytes(b"")
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert any("bun.lockb" in m for m in v.missing)


def test_verify_fails_when_package_lock_present(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "package-lock.json").write_text("{}")
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert any("package-lock.json" in m for m in v.missing)


def test_verify_fails_when_no_git(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / ".git").rmdir()
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert any(".git" in m for m in v.missing)


def test_verify_warns_when_headers_missing(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "public" / "_headers").unlink()
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    # Missing _headers is a note, not a hard fail.
    assert v.ok is True
    assert any("_headers" in n for n in v.notes)


def test_verify_handles_unparseable_wrangler(tmp_path):
    project = _mk_clean_project(tmp_path)
    (project / "wrangler.jsonc").write_text("{ invalid json !! }")
    v = CloudflarePagesDeploy(api_token="t", account_id="a").verify_local_config(project)
    assert not v.ok
    assert any("unparseable" in m for m in v.missing)


# ---------- create_github_repo ----------


def test_create_github_repo_dry_run_no_subprocess(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a", dry_run=True)
    with patch("portfolio.deploy.subprocess.run") as run:
        result = cf.create_github_repo(project, "vijo/kwizicle")
    assert result.ok and not result.skipped
    assert "[dry-run]" in result.detail
    run.assert_not_called()


def test_create_github_repo_skips_when_already_exists(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")
    fake_view = MagicMock()
    fake_view.returncode = 0
    fake_view.stdout = '{"url": "https://github.com/vijo/kwizicle"}'
    with patch("portfolio.deploy.subprocess.run", return_value=fake_view) as run:
        result = cf.create_github_repo(project, "vijo/kwizicle")
    assert result.ok and result.skipped
    # Only the `gh repo view` call ran; create wasn't attempted.
    assert run.call_count == 1
    assert run.call_args.args[0][:3] == ["gh", "repo", "view"]


def test_create_github_repo_runs_create_when_missing(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")

    def fake_run(args, **kwargs):
        m = MagicMock()
        if args[:3] == ["gh", "repo", "view"]:
            m.returncode = 1  # not found
            m.stdout = ""
            m.stderr = "GraphQL error: Could not resolve to a Repository"
        else:
            m.returncode = 0
            m.stdout = "https://github.com/vijo/kwizicle\n"
            m.stderr = ""
        return m

    with patch("portfolio.deploy.subprocess.run", side_effect=fake_run) as run:
        result = cf.create_github_repo(project, "vijo/kwizicle", private=False)
    assert result.ok and not result.skipped
    assert run.call_count == 2
    # Second call: gh repo create with --public
    create_call = run.call_args_list[1]
    assert "create" in create_call.args[0]
    assert "--public" in create_call.args[0]
    assert "--push" in create_call.args[0]


def test_create_github_repo_passes_private_flag(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")

    def fake_run(args, **kwargs):
        m = MagicMock()
        if args[:3] == ["gh", "repo", "view"]:
            m.returncode = 1
        else:
            m.returncode = 0
            m.stdout = "ok"
        m.stderr = ""
        return m

    with patch("portfolio.deploy.subprocess.run", side_effect=fake_run) as run:
        cf.create_github_repo(project, "vijo/kwizicle", private=True)
    create_call = run.call_args_list[1]
    assert "--private" in create_call.args[0]
    assert "--public" not in create_call.args[0]


def test_create_github_repo_handles_gh_not_installed(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")
    with patch("portfolio.deploy.subprocess.run", side_effect=FileNotFoundError):
        result = cf.create_github_repo(project, "vijo/kwizicle")
    assert not result.ok
    assert "gh" in result.detail.lower()


def test_create_github_repo_propagates_create_failure(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="a")

    def fake_run(args, **kwargs):
        m = MagicMock()
        if args[:3] == ["gh", "repo", "view"]:
            m.returncode = 1
        else:
            m.returncode = 1
            m.stdout = ""
            m.stderr = "auth required"
        return m

    with patch("portfolio.deploy.subprocess.run", side_effect=fake_run):
        result = cf.create_github_repo(project, "vijo/kwizicle")
    assert not result.ok
    assert "auth required" in result.detail


# ---------- create_project (CF Pages) ----------


def test_create_project_dry_run_returns_payload(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="acc1", dry_run=True)
    with patch("portfolio.deploy.requests") as r:
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")
    assert result.ok and not result.skipped
    body = result.payload["body"]
    assert body["name"] == "kwizicle"
    assert body["build_config"]["build_command"] == "pnpm run build"
    assert body["build_config"]["destination_dir"] == "dist"
    assert body["source"]["config"]["owner"] == "vijo"
    assert body["source"]["config"]["repo_name"] == "kwizicle"
    r.post.assert_not_called()


def test_create_project_calls_cf_api_with_correct_url(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="tok123", account_id="acc1")

    fake_get = MagicMock(status_code=404)
    fake_post = MagicMock(status_code=201)
    fake_post.json.return_value = {"result": {"name": "kwizicle"}}

    with patch("portfolio.deploy.requests") as r:
        r.get.return_value = fake_get
        r.post.return_value = fake_post
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")

    assert result.ok and not result.skipped
    # POSTed to the right URL with bearer auth
    post_args = r.post.call_args
    assert "/accounts/acc1/pages/projects" in post_args.args[0]
    assert post_args.kwargs["headers"]["Authorization"] == "Bearer tok123"


def test_create_project_skips_when_existing(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="acc1")

    fake_get = MagicMock(status_code=200)
    fake_get.json.return_value = {"result": {"name": "kwizicle", "id": "existing"}}

    with patch("portfolio.deploy.requests") as r:
        r.get.return_value = fake_get
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")

    assert result.ok and result.skipped
    r.post.assert_not_called()
    assert result.payload["existing"]["id"] == "existing"


def test_create_project_falls_back_to_domain_base_when_wrangler_missing(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    (project / "package.json").write_text(json.dumps({"name": "x", "scripts": {"build": "vite build"}}))
    cf = CloudflarePagesDeploy(api_token="t", account_id="acc1", dry_run=True)
    with patch("portfolio.deploy.requests"):
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")
    assert result.payload["body"]["name"] == "kwizicle"


def test_create_project_propagates_cf_error(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="acc1")

    fake_get = MagicMock(status_code=404)
    fake_post = MagicMock(status_code=400)
    fake_post.json.return_value = {"errors": [{"code": 8000007, "message": "name conflict"}]}

    with patch("portfolio.deploy.requests") as r:
        r.get.return_value = fake_get
        r.post.return_value = fake_post
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")

    assert not result.ok
    assert "HTTP 400" in result.detail
    assert "name conflict" in str(result.detail)


def test_create_project_handles_network_error(tmp_path):
    project = _mk_clean_project(tmp_path)
    cf = CloudflarePagesDeploy(api_token="t", account_id="acc1")

    with patch("portfolio.deploy.requests") as r:
        r.get.return_value = MagicMock(status_code=404)
        r.post.side_effect = ConnectionError("dns fail")
        result = cf.create_project(project, "kwizicle.com", gh_owner="vijo", gh_repo="kwizicle")

    assert not result.ok
    assert "ConnectionError" in result.detail


# ---------- detect_gh_owner ----------


def test_detect_gh_owner_returns_login():
    fake = MagicMock(returncode=0, stdout="vijocherian\n")
    with patch("portfolio.deploy.subprocess.run", return_value=fake):
        assert detect_gh_owner() == "vijocherian"


def test_detect_gh_owner_returns_none_when_gh_unauth():
    fake = MagicMock(returncode=1, stdout="", stderr="not authed")
    with patch("portfolio.deploy.subprocess.run", return_value=fake):
        assert detect_gh_owner() is None


def test_detect_gh_owner_returns_none_when_gh_missing():
    with patch("portfolio.deploy.subprocess.run", side_effect=FileNotFoundError):
        assert detect_gh_owner() is None
