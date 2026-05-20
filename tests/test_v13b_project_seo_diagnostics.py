"""Tests for v13.B — per-project GSC diagnostics module + render block.

Three surfaces:
  1. `project_seo_diagnostics` — dataclasses, sitemap detail
     parsing, hint generation, no-GSC-property path
  2. `gsc_detail_cache` — per-domain 24h cache shape
  3. `cli._render_project_seo_diagnostics` — render variants

GSC API calls are stubbed via duck-typed `_FakeService`; URL
Inspection is monkey-patched at the module-import boundary.
"""
from __future__ import annotations

import io
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from rich.console import Console

from portfolio import cli as cli_mod
from portfolio import gsc_detail_cache, project_seo_diagnostics
from portfolio.gsc_recrawl import UrlInspection
from portfolio.project_seo_diagnostics import (
    CoverageDetail,
    Hint,
    ProjectSeoDiagnostics,
    SitemapDetail,
    _generate_hints,
    _origin_from_property,
    _sitemap_status,
    build_diagnostics,
    fetch_sitemap_details,
)


def _capturing_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False)


# ---------- sitemap status cascade ----------


def test_sitemap_status_error_wins():
    assert _sitemap_status(errors=2, warnings=3, is_pending=True) == "ERROR"


def test_sitemap_status_pending_above_warn():
    """Pending = GSC hasn't fetched yet; ranks above WARN because
    we don't yet know if warnings will materialize."""
    assert _sitemap_status(errors=0, warnings=2, is_pending=True) == "PENDING"


def test_sitemap_status_warn():
    assert _sitemap_status(errors=0, warnings=2, is_pending=False) == "WARN"


def test_sitemap_status_ok():
    assert _sitemap_status(errors=0, warnings=0, is_pending=False) == "OK"


# ---------- origin extraction ----------


def test_origin_from_url_prefix_property():
    assert _origin_from_property("https://homeloom.app/") == "https://homeloom.app"


def test_origin_from_sc_domain_property():
    assert _origin_from_property("sc-domain:homeloom.app") == "https://homeloom.app"


def test_origin_from_url_prefix_without_trailing_slash():
    assert _origin_from_property("https://example.com") == "https://example.com"


# ---------- sitemap detail fetching ----------


class _FakeSitemapsService:
    """Duck-typed stand-in for `service.sitemaps()`. The real API is
    chained as `service.sitemaps().list(siteUrl=...).execute()`."""
    def __init__(self, payload):
        self._payload = payload

    def list(self, siteUrl):
        self._site_url = siteUrl
        return self

    def execute(self):
        return self._payload


class _FakeService:
    def __init__(self, sitemap_payload=None):
        self._sm = _FakeSitemapsService(sitemap_payload or {})

    def sitemaps(self):
        return self._sm


def test_fetch_sitemap_details_parses_basic_response():
    payload = {
        "sitemap": [
            {
                "path": "https://homeloom.app/sitemap.xml",
                "errors": "0",
                "warnings": "0",
                "lastDownloaded": "2026-05-18T03:11:00Z",
                "isPending": False,
                "contents": [{"submitted": "47"}],
            },
        ],
    }
    service = _FakeService(sitemap_payload=payload)
    result = fetch_sitemap_details(service, "https://homeloom.app/")
    assert len(result) == 1
    sm = result[0]
    assert sm.path == "/sitemap.xml"
    assert sm.full_url == "https://homeloom.app/sitemap.xml"
    assert sm.status == "OK"
    assert sm.errors == 0
    assert sm.warnings == 0


def test_fetch_sitemap_details_error_status():
    """Errors > 0 → status ERROR + error_summary populated."""
    payload = {
        "sitemap": [
            {
                "path": "https://homeloom.app/sitemap-pages.xml",
                "errors": 14,
                "warnings": 0,
                "lastDownloaded": "2026-05-07T03:11:00Z",
                "isPending": False,
                "contents": [{"submitted": 47}],
            },
        ],
    }
    service = _FakeService(sitemap_payload=payload)
    result = fetch_sitemap_details(service, "https://homeloom.app/")
    assert result[0].status == "ERROR"
    assert result[0].errors == 14
    # Summary populated for renderer
    assert "14 error" in result[0].error_summary


def test_fetch_sitemap_details_pending_status():
    payload = {
        "sitemap": [
            {
                "path": "https://homeloom.app/sitemap.xml",
                "errors": 0,
                "warnings": 0,
                "isPending": True,
            },
        ],
    }
    result = fetch_sitemap_details(_FakeService(payload), "https://homeloom.app/")
    assert result[0].status == "PENDING"
    assert result[0].is_pending is True


def test_fetch_sitemap_details_empty_response():
    """No sitemaps submitted → empty list, no crash."""
    result = fetch_sitemap_details(_FakeService({}), "https://homeloom.app/")
    assert result == []


def test_fetch_sitemap_details_tolerates_api_error():
    """Defensive — googleapiclient raises many error types; the
    helper must catch and return []."""
    class BoomService:
        def sitemaps(self):
            class BoomSitemaps:
                def list(self, **k):
                    raise RuntimeError("transient GSC outage")
            return BoomSitemaps()
    result = fetch_sitemap_details(BoomService(), "https://x.com/")
    assert result == []


def test_fetch_sitemap_details_strips_property_prefix():
    """The renderer wants the relative path. Strip the property
    URL prefix from each sitemap's full URL."""
    payload = {"sitemap": [
        {"path": "https://homeloom.app/sitemaps/articles.xml",
         "errors": 0, "warnings": 0},
    ]}
    result = fetch_sitemap_details(_FakeService(payload), "https://homeloom.app/")
    assert result[0].path == "/sitemaps/articles.xml"


# ---------- hints generator ----------


def test_generate_hints_sitemap_errors_first():
    """Sitemap errors block discovery; render them before per-URL
    coverage issues."""
    sitemaps = [
        SitemapDetail(path="/sitemap.xml", full_url="...", status="ERROR",
                      errors=2),
    ]
    coverage = [
        CoverageDetail(url="https://x.com/a", coverage_state="crawled_not_indexed"),
    ]
    hints = _generate_hints("x.com", sitemaps, coverage)
    assert len(hints) >= 2
    assert hints[0].target == "/sitemap.xml"
    assert hints[0].severity == "error"


def test_generate_hints_coverage_state_each_gets_one():
    """Every URL with a known failing coverage_state produces one
    hint. Multiple URLs with the same state → multiple hints (one
    per URL) because the operator's action is per-URL."""
    coverage = [
        CoverageDetail(url="https://x.com/a", coverage_state="crawled_not_indexed"),
        CoverageDetail(url="https://x.com/b", coverage_state="crawled_not_indexed"),
        CoverageDetail(url="https://x.com/c", coverage_state="not_found_404"),
    ]
    hints = _generate_hints("x.com", [], coverage)
    assert len(hints) == 3
    assert any("/a" in h.text for h in hints)
    assert any("/b" in h.text for h in hints)
    assert any("/c" in h.text for h in hints)


def test_generate_hints_unknown_coverage_state_no_hint():
    """submitted_indexed (the happy path) generates no hint —
    nothing to do."""
    coverage = [
        CoverageDetail(url="https://x.com/a", coverage_state="submitted_indexed"),
    ]
    hints = _generate_hints("x.com", [], coverage)
    assert hints == []


def test_generate_hints_includes_404_advice():
    coverage = [
        CoverageDetail(url="https://x.com/gone", coverage_state="not_found_404"),
    ]
    hints = _generate_hints("x.com", [], coverage)
    assert "404" in hints[0].text or "404" in hints[0].text.lower() or \
           "remove from sitemap" in hints[0].text


def test_generate_hints_sitemap_error_mentions_project_fix():
    sitemaps = [
        SitemapDetail(path="/sitemap.xml", full_url="...", status="ERROR",
                      errors=1),
    ]
    hints = _generate_hints("homeloom.app", sitemaps, [])
    assert "homeloom.app" in hints[0].text
    assert "project fix" in hints[0].text


# ---------- build_diagnostics no-GSC-property path ----------


def test_build_diagnostics_not_registered(monkeypatch):
    """When find_gsc_property raises (no matching GSC property),
    return not_registered=True + a single hint pointing at the
    registration flow, NOT a crash."""
    from portfolio import gsc_recrawl

    def boom(domain, service=None):
        raise gsc_recrawl.RecrawlError(f"no GSC property covers {domain!r}")

    monkeypatch.setattr(project_seo_diagnostics, "find_gsc_property", boom)
    monkeypatch.setattr(project_seo_diagnostics, "authenticate", lambda: None)
    monkeypatch.setattr(project_seo_diagnostics, "get_service", lambda c: object())

    result = build_diagnostics("missing.example", service=object())
    assert result.not_registered is True
    assert result.property_url == ""
    assert result.sitemaps == []
    assert result.coverage == []
    assert len(result.hints) == 1
    assert "register" in result.hints[0].text.lower()


def test_build_diagnostics_registered_path(monkeypatch):
    """Happy path: property exists, sitemap details + coverage
    fetched. Returns a populated ProjectSeoDiagnostics."""
    # Stub find_gsc_property + sitemap detail + coverage detail.
    monkeypatch.setattr(
        project_seo_diagnostics, "find_gsc_property",
        lambda domain, service=None: "https://homeloom.app/",
    )
    monkeypatch.setattr(
        project_seo_diagnostics, "fetch_sitemap_details",
        lambda service, property_url: [
            SitemapDetail(path="/sitemap.xml", full_url="https://homeloom.app/sitemap.xml",
                          status="OK"),
        ],
    )
    monkeypatch.setattr(
        project_seo_diagnostics, "fetch_coverage_details",
        lambda service, property_url, top_n=10: [
            CoverageDetail(url="https://homeloom.app/",
                           coverage_state="submitted_indexed"),
        ],
    )
    result = build_diagnostics("homeloom.app", service=object())
    assert result.not_registered is False
    assert result.property_url == "https://homeloom.app/"
    assert len(result.sitemaps) == 1
    assert len(result.coverage) == 1
    # Happy path → no hints (everything works)
    assert result.hints == []


# ---------- gsc_detail_cache ----------


def test_cache_save_then_load(tmp_path, monkeypatch):
    """Round-trip a snapshot through save → load. Cache writes
    add `fetched_at` + `domain` metadata."""
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    payload = {
        "domain": "homeloom.app",
        "property_url": "https://homeloom.app/",
        "not_registered": False,
        "sitemaps": [],
        "coverage": [],
        "hints": [],
    }
    out_path = gsc_detail_cache.save_snapshot("homeloom.app", payload)
    assert out_path.exists()

    loaded = gsc_detail_cache.load_snapshot(out_path)
    assert loaded["domain"] == "homeloom.app"
    assert "fetched_at" in loaded
    assert loaded["property_url"] == "https://homeloom.app/"


def test_cache_per_domain_subdirs(tmp_path, monkeypatch):
    """One subdir per domain — `data/gsc/<domain>/<date>.json`.
    Domains are lowercased + stripped."""
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    gsc_detail_cache.save_snapshot("homeloom.app", {"k": 1})
    gsc_detail_cache.save_snapshot("airsucks.com", {"k": 2})
    assert (tmp_path / "gsc" / "homeloom.app").is_dir()
    assert (tmp_path / "gsc" / "airsucks.com").is_dir()


def test_cache_latest_snapshot_returns_newest(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    (tmp_path / "gsc" / "x.com").mkdir(parents=True)
    (tmp_path / "gsc" / "x.com" / "2026-05-15.json").write_text("{}")
    (tmp_path / "gsc" / "x.com" / "2026-05-18.json").write_text("{}")
    (tmp_path / "gsc" / "x.com" / "2026-05-10.json").write_text("{}")
    latest = gsc_detail_cache.latest_snapshot("x.com")
    assert latest.name == "2026-05-18.json"


def test_cache_latest_snapshot_returns_none_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "nope")
    assert gsc_detail_cache.latest_snapshot("x.com") is None


def test_cache_is_stale_fresh_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    out_path = gsc_detail_cache.save_snapshot("x.com", {})
    assert gsc_detail_cache.is_stale(out_path, max_age_hours=24) is False


def test_cache_is_stale_old_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    d = tmp_path / "gsc" / "x.com"
    d.mkdir(parents=True)
    p = d / "2026-05-01.json"
    p.write_text(json.dumps({
        "fetched_at": (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat(),
    }))
    assert gsc_detail_cache.is_stale(p, max_age_hours=24) is True


def test_cache_is_stale_unparseable_returns_true(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")
    d = tmp_path / "gsc" / "x.com"
    d.mkdir(parents=True)
    p = d / "2026-05-01.json"
    p.write_text("not json")
    assert gsc_detail_cache.is_stale(p) is True


# ---------- cli render block ----------


def _diag_with_findings() -> ProjectSeoDiagnostics:
    return ProjectSeoDiagnostics(
        domain="homeloom.app",
        property_url="https://homeloom.app/",
        not_registered=False,
        sitemaps=[
            SitemapDetail(path="/sitemap.xml", full_url="…",
                          status="OK", errors=0, warnings=0),
            SitemapDetail(path="/sitemap-pages.xml", full_url="…",
                          status="ERROR", errors=14, warnings=0,
                          error_summary="14 error(s) across 47 URL(s)"),
        ],
        coverage=[
            CoverageDetail(url="https://homeloom.app/",
                           coverage_state="submitted_indexed",
                           verdict="PASS"),
            CoverageDetail(url="https://homeloom.app/about",
                           coverage_state="crawled_not_indexed",
                           verdict="NEUTRAL"),
            CoverageDetail(url="https://homeloom.app/gone",
                           coverage_state="not_found_404"),
        ],
        hints=[
            Hint(target="/sitemap-pages.xml", severity="error",
                 text="/sitemap-pages.xml parse/fetch error → re-deploy"),
            Hint(target="https://homeloom.app/about", severity="warn",
                 text="/about crawled_not_indexed → expand content"),
            Hint(target="https://homeloom.app/gone", severity="error",
                 text="/gone not_found_404 → remove from sitemap"),
        ],
        fetched_at="2026-05-20T10:00:00+00:00",
    )


def test_render_diagnostics_full(monkeypatch):
    cap = _capturing_console()
    cli_mod._render_project_seo_diagnostics(_diag_with_findings(), cap)
    out = cap.file.getvalue()
    # Header sections
    assert "GSC diagnostics" in out
    assert "📋 Sitemaps" in out
    assert "📊 Coverage" in out
    assert "💡 Hints" in out
    # Sitemap rows
    assert "/sitemap.xml" in out
    assert "/sitemap-pages.xml" in out
    assert "ERROR" in out
    # Coverage rows
    assert "submitted_indexed" in out
    assert "crawled_not_indexed" in out
    assert "not_found_404" in out
    # Hints
    assert "re-deploy" in out
    assert "expand content" in out


def test_render_diagnostics_not_registered(monkeypatch):
    """not_registered=True path — single line + registration hint,
    no sitemap / coverage blocks."""
    cap = _capturing_console()
    diag = ProjectSeoDiagnostics(
        domain="missing.example",
        property_url="",
        not_registered=True,
        hints=[Hint(target="missing.example", severity="info",
                    text="register at search.google.com")],
        fetched_at="2026-05-20T10:00:00+00:00",
    )
    cli_mod._render_project_seo_diagnostics(diag, cap)
    out = cap.file.getvalue()
    assert "not registered in GSC" in out
    assert "register" in out
    # No sitemap / coverage block headers
    assert "📋 Sitemaps" not in out
    assert "📊 Coverage" not in out


def test_render_diagnostics_no_sitemaps_no_coverage(monkeypatch):
    """Registered but no sitemaps + no coverage data — render the
    'none submitted' / 'unreachable' fallback lines."""
    cap = _capturing_console()
    diag = ProjectSeoDiagnostics(
        domain="bare.example",
        property_url="https://bare.example/",
        not_registered=False,
        sitemaps=[],
        coverage=[],
        hints=[],
        fetched_at="2026-05-20T10:00:00+00:00",
    )
    cli_mod._render_project_seo_diagnostics(diag, cap)
    out = cap.file.getvalue()
    assert "none submitted" in out
    assert "unreachable" in out or "no URLs inspected" in out


def test_render_diagnostics_accepts_dict_shape(monkeypatch):
    """Render block must work with both ProjectSeoDiagnostics
    dataclass and dict reconstructed from cache."""
    cap = _capturing_console()
    diag_dict = {
        "domain": "x.com",
        "property_url": "https://x.com/",
        "not_registered": False,
        "sitemaps": [
            {"path": "/sitemap.xml", "full_url": "…", "status": "OK",
             "errors": 0, "warnings": 0, "is_pending": False,
             "error_summary": "", "last_downloaded": None},
        ],
        "coverage": [
            {"url": "https://x.com/", "coverage_state": "submitted_indexed",
             "verdict": "PASS", "page_fetch_state": None,
             "last_crawl_at": None, "indexing_state": None, "error": None},
        ],
        "hints": [],
        "fetched_at": "2026-05-20T10:00:00+00:00",
    }
    cli_mod._render_project_seo_diagnostics(diag_dict, cap)
    out = cap.file.getvalue()
    assert "GSC diagnostics" in out
    assert "/sitemap.xml" in out
    assert "submitted_indexed" in out


def test_render_diagnostics_coverage_pct_computed(monkeypatch):
    """Headline shows X/Y indexed and a percentage."""
    cap = _capturing_console()
    diag = ProjectSeoDiagnostics(
        domain="x.com", property_url="https://x.com/",
        not_registered=False,
        coverage=[
            CoverageDetail(url="https://x.com/a", coverage_state="submitted_indexed"),
            CoverageDetail(url="https://x.com/b", coverage_state="submitted_indexed"),
            CoverageDetail(url="https://x.com/c", coverage_state="crawled_not_indexed"),
            CoverageDetail(url="https://x.com/d", coverage_state="crawled_not_indexed"),
        ],
        fetched_at="2026-05-20T10:00:00+00:00",
    )
    cli_mod._render_project_seo_diagnostics(diag, cap)
    out = cap.file.getvalue()
    assert "2/4" in out
    assert "50%" in out


# ---------- focus / project-seo consistency (predicate test) ----------


def test_sitemap_error_detector_consistent_with_focus():
    """`fleet focus` flags `gsc_status == "ok" and sitemap_errors > 0`.
    v13.B's sitemap_status cascade fires ERROR on the same condition.
    Pin the predicate so both surfaces agree on what counts as broken."""
    # focus's predicate (paraphrased)
    def focus_says_broken(gsc_status, sitemap_errors):
        return gsc_status == "ok" and isinstance(sitemap_errors, int) and sitemap_errors > 0
    # v13.B's per-sitemap predicate
    def v13_says_error(sm: SitemapDetail) -> bool:
        return sm.status == "ERROR"

    # Equivalent on the same inputs
    sm = SitemapDetail(path="/x", full_url="…", status=_sitemap_status(2, 0, False), errors=2)
    assert focus_says_broken("ok", 2) is True
    assert v13_says_error(sm) is True

    sm_ok = SitemapDetail(path="/x", full_url="…", status=_sitemap_status(0, 0, False), errors=0)
    assert focus_says_broken("ok", 0) is False
    assert v13_says_error(sm_ok) is False
