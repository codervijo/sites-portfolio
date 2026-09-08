"""v45.F — registrar-truth gaps on client-owned domains.

The operator holds no registrar credential for a client's account, so
`auto_renew` is genuinely unknown and `expires` has no CSV/API source.
The posture: say "unknown" where it's unknown, but **fetch expiry from
RDAP rather than muting it** — a client letting the domain lapse kills
the site, and it's the operator who gets blamed.
"""
from __future__ import annotations

from datetime import date

import pytest

from portfolio import availability
from portfolio.data import OWNER_SELF, Domain
from portfolio.focus import build_focus_list


def _dom(name, **kw):
    base = dict(name=name, registrar="other", tld=".com", expires=None,
                auto_renew="", status="Active")
    base.update(kw)
    return Domain(**base)


# --- rdap_expiry_date --------------------------------------------------

def _rdap(monkeypatch, events):
    monkeypatch.setattr(availability, "_load_rdap_endpoints",
                        lambda: {"com": ["https://rdap.test/"]})

    class _R:
        status_code = 200

        @staticmethod
        def json():
            return {"events": events}

    monkeypatch.setattr(availability.requests, "get", lambda *a, **k: _R())


def test_rdap_expiry_date_reads_the_expiration_event(monkeypatch):
    _rdap(monkeypatch, [
        {"eventAction": "registration", "eventDate": "2020-03-01T00:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-03-01T00:00:00Z"},
    ])
    assert availability.rdap_expiry_date("x.com") == date(2027, 3, 1)


def test_rdap_creation_date_still_reads_registration(monkeypatch):
    """The refactor must not move the existing behavior."""
    _rdap(monkeypatch, [
        {"eventAction": "registration", "eventDate": "2020-03-01T00:00:00Z"},
        {"eventAction": "expiration", "eventDate": "2027-03-01T00:00:00Z"},
    ])
    assert availability.rdap_creation_date("x.com") == date(2020, 3, 1)


def test_rdap_expiry_absent_event_is_none(monkeypatch):
    _rdap(monkeypatch, [{"eventAction": "registration",
                         "eventDate": "2020-03-01T00:00:00Z"}])
    assert availability.rdap_expiry_date("x.com") is None


def test_rdap_expiry_date_only_form(monkeypatch):
    _rdap(monkeypatch, [{"eventAction": "expiration", "eventDate": "2027-03-01"}])
    assert availability.rdap_expiry_date("x.com") == date(2027, 3, 1)


def test_rdap_expiry_unknown_tld_is_none(monkeypatch):
    monkeypatch.setattr(availability, "_load_rdap_endpoints", lambda: {})
    assert availability.rdap_expiry_date("x.nope") is None


def test_rdap_expiry_network_error_is_none_not_raise(monkeypatch):
    monkeypatch.setattr(availability, "_load_rdap_endpoints",
                        lambda: {"com": ["https://rdap.test/"]})

    def _boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(availability.requests, "get", _boom)
    assert availability.rdap_expiry_date("x.com") is None


def test_rdap_expiry_malformed_date_is_none(monkeypatch):
    _rdap(monkeypatch, [{"eventAction": "expiration", "eventDate": "not-a-date"}])
    assert availability.rdap_expiry_date("x.com") is None


# --- focus: signal kept, action retargeted -----------------------------

def _focus(owners, days=10):
    return build_focus_list(
        live_snapshot=None, seo_snapshot=None,
        domains_with_expiry=[("client.com", days)],
        domain_owners=owners,
    )


def _expiry_signal(items):
    for it in items:
        for emoji, headline, action in it.signals:
            if "Expiring" in headline:
                return action
    return None


def test_client_domain_expiry_action_names_the_client():
    assert _expiry_signal(_focus({"client.com": "Acme Roofing"})) == (
        "→ client-owned (Acme Roofing) — ask them to renew")


def test_own_domain_keeps_the_registrar_action():
    assert _expiry_signal(_focus({"client.com": OWNER_SELF})) == (
        "→ renew at registrar before lapse")


def test_missing_owner_map_keeps_the_registrar_action():
    """Backward compatibility: callers that don't pass owners are unchanged."""
    items = build_focus_list(live_snapshot=None, seo_snapshot=None,
                             domains_with_expiry=[("client.com", 10)])
    assert _expiry_signal(items) == "→ renew at registrar before lapse"


def test_blank_owner_is_treated_as_self():
    assert _expiry_signal(_focus({"client.com": "  "})) == (
        "→ renew at registrar before lapse")


def test_client_expiry_is_not_suppressed():
    """The whole point: the signal survives, only its action changes."""
    items = _focus({"client.com": "Acme Roofing"})
    assert any("Expiring in 10 days" in h
               for it in items for _, h, _ in it.signals)


def test_owner_lookup_is_case_insensitive():
    assert _expiry_signal(
        build_focus_list(live_snapshot=None, seo_snapshot=None,
                         domains_with_expiry=[("Client.com", 10)],
                         domain_owners={"CLIENT.COM": "Acme"})
    ) == "→ client-owned (Acme) — ask them to renew"


# --- expiring table: unknown is stated, not blank ----------------------

def test_client_auto_renew_renders_as_unknown(monkeypatch, capsys):
    from portfolio import fleet_cli
    monkeypatch.setattr(fleet_cli, "load_domains", lambda: [
        _dom("client.com", owner="Acme Roofing",
             expires=date.today().replace(year=date.today().year + 1)),
    ])
    fleet_cli.info_expiring(within=400)
    assert "unknown" in capsys.readouterr().out


def test_own_domain_auto_renew_unchanged(monkeypatch, capsys):
    from portfolio import fleet_cli
    monkeypatch.setattr(fleet_cli, "load_domains", lambda: [
        _dom("mine.com", registrar="porkbun", auto_renew="On",
             expires=date.today().replace(year=date.today().year + 1)),
    ])
    fleet_cli.info_expiring(within=400)
    out = capsys.readouterr().out
    assert "On" in out and "unknown" not in out


def test_client_with_known_auto_renew_is_not_overwritten(monkeypatch, capsys):
    """If a value is somehow known, don't relabel it."""
    from portfolio import fleet_cli
    monkeypatch.setattr(fleet_cli, "load_domains", lambda: [
        _dom("client.com", owner="Acme", auto_renew="On",
             expires=date.today().replace(year=date.today().year + 1)),
    ])
    fleet_cli.info_expiring(within=400)
    assert "unknown" not in capsys.readouterr().out


# --- fleet sync --refresh-rdap: expiry pulled for clients only ---------

def _sync(monkeypatch, domains, *, expiry=date(2027, 3, 1)):
    from portfolio import fleet_cli
    updates: list[tuple[str, str, object]] = []
    monkeypatch.setattr(fleet_cli, "run_cleanup",
                        lambda: (__import__("pathlib").Path("p.json"), domains, []))
    monkeypatch.setattr("portfolio.data.update_domain_field",
                        lambda n, f, v: updates.append((n, f, v)) or True)
    monkeypatch.setattr("portfolio.availability.rdap_creation_date",
                        lambda n, **k: date(2020, 1, 1))
    monkeypatch.setattr("portfolio.availability.rdap_expiry_date",
                        lambda n, **k: expiry)
    fleet_cli.info_cleanup(refresh_rdap=True)
    return updates


def test_client_domain_gets_rdap_expiry(monkeypatch):
    updates = _sync(monkeypatch, [_dom("client.com", owner="Acme")])
    assert ("client.com", "expires", date(2027, 3, 1)) in updates


def test_own_domain_does_not_get_rdap_expiry(monkeypatch):
    """Registrar CSV/API is authoritative for our own domains — don't
    spend an RDAP call, and don't let RDAP overwrite registrar truth."""
    updates = _sync(monkeypatch, [_dom("mine.com", registrar="porkbun")])
    assert not any(f == "expires" for _, f, _ in updates)


def test_client_expiry_refetched_even_when_already_set(monkeypatch):
    """Unlike creation_date, expiry moves on renewal — a cached value
    going stale is the failure this phase exists to prevent."""
    updates = _sync(monkeypatch, [
        _dom("client.com", owner="Acme", expires=date(2026, 1, 1),
             domain_created=date(2020, 1, 1)),
    ])
    assert ("client.com", "expires", date(2027, 3, 1)) in updates


def test_unresolvable_client_expiry_writes_nothing(monkeypatch):
    updates = _sync(monkeypatch, [_dom("client.com", owner="Acme")],
                    expiry=None)
    assert not any(f == "expires" for _, f, _ in updates)


def test_creation_date_still_skipped_when_cached(monkeypatch):
    updates = _sync(monkeypatch, [
        _dom("mine.com", registrar="porkbun", domain_created=date(2019, 5, 5)),
    ])
    assert not any(f == "domain_created" for _, f, _ in updates)
