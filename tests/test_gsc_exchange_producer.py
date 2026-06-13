"""GSC Exchange v1 — producer-side conformance (contract §5, L1–L5).

Feeds a known set of inspections, asserts the emitted gsc.json validates
against the vendored schema and round-trips L2–L4, and checks the atomic
write (L5) + the gitignore guard (P5).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import jsonschema
import pytest

from portfolio.gsc_recrawl import (
    RecrawlReport,
    UrlInspection,
    build_exchange_payload,
    ensure_lamill_gitignored,
    export_exchange_file,
    write_exchange_file,
)

SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "docs" / "contracts" / "gsc-exchange.schema.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text())
FETCHED = datetime(2026, 6, 13, 1, 2, 3, tzinfo=timezone.utc)


def _report(site="donready.xyz"):
    return RecrawlReport(
        site=site,
        property_url=f"sc-domain:{site}",
        baseline=FETCHED,
        inspections=[
            UrlInspection(
                url=f"https://{site}/", status="ok", verdict="PASS",
                coverage_state="Submitted and indexed",
                indexing_state="INDEXING_ALLOWED",
                page_fetch_state="SUCCESSFUL",
                last_crawl_time=datetime(2026, 6, 11, 8, 22, tzinfo=timezone.utc),
            ),
            UrlInspection(
                url=f"https://{site}/best-scrubs/", status="ok",
                verdict="NEUTRAL", coverage_state="URL is unknown to Google",
            ),
            # An errored inspection: verdict/coverage None → safe defaults,
            # error carries the truth, internal `status` dropped.
            UrlInspection(
                url=f"https://{site}/broken/", status="error",
                error="HttpError: 500",
            ),
        ],
    )


def test_payload_validates_against_vendored_schema():  # L1
    payload = build_exchange_payload(_report(), fetched_at=FETCHED)
    jsonschema.validate(payload, SCHEMA)  # raises on non-conformance


def test_L2_schema_and_domain():
    payload = build_exchange_payload(_report("donready.xyz"), fetched_at=FETCHED)
    assert payload["schema"] == "gsc-exchange-v1"
    assert payload["domain"] == "donready.xyz"


def test_L3_fetched_at_is_utc_z():
    payload = build_exchange_payload(_report(), fetched_at=FETCHED)
    assert payload["fetched_at"].endswith("Z")
    # parses as a real timestamp (strip Z → fromisoformat)
    datetime.fromisoformat(payload["fetched_at"][:-1])
    assert payload["fetched_at"] == "2026-06-13T01:02:03Z"


def test_L4_every_url_absolute_https_on_domain():
    site = "donready.xyz"
    payload = build_exchange_payload(_report(site), fetched_at=FETCHED)
    assert payload["pages"]
    for p in payload["pages"]:
        assert p["url"].startswith(f"https://{site}/")


def test_mapping_drops_status_defaults_required_and_formats_crawl_time():
    payload = build_exchange_payload(_report(), fetched_at=FETCHED)
    pages = payload["pages"]
    assert all("status" not in p for p in pages)         # internal field dropped
    assert pages[0]["last_crawl_time"] == "2026-06-11T08:22:00Z"
    assert pages[1]["last_crawl_time"] is None
    # errored inspection: required fields defaulted, error preserved
    broken = pages[2]
    assert broken["verdict"] == "NEUTRAL"
    assert broken["coverage_state"] == "URL is unknown to Google"
    assert broken["error"] == "HttpError: 500"


def test_write_is_atomic_and_valid(tmp_path):  # L5 + L1 on disk
    site_dir = tmp_path / "donready.xyz"
    site_dir.mkdir()
    payload = build_exchange_payload(_report(), fetched_at=FETCHED)
    out = write_exchange_file(site_dir, payload)
    assert out == site_dir / ".lamill" / "gsc.json"
    # no temp leftovers (atomic rename cleaned up)
    assert not list(out.parent.glob(".gsc.json.tmp*"))
    on_disk = json.loads(out.read_text())
    jsonschema.validate(on_disk, SCHEMA)
    assert on_disk == payload


def test_export_gitignores_lamill(tmp_path):  # P5
    site_dir = tmp_path / "donready.xyz"
    site_dir.mkdir()
    export_exchange_file(_report(), site_dir, fetched_at=FETCHED)
    gi = (site_dir / ".gitignore").read_text()
    assert ".lamill/" in gi
    # idempotent — second call adds nothing
    assert ensure_lamill_gitignored(site_dir) is False
    assert (site_dir / ".gitignore").read_text().count(".lamill/") == 1


def test_empty_pages_is_valid():  # P6 degrade shape
    payload = build_exchange_payload(
        RecrawlReport(site="x.com", property_url="sc-domain:x.com",
                      baseline=FETCHED, inspections=[]),
        fetched_at=FETCHED, error="not a verified property",
    )
    jsonschema.validate(payload, SCHEMA)
    assert payload["pages"] == []
    assert payload["error"] == "not a verified property"
