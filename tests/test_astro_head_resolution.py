"""Astro static head resolution for the SEO meta checks (docs/bugs.md 2026-07-03).

Astro pages write `<title>{title}</title>` (a frontmatter const) and delegate
`<html>`/`<head>` to an imported layout. The checks used to read the raw
.astro and false-fail (literal `{title}`, no `<html>`). These lock in that
they now resolve the frontmatter const + merge the layout head.
"""
from __future__ import annotations

from portfolio.checks.seo import _read_head_html
from portfolio.checks.seo.check_070_has_title import run as run_070
from portfolio.checks.seo.check_071_has_meta_description import run as run_071
from portfolio.checks.seo.check_073_has_viewport import run as run_073
from portfolio.checks.seo.check_074_has_html_lang import run as run_074
from portfolio.checks.seo.check_079_json_ld_org_or_website import run as run_079
from portfolio.checks.seo import _jsonld_scripts

_BASE_ASTRO = """---
const brand = "DonReady";
---
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <slot name="head" />
  </head>
  <body><slot /></body>
</html>
"""

_INDEX_ASTRO = """---
import Base from "../layouts/Base.astro";
const title = "DonReady — Find scrubs that actually fit before you buy";
const description = "Compare scrub brands side by side, find the size that actually fits before you buy, and stay within your workplace dress code. Free.";
---
<Base>
  <Fragment slot="head">
    <title>{title}</title>
    <meta name="description" content={description} />
  </Fragment>
  <h1>{title}</h1>
</Base>
"""


def _astro_project(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    pages = tmp_path / "src" / "pages"
    pages.mkdir(parents=True)
    layouts = tmp_path / "src" / "layouts"
    layouts.mkdir(parents=True)
    (layouts / "Base.astro").write_text(_BASE_ASTRO)
    (pages / "index.astro").write_text(_INDEX_ASTRO)
    return str(tmp_path)


def test_head_html_resolves_const_and_merges_layout(tmp_path):
    html = _read_head_html(_astro_project(tmp_path))
    assert "<title>DonReady — Find scrubs" in html   # {title} resolved
    assert "{title}" not in html.split("</head>")[0] if "</head>" in html else "{title}" not in html
    assert 'lang="en"' in html                       # merged from Base layout
    assert "viewport" in html                        # merged from Base layout


def test_check_070_resolves_title(tmp_path):
    r = run_070(_astro_project(tmp_path))
    assert r.status == "pass"
    assert "DonReady" in r.message and "{title}" not in r.message


def test_check_071_resolves_description(tmp_path):
    r = run_071(_astro_project(tmp_path))
    assert r.status == "pass"               # 120-160 chars, resolved


def test_check_073_finds_layout_viewport(tmp_path):
    assert run_073(_astro_project(tmp_path)).status == "pass"


def test_check_074_finds_layout_html_lang(tmp_path):
    r = run_074(_astro_project(tmp_path))
    assert r.status == "pass"
    assert 'en' in r.message


def test_plain_index_html_unaffected(tmp_path):
    """Non-Astro (Vite) index.html is returned as-is, not Astro-processed."""
    (tmp_path / "package.json").write_text('{"name": "x"}')
    (tmp_path / "index.html").write_text("<title>Plain Vite Title Here OK</title>")
    assert "Plain Vite Title" in _read_head_html(str(tmp_path))


# ---- JSON-LD via framework idioms (CHECK_079, docs/bugs.md 2026-07-03) ----

def test_jsonld_astro_sethtml_inline_graph():
    """Astro `set:html={JSON.stringify({@graph:[Org, WebSite]})}` — inline."""
    src = (
        '<script type="application/ld+json" set:html={JSON.stringify({'
        '"@context":"https://schema.org","@graph":['
        '{"@type":"Organization","name":"X"},'
        '{"@type":"WebSite","url":"https://x/"}]})} />'
    )
    scripts = " ".join(_jsonld_scripts(src))
    assert '"@type":"Organization"' in scripts
    assert '"@type":"WebSite"' in scripts


def test_jsonld_tanstack_script_ldjson_const():
    """TanStack `"script:ld+json": constName` where const is an object."""
    src = (
        'const homeJsonLd = { "@context": "https://schema.org", '
        '"@type": "ProfessionalService", name: "LaMill" };\n'
        'meta: [{ "script:ld+json": homeJsonLd }]'
    )
    scripts = " ".join(_jsonld_scripts(src))
    assert '"@type":"ProfessionalService"' in scripts


def test_check_079_astro_inline_org(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    pages = tmp_path / "src" / "pages"
    pages.mkdir(parents=True)
    (pages / "index.astro").write_text(
        '---\nconst site = "https://x";\n---\n'
        '<script type="application/ld+json" set:html={JSON.stringify({'
        '"@context":"https://schema.org","@type":"Organization","name":"X"})} />'
        '<title>X</title>'
    )
    assert run_079(str(tmp_path)).status == "pass"


def test_check_079_accepts_org_subtype(tmp_path):
    """ProfessionalService / LocalBusiness etc. satisfy 'has an org entity'."""
    (tmp_path / "package.json").write_text('{"name": "x"}')
    (tmp_path / "index.html").write_text(
        '<script type="application/ld+json">'
        '{"@context":"https://schema.org","@type":"ProfessionalService"}</script>'
        '<title>X</title>'
    )
    assert run_079(str(tmp_path)).status == "pass"
