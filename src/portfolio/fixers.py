"""v6.C — Fixer registry for `portfolio project fix`.

A fixer is paired with a CHECK_ID. When the catalog flags that check
as `fail` (or `warn` in some cases), the fixer's `apply()` writes the
template, appends the section, or removes the file that makes the
check pass on next run.

Two tiers (only Tier 1 ships in v6.C):
  - Tier 1: deterministic templated writes / section appends / deletes
  - Tier 2: opt-in `claude -p` subprocess for content-quality checks
            where templates can't produce useful project-specific text
            (deferred to v6.C.1)

Idempotency is a hard contract: every fixer must produce the same
file state on a second `apply()` as the first. File-write fixers
satisfy this trivially (they check existence). Section-injection
fixers satisfy it by parsing existing headers and only appending
when the target header is absent. Tests in `test_fixers.py` lock
this in for every fixer.

Manual-only checks (those without a registered fixer) are surfaced
in the plan output with a `manual` marker so the user knows they
need to handle those by hand.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Literal

from . import templates


FixStatus = Literal["fixed", "nothing-to-do", "manual", "error", "would-fix"]


@dataclass
class FixResult:
    """Outcome of one fixer's `apply()` call."""
    status: FixStatus
    summary: str            # one-line description for plan / apply output
    files_touched: list[Path]   # paths written / appended / deleted


@dataclass
class FixerSpec:
    """One CHECK_ID's fixer."""
    check_id: str
    tier: int                                          # 1 = templated, 2 = AI
    plan_summary: str                                  # shown in dry-run plan
    apply: Callable[[Path, bool, bool], FixResult]
    # apply(project_dir, dry_run, assume_yes) -> FixResult
    # `assume_yes` matters only for fixers that prompt (lockfile deletes).


# ---------- helpers ----------


def _today() -> str:
    return date.today().isoformat()


def _domain_from_dir(project_dir: Path) -> str:
    """Use the directory name as the canonical domain. Mirrors how the
    rest of the CLI maps sites/<domain>/ to a domain name."""
    return project_dir.name


def _has_section_heading(text: str, heading: str) -> bool:
    """True iff `text` contains a `## <heading>` line (anywhere)."""
    pattern = rf"^##\s+{re.escape(heading)}\s*$"
    return bool(re.search(pattern, text, flags=re.MULTILINE))


def _append_section(text: str, section_body: str) -> str:
    """Append `section_body` to `text` with a single blank-line separator.
    Idempotent in itself — caller checks the heading first."""
    text = text.rstrip("\n")
    return f"{text}\n\n{section_body}"


# ---------- tier 1 fixers — file-existence (writes file if missing) ----------


def _write_file_fixer(rel_path: str, render: Callable[[Path], str],
                      summary: str, check_id: str) -> FixerSpec:
    """Build a fixer that writes a single file (creating parent dirs)
    if the file is absent. No-op if the file already exists."""
    def apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / rel_path
        if target.is_file():
            return FixResult("nothing-to-do",
                             f"{rel_path} already exists",
                             [])
        if dry_run:
            content = render(project_dir)
            return FixResult("would-fix",
                             f"write {rel_path} ({len(content)} bytes)",
                             [target])
        target.parent.mkdir(parents=True, exist_ok=True)
        content = render(project_dir)
        target.write_text(content)
        return FixResult("fixed",
                         f"wrote {rel_path}",
                         [target])
    return FixerSpec(check_id=check_id, tier=1, plan_summary=summary, apply=apply)


# ---------- tier 1 fixers — section injection (appends headed block if absent) ----------


def _section_inject_fixer(rel_path: str, heading: str,
                          render_section: Callable[[Path], str],
                          summary: str, check_id: str) -> FixerSpec:
    """Build a fixer that appends a `## <heading>` section + body to an
    existing file if the heading isn't already present. Skips if the
    target file doesn't exist (the file-existence fixer for that file
    handles creation)."""
    def apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / rel_path
        if not target.is_file():
            return FixResult("manual",
                             f"{rel_path} doesn't exist — fix the file-existence check first",
                             [])
        text = target.read_text()
        if _has_section_heading(text, heading):
            return FixResult("nothing-to-do",
                             f"## {heading} section already present in {rel_path}",
                             [])
        if dry_run:
            return FixResult("would-fix",
                             f"append ## {heading} to {rel_path}",
                             [target])
        new_text = _append_section(text, render_section(project_dir))
        target.write_text(new_text + "\n")
        return FixResult("fixed",
                         f"appended ## {heading} to {rel_path}",
                         [target])
    return FixerSpec(check_id=check_id, tier=1, plan_summary=summary, apply=apply)


# ---------- tier 1 fixers — file deletion (lockfiles) ----------


def _delete_file_fixer(rel_path: str, summary: str, check_id: str) -> FixerSpec:
    """Build a fixer that deletes a single file (with per-file confirmation
    in interactive mode unless --yes). No-op if the file is already absent."""
    def apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / rel_path
        if not target.exists():
            return FixResult("nothing-to-do",
                             f"{rel_path} already absent",
                             [])
        if dry_run:
            return FixResult("would-fix",
                             f"delete {rel_path}",
                             [target])
        if not assume_yes:
            # Caller (cli.py) handles the typer.confirm() — fixer trusts the
            # decision. The `assume_yes=False` path means caller already
            # confirmed (or is in scripted mode without --yes, which we
            # treat as a hard error one level up).
            pass
        target.unlink()
        return FixResult("fixed",
                         f"deleted {rel_path}",
                         [target])
    return FixerSpec(check_id=check_id, tier=1, plan_summary=summary, apply=apply)


# ---------- registry ----------


def _build_registry() -> dict[str, FixerSpec]:
    """Construct the {check_id → FixerSpec} map. Called once at import."""
    out: dict[str, FixerSpec] = {}

    def reg(spec: FixerSpec) -> None:
        out[spec.check_id] = spec

    # File-existence fixers: 8 templated whole-file writes.
    reg(_write_file_fixer(
        "README.md",
        lambda p: templates.readme_md(_domain_from_dir(p)),
        "write README.md",
        check_id="CHECK_001",
    ))
    reg(_write_file_fixer(
        "AI_AGENTS.md",
        lambda p: templates.ai_agents_md(_domain_from_dir(p)),
        "write AI_AGENTS.md (with Building/Deployment sections)",
        check_id="CHECK_002",
    ))
    reg(_write_file_fixer(
        "docs/prd.md",
        lambda p: templates.docs_prd_md(_domain_from_dir(p)),
        "write docs/prd.md (with Problem/Users sections)",
        check_id="CHECK_005",
    ))
    reg(_write_file_fixer(
        "docs/CLAUDE.md",
        lambda p: templates.docs_claude_md(_domain_from_dir(p)),
        "write docs/CLAUDE.md (with Project/Commands sections)",
        check_id="CHECK_006",
    ))
    reg(_write_file_fixer(
        "docs/Prompts.md",
        lambda p: templates.docs_prompts_md(_domain_from_dir(p), _today()),
        "write docs/Prompts.md skeleton",
        check_id="CHECK_007",
    ))
    reg(_write_file_fixer(
        "docs/growth.md",
        lambda p: templates.docs_growth_md(_domain_from_dir(p), _today()),
        "write docs/growth.md skeleton",
        check_id="CHECK_008",
    ))
    reg(_write_file_fixer(
        ".gitignore",
        lambda _p: templates.gitignore(),
        "write standard .gitignore",
        check_id="CHECK_009",
    ))
    reg(_write_file_fixer(
        ".env.example",
        lambda _p: templates.env_example(),
        "write .env.example",
        check_id="CHECK_011",
    ))

    # CHECK_012 makefile-forwards-to-parent: write only if Makefile is absent.
    # If a Makefile exists but doesn't forward, refuse — that's a manual call.
    def _fix_makefile(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / "Makefile"
        if target.is_file():
            return FixResult("manual",
                             "Makefile exists but doesn't forward — review by hand",
                             [])
        if dry_run:
            return FixResult("would-fix",
                             "write forwarding Makefile",
                             [target])
        target.write_text(templates.local_makefile(_domain_from_dir(project_dir)))
        return FixResult("fixed", "wrote forwarding Makefile", [target])
    reg(FixerSpec(check_id="CHECK_012", tier=1,
                  plan_summary="write forwarding Makefile (only if absent)",
                  apply=_fix_makefile))

    # Section-injection fixers: 4 append-if-missing.
    reg(_section_inject_fixer(
        "AI_AGENTS.md", "Building info",
        lambda _p: templates.ai_agents_section_building(),
        "append ## Building info to AI_AGENTS.md",
        check_id="CHECK_003",
    ))
    reg(_section_inject_fixer(
        "AI_AGENTS.md", "Deployment info",
        lambda _p: templates.ai_agents_section_deployment(),
        "append ## Deployment info to AI_AGENTS.md",
        check_id="CHECK_004",
    ))
    # CHECK_026 needs both `## Project` and `## Commands` — handle both.
    def _fix_claude_sections(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / "docs" / "CLAUDE.md"
        if not target.is_file():
            return FixResult("manual",
                             "docs/CLAUDE.md doesn't exist — fix CHECK_006 first",
                             [])
        text = target.read_text()
        added: list[str] = []
        if not _has_section_heading(text, "Project"):
            text = _append_section(text, templates.claude_md_section_project(_domain_from_dir(project_dir)))
            added.append("## Project")
        if not _has_section_heading(text, "Commands"):
            text = _append_section(text, templates.claude_md_section_commands())
            added.append("## Commands")
        if not added:
            return FixResult("nothing-to-do",
                             "docs/CLAUDE.md already has both sections",
                             [])
        if dry_run:
            return FixResult("would-fix",
                             f"append {' + '.join(added)} to docs/CLAUDE.md",
                             [target])
        target.write_text(text + "\n")
        return FixResult("fixed",
                         f"appended {' + '.join(added)} to docs/CLAUDE.md",
                         [target])
    reg(FixerSpec(check_id="CHECK_026", tier=1,
                  plan_summary="append ## Project + ## Commands to docs/CLAUDE.md",
                  apply=_fix_claude_sections))

    # CHECK_027 same pattern for prd.md (Problem + Users).
    def _fix_prd_sections(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / "docs" / "prd.md"
        if not target.is_file():
            return FixResult("manual",
                             "docs/prd.md doesn't exist — fix CHECK_005 first",
                             [])
        text = target.read_text()
        added: list[str] = []
        if not _has_section_heading(text, "Problem"):
            text = _append_section(text, templates.prd_md_section_problem())
            added.append("## Problem")
        if not _has_section_heading(text, "Users"):
            text = _append_section(text, templates.prd_md_section_users())
            added.append("## Users")
        if not added:
            return FixResult("nothing-to-do",
                             "docs/prd.md already has both sections",
                             [])
        if dry_run:
            return FixResult("would-fix",
                             f"append {' + '.join(added)} to docs/prd.md",
                             [target])
        target.write_text(text + "\n")
        return FixResult("fixed",
                         f"appended {' + '.join(added)} to docs/prd.md",
                         [target])
    reg(FixerSpec(check_id="CHECK_027", tier=1,
                  plan_summary="append ## Problem + ## Users to docs/prd.md",
                  apply=_fix_prd_sections))

    # Lockfile deletions — pnpm-only convention.
    reg(_delete_file_fixer(
        "package-lock.json",
        "delete package-lock.json (pnpm-only convention)",
        check_id="CHECK_032",
    ))
    reg(_delete_file_fixer(
        "bun.lockb",
        "delete bun.lockb (pnpm-only convention)",
        check_id="CHECK_033",
    ))
    reg(_delete_file_fixer(
        "yarn.lock",
        "delete yarn.lock (pnpm-only convention)",
        check_id="CHECK_034",
    ))

    return out


_REGISTRY: dict[str, FixerSpec] | None = None


def get_registry() -> dict[str, FixerSpec]:
    """Lazy-init the fixer registry. Same pattern as the check registry."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_registry()
    return _REGISTRY


def fixable_check_ids() -> set[str]:
    """Set of CHECK_IDs that have a registered Tier 1 fixer."""
    return {spec.check_id for spec in get_registry().values() if spec.tier == 1}


def get_fixer(check_id: str) -> FixerSpec | None:
    return get_registry().get(check_id)
