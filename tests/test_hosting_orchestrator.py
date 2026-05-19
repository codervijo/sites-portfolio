"""Tests for v11.E — `run_hosting()` orchestrator.

Mocks at the walker layer (not httpx) — orchestrator's job is task
fan-out, error capture, and conflict-flagging; the walker internals
are already tested in test_hosting_{vercel,cf_pages,hostgator}.py.
"""
from __future__ import annotations

import pytest

from portfolio import apikeys, hosting
from portfolio.hosting import (
    CFPagesAuthError,
    HostGatorAuthError,
    HostingResult,
    HostingRow,
    PROVIDER_CF_PAGES,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    VercelAuthError,
    VercelWalkError,
    _flag_provider_conflicts,
    _hg_account_ids_from_apikeys,
    run_hosting,
)


# ---- _flag_provider_conflicts ------------------------------------


def test_flag_provider_conflicts_marks_cross_provider_drift():
    """Same domain matched by Vercel + CF → both rows get conflict=True
    per resolution 11.F (two-row drift surface)."""
    rows = [
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="x.com", provider=PROVIDER_CF_PAGES),
        HostingRow(domain="y.com", provider=PROVIDER_VERCEL),  # single provider
    ]
    _flag_provider_conflicts(rows)
    assert rows[0].provider_conflict is True
    assert rows[1].provider_conflict is True
    # Single-provider row stays clean.
    assert rows[2].provider_conflict is False


def test_flag_provider_conflicts_flags_when_unowned_shares_domain_with_walked_row():
    """Updated 2026-05-19 — flag fires when ≥2 rows share a domain,
    regardless of provider identity. Includes provider=None rows."""
    rows = [
        HostingRow(domain="x.com", provider=None),
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL),
    ]
    _flag_provider_conflicts(rows)
    assert all(r.provider_conflict for r in rows)


def test_flag_provider_conflicts_flags_same_provider_duplicate():
    """v11.D hand test 2026-05-19 — `hybridautopart.com` showed up
    as an addon on both gator3164 AND gator4216 (one site, two
    HG accounts). Both rows carry `provider="hostgator"`, so the
    original cross-provider check missed them. Updated rule flags
    any duplicate domain — same-provider counts."""
    rows = [
        HostingRow(domain="hybridautopart.com", provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
        HostingRow(domain="hybridautopart.com", provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator4216"),
    ]
    _flag_provider_conflicts(rows)
    assert all(r.provider_conflict for r in rows)


def test_flag_provider_conflicts_no_op_when_each_domain_unique():
    """Negative — single row per domain → no flag set."""
    rows = [
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
        HostingRow(domain="c.com", provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
    ]
    _flag_provider_conflicts(rows)
    assert all(not r.provider_conflict for r in rows)


# ---- _hg_account_ids_from_apikeys ---------------------------------


def test_hg_account_ids_from_apikeys_enumerates_configured(monkeypatch):
    """Returns lowercased account_ids for every HOSTGATOR_TOKEN_<ID>
    that's actually set in portfolio.env."""
    def _fake_get(key: str) -> str | None:
        return {
            "HOSTGATOR_TOKEN_GATOR3164": "hg-tok-1",
            "HOSTGATOR_TOKEN_GATOR4216": "hg-tok-2",
        }.get(key)
    monkeypatch.setattr(apikeys, "get_key", _fake_get)

    accounts = _hg_account_ids_from_apikeys()
    assert set(accounts) == {"gator3164", "gator4216"}


def test_hg_account_ids_skips_unset_tokens(monkeypatch):
    """KNOWN_KEYS lists both accounts but only one token is set —
    only that one is returned."""
    monkeypatch.setattr(
        apikeys, "get_key",
        lambda key: "tok" if key == "HOSTGATOR_TOKEN_GATOR3164" else None,
    )
    accounts = _hg_account_ids_from_apikeys()
    assert accounts == ["gator3164"]


# ---- run_hosting happy path --------------------------------------


def _patch_walkers(monkeypatch, *, vercel_rows=None, cf_rows=None,
                   cf_workers_rows=None,
                   hg_rows_by_account=None,
                   vercel_raises=None, cf_raises=None,
                   cf_workers_raises=None,
                   hg_raises_by_account=None):
    """Stub all four walkers with deterministic return values or
    raised exceptions. Captures the call args for assertion.

    v11.H added CF Workers — stubs default to empty rows so tests
    that don't care about Workers don't have to set them up explicitly."""
    calls: dict[str, list[dict]] = {
        "vercel": [], "cf": [], "cf_workers": [], "hg": [],
    }

    def _vercel(token, fleet_domains, *, only_domain=None, **kw):
        calls["vercel"].append({
            "token": token, "fleet_domains": fleet_domains,
            "only_domain": only_domain,
        })
        if vercel_raises is not None:
            raise vercel_raises
        return list(vercel_rows or [])

    def _cf(token, account_id, fleet_domains, *, only_domain=None, **kw):
        calls["cf"].append({
            "token": token, "account_id": account_id,
            "fleet_domains": fleet_domains, "only_domain": only_domain,
        })
        if cf_raises is not None:
            raise cf_raises
        return list(cf_rows or [])

    def _cf_workers(token, account_id, fleet_domains, *, only_domain=None, **kw):
        calls["cf_workers"].append({
            "token": token, "account_id": account_id,
            "fleet_domains": fleet_domains, "only_domain": only_domain,
        })
        if cf_workers_raises is not None:
            raise cf_workers_raises
        return list(cf_workers_rows or [])

    def _hg(token, account_id, fleet_domains, *, only_domain=None, **kw):
        calls["hg"].append({
            "token": token, "account_id": account_id,
            "fleet_domains": fleet_domains, "only_domain": only_domain,
        })
        if hg_raises_by_account and account_id in hg_raises_by_account:
            raise hg_raises_by_account[account_id]
        rows = (hg_rows_by_account or {}).get(account_id, [])
        return list(rows)

    monkeypatch.setattr(hosting, "walk_vercel", _vercel)
    monkeypatch.setattr(hosting, "walk_cf_pages", _cf)
    monkeypatch.setattr(hosting, "walk_cf_workers", _cf_workers)
    monkeypatch.setattr(hosting, "walk_hostgator", _hg)
    return calls


def _patch_tokens(monkeypatch, **tokens):
    """Stub apikeys.get_key with a dict-of-tokens. Missing keys → None."""
    monkeypatch.setattr(apikeys, "get_key", lambda k: tokens.get(k))


def test_run_hosting_all_providers_configured_collects_all_rows(monkeypatch):
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc-tok",
                  CF_API_TOKEN="cf-tok",
                  CF_ACCOUNT_ID="cf-acct",
                  HOSTGATOR_TOKEN_GATOR3164="hg-tok-1",
                  HOSTGATOR_TOKEN_GATOR4216="hg-tok-2")
    _patch_walkers(
        monkeypatch,
        vercel_rows=[HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL)],
        cf_rows=[HostingRow(domain="calcengine.site", provider=PROVIDER_CF_PAGES)],
        hg_rows_by_account={
            "gator3164": [HostingRow(domain="hybridautopart.com",
                                     provider=PROVIDER_HOSTGATOR,
                                     hg_account_id="gator3164")],
            "gator4216": [HostingRow(domain="streamsgalaxy.com",
                                     provider=PROVIDER_HOSTGATOR,
                                     hg_account_id="gator4216")],
        },
    )

    result = run_hosting(
        fleet_domains={"airsucks.com", "calcengine.site",
                       "hybridautopart.com", "streamsgalaxy.com"},
    )
    assert isinstance(result, HostingResult)
    assert {r.domain for r in result.rows} == {
        "airsucks.com", "calcengine.site",
        "hybridautopart.com", "streamsgalaxy.com",
    }
    # All providers ran cleanly — no skips.
    assert result.skipped == {}


def test_run_hosting_missing_vercel_token_skips_vercel(monkeypatch):
    """No VERCEL_TOKEN → vercel walker isn't even called; reported
    in `skipped`."""
    _patch_tokens(monkeypatch, CF_API_TOKEN="cf-tok", CF_ACCOUNT_ID="cf-acct")
    calls = _patch_walkers(monkeypatch,
                           cf_rows=[HostingRow(domain="x.com",
                                               provider=PROVIDER_CF_PAGES)])
    result = run_hosting(fleet_domains={"x.com"})
    assert calls["vercel"] == []                          # never called
    assert "vercel" in result.skipped
    assert "VERCEL_TOKEN" in result.skipped["vercel"]
    # CF rows still collected.
    assert any(r.provider == PROVIDER_CF_PAGES for r in result.rows)


def test_run_hosting_missing_cf_pair_skips_cf(monkeypatch):
    """CF needs both CF_API_TOKEN AND CF_ACCOUNT_ID; missing either skips."""
    _patch_tokens(monkeypatch, VERCEL_TOKEN="vc",
                  CF_API_TOKEN="cf-tok")  # CF_ACCOUNT_ID missing
    calls = _patch_walkers(monkeypatch)
    result = run_hosting(fleet_domains=set())
    assert calls["cf"] == []
    assert "cloudflare-pages" in result.skipped
    assert "CF_ACCOUNT_ID" in result.skipped["cloudflare-pages"]


def test_run_hosting_no_hg_tokens_skips_hostgator(monkeypatch):
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc", CF_API_TOKEN="cf", CF_ACCOUNT_ID="acct")
    calls = _patch_walkers(monkeypatch)
    result = run_hosting(fleet_domains=set())
    assert calls["hg"] == []
    assert "hostgator" in result.skipped


def test_run_hosting_walker_auth_error_recorded_in_skipped(monkeypatch):
    """A walker raising *AuthError mid-call → recorded as skipped, but
    other walkers' results still come back (resolution 11.H)."""
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc-bad",
                  CF_API_TOKEN="cf", CF_ACCOUNT_ID="acct")
    _patch_walkers(monkeypatch,
                   vercel_raises=VercelAuthError("vercel 401"),
                   cf_rows=[HostingRow(domain="x.com",
                                       provider=PROVIDER_CF_PAGES)])
    result = run_hosting(fleet_domains={"x.com"})
    assert "vercel" in result.skipped
    assert "auth" in result.skipped["vercel"]
    # CF still produced a row.
    assert len(result.rows) == 1
    assert result.rows[0].provider == PROVIDER_CF_PAGES


def test_run_hosting_walker_walk_error_recorded_in_skipped(monkeypatch):
    """Non-auth walker failure (5xx mid-walk) → also recorded; other
    providers unaffected."""
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc",
                  CF_API_TOKEN="cf", CF_ACCOUNT_ID="acct")
    _patch_walkers(monkeypatch,
                   vercel_raises=VercelWalkError("502 on projects list"),
                   cf_rows=[HostingRow(domain="x.com",
                                       provider=PROVIDER_CF_PAGES)])
    result = run_hosting(fleet_domains={"x.com"})
    assert "vercel" in result.skipped
    assert "walker" in result.skipped["vercel"]


def test_run_hosting_per_hg_account_failure_isolated(monkeypatch):
    """One HG account's auth fails; the OTHER account's walker still
    runs and emits rows. Each account is its own skipped entry."""
    _patch_tokens(monkeypatch,
                  HOSTGATOR_TOKEN_GATOR3164="hg-bad",
                  HOSTGATOR_TOKEN_GATOR4216="hg-good")
    _patch_walkers(
        monkeypatch,
        hg_rows_by_account={
            "gator4216": [HostingRow(domain="streamsgalaxy.com",
                                     provider=PROVIDER_HOSTGATOR,
                                     hg_account_id="gator4216")],
        },
        hg_raises_by_account={
            "gator3164": HostGatorAuthError("gator3164 401"),
        },
    )
    result = run_hosting(fleet_domains={"streamsgalaxy.com"})
    assert "hostgator:gator3164" in result.skipped
    # gator4216 still produced a row.
    assert any(r.hg_account_id == "gator4216" for r in result.rows)


def test_run_hosting_flags_provider_conflict_on_cross_provider_match(monkeypatch):
    """Same domain on Vercel + CF → both rows come back with
    `provider_conflict=True` (resolution 11.F)."""
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc",
                  CF_API_TOKEN="cf", CF_ACCOUNT_ID="acct")
    _patch_walkers(
        monkeypatch,
        vercel_rows=[HostingRow(domain="x.com", provider=PROVIDER_VERCEL)],
        cf_rows=[HostingRow(domain="x.com", provider=PROVIDER_CF_PAGES)],
    )
    result = run_hosting(fleet_domains={"x.com"})
    assert len(result.rows) == 2
    assert all(r.provider_conflict for r in result.rows)


def test_run_hosting_only_domain_forwarded_to_walkers(monkeypatch):
    """`only_domain` arg must reach every walker — otherwise the
    single-domain probe collects unrelated rows."""
    _patch_tokens(monkeypatch,
                  VERCEL_TOKEN="vc",
                  CF_API_TOKEN="cf", CF_ACCOUNT_ID="acct",
                  HOSTGATOR_TOKEN_GATOR3164="hg")
    calls = _patch_walkers(monkeypatch)
    run_hosting(fleet_domains={"x.com"}, only_domain="x.com")
    assert calls["vercel"][0]["only_domain"] == "x.com"
    assert calls["cf"][0]["only_domain"] == "x.com"
    assert calls["hg"][0]["only_domain"] == "x.com"


def test_run_hosting_empty_token_set_returns_empty(monkeypatch):
    """All tokens missing → every walker is skipped, no rows."""
    _patch_tokens(monkeypatch)  # no tokens
    calls = _patch_walkers(monkeypatch)
    result = run_hosting(fleet_domains={"x.com"})
    assert result.rows == []
    assert set(result.skipped.keys()) == {
        "vercel", "cloudflare-pages", "cloudflare-workers", "hostgator",
    }
    assert calls["vercel"] == []
    assert calls["cf"] == []
    assert calls["hg"] == []
