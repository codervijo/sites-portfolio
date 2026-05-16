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


# CHECK_025 — growth-md-nonempty

def test_check_025_pass_long_body(tmp_path):
    (tmp_path / "docs").mkdir()
    body = "Tracking growth experiments here. " * 10  # ~340 chars
    (tmp_path / "docs" / "growth.md").write_text(f"# Growth\n\n{body}")
    assert run_check("CHECK_025", str(tmp_path)).status == "pass"


def test_check_025_fail_stub(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "growth.md").write_text("# Growth\n\nTBD\n")
    assert run_check("CHECK_025", str(tmp_path)).status == "fail"


def test_check_025_warn_missing(tmp_path):
    assert run_check("CHECK_025", str(tmp_path)).status == "warn"


def test_check_025_skips_pure_headings(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "growth.md").write_text(
        "# Growth\n## Plans\n## Experiments\n## Notes\n## TODO\n"
    )
    assert run_check("CHECK_025", str(tmp_path)).status == "fail"


# CHECK_026 — claude-md-min-sections

def test_check_026_pass(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CLAUDE.md").write_text(
        "# CLAUDE\n\n## Project\nDescription.\n\n## Commands\nmake dev\n"
    )
    assert run_check("CHECK_026", str(tmp_path)).status == "pass"


def test_check_026_fail_missing_one(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "CLAUDE.md").write_text("## Project\nthing\n")
    r = run_check("CHECK_026", str(tmp_path))
    assert r.status == "fail"
    assert "Commands" in r.message


def test_check_026_warn_missing(tmp_path):
    assert run_check("CHECK_026", str(tmp_path)).status == "warn"


# CHECK_027 — prd-md-min-sections

def test_check_027_pass_plain(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prd.md").write_text(
        "## Problem\n...\n## Users\n...\n"
    )
    assert run_check("CHECK_027", str(tmp_path)).status == "pass"


def test_check_027_pass_numbered(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prd.md").write_text(
        "## 1. Problem\n...\n## 2. Users\n...\n"
    )
    assert run_check("CHECK_027", str(tmp_path)).status == "pass"


def test_check_027_fail_missing(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "prd.md").write_text("## Goals\nstuff\n")
    r = run_check("CHECK_027", str(tmp_path))
    assert r.status == "fail"


def test_check_027_warn_no_file(tmp_path):
    assert run_check("CHECK_027", str(tmp_path)).status == "warn"


def test_check_012_fail_no_makefile(tmp_path):
    assert run_check("CHECK_012", str(tmp_path)).status == "fail"


# CHECK_013 — ai-agents-references-versioning


def test_check_013_pass_explicit_versioning_section(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(
        "# repo\n\n## Versioning\n\nvN.X convention. Two levels only.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "pass"
    assert "Versioning" in r.message


def test_check_013_pass_marker_plus_canonical_link(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(
        "# repo\n\nShipped v1.A; see sites/portfolio/AI_AGENTS.md for the convention.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "pass"


def test_check_013_fail_missing_file(tmp_path):
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "fail"
    assert "missing" in r.message.lower()


def test_check_013_fail_no_reference(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text("# repo\n\nno versioning info here.\n")
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "fail"
    assert "doesn't reference" in r.message or "convention" in r.message


def test_check_013_fail_three_level_drift(tmp_path):
    """A project using `vN.X.Y` anywhere in AI_AGENTS.md fails fast,
    with the offending identifier(s) named in the message."""
    (tmp_path / "AI_AGENTS.md").write_text(
        "# repo\n\n## Versioning\n\nShipped v5.F.1 and v6.C.2.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "fail"
    assert "three-level" in r.message.lower()
    assert "v5.F.1" in r.message
    assert "v6.C.2" in r.message


def test_check_013_drift_takes_priority_over_reference(tmp_path):
    """Three-level drift fails even when a `## Versioning` section exists —
    using the wrong convention is more broken than not referencing it."""
    (tmp_path / "AI_AGENTS.md").write_text(
        "# repo\n\n## Versioning\n\nWe use vN.X.Y for sub-phases. Shipped v3.A.1.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "fail"
    assert "three-level" in r.message.lower()
    assert "v3.A.1" in r.message


def test_check_013_drift_dedups_repeated_identifiers(tmp_path):
    """The same drift identifier appearing multiple times is reported once."""
    (tmp_path / "AI_AGENTS.md").write_text(
        "## Versioning\n\nv5.F.1 ships first. v5.F.1 ships second.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "fail"
    # Only one occurrence of v5.F.1 in the message
    assert r.message.count("v5.F.1") == 1


def test_check_013_passes_with_two_level_only(tmp_path):
    """A clean two-level AI_AGENTS.md passes even when it lists many phases."""
    (tmp_path / "AI_AGENTS.md").write_text(
        "## Versioning\n\nShipped v1.A, v1.B, v1.C, v2.A, v3.A, v3.B, v3.C.\n"
    )
    r = run_check("CHECK_013", str(tmp_path))
    assert r.status == "pass"
