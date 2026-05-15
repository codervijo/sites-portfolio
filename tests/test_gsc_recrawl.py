"""Tests for `lamill settings gsc recrawl` helpers (gsc_recrawl.py).

Mocks the googleapiclient `service` object — we never call real GSC
in tests. urlInspection.index.inspect responses follow the shape
documented at:
  https://developers.google.com/webmaster-tools/v1/url_inspection
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio import gsc_recrawl
from portfolio.gsc_recrawl import (
    RecrawlError,
    RecrawlReport,
    UrlInspection,
    _fmt_dt,
    _parse_last_crawl,
    append_to_growth_md,
    find_gsc_property,
    format_markdown_report,
    head_commit_time,
    inspect_one_url,
    read_urls_from_file,
    resolve_baseline,
    resolve_site_dir,
    run_recrawl,
)


# ---------- _parse_last_crawl ----------


def test_parse_last_crawl_z_suffix():
    dt = _parse_last_crawl("2026-05-15T12:34:56Z")
    assert dt is not None
    assert dt.tzinfo is not None
    assert dt.year == 2026 and dt.month == 5


def test_parse_last_crawl_offset_form():
    dt = _parse_last_crawl("2026-05-15T12:34:56+00:00")
    assert dt is not None


def test_parse_last_crawl_returns_none_for_empty_or_bad():
    assert _parse_last_crawl(None) is None
    assert _parse_last_crawl("") is None
    assert _parse_last_crawl("not a timestamp") is None


# ---------- UrlInspection.crawled_since ----------


def test_crawled_since_true_when_after_baseline():
    baseline = datetime(2026, 5, 15, tzinfo=timezone.utc)
    i = UrlInspection(url="x", status="ok",
                      last_crawl_time=datetime(2026, 5, 16, tzinfo=timezone.utc))
    assert i.crawled_since(baseline) is True


def test_crawled_since_false_when_before_baseline():
    baseline = datetime(2026, 5, 15, tzinfo=timezone.utc)
    i = UrlInspection(url="x", status="ok",
                      last_crawl_time=datetime(2026, 5, 14, tzinfo=timezone.utc))
    assert i.crawled_since(baseline) is False


def test_crawled_since_false_when_no_last_crawl():
    baseline = datetime(2026, 5, 15, tzinfo=timezone.utc)
    i = UrlInspection(url="x", status="ok", last_crawl_time=None)
    assert i.crawled_since(baseline) is False


# ---------- resolve_site_dir ----------


def test_resolve_site_dir_raises_when_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_recrawl, "SITES_ROOT", tmp_path)
    with pytest.raises(RecrawlError, match="not found"):
        resolve_site_dir("nonexistent.test")


def test_resolve_site_dir_returns_path_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_recrawl, "SITES_ROOT", tmp_path)
    site = tmp_path / "x.test"
    site.mkdir()
    assert resolve_site_dir("x.test") == site


# ---------- resolve_baseline ----------


def test_resolve_baseline_uses_since_when_provided(tmp_path):
    """The `since` arg is used verbatim; site_dir isn't read."""
    out = resolve_baseline(tmp_path, "2026-05-15T12:00:00Z")
    assert out == datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_resolve_baseline_assumes_utc_when_no_tz(tmp_path):
    out = resolve_baseline(tmp_path, "2026-05-15T12:00:00")
    assert out.tzinfo is not None
    assert out == datetime(2026, 5, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_resolve_baseline_raises_on_bad_iso(tmp_path):
    with pytest.raises(RecrawlError, match="could not parse --since"):
        resolve_baseline(tmp_path, "definitely not a date")


def test_resolve_baseline_falls_back_to_head_commit(tmp_path, monkeypatch):
    """When `since` is None, the baseline comes from `head_commit_time`."""
    captured: list[Path] = []
    def _fake_head(p):
        captured.append(p)
        return datetime(2026, 1, 1, tzinfo=timezone.utc)
    monkeypatch.setattr(gsc_recrawl, "head_commit_time", _fake_head)
    out = resolve_baseline(tmp_path, None)
    assert out == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert captured == [tmp_path]


# ---------- head_commit_time ----------


def test_head_commit_time_reads_git_log(monkeypatch, tmp_path):
    import subprocess as sp
    def _fake(*args, **kwargs):
        return "2026-05-15T12:34:56+00:00\n"
    monkeypatch.setattr(sp, "check_output", _fake)
    out = head_commit_time(tmp_path)
    assert out.year == 2026


def test_head_commit_time_raises_on_git_failure(monkeypatch, tmp_path):
    import subprocess as sp
    def _explode(*args, **kwargs):
        raise sp.CalledProcessError(128, args[0] if args else [])
    monkeypatch.setattr(sp, "check_output", _explode)
    with pytest.raises(RecrawlError, match="HEAD commit time"):
        head_commit_time(tmp_path)


# ---------- URL source ----------


def test_read_urls_from_file_strips_blanks_and_comments(tmp_path):
    p = tmp_path / "urls.txt"
    p.write_text(
        "# comment\n"
        "https://x.test/a\n"
        "\n"
        "https://x.test/b\n"
        "   # indented comment\n"
        "https://x.test/c\n"
    )
    out = read_urls_from_file(p)
    # `   # indented comment` is whitespace then `#` — `strip` removes the
    # leading spaces, so it still counts as a `#` comment.
    assert out == ["https://x.test/a", "https://x.test/b", "https://x.test/c"]


# ---------- find_gsc_property ----------


def test_find_gsc_property_prefers_sc_domain():
    """When both `sc-domain:` and `https://` cover the same host,
    the sc-domain form wins (covers all subdomains)."""
    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {
        "siteEntry": [
            {"siteUrl": "https://www.washcalc.app/"},
            {"siteUrl": "sc-domain:washcalc.app"},
        ]
    }
    assert find_gsc_property("washcalc.app", service=fake_service) == "sc-domain:washcalc.app"


def test_find_gsc_property_falls_back_to_url_form():
    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {
        "siteEntry": [{"siteUrl": "https://washcalc.app/"}]
    }
    assert find_gsc_property("washcalc.app", service=fake_service) == "https://washcalc.app/"


def test_find_gsc_property_raises_when_not_covered():
    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {
        "siteEntry": [{"siteUrl": "sc-domain:other.test"}]
    }
    with pytest.raises(RecrawlError, match="no GSC property"):
        find_gsc_property("washcalc.app", service=fake_service)


# ---------- inspect_one_url ----------


def _fake_inspect_response(last_crawl: str | None = None,
                           page_fetch: str | None = "PAGE_FETCH_STATE_SUCCESSFUL",
                           indexing: str | None = "INDEXING_ALLOWED",
                           coverage: str | None = "Submitted and indexed",
                           verdict: str | None = "PASS") -> dict:
    return {
        "inspectionResult": {
            "indexStatusResult": {
                "lastCrawlTime": last_crawl,
                "pageFetchState": page_fetch,
                "indexingState": indexing,
                "coverageState": coverage,
                "verdict": verdict,
            }
        }
    }


def test_inspect_one_url_returns_ok_on_success():
    service = MagicMock()
    service.urlInspection().index().inspect().execute.return_value = (
        _fake_inspect_response(last_crawl="2026-05-15T12:00:00Z")
    )
    r = inspect_one_url(service, "sc-domain:x.test", "https://x.test/a")
    assert r.status == "ok"
    assert r.last_crawl_time is not None
    assert r.page_fetch_state == "PAGE_FETCH_STATE_SUCCESSFUL"
    assert r.indexing_state == "INDEXING_ALLOWED"


def test_inspect_one_url_records_error_on_exception():
    service = MagicMock()
    service.urlInspection().index().inspect().execute.side_effect = RuntimeError("403")
    r = inspect_one_url(service, "sc-domain:x.test", "https://x.test/a")
    assert r.status == "error"
    assert "403" in r.error


def test_inspect_one_url_tolerates_missing_fields():
    """A response with no indexStatusResult still produces a clean
    UrlInspection — fields are None, status stays "ok"."""
    service = MagicMock()
    service.urlInspection().index().inspect().execute.return_value = {}
    r = inspect_one_url(service, "sc-domain:x.test", "https://x.test/a")
    assert r.status == "ok"
    assert r.last_crawl_time is None
    assert r.page_fetch_state is None


# ---------- RecrawlReport accounting ----------


def test_report_crawled_count():
    baseline = datetime(2026, 5, 15, tzinfo=timezone.utc)
    inspections = [
        UrlInspection("a", "ok", last_crawl_time=datetime(2026, 5, 16, tzinfo=timezone.utc)),
        UrlInspection("b", "ok", last_crawl_time=datetime(2026, 5, 16, tzinfo=timezone.utc)),
        UrlInspection("c", "ok", last_crawl_time=datetime(2026, 5, 1, tzinfo=timezone.utc)),
        UrlInspection("d", "error", error="403"),
    ]
    r = RecrawlReport(site="x.test", property_url="sc-domain:x.test",
                      baseline=baseline, inspections=inspections)
    assert r.crawled_count() == 2
    assert r.total_count() == 4
    assert r.errored_count() == 1


# ---------- format_markdown_report ----------


def test_format_markdown_report_includes_table_header():
    report = RecrawlReport(
        site="washcalc.app",
        property_url="sc-domain:washcalc.app",
        baseline=datetime(2026, 5, 15, tzinfo=timezone.utc),
        inspections=[
            UrlInspection(
                url="https://washcalc.app/",
                status="ok",
                last_crawl_time=datetime(2026, 5, 16, tzinfo=timezone.utc),
                page_fetch_state="PAGE_FETCH_STATE_SUCCESSFUL",
                indexing_state="INDEXING_ALLOWED",
                verdict="PASS",
            ),
        ],
    )
    md = format_markdown_report(report,
                                now=datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert "## GSC recrawl — washcalc.app — 2026-05-17" in md
    assert "Property: `sc-domain:washcalc.app`" in md
    assert "Re-crawled since baseline: **1/1**" in md
    assert "| URL | Last crawl |" in md
    assert "washcalc.app/" in md
    assert "✓" in md


def test_format_markdown_report_marks_uncrawled_with_x():
    report = RecrawlReport(
        site="x.test",
        property_url="sc-domain:x.test",
        baseline=datetime(2026, 5, 15, tzinfo=timezone.utc),
        inspections=[
            UrlInspection(
                url="https://x.test/old",
                status="ok",
                last_crawl_time=datetime(2026, 5, 1, tzinfo=timezone.utc),
            ),
        ],
    )
    md = format_markdown_report(report,
                                now=datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert "✗" in md
    assert "Re-crawled since baseline: **0/1**" in md


def test_format_markdown_report_handles_errored_urls():
    report = RecrawlReport(
        site="x.test",
        property_url="sc-domain:x.test",
        baseline=datetime(2026, 5, 15, tzinfo=timezone.utc),
        inspections=[
            UrlInspection(url="https://x.test/a", status="error", error="403"),
        ],
    )
    md = format_markdown_report(report,
                                now=datetime(2026, 5, 17, tzinfo=timezone.utc))
    assert "1 errored" in md
    assert "error: 403" in md


# ---------- append_to_growth_md ----------


def test_append_to_growth_md_creates_file_when_missing(tmp_path):
    site_dir = tmp_path
    p = append_to_growth_md(site_dir, "## entry\n\nbody\n")
    assert p == site_dir / "docs" / "growth.md"
    text = p.read_text()
    assert "Growth log" in text   # default header
    assert "## entry" in text
    assert "body" in text


def test_append_to_growth_md_preserves_existing_content(tmp_path):
    site_dir = tmp_path
    docs = site_dir / "docs"
    docs.mkdir()
    growth = docs / "growth.md"
    growth.write_text("# Growth log\n\n## old entry\n\nold body\n")
    append_to_growth_md(site_dir, "## new entry\n\nnew body\n")
    text = growth.read_text()
    assert "## old entry" in text
    assert "## new entry" in text
    assert text.index("## old entry") < text.index("## new entry")   # ordered


# ---------- run_recrawl orchestration ----------


def test_run_recrawl_uses_explicit_url_list(monkeypatch, tmp_path):
    site = "x.test"
    site_dir = tmp_path / site
    (site_dir / "docs").mkdir(parents=True)
    monkeypatch.setattr(gsc_recrawl, "SITES_ROOT", tmp_path)
    # Avoid running real git in head_commit_time.
    monkeypatch.setattr(gsc_recrawl, "head_commit_time",
                        lambda p: datetime(2026, 5, 1, tzinfo=timezone.utc))

    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {
        "siteEntry": [{"siteUrl": "sc-domain:x.test"}]
    }
    # urlInspection responses keyed by URL.
    def _inspect_side_effect(body=None, **_):
        url = body["inspectionUrl"]
        return MagicMock(execute=lambda: _fake_inspect_response(
            last_crawl="2026-05-16T00:00:00Z" if "new" in url else "2026-04-01T00:00:00Z"
        ))
    fake_service.urlInspection().index().inspect.side_effect = _inspect_side_effect

    report = run_recrawl(
        site,
        urls=["https://x.test/new", "https://x.test/old"],
        service=fake_service,
    )
    assert report.total_count() == 2
    assert report.crawled_count() == 1


def test_run_recrawl_falls_back_to_sitemap(monkeypatch, tmp_path):
    """When `urls` is None, the orchestrator pulls them from the sitemap
    (live fetcher mocked here)."""
    site = "x.test"
    (tmp_path / site).mkdir()
    monkeypatch.setattr(gsc_recrawl, "SITES_ROOT", tmp_path)
    monkeypatch.setattr(gsc_recrawl, "head_commit_time",
                        lambda p: datetime(2026, 5, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(gsc_recrawl, "fetch_sitemap_urls",
                        lambda origin: ["https://x.test/a", "https://x.test/b"])

    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {
        "siteEntry": [{"siteUrl": "sc-domain:x.test"}]
    }
    fake_service.urlInspection().index().inspect.return_value.execute.return_value = (
        _fake_inspect_response(last_crawl="2026-05-16T00:00:00Z")
    )

    report = run_recrawl(site, urls=None, since="2026-05-01T00:00:00Z",
                        service=fake_service)
    assert report.total_count() == 2
    assert all(i.crawled_since(report.baseline) for i in report.inspections)


def test_run_recrawl_raises_when_no_gsc_property(monkeypatch, tmp_path):
    site = "x.test"
    (tmp_path / site).mkdir()
    monkeypatch.setattr(gsc_recrawl, "SITES_ROOT", tmp_path)
    monkeypatch.setattr(gsc_recrawl, "head_commit_time",
                        lambda p: datetime(2026, 5, 1, tzinfo=timezone.utc))

    fake_service = MagicMock()
    fake_service.sites().list().execute.return_value = {"siteEntry": []}
    with pytest.raises(RecrawlError, match="no GSC property"):
        run_recrawl(site, urls=["https://x.test/a"], service=fake_service)


# ---------- _fmt_dt ----------


def test_fmt_dt_returns_dash_for_none():
    assert _fmt_dt(None) == "—"


def test_fmt_dt_formats_utc():
    out = _fmt_dt(datetime(2026, 5, 15, 12, 34, tzinfo=timezone.utc))
    assert out == "2026-05-15 12:34 UTC"
