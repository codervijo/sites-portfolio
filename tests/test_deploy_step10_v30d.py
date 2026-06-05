"""v30.D — deploy Step 10 IndexNow hook (`_deploy_step10_indexnow`)."""
from __future__ import annotations

import pytest

from portfolio import indexnow
from portfolio.cli import _deploy_step10_indexnow
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

_BASE = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(indexnow, "INDEX_DIR", tmp_path / "_idx")


def _site(tmp_path, *, index=True, key="abc123", enabled=True):
    idx = (f'\n[index]\nindexnow_key = "{key}"\n'
           f'indexnow_enabled = {"true" if enabled else "false"}\n') if index else ""
    (tmp_path / LAMILL_TOML_FILENAME).write_text(_BASE + idx)
    return tmp_path


def test_step10_no_index_is_noop(tmp_path, monkeypatch):
    _site(tmp_path, index=False)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls",
                        lambda *a, **k: pytest.fail("must not touch indexnow when unprovisioned"))
    _deploy_step10_indexnow(domain="example.com", project_dir=tmp_path, dry_run=False)


def test_step10_dry_run_no_submit(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "submit_urls", lambda *a, **k: pytest.fail("no submit in dry-run"))
    _deploy_step10_indexnow(domain="example.com", project_dir=tmp_path, dry_run=True)


def test_step10_pings_and_ledgers(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "key_is_live", lambda d, k, **kw: True)
    monkeypatch.setattr(indexnow, "fetch_sitemap_urls", lambda d, **kw: ["https://example.com/a"])
    sent = {}
    monkeypatch.setattr(indexnow, "submit_urls",
                        lambda domain, key, urls, **kw: sent.update(urls=urls) or len(urls))
    _deploy_step10_indexnow(domain="example.com", project_dir=tmp_path, dry_run=False)
    assert sent["urls"] == ["https://example.com/a"]
    assert "https://example.com/a" in indexnow.ledger_urls("example.com")


def test_step10_key_not_live_skips(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "key_is_live", lambda d, k, **kw: False)
    monkeypatch.setattr(indexnow, "submit_urls",
                        lambda *a, **k: pytest.fail("must not submit when key not live"))
    _deploy_step10_indexnow(domain="example.com", project_dir=tmp_path, dry_run=False)


def test_step10_soft_fails_on_exception(tmp_path, monkeypatch):
    _site(tmp_path)
    monkeypatch.setattr(indexnow, "key_is_live",
                        lambda d, k, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    _deploy_step10_indexnow(domain="example.com", project_dir=tmp_path, dry_run=False)  # no raise
