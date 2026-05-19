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


def test_dispatch_hostgator_missing_account_exits_2(tmp_path, monkeypatch):
    """lamill.toml without [deploy].account is a misconfig — refuse
    rather than guessing."""
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    _write_lamill_toml(project, platform="hostgator")  # no account
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "iotnews.today"])
    assert r.exit_code == 2
    assert "account is empty" in r.output


def test_dispatch_hostgator_missing_token_exits_2(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    # Build a fuller lamill.toml with the account field set.
    (project / "lamill.toml").write_text('''schema = "lamill-toml-v1"

[deploy]
platform = "hostgator"
account = "gator4216"
production_branch = "main"

[hosting]
public_html_path = "/home4/foundervijo/public_html/iotnews.today"
''')
    import portfolio.apikeys as apikeys_mod
    monkeypatch.setattr(apikeys_mod, "get_key", lambda k: None)
    monkeypatch.setattr(
        apikeys_mod, "hg_user_for_account", lambda a: "foundervijo"
    )
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "iotnews.today"])
    assert r.exit_code == 2
    assert "HOSTGATOR_TOKEN_GATOR4216" in r.output


def test_dispatch_hostgator_no_snapshot_exits_2(tmp_path, monkeypatch):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    (project / "lamill.toml").write_text('''schema = "lamill-toml-v1"

[deploy]
platform = "hostgator"
account = "gator4216"
production_branch = "main"

[hosting]
public_html_path = "/home4/foundervijo/public_html/iotnews.today"
''')
    import portfolio.apikeys as apikeys_mod
    import portfolio.hosting_cache as cache_mod
    monkeypatch.setattr(
        apikeys_mod, "get_key", lambda k: "tok" if "TOKEN" in k else None
    )
    monkeypatch.setattr(
        apikeys_mod, "hg_user_for_account", lambda a: "foundervijo"
    )
    monkeypatch.setattr(cache_mod, "latest_snapshot", lambda: None)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "iotnews.today"])
    assert r.exit_code == 2
    assert "No hosting snapshot" in r.output


def test_dispatch_hostgator_dry_run_calls_deploy_hg_files(
    tmp_path, monkeypatch
):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    (project / "lamill.toml").write_text('''schema = "lamill-toml-v1"

[deploy]
platform = "hostgator"
account = "gator4216"
production_branch = "main"

[hosting]
public_html_path = "/home4/foundervijo/public_html/iotnews.today"
''')
    import portfolio.apikeys as apikeys_mod
    import portfolio.hosting as hosting_mod
    import portfolio.hosting_cache as cache_mod

    monkeypatch.setattr(
        apikeys_mod, "get_key",
        lambda k: "tok" if "TOKEN" in k else None,
    )
    monkeypatch.setattr(
        apikeys_mod, "hg_user_for_account", lambda a: "foundervijo"
    )

    fake_row = hosting_mod.HostingRow(
        domain="iotnews.today",
        provider=hosting_mod.PROVIDER_HOSTGATOR,
        hg_account_id="gator4216",
        install_path="/home4/foundervijo/public_html/iotnews.today",
    )
    fake_result = hosting_mod.HostingResult(rows=[fake_row])

    monkeypatch.setattr(
        cache_mod, "latest_snapshot",
        lambda: tmp_path / "fake-snapshot.json",
    )
    monkeypatch.setattr(cache_mod, "load_snapshot", lambda p: {})
    monkeypatch.setattr(
        cache_mod, "result_from_snapshot", lambda s: fake_result
    )

    seen = {}

    def fake_deploy(row, *, lamill_toml, token, cpanel_user,
                    sites_root=None, dry_run=True, client=None):
        seen["row_domain"] = row.domain
        seen["dry_run"] = dry_run
        seen["token"] = token
        seen["cpanel_user"] = cpanel_user
        return hosting_mod.HgDeployRow(
            domain=row.domain, hg_account_id=row.hg_account_id or "",
            action="would_deploy", file_count=5, total_bytes=12345,
            notes="dry-run plan",
        )

    monkeypatch.setattr(hosting_mod, "deploy_hg_files", fake_deploy)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "iotnews.today"])
    assert r.exit_code == 0
    assert seen["row_domain"] == "iotnews.today"
    assert seen["dry_run"] is True  # default — no --apply
    assert seen["token"] == "tok"
    assert seen["cpanel_user"] == "foundervijo"
    assert "DRY-RUN" in r.output
    assert "5 files" in r.output


def test_dispatch_hostgator_apply_flag_disables_dry_run(
    tmp_path, monkeypatch
):
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "iotnews.today"
    project.mkdir()
    (project / "lamill.toml").write_text('''schema = "lamill-toml-v1"

[deploy]
platform = "hostgator"
account = "gator4216"
production_branch = "main"

[hosting]
public_html_path = "/home4/foundervijo/public_html/iotnews.today"
''')
    import portfolio.apikeys as apikeys_mod
    import portfolio.hosting as hosting_mod
    import portfolio.hosting_cache as cache_mod

    monkeypatch.setattr(
        apikeys_mod, "get_key",
        lambda k: "tok" if "TOKEN" in k else None,
    )
    monkeypatch.setattr(
        apikeys_mod, "hg_user_for_account", lambda a: "foundervijo"
    )

    fake_row = hosting_mod.HostingRow(
        domain="iotnews.today",
        provider=hosting_mod.PROVIDER_HOSTGATOR,
        hg_account_id="gator4216",
    )
    fake_result = hosting_mod.HostingResult(rows=[fake_row])
    monkeypatch.setattr(
        cache_mod, "latest_snapshot",
        lambda: tmp_path / "fake-snapshot.json",
    )
    monkeypatch.setattr(cache_mod, "load_snapshot", lambda p: {})
    monkeypatch.setattr(
        cache_mod, "result_from_snapshot", lambda s: fake_result
    )

    seen = {}

    def fake_deploy(row, *, dry_run=True, **kw):
        seen["dry_run"] = dry_run
        return hosting_mod.HgDeployRow(
            domain=row.domain, hg_account_id=row.hg_account_id or "",
            action="deployed", file_count=5, total_bytes=12345,
            notes="ok",
        )

    monkeypatch.setattr(hosting_mod, "deploy_hg_files", fake_deploy)
    runner = CliRunner()
    r = runner.invoke(
        app, ["new", "deploy", "iotnews.today", "--apply"]
    )
    assert r.exit_code == 0
    assert seen["dry_run"] is False
    assert "Deployed" in r.output


def test_dispatch_hostgator_wp_skip_exits_0(tmp_path, monkeypatch):
    """A WP site reported by deploy_hg_files exits 0 — the skip is
    informational, not an error."""
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "hybridautopart.com"
    project.mkdir()
    (project / "lamill.toml").write_text('''schema = "lamill-toml-v1"

[deploy]
platform = "hostgator"
account = "gator3164"
production_branch = "main"

[hosting]
public_html_path = "/home2/foundervijo/public_html/hybridautopart.com"
''')
    import portfolio.apikeys as apikeys_mod
    import portfolio.hosting as hosting_mod
    import portfolio.hosting_cache as cache_mod

    monkeypatch.setattr(
        apikeys_mod, "get_key",
        lambda k: "tok" if "TOKEN" in k else None,
    )
    monkeypatch.setattr(
        apikeys_mod, "hg_user_for_account", lambda a: "foundervijo"
    )
    fake_row = hosting_mod.HostingRow(
        domain="hybridautopart.com",
        provider=hosting_mod.PROVIDER_HOSTGATOR,
        hg_account_id="gator3164",
        wp_version="6.7.1",
    )
    monkeypatch.setattr(
        cache_mod, "latest_snapshot",
        lambda: tmp_path / "fake-snapshot.json",
    )
    monkeypatch.setattr(cache_mod, "load_snapshot", lambda p: {})
    monkeypatch.setattr(
        cache_mod, "result_from_snapshot",
        lambda s: hosting_mod.HostingResult(rows=[fake_row]),
    )

    def fake_deploy(row, **kw):
        return hosting_mod.HgDeployRow(
            domain=row.domain, hg_account_id=row.hg_account_id or "",
            action="skipped_wp", notes="WordPress 6.7.1 detected",
        )

    monkeypatch.setattr(hosting_mod, "deploy_hg_files", fake_deploy)
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "hybridautopart.com"])
    assert r.exit_code == 0
    assert "Skipped" in r.output
    assert "WP" in r.output


def test_dispatch_custom_routes_into_v11n_path(tmp_path, monkeypatch):
    """`platform=custom` shares the v11.N UAPI path — same code,
    same flags. Just verify routing (account check fires)."""
    sites_root = _patch_data_root(monkeypatch, tmp_path)
    project = sites_root / "self-hosted.example"
    project.mkdir()
    _write_lamill_toml(project, platform="custom")  # no account
    runner = CliRunner()
    r = runner.invoke(app, ["new", "deploy", "self-hosted.example"])
    assert r.exit_code == 2
    assert "account is empty" in r.output


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
