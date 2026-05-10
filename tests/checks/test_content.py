"""Tests for v5.G content-pipeline checks (CHECK_130–CHECK_137).

Auto-skip pattern: every check returns warn-skip when `seo/` is absent;
this keeps non-content projects clean (no false failures) while still
running the catalog uniformly.
"""
from __future__ import annotations

import json

from portfolio.checks import run_check


def _make_content_project(tmp_path):
    """Create the minimum scaffolding to make _is_content_project() True."""
    seo = tmp_path / "seo"
    seo.mkdir()
    return seo


# ---------- CHECK_130 — has-seo-dir (the gate) ----------


def test_check_130_pass_when_seo_dir_exists(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_130", str(tmp_path)).status == "pass"


def test_check_130_skips_when_no_seo_dir(tmp_path):
    """No `seo/` → skipped (not a fail). Most web projects fall here."""
    r = run_check("CHECK_130", str(tmp_path))
    assert r.status == "warn"
    assert "skipped" in r.message


# ---------- CHECK_131-137 — auto-skip on non-content projects ----------


def test_all_content_checks_skip_on_non_content_project(tmp_path):
    """A bare project (no seo/) gets warn-skip on every CHECK_13x — no
    false failures noised through."""
    for cid in ("CHECK_131", "CHECK_132", "CHECK_133", "CHECK_134",
                "CHECK_135", "CHECK_136", "CHECK_137"):
        r = run_check(cid, str(tmp_path))
        assert r.status == "warn", f"{cid} should warn-skip, got {r.status}"
        assert "skipped" in r.message, f"{cid} message: {r.message!r}"


# ---------- per-check pass + fail cases ----------


def test_check_131_pass(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert run_check("CHECK_131", str(tmp_path)).status == "pass"


def test_check_131_fail_when_pyproject_missing(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_131", str(tmp_path)).status == "fail"


def test_check_132_pass(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "uv.lock").write_text("# uv lockfile\n")
    assert run_check("CHECK_132", str(tmp_path)).status == "pass"


def test_check_132_fail(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_132", str(tmp_path)).status == "fail"


def test_check_133_pass(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "CLAUDE.md").write_text("# orientation\n")
    assert run_check("CHECK_133", str(tmp_path)).status == "pass"


def test_check_133_fail(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_133", str(tmp_path)).status == "fail"


def test_check_134_accepts_canonical_name(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "SEO_PIPELINE_PROMPT.md").write_text("prompt template")
    assert run_check("CHECK_134", str(tmp_path)).status == "pass"


def test_check_134_accepts_short_name(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "SEO_PIPELINE.md").write_text("prompt template")
    assert run_check("CHECK_134", str(tmp_path)).status == "pass"


def test_check_134_fail(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_134", str(tmp_path)).status == "fail"


def test_check_135_pass_topics_json(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "topics.json").write_text(json.dumps({"topics": []}))
    assert run_check("CHECK_135", str(tmp_path)).status == "pass"


def test_check_135_pass_content_plan_json(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "content-plan.json").write_text(json.dumps([]))
    assert run_check("CHECK_135", str(tmp_path)).status == "pass"


def test_check_135_fail_invalid_json(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "topics.json").write_text("{not valid json")
    r = run_check("CHECK_135", str(tmp_path))
    assert r.status == "fail"
    assert "invalid" in r.message.lower()


def test_check_135_fail_when_neither_present(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_135", str(tmp_path)).status == "fail"


def test_check_136_pass(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "Makefile.pipeline").write_text("step1:\n\techo hi\n")
    assert run_check("CHECK_136", str(tmp_path)).status == "pass"


def test_check_136_fail(tmp_path):
    _make_content_project(tmp_path)
    assert run_check("CHECK_136", str(tmp_path)).status == "fail"


def test_check_137_pass(tmp_path):
    seo = _make_content_project(tmp_path)
    (seo / "tests").mkdir()
    assert run_check("CHECK_137", str(tmp_path)).status == "pass"


def test_check_137_warn_when_no_tests_dir(tmp_path):
    """Severity: info. Missing test dir is `warn`, not `fail`."""
    _make_content_project(tmp_path)
    r = run_check("CHECK_137", str(tmp_path))
    assert r.status == "warn"
