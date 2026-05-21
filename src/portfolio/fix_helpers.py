"""v6.C — Fixer infrastructure shared across all check modules.

Each check module that has an auto-fixer declares (at module level):
  fix_tier_1: FixerSpec      # templated/deterministic
  fix_tier_2: FixerSpec      # AI-assisted (optional, v6.C.1+)

The factory helpers below (`file_writer`, `section_inject`,
`file_deleter`) build a FixerSpec for the common shapes — keeps each
check module's fixer down to ~3 lines.

Custom logic (e.g. CHECK_012's "write Makefile only if absent") just
constructs FixerSpec directly with its own apply closure.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Literal


FixStatus = Literal["fixed", "nothing-to-do", "manual", "error", "would-fix"]


@dataclass
class FixResult:
    """Outcome of one fixer's `apply()` call."""
    status: FixStatus
    summary: str
    files_touched: list[Path]


@dataclass(frozen=True)
class FixerSpec:
    """Per-check, per-tier fixer metadata + callable.

    `check_id` is filled in by the registry at discovery time (the check
    module's `CHECK_ID` is authoritative; the spec instance just rides
    along). Factories below leave it as "" and the registry rewrites it
    via `dataclasses.replace`."""
    check_id: str
    tier: int
    summary: str
    apply: Callable[[Path, bool, bool], FixResult]
    # apply(project_dir, dry_run, assume_yes) -> FixResult
    # `assume_yes` matters only for fixers that prompt (lockfile deletes).


# ---------- factory helpers ----------


def file_writer(rel_path: str, *, render: Callable[[Path], str],
                summary: str, tier: int = 1) -> FixerSpec:
    """Build a fixer that writes a single file (creating parent dirs)
    if the file is absent. No-op if the file already exists. Idempotent
    by construction."""
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
        return FixResult("fixed", f"wrote {rel_path}", [target])
    return FixerSpec(check_id="", tier=tier, summary=summary, apply=apply)


def section_inject(rel_path: str, heading: str, *,
                   render: Callable[[Path], str],
                   summary: str, tier: int = 1) -> FixerSpec:
    """Build a fixer that appends a `## <heading>` section to an existing
    file if the heading isn't already present. Returns "manual" if the
    target file doesn't exist (its file-existence sibling fixes that)."""
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
        new_text = _append_section(text, render(project_dir))
        target.write_text(new_text + "\n")
        return FixResult("fixed",
                         f"appended ## {heading} to {rel_path}",
                         [target])
    return FixerSpec(check_id="", tier=tier, summary=summary, apply=apply)


def file_deleter(rel_path: str, *, summary: str, tier: int = 1) -> FixerSpec:
    """Build a fixer that deletes a single file. No-op if already absent.
    Caller is expected to have confirmed the deletion (via cli.py's
    typer.confirm); this just executes."""
    def apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        target = project_dir / rel_path
        if not target.exists():
            return FixResult("nothing-to-do",
                             f"{rel_path} already absent",
                             [])
        if dry_run:
            return FixResult("would-fix", f"delete {rel_path}", [target])
        target.unlink()
        return FixResult("fixed", f"deleted {rel_path}", [target])
    return FixerSpec(check_id="", tier=tier, summary=summary, apply=apply)


# ---------- section-heading helpers (used by section_inject) ----------


def _has_section_heading(text: str, heading: str) -> bool:
    """True iff `text` contains a `## <heading>` line (anywhere; case-insensitive
    match is intentional — `## Building info` and `## BUILDING INFO` both count).
    Tolerates numeric prefixes like `## 1. Heading`."""
    pattern = (
        rf"^##\s+(?:\d+\.\s*)?{re.escape(heading)}\s*$"
    )
    return bool(re.search(pattern, text, flags=re.MULTILINE | re.IGNORECASE))


def _append_section(text: str, section_body: str) -> str:
    """Append `section_body` to `text` with a single blank-line separator."""
    text = text.rstrip("\n")
    return f"{text}\n\n{section_body}"


# ---------- v6.C.1: Claude subprocess infra (Tier 2 fixers) ----------


_DEFAULT_BUDGET_USD = 0.50
_DEFAULT_TIMEOUT_S = 180
_ALLOWED_TOOLS = "Read Edit Glob Grep"


def claude_available() -> bool:
    """True iff `claude` is on PATH."""
    return shutil.which("claude") is not None


@dataclass
class ClaudeResult:
    """Outcome of one `claude -p` subprocess call."""
    ok: bool
    cost_usd: float
    duration_s: float
    error: str | None
    raw_output: str


def run_claude(prompt: str, *, cwd: Path,
               budget_usd: float = _DEFAULT_BUDGET_USD,
               timeout_s: int = _DEFAULT_TIMEOUT_S,
               allowed_tools: str | None = None) -> ClaudeResult:
    """Run `claude -p <prompt>` non-interactively in `cwd` with
    restricted tools and a hard budget cap. Returns ClaudeResult.

    `allowed_tools` defaults to the Tier-2-fixer set
    (Read/Edit/Glob/Grep — no Write, no Bash, no network beyond
    model calls). Callers that need to create new files (e.g. v15.H
    stack translation creating Astro+Vite files at project root)
    pass an extended set like `"Read Write Edit Glob Grep Bash"`.
    """
    if not claude_available():
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error="claude-not-found", raw_output="")
    tools = allowed_tools if allowed_tools is not None else _ALLOWED_TOOLS
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", tools,
        "--max-budget-usd", str(budget_usd),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=float(timeout_s),
                            error="timeout", raw_output="")
    except OSError as e:
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error=f"oserror: {e}", raw_output="")
    if proc.returncode != 0 and not proc.stdout.strip().startswith("{"):
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error=f"exit-{proc.returncode}",
                            raw_output=proc.stderr or proc.stdout)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ClaudeResult(ok=False, cost_usd=0.0, duration_s=0.0,
                            error="bad-json", raw_output=proc.stdout[:500])
    cost = float(data.get("total_cost_usd") or 0.0)
    duration = float(data.get("duration_ms") or 0.0) / 1000.0
    if bool(data.get("is_error")):
        return ClaudeResult(ok=False, cost_usd=cost, duration_s=duration,
                            error=str(data.get("subtype") or "is_error"),
                            raw_output=proc.stdout[:500])
    return ClaudeResult(ok=True, cost_usd=cost, duration_s=duration,
                        error=None, raw_output="")


@dataclass
class ClaudeTextResult:
    """Outcome of one `claude -p` call invoked for a TEXT response (no
    tool use). `text` is the assistant's final message body; the rest
    mirrors `ClaudeResult`'s metadata for budget / observability."""
    ok: bool
    text: str
    cost_usd: float
    duration_s: float
    error: str | None
    raw_output: str   # stderr/stdout fragment on failure, "" on success


def run_claude_text(prompt: str, *, cwd: Path,
                    budget_usd: float = _DEFAULT_BUDGET_USD,
                    timeout_s: int = _DEFAULT_TIMEOUT_S) -> ClaudeTextResult:
    """Run `claude -p <prompt>` with NO tools allowed and capture the
    assistant's final text response.

    Different contract from `run_claude`:
      - `run_claude` is for Tier-2 fixers — Claude edits files in
        place via the Read/Edit/Glob/Grep toolset, and we only care
        whether it succeeded + how much it cost.
      - `run_claude_text` is for callers that want the model's text
        output back (v8.E interpretive verdict, future research /
        audit / classification passes). No tools allowed; the response
        is a single assistant message.

    Returns `ClaudeTextResult` with `text` populated on success. On
    failure (claude-not-found, timeout, bad-json, is_error from the
    CLI), `text == ""` and `error` carries the cause.
    """
    if not claude_available():
        return ClaudeTextResult(ok=False, text="", cost_usd=0.0,
                                duration_s=0.0, error="claude-not-found",
                                raw_output="")
    cmd = [
        "claude", "-p", prompt,
        "--output-format", "json",
        "--allowedTools", "",         # no tool use — pure text response
        "--max-budget-usd", str(budget_usd),
    ]
    try:
        proc = subprocess.run(
            cmd, cwd=str(cwd),
            capture_output=True, text=True,
            timeout=timeout_s, check=False,
        )
    except subprocess.TimeoutExpired:
        return ClaudeTextResult(ok=False, text="", cost_usd=0.0,
                                duration_s=float(timeout_s),
                                error="timeout", raw_output="")
    except OSError as e:
        return ClaudeTextResult(ok=False, text="", cost_usd=0.0,
                                duration_s=0.0, error=f"oserror: {e}",
                                raw_output="")
    # Same JSON-on-stdout convention as run_claude — even non-zero
    # exits often carry a parseable error envelope on stdout, so try
    # to parse before treating as a process-level failure.
    if proc.returncode != 0 and not proc.stdout.strip().startswith("{"):
        return ClaudeTextResult(ok=False, text="", cost_usd=0.0,
                                duration_s=0.0,
                                error=f"exit-{proc.returncode}",
                                raw_output=proc.stderr or proc.stdout)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return ClaudeTextResult(ok=False, text="", cost_usd=0.0,
                                duration_s=0.0, error="bad-json",
                                raw_output=proc.stdout[:500])
    cost = float(data.get("total_cost_usd") or 0.0)
    duration = float(data.get("duration_ms") or 0.0) / 1000.0
    if bool(data.get("is_error")):
        return ClaudeTextResult(ok=False, text="", cost_usd=cost,
                                duration_s=duration,
                                error=str(data.get("subtype") or "is_error"),
                                raw_output=proc.stdout[:500])
    text = str(data.get("result") or "")
    if not text:
        # `result` field empty / missing on a non-error response is a
        # surprise — surface it rather than silently returning "".
        return ClaudeTextResult(ok=False, text="", cost_usd=cost,
                                duration_s=duration, error="empty-result",
                                raw_output=proc.stdout[:500])
    return ClaudeTextResult(ok=True, text=text, cost_usd=cost,
                            duration_s=duration, error=None, raw_output="")


def read_file_for_context(path: Path, max_chars: int = 4000) -> str:
    """Best-effort file read for prompt context. Returns "" on error and
    truncates long files to keep prompt cost modest."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return ""
    if len(text) > max_chars:
        return text[:max_chars] + "\n[... truncated ...]"
    return text


def project_context(project_dir: Path) -> str:
    """Brief multi-file context block for Tier 2 prompts. AI_AGENTS.md
    + a sliver of package.json / pyproject.toml if present. Capped at
    ~5KB so prompts stay cheap."""
    parts: list[str] = []
    ai = project_dir / "AI_AGENTS.md"
    if ai.is_file():
        parts.append("=== AI_AGENTS.md ===\n" + read_file_for_context(ai, 3000))
    pkg = project_dir / "package.json"
    if pkg.is_file():
        parts.append("=== package.json ===\n" + read_file_for_context(pkg, 800))
    pyproj = project_dir / "pyproject.toml"
    if pyproj.is_file():
        parts.append("=== pyproject.toml ===\n" + read_file_for_context(pyproj, 800))
    return "\n\n".join(parts)


def ai_fixer_factory(check_id: str, prompt_builder: Callable[[Path], str],
                     *, summary: str, tier: int = 2) -> FixerSpec:
    """Build a Tier 2 FixerSpec that spawns `claude -p` to fix `check_id`.

    The fixer:
      1. Builds the prompt from the project state.
      2. Spawns `claude -p` (restricted tools, budget cap, timeout).
      3. Re-runs the targeted CHECK; pass → "fixed", else "error".

    `check_id` is duplicated here (vs left empty for the registry to
    fill) because Tier 2 fixers need the ID at apply-time (to re-run
    the verification check). The registry will overwrite it but the
    runtime closure already has it captured."""
    captured_id = check_id

    def apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        if dry_run:
            return FixResult("would-fix",
                             f"spawn claude -p to {summary}",
                             [])
        if not claude_available():
            return FixResult("error",
                             "claude CLI not on PATH (install Claude Code)",
                             [])
        from .checks import run_check
        prompt = prompt_builder(project_dir)
        result = run_claude(prompt, cwd=project_dir)
        if not result.ok:
            return FixResult("error",
                             f"claude failed: {result.error}",
                             [])
        new_result = run_check(captured_id, str(project_dir))
        if new_result.status == "pass":
            return FixResult(
                "fixed",
                f"claude completed (${result.cost_usd:.3f} · {result.duration_s:.0f}s) — {captured_id} now passing",
                [],
            )
        return FixResult(
            "error",
            (f"claude completed (${result.cost_usd:.3f} · {result.duration_s:.0f}s) "
             f"but {captured_id} still {new_result.status}: {new_result.message}"),
            [],
        )
    return FixerSpec(check_id=check_id, tier=tier, summary=summary, apply=apply)
