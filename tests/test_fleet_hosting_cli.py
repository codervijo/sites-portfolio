"""Tests for v11.G — `fleet hosting` CLI shell.

Stubs at the `run_hosting` + `hosting_cache` boundary. Tests focus
on:
  - cache-eligibility logic (fresh snapshot reused; stale → re-walk)
  - --refresh forces re-walk
  - --provider filters rows post-walker
  - --json emits the typed shape
  - Unknown --provider value rejected with exit code 2

v15.B hard-cutover: the `--only <domain>` flag was removed from
`fleet hosting`. Single-domain probes live at `project hosting
<domain>` now (see `test_project_hosting_cli.py`). The "rejects
--only" test below asserts the old flag fails outright.
"""
from __future__ import annotations

import json
from pathlib import Path

import typer
from typer.testing import CliRunner

from portfolio import cli, data, fleet_cli, hosting, hosting_cache
from portfolio.hosting import (
    HostingResult,
    HostingRow,
    PROVIDER_CF_PAGES,
    PROVIDER_CF_WORKERS,
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
    # _fleet_hosting_impl resolves load_domains in fleet_cli's namespace
    # after the v35.F incr-10 split.
    monkeypatch.setattr(
        fleet_cli, "load_domains",
        lambda *a, **kw: [_D(n) for n in names],
    )


def _patch_run_hosting(monkeypatch, *, result: HostingResult,
                       capture: dict | None = None):
    """Replace `hosting.run_hosting` with a stub. `capture` records
    the call args (fleet_domains, only_domain) for assertion.

    `only_domain` is accepted for back-compat with `project hosting`
    (the per-project verb that still uses it); `fleet hosting` no
    longer passes it post-v15.B."""
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


def test_fleet_hosting_only_flag_rejected_post_v15b(monkeypatch, tmp_path):
    """v15.B hard-cutover guard — `--only` is no longer a valid flag
    on `fleet hosting`. Old invocations now fail with typer's
    standard "no such option" error (exit code 2). Single-domain
    probes live at `project hosting <domain>` instead."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["airsucks.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult())
    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--only", "airsucks.com"])
    assert out.exit_code == 2
    assert "no such option" in out.output.lower() or "--only" in out.output


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


# ---- v11.I renderer upgrades ------------------------------------


def test_fleet_hosting_table_includes_status_emoji_column(monkeypatch, tmp_path):
    """v11.I — first column is a single-glyph status. With a fresh
    READY Vercel row the table contains ✓."""
    from datetime import datetime, timezone
    fresh_iso = datetime.now(timezone.utc).isoformat()
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(
            domain="a.com", provider=PROVIDER_VERCEL,
            latest_deploy_status="READY",
            last_successful_deploy_at=fresh_iso,
        ),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0, out.output
    assert "✓" in out.output


def test_fleet_hosting_table_shows_conflict_glyph_for_conflict_row(
    monkeypatch, tmp_path,
):
    """Provider-conflict rows render with 🤐 in the status column."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["x.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="x.com", provider=PROVIDER_VERCEL,
                   provider_conflict=True),
        HostingRow(domain="x.com", provider=PROVIDER_CF_PAGES,
                   provider_conflict=True),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "🤐" in out.output


def test_fleet_hosting_omits_hg_extra_column_when_no_hg_rows(
    monkeypatch, tmp_path,
):
    """v11.I — HG-extra column hidden when zero HG rows.

    Bug 2026-05-19 fix: empty column was visual noise. Now only
    rendered when at least one row would populate it."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "HG-extra" not in out.output


def test_fleet_hosting_shows_hg_extra_column_when_hg_row_present(
    monkeypatch, tmp_path,
):
    """Counter-test: column SHOWS when an HG row exists. Per-row
    HG-extra carries WP version + install_path; disk usage moved to
    the footer (account-level, 2026-05-21 fix)."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(
            domain="b.com", provider=PROVIDER_HOSTGATOR,
            hg_account_id="gator3164",
            disk_used_mb=1430, wp_version="6.7.1",
        ),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "HG-extra" in out.output
    assert "WP 6.7.1" in out.output
    # disk MB no longer in per-row HG-extra; surfaced in footer.
    assert "HG accounts: gator3164 1430MB" in out.output


def test_fleet_hosting_footer_aggregates_disk_per_hg_account(
    monkeypatch, tmp_path,
):
    """2026-05-21 fix — disk_used_mb is account-scoped, not per-domain.
    Two sites on the same gator3164 account + one on gator4216 should
    produce a footer with both accounts listed once, sorted by name."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com", "c.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(
            domain="a.com", provider=PROVIDER_HOSTGATOR,
            hg_account_id="gator3164", disk_used_mb=500,
        ),
        HostingRow(
            domain="b.com", provider=PROVIDER_HOSTGATOR,
            hg_account_id="gator3164", disk_used_mb=500,
        ),
        HostingRow(
            domain="c.com", provider=PROVIDER_HOSTGATOR,
            hg_account_id="gator4216", disk_used_mb=4959,
        ),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    # Single footer line lists each account once, sorted.
    assert "HG accounts: gator3164 500MB · gator4216 4959MB" in out.output
    # Per-row "disk NMB" gone.
    assert "disk 500MB" not in out.output
    assert "disk 4959MB" not in out.output


def test_fleet_hosting_no_hg_disk_footer_when_no_hg_disk_data(
    monkeypatch, tmp_path,
):
    """Footer line suppressed when no HG row has disk_used_mb populated
    (e.g., cache predates v11 fields, or only non-HG rows present)."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "HG accounts:" not in out.output


def test_fleet_hosting_footer_summary_line_shows_provider_counts(
    monkeypatch, tmp_path,
):
    """v11.I bug-2 fix — footer aggregates row counts by provider."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com", "c.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_PAGES),
        HostingRow(domain="c.com", provider=PROVIDER_CF_PAGES),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    assert "3 rows" in out.output
    assert "1 vercel" in out.output
    assert "2 cloudflare-pages" in out.output
    assert "0 cloudflare-workers" in out.output
    assert "0 hostgator" in out.output


def test_fleet_hosting_footer_includes_skipped_count_when_present(
    monkeypatch, tmp_path,
):
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(
        rows=[HostingRow(domain="a.com", provider=PROVIDER_VERCEL)],
        skipped={
            "hostgator:gator3164": "walker — 403",
            "hostgator:gator4216": "walker — 403",
        },
    ))
    out = runner.invoke(cli.app, ["fleet", "hosting"])
    assert out.exit_code == 0
    # Rich's word-wrap can split the footer across lines on a narrow
    # terminal — normalize whitespace before asserting.
    normalized = " ".join(out.output.split())
    assert "2 skipped" in normalized
    assert "hostgator:gator3164" in out.output


def test_fleet_hosting_provider_filter_zero_rows_shows_pre_filter_breakdown(
    monkeypatch, tmp_path,
):
    """v11.I bug-3 fix — filtering to a provider with 0 matches should
    explain the filter caused it + show what WAS available.

    Reproduces the operator's observation 2026-05-19 where
    `--provider=cloudflare-pages` showed only "No hosting rows"
    despite the walker returning 11 rows under other providers."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, ["a.com", "b.com"])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[
        HostingRow(domain="a.com", provider=PROVIDER_VERCEL),
        HostingRow(domain="b.com", provider=PROVIDER_CF_WORKERS),
    ]))
    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--provider", "cloudflare-pages"])
    assert out.exit_code == 0
    assert "No `cloudflare-pages` rows." in out.output
    assert "Filtered from 2 total" in out.output
    # Pre-filter breakdown surfaces the available providers.
    assert "1 vercel" in out.output
    assert "1 cloudflare-workers" in out.output


def test_fleet_hosting_provider_filter_when_walker_returned_zero(
    monkeypatch, tmp_path,
):
    """Distinguish from previous test — when walker genuinely returned
    zero rows, the message stays "No hosting rows." (no filter to blame)."""
    _stub_hosting_cache(monkeypatch, tmp_path)
    _patch_fleet_domains(monkeypatch, [])
    _patch_run_hosting(monkeypatch, result=HostingResult(rows=[]))
    out = runner.invoke(cli.app, ["fleet", "hosting",
                                  "--provider", "cloudflare-pages"])
    assert out.exit_code == 0
    assert "No hosting rows" in out.output
    # NO "Filtered from N total" since there was nothing to filter from.
    assert "Filtered from" not in out.output
