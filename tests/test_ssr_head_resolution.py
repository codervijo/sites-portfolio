"""SSR-head resolution for the SEO meta checks (docs/bugs.md 2026-06-29).

Stacks that define the head in code (TanStack Start / Astro / Next) ship
no static index.html, so CHECK_070/071/076/077 used to skip and let a
placeholder title through. These tests lock in that they now evaluate the
in-code head.
"""
from __future__ import annotations

from portfolio.checks.seo import _read_head_html
from portfolio.checks.seo.check_070_has_title import run as run_070
from portfolio.checks.seo.check_071_has_meta_description import run as run_071
from portfolio.checks.seo.check_076_has_open_graph import run as run_076
from portfolio.checks.seo.check_077_has_twitter_card import run as run_077

# A realistic TanStack Start root head (lamill.io shape), all tags valid.
_TANSTACK_ROOT = '''
export const Route = createRootRouteWithContext()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { title: "LaMill \\u2014 Engineering Studio Portfolio Site" },
      { name: "description", content: "LaMill is an engineering studio for full-stack, Linux, hardware, and IoT systems, shipping software and content alongside your product." },
      { property: "og:title", content: "LaMill" },
      { property: "og:description", content: "Engineering studio." },
      { property: "og:url", content: "https://lamill.io/" },
      { property: "og:type", content: "website" },
      { property: "og:image", content: "https://lamill.io/og.png" },
      { name: "twitter:card", content: "summary" },
    ],
  }),
});
'''


def _tanstack_project(tmp_path, root_src=_TANSTACK_ROOT):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    routes = tmp_path / "src" / "routes"
    routes.mkdir(parents=True)
    (routes / "__root.tsx").write_text(root_src)
    return str(tmp_path)


# ---- _read_head_html synthesis ----

def test_synthesizes_head_from_tanstack_source(tmp_path):
    html = _read_head_html(_tanstack_project(tmp_path))
    assert html is not None
    assert "<title>" in html
    assert 'property="og:title"' in html
    assert 'name="twitter:card"' in html


def test_static_index_html_still_preferred(tmp_path):
    """Regression: a real index.html must still be read as before."""
    (tmp_path / "package.json").write_text('{"name": "x"}')
    (tmp_path / "index.html").write_text("<title>Static</title>")
    html = _read_head_html(str(tmp_path))
    assert "Static" in html


def test_no_head_anywhere_returns_none(tmp_path):
    (tmp_path / "package.json").write_text('{"name": "x"}')
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "util.ts").write_text("export const x = 1;")
    assert _read_head_html(str(tmp_path)) is None


# ---- the four checks now EVALUATE in-code heads (no longer skip) ----

def test_check_070_evaluates_tanstack_title(tmp_path):
    r = run_070(_tanstack_project(tmp_path))
    assert "skipped" not in r.message
    assert r.status == "pass"  # 30-60 chars


def test_check_070_flags_placeholder_title_instead_of_skipping(tmp_path):
    """The bug: a placeholder title in code used to be invisible. Now the
    check sees it (and flags it short rather than skipping)."""
    src = _TANSTACK_ROOT.replace(
        "LaMill \\u2014 Engineering Studio Portfolio Site", "Lovable App"
    )
    r = run_070(_tanstack_project(tmp_path, src))
    assert "skipped" not in r.message
    assert r.status == "warn"  # 11 chars, under 30 — but SEEN
    assert "Lovable App" in r.message


def test_check_071_evaluates_tanstack_description(tmp_path):
    r = run_071(_tanstack_project(tmp_path))
    assert "skipped" not in r.message
    assert r.status == "pass"  # 120-160 chars


def test_check_076_evaluates_tanstack_open_graph(tmp_path):
    r = run_076(_tanstack_project(tmp_path))
    assert "skipped" not in r.message
    assert r.status == "pass"  # all 5 og tags


def test_check_077_evaluates_tanstack_twitter(tmp_path):
    r = run_077(_tanstack_project(tmp_path))
    assert "skipped" not in r.message
    assert r.status == "pass"
