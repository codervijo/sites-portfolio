"""BUG-103 — same-stem domains must not share a CF project slug."""
from __future__ import annotations

import json

from portfolio.cf_slug import (
    find_slug_collisions,
    legacy_project_name,
    new_project_name,
    resolve_slug,
)

LAMILL_TOML = 'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "{platform}"\n'


def _site(root, domain, *, name=None, platform="cf-workers"):
    d = root / domain
    d.mkdir()
    (d / "lamill.toml").write_text(LAMILL_TOML.format(platform=platform))
    if name is not None:
        (d / "wrangler.jsonc").write_text(
            "// generated\n" + json.dumps({"name": name, "compatibility_date": "2026-01-01"})
        )
    return d


def test_new_name_keeps_tld():
    assert new_project_name("lamill.store") != new_project_name("lamill.pics")
    assert new_project_name("lamill.store") == "lamill-store"


def test_resolve_prefers_wrangler_name(tmp_path):
    d = _site(tmp_path, "kwizicle.com", name="kwizicle")
    assert resolve_slug(d, "kwizicle.com") == "kwizicle"  # existing site unchanged


def test_resolve_without_wrangler_uses_legacy(tmp_path):
    d = _site(tmp_path, "voltloop.site")
    assert resolve_slug(d, "voltloop.site") == legacy_project_name("voltloop.site") == "voltloop"


def test_collision_detected_for_same_stem(tmp_path):
    _site(tmp_path, "lamill.pics", name="lamill")
    _site(tmp_path, "lamill.store", name="lamill")
    assert find_slug_collisions("lamill.store", "lamill", tmp_path) == ["lamill.pics"]


def test_no_collision_after_rename(tmp_path):
    _site(tmp_path, "lamill.pics", name="lamill")
    _site(tmp_path, "lamill.store", name="lamill-store")
    assert find_slug_collisions("lamill.store", "lamill-store", tmp_path) == []


def test_non_cf_sites_ignored(tmp_path):
    _site(tmp_path, "lamill.io", name="lamill", platform="vercel")
    assert find_slug_collisions("lamill.store", "lamill", tmp_path) == []


def test_missing_sites_root(tmp_path):
    assert find_slug_collisions("x.com", "x", tmp_path / "nope") == []
