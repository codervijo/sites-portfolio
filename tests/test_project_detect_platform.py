"""Tests for `project.detect_platform()` — covers the 2026-05-21
fix where lamill.toml `[deploy].platform` is now consulted first,
ahead of marker-based inference.

Background: cf-workers sites carry a `wrangler.jsonc` for local
`wrangler dev`, which matched the `("cloudflare-pages", "wrangler.jsonc")`
marker and made the `project check` deploy summary render
`cloudflare-pages` for an operator-declared cf-workers site. The
fix reads `lamill.toml` first so the operator's declaration wins.
"""
from __future__ import annotations

from pathlib import Path

from portfolio.project import detect_platform


def _make_lamill_toml(project_dir: Path, platform: str) -> None:
    (project_dir / "lamill.toml").write_text(
        f'schema = "lamill-toml-v1"\n\n'
        f'[deploy]\nplatform = "{platform}"\n'
    )


def _make_astro_project(project_dir: Path) -> None:
    (project_dir / "package.json").write_text(
        '{"name": "test", "scripts": {"build": "astro build"},'
        ' "dependencies": {"astro": "^5.0.0"}}'
    )


# ---- lamill.toml wins over markers -----------------------------------


def test_lamill_toml_cf_workers_beats_wrangler_jsonc_marker(tmp_path):
    """The disclosur.dev-style case: project has both wrangler.jsonc
    (for local dev) and lamill.toml declaring cf-workers. Output
    must be cloudflare-workers, not cloudflare-pages."""
    _make_astro_project(tmp_path)
    (tmp_path / "wrangler.jsonc").write_text("{}")
    _make_lamill_toml(tmp_path, "cf-workers")

    result = detect_platform(tmp_path)

    assert result["platform"] == "cloudflare-workers"
    assert "lamill.toml:[deploy].platform" in result["evidence"]


def test_lamill_toml_cf_pages_beats_marker(tmp_path):
    """Declared cf-pages → cloudflare-pages (matches marker output,
    but the lamill.toml evidence trail is what the operator sees)."""
    _make_astro_project(tmp_path)
    (tmp_path / "wrangler.jsonc").write_text("{}")
    _make_lamill_toml(tmp_path, "cf-pages")

    result = detect_platform(tmp_path)

    assert result["platform"] == "cloudflare-pages"
    assert result["evidence"][0] == "lamill.toml:[deploy].platform"


def test_lamill_toml_vercel(tmp_path):
    _make_astro_project(tmp_path)
    _make_lamill_toml(tmp_path, "vercel")
    assert detect_platform(tmp_path)["platform"] == "vercel"


def test_lamill_toml_netlify(tmp_path):
    _make_astro_project(tmp_path)
    _make_lamill_toml(tmp_path, "netlify")
    assert detect_platform(tmp_path)["platform"] == "netlify"


def test_lamill_toml_hostgator(tmp_path):
    """`platform = "hostgator"` requires a `[hosting]` section per
    HOSTING_REQUIRED_PLATFORMS; both must be present for the
    declaration to load cleanly."""
    _make_astro_project(tmp_path)
    (tmp_path / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n'
        '[deploy]\nplatform = "hostgator"\n\n'
        '[hosting]\ncpanel_user = "user"\n'
    )
    assert detect_platform(tmp_path)["platform"] == "hostgator"


# ---- fall-through behavior (no lamill.toml or malformed) -------------


def test_no_lamill_toml_falls_through_to_markers(tmp_path):
    """Without lamill.toml the legacy marker-based detection runs.
    wrangler.jsonc → cloudflare-pages (the pre-fix behavior, still
    valid for projects that haven't adopted the declaration file)."""
    _make_astro_project(tmp_path)
    (tmp_path / "wrangler.jsonc").write_text("{}")

    result = detect_platform(tmp_path)

    assert result["platform"] == "cloudflare-pages"
    assert "wrangler.jsonc" in result["evidence"]
    assert not any("lamill.toml" in e for e in result["evidence"])


def test_malformed_lamill_toml_falls_through_to_markers(tmp_path):
    """ParseError → silently fall through. The validator surface for
    lamill.toml errors lives elsewhere (CHECK_109 etc.); detect_platform
    must not crash the deploy summary."""
    _make_astro_project(tmp_path)
    (tmp_path / "lamill.toml").write_text("this is not valid toml { [[[")
    (tmp_path / "vercel.json").write_text("{}")

    result = detect_platform(tmp_path)

    # Marker fallback fires.
    assert result["platform"] == "vercel"


def test_lamill_toml_platform_none_falls_through_to_markers(tmp_path):
    """`platform = "none"` means no deployment declared — fall through
    so marker-based detection can still surface something useful."""
    _make_astro_project(tmp_path)
    _make_lamill_toml(tmp_path, "none")
    (tmp_path / "vercel.json").write_text("{}")

    result = detect_platform(tmp_path)

    assert result["platform"] == "vercel"
