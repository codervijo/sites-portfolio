"""Tests for v5.C stack-category checks (CHECK_030–CHECK_039)."""
from __future__ import annotations

import json

from portfolio.checks import run_check


def _write_pkg(tmp_path, **payload):
    (tmp_path / "package.json").write_text(json.dumps(payload))


# CHECK_030 — has-package-json

def test_check_030_pass(tmp_path):
    _write_pkg(tmp_path, name="x")
    assert run_check("CHECK_030", str(tmp_path)).status == "pass"


def test_check_030_warn_when_not_web(tmp_path):
    assert run_check("CHECK_030", str(tmp_path)).status == "warn"


# CHECK_031 — has-pnpm-lock

def test_check_031_pass(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / "pnpm-lock.yaml").write_text("lockfileVersion: 9")
    assert run_check("CHECK_031", str(tmp_path)).status == "pass"


def test_check_031_fail(tmp_path):
    _write_pkg(tmp_path, name="x")
    assert run_check("CHECK_031", str(tmp_path)).status == "fail"


# CHECK_032 — no-package-lock-json

def test_check_032_pass(tmp_path):
    _write_pkg(tmp_path, name="x")
    assert run_check("CHECK_032", str(tmp_path)).status == "pass"


def test_check_032_fail_when_present(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / "package-lock.json").write_text("{}")
    assert run_check("CHECK_032", str(tmp_path)).status == "fail"


# CHECK_033 — no-bun-lockb

def test_check_033_fail_when_present(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / "bun.lockb").write_bytes(b"\x00\x01")
    assert run_check("CHECK_033", str(tmp_path)).status == "fail"


# CHECK_034 — no-yarn-lock

def test_check_034_fail_when_present(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / "yarn.lock").write_text("# yarn")
    assert run_check("CHECK_034", str(tmp_path)).status == "fail"


# CHECK_035 — vite-version-ok

def test_check_035_pass_v6(tmp_path):
    _write_pkg(tmp_path, name="x", devDependencies={"vite": "^6.0.0"})
    (tmp_path / "vite.config.ts").write_text("export default {}")
    assert run_check("CHECK_035", str(tmp_path)).status == "pass"


def test_check_035_fail_v5(tmp_path):
    _write_pkg(tmp_path, name="x", devDependencies={"vite": "^5.4.0"})
    (tmp_path / "vite.config.ts").write_text("export default {}")
    assert run_check("CHECK_035", str(tmp_path)).status == "fail"


def test_check_035_warn_no_vite(tmp_path):
    _write_pkg(tmp_path, name="x")
    assert run_check("CHECK_035", str(tmp_path)).status == "warn"


# CHECK_036 — astro-version-ok

def test_check_036_pass(tmp_path):
    _write_pkg(tmp_path, name="x", dependencies={"astro": "^5.1.0"})
    (tmp_path / "astro.config.mjs").write_text("export default {}")
    assert run_check("CHECK_036", str(tmp_path)).status == "pass"


def test_check_036_warn_no_astro(tmp_path):
    _write_pkg(tmp_path, name="x")
    assert run_check("CHECK_036", str(tmp_path)).status == "warn"


# CHECK_037 — package-json-build-and-dev-scripts

def test_check_037_pass(tmp_path):
    _write_pkg(tmp_path, name="x", scripts={"build": "vite build", "dev": "vite"})
    assert run_check("CHECK_037", str(tmp_path)).status == "pass"


def test_check_037_fail_missing_dev(tmp_path):
    _write_pkg(tmp_path, name="x", scripts={"build": "vite build"})
    assert run_check("CHECK_037", str(tmp_path)).status == "fail"


# CHECK_038 — node-modules-in-gitignore

def test_check_038_pass(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / ".gitignore").write_text("node_modules/\ndist/\n")
    assert run_check("CHECK_038", str(tmp_path)).status == "pass"


def test_check_038_fail(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / ".gitignore").write_text("dist/\n")
    assert run_check("CHECK_038", str(tmp_path)).status == "fail"


# CHECK_039 — has-tsconfig

def test_check_039_pass(tmp_path):
    _write_pkg(tmp_path, name="x")
    (tmp_path / "tsconfig.json").write_text("{}")
    assert run_check("CHECK_039", str(tmp_path)).status == "pass"
