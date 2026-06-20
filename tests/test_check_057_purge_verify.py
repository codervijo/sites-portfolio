"""CHECK_057 — the purge fix must not false-report "fixed" when a stale path
survives the purge as cf-cache-status DYNAMIC (regression: bugs.md 2026-06-19).
"""
from __future__ import annotations

import sys
import types

import portfolio.checks.deploy.check_057_cf_edge_cache_fresh as mod


def _stale_dynamic_row(path="/sitemap.xml"):
    # 200 served, not in dist, not a SPA fallback (xml) → _stale_paths flags it.
    return {
        "path": path, "url": f"https://x.test{path}", "status": 200,
        "cf_cache_status": "DYNAMIC", "content_type": "application/xml",
        "etag": None, "in_dist": False,
    }


def _fresh_row(path="/sitemap.xml"):
    return {
        "path": path, "url": f"https://x.test{path}", "status": 404,
        "cf_cache_status": "DYNAMIC", "content_type": "text/html",
        "etag": None, "in_dist": False,
    }


def _patch_common(monkeypatch, tmp_path, *, probe_rows, purge_calls):
    (tmp_path / "dist").mkdir()
    monkeypatch.setattr(mod, "_is_cf_pages_project", lambda p: True)
    monkeypatch.setattr(mod, "_domain_from_repo_path", lambda p: "x.test")
    # _run_probes returns the next batch each call (pre-purge, then post-purge).
    batches = list(probe_rows)
    monkeypatch.setattr(mod, "_run_probes", lambda *a, **k: batches.pop(0))
    fake_cf = types.ModuleType("portfolio.cloudflare")
    fake_cf.MissingCredentialsError = type("MissingCredentialsError", (Exception,), {})
    fake_cf.CloudflareAPIError = type("CloudflareAPIError", (Exception,), {})
    fake_cf.resolve_zone_id = lambda d: "zone123"
    fake_cf.purge_files = lambda z, urls: purge_calls.append(urls)
    monkeypatch.setitem(sys.modules, "portfolio.cloudflare", fake_cf)


def test_dynamic_stale_survives_purge_is_error_not_fixed(tmp_path, monkeypatch):
    # The bug: post-purge the path is STILL stale but served DYNAMIC (not HIT).
    calls: list = []
    _patch_common(
        monkeypatch, tmp_path,
        probe_rows=[[_stale_dynamic_row()], [_stale_dynamic_row()]],
        purge_calls=calls,
    )
    res = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert calls, "purge should have been attempted"
    assert res.status == "error", res.summary
    assert "still stale" in res.summary
    assert "DYNAMIC" in res.summary


def test_purge_that_clears_reports_fixed(tmp_path, monkeypatch):
    # Pre-purge stale, post-purge fresh (404 / in origin) → genuinely fixed.
    calls: list = []
    _patch_common(
        monkeypatch, tmp_path,
        probe_rows=[[_stale_dynamic_row()], [_fresh_row()]],
        purge_calls=calls,
    )
    res = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert res.status == "fixed", res.summary


def test_no_stale_paths_nothing_to_do(tmp_path, monkeypatch):
    calls: list = []
    _patch_common(
        monkeypatch, tmp_path,
        probe_rows=[[_fresh_row()]],
        purge_calls=calls,
    )
    res = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert res.status == "nothing-to-do"
    assert not calls
