"""Tests for CHECK_145 — deploy-fresh (v15.D).

Stubs the `version_stamp` boundary (fetch + local-head) so each
test can drive specific FreshnessReport verdicts without git or
HTTP I/O.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx

from portfolio.checks.deploy.check_145_deploy_fresh import run
from portfolio.version_stamp import (
    VersionStamp,
    VersionStampError,
)


def _make_web_site(tmp_path: Path, name: str = "example.com") -> Path:
    site = tmp_path / name
    site.mkdir()
    (site / "package.json").write_text('{"name": "test", "version": "1.0.0"}')
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'
        '[live]\nurl = "https://example.com"\n'
    )
    return site


def _patch_live_url(url):
    return patch(
        "portfolio.checks.deploy.check_145_deploy_fresh.resolve_live_url",
        lambda _: url,
    )


def _patch_fetch(stamp_or_error):
    return patch(
        "portfolio.checks.deploy.check_145_deploy_fresh.fetch_version_stamp",
        lambda _: stamp_or_error,
    )


def _patch_head(sha):
    return patch(
        "portfolio.checks.deploy.check_145_deploy_fresh.local_head_sha",
        lambda _: sha,
    )


# ---- skip paths ---------------------------------------------------


def test_warn_when_not_a_web_project(tmp_path: Path):
    site = tmp_path / "not-web"
    site.mkdir()
    result = run(str(site))
    assert result.status == "warn"
    assert "not a web project" in result.message


def test_warn_when_no_live_url(tmp_path: Path):
    site = _make_web_site(tmp_path)
    with _patch_live_url(None):
        result = run(str(site))
    assert result.status == "warn"
    assert "no live URL" in result.message


# ---- pass path: HEAD matches live ---------------------------------


def test_pass_when_head_matches_live(tmp_path: Path):
    site = _make_web_site(tmp_path)
    stamp = VersionStamp(schema=1, commit="abc123def4567890", built_at="2026-05-20T10:00:00Z")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(stamp), \
         _patch_head("abc123def4567890"):
        result = run(str(site))
    assert result.status == "pass"
    assert "HEAD matches live" in result.message
    assert "abc123def456" in result.message


# ---- fail path: drift ---------------------------------------------


def test_fail_on_drift(tmp_path: Path):
    site = _make_web_site(tmp_path)
    stamp = VersionStamp(schema=1, commit="aaaaaaaaaaaaaaaa", built_at="2026-05-20T10:00:00Z")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(stamp), \
         _patch_head("bbbbbbbbbbbbbbbb"):
        result = run(str(site))
    assert result.status == "fail"
    assert "drift" in result.message
    assert "aaaaaaaaaaaa" in result.message
    assert "bbbbbbbbbbbb" in result.message
    # Actionable hint.
    assert "redeploy" in result.message.lower() or "push" in result.message.lower()


# ---- warn paths: can't determine ----------------------------------


def test_warn_when_head_undetermined(tmp_path: Path):
    site = _make_web_site(tmp_path)
    stamp = VersionStamp(schema=1, commit="abc", built_at="2026-05-20T10:00:00Z")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(stamp), \
         _patch_head(None):
        result = run(str(site))
    assert result.status == "warn"
    assert "local HEAD" in result.message


def test_warn_when_live_unreachable(tmp_path: Path):
    site = _make_web_site(tmp_path)
    err = VersionStampError(kind="unreachable", detail="ConnectError: refused")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(err), \
         _patch_head("abc"):
        result = run(str(site))
    assert result.status == "warn"
    assert "can't read live version.json" in result.message
    # Cross-references CHECK_144.
    assert "CHECK_144" in result.message


def test_warn_when_live_404(tmp_path: Path):
    """A 404 is the not-found error kind; CHECK_145 still soft-warns
    so the operator only sees the actionable signal once (in CHECK_144)."""
    site = _make_web_site(tmp_path)
    err = VersionStampError(kind="not_found", detail="https://x/version.json → 404")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(err), \
         _patch_head("abc"):
        result = run(str(site))
    assert result.status == "warn"
    assert "CHECK_144" in result.message


def test_warn_when_live_commit_unknown(tmp_path: Path):
    """Plugin's fallback commit when neither git nor cloud env vars
    are available. Operator should fix the build env."""
    site = _make_web_site(tmp_path)
    stamp = VersionStamp(schema=1, commit="unknown", built_at="2026-05-20T10:00:00Z")
    with _patch_live_url("https://example.com"), \
         _patch_fetch(stamp), \
         _patch_head("abc"):
        result = run(str(site))
    assert result.status == "warn"
    assert "commit=\"unknown\"" in result.message
    assert "CF_PAGES_COMMIT_SHA" in result.message
