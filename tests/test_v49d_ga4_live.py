"""v49.D — CHECK_164 ga4-live-tag (live homepage / bundles load the recorded ID)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from portfolio.checks.seo import _live
from portfolio.checks.seo import check_164_ga4_live_tag as c164

GA = "G-TEST123ABC"
TOML = f'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n[analytics]\nga4_id = "{GA}"\n'


@pytest.fixture(autouse=True)
def _clear():
    _live.clear_cache()
    yield
    _live.clear_cache()


def _site(tmp_path: Path, toml=TOML) -> Path:
    d = tmp_path / "example.test"
    d.mkdir()
    (d / "package.json").write_text("{}")
    (d / "lamill.toml").write_text(toml)
    return d


def _serve(monkeypatch, pages: dict[str, str]):
    def handler(req: httpx.Request) -> httpx.Response:
        body = pages.get(str(req.url))
        return httpx.Response(200, text=body) if body is not None else httpx.Response(404)
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(_live, "_build_client", lambda: httpx.Client(transport=transport, follow_redirects=True))


def test_live_in_html(tmp_path, monkeypatch):
    d = _site(tmp_path)
    _serve(monkeypatch, {"https://example.test/": f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA}"></script>'})
    r = c164.run(str(d))
    assert r.status == "pass" and "homepage HTML" in r.message


def test_live_in_nested_bundle(tmp_path, monkeypatch):
    d = _site(tmp_path)
    _serve(monkeypatch, {
        "https://example.test/": '<script type="module" src="/assets/index-a1.js"></script>'
                                 '<script src="https://cdn.other.test/x.js"></script>',
        "https://example.test/assets/index-a1.js": 'import{a}from"./chunk-b2.js";import("./lazy-c3.js")',
        "https://example.test/assets/chunk-b2.js": "export const a=1",
        "https://example.test/assets/lazy-c3.js": f'const id=(void 0||"{GA}")',
    })
    state, detail = c164.live_state(d)
    assert state == "live" and "lazy-c3.js" in detail


def test_live_in_astro_island(tmp_path, monkeypatch):
    d = _site(tmp_path)
    _serve(monkeypatch, {
        "https://example.test/": '<astro-island component-url="/_astro/Tool.Ab1.js" renderer-url="/_astro/client.Cd2.js"></astro-island>',
        "https://example.test/_astro/client.Cd2.js": "x",
        "https://example.test/_astro/Tool.Ab1.js": f'import"./init.Ef3.js"',
        "https://example.test/_astro/init.Ef3.js": f'"{GA}"',
    })
    assert c164.live_state(d)[0] == "live"


def test_missing_and_mismatch_and_placeholder(tmp_path, monkeypatch):
    d = _site(tmp_path)
    _serve(monkeypatch, {"https://example.test/": "<html>G-XXXXXXXXXX</html>"})
    r = c164.run(str(d))
    assert r.status == "warn" and "not deployed" in r.message
    _live.clear_cache()
    _serve(monkeypatch, {"https://example.test/": "<script>gtag('config','G-OTHER99999')</script>"})
    assert c164.live_state(d) == ("mismatch", f"live loads G-OTHER99999, expected {GA}")


def test_unreachable_is_warn(tmp_path, monkeypatch):
    d = _site(tmp_path)
    _serve(monkeypatch, {})
    r = c164.run(str(d))
    assert r.status == "warn" and "unreachable" in r.message


def test_no_recorded_id_and_na(tmp_path):
    d = _site(tmp_path, toml='schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n')
    assert "CHECK_162" in c164.run(str(d)).message
    assert "n/a" in c164.run(str(tmp_path / "nope")).message
