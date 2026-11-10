"""v49.H — new sites ship with the GA4 tag (bootstrap + `new site` step)."""
from __future__ import annotations

import subprocess
from pathlib import Path

from portfolio import fleet_ga

GA = "G-NEWSITE123"
TOML = f'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n[analytics]\nga4_id = "{GA}"\n'
LAYOUT = "---\nconst x = 1;\n---\n<html>\n  <head>\n    <title>x</title>\n  </head>\n</html>\n"


def _git(d: Path, *a: str) -> str:
    return subprocess.run(["git", *a], cwd=d, check=True, capture_output=True, text=True).stdout


def _site(tmp_path: Path, toml: str = TOML) -> Path:
    d = tmp_path / "new.test"
    (d / "src/layouts").mkdir(parents=True)
    (d / "package.json").write_text("{}")
    (d / "lamill.toml").write_text(toml)
    (d / "src/layouts/Layout.astro").write_text(LAYOUT)
    _git(d.parent, "init", "-q", "-b", "main", str(d))
    _git(d, "config", "user.email", "t@t"); _git(d, "config", "user.name", "t")
    _git(d, "add", "-A"); _git(d, "commit", "-qm", "init")
    return d


def test_tags_and_commits_only_touched_files_locally(tmp_path):
    d = _site(tmp_path)
    (d / "notes.txt").write_text("wip")
    kind, msg, touched = fleet_ga.tag_new_site(d, commit=True)
    assert kind == "ok" and GA in msg
    assert sorted(touched) == ["src/components/Analytics.astro", "src/layouts/Layout.astro"]
    assert sorted(_git(d, "show", "--name-only", "--format=", "HEAD").split()) == sorted(touched)
    assert "notes.txt" in _git(d, "status", "--porcelain")


def test_already_tagged_is_ok_without_commit(tmp_path):
    d = _site(tmp_path)
    fleet_ga.tag_new_site(d, commit=True)
    head = _git(d, "rev-parse", "HEAD")
    kind, msg, touched = fleet_ga.tag_new_site(d, commit=True)
    assert (kind, touched) == ("ok", []) and _git(d, "rev-parse", "HEAD") == head


def test_no_recorded_id_skips_with_fleet_hint(tmp_path):
    d = _site(tmp_path, TOML.split("[analytics]")[0])
    kind, msg, _ = fleet_ga.tag_new_site(d, commit=True)
    assert kind == "skip" and "fleet ga --only new.test --apply" in msg


def test_dirty_touched_file_is_restored(tmp_path):
    d = _site(tmp_path)
    (d / "src/layouts/Layout.astro").write_text(LAYOUT + "<!-- wip -->\n")
    kind, msg, _ = fleet_ga.tag_new_site(d, commit=True)
    assert kind == "err" and "uncommitted" in msg
    assert (d / "src/layouts/Layout.astro").read_text() == LAYOUT + "<!-- wip -->\n"
    assert not (d / "src/components/Analytics.astro").exists()


def test_bootstrap_ships_tag_in_initial_tree(monkeypatch, tmp_path):
    from portfolio import bootstrap, ga4_admin
    from portfolio.checks.seo import check_163_ga4_tag_in_source as c163
    monkeypatch.setattr("portfolio.bootstrap._git_init_and_commit", lambda project_dir, msg: (True, "0123456"))
    monkeypatch.setattr(ga4_admin, "has_token", lambda: True)
    monkeypatch.setattr("portfolio.apikeys.get_key", lambda k: "42" if k == "GA4_ACCOUNT_ID" else None)
    monkeypatch.setattr(ga4_admin, "stream_index", lambda **kw: [])
    monkeypatch.setattr(ga4_admin, "set_data_retention", lambda *a, **kw: False)
    import httpx
    monkeypatch.setattr(ga4_admin, "_client", lambda client=None: httpx.Client(
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="offline"))))
    monkeypatch.setattr(ga4_admin, "create_property", lambda account_id, display_name, **kw: "111")
    monkeypatch.setattr(ga4_admin, "create_web_stream", lambda property_id, default_uri, **kw: ("s", GA))
    sites = tmp_path / "sites"; sites.mkdir()
    r = bootstrap.bootstrap("newsite.dev", stack="astro", operator_inputs={}, today_iso="2026-11-09", sites_root=sites)
    assert r.ga4_measurement_id == GA
    assert r.ga4_tag and r.ga4_tag[0] == "ok", r.ga4_tag
    assert GA in c163.source_ids(r.project_dir)


def test_bootstrap_without_ga4_does_not_tag(monkeypatch, tmp_path):
    from portfolio import bootstrap
    monkeypatch.setattr("portfolio.bootstrap._git_init_and_commit", lambda project_dir, msg: (True, "0123456"))
    sites = tmp_path / "sites"; sites.mkdir()
    r = bootstrap.bootstrap("newsite.dev", stack="astro", operator_inputs={}, today_iso="2026-11-09",
                            sites_root=sites, skip_ga4=True)
    assert r.ga4_tag is None
