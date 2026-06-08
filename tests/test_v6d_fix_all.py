"""Tests for v6.D — `portfolio project fix --all` fleetwide fix.

Eligibility filter: skip ignore_repos + skip projects whose domain is
in 'To be deleted immediately' category. Confirm prompt before
fleetwide writes (unless --yes). Continue-on-error.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from portfolio.cli import app


def _patch_repos_dir_and_domains(monkeypatch, repos_dir, domain_categories):
    """Stub config + portfolio.json to control fleet contents.
    `domain_categories` is a {domain: category} map; domains in
    'To be deleted immediately' get filtered out."""
    from portfolio.checks.config import CheckConfig
    cfg = CheckConfig(repos_dir=repos_dir, github_token="",
                      skip_checks=[], ignore_repos=[])
    # `_list_fleet_eligible_projects` imports `load_config` from
    # `portfolio.checks.config` inside the function — patch the
    # module-level binding it'll resolve.
    import portfolio.checks.config as config_module
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)

    # Stub load_domains to return Domain objects with the right categories.
    from portfolio.data import Domain
    from datetime import date
    domains = [
        Domain(name=name, registrar="Test", tld="com",
               expires=date(2030, 1, 1), auto_renew="On",
               status="Active", category=cat)
        for name, cat in domain_categories.items()
    ]
    import portfolio.fix_cli as fix_cli_mod  # v35.F incr 11: fix engine moved here
    monkeypatch.setattr(fix_cli_mod, "load_domains", lambda: domains)


def _make_repos(tmp_path, names):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    for n in names:
        (repos_dir / n).mkdir()
    return repos_dir


# ---------- eligibility filter ----------


def test_fleet_skips_deletion_marked_domains(tmp_path, monkeypatch):
    repos_dir = _make_repos(tmp_path, ["alpha.com", "junk.com", "beta.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir, {
        "alpha.com": "My brand",
        "junk.com": "To be deleted immediately",
        "beta.com": "Next session",
    })
    from portfolio.cli import _list_fleet_eligible_projects
    eligible = _list_fleet_eligible_projects()
    names = sorted(d for d, _ in eligible)
    assert names == ["alpha.com", "beta.com"]
    assert "junk.com" not in names


def test_fleet_includes_unresolved_dirs(tmp_path, monkeypatch):
    """Dirs that don't resolve to a portfolio.json domain (e.g. harmonia
    with no exact-name entry) are STILL eligible — fleetwide fix
    doesn't depend on the resolver."""
    repos_dir = _make_repos(tmp_path, ["harmonia", "kwizicle.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir, {
        "kwizicle.com": "My brand",
        # harmonia not in domain map at all
    })
    from portfolio.cli import _list_fleet_eligible_projects
    eligible = _list_fleet_eligible_projects()
    names = sorted(d for d, _ in eligible)
    assert "harmonia" in names
    assert "kwizicle.com" in names


def test_fleet_honors_ignore_repos(tmp_path, monkeypatch):
    from portfolio.checks.config import CheckConfig
    repos_dir = _make_repos(tmp_path, ["alpha.com", "beta.com", "skip.com"])
    cfg = CheckConfig(repos_dir=repos_dir, github_token="",
                      skip_checks=[], ignore_repos=["skip.com"],
                      dark_sites=[])
    import portfolio.checks.config as config_module
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    import portfolio.fix_cli as fix_cli_mod  # v35.F incr 11: fix engine moved here
    monkeypatch.setattr(fix_cli_mod, "load_domains", lambda: [])

    from portfolio.cli import _list_fleet_eligible_projects
    names = sorted(d for d, _ in _list_fleet_eligible_projects())
    assert names == ["alpha.com", "beta.com"]


def test_fleet_skips_dark_sites(tmp_path, monkeypatch):
    """2026-05-27 — `fleet fix` must skip dark_sites so internal projects
    don't receive auto-applied writes like always_use_https toggles.
    csinorcal.church incident (2026-05-27 PM) is the motivating case."""
    from portfolio.checks.config import CheckConfig
    repos_dir = _make_repos(tmp_path, [
        "csinorcal.church", "alpha.com", "intranet.example"
    ])
    cfg = CheckConfig(
        repos_dir=repos_dir, github_token="",
        skip_checks=[], ignore_repos=[],
        dark_sites=["csinorcal.church", "intranet.example"],
    )
    import portfolio.checks.config as config_module
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    import portfolio.fix_cli as fix_cli_mod  # v35.F incr 11: fix engine moved here
    monkeypatch.setattr(fix_cli_mod, "load_domains", lambda: [])

    from portfolio.cli import _list_fleet_eligible_projects
    names = sorted(d for d, _ in _list_fleet_eligible_projects())
    assert names == ["alpha.com"]
    assert "csinorcal.church" not in names
    assert "intranet.example" not in names


def test_fleet_dark_sites_match_is_case_insensitive(tmp_path, monkeypatch):
    """Config file may have dark_sites listed in any case; eligibility
    comparison must lowercase both sides (mirrors load_config behavior)."""
    from portfolio.checks.config import CheckConfig
    repos_dir = _make_repos(tmp_path, ["Internal.SITE", "alpha.com"])
    cfg = CheckConfig(
        repos_dir=repos_dir, github_token="",
        skip_checks=[], ignore_repos=[],
        dark_sites=["internal.site"],  # already lowercased by load_config
    )
    import portfolio.checks.config as config_module
    monkeypatch.setattr(config_module, "load_config", lambda path=None: cfg)
    import portfolio.fix_cli as fix_cli_mod  # v35.F incr 11: fix engine moved here
    monkeypatch.setattr(fix_cli_mod, "load_domains", lambda: [])

    from portfolio.cli import _list_fleet_eligible_projects
    names = sorted(d for d, _ in _list_fleet_eligible_projects())
    assert names == ["alpha.com"]


# ---------- CLI integration ----------


def test_fix_all_dry_run_renders_plan(tmp_path, monkeypatch):
    """Default --all (no --apply) prints plan, writes nothing."""
    repos_dir = _make_repos(tmp_path, ["alpha.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir,
                                  {"alpha.com": "My brand"})
    runner = CliRunner()
    result = runner.invoke(app, ["project", "fix", "--all"])
    assert result.exit_code == 0
    assert "Fleetwide fix plan" in result.stdout
    assert "alpha.com" in result.stdout
    assert "Re-run with --apply" in result.stdout


def test_fix_all_with_name_argument_errors(tmp_path, monkeypatch):
    """`fix <name> --all` is a usage error (mutually exclusive)."""
    repos_dir = _make_repos(tmp_path, ["alpha.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir,
                                  {"alpha.com": "My brand"})
    runner = CliRunner()
    result = runner.invoke(app, ["project", "fix", "alpha.com", "--all"])
    assert result.exit_code == 2
    assert "either" in result.stdout.lower() or "both" in result.stdout.lower()


def test_fix_no_name_no_all_errors():
    """`project fix` with no name and no --all is a usage error."""
    runner = CliRunner()
    result = runner.invoke(app, ["project", "fix"])
    assert result.exit_code == 2
    assert "needs" in result.stdout.lower() or "<name>" in result.stdout


def test_fix_all_empty_fleet(tmp_path, monkeypatch):
    """No eligible projects → friendly message + exit 0."""
    repos_dir = tmp_path / "empty-repos"
    repos_dir.mkdir()
    _patch_repos_dir_and_domains(monkeypatch, repos_dir, {})
    runner = CliRunner()
    result = runner.invoke(app, ["project", "fix", "--all"])
    assert result.exit_code == 0
    assert "No fleetwide-eligible projects" in result.stdout


def test_fix_all_filters_deletion_marked_in_output(tmp_path, monkeypatch):
    """Project marked 'To be deleted immediately' must NOT appear in
    the fleetwide plan output."""
    repos_dir = _make_repos(tmp_path, ["alpha.com", "junk.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir, {
        "alpha.com": "My brand",
        "junk.com": "To be deleted immediately",
    })
    runner = CliRunner()
    result = runner.invoke(app, ["project", "fix", "--all"])
    assert result.exit_code == 0
    # alpha appears in plan; junk does not.
    assert "alpha.com" in result.stdout
    # junk.com filtered out before plan render
    plan_section = result.stdout.split("Re-run with --apply")[0]
    assert "junk.com" not in plan_section


def test_fix_all_apply_with_yes_no_confirm_prompt(tmp_path, monkeypatch):
    """`--apply --yes` skips the fleetwide confirm prompt."""
    repos_dir = _make_repos(tmp_path, ["alpha.com"])
    _patch_repos_dir_and_domains(monkeypatch, repos_dir,
                                  {"alpha.com": "My brand"})
    runner = CliRunner()
    # Pass --yes so we don't need to handle the prompt.
    result = runner.invoke(
        app, ["project", "fix", "--all", "--apply", "--yes",
              "--rule", "CHECK_001"],
    )
    # Either applied or there were no fixes — both acceptable. Just
    # confirm no prompt error.
    assert result.exit_code in (0, 3)
