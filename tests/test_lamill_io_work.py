"""Tests for lamill_io_work — auto-linking new sites from the lamill.io hub."""
from __future__ import annotations

from types import SimpleNamespace

import portfolio.lamill_io_work as liw


def _work_dir(tmp_path):
    d = tmp_path / "lamill.io" / "src" / "content" / "work"
    d.mkdir(parents=True)
    return d


def test_slug_for():
    assert liw.slug_for("drdebug.dev") == "drdebug"
    assert liw.slug_for("cottagefoodmap.com") == "cottagefoodmap"
    assert liw.slug_for("isitholiday.today") == "isitholiday"
    assert liw.slug_for("real-pay.xyz") == "real-pay"


def test_creates_draft_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    _work_dir(tmp_path)
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03")
    assert res.status == "created"
    txt = res.path.read_text()
    assert 'slug: "drdebug"' in txt
    assert 'url: "https://drdebug.dev/"' in txt
    assert 'status: "draft"' in txt          # never auto-publishes
    assert 'date: "2026-07-03"' in txt
    assert 'import type { WorkEntry }' in txt


def test_idempotent_no_clobber(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    wd = _work_dir(tmp_path)
    (wd / "drdebug.ts").write_text("// hand-authored, keep me")
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03")
    assert res.status == "exists"
    assert (wd / "drdebug.ts").read_text() == "// hand-authored, keep me"


def test_dry_run_writes_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    wd = _work_dir(tmp_path)
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03", dry_run=True)
    assert res.status == "dry-run"
    assert not (wd / "drdebug.ts").exists()


def test_no_lamill_io_repo(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)  # no lamill.io/ dir
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03")
    assert res.status == "no-lamill-io"


def test_stack_chips_from_framework(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    _work_dir(tmp_path)
    import portfolio.lamill_toml as lt
    monkeypatch.setattr(
        lt, "load",
        lambda p: SimpleNamespace(stack=SimpleNamespace(framework="astro")),
    )
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03")
    assert 'stack: ["Astro"]' in res.path.read_text()


def test_stack_empty_when_no_toml(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    _work_dir(tmp_path)
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03")
    assert "stack: []" in res.path.read_text()


def test_title_override(tmp_path, monkeypatch):
    monkeypatch.setattr(liw, "SITES_ROOT", tmp_path)
    _work_dir(tmp_path)
    res = liw.add_work_entry("drdebug.dev", date="2026-07-03", title="DrDebug")
    assert 'title: "DrDebug"' in res.path.read_text()
