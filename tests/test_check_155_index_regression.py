"""v30.E — CHECK_155 index-regression (URL-Inspection snapshot diff)."""
from __future__ import annotations

import json

import pytest

from portfolio import gsc_detail_cache
from portfolio.checks.deploy import check_155_index_regression as chk


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(gsc_detail_cache, "GSC_DETAIL_DIR", tmp_path / "_gsc")


def _site(tmp_path):
    s = tmp_path / "example.com"
    s.mkdir()
    return s


def _snap(tmp_path, date, inspections):
    d = tmp_path / "_gsc" / "example.com"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date}.json").write_text(json.dumps({"v16c_inspections": inspections}))


def test_pass_under_two_snapshots(tmp_path):
    site = _site(tmp_path)
    _snap(tmp_path, "2026-06-05", [{"url": "https://example.com/", "coverage_state": "Submitted and indexed"}])
    assert chk.run(str(site)).status == "pass"


def test_pass_when_no_regression(tmp_path):
    site = _site(tmp_path)
    _snap(tmp_path, "2026-06-04", [{"url": "https://example.com/a", "coverage_state": "Submitted and indexed"}])
    _snap(tmp_path, "2026-06-05", [{"url": "https://example.com/a", "coverage_state": "Submitted and indexed"}])
    assert chk.run(str(site)).status == "pass"


def test_warns_on_regression(tmp_path):
    site = _site(tmp_path)
    _snap(tmp_path, "2026-06-04", [{"url": "https://example.com/a", "coverage_state": "Submitted and indexed"}])
    _snap(tmp_path, "2026-06-05", [{"url": "https://example.com/a", "coverage_state": "Crawled - currently not indexed"}])
    res = chk.run(str(site))
    assert res.status == "warn" and "dropped" in res.message


def test_not_regression_if_never_indexed(tmp_path):
    site = _site(tmp_path)
    _snap(tmp_path, "2026-06-04", [{"url": "https://example.com/a", "coverage_state": "Discovered - currently not indexed"}])
    _snap(tmp_path, "2026-06-05", [{"url": "https://example.com/a", "coverage_state": "Not found (404)"}])
    assert chk.run(str(site)).status == "pass"
