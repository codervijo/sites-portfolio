"""Tests for v5.C deploy-category checks (CHECK_050–CHECK_056)."""
from __future__ import annotations

import json

from portfolio.checks import run_check


# CHECK_050 — deploy-target-uniqueness

def test_check_050_pass_one_target(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    assert run_check("CHECK_050", str(tmp_path)).status == "pass"


def test_check_050_fail_multiple(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    (tmp_path / "vercel.json").write_text("{}")
    assert run_check("CHECK_050", str(tmp_path)).status == "fail"


def test_check_050_warn_none(tmp_path):
    assert run_check("CHECK_050", str(tmp_path)).status == "warn"


# CHECK_051 — wrangler-compatibility-date

def test_check_051_pass(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{"compatibility_date": "2026-01-01"}'
    )
    assert run_check("CHECK_051", str(tmp_path)).status == "pass"


def test_check_051_fail_missing_field(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    assert run_check("CHECK_051", str(tmp_path)).status == "fail"


def test_check_051_warn_no_wrangler(tmp_path):
    assert run_check("CHECK_051", str(tmp_path)).status == "warn"


def test_check_051_strips_jsonc_comments(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text(
        '// comment\n{"compatibility_date": "2026-01-01"}'
    )
    assert run_check("CHECK_051", str(tmp_path)).status == "pass"


# CHECK_052 — wrangler-assets-directory

def test_check_052_pass(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{"assets": {"directory": "./dist"}}'
    )
    assert run_check("CHECK_052", str(tmp_path)).status == "pass"


def test_check_052_fail_wrong_dir(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{"assets": {"directory": "./out"}}'
    )
    assert run_check("CHECK_052", str(tmp_path)).status == "fail"


def test_check_052_fail_no_assets_block(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    assert run_check("CHECK_052", str(tmp_path)).status == "fail"


# CHECK_053 — wrangler-no-redirects-fallback

def test_check_053_pass(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    (tmp_path / "public").mkdir()
    assert run_check("CHECK_053", str(tmp_path)).status == "pass"


def test_check_053_fail(tmp_path):
    (tmp_path / "wrangler.jsonc").write_text("{}")
    (tmp_path / "public").mkdir()
    (tmp_path / "public" / "_redirects").write_text("/* /index.html 200")
    assert run_check("CHECK_053", str(tmp_path)).status == "fail"


# CHECK_054 — wrangler-name-matches-slug

def test_check_054_pass(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    (project / "wrangler.jsonc").write_text('{"name": "kwizicle"}')
    assert run_check("CHECK_054", str(project)).status == "pass"


def test_check_054_warn_mismatch(tmp_path):
    project = tmp_path / "kwizicle.com"
    project.mkdir()
    (project / "wrangler.jsonc").write_text('{"name": "different"}')
    assert run_check("CHECK_054", str(project)).status == "warn"


# CHECK_055 — vercel-config-sane

def test_check_055_pass(tmp_path):
    (tmp_path / "vercel.json").write_text(json.dumps({"version": 2}))
    assert run_check("CHECK_055", str(tmp_path)).status == "pass"


def test_check_055_fail_invalid_json(tmp_path):
    (tmp_path / "vercel.json").write_text("{not valid json")
    assert run_check("CHECK_055", str(tmp_path)).status == "fail"


def test_check_055_warn_no_vercel(tmp_path):
    assert run_check("CHECK_055", str(tmp_path)).status == "warn"


# CHECK_056 — builder-referenced-in-makefile

def test_check_056_pass_with_builder_path(tmp_path):
    (tmp_path / "Makefile").write_text("BUILDER_PATH ?= ../builder\n")
    assert run_check("CHECK_056", str(tmp_path)).status == "pass"


def test_check_056_pass_with_make_c_parent(tmp_path):
    (tmp_path / "Makefile").write_text("dev:\n\t$(MAKE) -C .. dev\n")
    assert run_check("CHECK_056", str(tmp_path)).status == "pass"


def test_check_056_warn_plain_makefile(tmp_path):
    (tmp_path / "Makefile").write_text("dev:\n\techo dev\n")
    assert run_check("CHECK_056", str(tmp_path)).status == "warn"


def test_check_056_warn_no_makefile(tmp_path):
    assert run_check("CHECK_056", str(tmp_path)).status == "warn"
