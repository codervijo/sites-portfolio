"""v51.C — URL Inspection sweep: new fields, quota, cache, throttle, resume."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from portfolio import gsc_detail_cache, seo_deep
from portfolio.gsc_recrawl import UrlInspection, inspect_one_url, pick_property
from portfolio.project_seo_diagnostics import (
    URL_INSPECTION_DAILY_QUOTA,
    URL_INSPECTION_PER_MINUTE_QUOTA,
)

D = "s.com"
P = "sc-domain:s.com"
URLS = [f"https://s.com/p{i}" for i in range(5)]


@pytest.fixture(autouse=True)
def _tmp_gsc(monkeypatch, tmp_path):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "gsc")


def _ok(_svc, _prop, url):
    return UrlInspection(url=url, status="ok", coverage_state="URL is unknown to Google",
                         verdict="NEUTRAL", sitemaps=[])


class _Clock:
    def __init__(self):
        self.t, self.slept = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def _sweep(urls=URLS, **kw):
    c = _Clock()
    kw.setdefault("inspect", _ok)
    return seo_deep.sweep_inspections(D, urls, service=None, property_url=P,
                                      clock=c, sleep=c.sleep, **kw), c


# ---------- quota constants (v51.A) ----------

def test_quota_constants_match_google_published_limits():
    assert URL_INSPECTION_DAILY_QUOTA == 2000
    assert URL_INSPECTION_PER_MINUTE_QUOTA == 600
    assert seo_deep.SWEEP_PER_MINUTE < URL_INSPECTION_PER_MINUTE_QUOTA


# ---------- inspect_one_url: new fields ----------

class _Svc:
    def __init__(self, resp=None, exc=None):
        self.resp, self.exc = resp, exc

    def urlInspection(self):
        return self

    def index(self):
        return self

    def inspect(self, body):
        return self

    def execute(self):
        if self.exc:
            raise self.exc
        return self.resp


def test_inspect_captures_discovery_and_canonical_fields():
    svc = _Svc(resp={"inspectionResult": {"indexStatusResult": {
        "verdict": "PASS", "coverageState": "Submitted and indexed",
        "sitemap": ["https://s.com/sitemap-0.xml"],
        "referringUrls": ["https://s.com/"],
        "googleCanonical": "https://s.com/a", "userCanonical": "https://s.com/a",
        "robotsTxtState": "ALLOWED", "crawledAs": "MOBILE",
        "lastCrawlTime": "2026-11-01T00:00:00Z",
    }}})
    i = inspect_one_url(svc, P, "https://s.com/a")
    assert i.sitemaps == ["https://s.com/sitemap-0.xml"]
    assert i.referring_urls == ["https://s.com/"]
    assert (i.google_canonical, i.user_canonical) == ("https://s.com/a",) * 2
    assert (i.robots_txt_state, i.crawled_as) == ("ALLOWED", "MOBILE")


def test_inspect_unknown_url_has_empty_lists_not_none():
    svc = _Svc(resp={"inspectionResult": {"indexStatusResult": {
        "verdict": "NEUTRAL", "coverageState": "URL is unknown to Google"}}})
    i = inspect_one_url(svc, P, "https://s.com/a")
    assert i.sitemaps == [] and i.referring_urls == [] and i.google_canonical is None


def test_inspect_error_keeps_http_status():
    class _Resp:
        status = 429
    e = RuntimeError("Quota exceeded")
    e.resp = _Resp()
    i = inspect_one_url(_Svc(exc=e), P, "https://s.com/a")
    assert i.status == "error" and i.http_status == 429


def test_pick_property_prefers_sc_domain():
    assert pick_property([{"siteUrl": "https://s.com/"}, {"siteUrl": P}]) == P
    assert pick_property([{"siteUrl": "https://s.com/"}]) == "https://s.com/"


# ---------- sweep ----------

def test_sweep_inspects_all_and_persists_section():
    res, _ = _sweep()
    assert res.inspected == 5 and res.complete and res.stopped_reason is None
    saved = seo_deep.load_today_records(D)
    assert set(saved) == set(URLS)
    assert saved[URLS[0]]["sitemaps"] == [] and saved[URLS[0]]["inspected_at"]


def test_sweep_reuses_same_day_cache_unless_fresh():
    _sweep()
    calls = []

    def counting(svc, prop, url):
        calls.append(url)
        return _ok(svc, prop, url)
    res, _ = _sweep(inspect=counting)
    assert res.from_cache == 5 and calls == []
    res, _ = _sweep(inspect=counting, fresh=True)
    assert res.inspected == 5 and len(calls) == 5


def test_cached_errors_are_retried():
    seo_deep.save_records(D, {URLS[0]: {"url": URLS[0], "status": "error"}})
    res, _ = _sweep(urls=URLS[:1])
    assert res.inspected == 1 and res.from_cache == 0


def test_budget_stops_and_lists_rest_then_resume_completes():
    res, _ = _sweep(budget=2)
    assert res.inspected == 2 and res.stopped_reason == "budget"
    assert res.not_inspected == URLS[2:]
    res2, _ = _sweep(budget=10)
    assert res2.from_cache == 2 and res2.inspected == 3 and res2.complete


def test_quota_429_stops_sweep_without_counting_error():
    n = {"i": 0}

    def flaky(svc, prop, url):
        n["i"] += 1
        if n["i"] == 3:
            return UrlInspection(url=url, status="error", error="HttpError", http_status=429)
        return _ok(svc, prop, url)
    res, _ = _sweep(inspect=flaky)
    assert res.stopped_reason == "quota" and res.errors == 0
    assert res.inspected == 2 and res.not_inspected == URLS[2:]
    assert n["i"] == 3                       # no calls after the 429


def test_non_quota_error_is_recorded_and_sweep_continues():
    def bad_one(svc, prop, url):
        if url == URLS[1]:
            return UrlInspection(url=url, status="error", error="HttpError 500", http_status=500)
        return _ok(svc, prop, url)
    res, _ = _sweep(inspect=bad_one)
    assert res.errors == 1 and res.inspected == 4 and res.complete


def test_default_budget_subtracts_todays_recorded_calls():
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    gsc_detail_cache.save_snapshot(D, {"v16c_inspections": [{}] * 10})
    seo_deep.save_records(D, {"x": {"status": "ok", "inspected_at": today + "T00:00:00+00:00"}})
    assert seo_deep.inspections_used_today(D) == 11
    res, _ = _sweep(urls=[])
    assert res.budget == URL_INSPECTION_DAILY_QUOTA - 11


def test_throttle_spaces_calls_under_per_minute_cap():
    res, clock = _sweep(per_minute=60)       # 1 call / second
    assert res.inspected == 5
    assert clock.slept == [pytest.approx(1.0)] * 4


def test_merge_preserves_other_sections_and_urls():
    gsc_detail_cache.save_snapshot(D, {"v16c_inspections": [{"url": "keep"}],
                                       "sitemaps": ["x"]})
    seo_deep.save_records(D, {"https://s.com/old": {"status": "ok"}})
    _sweep(urls=URLS[:2])
    snap = gsc_detail_cache.load_snapshot(gsc_detail_cache.latest_snapshot(D))
    assert snap["v16c_inspections"] == [{"url": "keep"}] and snap["sitemaps"] == ["x"]
    assert set(snap[seo_deep.DEEP_SECTION]) == {"https://s.com/old", *URLS[:2]}


def test_partial_progress_saved_even_if_sweep_raises():
    def explode(svc, prop, url):
        if url == URLS[3]:
            raise KeyboardInterrupt
        return _ok(svc, prop, url)
    with pytest.raises(KeyboardInterrupt):
        _sweep(inspect=explode)
    assert set(seo_deep.load_today_records(D)) == set(URLS[:3])


def test_progress_outcomes():
    seo_deep.save_records(D, {URLS[0]: {"url": URLS[0], "status": "ok"}})
    seen = []
    _sweep(urls=URLS[:2], on_progress=lambda i, n, u, o: seen.append(o))
    assert seen == ["cached", "ok"]


def test_open_gsc_maps_preflight_failure_to_typed_error(monkeypatch):
    from portfolio import seo_runtime

    def fail():
        raise seo_runtime.GscPreflightError("no internet — fix it")
    monkeypatch.setattr(seo_runtime, "gsc_preflight", fail)
    with pytest.raises(seo_deep.GscUnavailable, match="no internet"):
        seo_deep.open_gsc(D)


def test_open_gsc_no_property(monkeypatch):
    from portfolio import seo_runtime
    monkeypatch.setattr(seo_runtime, "gsc_preflight", lambda: (object(), {"other.com": []}))
    with pytest.raises(seo_deep.GscUnavailable, match="no Search Console property covers s.com"):
        seo_deep.open_gsc(D)
