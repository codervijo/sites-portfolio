"""Tests for portfolio.cloudflare — CF API client used by CHECK_142's
tier-1 fix. All network calls go through an injected `httpx.Client` so
no test ever touches the real Cloudflare API."""
from __future__ import annotations

import json

import httpx
import pytest

from portfolio import cloudflare


def _mock_client(handler) -> httpx.Client:
    transport = httpx.MockTransport(handler)
    return httpx.Client(transport=transport, base_url=cloudflare.API_BASE,
                        headers={"Authorization": "Bearer test-token",
                                 "Content-Type": "application/json"})


def test_read_token_raises_when_missing(monkeypatch, tmp_path):
    """v15.O — env-first: stub apikeys.get_key to return empty so we
    fall through to the file (which is also missing here)."""
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", tmp_path / "no-token-here")
    import portfolio.apikeys as apikeys_mod
    monkeypatch.setattr(apikeys_mod, "get_key", lambda k: "")
    with pytest.raises(cloudflare.MissingCredentialsError) as exc:
        cloudflare._read_token()
    msg = str(exc.value)
    assert "dash.cloudflare.com/profile/api-tokens" in msg
    assert "settings apikeys set CF_API_TOKEN" in msg


def test_read_token_env_wins_over_file(monkeypatch, tmp_path):
    """v15.O — when CF_API_TOKEN is in portfolio.env, it wins over
    the legacy file."""
    p = tmp_path / "token"
    p.write_text("file-token-old\n")
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", p)
    import portfolio.apikeys as apikeys_mod
    monkeypatch.setattr(
        apikeys_mod, "get_key",
        lambda k: "env-token-new" if k == "CF_API_TOKEN" else "",
    )
    assert cloudflare._read_token() == "env-token-new"


def test_read_token_falls_back_to_file_when_env_empty(monkeypatch, tmp_path):
    """v15.O — file is the fallback when env is unset."""
    p = tmp_path / "token"
    p.write_text("  abc123  \n")
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", p)
    import portfolio.apikeys as apikeys_mod
    monkeypatch.setattr(apikeys_mod, "get_key", lambda k: "")
    assert cloudflare._read_token() == "abc123"


def test_resolve_zone_id_uses_cache(monkeypatch, tmp_path):
    cache_path = tmp_path / "zones.json"
    cache_path.write_text(json.dumps({"example.com": "zone-abc"}))
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", cache_path)

    # If the cache works, the client mock should never get called. Make
    # the handler raise so a regression here surfaces loudly.
    def handler(request):
        raise AssertionError(f"unexpected API call: {request.url}")
    client = _mock_client(handler)

    assert cloudflare.resolve_zone_id("example.com", client=client) == "zone-abc"


def test_resolve_zone_id_fetches_and_persists_on_cache_miss(monkeypatch, tmp_path):
    cache_path = tmp_path / "zones.json"
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", cache_path)

    captured_params = {}

    def handler(request):
        captured_params.update(dict(request.url.params))
        return httpx.Response(200, json={
            "success": True,
            "result": [{"id": "zone-xyz", "name": "newsite.com"}],
        })

    client = _mock_client(handler)
    zone = cloudflare.resolve_zone_id("newsite.com", client=client)
    assert zone == "zone-xyz"
    assert captured_params.get("name") == "newsite.com"
    # Persisted for next call.
    assert json.loads(cache_path.read_text()) == {"newsite.com": "zone-xyz"}


def test_resolve_zone_id_raises_when_zone_not_found(monkeypatch, tmp_path):
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", tmp_path / "z.json")
    client = _mock_client(lambda req: httpx.Response(
        200, json={"success": True, "result": []}))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.resolve_zone_id("absent.com", client=client)
    assert "No CF zone" in str(exc.value)


def test_resolve_zone_id_raises_on_api_error(monkeypatch, tmp_path):
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", tmp_path / "z.json")
    client = _mock_client(lambda req: httpx.Response(
        200, json={"success": False, "errors": [{"code": 9109, "message": "unauthorized"}]}))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.resolve_zone_id("locked.com", client=client)
    assert "success=false" in str(exc.value)


def test_resolve_zone_id_raises_on_http_error(monkeypatch, tmp_path):
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", tmp_path / "z.json")
    client = _mock_client(lambda req: httpx.Response(401, text="forbidden"))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.resolve_zone_id("x.com", client=client)
    assert "HTTP 401" in str(exc.value)


def test_purge_files_no_op_on_empty_list():
    # Passing client=None would try to read the token file. An empty
    # urls list must short-circuit before that.
    cloudflare.purge_files("zone-abc", [])


def test_purge_files_posts_url_list():
    captured: dict = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"success": True})

    client = _mock_client(handler)
    cloudflare.purge_files("zone-abc",
                           ["https://x.com/a", "https://x.com/b"],
                           client=client)
    assert "/zones/zone-abc/purge_cache" in captured["url"]
    assert captured["body"] == {"files": ["https://x.com/a", "https://x.com/b"]}


def test_purge_files_raises_on_more_than_30_urls():
    urls = [f"https://x.com/{i}" for i in range(31)]
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.purge_files("zone-abc", urls,
                               client=_mock_client(lambda req: httpx.Response(200)))
    assert "30 per request" in str(exc.value)


def test_purge_files_raises_on_non_200():
    client = _mock_client(lambda req: httpx.Response(429, text="rate limited"))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.purge_files("zone-abc", ["https://x.com/a"], client=client)
    assert "HTTP 429" in str(exc.value)


def test_purge_files_raises_on_success_false():
    client = _mock_client(lambda req: httpx.Response(
        200, json={"success": False,
                   "errors": [{"code": 9106, "message": "URL not in zone"}]}))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.purge_files("zone-abc", ["https://x.com/a"], client=client)
    assert "success=false" in str(exc.value)


def test_zones_cache_round_trip(monkeypatch, tmp_path):
    cache_path = tmp_path / "zones.json"
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", cache_path)
    assert cloudflare._load_zones_cache() == {}
    cloudflare._save_zones_cache({"a.com": "1", "b.com": "2"})
    assert cloudflare._load_zones_cache() == {"a.com": "1", "b.com": "2"}


def test_zones_cache_tolerates_corrupt_json(monkeypatch, tmp_path):
    cache_path = tmp_path / "zones.json"
    cache_path.write_text("{not valid json")
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", cache_path)
    assert cloudflare._load_zones_cache() == {}


# ---------- save_token + verify_token + token_status ----------


def test_save_token_writes_file_with_mode_0600(monkeypatch, tmp_path):
    token_path = tmp_path / "subdir" / "token"
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", token_path)
    cloudflare.save_token("abc123")
    assert token_path.read_text() == "abc123"
    assert oct(token_path.stat().st_mode & 0o777) == "0o600"


def test_save_token_creates_parent_dir(monkeypatch, tmp_path):
    """save_token must mkdir -p the parent — the operator shouldn't
    have to pre-create ~/.config/portfolio/cloudflare/."""
    token_path = tmp_path / "fresh" / "nested" / "token"
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", token_path)
    cloudflare.save_token("xyz")
    assert token_path.is_file()
    assert token_path.parent.is_dir()


def test_save_token_strips_whitespace(monkeypatch, tmp_path):
    """Dashboards' copy widgets often append a newline; strip it so the
    Authorization header doesn't contain stray whitespace."""
    token_path = tmp_path / "token"
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", token_path)
    cloudflare.save_token("  padded-token  \n")
    assert token_path.read_text() == "padded-token"


def test_save_token_refuses_empty(monkeypatch, tmp_path):
    """Saving an empty string leaves the next call failing obscurely
    inside an HTTP request. Catch it at save time with a clear error."""
    token_path = tmp_path / "token"
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", token_path)
    with pytest.raises(ValueError) as exc:
        cloudflare.save_token("   \n  ")
    assert "empty" in str(exc.value)
    assert not token_path.exists()


def test_verify_token_returns_result_on_success():
    captured: dict = {}

    def handler(request):
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("Authorization")
        return httpx.Response(200, json={
            "success": True,
            "result": {"id": "tok-1", "status": "active",
                       "expires_on": None, "not_before": None},
        })
    client = _mock_client(handler)
    result = cloudflare.verify_token(client=client)
    assert result["status"] == "active"
    assert "/user/tokens/verify" in captured["url"]


def test_verify_token_raises_on_non_200():
    client = _mock_client(lambda req: httpx.Response(401, text="unauth"))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.verify_token(client=client)
    assert "HTTP 401" in str(exc.value)


def test_verify_token_raises_on_success_false():
    client = _mock_client(lambda req: httpx.Response(
        200, json={"success": False,
                   "errors": [{"code": 1000, "message": "invalid token"}]}))
    with pytest.raises(cloudflare.CloudflareAPIError) as exc:
        cloudflare.verify_token(client=client)
    assert "success=false" in str(exc.value)


def test_token_status_when_nothing_configured(monkeypatch, tmp_path):
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", tmp_path / "missing" / "token")
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", tmp_path / "zones.json")
    s = cloudflare.token_status()
    assert s["token_present"] is False
    assert s["token_mode"] is None
    assert s["zones_cached"] == 0


def test_token_status_when_token_saved(monkeypatch, tmp_path):
    token_path = tmp_path / "cloudflare" / "token"
    monkeypatch.setattr(cloudflare, "TOKEN_PATH", token_path)
    zones_path = tmp_path / "zones.json"
    monkeypatch.setattr(cloudflare, "ZONES_CACHE", zones_path)
    cloudflare.save_token("a-token")
    zones_path.write_text(json.dumps({"a.com": "1", "b.com": "2"}))

    s = cloudflare.token_status()
    assert s["token_present"] is True
    assert s["token_mode"] == "0o600"
    assert s["zones_cached"] == 2
    assert s["parent_mode"] == "0o700"
