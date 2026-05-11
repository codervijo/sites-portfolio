"""Tests for the `launched` / `domain_created` age-tracking pair:
  - Domain dataclass new fields + age properties
  - JSON serializer round-trip
  - cleanup() preserves these fields across CSV rebuild
  - update_domain_field() atomic single-row mutation
  - dashboard column formatting
  - RDAP creation_date event parsing (without network)
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest


def test_domain_age_properties():
    from portfolio.data import Domain
    today = date.today()
    d = Domain(
        name="x.com", registrar="r", tld=".com",
        expires=None, auto_renew="", status="",
        launched=today - timedelta(days=14),
        domain_created=today - timedelta(days=365 * 5),
    )
    assert d.site_age_days == 14
    assert d.domain_age_days == 365 * 5


def test_domain_age_properties_none_when_unset():
    from portfolio.data import Domain
    d = Domain(name="x.com", registrar="r", tld=".com",
               expires=None, auto_renew="", status="")
    assert d.site_age_days is None
    assert d.domain_age_days is None


def test_jsonable_round_trip_includes_age_fields():
    from portfolio.data import Domain, _domain_from_jsonable, _domain_to_jsonable
    d = Domain(
        name="x.com", registrar="r", tld=".com",
        expires=None, auto_renew="", status="",
        launched=date(2026, 4, 1),
        domain_created=date(2020, 1, 15),
    )
    raw = _domain_to_jsonable(d)
    assert raw["launched"] == "2026-04-01"
    assert raw["domain_created"] == "2020-01-15"
    d2 = _domain_from_jsonable(raw)
    assert d2.launched == date(2026, 4, 1)
    assert d2.domain_created == date(2020, 1, 15)


def test_cleanup_preserves_launched_and_domain_created(tmp_path, monkeypatch):
    """cleanup() rebuilds from CSV but must not erase user-set launched/
    RDAP-fetched domain_created.
    """
    from portfolio import data as data_mod

    # Stage 1: write a portfolio.json with launched + domain_created set.
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", tmp_path / "portfolio.json")
    existing = {
        "schema_version": 1,
        "generated_at": "2026-05-11T00:00:00+00:00",
        "domains": [
            {
                "name": "kept.com",
                "registrar": "godaddy",
                "tld": ".com",
                "expires": "2027-01-01",
                "auto_renew": "On",
                "status": "Active",
                "category": "My brand",
                "launched": "2026-04-18",
                "domain_created": "2020-01-15",
            }
        ],
    }
    data_mod.PORTFOLIO_JSON.write_text(json.dumps(existing) + "\n")

    # Stage 2: force cleanup() to pretend CSV input only includes the
    # bare schema (no launched / domain_created — those don't come from
    # registrar CSVs anyway).
    from portfolio.data import Domain

    def fake_load_from_registrars():
        return [Domain(
            name="kept.com", registrar="godaddy", tld=".com",
            expires=date(2027, 1, 1), auto_renew="On", status="Active",
        )]
    monkeypatch.setattr(data_mod, "_load_from_registrars", fake_load_from_registrars)
    monkeypatch.setattr(data_mod, "_load_legacy_plan_md",
                        lambda: {"kept.com": "My brand"})

    out_path, domains, _ = data_mod.cleanup()
    # Re-read to be sure persistence happened.
    after = json.loads(out_path.read_text())
    row = after["domains"][0]
    assert row["launched"] == "2026-04-18"
    assert row["domain_created"] == "2020-01-15"


def test_cleanup_handles_missing_portfolio_json(tmp_path, monkeypatch):
    """First-ever cleanup() run: no preserved fields, no crash."""
    from portfolio import data as data_mod
    from portfolio.data import Domain

    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", tmp_path / "portfolio.json")
    monkeypatch.setattr(data_mod, "_load_from_registrars",
                        lambda: [Domain(name="new.com", registrar="godaddy", tld=".com",
                                        expires=None, auto_renew="", status="")])
    monkeypatch.setattr(data_mod, "_load_legacy_plan_md", lambda: {})
    out_path, domains, _ = data_mod.cleanup()
    assert out_path.exists()
    assert domains[0].launched is None


def test_update_domain_field_atomic_write(tmp_path, monkeypatch):
    from portfolio import data as data_mod

    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", tmp_path / "portfolio.json")
    data_mod.PORTFOLIO_JSON.write_text(json.dumps({
        "domains": [{"name": "a.com"}, {"name": "b.com"}],
    }) + "\n")
    ok = data_mod.update_domain_field("b.com", "launched", date(2026, 5, 1))
    assert ok
    after = json.loads(data_mod.PORTFOLIO_JSON.read_text())
    assert after["domains"][1]["launched"] == "2026-05-01"
    assert "launched" not in after["domains"][0]


def test_update_domain_field_returns_false_when_missing(tmp_path, monkeypatch):
    from portfolio import data as data_mod
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", tmp_path / "portfolio.json")
    data_mod.PORTFOLIO_JSON.write_text(json.dumps({"domains": []}) + "\n")
    assert data_mod.update_domain_field("ghost.com", "launched",
                                        date(2026, 5, 1)) is False


def test_dashboard_fmt_long_age():
    from portfolio.dashboard import _fmt_long_age
    assert _fmt_long_age(None) == "—"
    assert _fmt_long_age(0) == "today"
    assert _fmt_long_age(5) == "5d"
    assert _fmt_long_age(13) == "13d"
    assert _fmt_long_age(14) == "2w"
    assert _fmt_long_age(45) == "6w"     # still weeks below 60d
    assert _fmt_long_age(90) == "3mo"
    assert _fmt_long_age(729) == "24mo"
    assert _fmt_long_age(730) == "2y"
    assert _fmt_long_age(365 * 5) == "5y"


def test_rdap_creation_date_parses_registration_event(monkeypatch):
    from portfolio import availability

    class FakeResponse:
        status_code = 200
        def json(self):
            return {
                "events": [
                    {"eventAction": "last update", "eventDate": "2024-06-01T00:00:00Z"},
                    {"eventAction": "registration", "eventDate": "2018-03-15T14:23:00Z"},
                ]
            }
    monkeypatch.setattr(availability, "_load_rdap_endpoints",
                        lambda: {"com": ["https://example.test"]})
    monkeypatch.setattr(availability.requests, "get",
                        lambda *a, **kw: FakeResponse())
    result = availability.rdap_creation_date("example.com")
    assert result == date(2018, 3, 15)


def test_rdap_creation_date_returns_none_on_no_registration_event(monkeypatch):
    from portfolio import availability

    class FakeResponse:
        status_code = 200
        def json(self):
            return {"events": [{"eventAction": "expiration", "eventDate": "2027-01-01"}]}
    monkeypatch.setattr(availability, "_load_rdap_endpoints",
                        lambda: {"com": ["https://example.test"]})
    monkeypatch.setattr(availability.requests, "get",
                        lambda *a, **kw: FakeResponse())
    assert availability.rdap_creation_date("example.com") is None


def test_rdap_creation_date_returns_none_on_no_endpoint(monkeypatch):
    from portfolio import availability
    monkeypatch.setattr(availability, "_load_rdap_endpoints", lambda: {})
    # No network call should be attempted — verify by exploding if it tries.
    monkeypatch.setattr(availability.requests, "get",
                        lambda *a, **kw: pytest.fail("should not call network"))
    assert availability.rdap_creation_date("example.invalidtld") is None


def test_fetch_first_commit_date_returns_none_outside_repo(tmp_path):
    from portfolio.project import fetch_first_commit_date
    assert fetch_first_commit_date(tmp_path) is None
