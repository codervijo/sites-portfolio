"""v45.H — optional client questions in `new bootstrap`.

Contact → clients.csv columns; business context → lamill.toml [client].
"""
from __future__ import annotations

import csv
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from portfolio import bootstrap as bs_mod
from portfolio import bootstrap_cli as bc_mod
from portfolio import data as data_mod
from portfolio.cli import app


# ---------- append_client_row ----------


def test_append_client_row_writes_contact_columns(tmp_path):
    path = tmp_path / "clients.csv"
    data_mod.append_client_row(
        name="a.com", owner="Derek Hoyt",
        contact_name="Derek", contact_email="d@a.com", path=path,
    )
    rows = list(csv.DictReader(path.open()))
    assert rows == [{"domain": "a.com", "owner": "Derek Hoyt", "category": "",
                     "contact_name": "Derek", "contact_email": "d@a.com"}]


def test_append_client_row_preserves_hand_added_columns(tmp_path):
    path = tmp_path / "clients.csv"
    path.write_text("domain,owner,category,phone\nold.com,Acme,,555-1234\n")
    data_mod.append_client_row(name="new.com", owner="Acme", path=path)
    rows = list(csv.DictReader(path.open()))
    assert rows[0]["phone"] == "555-1234"
    assert rows[0]["domain"] == "old.com"
    assert rows[1]["domain"] == "new.com"
    assert rows[1]["phone"] == ""
    # And the reader still loads both.
    assert {d.name for d in data_mod._load_clients(path)} == {"old.com", "new.com"}


# ---------- _resolve_client_details ----------


def test_resolve_not_client_is_empty(monkeypatch):
    monkeypatch.setattr(bc_mod.typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    assert bc_mod._resolve_client_details(
        is_client=False, flags={}, non_interactive=False) == {}


def test_resolve_non_interactive_uses_flags_only(monkeypatch):
    monkeypatch.setattr(bc_mod.typer, "prompt",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    out = bc_mod._resolve_client_details(
        is_client=True, non_interactive=True,
        flags={"business_name": " Hoyt Engines ", "notes": ""},
    )
    assert out == {"business_name": "Hoyt Engines"}


def test_resolve_interactive_prompts_missing_and_drops_blanks(monkeypatch):
    answers = iter(["Derek", "", "Monterey, CA", "", "", ""])
    asked: list[str] = []

    def fake_prompt(label, **_k):
        asked.append(label.strip())
        return next(answers)

    monkeypatch.setattr(bc_mod.typer, "prompt", fake_prompt)
    out = bc_mod._resolve_client_details(
        is_client=True, non_interactive=False,
        flags={"business_name": "Hoyt Engines"},
    )
    assert "Business name" not in asked          # flag skipped its prompt
    assert len(asked) == 6
    assert out == {"contact_name": "Derek", "business_name": "Hoyt Engines",
                   "service_area": "Monterey, CA"}


# ---------- _apply_client_table ----------


def test_apply_client_table_upserts_and_preserves_rest(tmp_path):
    original = (
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n'
        '# operator comment\n[content]\nicp = "x"\n'
    )
    (tmp_path / "lamill.toml").write_text(original)
    bc_mod._apply_client_table(
        tmp_path, {"contact_name": "Derek", "business_name": "Hoyt Engines",
                   "deadline": "end of November"},
    )
    text = (tmp_path / "lamill.toml").read_text()
    doc = tomllib.loads(text)
    assert doc["client"] == {"business_name": "Hoyt Engines",
                             "deadline": "end of November"}
    assert "contact_name" not in doc["client"]   # contact goes to csv
    assert "# operator comment" in text
    assert doc["content"] == {"icp": "x"}


def test_apply_client_table_no_toml_fields_writes_nothing(tmp_path):
    (tmp_path / "lamill.toml").write_text('[deploy]\nplatform = "cf-pages"\n')
    before = (tmp_path / "lamill.toml").read_text()
    bc_mod._apply_client_table(tmp_path, {"contact_email": "d@a.com"})
    assert (tmp_path / "lamill.toml").read_text() == before


# ---------- CLI integration ----------


def test_cli_bootstrap_client_details_flags(monkeypatch, tmp_path):
    pj = tmp_path / "portfolio.json"
    pj.write_text('{"schema_version": 2, "domains": []}')
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    clients_csv = domains_dir / "clients.csv"
    monkeypatch.setattr(bs_mod, "PORTFOLIO_JSON", pj)
    monkeypatch.setattr(bs_mod, "DOMAINS_DIR", domains_dir)
    monkeypatch.setattr(data_mod, "PORTFOLIO_JSON", pj)
    monkeypatch.setattr(data_mod, "CLIENTS_CSV", clients_csv)
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(bs_mod, "SITES_ROOT", sites_root)

    result = CliRunner().invoke(app, [
        "new", "bootstrap", "clientsite.com", "--owner", "Derek Hoyt",
        "--client-contact-email", "d@clientsite.com",
        "--client-business-name", "Hoyt Engines",
        "--non-interactive",
    ])
    assert result.exit_code == 0, result.stdout
    row = next(csv.DictReader(clients_csv.open()))
    assert row["contact_email"] == "d@clientsite.com"
    doc = tomllib.loads((sites_root / "clientsite.com" / "lamill.toml").read_text())
    assert doc["client"] == {"business_name": "Hoyt Engines"}
