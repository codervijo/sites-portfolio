"""Tests for v18.B — static GA4 conformance checks.

Two new atomic checks fire only when CHECK_080 detected GA4
specifically (markers `gtag(` or `googletagmanager.com`). Both skip
cleanly when CHECK_080 didn't fire (Plausible-only / CF-Analytics-
only / no analytics).

  - CHECK_148 ga4-id-well-formed — extracted `G-XXX` ID matches
    `G-[A-Z0-9]{6,12}` shape.
  - CHECK_149 ga4-script-src-google — loader script src points to
    `www.googletagmanager.com/gtag/js`.
"""
from __future__ import annotations

from pathlib import Path

from portfolio.checks.seo.check_148_ga4_id_well_formed import run as run_148
from portfolio.checks.seo.check_149_ga4_script_src_google import run as run_149


def _make_site(tmp_path: Path, html: str) -> Path:
    """Minimum-shape web project — package.json + index.html — that
    passes the `_is_web_project` + `_read_index_html` preludes."""
    (tmp_path / "package.json").write_text("{}")
    (tmp_path / "index.html").write_text(html)
    return tmp_path


# Real-world sample from the operator's fleet (keralavotemap.site).
_REAL_GA4_BLOCK = """\
<!DOCTYPE html><html><head>
<script async src="https://www.googletagmanager.com/gtag/js?id=G-QG4CYZ7MXE"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-QG4CYZ7MXE');
</script>
</head></html>
"""


# ---- CHECK_148 ga4-id-well-formed -----------------------------------


def test_148_pass_on_well_formed_real_world_id(tmp_path):
    site = _make_site(tmp_path, _REAL_GA4_BLOCK)
    result = run_148(str(site))
    assert result.status == "pass"
    assert "G-QG4CYZ7MXE" in result.message


def test_148_skip_when_no_ga4_markers(tmp_path):
    """Plausible-only site → CHECK_148 must skip, not fail. CHECK_080
    handles the broader 'has analytics' question; CHECK_148 only
    speaks to GA4 specifically."""
    plausible_html = '<html><head><script defer data-domain="x.com" src="https://plausible.io/js/script.js"></script></head></html>'
    site = _make_site(tmp_path, plausible_html)
    result = run_148(str(site))
    assert result.status == "warn"
    assert "skipped" in result.message


def test_148_fail_on_placeholder_id(tmp_path):
    """Common copy/paste failure mode: operator leaves `G-XXXXXX`
    placeholder from a code snippet. ID shape allows uppercase
    A-Z + digits, so `G-XXXXXX` (6 X's) DOES match the regex —
    but real-world GA4 IDs are 10 chars and never all-letter. This
    test instead targets the lowercase-leak failure mode which the
    regex catches."""
    html = '<script src="https://www.googletagmanager.com/gtag/js?id=G-abc123"></script>'
    site = _make_site(tmp_path, html)
    result = run_148(str(site))
    assert result.status == "fail"
    assert "malformed" in result.message.lower()
    assert "G-abc123" in result.message


def test_148_fail_when_markers_present_but_no_id_extractable(tmp_path):
    """gtag() function called but no `G-` ID anywhere in the page —
    the analytics is wired to nothing."""
    html = '<script>gtag("event", "page_view");</script>'
    site = _make_site(tmp_path, html)
    result = run_148(str(site))
    assert result.status == "fail"
    assert "no `G-" in result.message


def test_148_skip_when_not_a_web_project(tmp_path):
    # No package.json
    (tmp_path / "index.html").write_text(_REAL_GA4_BLOCK)
    result = run_148(str(tmp_path))
    assert result.status == "warn"
    assert "not a web project" in result.message


def test_148_pass_when_multiple_consistent_ids(tmp_path):
    """Real-world install repeats the ID — loader src + gtag('config')
    call. CHECK_148 dedupes and accepts when all are well-formed."""
    site = _make_site(tmp_path, _REAL_GA4_BLOCK)
    result = run_148(str(site))
    assert result.status == "pass"
    # The ID should appear ONCE in the message (deduped) even though
    # the HTML has it twice.
    assert result.message.count("G-QG4CYZ7MXE") == 1


# ---- CHECK_149 ga4-script-src-google --------------------------------


def test_149_pass_on_real_world_install(tmp_path):
    site = _make_site(tmp_path, _REAL_GA4_BLOCK)
    result = run_149(str(site))
    assert result.status == "pass"


def test_149_skip_when_no_ga4_markers(tmp_path):
    """No `gtag(` inline marker → not a GA4 install, skip."""
    plausible_html = '<script defer data-domain="x.com" src="https://plausible.io/js/script.js"></script>'
    site = _make_site(tmp_path, plausible_html)
    result = run_149(str(site))
    assert result.status == "warn"
    assert "skipped" in result.message


def test_149_fail_on_inline_only_no_loader(tmp_path):
    """The classic broken install: operator pasted the inline
    `gtag('config', ...)` block but forgot the loader `<script>`
    tag above it. gtag function never defined at runtime."""
    html = """\
<html><head>
<script>
  function gtag(){dataLayer.push(arguments);}
  gtag('config', 'G-QG4CYZ7MXE');
</script>
</head></html>
"""
    site = _make_site(tmp_path, html)
    result = run_149(str(site))
    assert result.status == "fail"
    assert "loader" in result.message.lower()


def test_149_fail_on_typod_loader_src(tmp_path):
    """Operator typo'd the CDN host — loader points to a non-existent
    domain. Library never loads."""
    html = """\
<script async src="https://www.googletagmanger.com/gtag/js?id=G-QG4CYZ7MXE"></script>
<script>gtag('config', 'G-QG4CYZ7MXE');</script>
"""
    site = _make_site(tmp_path, html)
    result = run_149(str(site))
    assert result.status == "fail"


def test_149_skip_when_not_a_web_project(tmp_path):
    (tmp_path / "index.html").write_text(_REAL_GA4_BLOCK)
    result = run_149(str(tmp_path))
    assert result.status == "warn"
    assert "not a web project" in result.message


def test_149_accepts_both_quoting_styles(tmp_path):
    """Loader src might be in single or double quotes. Both valid."""
    html_single = "<script async src='https://www.googletagmanager.com/gtag/js?id=G-X'></script><script>gtag('init')</script>"
    site = _make_site(tmp_path, html_single)
    assert run_149(str(site)).status == "pass"


# ---- Registry / catalog wiring --------------------------------------


def test_148_149_discoverable_via_registry():
    """Both checks must auto-discover via `list_checks()` so they
    actually fire on `project check` runs."""
    from portfolio.checks import list_checks

    ids = {c.id for c in list_checks()}
    assert "CHECK_148" in ids
    assert "CHECK_149" in ids
