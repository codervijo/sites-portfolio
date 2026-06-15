"""Tests for CHECK_145 — deploy-fresh (v41.B rewrite — CF Pages deployments API).

Stubs the CF boundary (`_resolve_pages_project`, `latest_pages_deployment`),
the creds (`apikeys.get_key`), and `local_head_sha`, so each test drives a
specific deploy-health state without CF/HTTP/git I/O.

NOTE on patch targets: the check lazy-imports `get_key` (from `apikeys`) and
`latest_pages_deployment` (from `cloudflare`) *inside* `run()`, so they must be
patched at their **source** modules. `_resolve_pages_project` and
`local_head_sha` are module-level on the check, so patch them there.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from portfolio.checks.deploy.check_145_deploy_fresh import run

_MOD = "portfolio.checks.deploy.check_145_deploy_fresh"


def _make_site(tmp_path: Path, name="example.com", platform="cf-pages") -> Path:
    site = tmp_path / name
    site.mkdir()
    (site / "package.json").write_text('{"name": "t", "version": "1.0.0"}')
    (site / "lamill.toml").write_text(
        f'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "{platform}"\n')
    return site


def _creds(_k):
    return "tok" if "TOKEN" in _k else "acct"


def _run(site, *, deployment, head, project="example-com"):
    """deployment = (status, commit, dep_id)."""
    with patch("portfolio.apikeys.get_key", _creds), \
         patch(f"{_MOD}._resolve_pages_project", lambda d, **k: project), \
         patch("portfolio.cloudflare.latest_pages_deployment", lambda p, **k: deployment), \
         patch(f"{_MOD}._origin_head_sha", lambda _p, _b: head):
        return run(str(site))


# ---- skip paths ----------------------------------------------------


def test_warn_when_not_web_project(tmp_path):
    site = tmp_path / "not-web"
    site.mkdir()
    assert run(str(site)).status == "warn"


def test_warn_when_not_cf_pages(tmp_path):
    # platform check returns before creds are read — no patching needed.
    site = _make_site(tmp_path, platform="vercel")
    r = run(str(site))
    assert r.status == "warn"
    assert "vercel" in r.message and "not applicable" in r.message


def test_warn_when_no_creds(tmp_path):
    site = _make_site(tmp_path)
    with patch("portfolio.apikeys.get_key", lambda k: None):
        r = run(str(site))
    assert r.status == "warn"
    assert "creds" in r.message


# ---- the headline case: build failed --------------------------------


def test_fail_when_latest_build_failed(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=("failure", "abc123", "d1"), head="abc123")
    assert r.status == "fail"
    assert "FAILED" in r.message


# ---- drift: deployed commit != HEAD ---------------------------------


def test_fail_on_commit_drift(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=("success", "aaaaaaaaaaaa", "d1"), head="bbbbbbbbbbbb")
    assert r.status == "fail"
    assert "drift" in r.message
    assert "aaaaaaaaaaaa" in r.message and "bbbbbbbbbbbb" in r.message


# ---- pass: build ok + commit matches --------------------------------


def test_pass_when_head_shipped(tmp_path):
    site = _make_site(tmp_path)
    sha = "abc123def4567890"
    r = _run(site, deployment=("success", sha, "d1"), head=sha)
    assert r.status == "pass"
    assert "shipped" in r.message


def test_pass_when_commit_is_short_prefix_of_head(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=("success", "abc123de", "d1"), head="abc123def4567890")
    assert r.status == "pass"


# ---- warn: can't determine ------------------------------------------


def test_warn_when_no_deployments(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=(None, None, None), head="abc")
    assert r.status == "warn" and "no deployments" in r.message


def test_warn_when_origin_ref_undetermined(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=("success", "abc123", "d1"), head=None)
    assert r.status == "warn" and "origin/" in r.message


def test_warn_when_no_commit_metadata(tmp_path):
    site = _make_site(tmp_path)
    r = _run(site, deployment=("success", None, "d1"), head="abc123")
    assert r.status == "warn" and "commit metadata" in r.message


def test_warn_when_project_not_resolvable(tmp_path):
    site = _make_site(tmp_path)
    with patch("portfolio.apikeys.get_key", _creds), \
         patch(f"{_MOD}._resolve_pages_project", lambda d, **k: None):
        r = run(str(site))
    assert r.status == "warn" and "no CF Pages project" in r.message
