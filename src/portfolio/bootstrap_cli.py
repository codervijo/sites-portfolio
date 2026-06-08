"""v35.F incr 8 — `new bootstrap` helper + renderer cluster, extracted from
cli.py (behavior-preserving, H1; approach A — sibling module).

All helpers are exclusive to the `new bootstrap` command: operator-input
collection, smart-paste apply/confirm, inventory + git-url + growth resolvers,
and the preflight/summary/tree/conformance/LLM-template renderers (plus their
constants). Self-contained — external deps are all imports. cli.py re-exports
every name; the `@new_app.command("bootstrap")` callback stays in cli.py.
"""
from __future__ import annotations

import re

import typer

from .console import console
from .data import PORTFOLIO_JSON


def _prompt_multiline(label: str, *, hint: str | None = None,
                      detect_blob: bool = False) -> str:
    """Read multi-line input until two blank lines or EOF.

    Behavior:
      - Prints `label` (rich markup OK) and the optional `hint`.
      - Reads `sys.stdin` line-by-line until either:
          * Two consecutive blank lines (operator hit Enter twice), OR
          * EOF (Ctrl-D / closed stream)
      - Strips trailing blank lines; returns the joined text. Empty
        input (immediate Enter-Enter or EOF) → "".

    Single-line answers still work: type the line, hit Enter, hit
    Enter again to terminate.

    When `detect_blob` is set and the first non-blank line looks like a
    numbered section header, the input is treated as a pasted
    multi-section reply: blank lines no longer terminate (a blob's own
    section separators are blank lines), so reading continues until EOF
    (Ctrl-D) or a run of 3+ consecutive blank lines. This keeps the
    whole blob in one capture so smart-paste can route every section,
    instead of stopping at the first double blank and leaking the rest
    into later prompts.
    """
    import sys

    if label:
        console.print(label)
    if hint:
        console.print(f"  [dim]{hint}[/]")

    lines: list[str] = []
    blank_run = 0
    blob_mode = False
    seen_nonblank = False
    while True:
        try:
            line = sys.stdin.readline()
        except (KeyboardInterrupt, EOFError):
            break
        if line == "":   # EOF (Ctrl-D)
            break
        # `readline` keeps the trailing newline; strip it but only
        # the trailing newline, not internal whitespace.
        stripped = line.rstrip("\n").rstrip("\r")
        if stripped == "":
            blank_run += 1
            # A detected blob uses blank lines as section separators, so
            # only a long run (3+) or EOF ends it; plain input still
            # ends on the usual double blank.
            terminator = 3 if blob_mode else 2
            if blank_run >= terminator:
                break
            lines.append("")
            continue
        blank_run = 0
        if not seen_nonblank:
            seen_nonblank = True
            if detect_blob:
                # A multi-section paste — a ```code fence```, a numbered
                # header (`2. Summary`), or a bare canonical label
                # (`Summary`). In blob mode blank lines are section
                # separators, not terminators (read to EOF/Ctrl-D).
                from .bootstrap_paste import is_section_header_line
                if stripped.startswith("```") or is_section_header_line(stripped):
                    blob_mode = True
        lines.append(stripped)

    # Drop trailing blank lines from the captured buffer.
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines)


def _resolve_git_url(*, flag_value: str, non_interactive: bool,
                     max_attempts: int = 3) -> str:
    """Return the Lovable-repo URL the operator wants to clone (or "").

    Resolution order:
      1. `--git-url <url>` flag → returned verbatim (no prompt).
      2. `--non-interactive` → "" (blank-scaffold path).
      3. Else: interactive prompt. Empty input → "" (blank-scaffold).
         Non-empty input must start with `http://`, `https://`, or
         `git@`; otherwise re-prompt up to `max_attempts` times before
         warning-and-skipping.
    """
    if flag_value:
        return flag_value
    if non_interactive:
        return ""

    console.print(
        "\n[bold]Lovable GitHub repo URL[/]"
        " [dim](Enter to skip and scaffold blank)[/]"
    )
    for _ in range(max_attempts):
        raw = typer.prompt(
            "  >", default="", show_default=False,
        ).strip()
        if not raw:
            return ""
        if re.match(r"^https?://", raw) or re.match(r"^git@", raw):
            return raw
        console.print(
            "  [yellow]Expected an https:// URL or a git@host:path "
            "shape; try again or hit Enter to skip.[/]"
        )
    console.print(
        "  [yellow]3 invalid attempts; skipping — bootstrap will "
        "scaffold a blank project.[/]"
    )
    return ""


def _render_bootstrap_preflight(
    *, domain: str, non_interactive: bool, git_url: str,
    summary: str, audience: str, icp: str, goal: str,
    content_strategy: str, growth_hypothesis: str,
    registered: bool | None, registrar: str,
) -> None:
    """Print a single banner listing all 9 upcoming prompts.

    No-op when:
      - `non_interactive=True` (no prompts fire)
      - Every section already has a flag value AND `git_url` is set
        AND `registered`+`registrar` are set (no prompts fire)
    """
    if non_interactive:
        return
    all_supplied = (
        bool(git_url)
        and bool(summary.strip()) and bool(audience.strip())
        and bool(icp.strip()) and bool(goal.strip())
        and bool(content_strategy.strip())
        and bool(growth_hypothesis.strip())
        and registered is not None and bool(registrar)
    )
    if all_supplied:
        return

    console.print(
        f"\n[bold]About to bootstrap [cyan]{domain}[/].[/] "
        "You'll be asked 9 questions:\n"
    )
    rows = [
        ("1.", "Lovable GitHub repo URL", "Enter to skip; scaffolds blank"),
        ("2.", "Summary", "one paragraph"),
        ("3.", "Audience", "one sentence"),
        ("4.", "ICP", "specific ideal customer"),
        ("5.", "Goals", "1-2 sentences"),
        ("6.", "Content strategy", "page types · topics · format mix"),
        ("7.", "Domain registered?", "Y/n"),
        ("8.", "Registrar", "porkbun / godaddy / namecheap / other"),
        ("9.", "Growth hypothesis", "one paragraph"),
    ]
    for num, label, hint in rows:
        console.print(
            f"  {num} [bold]{label:<32}[/] [dim]({hint})[/]"
        )
    console.print(
        "\n  [dim]Skip individual prompts with --<flag>; "
        "skip all with --non-interactive.[/]"
    )
    console.print(
        "  [dim]Paragraph prompts (1, 2, 4, 6, 9): "
        "finish with Enter twice or Ctrl-D.[/]"
    )


# The 6 LLM-draftable content sections + their bootstrap prompt-order
# numbers (matching _POSITIONAL_ORDER / the preflight banner). Prompts 1
# (Lovable repo), 7 (registered), 8 (registrar) aren't LLM-draftable, so
# they're omitted from the template.
# (number, label, length-hint). Rendered as `N. Label  (length-hint)` —
# the bare template (2026-05-29): one line per section, no descriptive
# prose. The reply-format instruction above the list tells the LLM to
# put content on the next line so smart-paste can route each section.
_LLM_TEMPLATE_SECTIONS: list[tuple[str, str, str]] = [
    ("2", "Summary", "one paragraph"),
    ("3", "Audience", "one sentence"),
    ("4", "ICP", "one paragraph"),
    ("5", "Goals", "1-2 sentences"),
    ("6", "Content strategy", "one paragraph"),
    ("9", "Growth hypothesis", "one paragraph"),
]


def _render_llm_prompt_template(
    *, domain: str, topic: str, non_interactive: bool,
    summary: str, audience: str, icp: str, goal: str,
    content_strategy: str, growth_hypothesis: str,
) -> None:
    """Print a copy-paste LLM prompt for the content sections.

    No-op when:
      - `non_interactive=True` (no prompts fire), OR
      - every content section already has a flag value (nothing to draft).
    """
    if non_interactive:
        return
    all_content_supplied = all(
        bool(s.strip()) for s in (
            summary, audience, icp, goal, content_strategy, growth_hypothesis,
        )
    )
    if all_content_supplied:
        return

    if topic.strip():
        lead = f"Draft positioning for {domain} — {topic.strip()}."
    else:
        lead = f"Draft positioning for {domain} (one line on what it is: …)."

    console.print("\n[bold]─── Paste into ChatGPT / claude.ai ───[/]")
    console.print(
        f"{lead}\n"
        "Put your WHOLE reply in one fenced code block (```), each section "
        "as `N. Label` on its own line with its content on the line(s) "
        "below — the code block keeps the numbers intact when you copy it:\n"
    )
    for num, label, length in _LLM_TEMPLATE_SECTIONS:
        console.print(f"{num}. {label}  ({length})")
    console.print("[bold]───[/]")
    console.print(
        "[dim]Paste the whole reply at the first prompt below — smart-paste "
        "fills every section. Or answer section-by-section.[/]"
    )


def _resolve_growth_hypothesis(*, flag_value: str,
                               non_interactive: bool) -> str:
    """Return the operator's growth hypothesis as a single string
    (possibly empty).

    Resolution order:
      1. `--growth-hypothesis "X"` flag (whitespace stripped) → no
         prompt.
      2. `--non-interactive` → empty (docs/growth.md gets the
         pre-v9.D default first entry).
      3. Else: interactive multi-line prompt. Empty answer → empty
         result.

    Uses the multi-line prompt helper (bug-fix 2026-05-20) so
    multi-paragraph pastes don't overflow into the shell.
    """
    if flag_value.strip():
        return flag_value.strip()
    if non_interactive:
        return ""
    return _prompt_multiline(
        "\n[bold]Growth hypothesis[/]"
        " [dim](v9.D — seeds docs/growth.md's first dated entry)[/]",
        hint=(
            "One paragraph: what's your bet for how this site reaches "
            "its audience? Press Enter twice (or Ctrl-D) when done. "
            "Hit Enter twice immediately to skip — growth.md will get "
            "the default \"site scaffolded\" first entry."
        ),
    )


_REGISTRARS = ("porkbun", "godaddy", "namecheap", "other")


def _resolve_inventory_inputs(*, domain: str, registered: bool | None,
                              registrar: str, non_interactive: bool) -> dict:
    """Determine whether to update portfolio.json + with what fields.

    Returns a dict with keys:
      action:    "append" → call append_domain_row
                 "skip"   → no inventory write (operator opted out or
                            non-interactive without explicit flag)
                 "exists" → predetermined: row already in portfolio.json
                            (idempotent re-run); informational only
      registered: bool (when action != "skip")
      registrar:  str (when action != "skip")

    Decision rules:
      - If `name` already in portfolio.json → action="exists", no prompts.
      - If `registered` flag set + `registrar` flag set → action="append".
      - If `non_interactive` AND no `registered` flag → action="skip"
        (no inventory write; operator runs cleanup later).
      - Else interactive: prompt Y/n for registration + select registrar.
    """
    from .data import PORTFOLIO_JSON
    import json as _json

    # Existing-row short-circuit: skip prompts + inventory write entirely.
    if PORTFOLIO_JSON.exists():
        try:
            payload = _json.loads(PORTFOLIO_JSON.read_text())
            existing = {row.get("name", "").lower()
                        for row in payload.get("domains", [])}
        except (OSError, _json.JSONDecodeError):
            existing = set()
        if domain.lower() in existing:
            return {"action": "exists"}

    # Both flags supplied → no prompts.
    if registered is not None and registrar:
        if registrar not in _REGISTRARS:
            console.print(
                f"[red]--registrar must be one of {', '.join(_REGISTRARS)}; "
                f"got {registrar!r}.[/]"
            )
            raise typer.Exit(2)
        return {"action": "append", "registered": registered,
                "registrar": registrar}

    if non_interactive:
        # No explicit flag in batch mode → skip inventory write.
        # Operator can update later via fleet cleanup or a direct edit.
        if registered is None:
            return {"action": "skip"}
        # Flag set in non-interactive mode but registrar omitted →
        # assume porkbun, the fleet default (operator policy 2026-05-29).
        # An explicit --registrar always overrides.
        return {"action": "append", "registered": registered,
                "registrar": registrar or "porkbun"}

    # Interactive path. Prompt for registration status, then registrar.
    console.print(
        f"\n[bold]Domain inventory ([cyan]{domain}[/])[/]"
        " [dim](v9.C — auto-updates portfolio.json so "
        "`project check {domain}` resolves)[/]"
    )
    if registered is None:
        answer = typer.prompt(
            "  Is the domain registered? [Y/n]",
            default="Y", show_default=False,
        ).strip().lower()
        registered = answer not in ("n", "no")
    if not registrar:
        # Bug-fix 2026-05-20 — registrar prompt was accepting free
        # text; tighten to the canonical set with up to 3 retries
        # then fall back to "other". Case-insensitive + whitespace-
        # stripped.
        registrar = _prompt_registrar()

    return {"action": "append", "registered": registered,
            "registrar": registrar}


def _prompt_registrar(max_attempts: int = 3) -> str:
    """Interactive registrar prompt with retry-on-invalid.

    Accepts (case-insensitive, whitespace-stripped): porkbun / godaddy
    / namecheap / other. After `max_attempts` invalid responses, falls
    back to "other" rather than raising — keeps the bootstrap flow
    moving forward.
    """
    for _ in range(max_attempts):
        raw = typer.prompt(
            f"  Registrar [{'/'.join(_REGISTRARS)}]",
            default="porkbun", show_default=False,
        )
        candidate = raw.strip().lower()
        if candidate in _REGISTRARS:
            return candidate
        console.print(
            f"  [yellow]Accepted: {', '.join(_REGISTRARS)}[/]"
        )
    console.print(
        "  [dim]3 invalid attempts; defaulting to 'other'.[/]"
    )
    return "other"


def _apply_inventory_decision(domain: str, decision: dict) -> None:
    """Execute the resolved inventory decision. Logs the outcome so
    the operator sees what happened in the summary."""
    action = decision.get("action")
    if action == "skip":
        # Silent — non-interactive runs deliberately skipped this.
        return
    if action == "exists":
        console.print(
            f"[dim]  portfolio.json: row for {domain} already present; "
            f"no update.[/]"
        )
        return
    if action == "append":
        from .data import append_domain_row

        result = append_domain_row(
            name=domain,
            registrar=decision["registrar"],
            registered=decision["registered"],
        )
        status = "Active" if decision["registered"] else "Pending"
        if result == "added":
            console.print(
                f"[green]  ✓ portfolio.json: appended {domain} "
                f"(registrar={decision['registrar']}, status={status})[/]"
            )
        elif result == "exists":
            # Race condition (unlikely but defensive) — pre-check
            # didn't see the row but append did. Still informational.
            console.print(
                f"[dim]  portfolio.json: row for {domain} already present; "
                f"no update.[/]"
            )
        elif result == "no-file":
            console.print(
                f"[yellow]  ⚠ portfolio.json missing — run "
                f"`lamill fleet sync` to bootstrap the inventory, "
                f"then re-run this command (or add the row manually).[/]"
            )


# Bug-fix 2026-05-28 — per-section prompt numbers, matching the preflight
# banner + LLM-template prompt order (1=Lovable, 2=Summary, …, 9=Growth).
# Inline `[N/9]` on each prompt + a "✓ saved as <section>" echo break the
# visual blend that let the operator type ICP content into the Audience
# prompt (the ICP description rendered immediately after the Audience
# input with no boundary).
_OPERATOR_SECTION_NUMBERS: dict[str, str] = {
    "Summary": "2",
    "Audience": "3",
    "ICP": "4",
    "Goals": "5",
    "Content strategy": "6",
}


def _collect_operator_inputs(*,
                             summary: str, audience: str, icp: str,
                             goal: str, content_strategy: str,
                             non_interactive: bool,
                             extras_out: dict | None = None,
                             ) -> dict[str, str]:
    """Build the {heading → content} dict the bootstrap renderer
    consumes for operator-input sections.

    Flag values take precedence. Sections without a flag value get
    interactively prompted unless `non_interactive=True`, in which
    case they're left empty and the renderer drops in `(to be filled
    in)` placeholders.

    Bug-fix 2026-05-20 — smart multi-section paste. The first
    paragraph-style prompt (typically Summary) inspects the captured
    text via `parse_multisection_paste()`. When the operator pasted
    an LLM-staged 9-section response, the paste is split into
    canonical sections and (on operator confirm) the remaining
    AI_AGENTS prompts are auto-filled. Cross-section overrides
    (git_url / growth_hypothesis / registered / registrar) land in
    `extras_out` so the orchestrator can forward them to the
    downstream resolvers (`_resolve_git_url`, `_resolve_inventory_inputs`,
    `_resolve_growth_hypothesis`) without re-prompting.

    Returns a complete dict (one key per operator-input section,
    even if the value is empty) so the renderer doesn't need to
    guess defaults.
    """
    from .canonical_sections import operator_sections
    from .bootstrap_paste import (
        CANONICAL_LABELS,
        first_nonblank_line,
        looks_like_repo_url,
        normalize_registrar,
        normalize_yes_no,
        parse_multisection_paste,
        preview_snippet,
    )

    # Map CLI-flag value → canonical heading. Mirrors the order in
    # canonical_sections.AI_AGENTS_SECTIONS; the user-facing flag
    # names are flat (no `--` prefix here; typer adds those).
    flag_values: dict[str, str] = {
        "Summary": summary,
        "Audience": audience,
        "ICP": icp,
        "Goals": goal,
        "Content strategy": content_strategy,
    }

    inputs: dict[str, str] = {}
    pending_for_prompt: list = []
    for spec in operator_sections():
        v = flag_values.get(spec.heading, "").strip()
        if v:
            inputs[spec.heading] = v
        elif non_interactive:
            inputs[spec.heading] = ""   # placeholder will render
        else:
            pending_for_prompt.append(spec)
            inputs[spec.heading] = ""   # provisional; overwritten if prompted

    # Map canonical-paste keys → AI_AGENTS heading for operator
    # sections so a parsed paste can be sluiced into `inputs`.
    paste_key_to_heading: dict[str, str] = {
        "summary": "Summary",
        "audience": "Audience",
        "icp": "ICP",
        "goals": "Goals",
        "content_strategy": "Content strategy",
    }
    # Sections that render best on one line (single-line in AI_AGENTS).
    single_line_headings = {"Audience", "Goals"}

    if pending_for_prompt:
        console.print(
            "\n[bold]Operator content for AI_AGENTS.md[/]"
            " [dim](press Enter to skip; "
            "section will render `(to be filled in)`)[/]"
        )
        # Paragraph-style sections use the multi-line prompt helper so
        # multi-paragraph input doesn't overflow into the shell; the
        # one-line sections (Audience, Goals) stay on `typer.prompt`.
        multiline_sections = {"Summary", "ICP", "Content strategy"}

        # 2026-05-29 — lead with the full cut-and-paste. The operator's
        # primary path is: generate the reply in ChatGPT / claude.ai (the
        # template above) and paste the whole thing here. Pressing Enter
        # falls through to section-by-section prompts (Summary first). A
        # single non-blob paragraph here is taken as the Summary.
        pasted = _prompt_multiline(
            "\n  [bold]Paste the full reply[/] from the box above"
            " — finish with [bold]Ctrl-D[/].",
            hint=(
                "Smart-paste fills every section. Or press Enter to "
                "answer section-by-section instead."
            ),
            detect_blob=True,
        ).strip()
        if pasted:
            parsed = parse_multisection_paste(pasted)
            if parsed is not None and _confirm_multisection_paste(
                parsed, current_heading="Summary",
            ):
                _apply_multisection_paste(
                    parsed,
                    inputs=inputs,
                    extras_out=extras_out,
                    paste_key_to_heading=paste_key_to_heading,
                    single_line_headings=single_line_headings,
                    current_heading="Summary",
                )
            elif any(s.heading == "Summary" for s in pending_for_prompt):
                # Not a multi-section blob — a single paragraph the
                # operator typed → take it as the Summary; the remaining
                # sections still get prompted below.
                inputs["Summary"] = pasted
                console.print("  [green]✓ saved as Summary[/]")

        # Section-by-section for anything still empty (Summary included,
        # when the operator chose the by-hand path).
        for spec in pending_for_prompt:
            if inputs.get(spec.heading):
                continue
            _num = _OPERATOR_SECTION_NUMBERS.get(spec.heading, "?")
            if spec.heading in multiline_sections:
                answer = _prompt_multiline(
                    f"\n  [bold][{_num}/9][/] [cyan]{spec.heading}[/]"
                    f" — [dim]{spec.description}[/]",
                    hint=(
                        "Hit Enter twice when done, or Ctrl-D. "
                        "Enter twice immediately to skip."
                    ),
                ).strip()
            else:
                console.print(
                    f"\n  [bold][{_num}/9][/] [cyan]{spec.heading}[/]"
                    f" — [dim]{spec.description}[/]"
                )
                answer = typer.prompt(
                    "  >", default="", show_default=False,
                ).strip()
            if answer:
                inputs[spec.heading] = answer
                # Echo a confirmation so the next prompt's description
                # can't blend into this section's input area (the
                # Audience/ICP confusion, 2026-05-28).
                console.print(f"  [green]✓ saved as {spec.heading}[/]")

    return inputs


def _confirm_multisection_paste(parsed: dict[str, str], *,
                                current_heading: str) -> bool:
    """Print the multi-section preview banner and prompt for confirmation.

    Bug-fix 2026-05-20 — when smart-paste detects a multi-section
    response at the Summary prompt, show the operator each detected
    section's name + a short snippet so they can verify the parse
    before auto-fill commits. Default Yes (Enter to accept).

    Returns True on Y / yes / empty (default); False on N / no.
    """
    from .bootstrap_paste import CANONICAL_LABELS, preview_snippet

    n = len(parsed)
    console.print(
        f"\n[bold]Detected a multi-section paste with {n} sections:[/]"
    )
    # Preserve insertion order so the preview matches the operator's
    # mental model of how their LLM laid out the response.
    for key, content in parsed.items():
        label = CANONICAL_LABELS.get(key, key)
        snippet = preview_snippet(content, limit=80)
        console.print(
            f"  [green]✓[/] [bold]{label:<22}[/] [dim]{snippet}[/]"
        )
    raw = typer.prompt(
        "\n  Auto-fill the remaining prompts from this paste? [Y/n]",
        default="Y", show_default=False,
    ).strip().lower()
    return raw not in ("n", "no")


def _apply_multisection_paste(parsed: dict[str, str], *,
                              inputs: dict[str, str],
                              extras_out: dict | None,
                              paste_key_to_heading: dict[str, str],
                              single_line_headings: set[str],
                              current_heading: str) -> None:
    """Sluice a parsed multi-section paste into the orchestrator state.

    Populates `inputs[]` for any matched AI_AGENTS heading and
    `extras_out[]` for cross-section overrides (git_url /
    growth_hypothesis / registered / registrar). Sections missing
    from the paste are left for the regular prompt flow."""
    from .bootstrap_paste import (
        CANONICAL_LABELS,
        first_nonblank_line,
        looks_like_repo_url,
        normalize_registrar,
        normalize_yes_no,
        preview_snippet,
    )

    valid_registrars = _REGISTRARS  # ("porkbun", "godaddy", "namecheap", "other")
    filled: list[tuple[str, str]] = []

    for key, content in parsed.items():
        heading = paste_key_to_heading.get(key)
        if heading is not None:
            value = content.strip()
            if heading in single_line_headings:
                value = first_nonblank_line(value)
            if value:
                inputs[heading] = value
                filled.append((CANONICAL_LABELS.get(key, heading), value))
            continue

        # Cross-section overrides — only populated when extras_out is
        # supplied (the orchestrator path). Stand-alone callers that
        # don't pass extras_out (e.g. unit tests that don't care)
        # silently ignore these.
        if extras_out is None:
            continue

        if key == "growth_hypothesis":
            value = content.strip()
            if value:
                extras_out["growth_hypothesis"] = value
                filled.append(("Growth hypothesis", preview_snippet(value)))
        elif key == "domain_registered":
            parsed_bool = normalize_yes_no(content)
            if parsed_bool is not None:
                extras_out["registered"] = parsed_bool
                filled.append(
                    ("Domain registered?",
                     "yes" if parsed_bool else "no"),
                )
        elif key == "registrar":
            value = normalize_registrar(content, valid_registrars)
            extras_out["registrar"] = value
            filled.append(("Registrar", value))
        elif key == "lovable_repo":
            value = content.strip()
            if value and looks_like_repo_url(value):
                extras_out["git_url"] = value
                filled.append(("Lovable GitHub repo URL", value))
            elif value:
                # Non-URL-shaped — skip rather than crashing the
                # downstream `_resolve_git_url` validator.
                console.print(
                    f"  [yellow]Skipping Lovable repo value "
                    f"(doesn't look like a URL): {value!r}[/]"
                )

    if filled:
        console.print("\n[bold]Auto-filled from paste:[/]")
        for label, value in filled:
            console.print(
                f"  [green]✓[/] [bold]{label:<22}[/] "
                f"[dim]{preview_snippet(value)}[/]"
            )


def _render_bootstrap_summary(result, domain: str, *, topic: str = "") -> None:
    """Post-bootstrap report: header, file inventory, tree view, conformance
    pass/fail, predicted live URL, grouped next-step commands.

    When `topic` is non-empty, a one-line `Topic:` header is printed
    first — same operator-facing affordance as `new validate` /
    `new domain`. Empty topic omits the line.
    """
    if topic:
        console.print(f"[bold]Topic:[/] [cyan]{topic}[/]\n")
    console.print(
        f"[green]✓[/] Bootstrapped [bold]{result.project_dir}[/]  "
        f"[dim](path={result.path}, stack={result.stack})[/]"
    )

    if result.files_copied:
        console.print(f"\n[bold]Copied from genai/ ({len(result.files_copied)}):[/]")
        for f in result.files_copied:
            console.print(f"  • {f}")

    if result.cf_fixes:
        console.print(f"\n[bold]Cloudflare Pages safety fixes ({len(result.cf_fixes)}):[/]")
        for fix in result.cf_fixes:
            console.print(f"  • {fix}")

    if result.files_written:
        console.print(f"\n[bold]Files written ({len(result.files_written)}):[/]")
        for f in sorted(result.files_written):
            console.print(f"  • {f}")

    # v18.D — surface GA4 auto-create outcome. Always render the line
    # so the operator sees whether GA4 was wired (or why it wasn't).
    if result.ga4_status:
        if result.ga4_status == "created":
            console.print(
                f"\n[green]✓[/] GA4 property created · "
                f"measurement ID [cyan]{result.ga4_measurement_id}[/] "
                f"written to lamill.toml [dim][analytics][/]"
            )
        elif result.ga4_status.startswith("skipped:"):
            console.print(
                f"\n[yellow]↷[/] GA4 property creation "
                f"[dim]{result.ga4_status[len('skipped:'):]}[/]"
            )
        elif result.ga4_status.startswith("failed:"):
            console.print(
                f"\n[red]✗[/] GA4 property creation failed (continuing) · "
                f"[dim]{result.ga4_status[len('failed:'):]}[/]"
            )

    # v29.D — surface [content] derivation outcome (ADR-0019). Derived
    # from the operator's authored AI_AGENTS sections; best-effort.
    if result.content_seeded:
        console.print(
            f"\n[green]✓[/] [content] seeded from your AI_AGENTS docs · "
            f"{len(result.content_seeded)} field(s): "
            f"[cyan]{', '.join(result.content_seeded)}[/] "
            f"[dim](review + fill any gaps via the starter todo)[/]"
        )
    else:
        console.print(
            "\n[yellow]↷[/] [content] left empty "
            "[dim](no OPENAI_API_KEY or no AI_AGENTS brief) — fill it in via the starter todo[/]"
        )

    if result.git_initialized:
        sha = result.initial_commit_sha[:7] if result.initial_commit_sha else "?"
        console.print(f"\n[green]✓[/] git initialized; initial commit [dim]{sha}[/]")
    else:
        console.print("\n[yellow]✗[/] git init failed — initialize manually")

    # v4.D polish 2026-05-08: tree view of the actual scaffold.
    _render_project_tree(result.project_dir)

    if result.warnings:
        console.print(f"\n[yellow]Warnings ({len(result.warnings)}):[/]")
        for w in result.warnings:
            console.print(f"  • {w}")

    # Conformance quick-check against the new project.
    _render_bootstrap_conformance(domain)

    # Predicted live URL.
    console.print(f"\n[bold]Live URL after deploy:[/]  [cyan]https://{domain}/[/]")

    # Grouped next steps with concrete commands.
    console.print("\n[bold]Next steps:[/]")
    console.print("  [bold cyan]Local dev[/]")
    console.print(f"    cd sites/{domain}")
    console.print("    make deps           [dim]# install dependencies via the central builder[/]")
    console.print("    make dev            [dim]# start the dev server[/]")
    console.print("  [bold cyan]Deploy[/]")
    console.print(f"    portfolio new deploy {domain}     [dim]# create GH repo + Cloudflare Pages project[/]")
    console.print("  [bold cyan]Verify after deploy[/]")
    console.print(f"    lamill fleet domains                       [dim]# refresh check snapshot[/]")
    console.print(f"    portfolio project check {domain}      [dim]# full conformance report[/]")


def _render_project_tree(project_dir) -> None:
    """Print a top-level tree of the bootstrapped project (one level deep,
    plus a count for any subdirectories that have entries). Skips .git and
    node_modules to avoid noise."""
    from pathlib import Path
    p = Path(project_dir)
    if not p.exists():
        return
    SKIP = {".git", "node_modules", "dist", ".venv", "__pycache__"}
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
    console.print(f"\n[bold]Project tree:[/]  [dim]{p.name}/[/]")
    for entry in entries:
        if entry.name in SKIP:
            continue
        if entry.is_dir():
            children = [c for c in entry.iterdir() if c.name not in SKIP]
            count = len(children)
            console.print(f"  ├── [bold cyan]{entry.name}/[/]  [dim]({count} entries)[/]")
        else:
            console.print(f"  ├── {entry.name}")


def _render_bootstrap_conformance(domain: str) -> None:
    """Run the universal check catalog against the freshly-bootstrapped project
    (scaffold + stack + deploy + seo categories — git is skipped since the new
    project hasn't been pushed yet) and print pass/fail per check.

    v5.C: switched from the legacy `project.build_status` rule list to the
    registry-based runner so a single source of truth (the catalog) drives
    every conformance surface."""
    from pathlib import Path

    from .checks import list_checks, load_config, run_checks
    from .data import ROOT as DATA_ROOT

    project_dir = DATA_ROOT.parent / domain
    if not project_dir.is_dir():
        console.print(f"\n[yellow]Conformance check skipped:[/] {project_dir} not found")
        return

    cfg = load_config()
    bootstrap_categories = {"scaffold", "docs", "stack", "deploy", "seo"}
    catalog_specs = [s for s in list_checks() if s.category in bootstrap_categories]
    catalog_ids = [s.id for s in catalog_specs]

    try:
        results = run_checks(str(project_dir), ids=catalog_ids,
                             skip_checks=cfg.skip_checks)
    except Exception as e:
        console.print(f"\n[yellow]Conformance check skipped:[/] {type(e).__name__}: {e}")
        return

    by_id = {s.id: s for s in catalog_specs}
    passed = [cid for cid, r in results.items() if r.status == "pass"]
    failed = [(cid, r) for cid, r in results.items() if r.status == "fail"]
    warned = [(cid, r) for cid, r in results.items() if r.status == "warn"]

    console.print(
        f"\n[bold]Conformance ({len(passed)} pass · {len(failed)} fail · {len(warned)} warn):[/]"
    )
    for cid in sorted(passed):
        spec = by_id[cid]
        console.print(f"  [green]✓[/] {cid} {spec.name}")
    for cid, r in sorted(failed):
        spec = by_id[cid]
        console.print(f"  [red]✗[/] {cid} {spec.name}  [dim]— {r.message}[/]")
    if warned:
        # Most warns are stack-aware skips ("not a Vite project — skipped"); fold them.
        skipped = [(cid, r) for cid, r in warned if "skipped" in r.message]
        real_warns = [(cid, r) for cid, r in warned if "skipped" not in r.message]
        for cid, r in sorted(real_warns):
            spec = by_id[cid]
            console.print(f"  [yellow]![/] {cid} {spec.name}  [dim]— {r.message}[/]")
        if skipped:
            console.print(
                f"  [dim]skipped ({len(skipped)}): "
                + ", ".join(cid for cid, _ in sorted(skipped))
                + "[/]"
            )
