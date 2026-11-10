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
                             is_live=lambda d, b: live, account_of=lambda ga: account)


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
