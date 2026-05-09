"""Tests for v5.A scaffold-category checks (CHECK_001–CHECK_012).

Each test creates a tmp_path repo with the right (or wrong) shape and runs
the corresponding check.
"""
from __future__ import annotations

from portfolio.checks import run_check


# CHECK_001 — has-readme

def test_check_001_pass(tmp_path):
    (tmp_path / "README.md").write_text("# repo")
    r = run_check("CHECK_001", str(tmp_path))
    assert r.status == "pass"


def test_check_001_fail_missing(tmp_path):
    r = run_check("CHECK_001", str(tmp_path))
    assert r.status == "fail"


# CHECK_002 — has-ai-agents-md

def test_check_002_pass(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("orientation")
    r = run_check("CHECK_002", str(tmp_path))
    assert r.status == "pass"


def test_check_002_fail(tmp_path):
    assert run_check("CHECK_002", str(tmp_path)).status == "fail"


# CHECK_003 — ai-agents-md-has-building-info

def test_check_003_pass_with_section(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(
        "# header\n\n## Building info\nSee `~/work/projects/builder/` and `../Makefile`.\n"
    )
    r = run_check("CHECK_003", str(tmp_path))
    assert r.status == "pass"


def test_check_003_fail_no_section(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("# header\n\nno building section")
    assert run_check("CHECK_003", str(tmp_path)).status == "fail"


def test_check_003_fail_no_file(tmp_path):
    assert run_check("CHECK_003", str(tmp_path)).status == "fail"


# CHECK_004 — ai-agents-md-has-deployment-info

def test_check_004_pass(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("## Deployment info\nCloudflare Pages\n")
    assert run_check("CHECK_004", str(tmp_path)).status == "pass"


def test_check_004_fail_no_section(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("# header")
    assert run_check("CHECK_004", str(tmp_path)).status == "fail"


# CHECK_005 — has-docs-prd

def test_check_005_pass(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prd.md").write_text("prd")
    assert run_check("CHECK_005", str(tmp_path)).status == "pass"


def test_check_005_fail(tmp_path):
    assert run_check("CHECK_005", str(tmp_path)).status == "fail"


# CHECK_006 — has-docs-claude

def test_check_006_pass(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CLAUDE.md").write_text("claude orientation")
    assert run_check("CHECK_006", str(tmp_path)).status == "pass"


def test_check_006_fail(tmp_path):
    assert run_check("CHECK_006", str(tmp_path)).status == "fail"


# CHECK_007 — has-docs-prompts

def test_check_007_pass_capital_p(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "Prompts.md").write_text("prompts")
    assert run_check("CHECK_007", str(tmp_path)).status == "pass"


def test_check_007_pass_lowercase(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prompts.md").write_text("prompts")
    assert run_check("CHECK_007", str(tmp_path)).status == "pass"


def test_check_007_fail(tmp_path):
    assert run_check("CHECK_007", str(tmp_path)).status == "fail"


# CHECK_008 — has-docs-growth

def test_check_008_pass(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "growth.md").write_text("growth log")
    assert run_check("CHECK_008", str(tmp_path)).status == "pass"


def test_check_008_fail(tmp_path):
    assert run_check("CHECK_008", str(tmp_path)).status == "fail"


# CHECK_009 — has-gitignore

def test_check_009_pass(tmp_path):
    (tmp_path / ".gitignore").write_text("node_modules\n")
    assert run_check("CHECK_009", str(tmp_path)).status == "pass"


def test_check_009_fail(tmp_path):
    assert run_check("CHECK_009", str(tmp_path)).status == "fail"


# CHECK_010 — has-tests

def test_check_010_pass_tests_dir(tmp_path):
    (tmp_path / "tests").mkdir()
    assert run_check("CHECK_010", str(tmp_path)).status == "pass"


def test_check_010_pass_src_tests(tmp_path):
    (tmp_path / "src" / "__tests__").mkdir(parents=True)
    assert run_check("CHECK_010", str(tmp_path)).status == "pass"


def test_check_010_warn_no_tests(tmp_path):
    """SEVERITY=info: missing tests is `warn`, not `fail`."""
    r = run_check("CHECK_010", str(tmp_path))
    assert r.status == "warn"


# CHECK_011 — has-env-example

def test_check_011_pass(tmp_path):
    (tmp_path / ".env.example").write_text("FOO=bar\n")
    assert run_check("CHECK_011", str(tmp_path)).status == "pass"


def test_check_011_warn_missing(tmp_path):
    r = run_check("CHECK_011", str(tmp_path))
    assert r.status == "warn"


# CHECK_012 — makefile-forwards-to-parent

def test_check_012_pass_kwizicle_pattern(tmp_path):
    (tmp_path / "Makefile").write_text(
        'PROJ := myproject\n'
        '%:\n'
        '\t$(MAKE) -C .. $@ proj=$(PROJ)\n'
    )
    assert run_check("CHECK_012", str(tmp_path)).status == "pass"


def test_check_012_warn_no_forward(tmp_path):
    """Makefile present but doesn't forward to ../Makefile."""
    (tmp_path / "Makefile").write_text("all:\n\techo hello\n")
    r = run_check("CHECK_012", str(tmp_path))
    assert r.status == "warn"


def test_check_012_fail_no_makefile(tmp_path):
    assert run_check("CHECK_012", str(tmp_path)).status == "fail"
