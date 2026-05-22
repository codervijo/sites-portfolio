"""Tests for v18.C — GA4 Admin API client.

Verifies the two public API helpers (`create_property` +
`create_web_stream`) plus the credential / token state probes that
the CLI surface uses.

All HTTP stubbed via `httpx.MockTransport` so the suite never
touches the real Analytics Admin API. OAuth refresh + interactive
flow are mocked at the boundary (we trust google-auth-oauthlib's
own test coverage).
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from portfolio.ga4_admin import (
    GA4AdminError,
    MissingCredentialsError,
    create_property,
    create_web_stream,
    has_token,
)


# ---- create_property -------------------------------------------------


def test_create_property_returns_numeric_property_id():
    """Happy path: 200 response with `name: "properties/123456789"`
    → helper returns the bare numeric ID."""
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1beta/properties"
        body = json.loads(request.content)
        assert body["parent"] == "accounts/42"
        assert body["displayName"] == "washcalc.app"
        assert body["timeZone"] == "America/Los_Angeles"
        assert body["currencyCode"] == "USD"
        return httpx.Response(
            200,
            json={
                "name": "properties/123456789",
                "displayName": "washcalc.app",
                "timeZone": "America/Los_Angeles",
                "currencyCode": "USD",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    pid = create_property("42", "washcalc.app", client=client)
    assert pid == "123456789"


def test_create_property_raises_on_403():
    """Token lacks `analytics.edit` scope → 403. Caller (bootstrap)
    treats this as a soft-skip but the helper raises so callers can
    distinguish from network failures."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403,
            text=json.dumps({"error": {
                "code": 403,
                "message": "Request had insufficient authentication scopes.",
            }}),
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GA4AdminError) as exc_info:
        create_property("42", "washcalc.app", client=client)
    assert "HTTP 403" in str(exc_info.value)
    assert "scopes" in str(exc_info.value).lower()


def test_create_property_raises_on_unexpected_response_shape():
    """If the API returns 200 but with an unexpected shape (no `name`
    field), the helper raises rather than guessing."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GA4AdminError, match="unexpected"):
        create_property("42", "x.com", client=client)


def test_create_property_accepts_custom_timezone_currency():
    """Operator with non-US fleet might want a different timezone /
    currency on the GA4 property."""
    captured: dict[str, dict] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"name": "properties/999"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    create_property(
        "42", "x.uk",
        time_zone="Europe/London", currency_code="GBP",
        client=client,
    )
    assert captured["body"]["timeZone"] == "Europe/London"
    assert captured["body"]["currencyCode"] == "GBP"


# ---- create_web_stream ----------------------------------------------


def test_create_web_stream_returns_stream_id_and_measurement_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/v1beta/properties/123/dataStreams"
        body = json.loads(request.content)
        assert body["type"] == "WEB_DATA_STREAM"
        assert body["webStreamData"]["defaultUri"] == "https://washcalc.app/"
        # display_name should default to "washcalc.app web stream"
        assert "washcalc.app" in body["displayName"]
        return httpx.Response(
            200,
            json={
                "name": "properties/123/dataStreams/456",
                "type": "WEB_DATA_STREAM",
                "displayName": "washcalc.app web stream",
                "webStreamData": {
                    "defaultUri": "https://washcalc.app/",
                    "measurementId": "G-HP39MQPM2M",
                },
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    stream_id, measurement_id = create_web_stream(
        "123", "https://washcalc.app/", client=client,
    )
    assert stream_id == "456"
    assert measurement_id == "G-HP39MQPM2M"


def test_create_web_stream_respects_explicit_display_name():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "name": "properties/123/dataStreams/789",
                "webStreamData": {"measurementId": "G-ABCDEFGHIJ"},
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    create_web_stream(
        "123", "https://x.com/",
        display_name="X production",
        client=client,
    )
    assert captured["body"]["displayName"] == "X production"


def test_create_web_stream_raises_on_404():
    """`property_id` doesn't exist → 404. Helper raises."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text='{"error":{"code":404}}')

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GA4AdminError, match="HTTP 404"):
        create_web_stream("nonexistent", "https://x.com/", client=client)


def test_create_web_stream_raises_when_response_missing_measurement_id():
    """Bizarre but possible — the API returns 200 but the
    measurementId field is absent. Helper raises rather than
    returning a stub value that would silently break bootstrap."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "name": "properties/123/dataStreams/789",
                "webStreamData": {"defaultUri": "https://x.com/"},
                # measurementId missing
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(GA4AdminError, match="measurementId"):
        create_web_stream("123", "https://x.com/", client=client)


# ---- has_token + missing credentials --------------------------------


def test_has_token_returns_false_when_token_file_absent(tmp_path, monkeypatch):
    """Fresh install (no OAuth done yet) → `has_token()` False."""
    monkeypatch.setattr("portfolio.ga4_admin.TOKEN_PATH", tmp_path / "token.json")
    assert has_token() is False


def test_has_token_returns_true_when_token_file_present(tmp_path, monkeypatch):
    fake_token = tmp_path / "token.json"
    fake_token.write_text('{"refresh_token": "fake"}')
    monkeypatch.setattr("portfolio.ga4_admin.TOKEN_PATH", fake_token)
    assert has_token() is True


def test_authenticate_raises_missing_credentials_when_client_config_absent(
    tmp_path, monkeypatch,
):
    """Without `credentials.json` (the OAuth client config from GCP
    Console), authenticate() must raise the typed error so the CLI
    surface can print actionable setup steps instead of an opaque
    file-not-found."""
    from portfolio import ga4_admin

    monkeypatch.setattr(ga4_admin, "CREDENTIALS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ga4_admin, "TOKEN_PATH", tmp_path / "tok.json")

    with pytest.raises(MissingCredentialsError) as exc_info:
        ga4_admin.authenticate()
    msg = str(exc_info.value)
    assert "GCP Console" in msg or "console.cloud.google.com" in msg
    assert "lamill settings ga4 auth" in msg


# ---- CLI surface — settings ga4 auth -------------------------------


def test_settings_ga4_auth_command_registered():
    """`lamill settings ga4 auth` exists in the typer app tree."""
    from typer.testing import CliRunner
    from portfolio.cli import app

    runner = CliRunner()
    # --help on the ga4 subgroup should list 'auth' as a command.
    result = runner.invoke(app, ["settings", "ga4", "--help"])
    assert result.exit_code == 0
    assert "auth" in result.output


def test_settings_ga4_auth_surfaces_missing_credentials_actionably(
    tmp_path, monkeypatch,
):
    """When the operator runs `lamill settings ga4 auth` without first
    placing `credentials.json`, the CLI prints actionable setup steps
    and exits 1 (not a stack trace)."""
    from typer.testing import CliRunner
    from portfolio.cli import app
    from portfolio import ga4_admin

    monkeypatch.setattr(ga4_admin, "CREDENTIALS_PATH", tmp_path / "missing.json")
    monkeypatch.setattr(ga4_admin, "TOKEN_PATH", tmp_path / "tok.json")

    runner = CliRunner()
    result = runner.invoke(app, ["settings", "ga4", "auth"])
    assert result.exit_code == 1
    out = result.output
    assert "Missing OAuth client config" in out
    assert "console.cloud.google.com" in out or "GCP Console" in out
