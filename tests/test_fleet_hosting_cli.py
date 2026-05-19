"""Tests for v11.G — `fleet hosting` CLI shell.

Stubs at the `run_hosting` + `hosting_cache` boundary. Tests focus
on:
  - cache-eligibility logic (fresh snapshot reused; stale → re-walk)
  - --refresh forces re-walk
  - --only forces single-domain probe (bypasses cache + doesn't
    overwrite the snapshot)
  - --provider filters rows post-walker
  - --json emits the typed shape
  - Unknown --provider value rejected with exit code 2
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from typer.testing import CliRunner

from portfolio import cli, data, hosting, hosting_cache
from portfolio.hosting import (
    HostingResult,
    HostingRow,
    PROVIDER_CF_PAGES,
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
)


runner = CliRunner()


# ---- helpers ------------------------------------------------------


def _patch_fleet_domains(monkeypatch, names: list[str]) -> None:
    """Stub `data.load_domains` so the CLI's fleet_domains set is
    deterministic without depending on the operator's portfolio.json."""
    class _D:
        def __init__(self, name): self.name = name
    monkeypatch.setattr(
        cli, "load_domains",
        lambda *a, **kw: [_D(n) for n in names],
    )


def _patch_run_hosting(monkeypatch, *, result: HostingResult,
                       capture: dict | None = None):
    """Replace `hosting.run_hosting` with a stub. `capture` records
    the call args (fleet_domains, only_domain) for assertion."""
    def _stub(fleet_domains, *, only_domain=None):
        if capture is not None:
            capture["fleet_domains"] = set(fleet_domains)
            capture["only_domain"] = only_domain
        return result
    monkeypatch.setattr(hosting, "run_hosting", _stub)


def _stub_hosting_cache(monkeypatch, tmp_path: Path) -> Path:
    """Redirect the cache module at a tmp dir."""
    hosting_dir = tmp_path / "data" / "hosting"
    monkeypatch.setattr(hosting_cache, "HOSTING_DIR", hosting_dir)
    return hosting_dir


# ---- --provider validation ---------------------------------------


def test_fleet_hosting_unknown_provider_exits_2(monkeypatch, tmp_path):
    _patch_fleet_domains(monkeypatch, [])
    _stub_hosting_cache(monkeypatch, tmp_path)
    result = runner.invoke(cli.app, ["fleet", "hosting", "--provider", "made-up"])
    assert result.exit_code == 2
    assert "Unknown provider" in result.output


def test_fleet_hosting_known_provider_accepted(monkeypatch, tmp_path):
    _patch_fleet_domains(monkeypatch, [])
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_run_hosting(monkeypatch, result=HostingResult())
    result = runner.invoke(cli.app, ["fleet", "hosting", "--provider", "vercel"])
    assert result.exit_code == 0


# ---- cache eligibility ------------------------------------------


def test_fleet_hosting_fresh_snapshot_reused_without_refresh(monkeypatch, tmp_path):
    """Fresh snapshot on disk → don't re-walk; render from cache."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    # Build a fresh snapshot (now-ish fetched_at).
    from datetime import datetime, timezone
    snap_path = hosting_dir / "today.json"
    snap_path.write_text(json.dumps({
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "rows": [{"domain": "airsucks.com", "provider": "vercel"}],
        "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(), capture=capture)

    out = runner.invoke(cli.app, ["fleet", "hosting", "--json"])
    assert out.exit_code == 0, out.output
    # run_hosting() must NOT have been called — cache was eligible.
    assert capture == {}
    body = json.loads(out.output)
    assert "snapshot" in body["source"]
    assert any(r["domain"] == "airsucks.com" for r in body["rows"])


def test_fleet_hosting_stale_snapshot_triggers_refresh(monkeypatch, tmp_path):
    """Old snapshot → re-walk + overwrite."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    from datetime import datetime, timedelta, timezone
    old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
    (hosting_dir / "old.json").write_text(json.dumps({
        "fetched_at": old_ts, "rows": [], "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(
        monkeypatch,
        result=HostingResult(rows=[HostingRow(
            domain="airsucks.com", provider=PROVIDER_VERCEL,
        )]),
        capture=capture,
    )

    out = runner.invoke(cli.app, ["fleet", "hosting", "--json"])
    assert out.exit_code == 0, out.output
    assert capture["fleet_domains"] == {"airsucks.com"}
    body = json.loads(out.output)
    assert "fresh walk" in body["source"]


def test_fleet_hosting_refresh_flag_forces_walk_even_when_fresh(monkeypatch, tmp_path):
    """--refresh bypasses cache eligibility regardless of snapshot age."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    from datetime import datetime, timezone
    fresh_ts = datetime.now(timezone.utc).isoformat()
    (hosting_dir / "today.json").write_text(json.dumps({
        "fetched_at": fresh_ts, "rows": [], "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(), capture=capture)

    out = runner.invoke(cli.app, ["fleet", "hosting", "--refresh", "--json"])
    assert out.exit_code == 0, out.output
    assert capture["fleet_domains"] == {"airsucks.com"}


def test_fleet_hosting_only_domain_bypasses_cache(monkeypatch, tmp_path):
    """--only DOMAIN always re-walks (single-domain probes shouldn't
    read or overwrite the fleet-wide snapshot)."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    from datetime import datetime, timezone
    fresh_ts = datetime.now(timezone.utc).isoformat()
    (hosting_dir / "today.json").write_text(json.dumps({
        "fetched_at": fresh_ts, "rows": [], "skipped": {},
    }))
    _patch_fleet_domains(monkeypatch, ["airsucks.com", "calcengine.site"])
    capture: dict = {}
    _patch_run_hosting(monkeypatch, result=HostingResult(), capture=capture)

    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--only", "airsucks.com", "--json"])
    assert out.exit_code == 0, out.output
    assert capture["only_domain"] == "airsucks.com"
    # The pre-existing snapshot file should NOT be overwritten.
    body = json.loads(out.output)
    assert "single-domain probe" in body["source"]


def test_fleet_hosting_only_domain_does_not_overwrite_snapshot(monkeypatch, tmp_path):
    """Critical invariant — single-domain probe must leave the fleet
    snapshot file alone (otherwise the operator's full snapshot gets
    clobbered by a one-row probe)."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    hosting_dir.mkdir(parents=True)
    snap_path = hosting_dir / "today.json"
    original_body = '{"fetched_at": "old", "rows": [{"domain":"keep.com"}], "skipped":{}}'
    snap_path.write_text(original_body)

    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(
        monkeypatch,
        result=HostingResult(rows=[HostingRow(domain="airsucks.com",
                                              provider=PROVIDER_VERCEL)]),
    )
    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--only", "airsucks.com", "--json"])
    assert out.exit_code == 0, out.output
    # Original snapshot unchanged.
    assert snap_path.read_text() == original_body


def test_fleet_hosting_walk_persists_snapshot(monkeypatch, tmp_path):
    """A normal fleet-wide walk writes today's snapshot to disk so the
    next invocation can read the cache."""
    hosting_dir = _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(
        monkeypatch,
        result=HostingResult(rows=[HostingRow(domain="airsucks.com",
                                              provider=PROVIDER_VERCEL)]),
    )
    out = runner.invoke(cli.app, ["fleet", "hosting", "--json"])
    assert out.exit_code == 0, out.output
    # Snapshot exists with today's date.
    saved = list(hosting_dir.glob("*.json"))
    assert len(saved) == 1


# ---- --provider filtering ---------------------------------------


def test_fleet_hosting_provider_filter_drops_other_rows(monkeypatch, tmp_path):
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com", "c.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
        HostingRow(domain="c.com", provider=PROVIDER_HOSTGATOR,
                   hg_account_id="gator3164"),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--provider", "hostgator", "--json"])
    assert out.exit_code == 0, out.output
    body = json.loads(out.output)
    assert [r["domain"] for r in body["rows"]] == ["c.com"]


# ---- --json output ----------------------------------------------


def test_fleet_hosting_json_includes_skipped(monkeypatch, tmp_path):
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(
        rows=[HostingRow(domain="a.com", provider=PROVIDER_VERCEL)],
        skipped={"hostgator": "no HOSTGATOR_TOKEN_<account> set"},
    ))
    out = runner.invoke(cli.app, ["fleet", "hosting", "--json"])
    body = json.loads(out.output)
    assert body["skipped"] == {"hostgator": "no HOSTGATOR_TOKEN_<account> set"}


def test_fleet_hosting_table_renders_with_no_rows(monkeypatch, tmp_path):
    """No matches → no table, but the command still succeeds and
    surfaces the skipped footer."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, [])
    _patch_run_hosting(monkeypatch, result=HostingResult(
        skipped={"vercel": "VERCEL_TOKEN not set"},
    ))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "No hosting rows" in out.output
    assert "VERCEL_TOKEN" in out.output
