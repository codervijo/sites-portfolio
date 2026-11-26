"""v46.G–I — CHECK_167 unknown-path-404, shared helpers, bootstrap born-conformant."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from portfolio import not_found as nf
from portfolio.checks.deploy import check_167_unknown_path_404 as c167

SPA_WRANGLER = '''{
  // keep this comment
  "name": "site",
  "assets": {
    "directory": "./dist",
    "not_found_handling": "single-page-application"
  }
}
'''


def _site(tmp_path: Path, name="s.com", *, wrangler=SPA_WRANGLER, astro=True,
          page404=False, stack="astro") -> Path:
    d = tmp_path / name
    d.mkdir()
    if wrangler is not None:
        (d / "wrangler.jsonc").write_text(wrangler)
    if astro:
        (d / "astro.config.mjs").write_text("export default {}\n")
    if page404:
        (d / "src" / "pages").mkdir(parents=True)
        (d / "src" / "pages" / "404.astro").write_text("404")
    if stack:
        (d / "lamill.toml").write_text(
            'schema = "lamill-toml-v1"\n[deploy]\nplatform = "cf-pages"\n'
            f'[stack]\nframework = "{stack}"\n')
    return d


def _client(code: int) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(code)))


# ---------- helpers ----------

def test_set_value_preserves_comments_and_replaces_in_place():
    out = nf.set_not_found_value(SPA_WRANGLER, "404-page")
    assert '"not_found_handling": "404-page"' in out
    assert "// keep this comment" in out and out.count("not_found_handling") == 1


def test_set_value_inserts_when_absent_and_refuses_without_assets():
    body = '{\n  "assets": {\n    "directory": "./dist"\n  }\n}\n'
    out = nf.set_not_found_value(body, "404-page")
    assert nf.not_found_value(out) == "404-page"
    with pytest.raises(ValueError):
        nf.set_not_found_value('{"name": "x"}', "404-page")


@pytest.mark.parametrize("stack,astro,spa", [
    ("astro", True, False), ("vite-react", False, True), ("tanstack", False, True),
    (None, True, False), (None, False, True),
])
def test_wants_spa_fallback(tmp_path, stack, astro, spa):
    d = tmp_path / "x"
    d.mkdir()
    if astro:
        (d / "astro.config.mjs").write_text("")
    assert nf.wants_spa_fallback(stack, d) is spa


# ---------- check ----------

def test_spa_value_on_astro_fails(tmp_path):
    r = c167.run(str(_site(tmp_path)), live=False)
    assert r.status == "fail"
    assert "single-page-application" in r.message and "no 404 page" in r.message


def test_correct_repo_and_live_404_passes(tmp_path):
    d = _site(tmp_path, wrangler=nf.set_not_found_value(SPA_WRANGLER, "404-page"), page404=True)
    assert c167.run(str(d), client=_client(404)).status == "pass"


def test_correct_repo_but_live_200_warns_not_deployed(tmp_path):
    d = _site(tmp_path, wrangler=nf.set_not_found_value(SPA_WRANGLER, "404-page"), page404=True)
    r = c167.run(str(d), client=_client(200))
    assert r.status == "warn" and "commit + push" in r.message


def test_unreachable_live_warns(tmp_path, monkeypatch):
    d = _site(tmp_path, wrangler=nf.set_not_found_value(SPA_WRANGLER, "404-page"), page404=True)
    monkeypatch.setattr(c167, "_live_status", lambda domain, client=None: None)
    assert c167.run(str(d)).status == "warn"


@pytest.mark.parametrize("kw,expect", [
    (dict(stack="vite-react", astro=False), "SPA"),
    (dict(wrangler=None), "not on Cloudflare"),
])
def test_not_applicable(tmp_path, kw, expect):
    r = c167.run(str(_site(tmp_path, **kw)), live=False)
    assert r.status == "pass" and "n/a" in r.message and expect in r.message


def test_non_domain_dir_na(tmp_path):
    assert "n/a" in c167.run(str(_site(tmp_path, name="portfolio")), live=False).message


def test_minimal_lamill_toml_baseline_uses_astro_config(tmp_path):
    """Additive-optional: no [stack] table → fall back to the Astro config."""
    d = _site(tmp_path, stack=None)
    (d / "lamill.toml").write_text('schema = "lamill-toml-v1"\n[deploy]\nplatform = "cf-pages"\n')
    assert c167.run(str(d), live=False).status == "fail"


# ---------- fixer ----------

def test_fixer_dry_run_then_apply_then_idempotent(tmp_path):
    d = _site(tmp_path)
    dry = c167.fix_tier_1.apply(d, True, False)
    assert dry.status == "would-fix" and not dry.files_touched
    assert nf.not_found_value((d / "wrangler.jsonc").read_text()) == "single-page-application"
    res = c167.fix_tier_1.apply(d, False, False)
    assert res.status == "fixed"
    assert nf.not_found_value((d / "wrangler.jsonc").read_text()) == "404-page"
    assert "// keep this comment" in (d / "wrangler.jsonc").read_text()
    page = (d / "src" / "pages" / "404.astro").read_text()
    assert 'name="robots" content="noindex"' in page and 'href="/"' in page
    assert c167.fix_tier_1.apply(d, False, False).status == "nothing-to-do"
    assert c167.run(str(d), live=False).status == "pass"


def test_fixer_keeps_existing_404_page(tmp_path):
    d = _site(tmp_path, page404=True)
    c167.fix_tier_1.apply(d, False, False)
    assert (d / "src" / "pages" / "404.astro").read_text() == "404"


def test_fixer_never_touches_spa_sites(tmp_path):
    d = _site(tmp_path, stack="vite-react", astro=False)
    assert c167.fix_tier_1.apply(d, False, False).status == "nothing-to-do"
    assert nf.not_found_value((d / "wrangler.jsonc").read_text()) == "single-page-application"


def test_fixer_manual_when_no_assets_block(tmp_path):
    d = _site(tmp_path, wrangler='{"name": "x"}\n')
    assert c167.fix_tier_1.apply(d, False, False).status == "manual"


# ---------- bootstrap born-conformant ----------

def test_bootstrap_wrangler_is_stack_aware():
    from portfolio.bootstrap import _wrangler_jsonc
    assert nf.not_found_value(_wrangler_jsonc("s.com", "2026-11-25")) == "404-page"
    assert nf.not_found_value(_wrangler_jsonc("s.com", "2026-11-25", spa=True)) == "single-page-application"


def test_cf_safety_fixes_astro_gets_404_page_and_static_value(tmp_path):
    from portfolio.bootstrap import _apply_cf_safety_fixes
    d = tmp_path / "s.com"
    d.mkdir()
    (d / "astro.config.mjs").write_text("")
    fixes = _apply_cf_safety_fixes(d, "s.com", "2026-11-25", "astro")
    assert nf.not_found_value((d / "wrangler.jsonc").read_text()) == "404-page"
    assert (d / "src" / "pages" / "404.astro").is_file()
    assert any("404" in f for f in fixes)


def test_cf_safety_fixes_spa_keeps_fallback_and_no_404_page(tmp_path):
    from portfolio.bootstrap import _apply_cf_safety_fixes
    d = tmp_path / "s.com"
    d.mkdir()
    _apply_cf_safety_fixes(d, "s.com", "2026-11-25", "vite")
    assert nf.not_found_value((d / "wrangler.jsonc").read_text()) == "single-page-application"
    assert not (d / "src" / "pages" / "404.astro").exists()
