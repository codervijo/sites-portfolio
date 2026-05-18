"""Tests for v10.C slice 2 — `fleet repos --add-deploy-declarations`.

Covers the classifier (`migrate_deploy_declarations`) and the CLI
shell. Each test wires a fake sites/ fleet under tmp_path and a
monkeypatched portfolio.json plan so the migration walks tmp_path,
not the operator's real fleet.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio import data, fleet_repos
from portfolio.cli import app
from portfolio.lamill_toml import (
    DeployBlock,
    LamillToml,
    load,
    write,
)
from portfolio.project_deploy import migrate_deploy_declarations


@pytest.fixture
def fake_fleet(monkeypatch, tmp_path: Path):
    """Mirrors test_settings_project_set_deploy.py's fixture but
    wires fleet_repos.SITES_ROOT (the migration's walker reads from
    there)."""
    sites_root = tmp_path / "sites"
    sites_root.mkdir()
    plan = {
        "airsucks.com": "Active",
        "calcengine.site": "Active",
        "hybridautopart.com": "Active",
        "kwizicle.com": "Active",
        "swiftly.co.in": "archived",  # exercise archived-via-category
    }
    for d in plan:
        (sites_root / d).mkdir()

    monkeypatch.setattr(fleet_repos, "SITES_ROOT", sites_root)
    monkeypatch.setattr(data, "load_plan", lambda: dict(plan))

    return sites_root, plan


def _write_wrangler_jsonc_pages(repo: Path) -> None:
    (repo / "wrangler.jsonc").write_text(
        '{"name":"x","pages_build_output_dir":"./dist"}\n'
    )


def _write_wrangler_jsonc_workers(repo: Path) -> None:
    (repo / "wrangler.jsonc").write_text(
        '{"name":"x","main":"src/worker.ts"}\n'
    )


def _write_vercel_json(repo: Path) -> None:
    (repo / "vercel.json").write_text('{"version": 2}\n')


def _write_netlify_toml(repo: Path) -> None:
    (repo / "netlify.toml").write_text('[build]\npublish = "dist"\n')


# ---------- classifier — dry-run ----------


def test_migration_classifies_no_signals_as_manual(fake_fleet):
    sites_root, _ = fake_fleet
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    # airsucks.com (no config files) → manual
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.classification == "manual"
    assert row.action == "skipped_manual"
    assert row.chosen_platform is None


def test_migration_classifies_single_signal_as_unambiguous(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.classification == "unambiguous"
    assert row.action == "would_write"
    assert row.chosen_platform == "cf-pages"


def test_migration_classifies_vercel_unambiguous(fake_fleet):
    sites_root, _ = fake_fleet
    _write_vercel_json(sites_root / "calcengine.site")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "calcengine.site")
    assert row.chosen_platform == "vercel"


def test_migration_classifies_netlify_unambiguous(fake_fleet):
    sites_root, _ = fake_fleet
    _write_netlify_toml(sites_root / "calcengine.site")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "calcengine.site")
    assert row.chosen_platform == "netlify"


def test_migration_classifies_workers_unambiguous(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_workers(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.chosen_platform == "cf-workers"


def test_migration_classifies_multiple_signals_as_ambiguous(fake_fleet):
    """The drift case — `wrangler.jsonc + vercel.json` co-exist
    (lamill.io's pre-migration shape)."""
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    _write_vercel_json(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.classification == "ambiguous"
    assert row.action == "skipped_ambiguous"
    assert row.chosen_platform is None  # not resolved without --include-ambiguous


def test_migration_skips_already_declared(fake_fleet):
    sites_root, _ = fake_fleet
    write(
        sites_root / "calcengine.site",
        LamillToml(deploy=DeployBlock(platform="vercel")),
    )
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "calcengine.site")
    assert row.classification == "already_declared"
    assert row.action == "skipped_already"


def test_migration_skips_archived_via_tombstone(fake_fleet):
    sites_root, _ = fake_fleet
    # Pre-write a wrangler.jsonc so the migration would otherwise
    # classify as unambiguous; tombstone overrides.
    repo = sites_root / "kwizicle.com"
    _write_wrangler_jsonc_pages(repo)
    (repo / "TOMBSTONE.md").write_text("retired 2026-04-01\n")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "kwizicle.com")
    assert row.classification == "archived"
    assert row.action == "skipped_archived"


def test_migration_skips_archived_via_portfolio_category(fake_fleet):
    sites_root, _ = fake_fleet
    # swiftly.co.in has category="archived" in the fake plan, AND a
    # platform-config file — category-based archived check wins.
    _write_vercel_json(sites_root / "swiftly.co.in")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "swiftly.co.in")
    assert row.classification == "archived"


# ---------- apply path — writes ----------


def test_migration_writes_lamill_toml_on_apply(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(
        dry_run=False, sites_root=sites_root,
    )
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.action == "wrote"

    loaded = load(sites_root / "airsucks.com")
    assert loaded is not None
    assert loaded.deploy.platform == "cf-pages"
    # custom_domains populated from the directory name.
    assert loaded.deploy.custom_domains == ["airsucks.com"]


def test_migration_apply_skips_ambiguous_without_include_flag(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    _write_vercel_json(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(
        dry_run=False, sites_root=sites_root,
    )
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.action == "skipped_ambiguous"
    # No file written.
    assert not (sites_root / "airsucks.com" / "lamill.toml").exists()


def test_migration_apply_writes_ambiguous_with_include_flag(fake_fleet):
    """`--include-ambiguous` picks via priority order (vercel >
    cf-pages > cf-workers > netlify) and embeds a notes warning."""
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    _write_vercel_json(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(
        dry_run=False, sites_root=sites_root, include_ambiguous=True,
    )
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.action == "wrote"
    assert row.chosen_platform == "vercel"  # priority wins

    loaded = load(sites_root / "airsucks.com")
    assert loaded.deploy.platform == "vercel"
    # notes embedded so the operator sees the conflict on inspection.
    assert loaded.notes is not None
    assert "AMBIGUOUS" in loaded.notes


def test_migration_priority_picks_cf_pages_over_netlify(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "calcengine.site")
    _write_netlify_toml(sites_root / "calcengine.site")
    rows = migrate_deploy_declarations(
        dry_run=False, sites_root=sites_root, include_ambiguous=True,
    )
    row = next(r for r in rows if r.domain == "calcengine.site")
    assert row.chosen_platform == "cf-pages"


def test_migration_dry_run_writes_nothing(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    rows = migrate_deploy_declarations(dry_run=True, sites_root=sites_root)
    row = next(r for r in rows if r.domain == "airsucks.com")
    assert row.action == "would_write"
    # No file written despite the unambiguous classification.
    assert not (sites_root / "airsucks.com" / "lamill.toml").exists()


# ---------- CLI shell ----------


def test_cli_dry_run_default_writes_nothing(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    runner = CliRunner()
    result = runner.invoke(
        app, ["fleet", "repos", "--add-deploy-declarations"],
    )
    assert result.exit_code == 0, result.stdout
    assert "Dry-run" in result.stdout
    assert "Unambiguous" in result.stdout
    assert "would write lamill.toml" in result.stdout
    # No file written.
    assert not (sites_root / "airsucks.com" / "lamill.toml").exists()


def test_cli_apply_writes_files(fake_fleet):
    sites_root, _ = fake_fleet
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")
    _write_vercel_json(sites_root / "calcengine.site")
    _write_netlify_toml(sites_root / "kwizicle.com")
    runner = CliRunner()
    result = runner.invoke(
        app, ["fleet", "repos", "--add-deploy-declarations", "--apply"],
    )
    assert result.exit_code == 0, result.stdout
    assert "wrote lamill.toml" in result.stdout
    # Three writes expected (one per unambiguous site).
    assert (sites_root / "airsucks.com" / "lamill.toml").exists()
    assert (sites_root / "calcengine.site" / "lamill.toml").exists()
    assert (sites_root / "kwizicle.com" / "lamill.toml").exists()


def test_cli_summary_shows_section_counts(fake_fleet):
    sites_root, _ = fake_fleet
    # Mix of classifications:
    _write_wrangler_jsonc_pages(sites_root / "airsucks.com")  # unambiguous
    _write_vercel_json(sites_root / "calcengine.site")
    _write_vercel_json(sites_root / "calcengine.site")  # idempotent
    _write_wrangler_jsonc_pages(sites_root / "kwizicle.com")
    _write_netlify_toml(sites_root / "kwizicle.com")  # ambiguous
    # hybridautopart.com → manual (no config files)
    # swiftly.co.in → archived (category)

    runner = CliRunner()
    result = runner.invoke(
        app, ["fleet", "repos", "--add-deploy-declarations"],
    )
    assert result.exit_code == 0, result.stdout
    flat = " ".join(result.stdout.split())
    assert "Total:" in flat
    # All five fake-fleet sites accounted for.
    assert "5 sites" in flat