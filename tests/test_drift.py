"""Tests for v6.A — `portfolio info drift` data analysis.

Each signal is tested in isolation via the helpers (`_compute_signal_*`).
The top-level `compute_drift()` integration test patches the data layer
+ filesystem so the test doesn't depend on real portfolio data.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

from portfolio.data import Domain
from portfolio.drift import (
    DriftReport,
    DuplicateAcrossRegistrars,
    ExpiryDelta,
    DeployedFlagged,
    _compute_signal_1,
    _compute_signal_2,
    _compute_signal_3,
    _compute_signal_5,
    _compute_signal_6,
    _list_site_dirs,
    compute_drift,
)


def _domain(name, registrar="Porkbun", category=None,
            expires=None) -> Domain:
    return Domain(
        name=name, registrar=registrar, tld=name.rsplit(".", 1)[-1] if "." in name else "",
        expires=expires, auto_renew="", status="", category=category,
    )


# ---------- signal 1: portfolio_no_dir ----------


def test_signal_1_flags_domains_with_no_dir():
    portfolio = [
        _domain("alpha.com"),
        _domain("beta.com"),
        _domain("gamma.com"),
    ]
    sites = {"alpha.com"}  # only alpha has a dir
    out = _compute_signal_1(portfolio, sites)
    assert out == ["beta.com", "gamma.com"]


def test_signal_1_skips_domains_marked_for_deletion():
    """Don't flag absence on domains the user has already retired."""
    portfolio = [
        _domain("retired.com", category="To be deleted immediately"),
        _domain("active.com"),
    ]
    sites = set()
    out = _compute_signal_1(portfolio, sites)
    assert out == ["active.com"]
    assert "retired.com" not in out


# ---------- signal 2: csv_only ----------


def test_signal_2_flags_csv_domains_missing_from_portfolio():
    csv_doms = [
        _domain("new.com", registrar="GoDaddy"),
        _domain("known.com", registrar="Porkbun"),
    ]
    portfolio_names = {"known.com"}
    out = _compute_signal_2(csv_doms, portfolio_names)
    assert out == [("new.com", "GoDaddy")]


# ---------- signal 3: expiry_mismatches ----------


def test_signal_3_flags_date_mismatch():
    csv_doms = [_domain("x.com", expires=date(2027, 1, 15))]
    portfolio_doms = [_domain("x.com", expires=date(2026, 12, 1))]
    out = _compute_signal_3(csv_doms, portfolio_doms)
    assert len(out) == 1
    assert out[0].csv_expires == date(2027, 1, 15)
    assert out[0].json_expires == date(2026, 12, 1)


def test_signal_3_no_mismatch_when_dates_agree():
    csv_doms = [_domain("x.com", expires=date(2027, 1, 15))]
    portfolio_doms = [_domain("x.com", expires=date(2027, 1, 15))]
    assert _compute_signal_3(csv_doms, portfolio_doms) == []


def test_signal_3_skips_when_only_in_one_source():
    """Signal 3 only fires for domains in BOTH sources. Domains in CSV
    but not portfolio.json are signal 2, not signal 3."""
    csv_doms = [_domain("only-csv.com", expires=date(2027, 1, 15))]
    portfolio_doms = [_domain("only-json.com", expires=date(2027, 1, 15))]
    assert _compute_signal_3(csv_doms, portfolio_doms) == []


# ---------- signal 5: deployed_but_flagged ----------


def test_signal_5_flags_live_site_in_delete_category(monkeypatch, tmp_path):
    portfolio = [
        _domain("flagged.com", category="To be deleted immediately"),
        _domain("active.com", category="My brand"),
    ]
    snap = {"results": [
        {"domain": "flagged.com", "variant": "bare", "classification": "live-site"},
        {"domain": "active.com", "variant": "bare", "classification": "live-site"},
    ]}
    fake_path = tmp_path / "snap.json"
    fake_path.write_text("{}")
    import portfolio.check as check_module
    monkeypatch.setattr(check_module, "latest_snapshot", lambda: fake_path)
    monkeypatch.setattr(check_module, "load_snapshot", lambda _p: snap)

    out, skipped = _compute_signal_5(portfolio)
    assert skipped is False
    assert len(out) == 1
    assert out[0].domain == "flagged.com"
    assert out[0].classification == "live-site"


def test_signal_5_skipped_when_no_snapshot(monkeypatch):
    import portfolio.check as check_module
    monkeypatch.setattr(check_module, "latest_snapshot", lambda: None)
    out, skipped = _compute_signal_5([_domain("x.com", category="To be deleted immediately")])
    assert skipped is True
    assert out == []


def test_signal_5_no_flagged_when_no_delete_category(monkeypatch, tmp_path):
    """If nothing's marked for deletion, nothing to flag — return [],
    not skipped."""
    fake_path = tmp_path / "snap.json"
    fake_path.write_text("{}")
    import portfolio.check as check_module
    monkeypatch.setattr(check_module, "latest_snapshot", lambda: fake_path)
    monkeypatch.setattr(check_module, "load_snapshot", lambda _p: {"results": []})
    out, skipped = _compute_signal_5([_domain("x.com", category="My brand")])
    assert skipped is False
    assert out == []


# ---------- signal 6: duplicate_in_registrars ----------


def test_signal_6_flags_domains_in_multiple_registrars():
    csv_doms = [
        _domain("transferred.com", registrar="GoDaddy"),
        _domain("transferred.com", registrar="Porkbun"),
        _domain("clean.com", registrar="Namecheap"),
    ]
    out = _compute_signal_6(csv_doms)
    assert len(out) == 1
    assert out[0].domain == "transferred.com"
    assert sorted(out[0].registrars) == ["GoDaddy", "Porkbun"]


def test_signal_6_no_duplicates_when_all_unique():
    csv_doms = [
        _domain("a.com", registrar="GoDaddy"),
        _domain("b.com", registrar="Porkbun"),
    ]
    assert _compute_signal_6(csv_doms) == []


# ---------- _list_site_dirs filtering ----------


def test_list_site_dirs_filters_hidden_and_special(tmp_path):
    (tmp_path / "real.com").mkdir()
    (tmp_path / ".hidden").mkdir()
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "portfolio").mkdir()  # the CLI tool itself
    (tmp_path / "file.txt").write_text("not a dir")
    out = _list_site_dirs(tmp_path)
    assert out == {"real.com"}


def test_list_site_dirs_returns_empty_for_missing_dir(tmp_path):
    assert _list_site_dirs(tmp_path / "nope") == set()


def test_list_site_dirs_lowercases(tmp_path):
    (tmp_path / "Mixed.Case").mkdir()
    out = _list_site_dirs(tmp_path)
    assert out == {"mixed.case"}


# ---------- DriftReport.is_clean ----------


def test_is_clean_when_all_signals_empty():
    r = DriftReport()
    assert r.is_clean() is True


def test_is_clean_false_when_any_signal_populated():
    assert DriftReport(portfolio_no_dir=["x.com"]).is_clean() is False
    assert DriftReport(csv_only=[("x.com", "G")]).is_clean() is False
    assert DriftReport(duplicate_in_registrars=[
        DuplicateAcrossRegistrars(domain="x.com", registrars=["A", "B"])
    ]).is_clean() is False


# ---------- compute_drift integration ----------


def test_compute_drift_integration(monkeypatch, tmp_path):
    """End-to-end with patched data layer + filesystem."""
    portfolio = [
        _domain("alpha.com", expires=date(2027, 1, 15)),
        _domain("beta.com", expires=date(2027, 6, 1)),
    ]
    csv_doms = [
        _domain("alpha.com", registrar="GoDaddy", expires=date(2027, 2, 1)),  # mismatch
        _domain("new.com", registrar="Porkbun"),  # csv-only
        _domain("transferred.com", registrar="GoDaddy"),  # duplicate
        _domain("transferred.com", registrar="Porkbun"),  # duplicate
    ]
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "alpha.com").mkdir()  # has a dir
    # beta.com missing dir → portfolio_no_dir

    import portfolio.drift as drift_module
    monkeypatch.setattr(drift_module, "load_domains", lambda: portfolio)
    monkeypatch.setattr(drift_module, "_load_from_registrars", lambda: csv_doms)
    # Skip GSC + snapshot signals (they're optional / external).
    import portfolio.check as check_module
    monkeypatch.setattr(check_module, "latest_snapshot", lambda: None)

    report = compute_drift(sites_root=sites)
    assert "beta.com" in report.portfolio_no_dir
    assert ("new.com", "Porkbun") in report.csv_only
    assert any(e.domain == "alpha.com" for e in report.expiry_mismatches)
    assert any(d.domain == "transferred.com" for d in report.duplicate_in_registrars)
