"""Tests for CHECK_057 — cf-edge-cache-fresh + its tier-1 purge fix.

The probe-helper accepts an injected `httpx.Client` so tests use a
MockTransport — no real network. The fixer's CF API calls are mocked
through `portfolio.cloudflare`."""
from __future__ import annotations

import httpx
import pytest

from portfolio.checks.deploy import check_057_cf_edge_cache_fresh as mod


# Repo where the domain (= repo dir name) matches what we curl in the probe.
def _repo(tmp_path, name: str = "donready.xyz", *, wrangler: bool = True,
          dist_files: list[str] | None = None):
    repo = tmp_path / name
    repo.mkdir()
    if wrangler:
        (repo / "wrangler.jsonc").write_text('{"name": "x"}')
    if dist_files is not None:
        dist = repo / "dist"
        dist.mkdir()
        for rel in dist_files:
            full = dist / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text("placeholder")
    return repo


def _client_for(responses: dict[str, httpx.Response]) -> httpx.Client:
    """Return an httpx.Client whose mock transport answers per-path.
    Anything not in the map → 404.

    follow_redirects=False mirrors production behavior — the probe
    records the literal response for each requested path, never the
    destination of a 301/302. See _probe_one in the check module."""
    def handler(request: httpx.Request) -> httpx.Response:
        return responses.get(request.url.path, httpx.Response(404))
    return httpx.Client(transport=httpx.MockTransport(handler),
                        follow_redirects=False)


# ---------- run() ----------


def test_run_warns_when_not_cf_pages(tmp_path):
    repo = _repo(tmp_path, wrangler=False, dist_files=["index.html"])
    r = mod.run(str(repo))
    assert r.status == "warn"
    assert "not a Cloudflare Pages project" in r.message


def test_run_warns_when_no_dist(tmp_path):
    repo = _repo(tmp_path, wrangler=True, dist_files=None)
    r = mod.run(str(repo))
    assert r.status == "warn"
    assert "no dist" in r.message


def test_run_fails_when_critical_path_stale_at_edge(tmp_path, monkeypatch):
    """The donready scenario: /sitemap.xml served 200 with cf HIT, but
    the current dist/ has no sitemap.xml (canonical is sitemap-index.xml)."""
    repo = _repo(tmp_path, dist_files=["index.html",
                                        "sitemap-index.xml",
                                        "sitemap-0.xml",
                                        "robots.txt"])
    responses = {
        "/": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
        "/robots.txt": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
        "/sitemap.xml": httpx.Response(200,
                                       headers={"cf-cache-status": "HIT",
                                                "etag": '"stale"'}),
        "/sitemap-index.xml": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
        "/sitemap-0.xml": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
    }
    monkeypatch.setattr(mod, "_run_probes",
                        lambda repo_path, domain, client=None:
                        [{**_probe_to_row(p, r, repo_path),
                          "is_critical": p in {"/robots.txt", "/sitemap.xml",
                                               "/sitemap-index.xml", "/sitemap-0.xml"}}
                         for p, r in responses.items()])
    r = mod.run(str(repo))
    assert r.status == "fail"
    assert "/sitemap.xml" in r.message
    assert "cache=HIT" in r.message
    assert "portfolio project fix" in r.message


def _probe_to_row(path, resp, repo_path):
    from pathlib import Path
    return {
        "path": path, "url": f"https://donready.xyz{path}",
        "status": resp.status_code,
        "cf_cache_status": resp.headers.get("cf-cache-status"),
        "etag": resp.headers.get("etag"),
        "error": None,
        "in_dist": mod._dist_path_for(Path(repo_path), path).is_file(),
    }


def test_run_passes_when_all_probed_paths_reconcile_with_dist(tmp_path):
    repo = _repo(tmp_path, dist_files=["index.html", "robots.txt",
                                        "sitemap.xml", "sitemap-index.xml",
                                        "sitemap-0.xml"])
    responses = {
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200),
        "/sitemap.xml": httpx.Response(200),
        "/sitemap-index.xml": httpx.Response(200),
        "/sitemap-0.xml": httpx.Response(200),
    }
    with _client_for(responses) as client:
        rows = mod._run_probes(repo, repo.name, client=client)
    # No stale paths — every served URL has its file in dist.
    assert mod._stale_paths(rows, critical_only=True) == []
    assert mod._stale_paths(rows) == []


def test_run_passes_when_critical_paths_return_404(tmp_path):
    """A site that doesn't serve `/sitemap.xml` at all (404) isn't
    stale — it's just absent. That's fine; only 200-served-but-not-in-
    dist is stale."""
    repo = _repo(tmp_path, dist_files=["index.html", "robots.txt",
                                        "sitemap-index.xml", "sitemap-0.xml"])
    responses = {
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200),
        "/sitemap.xml": httpx.Response(404),
        "/sitemap-index.xml": httpx.Response(200),
        "/sitemap-0.xml": httpx.Response(200),
    }
    with _client_for(responses) as client:
        rows = mod._run_probes(repo, repo.name, client=client)
    assert mod._stale_paths(rows) == []


def test_run_does_not_flag_legitimate_301_as_stale(tmp_path):
    """donready regression: /sitemap.xml correctly 301s to
    /sitemap-index.xml (operator's intentional fix after the original
    stale-cache incident). The probe must NOT follow that redirect and
    record the destination's 200+HIT as if the source path were stale.

    A 301/302 means the edge is routing, not serving stale content;
    dist/ presence is irrelevant here."""
    repo = _repo(tmp_path, dist_files=["index.html", "robots.txt",
                                        "sitemap-index.xml", "sitemap-0.xml"])
    # /sitemap.xml ABSENT from dist/ but the edge 301s to the real index.
    responses = {
        "/": httpx.Response(200),
        "/robots.txt": httpx.Response(200),
        "/sitemap.xml": httpx.Response(
            301, headers={"location": "/sitemap-index.xml"}),
        "/sitemap-index.xml": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
        "/sitemap-0.xml": httpx.Response(200),
    }
    with _client_for(responses) as client:
        rows = mod._run_probes(repo, repo.name, client=client)
    # The 301 row's status is 301, not 200 — so it doesn't qualify as stale.
    sitemap_row = next(r for r in rows if r["path"] == "/sitemap.xml")
    assert sitemap_row["status"] == 301
    assert mod._stale_paths(rows, critical_only=True) == []
    # And run() reports pass on this configuration.
    # (Skipped at the run() level here because run() calls _run_probes
    # without our injected client; the helper-level assertion is what
    # pins the no-follow-redirects contract.)


def test_run_warns_when_only_non_critical_is_stale(tmp_path):
    """A stale `/` (no index.html in dist/) is unusual but not fail-worthy
    — the home page doesn't drive sitemap discovery."""
    repo = _repo(tmp_path, dist_files=["robots.txt", "sitemap.xml",
                                        "sitemap-index.xml", "sitemap-0.xml"])
    # Note: no index.html → `/` is stale
    responses = {
        "/": httpx.Response(200, headers={"cf-cache-status": "HIT"}),
        "/robots.txt": httpx.Response(200),
        "/sitemap.xml": httpx.Response(200),
        "/sitemap-index.xml": httpx.Response(200),
        "/sitemap-0.xml": httpx.Response(200),
    }
    with _client_for(responses) as client:
        rows = mod._run_probes(repo, repo.name, client=client)
    assert mod._stale_paths(rows, critical_only=True) == []
    stale_any = mod._stale_paths(rows)
    assert [r["path"] for r in stale_any] == ["/"]


def test_run_warns_when_origin_unreachable(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])

    def all_error(repo_path, domain, client=None):
        return [
            {"path": p, "url": f"https://{domain}{p}", "status": None,
             "cf_cache_status": None, "etag": None,
             "error": "ConnectError: dns",
             "is_critical": True, "in_dist": False}
            for p, _ in mod._PROBE_PATHS
        ]
    monkeypatch.setattr(mod, "_run_probes", all_error)
    r = mod.run(str(repo))
    assert r.status == "warn"
    assert "origin unreachable" in r.message


# ---------- _dist_path_for ----------


def test_dist_path_root_maps_to_index_html(tmp_path):
    assert mod._dist_path_for(tmp_path, "/") == tmp_path / "dist" / "index.html"


def test_dist_path_explicit_file(tmp_path):
    assert mod._dist_path_for(tmp_path, "/sitemap.xml") == \
        tmp_path / "dist" / "sitemap.xml"


def test_dist_path_trailing_slash_maps_to_index_html(tmp_path):
    """Cloudflare Pages serves /about/ as dist/about/index.html."""
    assert mod._dist_path_for(tmp_path, "/about/") == \
        tmp_path / "dist" / "about" / "index.html"


# ---------- _apply_purge (tier-1 fix) ----------


def test_apply_purge_nothing_to_do_when_no_wrangler(tmp_path):
    repo = _repo(tmp_path, wrangler=False, dist_files=["index.html"])
    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "nothing-to-do"
    assert "Cloudflare" in out.summary


def test_apply_purge_manual_when_no_dist(tmp_path):
    repo = _repo(tmp_path, wrangler=True, dist_files=None)
    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "manual"
    assert "dist" in out.summary


def test_apply_purge_nothing_to_do_when_no_stale(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    monkeypatch.setattr(mod, "_run_probes",
                        lambda *a, **k: [
                            {"path": "/", "url": "https://x/", "status": 200,
                             "cf_cache_status": "HIT", "etag": None,
                             "error": None, "is_critical": False,
                             "in_dist": True},
                        ])
    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "nothing-to-do"
    assert "no stale" in out.summary


def test_apply_purge_would_fix_on_dry_run(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    monkeypatch.setattr(mod, "_run_probes",
                        lambda *a, **k: [
                            {"path": "/sitemap.xml",
                             "url": f"https://{repo.name}/sitemap.xml",
                             "status": 200, "cf_cache_status": "HIT",
                             "etag": '"x"', "error": None,
                             "is_critical": True, "in_dist": False},
                        ])
    out = mod._apply_purge(repo, dry_run=True, assume_yes=False)
    assert out.status == "would-fix"
    assert "/sitemap.xml" in out.summary


def test_apply_purge_returns_manual_when_token_missing(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    stale_row = {"path": "/sitemap.xml",
                 "url": f"https://{repo.name}/sitemap.xml",
                 "status": 200, "cf_cache_status": "HIT", "etag": None,
                 "error": None, "is_critical": True, "in_dist": False}
    monkeypatch.setattr(mod, "_run_probes", lambda *a, **k: [stale_row])

    from portfolio import cloudflare
    def raise_missing(*a, **k):
        raise cloudflare.MissingCredentialsError("no token at ~/.config/...")
    monkeypatch.setattr(cloudflare, "resolve_zone_id", raise_missing)

    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "manual"
    assert "no token" in out.summary


def test_apply_purge_returns_error_when_purge_call_fails(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    stale_row = {"path": "/sitemap.xml",
                 "url": f"https://{repo.name}/sitemap.xml",
                 "status": 200, "cf_cache_status": "HIT", "etag": None,
                 "error": None, "is_critical": True, "in_dist": False}
    monkeypatch.setattr(mod, "_run_probes", lambda *a, **k: [stale_row])
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "resolve_zone_id", lambda d, **k: "zone-abc")
    def raise_api(*a, **k):
        raise cloudflare.CloudflareAPIError("HTTP 429: rate limited")
    monkeypatch.setattr(cloudflare, "purge_files", raise_api)

    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "error"
    assert "purge call failed" in out.summary


def test_apply_purge_returns_error_when_reprobe_still_hits(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    stale_row = {"path": "/sitemap.xml",
                 "url": f"https://{repo.name}/sitemap.xml",
                 "status": 200, "cf_cache_status": "HIT", "etag": None,
                 "error": None, "is_critical": True, "in_dist": False}
    # Both probes (before + after purge) return the same stale-HIT row —
    # purge didn't take.
    monkeypatch.setattr(mod, "_run_probes", lambda *a, **k: [stale_row])
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "resolve_zone_id", lambda d, **k: "zone-abc")
    monkeypatch.setattr(cloudflare, "purge_files", lambda *a, **k: None)

    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "error"
    assert "still HIT" in out.summary


def test_apply_purge_fixed_when_reprobe_clean(tmp_path, monkeypatch):
    repo = _repo(tmp_path, dist_files=["index.html"])
    stale_row = {"path": "/sitemap.xml",
                 "url": f"https://{repo.name}/sitemap.xml",
                 "status": 200, "cf_cache_status": "HIT", "etag": None,
                 "error": None, "is_critical": True, "in_dist": False}
    cleared_row = {**stale_row, "status": 404,
                   "cf_cache_status": "MISS", "in_dist": False}

    call_count = {"n": 0}
    def two_step_probe(*a, **k):
        call_count["n"] += 1
        return [stale_row] if call_count["n"] == 1 else [cleared_row]
    monkeypatch.setattr(mod, "_run_probes", two_step_probe)
    from portfolio import cloudflare
    monkeypatch.setattr(cloudflare, "resolve_zone_id", lambda d, **k: "zone-abc")
    monkeypatch.setattr(cloudflare, "purge_files", lambda *a, **k: None)

    out = mod._apply_purge(repo, dry_run=False, assume_yes=False)
    assert out.status == "fixed"
    assert "/sitemap.xml" in out.summary
    assert call_count["n"] == 2   # one probe before purge, one after


# ---------- Registry integration ----------


def test_check_142_registered_with_metadata():
    from portfolio.checks.registry import _all_checks
    spec = _all_checks().get("CHECK_057")
    assert spec is not None
    assert spec.category == "deploy"
    assert spec.name == "cf-edge-cache-fresh"


def test_check_142_tier_1_fix_discovered():
    from portfolio.fix_registry import get_tier_1
    spec = get_tier_1("CHECK_057")
    assert spec is not None
    assert spec.tier == 1
    assert "purge" in spec.summary.lower()
