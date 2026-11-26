"""v50.D — CHECK_166 `email-footer-link` + the source-edit build check."""
from __future__ import annotations

from pathlib import Path

import pytest

import portfolio.email_routing as er
from portfolio.checks.deploy import check_166_email_footer_link as c166
from portfolio.fix_helpers import FixerSpec, FixResult

D = "footer-test.com"


def _site(tmp_path: Path) -> Path:
    base = tmp_path / D
    (base / "src").mkdir(parents=True)
    return base


def _w(base: Path, rel: str, text: str) -> Path:
    p = base / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


def _state(**kw) -> er.EmailState:
    st = er.EmailState(domain=D, forward_to="hello@lamill.io",
                       addresses=[f"hello@{D}"], on_cloudflare=True, zone_status="active")
    for k, v in kw.items():
        setattr(st, k, v)
    return st


READY = dict(routing_enabled=True, routing_status="ready",
             rules={f"hello@{D}": ["hello@lamill.io"]}, dest_exists=True, dest_verified=True)


@pytest.fixture
def mail(monkeypatch):
    box = {"st": _state(**READY)}
    monkeypatch.setattr(er, "inspect", lambda *a, **k: box["st"])
    return box


ASTRO_LAYOUT = """---
import Footer from "../components/Footer.astro";
---
<html><head><title>x</title></head>
<body><slot /><Footer /></body></html>
"""

ASTRO_FOOTER = """<footer class="site-footer">
  <ul class="links">
    <li class="item"><a class="link" href="/about/">About</a></li>
    <li class="item"><a class="link" href="/privacy/">Privacy</a></li>
  </ul>
</footer>
"""


def _astro(base: Path) -> Path:
    _w(base, "src/layouts/Base.astro", ASTRO_LAYOUT)
    return _w(base, "src/components/Footer.astro", ASTRO_FOOTER)


# ---------------------------------------------------------------- check


def test_check_warns_when_footer_lacks_mailto(tmp_path):
    base = _site(tmp_path)
    _astro(base)
    r = c166.run(str(base))
    assert r.status == "warn" and "Footer.astro" in r.message


def test_check_passes_on_existing_own_domain_mailto(tmp_path):
    base = _site(tmp_path)
    f = _astro(base)
    f.write_text(f.read_text().replace("</ul>", f'<li><a href="mailto:info@{D}">x</a></li></ul>'))
    assert c166.run(str(base)).status == "pass"


def test_check_other_domain_mailto_does_not_count(tmp_path):
    base = _site(tmp_path)
    f = _astro(base)
    f.write_text(f.read_text().replace("</ul>", '<li><a href="mailto:me@gmail.com">x</a></li></ul>'))
    assert c166.run(str(base)).status == "warn"


def test_check_no_footer_is_manual_warn(tmp_path):
    base = _site(tmp_path)
    _w(base, "src/layouts/Base.astro", "<html><head></head><body><slot /></body></html>")
    r = c166.run(str(base))
    assert r.status == "warn" and "by hand" in r.message


def test_not_applicable_for_non_domain_dir(tmp_path):
    base = tmp_path / "notadomain"
    base.mkdir()
    assert "n/a" in c166.run(str(base)).message


def test_footer_not_site_wide_is_ignored(tmp_path):
    base = _site(tmp_path)
    _w(base, "src/layouts/Base.astro", "<html><head></head><body><slot /></body></html>")
    _w(base, "src/components/Footer.astro", ASTRO_FOOTER)   # imported by nobody
    assert c166.footer_targets(base) == []


# ---------------------------------------------------------------- fixer


def test_fixer_clones_li_style_and_is_idempotent(tmp_path, mail):
    base = _site(tmp_path)
    f = _astro(base)
    r = c166._apply(base, dry_run=False, assume_yes=True)
    assert r.status == "fixed"
    text = f.read_text()
    assert f'<li class="item"><a href="mailto:hello@{D}" class="link">hello@{D}</a></li>' in text
    assert text.index("Privacy") < text.index("mailto:")
    assert c166.run(str(base)).status == "pass"
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "nothing-to-do"


def test_fixer_waits_for_check_165(tmp_path, mail):
    base = _site(tmp_path)
    f = _astro(base)
    mail["st"] = _state(dest_exists=True, dest_verified=False)
    r = c166._apply(base, dry_run=False, assume_yes=True)
    assert r.status == "manual" and "CHECK_165" in r.summary
    assert "mailto" not in f.read_text()


def test_fixer_other_provider_uses_known_address(tmp_path, mail):
    base = _site(tmp_path)
    f = _astro(base)
    _w(base, "src/pages/contact.astro", f'<a href="mailto:info@{D}">info@{D}</a>')
    mail["st"] = _state(other_provider="Google Workspace", mx_hosts=["aspmx.l.google.com"])
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "fixed"
    assert f"mailto:info@{D}" in f.read_text()


def test_fixer_other_provider_without_known_address_is_manual(tmp_path, mail):
    base = _site(tmp_path)
    _astro(base)
    mail["st"] = _state(other_provider="Zoho")
    r = c166._apply(base, dry_run=False, assume_yes=True)
    assert r.status == "manual" and "Zoho" in r.summary


def test_fixer_dry_run_writes_nothing(tmp_path, mail):
    base = _site(tmp_path)
    f = _astro(base)
    r = c166._apply(base, dry_run=True, assume_yes=True)
    assert r.status == "would-fix" and "mailto" not in f.read_text()


def test_fixer_no_footer_is_manual(tmp_path, mail):
    base = _site(tmp_path)
    _w(base, "src/layouts/Base.astro", "<html><head></head><body></body></html>")
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "manual"


def test_react_footer_two_hops(tmp_path, mail):
    base = _site(tmp_path)
    _w(base, "index.html", '<html><head></head><body><script type="module" src="/src/main.jsx"></script></body></html>')
    _w(base, "src/main.jsx", "import App from './App.jsx';\n")
    _w(base, "src/App.jsx", "import Footer from './components/Footer.jsx';\nexport default () => <><main/><Footer/></>;\n")
    f = _w(base, "src/components/Footer.jsx", (
        "export default function Footer() {\n"
        "  return (\n"
        "    <footer className=\"f\">\n"
        "      <a className=\"fl\" href=\"/\">Home</a> · <a className=\"fl\" href=\"/terms\">Terms</a>\n"
        "    </footer>\n"
        "  );\n"
        "}\n"))
    assert c166.footer_targets(base) == [f]
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "fixed"
    assert f'Terms</a> · <a href="mailto:hello@{D}" className="fl">hello@{D}</a>' in f.read_text()


def test_vite_index_html_footer_without_links(tmp_path, mail):
    base = tmp_path / D
    base.mkdir()
    idx = _w(base, "index.html", "<html><head></head><body>\n  <footer>\n    <p>© site</p>\n  </footer>\n</body></html>\n")
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "fixed"
    assert f'    <p><a href="mailto:hello@{D}">hello@{D}</a></p>\n  </footer>' in idx.read_text()


def test_mapped_links_are_not_cloned(tmp_path, mail):
    base = _site(tmp_path)
    _w(base, "src/layouts/Base.astro", ASTRO_LAYOUT)
    f = _w(base, "src/components/Footer.astro", (
        "<footer>\n  <nav>\n    {links.map((l) => <a class=\"x\" href={l.href}>{l.label}</a>)}\n  </nav>\n</footer>\n"))
    assert c166._apply(base, dry_run=False, assume_yes=True).status == "fixed"
    text = f.read_text()
    assert text.count("links.map") == 1 and f'  <p><a href="mailto:hello@{D}">' in text


def test_add_footer_link_needs_no_mail_gate(tmp_path):
    base = _site(tmp_path)
    f = _astro(base)   # conftest makes inspect raise; add_footer_link never calls it
    assert c166.add_footer_link(base, f"hello@{D}", dry_run=False).status == "fixed"
    assert f"mailto:hello@{D}" in f.read_text()


# ---------------------------------------------------------------- build gate


def _spec(edits: bool) -> FixerSpec:
    return FixerSpec(check_id="CHECK_X", tier=1, summary="", apply=lambda *a: None,
                     edits_source=edits)


def test_build_gate_restores_on_failed_build(tmp_path):
    from portfolio.fix_build import BuildGate
    base = _site(tmp_path)
    f = _w(base, "src/components/Footer.astro", "before")
    gate = BuildGate(base, build=lambda b: (False, "build failed (exit 1)"))
    f.write_text("after")
    new = _w(base, "src/components/New.astro", "x")
    gate.record(_spec(True), FixResult("fixed", "", [f, new]))
    out = gate.finish()
    assert out.kind == "failed" and "reverted" in out.detail
    assert f.read_text() == "before" and not new.exists()


def test_build_gate_keeps_edits_on_pass_and_skips_config_only(tmp_path):
    from portfolio.fix_build import BuildGate
    base = _site(tmp_path)
    f = _w(base, "src/components/Footer.astro", "before")
    calls = []
    gate = BuildGate(base, build=lambda b: (calls.append(b), (True, "build OK"))[1])
    gate.record(_spec(False), FixResult("fixed", "", [base / "lamill.toml"]))
    assert not gate.needed
    f.write_text("after")
    gate.record(_spec(True), FixResult("fixed", "", [f]))
    assert gate.finish().kind == "built" and f.read_text() == "after" and calls == [base]


def test_fixers_marked_as_source_editing():
    from portfolio.fix_registry import get_tier_1, reset_cache
    reset_cache()
    assert get_tier_1("CHECK_166").edits_source
    assert get_tier_1("CHECK_163").edits_source
    assert not get_tier_1("CHECK_165").edits_source
