"""v45.B/D — `owner` field + the clients.csv fourth sync source.

Central invariant under test: a missing / blank / malformed `owner`
never fails or crashes anything — it reads as "lamill" (the operator's
own sites). Every pre-v45 portfolio.json and every registrar CSV row
must keep working untouched.
"""
from __future__ import annotations

import csv
import json

import pytest

from portfolio import data as D
from portfolio.data import (
    OWNER_SELF,
    Domain,
    _apply_classification,
    _domain_from_jsonable,
    _domain_to_jsonable,
    _load_clients,
    _merge_clients,
    append_client_row,
    normalize_owner,
)


def _dom(name="example.com", **kw):
    base = dict(name=name, registrar="porkbun", tld=".com", expires=None,
                auto_renew="", status="Active")
    base.update(kw)
    return Domain(**base)


# --- normalize_owner: never raises -----------------------------------

@pytest.mark.parametrize("value", [None, "", "   ", "\t\n", 0, 3, [], {}, object()])
def test_normalize_owner_defaults_to_self_for_anything_unusable(value):
    assert normalize_owner(value) == OWNER_SELF


@pytest.mark.parametrize("value,expected", [
    ("Acme Roofing", "Acme Roofing"),
    ("  Acme  ", "Acme"),
    ("lamill", "lamill"),
    ("  lamill  ", "lamill"),
])
def test_normalize_owner_preserves_real_values(value, expected):
    assert normalize_owner(value) == expected


# --- Domain defaults --------------------------------------------------

def test_domain_defaults_to_self_owned():
    d = _dom()
    assert d.owner == OWNER_SELF
    assert d.is_client is False


def test_domain_with_client_owner_is_client():
    assert _dom(owner="Acme Roofing").is_client is True


def test_is_client_tolerates_blank_owner():
    d = _dom()
    d.owner = "   "
    assert d.is_client is False


# --- portfolio.json round-trip ---------------------------------------

def test_pre_v45_row_without_owner_parses_as_self():
    """The backward-compatibility guarantee: no migration needed."""
    row = {"name": "old.com", "registrar": "godaddy", "tld": ".com"}
    assert _domain_from_jsonable(row).owner == OWNER_SELF


def test_row_with_blank_owner_parses_as_self():
    row = {"name": "old.com", "registrar": "godaddy", "owner": "  "}
    assert _domain_from_jsonable(row).owner == OWNER_SELF


def test_row_with_null_owner_parses_as_self():
    row = {"name": "old.com", "registrar": "godaddy", "owner": None}
    assert _domain_from_jsonable(row).owner == OWNER_SELF


def test_owner_round_trips():
    d = _dom(owner="Acme Roofing")
    assert _domain_to_jsonable(d)["owner"] == "Acme Roofing"
    assert _domain_from_jsonable(_domain_to_jsonable(d)).owner == "Acme Roofing"


def test_schema_version_is_2():
    assert D.PORTFOLIO_SCHEMA_VERSION == 2


# --- clients.csv loader ----------------------------------------------

def _write_csv(path, text):
    path.write_text(text)
    return path


def test_load_clients_absent_file_is_empty(tmp_path):
    assert _load_clients(tmp_path / "nope.csv") == []


def test_load_clients_reads_rows(tmp_path):
    p = _write_csv(tmp_path / "clients.csv",
                   "domain,owner,category\n"
                   "clientsite.com,Acme Roofing,Client sites\n")
    rows = _load_clients(p)
    assert len(rows) == 1
    r = rows[0]
    assert r.name == "clientsite.com"
    assert r.owner == "Acme Roofing"
    assert r.category == "Client sites"
    assert r.registrar == D.REGISTRAR_OTHER
    assert r.tld == ".com"
    assert r.is_client is True


def test_load_clients_row_without_owner_is_self_not_a_crash(tmp_path):
    p = _write_csv(tmp_path / "clients.csv", "domain,owner\nfoo.com,\n")
    assert _load_clients(p)[0].owner == OWNER_SELF


def test_load_clients_missing_owner_column_is_self_not_a_crash(tmp_path):
    p = _write_csv(tmp_path / "clients.csv", "domain\nfoo.com\n")
    rows = _load_clients(p)
    assert len(rows) == 1 and rows[0].owner == OWNER_SELF


def test_load_clients_accepts_name_column_alias(tmp_path):
    p = _write_csv(tmp_path / "clients.csv", "name,owner\nfoo.com,Acme\n")
    assert _load_clients(p)[0].name == "foo.com"


def test_load_clients_skips_blank_and_comment_rows(tmp_path):
    p = _write_csv(tmp_path / "clients.csv",
                   "domain,owner\n,Acme\n# note,Acme\nfoo.com,Acme\n")
    assert [r.name for r in _load_clients(p)] == ["foo.com"]


def test_load_clients_lowercases_and_strips(tmp_path):
    p = _write_csv(tmp_path / "clients.csv", "domain,owner\n  FOO.COM ,Acme\n")
    assert _load_clients(p)[0].name == "foo.com"


def test_load_clients_garbage_file_returns_empty_not_crash(tmp_path):
    p = _write_csv(tmp_path / "clients.csv", "\x00\x01 not a csv at all")
    assert isinstance(_load_clients(p), list)


def test_load_clients_unreadable_file_returns_empty(tmp_path):
    p = tmp_path / "clients.csv"
    p.mkdir()  # a directory where a file is expected
    assert _load_clients(p) == []


# --- merge into the registrar-derived set -----------------------------

def test_merge_appends_new_client_domain():
    out = _merge_clients([_dom("mine.com")],
                         [_dom("client.com", registrar="other", owner="Acme")])
    assert [d.name for d in out] == ["mine.com", "client.com"]


def test_merge_applies_owner_to_an_existing_registrar_row():
    """Operator registered the domain on the client's behalf: registrar
    truth wins, roster contributes only owner."""
    mine = _dom("shared.com", registrar="porkbun", auto_renew="On")
    _merge_clients([mine], [_dom("shared.com", registrar="other", owner="Acme")])
    assert mine.owner == "Acme"
    assert mine.registrar == "porkbun"
    assert mine.auto_renew == "On"


def test_merge_fills_category_only_when_absent():
    have = _dom("a.com", category="Existing")
    lack = _dom("b.com", category=None)
    _merge_clients([have, lack], [
        _dom("a.com", owner="Acme", category="Roster"),
        _dom("b.com", owner="Acme", category="Roster"),
    ])
    assert have.category == "Existing"
    assert lack.category == "Roster"


def test_merge_with_empty_roster_is_a_noop():
    rows = [_dom("mine.com")]
    assert _merge_clients(rows, []) == rows


# --- classification ---------------------------------------------------

def test_classification_preserves_roster_category():
    d = _dom("client.com", registrar="other", owner="Acme",
             category="Client sites")
    out, uncategorized = _apply_classification([d], {})
    assert out[0].category == "Client sites"
    assert "client.com" not in uncategorized


def test_classification_still_derives_for_own_domains():
    d = _dom("mine.com", registrar="porkbun", category=None)
    out, _ = _apply_classification([d], {})
    assert out[0].category == "Under build"


# --- append_client_row -------------------------------------------------

def test_append_client_row_creates_file_with_header(tmp_path):
    p = tmp_path / "clients.csv"
    assert append_client_row(name="c.com", owner="Acme", path=p) == "added"
    rows = list(csv.DictReader(p.open(newline="")))
    assert rows == [{"domain": "c.com", "owner": "Acme", "category": ""}]


def test_append_client_row_is_idempotent(tmp_path):
    p = tmp_path / "clients.csv"
    append_client_row(name="c.com", owner="Acme", path=p)
    assert append_client_row(name="c.com", owner="Acme", path=p) == "exists"
    assert len(list(csv.DictReader(p.open(newline="")))) == 1


def test_append_client_row_preserves_existing_rows(tmp_path):
    p = tmp_path / "clients.csv"
    append_client_row(name="a.com", owner="Acme", path=p)
    append_client_row(name="b.com", owner="Beta", category="Client sites", path=p)
    rows = list(csv.DictReader(p.open(newline="")))
    assert [r["domain"] for r in rows] == ["a.com", "b.com"]
    assert rows[1]["category"] == "Client sites"


@pytest.mark.parametrize("owner", ["lamill", "", "  ", None])
def test_append_client_row_skips_non_clients(tmp_path, owner):
    p = tmp_path / "clients.csv"
    assert append_client_row(name="mine.com", owner=owner, path=p) == "skipped"
    assert not p.exists()


def test_append_client_row_skips_blank_domain(tmp_path):
    p = tmp_path / "clients.csv"
    assert append_client_row(name="  ", owner="Acme", path=p) == "skipped"


def test_append_client_row_round_trips_through_loader(tmp_path):
    p = tmp_path / "clients.csv"
    append_client_row(name="c.com", owner="Acme", category="Client sites", path=p)
    loaded = _load_clients(p)[0]
    assert (loaded.name, loaded.owner, loaded.category) == (
        "c.com", "Acme", "Client sites")


# --- cleanup(): the delete-on-sync bug this tier fixes ------------------

def test_client_domain_survives_cleanup(tmp_path, monkeypatch):
    """The core v45.D guarantee: a client domain is a *source*, so the
    portfolio.json rebuild can't delete it."""
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    (domains_dir / "clients.csv").write_text(
        "domain,owner,category\nclientsite.com,Acme Roofing,Client sites\n")
    pj = tmp_path / "portfolio.json"
    monkeypatch.setattr(D, "DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(D, "CLIENTS_CSV", domains_dir / "clients.csv")
    monkeypatch.setattr(D, "PORTFOLIO_JSON", pj)
    monkeypatch.setattr(D, "PLAN_MD", tmp_path / "plan.md")

    for _ in range(2):  # rebuild twice — the row must not vanish
        D.cleanup()

    payload = json.loads(pj.read_text())
    assert payload["schema_version"] == 2
    rows = {r["name"]: r for r in payload["domains"]}
    assert rows["clientsite.com"]["owner"] == "Acme Roofing"
    assert rows["clientsite.com"]["registrar"] == "other"
    assert rows["clientsite.com"]["category"] == "Client sites"


def test_cleanup_stamps_self_owner_on_registrar_domains(tmp_path, monkeypatch):
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    (domains_dir / "porkbun.csv").write_text(
        "DOMAIN,TLD,STATUSES,CREATE DATE,EXPIRE DATE,AUTO RENEW\n"
        "mine.com,com,ACTIVE,2024-01-01,2027-01-01,On\n")
    pj = tmp_path / "portfolio.json"
    monkeypatch.setattr(D, "DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(D, "CLIENTS_CSV", domains_dir / "clients.csv")
    monkeypatch.setattr(D, "PORTFOLIO_JSON", pj)
    monkeypatch.setattr(D, "PLAN_MD", tmp_path / "plan.md")
    D.cleanup()
    rows = json.loads(pj.read_text())["domains"]
    assert rows[0]["owner"] == OWNER_SELF


# --- `new bootstrap --owner` routing -----------------------------------

def test_resolve_routes_client_owner_to_roster():
    from portfolio.bootstrap_cli import _resolve_inventory_inputs
    d = _resolve_inventory_inputs(domain="c.com", registered=None,
                                  registrar="", non_interactive=True,
                                  owner="Acme Roofing")
    assert d["action"] == "append-client"
    assert d["owner"] == "Acme Roofing"


@pytest.mark.parametrize("owner", ["", "  ", "lamill"])
def test_resolve_keeps_own_domains_on_the_portfolio_json_path(owner):
    from portfolio.bootstrap_cli import _resolve_inventory_inputs
    d = _resolve_inventory_inputs(domain="mine.com", registered=True,
                                  registrar="porkbun", non_interactive=True,
                                  owner=owner)
    assert d["action"] == "append"
    assert d["owner"] == OWNER_SELF


def test_resolve_owner_omitted_entirely_is_backward_compatible():
    """Callers that never pass `owner` must behave exactly as before."""
    from portfolio.bootstrap_cli import _resolve_inventory_inputs
    d = _resolve_inventory_inputs(domain="mine.com", registered=True,
                                  registrar="porkbun", non_interactive=True)
    assert d["action"] == "append" and d["owner"] == OWNER_SELF


def test_client_route_skips_registrar_prompts_when_interactive(monkeypatch):
    """A client's registrar isn't the operator's to record — the client
    branch must short-circuit before any prompt fires."""
    import typer
    from portfolio import bootstrap_cli

    def _boom(*a, **k):
        raise AssertionError("prompted on the client path")

    monkeypatch.setattr(typer, "prompt", _boom)
    d = bootstrap_cli._resolve_inventory_inputs(
        domain="c.com", registered=None, registrar="",
        non_interactive=False, owner="Acme")
    assert d["action"] == "append-client"


def test_apply_decision_writes_roster(tmp_path, monkeypatch):
    from portfolio import bootstrap_cli
    from portfolio import data as _D
    p = tmp_path / "clients.csv"
    monkeypatch.setattr(_D, "CLIENTS_CSV", p)
    bootstrap_cli._apply_inventory_decision(
        "c.com", {"action": "append-client", "owner": "Acme"})
    assert list(csv.DictReader(p.open(newline="")))[0]["owner"] == "Acme"


def test_apply_decision_client_path_never_touches_portfolio_json(tmp_path, monkeypatch):
    from portfolio import bootstrap_cli
    from portfolio import data as _D
    pj = tmp_path / "portfolio.json"
    pj.write_text(json.dumps({"schema_version": 2, "domains": []}))
    monkeypatch.setattr(_D, "CLIENTS_CSV", tmp_path / "clients.csv")
    monkeypatch.setattr(_D, "PORTFOLIO_JSON", pj)
    bootstrap_cli._apply_inventory_decision(
        "c.com", {"action": "append-client", "owner": "Acme"})
    assert json.loads(pj.read_text())["domains"] == []
