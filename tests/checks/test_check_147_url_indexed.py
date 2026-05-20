"""Tests for CHECK_147 — url-indexed (v16.C).

Stubs the cache-load + GSC-fetch boundaries so we don't need real
GSC credentials. The check has three control branches:
  - cache hit + all indexed → pass
  - cache hit + any non-indexed → fail
  - cache miss + live fetch → exercises the GSC plumbing
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio.checks.deploy.check_147_url_indexed import (
    _INDEXED_STATES,
    run,
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
        "portfolio.checks.deploy.check_147_url_indexed.resolve_live_url",
        lambda _: url,
    )


def _patch_cache(inspections):
    """Cache hit returns `inspections`; cache miss returns None."""
    return patch(
        "portfolio.checks.deploy.check_147_url_indexed._load_cached_inspections",
        lambda _: inspections,
    )


def _patch_fetch(result):
    """`result` is either a list[dict] (success) or an exception."""
    if isinstance(result, Exception):
        def _raise(*a, **kw):
            raise result
        return patch(
            "portfolio.checks.deploy.check_147_url_indexed._fetch_inspections",
            _raise,
        )
    return patch(
        "portfolio.checks.deploy.check_147_url_indexed._fetch_inspections",
        lambda *a, **kw: result,
    )


def _patch_save():
    return patch(
        "portfolio.checks.deploy.check_147_url_indexed._save_inspections",
        lambda *a, **kw: None,
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


# ---- cache hit, all indexed → pass ---------------------------------


def test_pass_when_all_indexed_from_cache(tmp_path: Path):
    site = _make_web_site(tmp_path, "ok.com")
    inspections = [
        {"url": "https://ok.com/", "status": "ok",
         "coverage_state": "Submitted and indexed"},
        {"url": "https://ok.com/about", "status": "ok",
         "coverage_state": "Submitted and indexed"},
        {"url": "https://ok.com/blog", "status": "ok",
         "coverage_state": "Indexed, not submitted in sitemap"},
    ]
    with _patch_live_url("https://ok.com"), _patch_cache(inspections):
        result = run(str(site))
    assert result.status == "pass"
    assert "3/3 top URLs indexed" in result.message
    assert "source: cache" in result.message


def test_indexed_states_include_both_variants():
    """Sanity — the indexed set covers both GSC strings."""
    assert "Submitted and indexed" in _INDEXED_STATES
    assert "Indexed, not submitted in sitemap" in _INDEXED_STATES


# ---- cache hit, non-indexed → fail --------------------------------


def test_fail_when_any_non_indexed(tmp_path: Path):
    site = _make_web_site(tmp_path, "broken.com")
    inspections = [
        {"url": "https://broken.com/", "status": "ok",
         "coverage_state": "Submitted and indexed"},
        {"url": "https://broken.com/old", "status": "ok",
         "coverage_state": "Crawled - currently not indexed"},
        {"url": "https://broken.com/gone", "status": "ok",
         "coverage_state": "Not found (404)"},
    ]
    with _patch_live_url("https://broken.com"), _patch_cache(inspections):
        result = run(str(site))
    assert result.status == "fail"
    assert "1/3 top URLs indexed" in result.message
    assert "2 non-indexed" in result.message
    assert "Crawled - currently not indexed" in result.message
    assert "Not found (404)" in result.message


def test_fail_truncates_to_three_with_overflow_marker(tmp_path: Path):
    site = _make_web_site(tmp_path, "many.com")
    inspections = [
        {"url": f"https://many.com/p{i}", "status": "ok",
         "coverage_state": "Crawled - currently not indexed"}
        for i in range(7)
    ]
    with _patch_live_url("https://many.com"), _patch_cache(inspections):
        result = run(str(site))
    assert result.status == "fail"
    assert "+4 more" in result.message
    # First 3 listed.
    assert "/p0" in result.message
    assert "/p1" in result.message
    assert "/p2" in result.message
    # Not listed in preview (only "+N more").
    assert "/p3" not in result.message


# ---- empty inspections list → warn --------------------------------


def test_warn_when_no_inspections(tmp_path: Path):
    site = _make_web_site(tmp_path, "empty.com")
    with _patch_live_url("https://empty.com"), \
         _patch_cache(None), _patch_fetch([]), _patch_save():
        result = run(str(site))
    assert result.status == "warn"
    assert "no URLs inspected" in result.message


def test_warn_when_all_inspections_errored(tmp_path: Path):
    site = _make_web_site(tmp_path, "errs.com")
    inspections = [
        {"url": f"https://errs.com/p{i}", "status": "error",
         "error": "HttpError 500"}
        for i in range(3)
    ]
    with _patch_live_url("https://errs.com"), _patch_cache(inspections):
        result = run(str(site))
    assert result.status == "warn"
    assert "all 3 URL inspections errored" in result.message


# ---- cache miss + GSC layer error → warn --------------------------


def test_warn_on_gsc_unavailable(tmp_path: Path):
    site = _make_web_site(tmp_path, "anon.com")
    from portfolio.checks.deploy.check_147_url_indexed import _GscUnavailable
    with _patch_live_url("https://anon.com"), \
         _patch_cache(None), \
         _patch_fetch(_GscUnavailable("credentials not configured")):
        result = run(str(site))
    assert result.status == "warn"
    assert "GSC URL Inspection unavailable" in result.message
    assert "credentials not configured" in result.message


# ---- cache miss + live fetch succeeds + pass ----------------------


def test_pass_on_live_fetch(tmp_path: Path):
    site = _make_web_site(tmp_path, "fresh.com")
    inspections = [
        {"url": "https://fresh.com/", "status": "ok",
         "coverage_state": "Submitted and indexed"},
    ]
    saved = {}

    def _capture_save(domain, inspections_arg):
        saved["domain"] = domain
        saved["inspections"] = inspections_arg

    with _patch_live_url("https://fresh.com"), \
         _patch_cache(None), \
         _patch_fetch(inspections), \
         patch(
             "portfolio.checks.deploy.check_147_url_indexed._save_inspections",
             _capture_save,
         ):
        result = run(str(site))
    assert result.status == "pass"
    assert "source: live" in result.message
    assert saved["domain"] == "fresh.com"
    assert saved["inspections"] == inspections


# ---- mobile-usability data does NOT trigger fail ------------------


def test_mobile_usability_does_not_fail_the_check(tmp_path: Path):
    """v16.A locked: CHECK_147 is indexing-only. Mobile-usability data
    may be in the inspection result but doesn't flip pass/fail."""
    site = _make_web_site(tmp_path, "mobile.com")
    inspections = [
        {"url": "https://mobile.com/", "status": "ok",
         "coverage_state": "Submitted and indexed",
         "mobile_usability_verdict": "FAIL"},
    ]
    with _patch_live_url("https://mobile.com"), _patch_cache(inspections):
        result = run(str(site))
    assert result.status == "pass"
