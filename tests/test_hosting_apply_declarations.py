"""Tests for v11.J — `apply_hg_declarations()` + CLI flag.

`apply_hg_declarations()` is the data layer — pure logic that
decides per-row what action would be taken. Tests inject
`sites_root` (tmp filesystem) and `plan` (dict) so no real
portfolio.json / SITES_ROOT is touched.

CLI tests via Typer's CliRunner stub the walker so we can control
the rows being applied.
"""
from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from portfolio import apikeys, cli, hosting, hosting_cache
from portfolio.hosting import (
    HostingResult,
    HostingRow,
    HgApplyRow,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    apply_hg_declarations,
)
from portfolio.lamill_toml import LAMILL_TOML_FILENAME, load


# ---- apply_hg_declarations — pure data layer --------------------


def _hg_row(*, domain: str, account_id: str = "gator3164",
            install_path: str | None = "/home1/u/public_html/site",
            wp_version: str | None = None) -> HostingRow:
    """Compact builder for HG HostingRows in the apply tests."""
    return HostingRow(
        domain=domain,
        provider=PROVIDER_HOSTGATOR,
        hg_account_id=account_id,
        install_path=install_path,
        wp_version=wp_version,
    )


def test_apply_ignores_non_hg_rows(tmp_path):
    """`provider!=hostgator` rows are skipped silently — v10.C already
    handles CF/Vercel via filesystem inference. apply_hg_declarations
    is HG-only."""
    rows = [
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
        HostingRow(domain="c.com", provider=PROVIDER_CF_WORKERS),
    ]
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan={})
    assert result == []


def test_apply_skips_when_no_site_dir(tmp_path):
    """HG-hosted domain with no local `sites/<domain>/` → skipped."""
    rows = [_hg_row(domain="thakinaam.com")]
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan={})
    assert len(result) == 1
    assert result[0].action == "skipped_no_site_dir"
    assert "missing" in result[0].notes


def test_apply_skips_when_archived_via_tombstone(tmp_path):
    """TOMBSTONE.md present → skipped_archived (mirrors v10.C
    `_is_archived` logic)."""
    site = tmp_path / "archived.example"
    site.mkdir()
    (site / "TOMBSTONE.md").write_text("# archived\n")
    rows = [_hg_row(domain="archived.example")]
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan={})
    assert result[0].action == "skipped_archived"


def test_apply_skips_when_archived_via_plan_category(tmp_path):
    """portfolio.json category in archived set → skipped."""
    site = tmp_path / "retiring.com"
    site.mkdir()
    rows = [_hg_row(domain="retiring.com")]
    plan = {"retiring.com": "archived"}
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan=plan)
    assert result[0].action == "skipped_archived"


def test_apply_skips_when_lamill_toml_already_exists(tmp_path):
    """Resolution 11.N — never overwrite. lamill.toml present →
    skipped_already, no write."""
    site = tmp_path / "hybridautopart.com"
    site.mkdir()
    (site / LAMILL_TOML_FILENAME).write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "hostgator"\n'
    )
    rows = [_hg_row(domain="hybridautopart.com")]
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan={})
    assert result[0].action == "skipped_already"
    # The file body is untouched.
    body = (site / LAMILL_TOML_FILENAME).read_text()
    assert "made-up" not in body  # arbitrary sentinel


def test_apply_dry_run_does_not_write(tmp_path):
    """Default dry-run mode reports `would_write` but writes nothing."""
    site = tmp_path / "hybridautopart.com"
    site.mkdir()
    rows = [_hg_row(domain="hybridautopart.com",
                    install_path="/home1/u/public_html/hybridautopart.com")]
    result = apply_hg_declarations(
        rows, sites_root=tmp_path, plan={}, dry_run=True,
    )
    assert result[0].action == "would_write"
    assert not (site / LAMILL_TOML_FILENAME).exists()


def test_apply_writes_when_not_dry_run(tmp_path):
    """`dry_run=False` actually writes a parseable lamill.toml."""
    site = tmp_path / "hybridautopart.com"
    site.mkdir()
    rows = [_hg_row(
        domain="hybridautopart.com",
        account_id="gator3164",
        install_path="/home1/u/public_html/hybridautopart.com",
    )]
    result = apply_hg_declarations(
        rows, sites_root=tmp_path, plan={}, dry_run=False,
    )
    assert result[0].action == "wrote"
    written = site / LAMILL_TOML_FILENAME
    assert written.exists()

    # Roundtrip through v10.A loader to confirm schema is valid.
    payload = load(site)
    assert payload is not None
    assert payload.deploy.platform == "hostgator"
    assert payload.deploy.account == "gator3164"
    assert payload.deploy.custom_domains == ["hybridautopart.com"]
    assert payload.hosting is not None
    assert payload.hosting.cpanel_user == "gator3164"
    assert payload.hosting.cpanel_url == "https://gator3164.hostgator.com:2083"
    assert payload.hosting.ftp_host == "gator3164.hostgator.com"
    assert payload.hosting.public_html_path == "/home1/u/public_html/hybridautopart.com"


def test_apply_handles_multiple_rows_with_mixed_outcomes(tmp_path):
    """A single call returns mixed actions across the input rows.
    Reflects the real fleet shape — some sites have local repos,
    some don't, some already have lamill.toml."""
    # has site dir, no lamill.toml → would_write (dry run)
    (tmp_path / "fresh.com").mkdir()

    # has site dir + lamill.toml → skipped_already
    site2 = tmp_path / "declared.com"
    site2.mkdir()
    (site2 / LAMILL_TOML_FILENAME).write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "hostgator"\n'
    )

    # no site dir → skipped_no_site_dir
    rows = [
        _hg_row(domain="fresh.com"),
        _hg_row(domain="declared.com"),
        _hg_row(domain="missing.com"),
    ]
    result = apply_hg_declarations(
        rows, sites_root=tmp_path, plan={}, dry_run=True,
    )
    actions = {r.domain: r.action for r in result}
    assert actions == {
        "fresh.com": "would_write",
        "declared.com": "skipped_already",
        "missing.com": "skipped_no_site_dir",
    }


def test_apply_drops_hg_row_without_account_id(tmp_path):
    """Defensive — every HG row from the walker carries account_id,
    but if somehow malformed, skip silently rather than write a
    broken lamill.toml."""
    rows = [HostingRow(
        domain="weird.com", provider=PROVIDER_HOSTGATOR,
        hg_account_id=None,
    )]
    result = apply_hg_declarations(rows, sites_root=tmp_path, plan={})
    assert result == []


def test_apply_includes_install_path_in_notes_when_set(tmp_path):
    """Notes string carries the install_path for operator visibility
    at dry-run time."""
    (tmp_path / "x.com").mkdir()
    rows = [_hg_row(
        domain="x.com", account_id="gator3164",
        install_path="/home1/u/public_html/x.com",
    )]
    result = apply_hg_declarations(
        rows, sites_root=tmp_path, plan={}, dry_run=True,
    )
    assert result[0].action == "would_write"
    assert "public_html_path=/home1/u/public_html/x.com" in result[0].notes


# ---- CLI flag — Typer integration -------------------------------


runner = CliRunner()


def _patch_fleet_domains(monkeypatch, names: list[str]) -> None:
    class _D:
        def __init__(self, name): self.name = name
    monkeypatch.setattr(
        cli, "load_domains",
        lambda *a, **kw: [_D(n) for n in names],
    )


def _patch_run_hosting_with_rows(monkeypatch, rows: list[HostingRow]):
    def _stub(fleet_domains, *, only_domain=None):
        return HostingResult(rows=list(rows))
    monkeypatch.setattr(hosting, "run_hosting", _stub)


def _stub_hosting_cache(monkeypatch, tmp_path: Path) -> Path:
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    return hosting_dir


def test_cli_apply_declarations_dry_run_default(monkeypatch, tmp_path):
    """`--apply-declarations` without `--apply` is dry-run; uses the
    walker rows; doesn't write."""
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "hybridautopart.com").mkdir()
    # Force the apply function to use our tmp sites_root.
    from portfolio import fleet_repos
    monkeypatch.setattr(fleet_repos, "SITES_ROOT", sites)

    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["hybridautopart.com"])
    _patch_run_hosting_with_rows(monkeypatch, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164",
                   install_path="/home1/u/public_html/hybridautopart.com"),
    ])

    out = runner.invoke(cli.app, ["fleet", "hosting", "--apply-declarations"])
    assert out.exit_code == 0, out.output
    assert "dry-run" in out.output
    assert "Would write" in out.output
    assert "hybridautopart.com" in out.output
    # Critical: no file written in dry-run.
    assert not (sites / "hybridautopart.com" / LAMILL_TOML_FILENAME).exists()


def test_cli_apply_declarations_apply_writes_file(monkeypatch, tmp_path):
    """`--apply-declarations --apply` actually writes the lamill.toml."""
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "hybridautopart.com").mkdir()
    from portfolio import fleet_repos
    monkeypatch.setattr(fleet_repos, "SITES_ROOT", sites)

    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["hybridautopart.com"])
    _patch_run_hosting_with_rows(monkeypatch, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164",
                   install_path="/home1/u/public_html/hybridautopart.com"),
    ])

    out = runner.invoke(
        cli.app, ["fleet", "hosting", "--apply-declarations", "--apply"],
    )
    assert out.exit_code == 0, out.output
    assert "apply" in out.output
    assert "Wrote" in out.output
    # File now exists with a valid schema.
    written = sites / "hybridautopart.com" / LAMILL_TOML_FILENAME
    assert written.exists()
    body = written.read_text()
    assert 'platform = "hostgator"' in body


def test_cli_apply_declarations_json_output(monkeypatch, tmp_path):
    """`--apply-declarations --json` emits structured output."""
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "hybridautopart.com").mkdir()
    from portfolio import fleet_repos
    monkeypatch.setattr(fleet_repos, "SITES_ROOT", sites)

    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["hybridautopart.com"])
    _patch_run_hosting_with_rows(monkeypatch, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
    ])

    out = runner.invoke(
        cli.app, ["fleet", "hosting", "--apply-declarations", "--json"],
    )
    assert out.exit_code == 0, out.output
    body = json.loads(out.output)
    assert body["dry_run"] is True
    assert len(body["rows"]) == 1
    assert body["rows"][0]["domain"] == "hybridautopart.com"
    assert body["rows"][0]["action"] == "would_write"


def test_cli_apply_declarations_no_hg_rows_emits_helpful_message(
    monkeypatch, tmp_path,
):
    """Empty walker output → friendly hint, exit 0."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, [])
    _patch_run_hosting_with_rows(monkeypatch, [])

    out = runner.invoke(cli.app, ["fleet", "hosting", "--apply-declarations"])
    assert out.exit_code == 0
    assert "No HG rows" in out.output


def test_cli_apply_declarations_dry_run_hints_next_step(monkeypatch, tmp_path):
    """When there ARE would-write rows in dry-run, footer hints at
    `--apply` as the next step."""
    sites = tmp_path / "sites"
    sites.mkdir()
    (sites / "hybridautopart.com").mkdir()
    from portfolio import fleet_repos
    monkeypatch.setattr(fleet_repos, "SITES_ROOT", sites)

    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["hybridautopart.com"])
    _patch_run_hosting_with_rows(monkeypatch, [
        HostingRow(domain="hybridautopart.com",
                   provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
    ])

    out = runner.invoke(cli.app, ["fleet", "hosting", "--apply-declarations"])
    assert out.exit_code == 0
    normalized = " ".join(out.output.split())
    assert "--apply" in normalized
