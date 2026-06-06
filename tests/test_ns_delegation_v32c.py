"""v32.C — NS delegation honesty. The registrar API's stored NS value
("getNs says Cloudflare") is distinct from the real parent-zone delegation
("dig NS says ..."). Step 4 reports them separately and never treats a
registrar-API match as a completed cutover. Propagation-aware: an empty
`dig` answer is "awaiting delegation", not a failure. See ADR-0022 rule (b).
"""
from __future__ import annotations

from portfolio import cli

TARGET = ["alice.ns.cloudflare.com", "bob.ns.cloudflare.com"]


def _patch_dig(monkeypatch, answer):
    # diagnose._dig is imported inside the helper, so patch it at the source.
    from portfolio import diagnose
    monkeypatch.setattr(diagnose, "_dig",
                        lambda name, rtype: answer if rtype == "NS" else [])


def test_delegation_matches_when_dig_returns_cloudflare(monkeypatch):
    # dig answers carry a trailing dot + mixed case — helper normalizes.
    _patch_dig(monkeypatch, ["Alice.NS.Cloudflare.com.", "bob.ns.cloudflare.com."])
    delegated, matched = cli._ns_delegation("example.com", TARGET)
    assert matched is True
    assert delegated == ["alice.ns.cloudflare.com", "bob.ns.cloudflare.com"]


def test_delegation_mismatch_when_still_on_porkbun(monkeypatch):
    # Registrar API may say "Cloudflare", but the parent zone still delegates
    # to Porkbun (URL Forwarding pins Porkbun NS). matches=False, delegated set.
    _patch_dig(monkeypatch, ["curitiba.ns.porkbun.com.", "fortaleza.ns.porkbun.com."])
    delegated, matched = cli._ns_delegation("example.com", TARGET)
    assert matched is False
    assert delegated == ["curitiba.ns.porkbun.com", "fortaleza.ns.porkbun.com"]


def test_delegation_empty_is_awaiting_not_failure(monkeypatch):
    # dig returns nothing (propagating, or dig missing) → matches False, but
    # delegated is empty so callers print "awaiting", not a hard mismatch.
    _patch_dig(monkeypatch, [])
    delegated, matched = cli._ns_delegation("example.com", TARGET)
    assert matched is False
    assert delegated == []


def test_print_delegation_confirmed(monkeypatch, capsys):
    _patch_dig(monkeypatch, ["alice.ns.cloudflare.com", "bob.ns.cloudflare.com"])
    cli._print_ns_delegation("example.com", TARGET)
    out = capsys.readouterr().out
    assert "delegation confirmed" in out


def test_print_delegation_awaiting_when_mismatch(monkeypatch, capsys):
    _patch_dig(monkeypatch, ["curitiba.ns.porkbun.com"])
    cli._print_ns_delegation("example.com", TARGET)
    out = capsys.readouterr().out
    assert "awaiting delegation" in out
    assert "porkbun" in out  # shows the real delegated value


def test_print_delegation_not_visible_when_empty(monkeypatch, capsys):
    _patch_dig(monkeypatch, [])
    cli._print_ns_delegation("example.com", TARGET)
    out = capsys.readouterr().out
    assert "not yet visible" in out
