"""Tests for v15.H — bootstrap stack normalization via Claude subprocess.

Coverage:
  - `detect_stack()` unit tests per known stack
  - `validate_translation()` unit tests (ok + each failure path)
  - `translate_to_astro()` orchestration with mocked `run_claude`
  - bootstrap.py hook integration (via mocked Claude)
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from portfolio.fix_helpers import ClaudeResult
from portfolio.stack_translate import (
    STACK_ASTRO,
    STACK_NEXTJS,
    STACK_SVELTEKIT,
    STACK_TANSTACK,
    STACK_UNKNOWN,
    STACK_VITE_REACT,
    StackTranslationError,
    detect_stack,
    translate_to_astro,
    validate_translation,
)


def _write_pkg(genai_dir: Path, deps: dict, dev_deps: dict | None = None) -> None:
    genai_dir.mkdir(parents=True, exist_ok=True)
    pkg = {"name": "test", "version": "0.0.1", "dependencies": deps}
    if dev_deps:
        pkg["devDependencies"] = dev_deps
    (genai_dir / "package.json").write_text(json.dumps(pkg, indent=2))


# ---- detect_stack ------------------------------------------------


def test_detect_astro(tmp_path):
    g = tmp_path / "genai"
    _write_pkg(g, {"astro": "^5.0.0"})
    (g / "astro.config.mjs").write_text("export default {}")
    d = detect_stack(g)
    assert d.stack == STACK_ASTRO
    assert "dependency:astro" in d.signals
    assert "config:astro.config" in d.signals


def test_detect_astro_without_config_still_astro(tmp_path):
    """Astro dep alone is sufficient — config absence is a downstream
    validator concern, not a detector concern."""
    g = tmp_path / "genai"
    _write_pkg(g, {"astro": "^5.0.0"})
    d = detect_stack(g)
    assert d.stack == STACK_ASTRO


def test_detect_sveltekit_via_dep(tmp_path):
    g = tmp_path / "genai"
    _write_pkg(g, {"@sveltejs/kit": "^2.0.0"})
    assert detect_stack(g).stack == STACK_SVELTEKIT


def test_detect_sveltekit_via_config_only(tmp_path):
    """svelte.config.js alone (no @sveltejs/kit dep) still flags as
    SvelteKit — covers the case of malformed package.json."""
    g = tmp_path / "genai"
    g.mkdir()
    (g / "svelte.config.js").write_text("export default {}")
    assert detect_stack(g).stack == STACK_SVELTEKIT


def test_detect_nextjs(tmp_path):
    g = tmp_path / "genai"
    _write_pkg(g, {"next": "^14.0.0"})
    assert detect_stack(g).stack == STACK_NEXTJS


def test_detect_tanstack_start(tmp_path):
    """The canonical case — Lovable export with TanStack Start +
    Cloudflare Workers via @cloudflare/vite-plugin."""
    g = tmp_path / "genai"
    _write_pkg(g, {
        "@tanstack/react-start": "^0.1.0",
        "@cloudflare/vite-plugin": "^1.0.0",
        "react": "^19.0.0",
    })
    (g / "src").mkdir()
    (g / "src" / "server.ts").write_text("export default {}")
    d = detect_stack(g)
    assert d.stack == STACK_TANSTACK
    assert any("tanstack" in s for s in d.signals)
    assert "file:src/server.ts" in d.signals


def test_detect_tanstack_without_server_file(tmp_path):
    """Multi-tanstack-package exports without an SSR server still
    flag as TanStack."""
    g = tmp_path / "genai"
    _write_pkg(g, {"@tanstack/react-router": "^1.0.0"})
    assert detect_stack(g).stack == STACK_TANSTACK


def test_detect_vite_react(tmp_path):
    g = tmp_path / "genai"
    _write_pkg(g, {"vite": "^6.0.0", "react": "^19.0.0"})
    d = detect_stack(g)
    assert d.stack == STACK_VITE_REACT


def test_detect_vite_without_react_is_unknown(tmp_path):
    """`vite` alone (no react, no astro) doesn't satisfy the
    vite-react case — operator gets `unknown` so they decide."""
    g = tmp_path / "genai"
    _write_pkg(g, {"vite": "^6.0.0"})
    assert detect_stack(g).stack == STACK_UNKNOWN


def test_detect_missing_genai_dir(tmp_path):
    """Caller may pass a path that doesn't exist — detector handles
    gracefully."""
    d = detect_stack(tmp_path / "does-not-exist")
    assert d.stack == STACK_UNKNOWN
    assert "genai_dir_missing" in d.signals


def test_detect_empty_genai_dir(tmp_path):
    g = tmp_path / "genai"
    g.mkdir()
    d = detect_stack(g)
    assert d.stack == STACK_UNKNOWN


def test_detect_invalid_package_json(tmp_path):
    """Malformed package.json shouldn't crash; detector records the
    signal + falls through to unknown."""
    g = tmp_path / "genai"
    g.mkdir()
    (g / "package.json").write_text("{ not json")
    d = detect_stack(g)
    assert d.stack == STACK_UNKNOWN
    assert "package_json_unreadable" in d.signals


def test_detect_dev_dependencies_count(tmp_path):
    """Deps in devDependencies still count for detection."""
    g = tmp_path / "genai"
    _write_pkg(g, deps={}, dev_deps={"astro": "^5.0.0"})
    assert detect_stack(g).stack == STACK_ASTRO


# ---- validate_translation ---------------------------------------


def _scaffold_valid_astro(project_dir: Path):
    """Build a minimally-valid Astro+Vite layout to exercise the
    validator's happy path."""
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "package.json").write_text(json.dumps({
        "name": "test", "version": "0.0.1",
        "dependencies": {"astro": "^5.0.0", "vite": "^6.0.0"},
    }))
    (project_dir / "astro.config.mjs").write_text("export default {}")
    (project_dir / "src" / "pages").mkdir(parents=True)
    (project_dir / "src" / "pages" / "index.astro").write_text("---\n---\n<h1>Hi</h1>")


def test_validate_happy_path(tmp_path):
    _scaffold_valid_astro(tmp_path)
    r = validate_translation(tmp_path)
    assert r.ok
    assert r.issues == []


def test_validate_missing_package_json(tmp_path):
    (tmp_path / "astro.config.mjs").write_text("")
    (tmp_path / "src" / "pages").mkdir(parents=True)
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("package.json" in i for i in r.issues)


def test_validate_missing_astro_dep(tmp_path):
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test", "dependencies": {"react": "^19.0.0"},
    }))
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("missing 'astro'" in i for i in r.issues)


def test_validate_banned_tanstack_dep(tmp_path):
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "dependencies": {
            "astro": "^5.0.0",
            "@tanstack/react-start": "^0.1.0",
        },
    }))
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("@tanstack/react-start" in i for i in r.issues)


def test_validate_banned_next_dep_exact_match_only(tmp_path):
    """The validator's 'next' check matches the exact dep name, NOT
    every package starting with 'next' (e.g. `next-themes` is fine)."""
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "dependencies": {
            "astro": "^5.0.0",
            "next-themes": "^0.4.0",  # NOT banned
        },
    }))
    r = validate_translation(tmp_path)
    assert r.ok, r.issues


def test_validate_banned_next_dep_exact_hit(tmp_path):
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "dependencies": {
            "astro": "^5.0.0",
            "next": "^14.0.0",
        },
    }))
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("'next'" in i for i in r.issues)


def test_validate_banned_sveltekit_dep(tmp_path):
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "test",
        "dependencies": {
            "astro": "^5.0.0",
            "@sveltejs/kit": "^2.0.0",
        },
    }))
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("@sveltejs/" in i for i in r.issues)


def test_validate_missing_astro_config(tmp_path):
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "astro.config.mjs").unlink()
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("astro.config" in i for i in r.issues)


def test_validate_missing_src_pages(tmp_path):
    _scaffold_valid_astro(tmp_path)
    # Remove src/pages.
    (tmp_path / "src" / "pages" / "index.astro").unlink()
    (tmp_path / "src" / "pages").rmdir()
    r = validate_translation(tmp_path)
    assert not r.ok
    assert any("src/pages/" in i for i in r.issues)


def test_validate_wrangler_jsonc_allowed(tmp_path):
    """v15.M removed the v15.H 'no wrangler.jsonc' check — bootstrap
    legitimately writes one as part of CF safety fixes."""
    _scaffold_valid_astro(tmp_path)
    (tmp_path / "wrangler.jsonc").write_text("{}")
    r = validate_translation(tmp_path)
    assert r.ok, r.issues
    assert not any("wrangler.jsonc" in i for i in r.issues)


# ---- translate_to_astro orchestration ----------------------------


def test_translate_returns_claude_unavailable(tmp_path):
    """When `claude` CLI isn't on PATH, bail with a clear error."""
    with patch("portfolio.stack_translate.claude_available", return_value=False):
        result = translate_to_astro(
            tmp_path,
            detection=type("D", (), {"stack": STACK_TANSTACK, "signals": ["dependency:@tanstack/react-start"]})(),
        )
    assert not result.ok
    assert result.error == "claude-not-found"
    assert "Claude Code installed locally" in result.raw_output


def test_translate_passes_through_run_claude_result(tmp_path):
    """The wrapper just forwards `run_claude`'s ClaudeResult."""
    fake = ClaudeResult(ok=True, cost_usd=0.12, duration_s=42.0, error=None, raw_output="")
    with patch("portfolio.stack_translate.claude_available", return_value=True), \
         patch("portfolio.stack_translate.run_claude", return_value=fake) as run_mock:
        result = translate_to_astro(
            tmp_path,
            detection=type("D", (), {"stack": STACK_TANSTACK, "signals": ["dependency:@tanstack/react-router"]})(),
        )
    assert result is fake
    # Verify run_claude was called with the right cwd.
    args, kwargs = run_mock.call_args
    assert kwargs.get("cwd") == tmp_path
    # And the prompt mentions the detected stack.
    assert "tanstack-start" in args[0]


def test_translate_prompt_includes_detection_signals(tmp_path):
    captured = {}

    def fake_run(prompt, **kw):
        captured["prompt"] = prompt
        return ClaudeResult(ok=True, cost_usd=0.0, duration_s=0.0, error=None, raw_output="")

    detection = type("D", (), {
        "stack": STACK_NEXTJS,
        "signals": ["dependency:next", "dependency:react"],
    })()
    with patch("portfolio.stack_translate.claude_available", return_value=True), \
         patch("portfolio.stack_translate.run_claude", side_effect=fake_run):
        translate_to_astro(tmp_path, detection=detection)

    assert "dependency:next" in captured["prompt"]
    assert "dependency:react" in captured["prompt"]
    # Translation contract is in the prompt body.
    assert "Astro" in captured["prompt"]
    assert "wrangler.jsonc" in captured["prompt"]  # explicit do-NOT-write list
    assert "pnpm" in captured["prompt"]
