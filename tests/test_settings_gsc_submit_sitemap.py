"""`lamill settings gsc submit-sitemap --site <domain>` — the thin GSC
sitemap (re)submit command. Mocks gsc_admin so no real GSC calls happen.
"""
from __future__ import annotations

import pytest
from typer.testing import CliRunner

import portfolio.cli as climod
import portfolio.gsc_admin as gsc_admin
from portfolio.gsc_admin import GSCAdminError

runner = CliRunner()


@pytest.fixture(autouse=True)
def _stub_gsc(monkeypatch):
    monkeypatch.setattr(gsc_admin, "resolve_sitemap_url",
                        lambda d, **k: f"https://{d}/sitemap.xml")
    monkeypatch.setattr(gsc_admin, "list_sitemaps", lambda d, **k: [])
    monkeypatch.setattr(gsc_admin, "delete_sitemap", lambda d, u, **k: True)
    monkeypatch.setattr(gsc_admin, "submit_sitemap", lambda d, u, **k: True)


def _run(*args):
    return runner.invoke(climod.app, ["settings", "gsc", "submit-sitemap", *args])


def test_submit_new_sitemap_succeeds():
    res = _run("--site", "airsucks.com")
    assert res.exit_code == 0
    assert "submitted" in res.output
    assert "airsucks.com/sitemap.xml" in res.output


def test_already_submitted_is_soft_skip(monkeypatch):
    monkeypatch.setattr(gsc_admin, "submit_sitemap", lambda d, u, **k: False)
    res = _run("--site", "airsucks.com")
    assert res.exit_code == 0
    assert "already submitted" in res.output
    assert "--force" in res.output            # hints the re-fetch path


def test_force_deletes_then_resubmits(monkeypatch):
    calls = {"deleted": 0}
    monkeypatch.setattr(gsc_admin, "list_sitemaps",
                        lambda d, **k: [{"path": f"https://{d}/sitemap.xml"}])
    monkeypatch.setattr(gsc_admin, "delete_sitemap",
                        lambda d, u, **k: calls.__setitem__("deleted", calls["deleted"] + 1))
    res = _run("--site", "airsucks.com", "--force")
    assert res.exit_code == 0
    assert calls["deleted"] == 1              # existing entry was removed first
    assert "submitted" in res.output


def test_url_override_skips_resolve(monkeypatch):
    seen = {}
    monkeypatch.setattr(gsc_admin, "submit_sitemap",
                        lambda d, u, **k: seen.update(url=u) or True)
    res = _run("--site", "x.com", "--url", "https://x.com/custom.xml")
    assert res.exit_code == 0
    assert seen["url"] == "https://x.com/custom.xml"


def test_gsc_error_exits_2(monkeypatch):
    def _boom(d, u, **k):
        raise GSCAdminError("insufficient_scope: OAuth token missing webmasters write")
    monkeypatch.setattr(gsc_admin, "submit_sitemap", _boom)
    res = _run("--site", "airsucks.com")
    assert res.exit_code == 2
    assert "insufficient_scope" in res.output
