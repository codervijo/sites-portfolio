"""Tests for CHECK_081 — no AI-builder placeholder metadata/cruft."""
from __future__ import annotations

from portfolio.checks.seo.check_081_no_placeholder_metadata import (
    fix_tier_2,
    run,
)
from portfolio.fix_helpers import FixerSpec


def _web(tmp_path):
    """Make tmp_path look like a web project (CHECK gate = package.json)."""
    (tmp_path / "package.json").write_text('{"name": "x"}')
    return tmp_path


def test_pass_on_clean_web_project(tmp_path):
    _web(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.tsx").write_text("export const x = 1;")
    assert run(str(tmp_path)).status == "pass"


def test_skips_non_web_project(tmp_path):
    # No package.json → not a web project.
    assert run(str(tmp_path)).status == "warn"


def test_detects_placeholder_in_ssr_head_code(tmp_path):
    """The core case: head lives in a route file (TanStack Start), NOT
    index.html — exactly what CHECK_070/071 miss (docs/bugs.md 2026-06-29)."""
    _web(tmp_path)
    routes = tmp_path / "src" / "routes"
    routes.mkdir(parents=True)
    (routes / "__root.tsx").write_text(
        'head: () => ({ meta: [{ title: "Lovable App" }] })'
    )
    r = run(str(tmp_path))
    assert r.status == "fail"
    assert "Lovable App" in r.message
    assert "__root.tsx" in r.message


def test_detects_placeholder_in_index_html(tmp_path):
    _web(tmp_path)
    (tmp_path / "index.html").write_text("<title>Lovable App</title>")
    assert run(str(tmp_path)).status == "fail"


def test_detects_lovable_tagger_dep_in_package_json(tmp_path):
    (tmp_path / "package.json").write_text(
        '{"devDependencies": {"lovable-tagger": "^1.2.0"}}'
    )
    r = run(str(tmp_path))
    assert r.status == "fail"
    assert "lovable-tagger" in r.message


def test_detects_twitter_handle(tmp_path):
    _web(tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "head.ts").write_text(
        'meta: [{ name: "twitter:site", content: "@Lovable" }]'
    )
    assert run(str(tmp_path)).status == "fail"


def test_ignores_build_output(tmp_path):
    """Cruft only in dist/.output (build artifacts) must not fail a clean source."""
    _web(tmp_path)
    out = tmp_path / ".output" / "server"
    out.mkdir(parents=True)
    (out / "bundle.mjs").write_text('title: "Lovable App"')
    # .output isn't under src/ and isn't a top-level scanned file → ignored.
    assert run(str(tmp_path)).status == "pass"


def test_tier2_fixer_registered_and_dry_run_is_noop(tmp_path):
    assert isinstance(fix_tier_2, FixerSpec)
    assert fix_tier_2.tier == 2
    res = fix_tier_2.apply(tmp_path, True, False)  # dry_run=True
    assert res.status == "would-fix"
