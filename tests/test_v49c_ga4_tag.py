"""v49.C — CHECK_163 ga4-tag-in-source + per-stack injection fixer."""
from __future__ import annotations

from pathlib import Path

from portfolio.checks.seo import check_163_ga4_tag_in_source as c163

GA = "G-TEST123ABC"
TOML = f'schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n\n[analytics]\nga4_id = "{GA}"\n'

ASTRO_LAYOUT = """---
import "../styles/global.css";
const { title } = Astro.props;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <title>{title}</title>
  </head>
  <body><slot /></body>
</html>
"""


def _site(tmp_path: Path, name="example.test", toml=TOML) -> Path:
    d = tmp_path / name
    (d / "src").mkdir(parents=True)
    (d / "package.json").write_text("{}")
    if toml is not None:
        (d / "lamill.toml").write_text(toml)
    return d


def _w(d: Path, rel: str, text: str) -> Path:
    p = d / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _fix(d, dry=False):
    return c163._fix(d, dry_run=dry, assume_yes=True)


# ---- check -----------------------------------------------------------------

def test_check_passes_without_recorded_id_and_na(tmp_path):
    d = _site(tmp_path, toml='schema = "lamill-toml-v1"\n\n[deploy]\nplatform = "cf-pages"\n')
    assert "CHECK_162" in c163.run(str(d)).message
    assert "n/a" in c163.run(str(tmp_path / "nope")).message


def test_check_warns_when_untagged_and_on_other_id(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    assert c163.run(str(d)).status == "warn"
    _w(d, "src/components/X.astro", '<script>gtag("config","G-OTHER99999")</script>')
    r = c163.run(str(d))
    assert r.status == "warn" and "G-OTHER99999" in r.message
    assert _fix(d).status == "manual"


# ---- Astro -----------------------------------------------------------------

def test_astro_injects_component_into_every_head_owner(tmp_path):
    d = _site(tmp_path)
    lay = _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    nf = _w(d, "src/pages/404.astro", "<html><head><title>x</title></head><body/></html>\n")
    assert _fix(d, dry=True).status == "would-fix"
    assert not (d / "src/components/Analytics.astro").exists()

    res = _fix(d)
    assert res.status == "fixed"
    comp = (d / "src/components/Analytics.astro").read_text()
    assert f'const GA_ID = "{GA}";' in comp and "googletagmanager.com/gtag/js" in comp
    lt = lay.read_text()
    assert lt.startswith('---\nimport Analytics from "../components/Analytics.astro";\nimport "../styles/global.css";')
    assert "    <Analytics />\n  </head>" in lt
    nt = nf.read_text()
    assert nt.startswith('---\nimport Analytics from "../components/Analytics.astro";\n---\n')
    assert "<Analytics />" in nt
    assert c163.run(str(d)).status == "pass"
    assert _fix(d).status == "nothing-to-do"


def test_astro_existing_analytics_component_is_manual(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    _w(d, "src/components/Analytics.astro", "<!-- plausible -->")
    assert _fix(d).status == "manual"


# ---- env-wired -------------------------------------------------------------

def test_env_wired_reads_get_committed_default(tmp_path):
    d = _site(tmp_path)
    lay = _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT.replace(
        "const { title } = Astro.props;", "const GA_ID = import.meta.env.PUBLIC_GA_ID;"))
    init = _w(d, "src/analytics/init.ts",
              "const a = import.meta.env.VITE_GA_ID?.trim();\n"
              "const b = (env.PUBLIC_GA_ID ?? env.VITE_GA_ID)?.trim();\n")
    dts = _w(d, "src/vite-env.d.ts", "interface E { readonly VITE_GA_ID?: string }\n// import.meta.env.VITE_GA_ID\n")
    res = _fix(d)
    assert res.status == "fixed" and "default" in res.summary
    assert f'const GA_ID = (import.meta.env.PUBLIC_GA_ID || "{GA}");' in lay.read_text()
    it = init.read_text()
    assert f'(import.meta.env.VITE_GA_ID || "{GA}")?.trim()' in it
    assert f'(env.PUBLIC_GA_ID ?? (env.VITE_GA_ID || "{GA}"))?.trim()' in it
    assert "|| " not in dts.read_text()
    assert not (d / "src/components/Analytics.astro").exists()
    assert _fix(d).status == "nothing-to-do"


# ---- Vite index.html / TanStack -------------------------------------------

def test_vite_index_html_gets_snippet(tmp_path):
    d = _site(tmp_path)
    idx = _w(d, "index.html", "<!doctype html>\n<html>\n  <head>\n    <title>x</title>\n  </head>\n</html>\n")
    assert _fix(d).status == "fixed"
    t = idx.read_text()
    assert f'gtag/js?id={GA}"' in t and f"gtag('config', '{GA}');" in t
    assert t.index("gtag/js") < t.index("</head>")
    assert c163.run(str(d)).status == "pass"


def test_tanstack_root_gets_jsx_scripts(tmp_path):
    d = _site(tmp_path)
    root = _w(d, "src/routes/__root.tsx",
              "function RootShell() {\n  return (\n    <html>\n      <head>\n        <HeadContent />\n"
              "      </head>\n    </html>\n  );\n}\n")
    _w(d, "index.html", "<html><head></head></html>")  # ignored when a .tsx owns </head>
    assert _fix(d).status == "fixed"
    t = root.read_text()
    assert f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA}" />' in t
    assert "dangerouslySetInnerHTML" in t and f"gtag('config', '{GA}')" in t
    assert "G-" not in (d / "index.html").read_text()


def test_no_head_anywhere_is_manual(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/App.tsx", "export default () => <div/>;")
    assert _fix(d).status == "manual"


# ---- privacy ---------------------------------------------------------------

def test_privacy_sentence_added_after_last_paragraph(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    page = _w(d, "src/pages/privacy.astro", "<main>\n    <p>One.</p>\n    <p>Two.</p>\n  <footer/></main>\n")
    res = _fix(d)
    assert res.status == "fixed" and "privacy" in res.summary
    t = page.read_text()
    assert f"<p>Two.</p>\n    <p>{c163.PRIVACY_SENTENCE}</p>" in t
    assert c163.privacy_state(d)[0] == "ok"
    assert c163.run(str(d)).status == "pass"


def test_privacy_follows_imported_component(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    _w(d, "src/pages/privacy.astro", '---\nimport PrivacyPage from "../components/pages/PrivacyPage";\n---\n<PrivacyPage />\n')
    comp = _w(d, "src/components/pages/PrivacyPage.tsx", "export default () => (<div><p>Hi.</p></div>);\n")
    _fix(d)
    assert "Google Analytics 4" in comp.read_text()


def test_privacy_follows_at_alias_import(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    _w(d, "src/pages/privacy.astro", '---\nimport { PrivacyPage } from "@/components/pages/PrivacyPage";\n---\n<PrivacyPage />\n')
    comp = _w(d, "src/components/pages/PrivacyPage.tsx", "export const PrivacyPage = () => <p>Hi.</p>;\n")
    assert c163.privacy_state(d) == ("missing", comp)


def test_privacy_saying_no_analytics_is_left_for_operator(tmp_path):
    d = _site(tmp_path)
    _w(d, "src/layouts/Layout.astro", ASTRO_LAYOUT)
    page = _w(d, "src/pages/privacy.astro", "<p><strong>No analytics.</strong> None.</p>\n")
    res = _fix(d)
    assert res.status == "fixed" and "by hand" in res.summary
    assert "Google" not in page.read_text()
    r = c163.run(str(d))
    assert r.status == "warn" and "privacy" in r.message
    assert _fix(d).status == "manual"


def test_registered_in_tier1_registry():
    from portfolio import fix_registry
    fix_registry.reset_cache()
    assert fix_registry.get_tier_1("CHECK_163") is not None
