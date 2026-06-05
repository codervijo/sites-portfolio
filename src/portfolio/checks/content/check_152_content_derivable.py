"""CHECK_152 — `[content]` is empty but `AI_AGENTS.md` supplies derivable
material, so a fix can derive + seed it (v29.F).

Honors the `[content]` "empty is better than wrong" posture: this only
warns when the operator's authored `AI_AGENTS.md` actually carries the
prose v29 derives from (a non-empty Content strategy or ICP section). A
thin brief stays silent (`pass`), and any seeded field flips it green.
The `fix_tier_1` parses those sections, runs `content_derive`, and seeds
the block via the gated `set_content_block` (never clobbers populated
content). Per the prefer-check/fix delivery rule, this is exposed through
`project fix` / `fleet fix` rather than a bespoke verb.
"""
from __future__ import annotations

from pathlib import Path

from portfolio import apikeys, content_derive
from portfolio import lamill_toml_edit as edit
from portfolio.fix_helpers import FixerSpec, FixResult
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

from ..result import CheckResult

CHECK_ID = "CHECK_152"
CHECK_NAME = "content-derivable"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = (
    "[content] is empty but AI_AGENTS.md supplies derivable material "
    "(`project fix` derives + seeds it; v29.F)."
)


def _derivable(repo_path: str) -> bool:
    """True when AI_AGENTS.md carries the prose v29 derives `[content]`
    from — a non-empty Content strategy or ICP section."""
    sections = content_derive.sections_from_repo(repo_path)
    return bool(sections.get("Content strategy") or sections.get("ICP"))


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    if not (base / LAMILL_TOML_FILENAME).is_file():
        return CheckResult(status="pass", message="no lamill.toml — not applicable")
    if not edit.content_is_blank(edit.content_field_values(base)):
        return CheckResult(status="pass", message="[content] populated")
    if not _derivable(repo_path):
        return CheckResult(
            status="pass",
            message="[content] empty; AI_AGENTS.md has no derivable material",
        )
    return CheckResult(
        status="warn",
        message="[content] empty but AI_AGENTS.md is derivable — `project fix` to seed",
    )


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    ai = project_dir / "AI_AGENTS.md"
    if not ai.is_file():
        return FixResult("manual", "no AI_AGENTS.md to derive [content] from", [])
    if not edit.content_is_blank(edit.content_field_values(project_dir)):
        return FixResult("nothing-to-do", "[content] already populated", [])
    if dry_run:
        # No external call in dry-run (mirrors the Tier-2 ai_fixer).
        return FixResult(
            "would-fix",
            "derive + seed [content] from AI_AGENTS.md (one OpenAI call)",
            [],
        )
    api_key = apikeys.get_key("OPENAI_API_KEY")
    if not api_key:
        return FixResult(
            "manual",
            "no OPENAI_API_KEY — `lamill settings apikeys set OPENAI_API_KEY <key>` to derive",
            [],
        )
    sections = content_derive.parse_ai_agents_sections(ai.read_text(encoding="utf-8"))
    derived = content_derive.derive_content(sections, api_key=api_key)
    if not edit.set_content_block(project_dir, derived):
        return FixResult(
            "nothing-to-do",
            "derivation produced nothing usable — [content] left empty",
            [],
        )
    seeded = sorted(k for k, v in derived.items() if v)
    summary = f"seeded {len(seeded)} [content] field(s): {', '.join(seeded)}"
    # The seed and the "Fill in [content]" starter todo are two halves of
    # the same gate: once the gating fields are all filled, close the nag
    # so it stops surfacing in `fleet focus` (mirrors v29.D bootstrap
    # shipping todo-free).
    if not edit.content_todo_blanks(edit.content_field_values(project_dir)):
        if edit.complete_content_todo(project_dir):
            summary += "; closed the 'Fill in [content]' todo"
    return FixResult("fixed", summary, [project_dir / LAMILL_TOML_FILENAME])


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="derive + seed [content] from AI_AGENTS.md",
    apply=_fix,
)
