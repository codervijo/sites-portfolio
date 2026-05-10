"""Tests for v5.C SEO-category checks (CHECK_060–CHECK_080)."""
from __future__ import annotations

import json

from portfolio.checks import run_check


def _make_web_project(tmp_path):
    """Minimal scaffold that lets all SEO checks see this as a web project."""
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    (tmp_path / "public").mkdir()
    return tmp_path


def _write_index_html(tmp_path, body: str) -> None:
    (tmp_path / "index.html").write_text(body)


_FULL_HTML = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>A clear and reasonable page title here today</title>
    <meta name="description" content="{desc}" />
    <link rel="canonical" href="https://example.com/" />
    <meta name="robots" content="index, follow" />
    <meta property="og:title" content="t" />
    <meta property="og:description" content="d" />
    <meta property="og:url" content="https://example.com/" />
    <meta property="og:type" content="website" />
    <meta property="og:image" content="https://example.com/x.png" />
    <meta name="twitter:card" content="summary_large_image" />
    <script type="application/ld+json">
      {{"@context": "https://schema.org", "@type": "WebSite", "name": "Example"}}
    </script>
    <script src="https://www.googletagmanager.com/gtag/js?id=G-XYZ"></script>
  </head>
  <body></body>
</html>
"""

# Reasonable description (~140 chars) so meta-description check passes.
_DESC = "a" * 140


def _write_full_index(tmp_path):
    _write_index_html(tmp_path, _FULL_HTML.format(desc=_DESC))


# ---------- assets ----------

# CHECK_060 — has-favicon (severity: error — branding leak signal)

def test_check_060_pass(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "public" / "favicon.svg").write_text("<svg/>")
    assert run_check("CHECK_060", str(tmp_path)).status == "pass"


def test_check_060_fail(tmp_path):
    _make_web_project(tmp_path)
    assert run_check("CHECK_060", str(tmp_path)).status == "fail"


def test_check_060_severity_is_error():
    """Branding leak (default favicon visible to visitors) is an error,
    not a warning."""
    from portfolio.checks import get_check
    spec = get_check("CHECK_060")
    assert spec.severity == "error"


def test_check_060_fails_on_lovable_default(tmp_path):
    """A favicon whose SHA-256 matches a known AI-scaffolder default
    fails with a clear "replace before shipping" message — even though
    a file is technically present."""
    _make_web_project(tmp_path)
    # Bytes from sites/newiniot.com/public/favicon.ico (verified 2026-05-09).
    # Round-trip the file content to keep the test self-contained — we
    # don't ship the binary, we reproduce its hash by writing a payload
    # whose SHA-256 we already registered. Easiest way: monkey-patch
    # the registered hashes to include a hash we control.
    import hashlib

    payload = b"this-is-a-fake-lovable-favicon-payload"
    digest = hashlib.sha256(payload).hexdigest()

    from portfolio.checks.seo import check_060_has_favicon as mod
    original = dict(mod._KNOWN_DEFAULT_FAVICON_HASHES)
    mod._KNOWN_DEFAULT_FAVICON_HASHES[digest] = "Lovable"
    try:
        (tmp_path / "public" / "favicon.ico").write_bytes(payload)
        result = run_check("CHECK_060", str(tmp_path))
        assert result.status == "fail"
        assert "Lovable" in result.message
        assert "replace" in result.message.lower()
    finally:
        mod._KNOWN_DEFAULT_FAVICON_HASHES.clear()
        mod._KNOWN_DEFAULT_FAVICON_HASHES.update(original)


def test_check_060_real_lovable_hash_is_registered():
    """Smoke check: the known-Lovable hash from newiniot.com is registered."""
    from portfolio.checks.seo.check_060_has_favicon import (
        _KNOWN_DEFAULT_FAVICON_HASHES,
    )
    lovable = "dd821076a9b03adc2173c93956226aea3d92482d7578fc4339c5d3a2e9c24586"
    assert lovable in _KNOWN_DEFAULT_FAVICON_HASHES
    assert _KNOWN_DEFAULT_FAVICON_HASHES[lovable] == "Lovable"


# CHECK_061 — has-robots-txt

def test_check_061_pass(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "public" / "robots.txt").write_text("User-agent: *\n")
    assert run_check("CHECK_061", str(tmp_path)).status == "pass"


def test_check_061_fail(tmp_path):
    _make_web_project(tmp_path)
    assert run_check("CHECK_061", str(tmp_path)).status == "fail"


# CHECK_062 — robots-mentions-sitemap

def test_check_062_pass(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "public" / "robots.txt").write_text(
        "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
    )
    assert run_check("CHECK_062", str(tmp_path)).status == "pass"


def test_check_062_fail(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "public" / "robots.txt").write_text("User-agent: *\n")
    assert run_check("CHECK_062", str(tmp_path)).status == "fail"


# CHECK_063 — has-sitemap-xml

def test_check_063_pass_static(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "public" / "sitemap.xml").write_text("<urlset/>")
    assert run_check("CHECK_063", str(tmp_path)).status == "pass"


def test_check_063_pass_generator(tmp_path):
    _make_web_project(tmp_path)
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "generate-sitemap.mjs").write_text("// gen")
    assert run_check("CHECK_063", str(tmp_path)).status == "pass"


def test_check_063_fail(tmp_path):
    _make_web_project(tmp_path)
    assert run_check("CHECK_063", str(tmp_path)).status == "fail"


# CHECK_064 — sitemap-in-build-script

def test_check_064_pass_astro(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x",
        "dependencies": {"@astrojs/sitemap": "^3.0.0"},
    }))
    assert run_check("CHECK_064", str(tmp_path)).status == "pass"


def test_check_064_pass_vite_chained(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x",
        "scripts": {"build": "vite build && node scripts/generate-sitemap.mjs"},
    }))
    assert run_check("CHECK_064", str(tmp_path)).status == "pass"


def test_check_064_warn_neither(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x",
        "scripts": {"build": "vite build"},
    }))
    assert run_check("CHECK_064", str(tmp_path)).status == "warn"


# ---------- meta tags ----------

# CHECK_070 — has-title-tag

def test_check_070_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_070", str(tmp_path)).status == "pass"


def test_check_070_fail_no_title(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head><body></body></html>")
    assert run_check("CHECK_070", str(tmp_path)).status == "fail"


def test_check_070_warn_too_short(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head><title>x</title></head></html>")
    assert run_check("CHECK_070", str(tmp_path)).status == "warn"


# CHECK_071 — has-meta-description

def test_check_071_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_071", str(tmp_path)).status == "pass"


def test_check_071_fail_missing(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head><title>t</title></head></html>")
    assert run_check("CHECK_071", str(tmp_path)).status == "fail"


# CHECK_072 — has-canonical-link

def test_check_072_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_072", str(tmp_path)).status == "pass"


def test_check_072_fail(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_072", str(tmp_path)).status == "fail"


# CHECK_073 — has-meta-viewport

def test_check_073_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_073", str(tmp_path)).status == "pass"


def test_check_073_fail(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_073", str(tmp_path)).status == "fail"


# CHECK_074 — has-html-lang

def test_check_074_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_074", str(tmp_path)).status == "pass"


def test_check_074_fail_no_lang(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_074", str(tmp_path)).status == "fail"


# CHECK_075 — has-meta-robots

def test_check_075_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_075", str(tmp_path)).status == "pass"


def test_check_075_warn_missing(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_075", str(tmp_path)).status == "warn"


# CHECK_076 — has-open-graph

def test_check_076_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_076", str(tmp_path)).status == "pass"


def test_check_076_fail_none(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_076", str(tmp_path)).status == "fail"


def test_check_076_warn_partial(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, """
<html><head>
  <meta property="og:title" content="t"/>
  <meta property="og:description" content="d"/>
</head></html>
""")
    assert run_check("CHECK_076", str(tmp_path)).status == "warn"


# CHECK_077 — has-twitter-card

def test_check_077_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_077", str(tmp_path)).status == "pass"


def test_check_077_fail(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_077", str(tmp_path)).status == "fail"


# CHECK_078 — has-json-ld

def test_check_078_pass(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_078", str(tmp_path)).status == "pass"


def test_check_078_fail(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_078", str(tmp_path)).status == "fail"


# CHECK_079 — json-ld-org-or-website

def test_check_079_pass_website(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_079", str(tmp_path)).status == "pass"


def test_check_079_pass_organization(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, """
<html><head>
  <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Organization", "name": "X"}
  </script>
</head></html>
""")
    assert run_check("CHECK_079", str(tmp_path)).status == "pass"


def test_check_079_pass_via_graph(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, """
<html><head>
  <script type="application/ld+json">
    {"@context": "https://schema.org", "@graph": [{"@type": "WebSite"}, {"@type": "WebPage"}]}
  </script>
</head></html>
""")
    assert run_check("CHECK_079", str(tmp_path)).status == "pass"


def test_check_079_fail_other_type(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, """
<html><head>
  <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "Article", "name": "X"}
  </script>
</head></html>
""")
    assert run_check("CHECK_079", str(tmp_path)).status == "fail"


# CHECK_080 — has-analytics

def test_check_080_pass_gtm(tmp_path):
    _make_web_project(tmp_path)
    _write_full_index(tmp_path)
    assert run_check("CHECK_080", str(tmp_path)).status == "pass"


def test_check_080_pass_plausible(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, '<html><head><script defer src="https://plausible.io/js/x.js"></script></head></html>')
    assert run_check("CHECK_080", str(tmp_path)).status == "pass"


def test_check_080_warn_none(tmp_path):
    _make_web_project(tmp_path)
    _write_index_html(tmp_path, "<html><head></head></html>")
    assert run_check("CHECK_080", str(tmp_path)).status == "warn"


# ---------- Astro template path ----------

def test_seo_checks_read_astro_index(tmp_path):
    (tmp_path / "package.json").write_text(json.dumps({"name": "x"}))
    src_pages = tmp_path / "src" / "pages"
    src_pages.mkdir(parents=True)
    (src_pages / "index.astro").write_text(
        """---
import Layout from '../layouts/Layout.astro';
---
<html lang="en">
  <head>
    <title>An Astro page with a clear title here</title>
    <meta name="viewport" content="width=device-width" />
  </head>
  <body></body>
</html>
"""
    )
    assert run_check("CHECK_073", str(tmp_path)).status == "pass"
    assert run_check("CHECK_074", str(tmp_path)).status == "pass"
    assert run_check("CHECK_070", str(tmp_path)).status == "pass"
