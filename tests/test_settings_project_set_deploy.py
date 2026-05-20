"""Tests for v10.B slice 1 — `settings deploy set` CLI (renamed in v14.B; was `settings project set-deploy`).

Covers: resolution (known/unknown/ambiguous domain), platform
validation, non-interactive happy path, hostgator/custom hosting-
required enforcement, existing-file preservation across update,
flag overrides for each [deploy] field, custom_domains list, and
the auto_deploy tri-state.
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
    load,
    write,
)


@pytest.fixture
def fake_fleet(monkeypatch, tmp_path: Path):
    """Wire a fake sites/ workspace + portfolio.json into the
    runtime so set-deploy can resolve names and write to real
    files under tmp_path.

    Returns (sites_root, plan_dict). The plan dict maps domain →
    category. Each domain gets an empty sites/<domain>/ dir
    pre-created (set-deploy expects the repo dir to exist).
    """
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    plan = {
        "airsucks.com": "Active",
        "hybridautopart.com": "Active",
        "calcengine.site": "Active",
    }
    for d in plan:
        (sites_root / d).mkdir()

    monkeypatch.setattr(project, "SITES_ROOT", sites_root)
    monkeypatch.setattr(project_deploy, "SITES_ROOT", sites_root)
    monkeypatch.setattr(data, "load_plan", lambda: dict(plan))

    return sites_root, plan


def _read_lamill(sites_root: Path, domain: str) -> LamillToml | None:
    return load(sites_root / domain)


# ---------- platform + resolution validation ----------


def test_set_deploy_rejects_invalid_platform(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "fly-io",
         "--non-interactive"],
    )
    assert result.exit_code == 2, result.stdout
    assert "Invalid platform" in result.stdout
    assert not (sites_root / "airsucks.com" / "lamill.toml").exists()


def test_set_deploy_rejects_unknown_domain(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "doesnotexist.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 1, result.stdout
    assert "not found" in result.stdout


def test_set_deploy_rejects_when_sibling_repo_missing(monkeypatch, tmp_path):
    # Plan has the domain, but no sites/<domain>/ dir exists.
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    monkeypatch.setattr(project, "SITES_ROOT", sites_root)
    monkeypatch.setattr(project_deploy, "SITES_ROOT", sites_root)
    monkeypatch.setattr(data, "load_plan", lambda: {"airsucks.com": "Active"})

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 1, result.stdout
    assert "Sibling repo missing" in result.stdout


# ---------- non-interactive happy path ----------


def test_set_deploy_writes_minimal_lamill_toml(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded is not None
    assert loaded.deploy.platform == "cf-pages"
    assert loaded.deploy.account is None
    assert loaded.deploy.production_branch == "main"
    assert loaded.deploy.auto_deploy is None
    assert loaded.deploy.effective_auto_deploy() is True  # cf-pages default
    assert loaded.deploy.custom_domains == []
    assert loaded.hosting is None
    assert loaded.backend is None
    assert loaded.notes is None


def test_set_deploy_account_flag_persists(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "vercel",
         "--account", "team-prod",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded.deploy.account == "team-prod"


def test_set_deploy_branch_flag_overrides_default(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--branch", "release",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded.deploy.production_branch == "release"


def test_set_deploy_auto_deploy_flag_explicit_false(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--no-auto-deploy",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded.deploy.auto_deploy is False
    assert loaded.deploy.effective_auto_deploy() is False


def test_set_deploy_custom_domains_multiple_flags(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "vercel",
         "--domain", "airsucks.com",
         "--domain", "www.airsucks.com",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded.deploy.custom_domains == ["airsucks.com", "www.airsucks.com"]


# ---------- hostgator / custom hosting-required ----------


def test_set_deploy_hostgator_non_interactive_without_hosting_fails(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "hybridautopart.com", "hostgator",
         "--non-interactive"],
    )
    assert result.exit_code == 2, result.stdout
    assert "requires a [hosting] section" in result.stdout
    # No file written.
    assert not (sites_root / "hybridautopart.com" / "lamill.toml").exists()


def test_set_deploy_hostgator_with_public_html_flag_succeeds(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "hybridautopart.com", "hostgator",
         "--public-html-path", "/home/vikt/public_html/hap/",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "hybridautopart.com")
    assert loaded.deploy.platform == "hostgator"
    assert loaded.hosting is not None
    assert loaded.hosting.public_html_path == "/home/vikt/public_html/hap/"
    assert loaded.hosting.cpanel_user is None


def test_set_deploy_custom_platform_requires_hosting_same_as_hostgator(fake_fleet):
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "custom",
         "--non-interactive"],
    )
    assert result.exit_code == 2, result.stdout
    assert "platform='custom'" in result.stdout
    assert "requires a [hosting] section" in result.stdout


def test_set_deploy_hostgator_full_hosting_flags(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "hybridautopart.com", "hostgator",
         "--cpanel-user", "vikt",
         "--cpanel-url", "https://gator4045.hostgator.com:2083",
         "--ftp-host", "ftp.hybridautopart.com",
         "--ftp-user", "vikt@hybridautopart.com",
         "--ftp-port", "21",
         "--public-html-path", "/home/vikt/public_html/hap/",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "hybridautopart.com")
    h = loaded.hosting
    assert h.cpanel_user == "vikt"
    assert h.cpanel_url == "https://gator4045.hostgator.com:2083"
    assert h.ftp_host == "ftp.hybridautopart.com"
    assert h.ftp_user == "vikt@hybridautopart.com"
    assert h.ftp_port == 21
    assert h.public_html_path == "/home/vikt/public_html/hap/"


# ---------- update path: existing file preserved ----------


def test_set_deploy_preserves_existing_backend_and_notes(fake_fleet):
    sites_root, _ = fake_fleet
    # Seed an existing lamill.toml with [backend] and [notes].
    initial = LamillToml(
        deploy=DeployBlock(platform="cf-pages"),
        backend=BackendBlock(db="sqlite", framework="fastapi", hosting="fly.io"),
        notes="initial bootstrap notes",
    )
    write(sites_root / "calcengine.site", initial)

    runner = CliRunner()
    # Operator changes platform but doesn't touch backend/notes.
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "calcengine.site", "vercel",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "calcengine.site")
    assert loaded.deploy.platform == "vercel"
    assert loaded.backend == BackendBlock(
        db="sqlite", framework="fastapi", hosting="fly.io"
    )
    assert loaded.notes == "initial bootstrap notes"


def test_set_deploy_preserves_existing_hosting_when_switching_to_non_hosting_platform(
    fake_fleet,
):
    # If the operator changes platform from hostgator → cf-pages,
    # the existing [hosting] block is preserved (it carries breadcrumbs
    # that might still matter; operator can remove manually).
    sites_root, _ = fake_fleet
    initial = LamillToml(
        deploy=DeployBlock(platform="hostgator"),
        hosting=HostingBlock(
            cpanel_user="vikt",
            public_html_path="/var/www/x/",
        ),
    )
    write(sites_root / "hybridautopart.com", initial)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "hybridautopart.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "hybridautopart.com")
    assert loaded.deploy.platform == "cf-pages"
    assert loaded.hosting is not None
    assert loaded.hosting.cpanel_user == "vikt"


def test_set_deploy_update_overwrites_account(fake_fleet):
    sites_root, _ = fake_fleet
    initial = LamillToml(
        deploy=DeployBlock(platform="vercel", account="team-old"),
    )
    write(sites_root / "airsucks.com", initial)

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "vercel",
         "--account", "team-new",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    loaded = _read_lamill(sites_root, "airsucks.com")
    assert loaded.deploy.account == "team-new"


# ---------- malformed existing file ----------


def test_set_deploy_rejects_when_existing_lamill_toml_malformed(fake_fleet):
    sites_root, _ = fake_fleet
    # Write a malformed lamill.toml
    (sites_root / "airsucks.com" / "lamill.toml").write_text(
        "this is not [valid"
    )

    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 1, result.stdout
    assert "malformed" in result.stdout


# ---------- atomic write ----------


def test_set_deploy_leaves_no_temp_files(fake_fleet):
    sites_root, _ = fake_fleet
    runner = CliRunner()
    result = runner.invoke(
        app,
        ["settings", "deploy", "set", "airsucks.com", "cf-pages",
         "--non-interactive"],
    )
    assert result.exit_code == 0, result.stdout
    # Only the lamill.toml file should remain — no .tmp leftovers.
    entries = sorted(p.name for p in (sites_root / "airsucks.com").iterdir())
    assert entries == ["lamill.toml"]
