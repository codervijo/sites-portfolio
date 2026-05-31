"""v27.J — `settings deploy set` (set_deploy) updates an existing
lamill.toml via surgical upsert, never a full rewrite (ADR-0018).

The regression: previously `set_deploy` rebuilt the whole file from a
partial struct and `write()`-d it, silently dropping `[stack]`,
`[[todo]]`, and the operator-authored `[content]` block. Now it upserts
only `[deploy]` / `[hosting]` and leaves the rest byte-identical.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio import lamill_toml as lt
from portfolio import lamill_toml_edit as edit
from portfolio.lamill_toml import LAMILL_TOML_FILENAME


_FULL = (
    "# header pointer line\n\n"
    'schema = "lamill-toml-v1"\n\n'
    '[deploy]\nplatform = "cf-pages"\nproduction_branch = "main"\n\n'
    '[stack]\nframework = "astro"\n\n'
    '# Tracked todos for x. status: "done" | "open".\n'
    '[[todo]]\nstatus = "open"\npriority = "high"\ntask = "do a thing"\n\n'
    "[content]\n# comment guidance\n"
    'site_type = ""            # keep me\nicp = ""\n'
)


def _site(root: Path, name: str, body: str) -> Path:
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / LAMILL_TOML_FILENAME).write_text(body)
    return d


# ---- set_table primitive --------------------------------------------


def test_set_table_replace_preserves_everything_else(tmp_path: Path):
    d = _site(tmp_path, "x", _FULL)
    edit.set_table(d, "deploy", {"platform": "vercel", "production_branch": "main"})
    doc = lt.load(d)
    text = (d / LAMILL_TOML_FILENAME).read_text()
    assert doc.deploy.platform == "vercel"
    assert doc.stack.framework == "astro"
    assert len(doc.todos) == 1
    assert "[content]" in text and "# comment guidance" in text and "keep me" in text
    assert text.startswith("# header pointer line")


def test_set_table_insert_when_absent(tmp_path: Path):
    d = _site(tmp_path, "x", _FULL)
    edit.set_table(d, "hosting", {"cpanel_user": "u", "ftp_host": "h"})
    text = (d / LAMILL_TOML_FILENAME).read_text()
    # inserted above [stack]/[[todo]]/[content], parses, content intact
    assert text.index("[hosting]") < text.index("[stack]")
    assert lt.load(d).hosting is not None
    assert "[content]" in text and "keep me" in text


def test_set_table_remove(tmp_path: Path):
    d = _site(tmp_path, "x", _FULL)
    edit.set_table(d, "hosting", {"cpanel_user": "u"})
    assert lt.load(d).hosting is not None
    edit.set_table(d, "hosting", None)
    assert lt.load(d).hosting is None
    assert "[content]" in (d / LAMILL_TOML_FILENAME).read_text()


def test_set_table_remove_absent_is_noop(tmp_path: Path):
    d = _site(tmp_path, "x", _FULL)
    before = (d / LAMILL_TOML_FILENAME).read_text()
    edit.set_table(d, "hosting", None)  # no [hosting] present
    assert (d / LAMILL_TOML_FILENAME).read_text() == before


# ---- set_deploy integration -----------------------------------------


def test_set_deploy_update_preserves_content_stack_todos(monkeypatch, tmp_path: Path):
    from portfolio import project_deploy as pd
    sites = tmp_path / "sites"
    site = _site(sites, "x.com", _FULL)
    monkeypatch.setattr(pd, "SITES_ROOT", sites)

    class _Res:
        matched = "x.com"
        candidates = ["x.com"]
    monkeypatch.setattr(pd, "resolve_project", lambda name: _Res())

    pd.set_deploy("x.com", "vercel", interactive=False,
                  custom_domains=["x.com"])

    doc = lt.load(site)
    text = (site / LAMILL_TOML_FILENAME).read_text()
    assert doc.deploy.platform == "vercel"          # updated
    assert doc.deploy.custom_domains == ["x.com"]
    assert doc.stack.framework == "astro"           # preserved
    assert len(doc.todos) == 1                       # preserved
    assert "[content]" in text and "# comment guidance" in text  # preserved
    assert "keep me" in text
