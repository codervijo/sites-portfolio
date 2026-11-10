"""v49.E — `lamill fleet ga` per-site runner."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from portfolio import fleet_ga
from portfolio.checks.seo import check_164_ga4_live_tag as c164

GA = "G-TEST123ABC"
TOML = f'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n[analytics]\nga4_id = "{GA}"\n'
LAYOUT = "---\nconst x = 1;\n---\n<html>\n  <head>\n    <title>x</title>\n  </head>\n</html>\n"


def _git(d: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, text=True).stdout


@pytest.fixture
def site(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(remote)], check=True)
    d = tmp_path / "example.test"
    (d / "src/layouts").mkdir(parents=True)
    (d / "package.json").write_text("{}")
    (d / "lamill.toml").write_text(TOML)
    (d / "src/layouts/Layout.astro").write_text(LAYOUT)
    (d / ".gitignore").write_text("dist/\n")
    _git(d.parent, "init", "-q", "-b", "main", str(d))
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    _git(d, "add", "-A")
    _git(d, "commit", "-qm", "init")
    _git(d, "remote", "add", "origin", str(remote))
    _git(d, "push", "-qu", "origin", "main")
    return d


@pytest.fixture(autouse=True)
def _live(monkeypatch):
    state = {"v": ("missing", "not yet")}
    monkeypatch.setattr(c164, "live_state", lambda base, client=None: state["v"])
    return state


def _good_build(base: Path):
    (base / "dist").mkdir(exist_ok=True)
    comp = (base / "src/components/Analytics.astro").read_text()
    (base / "dist/index.html").write_text(comp)
    return True, "build OK"


def _run(site, *, apply=True, build=_good_build, live=(True, "HTTP 200"), confirm=lambda q: True,
         account=("415643559", "LaMill Sites")):
    return fleet_ga.run_site(site.name, site, apply=apply, confirm=confirm, build=build,
                             is_live=lambda d, b: live, account_of=lambda ga: account,
                             other_account_id=lambda d: None)


@pytest.fixture(autouse=True)
def _fleet_account(monkeypatch):
    monkeypatch.setattr("portfolio.apikeys.get_key", lambda k: "415643559" if k == "GA4_ACCOUNT_ID" else None)


def test_dry_run_writes_nothing(site):
    r = _run(site, apply=False)
    assert r.outcome == "planned"
    assert not (site / "src/components/Analytics.astro").exists()
    assert _git(site, "status", "--porcelain") == ""


def test_apply_commits_only_touched_files_and_pushes(site):
    (site / "notes.txt").write_text("operator WIP")  # unrelated dirty file
    r = _run(site)
    assert r.outcome == "changed"
    assert sorted(r.touched) == ["src/components/Analytics.astro", "src/layouts/Layout.astro"]
    files = _git(site, "show", "--name-only", "--format=", "HEAD").split()
    assert sorted(files) == sorted(r.touched)
    assert "notes.txt" in _git(site, "status", "--porcelain")
    assert _git(site, "rev-parse", "HEAD") == _git(site, "rev-parse", "origin/main")
    assert GA in _git(site, "log", "-1", "--format=%s")


def test_build_failure_restores_everything(site):
    r = _run(site, build=lambda b: (False, "build failed (exit 1)"))
    assert r.outcome == "failed"
    assert not (site / "src/components/Analytics.astro").exists()
    assert (site / "src/layouts/Layout.astro").read_text() == LAYOUT
    assert _git(site, "log", "--oneline").count("\n") == 1


def test_build_without_id_in_output_fails(site):
    def b(base):
        (base / "dist").mkdir(exist_ok=True)
        (base / "dist/index.html").write_text("<html></html>")
        return True, "build OK"
    r = _run(site, build=b)
    assert r.outcome == "failed" and "doesn't contain" in r.detail
    assert (site / "src/layouts/Layout.astro").read_text() == LAYOUT


def test_touched_file_with_uncommitted_edits_stops(site):
    (site / "src/layouts/Layout.astro").write_text(LAYOUT + "<!-- wip -->\n")
    r = _run(site)
    assert r.outcome == "failed" and "uncommitted" in r.detail
    assert (site / "src/layouts/Layout.astro").read_text() == LAYOUT + "<!-- wip -->\n"
    assert not (site / "src/components/Analytics.astro").exists()


def test_not_live_is_skipped(site):
    r = _run(site, live=(False, "HTTP 404"))
    assert r.outcome == "skipped"


def test_unreachable_continues(site):
    r = _run(site, live=(None, "ConnectError: TLS"))
    assert r.outcome == "changed"


def test_id_in_other_account_is_deferred(site):
    r = _run(site, account=("365405177", "LaMill Rentals"))
    assert r.outcome == "deferred" and "LaMill Rentals" in r.detail
    assert not (site / "src/components/Analytics.astro").exists()


def test_rerun_is_done_and_reports_live(site, _live):
    _run(site)
    _live["v"] = ("live", f"{GA} in homepage HTML")
    head = _git(site, "rev-parse", "HEAD")
    r = _run(site, build=lambda b: pytest.fail("no build on a done site"))
    assert r.outcome == "done"
    assert _git(site, "rev-parse", "HEAD") == head


def test_declined_confirmation(site):
    r = _run(site, confirm=lambda q: False)
    assert r.outcome == "skipped"
    assert not (site / "src/components/Analytics.astro").exists()


def test_cli_registered():
    from typer.testing import CliRunner

    from portfolio.cli import app
    out = CliRunner().invoke(app, ["fleet", "ga", "--help"])
    assert out.exit_code == 0 and "--apply" in out.output


def test_privacy_page_claiming_no_analytics_blocks(site):
    (site / "src/pages").mkdir()
    (site / "src/pages/privacy.astro").write_text("<p>No analytics.</p>\n")
    _git(site, "add", "-A"); _git(site, "commit", "-qm", "privacy")
    r = _run(site)
    assert r.outcome == "failed" and "rewrite it first" in r.detail
    assert not (site / "src/components/Analytics.astro").exists()


def test_build_rewriting_a_tracked_file_is_undone(site):
    (site / "public").mkdir()
    (site / "public/sitemap.xml").write_text("<old/>")
    _git(site, "add", "-A"); _git(site, "commit", "-qm", "sitemap")

    def b(base):
        (base / "public/sitemap.xml").write_text("<regenerated/>")
        return _good_build(base)
    r = _run(site, build=b)
    assert r.outcome == "changed"
    assert (site / "public/sitemap.xml").read_text() == "<old/>"
    assert _git(site, "status", "--porcelain") == ""


# ---------------------------------------------------------------- v49.F --switch-old

OLD = "G-OLDOLD1234"
NEW = "G-NEWNEW5678"


def _switch_site(site: Path) -> Path:
    (site / "lamill.toml").write_text(TOML.replace(GA, OLD))
    (site / "src/components").mkdir(parents=True, exist_ok=True)
    (site / "src/components/Analytics.astro").write_text(f'<script src="https://www.googletagmanager.com/gtag/js?id={OLD}"></script>\n')
    (site / "src/layouts/Layout.astro").write_text(LAYOUT.replace("</head>", "<Analytics />\n  </head>"))
    _git(site, "add", "-A"); _git(site, "commit", "-qm", "old ga"); _git(site, "push", "-q")
    return site


def _run_switch(site, *, apply=True, env=("PUBLIC_GA_ID",), env_ok=True, build=_good_build):
    calls = []

    def drop(base, dry):
        calls.append(dry)
        if not dry and not env_ok:
            raise RuntimeError("403")
        return list(env)
    r = fleet_ga.run_site(site.name, site, apply=apply, confirm=lambda q: True, build=build,
                          is_live=lambda d, b: (True, "HTTP 200"),
                          account_of=lambda ga: ("365405177", "LaMill Rentals"),
                          switch_old=True, new_property=lambda d: NEW, drop_env=drop,
                          other_account_id=lambda d: OLD)
    return r, calls


def test_switch_dry_run_writes_nothing(site):
    _switch_site(site)
    r, calls = _run_switch(site, apply=False)
    assert r.outcome == "planned" and calls == [True]
    assert _git(site, "status", "--porcelain") == ""


def test_switch_replaces_id_drops_env_and_pushes(site):
    _switch_site(site)
    r, calls = _run_switch(site)
    assert r.outcome == "changed", r.detail
    assert calls == [True, False]
    assert NEW in (site / "lamill.toml").read_text()
    comp = (site / "src/components/Analytics.astro").read_text()
    assert NEW in comp and OLD not in comp
    assert f"{OLD} → {NEW}" in _git(site, "log", "-1", "--format=%s")
    assert _git(site, "rev-parse", "HEAD") == _git(site, "rev-parse", "origin/main")


def test_switch_env_delete_failure_reverts(site):
    _switch_site(site)
    head = _git(site, "rev-parse", "HEAD")
    r, _ = _run_switch(site, env_ok=False)
    assert r.outcome == "failed" and "env delete failed" in r.detail
    assert OLD in (site / "lamill.toml").read_text()
    assert _git(site, "rev-parse", "HEAD") == head
    assert _git(site, "status", "--porcelain") == ""


def test_without_flag_still_deferred(site):
    _switch_site(site)
    r = _run(site, account=("365405177", "LaMill Rentals"))
    assert r.outcome == "deferred"


def test_ensure_property_ignore_other_accounts_creates(monkeypatch):
    from portfolio import ga4_admin
    idx = [ga4_admin.StreamHit("1", "Old", "p1", "x.test", OLD, "x.test")]
    monkeypatch.setattr(ga4_admin, "create_property", lambda acct, name, client=None: "p2")
    monkeypatch.setattr(ga4_admin, "create_web_stream", lambda pid, uri, display_name, client=None: ("s", NEW))
    monkeypatch.setattr(ga4_admin, "set_data_retention", lambda pid, client=None: True)
    assert ga4_admin.ensure_property("x.test", "2", index=idx, client=object()).status == "elsewhere"
    out = ga4_admin.ensure_property("x.test", "2", index=idx, ignore_other_accounts=True, client=object())
    assert (out.status, out.measurement_id) == ("created", NEW)
    again = ga4_admin.ensure_property("x.test", "2", index=idx, ignore_other_accounts=True, client=object())
    assert (again.status, again.measurement_id) == ("found", NEW)


def test_switch_updates_gitignored_env_without_committing(site):
    _switch_site(site)
    (site / ".gitignore").write_text("dist/\n.env\n")
    _git(site, "commit", "-qam", "ignore env"); _git(site, "push", "-q")
    (site / ".env").write_text(f"PUBLIC_GA_ID={OLD}\n")
    r, _ = _run_switch(site)
    assert r.outcome == "changed"
    assert (site / ".env").read_text() == f"PUBLIC_GA_ID={NEW}\n"
    assert ".env" not in _git(site, "show", "--name-only", "--format=", "HEAD").split()


def test_switch_build_failure_restores_env(site):
    _switch_site(site)
    (site / ".gitignore").write_text("dist/\n.env\n")
    _git(site, "commit", "-qam", "ignore env"); _git(site, "push", "-q")
    (site / ".env").write_text(f"PUBLIC_GA_ID={OLD}\n")
    r, _ = _run_switch(site, build=lambda b: (False, "build failed (exit 1)"))
    assert r.outcome == "failed"
    assert (site / ".env").read_text() == f"PUBLIC_GA_ID={OLD}\n"


def test_switch_rerun_without_recorded_id_still_switches(site, monkeypatch):
    """calcengine shape: no ID in lamill.toml or source; old ID only in the
    hosting env; the fleet property already exists from a reverted run."""
    from portfolio.checks.seo import check_162_ga4_id_recorded as c162
    monkeypatch.setattr(c162, "_fix", lambda base, dry_run, assume_yes: (
        c162.FixResult("would-fix", f"record existing {NEW}", []) if dry_run
        else c162.FixResult("nothing-to-do", "", [])))
    (site / "lamill.toml").write_text(TOML.split("[analytics]")[0])
    _git(site, "commit", "-qam", "no id"); _git(site, "push", "-q")
    r, calls = _run_switch(site)
    assert r.outcome == "changed", r.detail
    assert calls == [True, False]
    assert f"{OLD} → {NEW}" in _git(site, "log", "-1", "--format=%s")
