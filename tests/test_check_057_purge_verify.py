"""CHECK_057 — the purge fix must not false-report "fixed" when a stale path
survives the purge as cf-cache-status DYNAMIC (regression: bugs.md 2026-06-19).

Mocks via `monkeypatch.setattr` on the real `portfolio.cloudflare` module (same
pattern as tests/checks/test_check_057_cf_edge_cache_fresh.py) — never replaces
sys.modules, so it can't pollute other tests.
"""
from __future__ import annotations

import portfolio.checks.deploy.check_057_cf_edge_cache_fresh as mod


def _stale_row(path="/sitemap.xml", cache="DYNAMIC"):
    # 200 served, not in dist, not a SPA fallback, and actually edge-cached
    # (age > 0) → _stale_paths flags it. age is what distinguishes a genuinely
    # cached-stale object from a fresh DYNAMIC pass-through.
    return {
        "path": path, "url": f"https://x.test{path}", "status": 200,
        "cf_cache_status": cache, "content_type": "application/xml",
        "etag": None, "age": 109000, "cache_control": "public, s-maxage=604800",
        "error": None, "is_critical": True, "in_dist": False,
    }


def _fresh_row(path="/sitemap.xml"):
    # 404 at origin → not stale (status != 200).
    return {
        "path": path, "url": f"https://x.test{path}", "status": 404,
        "cf_cache_status": "DYNAMIC", "content_type": "text/html",
        "etag": None, "error": None, "is_critical": True, "in_dist": False,
    }


def _patch(monkeypatch, tmp_path, *, probe_batches, purge_calls):
    (tmp_path / "dist").mkdir()
    monkeypatch.setattr(mod, "_is_cf_pages_project", lambda p: True)
    monkeypatch.setattr(mod, "_domain_from_repo_path", lambda p: "x.test")
    batches = list(probe_batches)
    monkeypatch.setattr(mod, "_run_probes", lambda *a, **k: batches.pop(0))
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "resolve_zone_id", lambda d, **k: "zone-abc")
    monkeypatch.setattr(cloudflare, "purge_files",
                        lambda z, urls, **k: purge_calls.append(urls))


def test_dynamic_stale_survives_purge_is_error_not_fixed(tmp_path, monkeypatch):
    # The regression: post-purge the path is STILL stale but served DYNAMIC
    # (not HIT) — the old HIT-only verify reported "fixed" here.
    calls: list = []
    _patch(monkeypatch, tmp_path,
           probe_batches=[[_stale_row()], [_stale_row()]], purge_calls=calls)
    out = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert calls, "purge should have been attempted"
    assert out.status == "error", out.summary
    assert "still stale" in out.summary
    assert "DYNAMIC" in out.summary


def test_purge_that_clears_reports_fixed(tmp_path, monkeypatch):
    calls: list = []
    _patch(monkeypatch, tmp_path,
           probe_batches=[[_stale_row()], [_fresh_row()]], purge_calls=calls)
    out = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert out.status == "fixed", out.summary


def test_no_stale_paths_nothing_to_do(tmp_path, monkeypatch):
    calls: list = []
    _patch(monkeypatch, tmp_path,
           probe_batches=[[_fresh_row()]], purge_calls=calls)
    out = mod._apply_purge(tmp_path, dry_run=False, assume_yes=True)
    assert out.status == "nothing-to-do"
    assert not calls
