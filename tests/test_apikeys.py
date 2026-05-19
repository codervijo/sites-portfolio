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
    monkeypatch.setattr(apikeys, "_probe_serpapi",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_vercel",
                        lambda _t: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_hostgator",
                        lambda _t, _a, _u=None: ProbeResult("missing", ""))

    out = apikeys.probe_all()
    for key in apikeys.KNOWN_KEYS:
        assert key in out


def test_known_keys_includes_canonical_set():
    """Sanity: the supported-keys list covers every credential the rest
    of the CLI references."""
    expected = {"OPENAI_API_KEY", "PORKBUN_API_KEY", "PORKBUN_SECRET_API_KEY",
                "CF_API_TOKEN", "CF_ACCOUNT_ID", "CRUX_API_KEY",
                "SERPAPI_KEY",                # v8.D
                "VERCEL_TOKEN",               # v11.A
                "HOSTGATOR_TOKEN_GATOR3164",  # v11.A
                "HOSTGATOR_USER_GATOR3164",   # v11.A patch 2026-05-19
                "HOSTGATOR_TOKEN_GATOR4216",  # v11.A
                "HOSTGATOR_USER_GATOR4216"}   # v11.A patch 2026-05-19
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


# ---------- v11.A: Vercel + HostGator probes ----------


def test_probe_vercel_missing_when_empty():
    assert apikeys._probe_vercel("").status == "missing"


def test_probe_vercel_valid_returns_username(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"user": {"username": "vijo", "email": "x@y.com"}}
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_vercel("vc-fake")
    assert result.status == "valid"
    assert "user=vijo" in result.detail


def test_probe_vercel_invalid_on_401(monkeypatch):
    class _Resp:
        status_code = 401
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_vercel("vc-bad")
    assert result.status == "invalid"
    assert "401" in result.detail


def test_probe_vercel_network_error(monkeypatch):
    import httpx as _httpx
    def _raise(*a, **kw):
        raise _httpx.ConnectError("boom")
    monkeypatch.setattr(apikeys.httpx, "get", _raise)
    result = apikeys._probe_vercel("vc-any")
    assert result.status == "invalid"
    assert "ConnectError" in result.detail


def test_hg_account_from_keyname_parses():
    """Account-id extraction from `HOSTGATOR_TOKEN_<ACCOUNT_ID>`."""
    assert apikeys._hg_account_from_keyname("HOSTGATOR_TOKEN_GATOR3164") == "gator3164"
    assert apikeys._hg_account_from_keyname("HOSTGATOR_TOKEN_GATOR4216") == "gator4216"
    assert apikeys._hg_account_from_keyname("HOSTGATOR_TOKEN_") is None
    assert apikeys._hg_account_from_keyname("OPENAI_API_KEY") is None
    assert apikeys._hg_account_from_keyname("") is None


def test_probe_hostgator_missing_when_empty_token():
    assert apikeys._probe_hostgator("", "gator3164").status == "missing"


def test_probe_hostgator_invalid_when_empty_account_id():
    """Programmer-error guard — token present but account_id blank."""
    result = apikeys._probe_hostgator("hg-fake", "")
    assert result.status == "invalid"
    assert "account_id" in result.detail


def test_probe_hostgator_uses_account_derived_url(monkeypatch):
    """Resolution 11.L — cPanel host derives from account_id, not config.
    Username defaults to account_id when cpanel_user isn't passed
    (back-compat with shared-hosting where username==server)."""
    captured = {}
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": 1, "data": {"user": "gator3164"}}
    def _capture(url, **kw):
        captured["url"] = url
        captured["auth"] = kw.get("headers", {}).get("Authorization")
        return _Resp()
    monkeypatch.setattr(apikeys.httpx, "get", _capture)

    apikeys._probe_hostgator("hg-token", "gator3164")
    assert "gator3164.hostgator.com:2083" in captured["url"]
    assert "Variables/get_user_information" in captured["url"]
    # cPanel custom auth scheme — NOT HTTP Basic. Username defaults
    # to account_id when not explicitly passed.
    assert captured["auth"] == "cpanel gator3164:hg-token"


def test_probe_hostgator_overrides_username_when_cpanel_user_passed(monkeypatch):
    """v11.A patch 2026-05-19 — operator's cPanel username may differ
    from server hostname (e.g. `foundervijo` on `gator3164` server).
    `cpanel_user` argument overrides the default account_id-as-user."""
    captured = {}
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": 1, "data": {"user": "foundervijo"}}
    def _capture(url, **kw):
        captured["url"] = url
        captured["auth"] = kw.get("headers", {}).get("Authorization")
        return _Resp()
    monkeypatch.setattr(apikeys.httpx, "get", _capture)

    apikeys._probe_hostgator("hg-token", "gator3164", cpanel_user="foundervijo")
    # URL still uses server hostname.
    assert "gator3164.hostgator.com:2083" in captured["url"]
    # Auth header uses the override username, not the server slug.
    assert captured["auth"] == "cpanel foundervijo:hg-token"


def test_hg_user_for_account_returns_env_var_value(monkeypatch, tmp_path):
    """`HOSTGATOR_USER_GATOR3164=foundervijo` in portfolio.env →
    helper returns `foundervijo`."""
    _patch_env_path(monkeypatch, tmp_path)
    apikeys.set_key("HOSTGATOR_USER_GATOR3164", "foundervijo")
    assert apikeys.hg_user_for_account("gator3164") == "foundervijo"


def test_hg_user_for_account_falls_back_to_account_id_when_unset(
    monkeypatch, tmp_path,
):
    """When `HOSTGATOR_USER_<account>` isn't set, fall back to
    `account_id` — back-compat with shared-hosting where the cPanel
    username equals the server hostname."""
    _patch_env_path(monkeypatch, tmp_path)
    assert apikeys.hg_user_for_account("gator3164") == "gator3164"


def test_hg_user_for_account_empty_input_returns_empty(monkeypatch, tmp_path):
    """Defensive — empty account_id in → empty out (no env-var lookup
    to do)."""
    _patch_env_path(monkeypatch, tmp_path)
    assert apikeys.hg_user_for_account("") == ""


def test_probe_hostgator_valid_on_uapi_status_1(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": 1, "data": {"user": "gator4216"}}
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_hostgator("hg-good", "gator4216")
    assert result.status == "valid"
    assert "gator4216" in result.detail


def test_probe_hostgator_invalid_on_uapi_status_0(monkeypatch):
    """UAPI's own failure path — HTTP 200 but `status=0` in body."""
    class _Resp:
        status_code = 200
        def json(self):
            return {"status": 0, "errors": ["Token does not exist."]}
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_hostgator("hg-bad", "gator3164")
    assert result.status == "invalid"
    assert "Token does not exist" in result.detail


def test_probe_hostgator_invalid_on_401(monkeypatch):
    class _Resp:
        status_code = 401
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_hostgator("hg-revoked", "gator3164")
    assert result.status == "invalid"
    assert "401" in result.detail


def test_probe_hostgator_invalid_on_403_scope(monkeypatch):
    class _Resp:
        status_code = 403
    monkeypatch.setattr(apikeys.httpx, "get", lambda *a, **kw: _Resp())
    result = apikeys._probe_hostgator("hg-noscope", "gator3164")
    assert result.status == "invalid"
    assert "403" in result.detail


def test_probe_hostgator_network_error(monkeypatch):
    import httpx as _httpx
    def _raise(*a, **kw):
        raise _httpx.ConnectError("boom")
    monkeypatch.setattr(apikeys.httpx, "get", _raise)
    result = apikeys._probe_hostgator("hg-any", "gator3164")
    assert result.status == "invalid"
    assert "ConnectError" in result.detail


def test_probe_all_dispatches_to_hg_accounts(monkeypatch, tmp_path):
    """probe_all() should call _probe_hostgator once per HG_TOKEN_* known
    key. Verifies the loop over KNOWN_KEYS picks both gator3164 and
    gator4216 — and would pick up a third if added later."""
    _patch_env_path(monkeypatch, tmp_path)
    from portfolio.apikeys import ProbeResult
    # Stub the other probes so they don't try real network calls.
    monkeypatch.setattr(apikeys, "_probe_openai",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_crux",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_porkbun",
                        lambda _a, _b: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_cf_token",
                        lambda _t: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_serpapi",
                        lambda _k: ProbeResult("missing", ""))
    monkeypatch.setattr(apikeys, "_probe_vercel",
                        lambda _t: ProbeResult("missing", ""))
    calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        apikeys, "_probe_hostgator",
        lambda token, account_id, cpanel_user=None: (
            calls.append((token, account_id, cpanel_user or ""))
            or ProbeResult("missing", "")
        ),
    )

    out = apikeys.probe_all()
    assert "HOSTGATOR_TOKEN_GATOR3164" in out
    assert "HOSTGATOR_TOKEN_GATOR4216" in out
    # Verify the loop called _probe_hostgator with the right derived
    # account_ids — order follows KNOWN_KEYS declaration order.
    account_ids_called = [c[1] for c in calls]
    assert "gator3164" in account_ids_called
    assert "gator4216" in account_ids_called
