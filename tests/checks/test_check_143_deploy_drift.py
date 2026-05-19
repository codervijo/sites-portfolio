"""Tests for CHECK_143 — deploy-drift (v10.E)."""
from __future__ import annotations

import json
from pathlib import Path

from portfolio.checks.deploy.check_143_deploy_drift import (
    _classify_actual_platform,
    run,
)


# ---- helpers --------------------------------------------------------


def _write_lamill_toml(site: Path, platform: str, **extra) -> None:
    """Write a minimal-but-valid lamill.toml. `extra` lets a test add
    platform-specific scaffolding (e.g. the [hosting] block hostgator
    requires)."""
    body = [
        'schema = "lamill-toml-v1"',
        "",
        "[deploy]",
        f'platform = "{platform}"',
    ]
    for k, v in extra.items():
        if k == "hosting" and v:
            body.append("")
            body.append("[hosting]")
            for hk, hv in v.items():
                body.append(f'{hk} = "{hv}"')
    site.joinpath("lamill.toml").write_text("\n".join(body) + "\n")


def _stub_snapshot(tmp_path: Path, results: list[dict]) -> Path:
    checks_dir = tmp_path / "data" / "checks"
    checks_dir.mkdir(parents=True)
    out = checks_dir / "2026-05-18.json"
    out.write_text(json.dumps({
        "fetched_at": "2026-05-18T00:00:00+00:00",
        "scope": "wip",
        "results": results,
    }))
    return out


def _patch_snapshot(monkeypatch, tmp_path: Path, results: list[dict] | None):
    from portfolio import check as check_mod
    if results is None:
        monkeypatch.setattr(check_mod, "latest_snapshot", lambda: None)
        return None
    snap = _stub_snapshot(tmp_path, results)
    monkeypatch.setattr(check_mod, "latest_snapshot", lambda: snap)
    return snap


def _make_site(tmp_path: Path, name: str) -> Path:
    site = tmp_path / name
    site.mkdir()
    return site


# ---- classifier unit tests -----------------------------------------


def test_classifier_detects_wordpress_generator():
    row = {
        "body_excerpt": (
            '<!DOCTYPE html><html><head>'
            '<meta name="generator" content="WordPress 6.7" />'
        ),
        "final_url": "https://iotnews.today",
    }
    platform, signal = _classify_actual_platform(row)
    assert platform == "hostgator"
    assert "WordPress" in (signal or "")


def test_classifier_detects_wordpress_error_page_title():
    """The iotnews.today 2026-05-18 case — half-installed WP serves an
    error page whose body excerpt cuts off before the generator meta but
    still contains `<title>WordPress &rsaquo; Error</title>`."""
    row = {
        "body_excerpt": (
            '<!DOCTYPE html><html><head>'
            '<meta name="robots" content="noindex" />'
            '<title>WordPress &rsaquo; Error</title>'
        ),
        "final_url": "https://iotnews.today",
    }
    platform, _ = _classify_actual_platform(row)
    assert platform == "hostgator"


def test_classifier_detects_wp_includes_path():
    """wp-includes / wp-content / wp-admin appear in server-rendered
    HTML on every WP page (in `<link>` / `<script>` refs)."""
    row = {
        "body_excerpt": (
            '<html><head>'
            "<link rel='stylesheet' href='https://example.com/wp-includes/css/style.css'>"
        ),
        "final_url": "https://example.com",
    }
    platform, _ = _classify_actual_platform(row)
    assert platform == "hostgator"


def test_classifier_detects_pages_dev_in_final_url():
    row = {
        "body_excerpt": "",
        "final_url": "https://example-com.pages.dev/",
    }
    platform, signal = _classify_actual_platform(row)
    assert platform == "cf-pages"
    assert ".pages.dev" in (signal or "")


def test_classifier_detects_vercel_app_in_redirect_chain():
    row = {
        "body_excerpt": "",
        "final_url": "https://example.com",
        "redirect_chain": ["https://example-com.vercel.app/"],
    }
    platform, signal = _classify_actual_platform(row)
    assert platform == "vercel"


def test_classifier_returns_none_when_no_signal():
    row = {"body_excerpt": "<html><body>hi</body></html>",
           "final_url": "https://example.com"}
    platform, signal = _classify_actual_platform(row)
    assert platform is None
    assert signal is None


def test_classifier_wordpress_wins_over_provider_host():
    """Defensive — WP HTML served from a *.vercel.app preview URL is the
    iotnews.today case in extremis. WP generator should still win since
    it's a stronger 'what's actually running here' signal."""
    row = {
        "body_excerpt": '<meta name="generator" content="WordPress 6.7">',
        "final_url": "https://something.pages.dev/",
    }
    platform, _ = _classify_actual_platform(row)
    assert platform == "hostgator"


# ---- end-to-end run() tests ----------------------------------------


def test_pass_when_declared_matches_actual_cf_pages(tmp_path: Path, monkeypatch):
    site = _make_site(tmp_path, "example.com")
    _write_lamill_toml(site, "cf-pages")
    _patch_snapshot(monkeypatch, tmp_path, [
        {"domain": "example.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://example.com",
         "redirect_chain": ["https://example-com.pages.dev/"],
         "body_excerpt": ""},
    ])
    result = run(str(site))
    assert result.status == "pass"
    assert "cf-pages" in result.message


def test_fail_when_declared_vercel_but_actual_is_wordpress(tmp_path: Path, monkeypatch):
    """The canonical iotnews.today drift case from the v10.D handoff."""
    site = _make_site(tmp_path, "iotnews.today")
    _write_lamill_toml(site, "vercel")
    _patch_snapshot(monkeypatch, tmp_path, [
        {"domain": "iotnews.today", "variant": "bare",
         "classification": "error", "status": 500,
         "final_url": "https://iotnews.today",
         "redirect_chain": [],
         "body_excerpt": '<meta name="generator" content="WordPress 6.7">'},
    ])
    result = run(str(site))
    assert result.status == "fail"
    assert "DRIFT" in result.message
    assert "vercel" in result.message
    assert "hostgator" in result.message


def test_warn_when_no_lamill_toml(tmp_path: Path, monkeypatch):
    site = _make_site(tmp_path, "example.com")
    _patch_snapshot(monkeypatch, tmp_path, [])
    result = run(str(site))
    assert result.status == "warn"
    assert "lamill.toml" in result.message


def test_warn_when_platform_is_none(tmp_path: Path, monkeypatch):
    """`platform="none"` means 'intentionally not deployed' — drift n/a."""
    site = _make_site(tmp_path, "example.com")
    _write_lamill_toml(site, "none")
    _patch_snapshot(monkeypatch, tmp_path, [
        {"domain": "example.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://example.com",
         "redirect_chain": [],
         "body_excerpt": ""},
    ])
    result = run(str(site))
    assert result.status == "warn"
    assert '"none"' in result.message


def test_warn_when_no_snapshot(tmp_path: Path, monkeypatch):
    site = _make_site(tmp_path, "example.com")
    _write_lamill_toml(site, "cf-pages")
    _patch_snapshot(monkeypatch, tmp_path, None)
    result = run(str(site))
    assert result.status == "warn"
    assert "no live snapshot" in result.message


def test_warn_when_no_row_for_domain(tmp_path: Path, monkeypatch):
    site = _make_site(tmp_path, "example.com")
    _write_lamill_toml(site, "cf-pages")
    _patch_snapshot(monkeypatch, tmp_path, [
        {"domain": "other.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://other.com", "redirect_chain": [],
         "body_excerpt": ""},
    ])
    result = run(str(site))
    assert result.status == "warn"
    assert "no row" in result.message


def test_warn_when_classifier_returns_unknown(tmp_path: Path, monkeypatch):
    """Bare apex serving plain HTML with no platform fingerprint → unknown."""
    site = _make_site(tmp_path, "example.com")
    _write_lamill_toml(site, "cf-pages")
    _patch_snapshot(monkeypatch, tmp_path, [
        {"domain": "example.com", "variant": "bare",
         "classification": "live-site", "status": 200,
         "final_url": "https://example.com",
         "redirect_chain": [],
         "body_excerpt": "<html><body>hi</body></html>"},
    ])
    result = run(str(site))
    assert result.status == "warn"
    assert "actual unknown" in result.message


def test_warn_when_lamill_toml_invalid(tmp_path: Path, monkeypatch):
    """Invalid file → drift can't be checked; CHECK_059 owns the verdict."""
    site = _make_site(tmp_path, "example.com")
    (site / "lamill.toml").write_text("garbage = not [valid")
    _patch_snapshot(monkeypatch, tmp_path, [])
    result = run(str(site))
    assert result.status == "warn"
    assert "CHECK_059" in result.message


def test_warn_when_archived(tmp_path: Path, monkeypatch):
    site = _make_site(tmp_path, "archived.example")
    (site / "TOMBSTONE.md").write_text("# archived\n")
    _write_lamill_toml(site, "cf-pages")
    _patch_snapshot(monkeypatch, tmp_path, [])
    result = run(str(site))
    assert result.status == "warn"
    assert "archived" in result.message
