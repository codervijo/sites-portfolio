"""Tests for CHECK_144 — has-version-stamp (v15.C).

Uses `httpx.MockTransport` to drive the runtime fetch deterministically.
Mirrors the pattern in `tests/checks/test_seo_live.py`.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from portfolio.checks.deploy.check_144_has_version_stamp import run


def _make_web_site(tmp_path: Path, name: str = "example.com") -> Path:
    """Create a minimal repo dir that `_is_web_project` recognizes.
    Mirrors the lamill.toml + package.json convention used by the
    walker. The exact recognizer is intentionally loose — a package.json
    is sufficient."""
    site = tmp_path / name
    site.mkdir()
    (site / "package.json").write_text('{"name": "test", "version": "1.0.0"}')
    (site / "lamill.toml").write_text(
        'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n'
        '[live]\nurl = "https://example.com"\n'
    )
    return site


def _patch_transport(handler):
    """Patch `_build_client` to return an httpx.Client with a MockTransport."""
    def _builder():
        transport = httpx.MockTransport(handler)
        return httpx.Client(transport=transport, follow_redirects=True, timeout=10.0)
    return patch(
        "portfolio.checks.deploy.check_144_has_version_stamp._build_client",
        _builder,
    )


def _patch_live_url(url: str):
    return patch(
        "portfolio.checks.deploy.check_144_has_version_stamp.resolve_live_url",
        lambda _: url,
    )


# ---- skip paths ---------------------------------------------------


def test_warn_when_not_a_web_project(tmp_path: Path):
    site = tmp_path / "not-a-web-project"
    site.mkdir()
    # Intentionally no package.json — _is_web_project should reject.
    result = run(str(site))
    assert result.status == "warn"
    assert "not a web project" in result.message


def test_warn_when_no_live_url(tmp_path: Path):
    site = _make_web_site(tmp_path)
    with _patch_live_url(None):
        result = run(str(site))
    assert result.status == "warn"
    assert "no live URL" in result.message


# ---- transport failures (warn, not fail) --------------------------


def test_warn_on_network_error(tmp_path: Path):
    site = _make_web_site(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "warn"
    assert "unreachable" in result.message


# ---- HTTP failures (fail) -----------------------------------------


def test_fail_on_404(tmp_path: Path):
    site = _make_web_site(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "404" in result.message
    # Operator gets a pointer to the fix.
    assert "vite-version-stamp" in result.message


def test_fail_on_500(tmp_path: Path):
    site = _make_web_site(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "500" in result.message


# ---- shape validation (fail) --------------------------------------


def test_fail_when_body_not_json(tmp_path: Path):
    site = _make_web_site(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json at all")

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "did not parse as JSON" in result.message


def test_fail_when_body_not_object(tmp_path: Path):
    site = _make_web_site(tmp_path)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=["wrong", "shape"])

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "expected object" in result.message


def test_fail_when_commit_missing(tmp_path: Path):
    site = _make_web_site(tmp_path)
    body = {"schema": 1, "built_at": "2026-05-20T10:00:00Z"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "commit" in result.message


def test_fail_when_built_at_missing(tmp_path: Path):
    site = _make_web_site(tmp_path)
    body = {"schema": 1, "commit": "abc123"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "built_at" in result.message


def test_fail_when_commit_empty(tmp_path: Path):
    site = _make_web_site(tmp_path)
    body = {"schema": 1, "commit": "   ", "built_at": "2026-05-20T10:00:00Z"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "fail"
    assert "commit" in result.message


# ---- happy paths --------------------------------------------------


def test_pass_with_full_payload(tmp_path: Path):
    site = _make_web_site(tmp_path)
    body = {
        "schema": 1,
        "commit": "a693d96f1234567890abcdef1234567890abcdef",
        "built_at": "2026-05-20T10:00:00Z",
    }
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "pass"
    assert captured["url"] == "https://example.com/version.json"
    # Render short commit + ISO timestamp + schema note.
    assert "a693d96f1234" in result.message
    assert "2026-05-20T10:00:00Z" in result.message
    assert "schema v1" in result.message


def test_pass_without_schema_field(tmp_path: Path):
    """Backwards-compatible: missing `schema` is accepted, just omits
    the schema annotation from the message."""
    site = _make_web_site(tmp_path)
    body = {
        "commit": "abc123",
        "built_at": "2026-05-20T10:00:00Z",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "pass"
    assert "abc123" in result.message
    assert "schema v" not in result.message  # no schema annotation


def test_pass_with_unknown_commit(tmp_path: Path):
    """Plugin falls back to 'unknown' when neither git nor cloud env vars
    yield a SHA. Rendering shows it literally, not a truncated 12-char form."""
    site = _make_web_site(tmp_path)
    body = {"schema": 1, "commit": "unknown", "built_at": "2026-05-20T10:00:00Z"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "pass"
    assert "unknown" in result.message


def test_trailing_slash_on_origin_handled(tmp_path: Path):
    """`https://example.com/` vs `https://example.com` should resolve
    to the same fetch URL — no double slashes, no missing path."""
    site = _make_web_site(tmp_path)
    body = {"schema": 1, "commit": "abc", "built_at": "2026-05-20T10:00:00Z"}
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json=body)

    with _patch_live_url("https://example.com/"), _patch_transport(handler):
        result = run(str(site))
    assert result.status == "pass"
    assert captured["url"] == "https://example.com/version.json"
