"""Tests for v11.M — `new deploy <domain>` polymorphic dispatcher.

Covers the dispatcher in `cli.py::new_deploy` and the shell-out
helpers `deploy_cf_workers_via_shell` / `deploy_vercel_via_shell`
in `deploy.py`. No real subprocesses or API calls — `runner` injection
in the deploy helpers; subprocess fakes in the CLI tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from portfolio.cli import app
from portfolio.deploy import (
    StepResult,
    deploy_cf_workers_via_shell,
    deploy_vercel_via_shell,
)


# ---------- helpers ----------


@dataclass
class _FakeProc:
    returncode: int


def _write_lamill_toml(project_dir: Path, *, platform: str) -> None:
    body = f'''schema = "lamill-toml-v1"

[deploy]
platform = "{platform}"
production_branch = "main"
'''
    if platform in ("hostgator", "custom"):
        body += '''
[hosting]
public_html_path = "/home/test/public_html/example.com"
'''
    (project_dir / "lamill.toml").write_text(body)


def _patch_data_root(monkeypatch, tmp_path: Path) -> Path:
    """Point portfolio.data.ROOT at a fake repo dir so DATA_ROOT.parent
    becomes our tmp 'sites' root. Returns the sites root."""
    fake_repo = tmp_path / "portfolio"
    fake_repo.mkdir()
    import portfolio.data as data_mod
    monkeypatch.setattr(data_mod, "ROOT", fake_repo)
    return tmp_path


# =====================================================================
# Shell helpers (deploy.py)
# =====================================================================


def test_cf_workers_dry_run_returns_skipped_step(tmp_path):
    r = deploy_cf_workers_via_shell(tmp_path, dry_run=True)
    assert r.skipped is True
    assert r.ok is True
    assert "pnpm run deploy" in r.detail
    assert str(tmp_path) in r.detail


def test_cf_workers_invokes_pnpm_run_deploy(tmp_path):
    runner = MagicMock(return_value=_FakeProc(returncode=0))
    r = deploy_cf_workers_via_shell(tmp_path, dry_run=False, runner=runner)
    assert r.ok is True
    assert r.skipped is False
    runner.assert_called_once()
    args, kwargs = runner.call_args
    assert args[0] == ["pnpm", "run", "deploy"]
    assert kwargs["cwd"] == str(tmp_path)


def test_cf_workers_nonzero_exit_returns_failure(tmp_path):
    runner = MagicMock(return_value=_FakeProc(returncode=2))
    r = deploy_cf_workers_via_shell(tmp_path, dry_run=False, runner=runner)
    assert r.ok is False
    assert "exited with code 2" in r.detail


def test_cf_workers_command_not_found_returns_failure(tmp_path):
    def boom(*a, **kw):
        raise FileNotFoundError("pnpm")
    r = deploy_cf_workers_via_shell(tmp_path, dry_run=False, runner=boom)
    assert r.ok is False
    assert "command not found" in r.detail
    assert "pnpm" in r.detail


def test_vercel_dry_run_returns_skipped_step(tmp_path):
    r = deploy_vercel_via_shell(tmp_path, dry_run=True)
    assert r.skipped is True
    assert r.ok is True
    assert "vercel deploy --prod" in r.detail


def test_vercel_invokes_vercel_deploy_prod(tmp_path):
    runner = MagicMock(return_value=_FakeProc(returncode=0))
    r = deploy_vercel_via_shell(tmp_path, dry_run=False, runner=runner)
    assert r.ok is True
    args, kwargs = runner.call_args
    assert args[0] == ["vercel", "deploy", "--prod"]
    assert kwargs["cwd"] == str(tmp_path)


def test_vercel_nonzero_exit_returns_failure(tmp_path):
    runner = MagicMock(return_value=_FakeProc(returncode=1))
    r = deploy_vercel_via_shell(tmp_path, dry_run=False, runner=runner)
    assert r.ok is False
    assert "exited with code 1" in r.detail


def test_vercel_command_not_found_returns_failure(tmp_path):
    def boom(*a, **kw):
        raise FileNotFoundError("vercel")
    r = deploy_vercel_via_shell(tmp_path, dry_run=False, runner=boom)
    assert r.ok is False
    assert "command not found" in r.detail


# =====================================================================
# CLI dispatcher (cli.py::new_deploy)
# =====================================================================


def test_dispatch_missing_project_dir_exits_1(tmp_path, monkeypatch):
    _patch_data_root(monkeypatch, tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "ghost.com"])
    assert r.exit_code == 1
    assert "Project dir not found" in r.output


def test_dispatch_invalid_lamill_toml_exits_2(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "bad.com"
    project.mkdir()
    (project / "lamill.toml").write_text("not = valid = toml ===")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "bad.com"])
    assert r.exit_code == 2
    assert "lamill.toml invalid" in r.output


def test_dispatch_missing_lamill_toml_defaults_cf_pages(
    tmp_path, monkeypatch
):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "legacy.com"
    project.mkdir()
    # No lamill.toml — should print the "assuming cf-pages" notice
    # then hit the CF Pages flow, which immediately demands
    # CF_API_TOKEN / CF_ACCOUNT_ID. Stub load_env to return empty so
    # we hit the exit-2 path without going further into CF API land.
    import portfolio.suggest as suggest_mod
    monkeypatch.setattr(suggest_mod, "load_env", lambda: {})
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "legacy.com"])
    assert "assuming platform=cf-pages" in r.output
    assert "CF_API_TOKEN" in r.output  # routed into CF Pages path
    assert r.exit_code == 2


def test_dispatch_platform_none_rejects_with_set_deploy_hint(
    tmp_path, monkeypatch
):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "undeclared.com"
    project.mkdir()
    _write_lamill_toml(project, platform="none")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "undeclared.com"])
    assert r.exit_code == 2
    assert "Platform is `none`" in r.output
    assert "set-deploy" in r.output


def test_dispatch_cf_pages_routes_into_v3c_flow(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "kwizicle.com"
    project.mkdir()
    _write_lamill_toml(project, platform="cf-pages")
    # Stub env to fail-fast inside _deploy_cf_pages_v3c; this proves
    # we routed there rather than into a wrong branch.
    import portfolio.suggest as suggest_mod
    monkeypatch.setattr(suggest_mod, "load_env", lambda: {})
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "kwizicle.com"])
    assert r.exit_code == 2
    assert "CF_API_TOKEN" in r.output


def test_dispatch_cf_workers_invokes_shell_helper(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "airsucks.com"
    project.mkdir()
    _write_lamill_toml(project, platform="cf-workers")

    calls = {}

    def fake_shell(project_dir, *, dry_run=False, runner=None):
        calls["project_dir"] = project_dir
        calls["dry_run"] = dry_run
        return StepResult(step="cf-workers-shell", ok=True, detail="ran")

    import portfolio.deploy as deploy_mod
    monkeypatch.setattr(
        deploy_mod, "deploy_cf_workers_via_shell", fake_shell
    )
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "airsucks.com"])
    assert r.exit_code == 0
    assert calls["project_dir"] == project
    assert calls["dry_run"] is False
    assert "platform=cf-workers" in r.output
    assert "Deploy complete" in r.output


def test_dispatch_cf_workers_dry_run_passes_flag(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "voltloop.com"
    project.mkdir()
    _write_lamill_toml(project, platform="cf-workers")

    calls = {}

    def fake_shell(project_dir, *, dry_run=False, runner=None):
        calls["dry_run"] = dry_run
        return StepResult(
            step="cf-workers-shell", ok=True, skipped=True,
            detail="DRY-RUN — would run …",
        )

    import portfolio.deploy as deploy_mod
    monkeypatch.setattr(
        deploy_mod, "deploy_cf_workers_via_shell", fake_shell
    )
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "voltloop.com", "--dry-run"])
    assert r.exit_code == 0
    assert calls["dry_run"] is True
    assert "DRY-RUN" in r.output


def test_dispatch_cf_workers_shell_failure_exits_6(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "kwizicle.com"
    project.mkdir()
    _write_lamill_toml(project, platform="cf-workers")

    def fake_shell(project_dir, *, dry_run=False, runner=None):
        return StepResult(
            step="cf-workers-shell", ok=False,
            detail="`pnpm run deploy` exited with code 1",
        )

    import portfolio.deploy as deploy_mod
    monkeypatch.setattr(
        deploy_mod, "deploy_cf_workers_via_shell", fake_shell
    )
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "kwizicle.com"])
    assert r.exit_code == 6


def test_dispatch_vercel_invokes_shell_helper(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "civictools.com"
    project.mkdir()
    _write_lamill_toml(project, platform="vercel")

    calls = {}

    def fake_shell(project_dir, *, dry_run=False, runner=None):
        calls["project_dir"] = project_dir
        return StepResult(step="vercel-shell", ok=True, detail="ran")

    import portfolio.deploy as deploy_mod
    monkeypatch.setattr(deploy_mod, "deploy_vercel_via_shell", fake_shell)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "civictools.com"])
    assert r.exit_code == 0
    assert calls["project_dir"] == project
    assert "platform=vercel" in r.output


def test_dispatch_vercel_shell_failure_exits_6(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "civictools.com"
    project.mkdir()
    _write_lamill_toml(project, platform="vercel")

    def fake_shell(project_dir, *, dry_run=False, runner=None):
        return StepResult(
            step="vercel-shell", ok=False,
            detail="`vercel deploy --prod` exited with code 1",
        )

    import portfolio.deploy as deploy_mod
    monkeypatch.setattr(deploy_mod, "deploy_vercel_via_shell", fake_shell)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "civictools.com"])
    assert r.exit_code == 6


def test_dispatch_hostgator_shows_v11n_placeholder(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    _write_lamill_toml(project, platform="hostgator")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "iotnews.today"])
    assert r.exit_code == 2
    assert "v11.N" in r.output
    assert "hostgator" in r.output.lower() or "'hostgator'" in r.output


def test_dispatch_custom_shows_v11n_placeholder(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "self-hosted.example"
    project.mkdir()
    _write_lamill_toml(project, platform="custom")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "self-hosted.example"])
    assert r.exit_code == 2
    assert "v11.N" in r.output


def test_dispatch_netlify_shows_not_implemented(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "neverdeployed.com"
    project.mkdir()
    _write_lamill_toml(project, platform="netlify")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "neverdeployed.com"])
    assert r.exit_code == 2
    assert "netlify" in r.output
    assert "doesn't implement it yet" in r.output


def test_dispatch_github_pages_shows_not_implemented(
    tmp_path, monkeypatch
):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "ghpages.example"
    project.mkdir()
    _write_lamill_toml(project, platform="github-pages")
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "ghpages.example"])
    assert r.exit_code == 2
    assert "github-pages" in r.output
