"""Tests for v27.C — `stack_classifier.classify_stack()`.

Heuristic-only; no real filesystem dependencies beyond `tmp_path`.
Each test builds the minimum on-disk shape for one detection branch
and asserts the framework + signal evidence."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from portfolio.lamill_toml import STACK_FRAMEWORK_VALUES
from portfolio.stack_classifier import (
    StackDetection,
    classify_stack,
    merged_deps,
    read_package_json,
)


# ---------- shared dep primitives (v35.C) ----------


def test_merged_deps_merges_deps_and_devdeps():
    pkg = {"dependencies": {"a": "1", "b": "2"}, "devDependencies": {"c": "3"}}
    assert merged_deps(pkg) == {"a": "1", "b": "2", "c": "3"}


def test_merged_deps_devdeps_win_on_conflict():
    pkg = {"dependencies": {"vite": "5"}, "devDependencies": {"vite": "6"}}
    assert merged_deps(pkg)["vite"] == "6"


def test_merged_deps_tolerates_missing_keys():
    assert merged_deps({}) == {}
    assert merged_deps({"dependencies": None, "devDependencies": None}) == {}


def test_read_package_json_tolerant(tmp_path: Path):
    assert read_package_json(tmp_path) == {}  # missing
    (tmp_path / "package.json").write_text("{ not json")
    assert read_package_json(tmp_path) == {}  # invalid
    (tmp_path / "package.json").write_text('{"dependencies": {"astro": "^5"}}')
    assert read_package_json(tmp_path)["dependencies"]["astro"] == "^5"


def _pkg(deps: dict[str, str] | None = None,
         dev_deps: dict[str, str] | None = None) -> dict:
    return {
        "dependencies": deps or {},
        "devDependencies": dev_deps or {},
    }


def _write_pkg(d: Path, pkg: dict) -> None:
    (d / "package.json").write_text(json.dumps(pkg))


# ---------- wordpress (highest priority) ----------


def test_detects_wordpress_via_wp_config_php(tmp_path: Path):
    (tmp_path / "wp-config.php").write_text("<?php define('DB_NAME', 'x');")
    r = classify_stack(tmp_path)
    assert r.framework == "wordpress"
    assert "file:wp-config.php" in r.signals


def test_detects_wordpress_via_wp_load_php(tmp_path: Path):
    (tmp_path / "wp-load.php").write_text("<?php")
    r = classify_stack(tmp_path)
    assert r.framework == "wordpress"


def test_detects_wordpress_via_wp_content_dir(tmp_path: Path):
    (tmp_path / "wp-content").mkdir()
    r = classify_stack(tmp_path)
    assert r.framework == "wordpress"
    assert "dir:wp-content" in r.signals


def test_wp_markers_win_over_js_markers(tmp_path: Path):
    """WordPress markers take priority — a WP site that happens to have
    a build tool config in the repo (rare but possible) is still WP."""
    (tmp_path / "wp-config.php").write_text("<?php")
    _write_pkg(tmp_path, _pkg(deps={"astro": "^5.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "wordpress"


# ---------- tanstack (uses vite under the hood) ----------


def test_detects_tanstack_when_dep_present(tmp_path: Path):
    """Tanstack Start uses Vite for the build but is a distinct
    framework choice — check before plain `vite-react`."""
    (tmp_path / "vite.config.ts").write_text("export default {};")
    _write_pkg(tmp_path, _pkg(deps={
        "@tanstack/react-start": "^1.0.0",
        "vite": "^7.0.0",
        "react": "^19.0.0",
    }))
    r = classify_stack(tmp_path)
    assert r.framework == "tanstack"


# ---------- astro ----------


def test_detects_astro_via_dep(tmp_path: Path):
    _write_pkg(tmp_path, _pkg(deps={"astro": "^5.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "astro"
    assert "dep:astro=^5.0.0" in r.signals


def test_detects_astro_via_config_when_no_vite_config(tmp_path: Path):
    (tmp_path / "astro.config.mjs").write_text("export default {};")
    r = classify_stack(tmp_path)
    assert r.framework == "astro"


# ---------- nextjs / sveltekit ----------


def test_detects_nextjs(tmp_path: Path):
    _write_pkg(tmp_path, _pkg(deps={"next": "^15.0.0", "react": "^19.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "nextjs"


def test_detects_sveltekit(tmp_path: Path):
    _write_pkg(tmp_path, _pkg(dev_deps={"@sveltejs/kit": "^2.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "sveltekit"


# ---------- vite-react ----------


def test_detects_vite_react_via_config(tmp_path: Path):
    (tmp_path / "vite.config.ts").write_text("export default {};")
    _write_pkg(tmp_path, _pkg(deps={"vite": "^6.0.0", "react": "^18.3.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "vite-react"


def test_detects_vite_react_via_deps_when_no_config(tmp_path: Path):
    _write_pkg(tmp_path, _pkg(deps={"vite": "^6.0.0", "react": "^18.3.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "vite-react"


def test_vite_alone_without_react_not_classified(tmp_path: Path):
    """Plain `vite` without `react` (e.g. a vanilla-JS Vite project)
    isn't `vite-react`; returns None for caller policy."""
    _write_pkg(tmp_path, _pkg(deps={"vite": "^6.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework is None


# ---------- ambiguity guard (lamillrentals two-config case) ----------


def test_two_configs_no_astro_dep_is_ambiguous(tmp_path: Path):
    """Both `astro.config.*` and `vite.config.*` present but no `astro`
    dep → flag for operator review (the lamillrentals.com case)."""
    (tmp_path / "astro.config.mjs").write_text("export default {};")
    (tmp_path / "vite.config.ts").write_text("export default {};")
    _write_pkg(tmp_path, _pkg(deps={"vite": "^5.0.0", "react": "^18.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework is None
    assert r.notes is not None and "operator review" in r.notes
    # Evidence preserved so the operator can see what's there.
    assert any("astro.config" in s for s in r.signals)
    assert any("vite.config" in s for s in r.signals)


def test_two_configs_with_astro_dep_resolves_to_astro(tmp_path: Path):
    """Same two configs, but with `astro` in deps — the dep is the
    definitive signal, so it's astro (the vite.config is build-tooling
    under astro)."""
    (tmp_path / "astro.config.mjs").write_text("export default {};")
    (tmp_path / "vite.config.ts").write_text("export default {};")
    _write_pkg(tmp_path, _pkg(deps={"astro": "^5.0.0"}))
    r = classify_stack(tmp_path)
    assert r.framework == "astro"


# ---------- no markers ----------


def test_no_package_json_no_markers_returns_none(tmp_path: Path):
    """A bare directory (e.g. HG-hosted WP site whose local repo has no
    files yet, or a newly-created placeholder) returns framework=None
    with a hint for the caller."""
    r = classify_stack(tmp_path)
    assert r.framework is None
    assert r.notes is not None and "caller decides" in r.notes


def test_invalid_package_json_does_not_crash(tmp_path: Path):
    """A malformed package.json is treated as absent — no crash."""
    (tmp_path / "package.json").write_text("not-json{{{")
    r = classify_stack(tmp_path)
    assert r.framework is None


# ---------- framework values stay aligned with the schema ----------


def test_classifier_outputs_match_schema_enum():
    """Every framework value the classifier can return must also be a
    valid value in `lamill_toml.STACK_FRAMEWORK_VALUES` — otherwise the
    backfill would write a value the loader rejects."""
    # Hard-coded set of frameworks the classifier can emit (matches
    # the docstring + branch labels). Keep in sync with classify_stack.
    classifier_outputs = {
        "wordpress", "tanstack", "astro", "nextjs", "sveltekit",
        "vite-react",
    }
    schema_values = set(STACK_FRAMEWORK_VALUES)
    extras = classifier_outputs - schema_values
    assert not extras, (
        f"classifier can emit {extras!r} but schema only allows "
        f"{schema_values!r}"
    )
