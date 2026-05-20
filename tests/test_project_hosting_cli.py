"""Tests for v15.B — `project hosting <domain>` CLI surface.

Stubs at the `run_hosting` + `hosting_cache` boundary, mirroring
`test_fleet_hosting_cli.py`. Covers:
  - Happy path: known domain → vertical sections rendered
  - JSON output for scripted consumption
  - Unknown domain → no rows + helpful "not claimed" notice
  - Cache reuse vs --refresh re-walk
  - Single-domain probe does NOT overwrite the fleet snapshot

The legacy single-domain branch on `fleet hosting --only <domain>`
moved here. Hard-cutover — no alias on the old verb. See
`test_fleet_hosting_cli.py::test_fleet_hosting_only_flag_rejected_post_v15b`
for the guard.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from typer.testing import CliRunner

from portfolio import cli, hosting, hosting_cache
from portfolio.hosting import (
    HostingResult,
    HostingRow,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
    PROVIDER_VERCEL,
)


runner = CliRunner()


# ---- helpers ------------------------------------------------------


def _patch_fleet_domains(monkeypatch, names: list[str]) -> None:
    class _D:
        def __init__(self, name): self.name = name
    monkeypatch.setattr(
        cli, "load_domains",
        lambda *a, **kw: [_D(n) for n in names],
    )


def _patch_run_hosting(monkeypatch, *, result: HostingResult,
                       capture: dict | None = None):
    def _stub(fleet_domains, *, only_domain=None):
        if capture is not None:
            capture["fleet_domains"] = set(fleet_domains)
            capture["only_domain"] = only_domain
        return result
    monkeypatch.setattr(hosting, "run_hosting", _stub)


def _stub_hosting_cache(monkeypatch, tmp_path: Path) -> Path:
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    return hosting_dir


# ---- happy path ---------------------------------------------------


def test_project_hosting_renders_vertical_sections(monkeypatch, tmp_path):
    """A known domain returns the 📦 Deploy + 📌 Domains blocks
    instead of a one-row table."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    fresh_iso = datetime.now(timezone.utc).isoformat()
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(
            domain="airsucks.com",
            provider="cloudflare-workers",
            latest_deploy_status="READY",
            last_successful_deploy_at=fresh_iso,
            latest_deploy_at=fresh_iso,
        ),
    ]))
    out = runner.invoke(cli.app, ["project", "hosting", "airsucks.com"])
    assert out.exit_code == 0, out.output
    # Header.
    assert "airsucks.com" in out.output
    assert "cloudflare-workers" in out.output
    # Sections — vertical layout, not a table.
    assert "📦 Deploy" in out.output
    assert "📌 Domains" in out.output
    assert "DEPLOYED" in out.output
    # No table border characters (the table renderer uses ┌─ etc.).
    assert "┌" not in out.output
    assert "┃" not in out.output


def test_project_hosting_lowercases_domain(monkeypatch, tmp_path):
    """Mixed-case input should still match a lowercase row."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL),
    ]))
    out = runner.invoke(cli.app, ["project", "hosting", "AirSucks.COM"])
    assert out.exit_code == 0, out.output
    assert "airsucks.com" in out.output


# ---- JSON output --------------------------------------------------


def test_project_hosting_json_emits_typed_shape(monkeypatch, tmp_path):
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL),
    ]))
    out = runner.invoke(
        cli.app, ["project", "hosting", "airsucks.com", "--json"],
    )
    assert out.exit_code == 0, out.output
    body = json.loads(out.output)
    assert body["domain"] == "airsucks.com"
    assert "source" in body
    assert [r["domain"] for r in body["rows"]] == ["airsucks.com"]


def test_project_hosting_json_filters_to_one_domain(monkeypatch, tmp_path):
    """Walker may return multiple rows; `project hosting` filters
    to the requested domain only."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
    ]))
    out = runner.invoke(cli.app, ["project", "hosting", "a.com", "--json"])
    body = json.loads(out.output)
    assert [r["domain"] for r in body["rows"]] == ["a.com"]


# ---- unknown domain ----------------------------------------------


def test_project_hosting_unknown_domain_returns_friendly_notice(
    monkeypatch, tmp_path,
):
    """When the walker returns nothing for the requested domain,
    show the 'not claimed' notice + skipped-provider footer (if any),
    exit 0 — discoverability, not an error."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["other.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(
        rows=[HostingRow(domain="other.com", provider=PROVIDER_VERCEL)],
        skipped={"hostgator": "no HOSTGATOR_TOKEN_<account> set"},
    ))
    out = runner.invoke(cli.app, ["project", "hosting", "ghost.com"])
    assert out.exit_code == 0, out.output
    assert "No hosting rows for ghost.com" in out.output
    assert "hostgator skipped" in out.output


def test_project_hosting_unknown_domain_json_returns_empty_rows(
    monkeypatch, tmp_path,
):
    """JSON shape stays consistent — `rows: []` for unknown, not an error."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["other.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult())
    out = runner.invoke(
        cli.app, ["project", "hosting", "ghost.com", "--json"],
    )
    assert out.exit_code == 0, out.output
    body = json.loads(out.output)
    assert body["domain"] == "ghost.com"
    assert body["rows"] == []


# ---- cache reuse vs --refresh ------------------------------------


def test_project_hosting_uses_fresh_snapshot(monkeypatch, tmp_path):
    """When a fresh fleet snapshot exists, `project hosting` reads
    from it instead of re-probing."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    fresh_ts = datetime.now(timezone.utc).isoformat()
    (hosting_dir / "today.json").write_text(json.dumps({
        "fetched_at": fresh_ts,
        "rows": [{"domain": "airsucks.com", "provider": "vercel"}],
        "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(), capture=capture)

    out = runner.invoke(
        cli.app, ["project", "hosting", "airsucks.com", "--json"],
    )
    assert out.exit_code == 0, out.output
    # run_hosting must NOT have been called.
    assert capture == {}
    body = json.loads(out.output)
    assert "snapshot" in body["source"]
    assert body["rows"][0]["domain"] == "airsucks.com"


def test_project_hosting_refresh_forces_walk(monkeypatch, tmp_path):
    """--refresh re-probes even when a fresh snapshot exists. Walker
    is called with `only_domain=` so it's a single-domain probe."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    fresh_ts = datetime.now(timezone.utc).isoformat()
    (hosting_dir / "today.json").write_text(json.dumps({
        "fetched_at": fresh_ts, "rows": [], "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL),
    ]), capture=capture)

    out = runner.invoke(
        cli.app, ["project", "hosting", "airsucks.com",
                  "--refresh", "--json"],
    )
    assert out.exit_code == 0, out.output
    assert capture["only_domain"] == "airsucks.com"
    body = json.loads(out.output)
    assert "single-domain probe" in body["source"]


def test_project_hosting_stale_snapshot_triggers_single_domain_probe(
    monkeypatch, tmp_path,
):
    """An old snapshot is treated as missing — the renderer falls
    through to a single-domain probe (NOT a full fleet re-walk)."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    (hosting_dir / "old.json").write_text(json.dumps({
        "fetched_at": old_ts, "rows": [], "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(), capture=capture)
    out = runner.invoke(
        cli.app, ["project", "hosting", "airsucks.com", "--json"],
    )
    assert out.exit_code == 0, out.output
    assert capture["only_domain"] == "airsucks.com"


def test_project_hosting_refresh_does_not_overwrite_fleet_snapshot(
    monkeypatch, tmp_path,
):
    """Critical invariant — a single-domain probe must leave the
    fleet snapshot file alone (otherwise the operator's full
    snapshot gets clobbered by a one-row probe)."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    snap_path = hosting_dir / "today.json"
    original_body = (
        '{"fetched_at": "old", "rows": [{"domain":"keep.com"}], "skipped":{}}'
    )
    snap_path.write_text(original_body)

    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="airsucks.com", provider=PROVIDER_VERCEL),
    ]))
    out = runner.invoke(
        cli.app, ["project", "hosting", "airsucks.com",
                  "--refresh", "--json"],
    )
    assert out.exit_code == 0, out.output
    # Original snapshot unchanged.
    assert snap_path.read_text() == original_body


# ---- conflict rendering ------------------------------------------


def test_project_hosting_conflict_renders_both_rows(monkeypatch, tmp_path):
    """When a domain is claimed by multiple walkers, the per-project
    view stacks both provider sections under one header. Same
    information surface as the fleet table's 🤐 row."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["x.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL,
                   provider_conflict=True),
        HostingRow(domain="x.com", provider=PROVIDER_CF_WORKERS,
                   provider_conflict=True),
    ]))
    out = runner.invoke(cli.app, ["project", "hosting", "x.com"])
    assert out.exit_code == 0, out.output
    # Both providers surface; conflict notice present.
    assert "vercel" in out.output
    assert "cloudflare-workers" in out.output
    assert "🤐" in out.output
