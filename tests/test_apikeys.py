"""Tests for v7.A — `settings apikeys` env-file IO + connectivity probes.

Probes are mocked via httpx.MockTransport — no live network calls in
the test suite. The probe shape (`ProbeResult.status`) is the contract
the CLI relies on.
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from portfolio import apikeys


def _patch_env_path(monkeypatch, tmp_path):
    """Point apikeys at a tmp portfolio.env so tests don't touch real one."""
    env_path = tmp_path / "portfolio.env"
    monkeypatch.setattr(apikeys, "PORTFOLIO_ENV", env_path)
    # `ensure_portfolio_env` writes the template if absent.
    import portfolio.suggest as suggest_module
    monkeypatch.setattr(suggest_module, "PORTFOLIO_ENV", env_path)
    return env_path


# ---------- env file IO ----------


def test_set_key_creates_file_when_missing(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    apikeys.set_key("OPENAI_API_KEY", "sk-test123")
    assert env.exists()
    text = env.read_text()
    assert "OPENAI_API_KEY=sk-test123" in text


def test_set_key_updates_existing_value(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text("OPENAI_API_KEY=old\nCRUX_API_KEY=keep\n")
    apikeys.set_key("OPENAI_API_KEY", "new")
    text = env.read_text()
    assert "OPENAI_API_KEY=new" in text
    assert "CRUX_API_KEY=keep" in text   # unchanged
    # No duplicate.
    assert text.count("OPENAI_API_KEY=") == 1


def test_set_key_preserves_comments_and_blank_lines(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text(
        "# Top comment\n\n"
        "# Section A\n"
        "OPENAI_API_KEY=old\n"
        "\n"
        "# Section B\n"
        "CRUX_API_KEY=set\n"
    )
    apikeys.set_key("OPENAI_API_KEY", "new")
    text = env.read_text()
    assert "# Top comment" in text
    assert "# Section A" in text
    assert "# Section B" in text
    assert "OPENAI_API_KEY=new" in text
    assert "CRUX_API_KEY=set" in text


def test_set_key_appends_new_key_at_end(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text("OPENAI_API_KEY=existing\n")
    apikeys.set_key("CRUX_API_KEY", "new")
    text = env.read_text()
    lines = text.strip().splitlines()
    assert lines[-1] == "CRUX_API_KEY=new"


def test_get_key_returns_none_for_unset(monkeypatch, tmp_path):
    _patch_env_path(monkeypatch, tmp_path)
    assert apikeys.get_key("OPENAI_API_KEY") is None


def test_get_key_returns_none_for_empty_value(monkeypatch, tmp_path):
    """Empty values count as unset (matches portfolio.env template
    convention of `KEY=` placeholders)."""
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text("OPENAI_API_KEY=\nCRUX_API_KEY=real\n")
    assert apikeys.get_key("OPENAI_API_KEY") is None
    assert apikeys.get_key("CRUX_API_KEY") == "real"


def test_get_key_strips_quotes(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text('OPENAI_API_KEY="sk-quoted"\n')
    assert apikeys.get_key("OPENAI_API_KEY") == "sk-quoted"


def test_delete_key_removes_line(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text("OPENAI_API_KEY=del\nCRUX_API_KEY=keep\n")
    removed = apikeys.delete_key("OPENAI_API_KEY")
    assert removed is True
    text = env.read_text()
    assert "OPENAI_API_KEY" not in text
    assert "CRUX_API_KEY=keep" in text


def test_delete_key_returns_false_when_absent(monkeypatch, tmp_path):
    """Key not in file at all → delete returns False (no-op)."""
    env = _patch_env_path(monkeypatch, tmp_path)
    # Bypass the template (which would include OPENAI_API_KEY=) and
    # write a file without the targeted key.
    env.write_text("CRUX_API_KEY=set\n")
    assert apikeys.delete_key("OPENAI_API_KEY") is False
    # And the existing key untouched.
    assert env.read_text() == "CRUX_API_KEY=set\n"


def test_delete_key_preserves_other_lines(monkeypatch, tmp_path):
    env = _patch_env_path(monkeypatch, tmp_path)
    env.write_text(
        "# header\n"
        "OPENAI_API_KEY=del\n"
        "# section comment\n"
        "CRUX_API_KEY=keep\n"
    )
    apikeys.delete_key("OPENAI_API_KEY")
    text = env.read_text()
    assert "# header" in text
    assert "# section comment" in text
    assert "CRUX_API_KEY=keep" in text


def test_set_then_get_roundtrip(monkeypatch, tmp_path):
    _patch_env_path(monkeypatch, tmp_path)
    apikeys.set_key("OPENAI_API_KEY", "value-A")
    apikeys.set_key("CRUX_API_KEY", "value-B")
    assert apikeys.get_key("OPENAI_API_KEY") == "value-A"
    assert apikeys.get_key("CRUX_API_KEY") == "value-B"


# ---------- connectivity probes ----------


def _stub_httpx_get(monkeypatch, status_code: int):
    """Replace `apikeys.httpx.get` with a stub returning the given status."""
    class _StubResponse:
        def __init__(self, code):
            self.status_code = code
        def json(self):
            return {}
    fake_get = lambda *a, **kw: _StubResponse(status_code)
    monkeypatch.setattr(apikeys.httpx, "get", fake_get)


def test_probe_openai_valid_on_200(monkeypatch):
    _stub_httpx_get(monkeypatch, 200)
    result = apikeys._probe_openai("sk-fake")
    assert result.status == "valid"


def test_probe_openai_invalid_on_401(monkeypatch):
    _stub_httpx_get(monkeypatch, 401)
    result = apikeys._probe_openai("sk-bad")
    assert result.status == "invalid"
    assert "401" in result.detail


def test_probe_openai_missing_when_empty():
    """Empty key short-circuits before any network call."""
    result = apikeys._probe_openai("")
    assert result.status == "missing"


def test_probe_crux_missing_when_empty():
    result = apikeys._probe_crux("")
    assert result.status == "missing"


def test_probe_porkbun_missing_when_either_half_absent():
    """Porkbun needs both keys."""
    assert apikeys._probe_porkbun("", "secret").status == "missing"
    assert apikeys._probe_porkbun("api", "").status == "missing"


def test_probe_cf_token_missing_when_empty():
    result = apikeys._probe_cf_token("")
    assert result.status == "missing"


def test_probe_all_returns_known_keys(monkeypatch, tmp_path):
    """probe_all() must return an entry for every KNOWN_KEY."""
    _patch_env_path(monkeypatch, tmp_path)
    # Stub all the network probes — this test is about the dispatch
    # shape, not actual connectivity.
    from portfolio.apikeys import ProbeResult
    monkeypatch.setattr(apikeys, "_probe_openai",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_crux",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_porkbun",
                        lambda _a, _b: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_cf_token",
                        lambda _t: ProbeResult("missing", ""))

    out = apikeys.probe_all()
    for key in apikeys.KNOWN_KEYS:
        assert key in out


def test_known_keys_includes_canonical_set():
    """Sanity: the supported-keys list covers every credential the rest
    of the CLI references."""
    expected = {"OPENAI_API_KEY", "PORKBUN_API_KEY", "PORKBUN_SECRET_API_KEY",
                "CF_API_TOKEN", "CF_ACCOUNT_ID", "CRUX_API_KEY",
                "SERPAPI_KEY"}  # v8.D
    assert set(apikeys.KNOWN_KEYS) == expected


def test_serpapi_probe_missing_returns_missing():
    result = apikeys._probe_serpapi("")
    assert result.status == "missing"


def test_serpapi_probe_valid_response(monkeypatch):
    """200 with plan + searches_left fields → valid + useful detail."""
    class _Resp:
        status_code = 200
        def json(self):
            return {"plan_name": "Free", "searches_left": 247}

    import httpx as _httpx
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_serpapi("fake-key")
    assert result.status == "valid"
    assert "Free" in result.detail
    assert "247" in result.detail


def test_serpapi_probe_unauthorized(monkeypatch):
    class _Resp:
        status_code = 401
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_serpapi("bad-key")
    assert result.status == "invalid"
    assert "401" in result.detail


def test_serpapi_probe_network_error(monkeypatch):
    import httpx as _httpx
    def _raise(*a, **kw):
        raise _httpx.ConnectError("boom")
    monkeypatch.setattr(apikeys.httpx, "get", _raise)
    result = apikeys._probe_serpapi("any-key")
    assert result.status == "invalid"
    assert "ConnectError" in result.detail
