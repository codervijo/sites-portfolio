"""Tests for v6.C — `src/portfolio/templates.py`.

Each template should:
  - Produce non-empty content
  - Mention the domain when given one
  - Include section headings the catalog requires (e.g. AI_AGENTS gets
    `## Building info` and `## Deployment info`; CLAUDE.md gets
    `## Project` and `## Commands`; etc.)
"""
from __future__ import annotations

from portfolio import templates


def test_readme_md_includes_domain():
    out = templates.readme_md("kwizicle.com")
    assert out
    assert "kwizicle.com" in out


def test_ai_agents_md_has_required_sections():
    """AI_AGENTS scaffold must satisfy CHECK_003 + CHECK_004 on its own."""
    out = templates.ai_agents_md("kwizicle.com")
    assert "## Building info" in out
    assert "## Deployment info" in out


def test_docs_prd_md_has_required_sections():
    """docs/prd.md scaffold must satisfy CHECK_027 (Problem + Users).
    Bootstrap's template uses numbered prefixes (`## 1. Problem`); the
    catalog check tolerates them."""
    out = templates.docs_prd_md("kwizicle.com")
    assert "Problem" in out
    assert "Users" in out
    # Run the actual catalog check end-to-end to lock down compatibility.
    import tempfile
    from pathlib import Path
    from portfolio.checks import run_check
    with tempfile.TemporaryDirectory() as td:
        (Path(td) / "docs").mkdir()
        (Path(td) / "docs" / "prd.md").write_text(out)
        assert run_check("CHECK_027", td).status == "pass"


def test_docs_claude_md_has_required_sections():
    """docs/CLAUDE.md scaffold must satisfy CHECK_026 (Project + Commands)
    and CHECK_043 (Heading hygiene)."""
    out = templates.docs_claude_md("kwizicle.com")
    assert "## Project" in out
    assert "## Commands" in out
    assert "## Heading hygiene" in out
    assert "kwizicle.com" in out


def test_claude_md_section_heading_hygiene_emitter_shape():
    """The section emitter produces a standalone `## Heading hygiene`
    block that the section-injection fixer can drop into an existing
    docs/CLAUDE.md."""
    out = templates.claude_md_section_heading_hygiene()
    assert out.startswith("## Heading hygiene")
    # The pre-edit ritual mentions the grep one-liner.
    assert "grep -nE '^#+ '" in out
    # The rationale call-out is present (otherwise the rule loses force).
    assert "Why:" in out or "**Why" in out


def test_docs_prompts_md_has_dated_h2():
    out = templates.docs_prompts_md("kwizicle.com", "2026-05-10")
    # CHECK_007 just needs the file; its sibling format check looks for
    # a dated H2 — both bootstrap and fix output should satisfy it.
    assert "2026-05-10" in out


def test_docs_growth_md_has_dated_h2():
    out = templates.docs_growth_md("kwizicle.com", "2026-05-10")
    assert "2026-05-10" in out


def test_gitignore_covers_node_modules():
    """CHECK_038 expects node_modules in .gitignore."""
    out = templates.gitignore()
    assert "node_modules" in out


def test_local_makefile_forwards_to_parent():
    """CHECK_012 expects $(MAKE) -C .. or BUILDER_PATH."""
    out = templates.local_makefile("kwizicle.com")
    # Either pattern is accepted by CHECK_012.
    assert "$(MAKE) -C .." in out or "BUILDER_PATH" in out


def test_env_example_is_a_template():
    out = templates.env_example()
    assert out
    # Should NOT contain real-looking values.
    assert "API_KEY=sk-" not in out


# ---------- section emitters ----------


def test_section_emitters_produce_h2_headings():
    """Every section emitter starts (or contains) a `## <heading>`."""
    assert "## Building info" in templates.ai_agents_section_building()
    assert "## Deployment info" in templates.ai_agents_section_deployment()
    assert "## Project" in templates.claude_md_section_project("kwizicle.com")
    assert "## Commands" in templates.claude_md_section_commands()
    assert "## Problem" in templates.prd_md_section_problem()
    assert "## Users" in templates.prd_md_section_users()
