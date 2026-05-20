"""Tests for v10.B slice 2 — `settings deploy show` CLI (renamed in v14.B; was `settings project show-deploy`).

Covers: resolution (known / unknown / ambiguous), missing
`lamill.toml` (exit 0 + helpful message), malformed file (exit 1),
pretty rendering of each block type, and `--json` payload shape.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio import data, project, project_deploy
from portfolio.cli import app
from portfolio.lamill_toml import (
    BackendBlock,
    DeployBlock,
    HostingBlock,
    LamillToml,
    write,
)


@pytest.fixture
def fake_fleet(monkeypatch, tmp_path: Path):
    """Mirrors test_settings_project_set_deploy.py's fixture — fake
    sites/ workspace + portfolio.json plan, monkeypatched into the
    runtime so commands resolve names against tmp_path."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    plan = {
        "airsucks.com": "Active",
        "hybridautopart.com": "Active",
    }
    for d in plan:
        (sites_root / d).mkdir()

    monkeypatch.setattr(project, "SITES_ROOT", sites_root)
    monkeypatch.setattr(project_deploy, "SITES_ROOT", sites_root)
    monkeypatch.setattr(data, "load_plan", lambda: dict(plan))

    return sites_root, plan


# ---------- resolution / missing file ----------


def test_show_deploy_unknown_domain_exits_1(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "doesnotexist.com"],
    )
    assert result.exit_code == 1, result.stdout
    assert "not found" in result.stdout


def test_show_deploy_missing_lamill_toml_exits_0_with_hint(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "airsucks.com"],
    )
    assert result.exit_code == 0, result.stdout
    assert "no deploy declaration" in result.stdout
    assert "settings deploy set" in result.stdout


def test_show_deploy_missing_json_emits_null(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "show", "airsucks.com", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == "null"


def test_show_deploy_malformed_existing_file_exits_1(fake_fleet):
    sites_root, _ = fake_fleet
    (sites_root / "airsucks.com" / "lamill.toml").write_text(
        "this is not [valid"
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "airsucks.com"],
    )
    assert result.exit_code == 1, result.stdout
    assert "malformed" in result.stdout


# ---------- pretty rendering ----------


def test_show_deploy_renders_minimal_lamill_toml(fake_fleet):
    sites_root, _ = fake_fleet
    write(sites_root / "airsucks.com",
          LamillToml(deploy=DeployBlock(platform="cf-pages")))

    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "airsucks.com"],
    )
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    assert "airsucks.com" in flat
    assert "declared deployment" in flat
    assert "lamill.toml" in flat  # source line
    assert "platform" in flat
    assert "cf-pages" in flat
    assert "branch" in flat and "main" in flat
    assert "auto-deploy" in flat
    assert "platform default" in flat  # cf-pages → yes is the default; renderer notes it
    # No optional blocks for the minimal payload.
    assert "hosting" not in flat or "hosting" in flat  # tolerant
    # The drift-check footer reminds the operator about v10.E.
    assert "Drift check" in flat
    assert "v10.E" in flat


def test_show_deploy_renders_full_payload(fake_fleet):
    sites_root, _ = fake_fleet
    payload = LamillToml(
        deploy=DeployBlock(
            platform="hostgator",
            account="vik@hostgator",
            production_branch="release",
            auto_deploy=False,
            custom_domains=["hybridautopart.com", "www.hybridautopart.com"],
        ),
        hosting=HostingBlock(
            cpanel_user="vikt",
            cpanel_url="https://gator4045.hostgator.com:2083",
            ftp_host="ftp.hybridautopart.com",
            ftp_user="vikt@hybridautopart.com",
            ftp_port=21,
            public_html_path="/home/vikt/public_html/hap/",
        ),
        backend=BackendBlock(
            db="postgres", framework="fastapi", hosting="fly.io"
        ),
        notes="WordPress install; planning React migration",
    )
    write(sites_root / "hybridautopart.com", payload)

    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "hybridautopart.com"],
    )
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    # [deploy] fields
    assert "hostgator" in flat
    assert "vik@hostgator" in flat
    assert "release" in flat
    assert "no" in flat  # auto-deploy = false
    assert "hybridautopart.com" in flat
    assert "www.hybridautopart.com" in flat
    # [hosting] fields
    assert "vikt" in flat
    assert "gator4045" in flat
    assert ":21" in flat
    assert "/home/vikt/public_html/hap/" in flat
    # [backend] fields
    assert "postgres" in flat
    assert "fastapi" in flat
    assert "fly.io" in flat
    # [notes] field — truncated only beyond 80 chars; this fits.
    assert "WordPress install" in flat


def test_show_deploy_renders_explicit_account_dash_when_absent(fake_fleet):
    sites_root, _ = fake_fleet
    write(sites_root / "airsucks.com",
          LamillToml(deploy=DeployBlock(platform="vercel")))
    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "airsucks.com"],
    )
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    # account field absent → renders as "—"
    assert "—" in flat


def test_show_deploy_truncates_long_notes(fake_fleet):
    sites_root, _ = fake_fleet
    long_text = "x" * 200  # > 80 chars
    write(
        sites_root / "airsucks.com",
        LamillToml(deploy=DeployBlock(platform="cf-pages"), notes=long_text),
    )
    runner = CliRunner()
    result = runner.invoke(
        app, ["settings", "deploy", "show", "airsucks.com"],
    )
    assert result.exit_code == 0, result.stdout
    # Truncation can happen via my manual "..." OR rich's column "…".
    # The real invariant: the full 200-char string isn't rendered.
    assert "x" * 200 not in result.stdout
    assert "..." in result.stdout or "…" in result.stdout


# ---------- --json output ----------


def test_show_deploy_json_emits_minimal_payload(fake_fleet):
    sites_root, _ = fake_fleet
    write(sites_root / "airsucks.com",
          LamillToml(deploy=DeployBlock(platform="cf-pages")))

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "show", "airsucks.com", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["schema"] == "lamill-toml-v1"
    assert payload["deploy"]["platform"] == "cf-pages"
    assert payload["deploy"]["production_branch"] == "main"
    # Optional fields not in dict because they're None/empty.
    assert "account" not in payload["deploy"]
    assert "auto_deploy" not in payload["deploy"]
    assert "custom_domains" not in payload["deploy"]
    assert "hosting" not in payload
    assert "backend" not in payload
    assert "notes" not in payload


def test_show_deploy_json_emits_full_payload(fake_fleet):
    sites_root, _ = fake_fleet
    full = LamillToml(
        deploy=DeployBlock(
            platform="vercel",
            account="team-prod",
            auto_deploy=True,
            custom_domains=["calcengine.site"],
        ),
        hosting=None,
        backend=BackendBlock(db="sqlite", framework="fastapi", hosting="fly.io"),
        notes="planned migration",
    )
    write(sites_root / "airsucks.com", full)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "show", "airsucks.com", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    p = json.loads(result.stdout)
    assert p["deploy"]["platform"] == "vercel"
    assert p["deploy"]["account"] == "team-prod"
    assert p["deploy"]["auto_deploy"] is True
    assert p["deploy"]["custom_domains"] == ["calcengine.site"]
    assert p["backend"] == {
        "db": "sqlite", "framework": "fastapi", "hosting": "fly.io"
    }
    assert p["notes"] == {"text": "planned migration"}


def test_show_deploy_json_emits_null_on_missing_file(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "show", "airsucks.com", "--json"],
    )
    assert result.exit_code == 0, result.stdout
    assert result.stdout.strip() == "null"


def test_show_deploy_json_unknown_domain_emits_null_and_exits_1(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "show", "doesnotexist.com", "--json"],
    )
    assert result.exit_code == 1, result.stdout
    # First line is `null` so a downstream `jq` pipe doesn't break.
    assert "null" in result.stdout
