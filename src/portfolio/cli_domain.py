"""v35.F incr 4 — `new domain` menu / decide / grid engine, extracted from cli.py.

Behavior-preserving extraction (H1; architecture.md § Tracked refactors § v35).
This is the interactive engine behind `lamill new domain`: the post-grid menu,
the registrar grid renderer, the shortlist + 6-step decide flow, the two
orchestrators (`_domain_suggest_validation` / `_domain_suggest_browse`), and
the input parsers they share.

Self-contained by design: provider deps (decide / suggest / availability) are
imported lazily inside the function bodies, so the only module-level
dependencies are the shared `console`, `typer`, `re`, and rich's `Table`.
cli.py re-exports every public name defined here, so existing
`from portfolio.cli import X` imports (callers + tests) keep working, and the
`@new_app.command("domain")` callback stays in cli.py and calls the two
orchestrators imported from here.
"""
from __future__ import annotations

import re

import typer
from rich.table import Table

from .console import console


def parse_pick_input(s: str, n_rows: int, columns: list[str]) -> tuple[int | None, str | None, str | None]:
    """Parse the picker's `N` or `N.tld` input.

    Returns `(row_idx_0based, override_tld_or_None, error_msg_or_None)`. Either
    a successful parse (idx + optional tld, no error) or `(None, None, err)`.
    The override TLD must be one of the displayed columns; out-of-range row
    indexes and unknown TLDs are surfaced as errors.
    """
    s = s.strip().lower()
    if not s:
        return None, None, "empty input"
    if "." in s:
        digit_part, tld_part = s.split(".", 1)
        tld = "." + tld_part
    else:
        digit_part, tld = s, None
    if not digit_part.isdigit():
        return None, None, f"'{s}': expected a row number (e.g. 5 or 5.app)"
    idx = int(digit_part) - 1
    if idx < 0 or idx >= n_rows:
        return None, None, f"row {digit_part} out of range (1-{n_rows})"
    if tld is not None and tld not in columns:
        return None, None, f"TLD {tld} not in displayed columns; choose from {' '.join(columns)}"
    return idx, tld, None


def parse_expand_input(s: str, rows) -> tuple[int | None, str | None]:
    """Parse the picker's expand command: `eN` or `e <name>`.

    Returns `(row_idx_0based, error_msg_or_None)`. Accepts:
      - `e5` / `e 5`  → row index lookup
      - `e codebeacon` / `e codebeacon.site` → name lookup (case-insensitive,
        prefix match acceptable; `.tld` suffix stripped)

    Returns `(None, "...")` on no-match or ambiguous-match (multiple prefix
    matches when rows differ).
    """
    s = s.strip().lower()
    if not s.startswith("e"):
        return None, "not an expand command"
    rest = s[1:].strip()
    if not rest:
        return None, "empty expand target — try 'e5' or 'e <name>'"
    if rest.isdigit():
        idx = int(rest) - 1
        if idx < 0 or idx >= len(rows):
            return None, f"row {rest} out of range (1-{len(rows)})"
        return idx, None
    # Strip optional `.tld` suffix
    name_part = rest.split(".", 1)[0] if "." in rest else rest
    if not re.match(r"^[a-z][a-z0-9]*$", name_part):
        return None, f"'{rest}' isn't a valid name or row number"
    matches = [(i, r) for i, r in enumerate(rows) if r.name.lower() == name_part]
    if not matches:
        # Try prefix match if no exact
        matches = [(i, r) for i, r in enumerate(rows) if r.name.lower().startswith(name_part)]
    if not matches:
        return None, f"no row matches '{name_part}'"
    if len(matches) > 1:
        names = ", ".join(r.name for _, r in matches[:5])
        return None, f"'{name_part}' is ambiguous: {names}"
    return matches[0][0], None


# v3.E 2026-05-08: post-grid menu. The menu replaces all the inline picker
# prompts (was N | N.tld | eN | "Add your own names?" auto-loop) with a
# numbered chooser. Re-shown after every non-terminating action; only
# successful registration or `q` exits.
# Menu items. (key, label, coming_soon). Slots 3 and 4 are reserved for
# v4.C (ask AI, widen) and not present yet. Slot 7 (decide from shortlist)
# is stubbed in v4.A as coming-soon for v4.B; slot 6 (mark/unmark shortlist)
# is active in v4.A. Stable numbering preserves muscle memory across phases.
MENU_ITEMS = [
    ("1", "Pick a row to register",                    False),
    ("2", "Expand a row (full-ladder detail)",         False),
    ("3", "Ask AI about a name",                       False),  # v4.C
    ("4", "Widen search — more candidates",            False),  # v4.C
    ("5", "Add my own names to the grid",              False),
    ("6", "Mark / unmark for shortlist",               False),
    ("7", "Decide from shortlist",                     False),
    # 2026-05-21: dropped letter-keyed `s` in favor of pure numeric
    # menu. Was `s` (between 7 and 8) — broke the eye's left-column
    # numeric scan. Now `8` keeps the affordance next to its 6/7
    # shortlist siblings; `9` and `10` follow.
    ("8", "Show marked names as full grid",            False),
    ("9", "Show TLD reference (pricing, SEO, vibe)",   False),
    ("10", "Rerun fresh (bypass cache)",               False),  # v4.D polish
]


# v4.B 2026-05-08: option 7 is now active. No coming-soon hints in v4.B;
# the constant is preserved (empty) for future stub use.
COMING_SOON_HINTS: dict[str, str] = {}


# v3.E 2026-05-08: per-TLD reference card. Surfaced via menu option 8 so the
# user can recall the operator / SEO / vibe / catch detail without leaving
# the tool. Card format mirrors the chat reference verbatim for the four
# TLDs the user emphasized (.app .dev .xyz .site) and matches that detail
# level for the rest of the default + full ladder.
TLD_REFERENCE = [
    {
        "tld": ".com",
        "grade": "A+",
        "operator": "Verisign",
        "reg": "$11",
        "renew": "$11",
        "vibe": "universal default; the global brand standard",
        "trust": "highest — recognized everywhere; what users type by default",
        "seo": "no penalty; baseline for everything else",
        "best_for": "any commercial site you intend to keep",
        "catch": "high collision risk; most short names already taken",
    },
    {
        "tld": ".app",
        "grade": "A",
        "operator": "Google Registry (2018)",
        "reg": "$11",
        "renew": "$15",
        "vibe": "modern app/SaaS, app-store adjacent",
        "trust": "high — Google-run, HSTS-preloaded (entire TLD forces HTTPS)",
        "seo": "no penalty",
        "best_for": "validation MVPs, mobile/web apps",
        "catch": "none meaningful",
    },
    {
        "tld": ".dev",
        "grade": "A",
        "operator": "Google Registry (2019)",
        "reg": "$11",
        "renew": "$13",
        "vibe": "developer tools, technical projects",
        "trust": "very high in tech audiences; HSTS-preloaded",
        "seo": "no penalty",
        "best_for": "dev tools, libraries, technical MVPs",
        "catch": "reads \"internal/staging\" to non-technical audiences",
    },
    {
        "tld": ".co",
        "grade": "B+",
        "operator": ".CO Internet S.A.S (2010)",
        "reg": "$10",
        "renew": "$27",
        "vibe": "Colombia ccTLD repurposed as a global .com alternative",
        "trust": "mid-high; mainstream-recognized after Twitter t.co et al.",
        "seo": "no penalty",
        "best_for": "fallback when .com is taken and you want a similar feel",
        "catch": "2.7× renewal cliff; users still type .com by reflex",
    },
    {
        "tld": ".xyz",
        "grade": "B+",
        "operator": "XYZ.com LLC (2014)",
        "reg": "$2",
        "renew": "$13",
        "vibe": "cheap-and-cheerful; legitimized by Alphabet (abc.xyz), Ethereum/ENS, web3 generally",
        "trust": "medium-high in tech, mixed in mainstream",
        "seo": "no penalty (one of the largest gTLDs by volume)",
        "best_for": "crypto-adjacent, experimental, Gen-Z-ish brands",
        "catch": "still reads \"scammy\" to some older/non-tech users",
    },
    {
        "tld": ".ai",
        "grade": "A-",
        "operator": "Government of Anguilla",
        "reg": "$83",
        "renew": "$83",
        "vibe": "AI startup signal; specialized but instantly read",
        "trust": "high in tech; carries clear positioning",
        "seo": "no penalty",
        "best_for": "AI/ML products you intend to keep long-term",
        "catch": "$83/yr — too steep for cheap validation",
    },
    {
        "tld": ".io",
        "grade": "B",
        "operator": "Internet Computer Bureau (British Indian Ocean Territory)",
        "reg": "$28",
        "renew": "$52",
        "vibe": "tech/startup default; reads developer-flavored",
        "trust": "high in tech; mainstream-aware",
        "seo": "no penalty",
        "best_for": "tech products willing to pay the premium",
        "catch": "$28 reg + ~2× renewal cliff; price-capped out for cheap validation",
    },
    {
        "tld": ".site",
        "grade": "C",
        "operator": "Radix Registry",
        "reg": "$2",
        "renew": "$30",
        "vibe": "generic, literal (\"this is a site\")",
        "trust": "low-mid; over-represented in parked-domain and spam datasets",
        "seo": "no penalty per Google, but signals \"low-effort\"",
        "best_for": "throwaway prototypes you'll let expire",
        "catch": "15× renewal cliff; weakest brand of the cheap tier",
    },
    {
        "tld": ".shop",
        "grade": "C",
        "operator": "GMO Registry",
        "reg": "$2",
        "renew": "$31",
        "vibe": "e-commerce-flavored; literally retail",
        "trust": "low-mid; locked to retail positioning",
        "seo": "no penalty per Google; reads narrow",
        "best_for": "e-commerce experiments / one-product stores",
        "catch": "15× renewal cliff; pigeonholes non-retail brands",
    },
    {
        "tld": ".life",
        "grade": "C",
        "operator": "Identity Digital (formerly Donuts)",
        "reg": "$2",
        "renew": "$29",
        "vibe": "generic lifestyle; vague",
        "trust": "low-mid; lacks definition",
        "seo": "no penalty; just unmemorable",
        "best_for": "lifestyle/wellness experiments; throwaways",
        "catch": "14× renewal cliff; brand is too soft to anchor anything",
    },
    {
        "tld": ".info",
        "grade": "C+",
        "operator": "Identity Digital",
        "reg": "$3",
        "renew": "$22",
        "vibe": "informational sites; reads dated (early-2000s)",
        "trust": "mid; recognized but unfashionable",
        "seo": "no penalty technically; \"info\" suffix can read SEO-bait",
        "best_for": "reference / informational properties; not products",
        "catch": "7× renewal cliff; dated feel limits brand growth",
    },
    {
        "tld": ".pro",
        "grade": "C+",
        "operator": "Identity Digital",
        "reg": "$3",
        "renew": "$22",
        "vibe": "professional services; was originally identity-verified",
        "trust": "mid; fine but narrow",
        "seo": "no penalty",
        "best_for": "individual practitioners, professional portfolios",
        "catch": "7× renewal cliff; \".pro\" reads niche, not product",
    },
]

# Closing summary the user asked for verbatim — anchors the trade-offs
# in the validation-pipeline context.
TLD_REFERENCE_SUMMARY = (
    "For your validation pipeline: .app and .dev are honest peers of .com "
    "(low renewal, dev-credible). .xyz is the cheap-grab that doesn't punish "
    "you on renewal. .site is fine for week-1 experiments but don't keep them."
)


def _render_tld_reference() -> None:
    """Print the per-TLD reference. One card per TLD with operator, reg/renew,
    vibe, trust, SEO, best-for, catch. Closes with a one-paragraph summary
    that frames the trade-offs in validation-pipeline terms."""
    grade_color = {
        "A+": "green", "A": "green", "A-": "green",
        "B+": "cyan",  "B": "cyan",
        "C+": "yellow", "C": "yellow",
    }
    console.print("\n[bold]TLD reference — pricing, SEO, vibe[/]\n")
    for entry in TLD_REFERENCE:
        color = grade_color.get(entry["grade"], "white")
        console.print(
            f"  [bold]{entry['tld']}[/]    Grade: [{color}]{entry['grade']}[/]"
        )
        console.print(f"    operator   {entry['operator']}")
        console.print(f"    reg/renew  {entry['reg']} / {entry['renew']}")
        console.print(f"    vibe       {entry['vibe']}")
        console.print(f"    trust      {entry['trust']}")
        console.print(f"    SEO        {entry['seo']}")
        console.print(f"    best for   {entry['best_for']}")
        console.print(f"    catch      {entry['catch']}")
        console.print()
    console.print(f"[dim]{TLD_REFERENCE_SUMMARY}[/]")


def _render_menu(shortlist_count: int = 0) -> None:
    """Render the post-grid menu. When shortlist_count > 0, items 6
    (Mark / unmark) and 8 (Show marked as grid) both get a
    "(N marked)" suffix so the user can see at a glance how big their
    shortlist has grown."""
    console.print("\n[bold]What do you want to do next?[/]")
    for key, label, coming_soon in MENU_ITEMS:
        line = f"  {key}. {label}"
        if key in ("6", "8") and shortlist_count > 0:
            line += f" ({shortlist_count} marked)"
        if coming_soon:
            line += "  [dim](coming soon)[/]"
        console.print(line)
    console.print("  q. Quit")


def _menu_keys_hint() -> str:
    """Format the menu keys for the bad-input hint, e.g. '1, 2, 5, 6, 7, 8'."""
    return ", ".join(k for k, _, _ in MENU_ITEMS)


def _menu_pick(rows, tld_list):
    """Sub-prompt for menu option 1. Returns (row, tld) on success or None."""
    sub = typer.prompt("Which row? (N, N.tld, or name.tld)", default="", show_default=False).strip().lower()
    if not sub:
        return None
    idx, override_tld, err = parse_pick_input(sub, len(rows), tld_list)
    if err:
        # Also accept "name.tld" or bare "name" — look up the row by name.
        if "." in sub:
            name_part, tld_part = sub.split(".", 1)
            lookup_tld: str | None = "." + tld_part
        else:
            name_part, lookup_tld = sub, None
        if not name_part.isdigit() and re.match(r"^[a-z][a-z0-9-]*$", name_part):
            matches = [i for i, r in enumerate(rows) if r.name.lower() == name_part]
            if not matches:
                matches = [i for i, r in enumerate(rows) if r.name.lower().startswith(name_part)]
            if len(matches) == 1:
                idx, override_tld, err = matches[0], lookup_tld, None
                if lookup_tld is not None and lookup_tld not in tld_list:
                    console.print(f"[red]TLD {lookup_tld} not in displayed columns; choose from {' '.join(tld_list)}[/]")
                    return None
            elif len(matches) > 1:
                names = ", ".join(rows[i].name for i in matches[:5])
                console.print(f"[red]'{name_part}' is ambiguous: {names}[/]")
                return None
        if err:
            console.print(f"[red]{err}[/]")
            return None
    row = rows[idx]
    if override_tld is not None:
        cell = row.cells.get(override_tld)
        if cell is None:
            console.print(f"[red]{override_tld} not in this row.[/]")
            return None
        if cell.available is False:
            console.print(f"[red]{row.name}{override_tld} is taken.[/]")
            return None
        if cell.over_max:
            console.print(f"[red]{row.name}{override_tld} is priced over --max-price (${cell.price:.2f}).[/]")
            return None
        return row, override_tld
    if row.pick_tld is None:
        avail = [t for t, c in row.cells.items() if c.available is not False and not c.over_max]
        hint = f" — e.g. `{idx + 1}{avail[0]}` for {row.name}{avail[0]}" if avail else ""
        console.print(f"[red]{row.name} has no recommended TLD (.com poisoned). "
                      f"Use N.tld to specify{hint}.[/]")
        return None
    return row, row.pick_tld


def _menu_expand(rows, tld_list, max_price, show_renewal):
    """Sub-prompt for menu option 2. Reuses parse_expand_input by prefixing 'e '
    so user can type a bare row number or name. Returns (row, tld) if user
    picked from the expanded view, otherwise None."""
    sub = typer.prompt("Which row? (number or name)", default="", show_default=False).strip().lower()
    if not sub:
        return None
    cmd = "e " + sub
    idx, err = parse_expand_input(cmd, rows)
    if err:
        console.print(f"[red]{err}[/]")
        return None
    return _expand_and_pick(rows[idx], tld_list, max_price, show_renewal=show_renewal)


def parse_shortlist_input(s: str, rows) -> tuple[str | None, list[str], list[str]]:
    """Parse a shortlist sub-prompt input. Returns `(action, names, errors)`.

    Accepts (single OR multi-target; comma- and/or whitespace-separated):
      - `m N` / `m N1 N2 ...` / `m alpha beta` → ("mark", [...], [...])
      - `u N` / `u N1, N2`                      → ("unmark", [...], [...])
      - empty / `b` → ("back", [], [])
      - **bare targets without a verb** → implicit mark, e.g. `39 18`
        becomes `("mark", ["row39name", "row18name"], [])`.

    Per-target errors (out-of-range, unknown name) accumulate in the errors
    list while valid targets accumulate in names — partial successes succeed.
    A pure parse failure (missing targets after `m`/`u`) returns
    `(None, [], [error])`.

    Note: the `p` (print) action was removed in v4.A polish — the shortlist
    is auto-printed when the user enters the sub-prompt, so an explicit
    print verb is redundant.
    """
    s = s.strip().lower()
    if not s or s == "b":
        return "back", [], []
    parts = s.split(None, 1)
    first = parts[0]
    if first in ("m", "u"):
        if len(parts) < 2:
            return None, [], [f"missing target(s) after '{first}'"]
        verb = first
        rest = parts[1].strip()
    else:
        # Implicit mark — treat the entire input as targets.
        verb = "m"
        rest = s
    # Tokenize targets — accept comma OR whitespace separators.
    targets = [t for t in re.split(r"[,\s]+", rest) if t]
    if not targets:
        return None, [], [f"missing target(s) after '{verb}'"]
    resolved: list[str] = []
    errors: list[str] = []
    for target in targets:
        if target.isdigit():
            idx = int(target) - 1
            if idx < 0 or idx >= len(rows):
                errors.append(f"row {target} out of range (1-{len(rows)})")
                continue
            resolved.append(rows[idx].name)
        else:
            name_part = target.split(".", 1)[0] if "." in target else target
            match = next((r for r in rows if r.name.lower() == name_part), None)
            if match is None:
                errors.append(f"no row matches '{name_part}'")
                continue
            resolved.append(match.name)
    action = "mark" if verb == "m" else "unmark"
    return action, resolved, errors


def _print_shortlist(shortlist: list[str], rows) -> None:
    """Pretty-print the current shortlist with each finalist's pick TLD + price."""
    if not shortlist:
        console.print("[yellow]Shortlist is empty.[/]")
        return
    console.print(f"\n[bold]Shortlist ({len(shortlist)}):[/]")
    by_name = {r.name: r for r in rows}
    for i, name in enumerate(shortlist, 1):
        row = by_name.get(name)
        if row is None:
            console.print(f"  {i}. {name}  [dim](not in current grid)[/]")
            continue
        pick = row.pick_label or "-"
        # Surface the price of the picked TLD if known.
        price_s = ""
        if row.pick_tld:
            cell = row.cells.get(row.pick_tld)
            if cell and cell.price is not None:
                price_s = f"  ${cell.price:.0f}"
        console.print(f"  {i}. [bold]{name}[/]  Pick: [cyan]{pick}[/]{price_s}")


# v4.C 2026-05-08: ask-AI-about-a-name (option 3) orchestrator.


def _menu_ask_ai(rows, topic: str, vocab_terms: list[str] | None,
                 openai_key: str) -> None:
    """Sub-prompt for menu option 3. Forgiving parser: scans the full input
    for any token that matches a row name (case-insensitive, .tld stripped).
    First match wins; the entire input becomes the question.

    Accepts:
      - `donready`                            → name=donready, default Q
      - `donready is this clinical?`          → name=donready, question=full input
      - `what is donready`                    → name=donready, question=full input
      - `compare donready vs scrubsync`       → name=donready (first match), Q=full input
    """
    from .decide import ask_ai_about_name
    if not openai_key:
        console.print("[red]OPENAI_API_KEY not set — Ask AI requires it.[/]")
        return
    sub = typer.prompt(
        "Which name to ask about? (e.g. 'donready' or 'what is donready')",
        default="", show_default=False,
    ).strip()
    if not sub:
        return
    # Token-scan for first matching row name.
    name_lookup = {r.name.lower(): r for r in rows}
    tokens = re.findall(r"[a-z][a-z0-9]*", sub.lower())
    match = next((name_lookup[t] for t in tokens if t in name_lookup), None)
    if match is None:
        sample = ", ".join(r.name for r in rows[:6])
        more = "..." if len(rows) > 6 else ""
        console.print(f"[red]No row name found in your input. Try one of:[/] {sample}{more}")
        return
    # Whether the user typed just the name (use default question) or wrote
    # a sentence (use the whole input as the question).
    only_name = sub.strip().lower() == match.name.lower()
    question = "" if only_name else sub
    console.print(f"[dim]asking gpt-5-mini about [bold]{match.name}[/]...[/]")
    try:
        answer = ask_ai_about_name(match.name, topic, vocab_terms, question, openai_key)
    except Exception as e:
        console.print(f"[red]Ask AI failed: {type(e).__name__}: {e}[/]")
        return
    console.print(f"\n[bold]{match.name}[/]")
    console.print(f"  {answer}\n")


# v4.C 2026-05-08: widen-search (option 4) orchestrator.


def _menu_widen(rows, *, topic: str, vocab_terms: list[str] | None,
                tld_list: list[str], max_price: float, pricing_dict: dict | None,
                avail_fn, show_renewal: bool, openai_key: str, log_fn):
    """Sub-prompt for menu option 4. Asks the user for optional guidance
    ("shorter", "foreign roots", etc.), calls widen_brainstorm, probes
    availability, merges into the grid. Returns the (possibly-merged)
    rows list."""
    from .suggest import (
        FULL_LADDER, build_grid, filter_pickable_rows, widen_brainstorm,
    )
    if not openai_key:
        console.print("[red]OPENAI_API_KEY not set — Widen requires it.[/]")
        return rows
    guidance = typer.prompt(
        "Guidance? (optional, e.g. 'shorter', 'foreign roots'; Enter for none)",
        default="", show_default=False,
    ).strip()
    history = [r.name for r in rows]
    console.print("[dim]asking gpt-5-mini for widened candidates...[/]")
    new_cands = widen_brainstorm(
        topic=topic, history=history, vocab_terms=vocab_terms,
        guidance=guidance, api_key=openai_key, log_fn=log_fn,
    )
    if not new_cands:
        console.print("[yellow]No new candidates returned. Try different guidance or run again.[/]")
        return rows
    console.print(f"[dim]+ {len(new_cands)} new name(s): {', '.join(c.name for c in new_cands)}[/]")
    new_rows = build_grid(
        new_cands, topic, tld_list, avail_fn,
        max_price=max_price, pricing_dict=pricing_dict,
        full_ladder=list(FULL_LADDER),
        vocab_terms=vocab_terms,
    )
    new_rows = filter_pickable_rows(new_rows)
    if not new_rows:
        console.print(f"[yellow]Widen produced names but none had a pickable cell under --max-price=${max_price:.2f}.[/]")
        return rows
    new_names = {r.name for r in new_rows}
    merged = new_rows + [r for r in rows if r.name not in new_names]
    merged.sort(key=lambda r: r.name.lower())
    _render_grid(merged, tld_list, show_renewal=show_renewal, topic=topic)
    return merged


# v4.B 2026-05-08: decide-from-shortlist orchestrator + helpers.


def _render_decide_table(finalists, max_price: float) -> None:
    """Focused comparison table for the decide phase. Columns:
    name · reg · renew (with cliff marker) · pick · anchors · defense.
    No per-TLD cell columns (cleaner than the full grid)."""
    t = Table(box=None, padding=(0, 1), show_header=True,
              title="[bold]Decide — finalists comparison[/]",
              title_justify="left")
    t.add_column("#", justify="right")
    t.add_column("Name", style="bold")
    t.add_column("Reg", justify="right")
    t.add_column("Renew", justify="right")
    t.add_column("Pick", style="cyan")
    t.add_column("Anchors", style="magenta")
    t.add_column("Defense")
    for i, row in enumerate(finalists, 1):
        pick_tld = row.pick_tld or "-"
        cell = row.cells.get(pick_tld) if row.pick_tld else None
        reg_s = f"${cell.price:.0f}" if (cell and cell.price is not None) else "-"
        renew_val = cell.renewal if cell else None
        renew_s = f"${renew_val:.0f}" if renew_val is not None else "-"
        cliff = _renewal_cliff_marker(cell.price if cell else None, renew_val)
        if cliff:
            renew_s += cliff
        anchors = " · ".join(row.anchors_matched) if row.anchors_matched else "-"
        # Defense one-liner.
        com_cell = row.cells.get(".com")
        if pick_tld == ".com":
            defense = "[dim]is the pick[/]"
        elif com_cell and com_cell.available is True and not com_cell.over_max:
            defense = "[green].com avail[/]"
        elif com_cell and com_cell.com_class == "live-site":
            defense = "[red].com is a live site[/]"
        elif com_cell and com_cell.available is False:
            defense = "[yellow].com taken[/]"
        else:
            defense = "[dim]?[/]"
        t.add_row(str(i), row.name, reg_s, renew_s,
                  row.pick_label or pick_tld, anchors, defense)
    console.print(t)


def _decide_step1_brand_collision(finalists, topic: str,
                                  vocab_terms: list[str] | None,
                                  openai_key: str) -> None:
    from .decide import check_brand_collision
    console.print("\n[bold]Step 1/6 — Brand collision check[/]  [dim](gpt-5-mini)[/]")
    for row in finalists:
        result = check_brand_collision(
            row.name, openai_key, topic=topic, vocab_terms=vocab_terms,
        )
        console.print(f"  [bold]{row.name}[/]")
        if result.backend == "ai":
            console.print(f"    {result.ai_verdict}")
        else:
            err = result.error or "skipped"
            console.print(f"    [yellow](skipped: {err})[/]")


def _decide_step2_uspto(finalists) -> None:
    from .decide import uspto_tess_url
    console.print("\n[bold]Step 2/6 — USPTO TESS quick search[/]  [dim](manual click-through)[/]")
    for row in finalists:
        console.print(f"  [bold]{row.name}[/]  [dim]{uspto_tess_url(row.name)}[/]")


def _decide_step3_extensibility(finalists, topic: str,
                                vocab_terms: list[str] | None,
                                openai_key: str) -> None:
    from .decide import assess_extensibility_safe
    console.print("\n[bold]Step 3/6 — Brand-extensibility[/]  [dim](AI assessment)[/]")
    for row in finalists:
        verdict = assess_extensibility_safe(row.name, topic, vocab_terms, openai_key)
        console.print(f"  [bold]{row.name}[/]  {verdict}")


def _decide_step4_cost(finalists) -> None:
    from .decide import compute_five_year_cost
    console.print("\n[bold]Step 4/6 — 5-year cost projection[/]  [dim](reg + 4×renewal)[/]")
    for row in finalists:
        cell = row.cells.get(row.pick_tld) if row.pick_tld else None
        if cell is None:
            console.print(f"  [bold]{row.name}{row.pick_tld or ''}[/]  [dim](no pick)[/]")
            continue
        five_yr = compute_five_year_cost(cell.price, cell.renewal)
        if five_yr is None:
            console.print(f"  [bold]{row.name}{row.pick_tld}[/]  [dim](no pricing)[/]")
            continue
        reg_s = f"${cell.price:.0f}" if cell.price is not None else "—"
        renew_s = f"${cell.renewal:.0f}" if cell.renewal is not None else "—"
        console.print(
            f"  [bold]{row.name}{row.pick_tld}[/]  {reg_s} + 4×{renew_s} = "
            f"[cyan]${five_yr:.0f}[/]"
        )


def _decide_step5_phone_test(finalists) -> list[str]:
    from .decide import parse_test_response
    console.print("\n[bold]Step 5/6 — Phone test[/]  [dim](interactive)[/]")
    console.print("  Say \"the site is <name>\" out loud for each finalist:")
    for row in finalists:
        console.print(f"    · {row.name}")
    sub = typer.prompt(
        "  Names that tripped you (comma-sep), or Enter for none",
        default="", show_default=False,
    )
    matched, unrecognized = parse_test_response(sub, [r.name for r in finalists])
    for u in unrecognized:
        console.print(f"  [yellow]'{u}' not in the finalists — typo?[/]")
    return matched


def _decide_step6_memory_test(finalists) -> list[str]:
    from .decide import parse_test_response
    console.print("\n[bold]Step 6/6 — Memory test[/]  [dim](interactive)[/]")
    console.print("  Look away for 30 seconds, then list the finalists from memory.")
    sub = typer.prompt(
        "  Names you couldn't recall (comma-sep), or Enter for none",
        default="", show_default=False,
    )
    matched, unrecognized = parse_test_response(sub, [r.name for r in finalists])
    for u in unrecognized:
        console.print(f"  [yellow]'{u}' not in the finalists — typo?[/]")
    return matched


def _menu_decide(rows, shortlist: list[str], tld_list: list[str],
                 max_price: float, topic: str, vocab_terms: list[str] | None,
                 openai_key: str):
    """Menu option 7 orchestrator. Returns (row, tld) pick or None."""
    finalists = [r for r in rows if r.name in shortlist]
    if not finalists:
        console.print("[yellow]Shortlist is empty — mark some candidates first (option 6).[/]")
        return None

    _render_decide_table(finalists, max_price=max_price)
    _decide_step1_brand_collision(finalists, topic, vocab_terms, openai_key)
    _decide_step2_uspto(finalists)
    _decide_step3_extensibility(finalists, topic, vocab_terms, openai_key)
    _decide_step4_cost(finalists)
    phone_concerns = _decide_step5_phone_test(finalists)
    memory_concerns = _decide_step6_memory_test(finalists)

    console.print("\n[bold]Test concerns:[/]")
    console.print(f"  · Phone test:  {', '.join(phone_concerns) if phone_concerns else '[dim](none)[/]'}")
    console.print(f"  · Memory test: {', '.join(memory_concerns) if memory_concerns else '[dim](none)[/]'}")

    while True:
        choice = typer.prompt(
            f"\nPick row 1-{len(finalists)} to register, or b to back to menu",
            default="b", show_default=False,
        ).strip().lower()
        if choice == "b" or not choice:
            return None
        if not choice.isdigit():
            console.print(f"[red]Type 1-{len(finalists)} or b.[/]")
            continue
        idx = int(choice) - 1
        if idx < 0 or idx >= len(finalists):
            console.print(f"[red]Row {choice} out of range (1-{len(finalists)}).[/]")
            continue
        row = finalists[idx]
        if row.pick_tld is None:
            console.print(f"[red]{row.name} has no recommended TLD; remove from shortlist or fix.[/]")
            continue
        return row, row.pick_tld


def _menu_show_marked(rows, shortlist: list[str], tld_list: list[str], *,
                     show_renewal: bool, topic: str = "") -> None:
    """Render the shortlist as a full registrar grid (same columns as
    the main grid) so the operator can compare marked names side-by-
    side with per-TLD cells, anchors, picks, and rationale visible.

    Distinct from the brief shortlist printed inside `_menu_shortlist`
    after each mark (that one is just name + pick + price). This is the
    full grid scoped to the marked set. Handy after marking 10+ names
    when the brief form loses the "why" / per-TLD detail.

    No-op cases handled explicitly:
      - empty shortlist → tells the operator to mark first
      - shortlist exists but none of the names appear in the current
        rows (can happen after `widen` filtered them out) → tells the
        operator to re-mark from the current grid
    """
    if not shortlist:
        console.print(
            "[yellow]Shortlist is empty. Mark some rows first (option 6).[/]"
        )
        return
    name_to_row = {r.name: r for r in rows}
    marked_rows = [name_to_row[n] for n in shortlist if n in name_to_row]
    missing = [n for n in shortlist if n not in name_to_row]

    if not marked_rows:
        console.print(
            f"[yellow]None of the {len(shortlist)} marked names are in the "
            f"current grid (e.g., after a widen pass that filtered them "
            f"out). Re-mark from the current grid (option 6).[/]"
        )
        return

    _render_grid(marked_rows, tld_list, show_renewal=show_renewal, topic=topic)
    if missing:
        sample = ", ".join(missing[:5])
        more = f" + {len(missing) - 5} more" if len(missing) > 5 else ""
        console.print(
            f"[dim]Note: {len(missing)} marked name(s) not in current grid: "
            f"{sample}{more}[/]"
        )


def _menu_shortlist(rows, shortlist: list[str]) -> list[str]:
    """Sub-prompt for menu option 6. Multi-target per invocation
    (`m 5 7 12` or `m 5,7,12` marks three at once).

    v4.A polish 2026-05-08: stays in this sub-prompt loop until the user
    types `b` (back). Each iteration auto-prints the current shortlist so
    the user sees their state after every modification. Returns the
    (possibly-modified) shortlist when `b` is pressed.
    """
    current = list(shortlist)
    while True:
        _print_shortlist(current, rows)
        sub = typer.prompt(
            "Action? (just type N or names to mark, e.g. '39 18' or 'alpha beta'; "
            "u to unmark, b to back)",
            default="", show_default=False,
        )
        action, names, errors = parse_shortlist_input(sub, rows)
        for err in errors:
            console.print(f"[red]{err}[/]")
        if action == "back":
            return current
        if action is None:
            continue
        if action == "mark":
            for name in names:
                if name in current:
                    console.print(f"[yellow]{name} is already on the shortlist.[/]")
                    continue
                current.append(name)
                console.print(f"[green]✓[/] Marked [bold]{name}[/]")
        elif action == "unmark":
            for name in names:
                if name not in current:
                    console.print(f"[yellow]{name} is not on the shortlist.[/]")
                    continue
                current.remove(name)
                console.print(f"[green]✓[/] Unmarked [bold]{name}[/]")


def _menu_add_names(rows, *, topic, openai_key, vocab_terms, tld_list,
                    max_price, pricing_dict, avail_fn, show_renewal, log_fn):
    """Sub-prompt for menu option 5. Returns the (possibly-merged) rows list.
    Empty input or all-rejected names returns the rows unchanged.

    v4.A 2026-05-08: after collecting seeds, optionally invokes
    `expand_user_seeds` to ask gpt-5-mini for plurals / near-synonyms /
    prefix-suffix riffs / adjacent anchors. Default Y so the user doesn't
    have to type every variation; pass n to skip.
    """
    from .suggest import (
        Candidate, FULL_LADDER, build_grid, expand_user_seeds,
        filter_pickable_rows, screen_for_content_strict,
    )
    sub = typer.prompt(
        "Names to add (comma-separated, no TLDs)",
        default="", show_default=False,
    ).strip()
    if not sub:
        return rows
    valid_names, rejected = _parse_user_added_names(sub)
    for r in rejected:
        console.print(f"[yellow]skipping {r}[/]")
    if not valid_names:
        console.print("[yellow]No valid names parsed.[/]")
        return rows
    valid_names, screen_dropped = screen_for_content_strict(
        valid_names, openai_key, log_fn=log_fn,
    )
    if screen_dropped:
        console.print(f"[yellow]Filtered {len(screen_dropped)} of your name(s) (content policy)[/]")
    if not valid_names:
        return rows

    # Offer to expand via AI — default Y; n skips.
    if openai_key and typer.confirm(
        "Expand with AI to get plurals, near-synonyms, etc.?",
        default=True,
    ):
        console.print(f"[dim]Asking gpt-5-mini for variants of {len(valid_names)} seed(s)...[/]")
        variants = expand_user_seeds(
            valid_names, topic, vocab_terms, openai_key, log_fn=log_fn,
        )
        if variants:
            console.print(f"[dim]+ {len(variants)} variant(s): {', '.join(variants)}[/]")
            valid_names = valid_names + variants
        else:
            console.print("[dim](no variants returned; using your seeds as-is)[/]")

    console.print(f"[dim]Probing {len(valid_names)} name(s)...[/]")
    user_cands = [Candidate(name=n, strategy="user") for n in valid_names]
    user_rows = build_grid(
        user_cands, topic, tld_list, avail_fn,
        max_price=max_price, pricing_dict=pricing_dict,
        full_ladder=list(FULL_LADDER),
        vocab_terms=vocab_terms,
    )
    user_rows = filter_pickable_rows(user_rows)
    if not user_rows:
        console.print(f"[yellow]None of those names had a pickable cell under --max-price=${max_price:.2f}.[/]")
        return rows
    user_names = {r.name for r in user_rows}
    merged = user_rows + [r for r in rows if r.name not in user_names]
    # v4.A: alphabetical, matching build_grid.
    merged.sort(key=lambda r: r.name.lower())
    _render_grid(merged, tld_list, show_renewal=show_renewal, topic=topic)
    return merged


def _parse_user_added_names(raw: str) -> tuple[list[str], list[str]]:
    """Parse a comma-separated list of user-supplied names. Returns
    (valid_names, rejected_with_reason). Each name must be alphabetic, lowercase,
    and ≤14 chars (matching _extract_names rules)."""
    valid: list[str] = []
    rejected: list[str] = []
    seen: set[str] = set()
    for piece in raw.replace("\n", ",").split(","):
        n = piece.strip().lower()
        if not n:
            continue
        # Strip optional .tld if user pasted full domains
        n = n.split(".", 1)[0]
        if not re.match(r"^[a-z][a-z0-9]*$", n):
            rejected.append(f"{piece.strip()} (invalid chars)")
            continue
        if len(n) > 14:
            rejected.append(f"{piece.strip()} (too long)")
            continue
        if n in seen:
            continue
        seen.add(n)
        valid.append(n)
    return valid, rejected


def _domain_suggest_validation(
    *,
    topic: str,
    tlds: str,
    max_price: float,
    non_interactive: bool,
    no_cache: bool,
    show_renewal: bool,
    with_abstract: bool,
) -> None:
    """v3.D validation-mode flow."""
    from .availability import AvailabilityChecker, load_porkbun_pricing
    from .suggest import (
        Candidate,
        DEFAULT_TLDS,
        FULL_LADDER,
        PORTFOLIO_ENV,
        already_owned_matches,
        build_grid,
        cache_get,
        cache_set,
        filter_default_strategies,
        filter_pickable_rows,
        load_env,
        load_strategies,
        porkbun_cart_url,
        register_domain,
        run_validation_pipeline,
    )

    env = load_env()
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        console.print(f"[red]OPENAI_API_KEY is not set.[/]  Edit [dim]{PORTFOLIO_ENV}[/] and try again.")
        raise typer.Exit(2)

    tld_list = [t.strip() if t.strip().startswith(".") else f".{t.strip()}" for t in tlds.split(",") if t.strip()] if tlds else list(DEFAULT_TLDS)
    all_strategies = filter_default_strategies(load_strategies(), with_abstract=with_abstract)

    owned = already_owned_matches(topic)
    if owned:
        console.print(f"[cyan]Already own ({len(owned)} match{'es' if len(owned) > 1 else ''}):[/]")
        for o in owned:
            console.print(f"  • {o}")
        if not non_interactive:
            cont = typer.confirm("Continue with new candidate brainstorm?", default=True)
            if not cont:
                raise typer.Exit(0)

    cached = None if no_cache else cache_get(topic, all_strategies)

    def _log(msg: str) -> None:
        console.print(f"[dim]{msg}[/]")

    checker = AvailabilityChecker(log_fn=_log)
    avail_fn = checker.make_check_callable()
    pricing_dict = load_porkbun_pricing()

    # Config summary.
    cfg_t = Table(box=None, padding=(0, 1), show_header=False, title="[bold]Search config (v3.D validation mode)[/]", title_justify="left")
    cfg_t.add_column("key", style="dim")
    cfg_t.add_column("value")
    cfg_t.add_row("topic", topic)
    cfg_t.add_row("max price", f"${max_price:.2f}/yr (pass --max-price=N to override; 999 disables)")
    cfg_t.add_row("TLD columns", " ".join(tld_list))
    cfg_t.add_row("availability", "RDAP + DoH fallback (Google then Cloudflare)")
    cfg_t.add_row("pricing", "Porkbun /pricing/get (public, cached 7d)")
    cfg_t.add_row("brainstorm", "OpenAI gpt-5-mini (vocab anchored)")
    cfg_t.add_row("strategies", f"{len(all_strategies)} ({', '.join(s.name for s in all_strategies)})")
    cfg_t.add_row("cache", "BYPASSED (--no-cache)" if no_cache else "7d topic-hash hit/miss")
    cfg_t.add_row("mode", "non-interactive" if non_interactive else "interactive")
    console.print(cfg_t)
    console.print()

    cache_payload = cached if cached else None

    def _save_cache(cands_by_strat, vocab_terms):
        cache_set(topic, all_strategies, cands_by_strat, vocab_terms=vocab_terms)

    rows, vocab_terms = run_validation_pipeline(
        topic=topic,
        api_key=openai_key,
        strategies=all_strategies,
        columns=tld_list,
        avail_check=avail_fn,
        max_price=max_price,
        pricing_dict=pricing_dict,
        cache_payload=cache_payload,
        cache_save_fn=None if no_cache else _save_cache,
        log_fn=_log,
        merge_topical=not tlds,  # v28.C: topic-aware TLDs only on the default ladder
    )

    # v3.D 2026-05-08: filter rows to those with at least one pickable cell
    # (available + under price cap). Drop the rest — nothing to do with them.
    rows = filter_pickable_rows(rows)

    if not rows:
        console.print("[yellow]No pickable candidates — every name was either taken or priced over --max-price. Try refining the topic, raising --max-price, or --no-cache.[/]")
        raise typer.Exit(0)

    _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)

    if non_interactive:
        return

    # v3.E 2026-05-08: post-grid menu. Replaces the inline pick + add-names
    # loops. Re-shown after every non-terminating action; terminates only on
    # successful pick (→ post_pick_flow) or `q`.
    # v4.A 2026-05-08: shortlist persists across menu iterations (list of
    # names, so it survives grid mutations from add-names / future widen).
    selected_row = None
    selected_tld = None
    shortlist: list[str] = []
    while selected_row is None:
        _render_menu(shortlist_count=len(shortlist))
        choice = typer.prompt(">", default="", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]No domain selected.[/]")
            return
        if choice == "1":
            result = _menu_pick(rows, tld_list)
            if result is not None:
                selected_row, selected_tld = result
                break
            # else: error printed by _menu_pick; re-show menu
            continue
        if choice == "2":
            result = _menu_expand(rows, tld_list, max_price, show_renewal)
            if result is not None:
                selected_row, selected_tld = result
                break
            # back from expand → re-render grid then re-show menu
            _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)
            continue
        if choice == "3":
            _menu_ask_ai(rows, topic=topic, vocab_terms=vocab_terms,
                         openai_key=openai_key)
            continue
        if choice == "4":
            rows = _menu_widen(
                rows, topic=topic, vocab_terms=vocab_terms,
                tld_list=tld_list, max_price=max_price,
                pricing_dict=pricing_dict, avail_fn=avail_fn,
                show_renewal=show_renewal, openai_key=openai_key, log_fn=_log,
            )
            continue
        if choice == "5":
            rows = _menu_add_names(
                rows, topic=topic, openai_key=openai_key,
                vocab_terms=vocab_terms, tld_list=tld_list,
                max_price=max_price, pricing_dict=pricing_dict,
                avail_fn=avail_fn, show_renewal=show_renewal, log_fn=_log,
            )
            continue
        if choice == "6":
            shortlist = _menu_shortlist(rows, shortlist)
            continue
        if choice == "7":
            result = _menu_decide(
                rows, shortlist, tld_list, max_price,
                topic=topic, vocab_terms=vocab_terms,
                openai_key=openai_key,
            )
            if result is not None:
                selected_row, selected_tld = result
                break
            # b from decide → main menu (shortlist preserved)
            continue
        if choice == "8":
            _menu_show_marked(
                rows, shortlist, tld_list,
                show_renewal=show_renewal, topic=topic,
            )
            continue
        if choice == "9":
            _render_tld_reference()
            continue
        if choice == "10":
            from .suggest import clear_brainstorm_cache
            cleared = clear_brainstorm_cache(topic, all_strategies)
            if cleared:
                console.print("[dim]Brainstorm cache cleared.[/]")
            console.print("[dim]Re-running pipeline (fresh)...[/]")
            rows, vocab_terms = run_validation_pipeline(
                topic=topic, api_key=openai_key,
                strategies=all_strategies,
                columns=tld_list, avail_check=avail_fn,
                max_price=max_price, pricing_dict=pricing_dict,
                cache_payload=None,
                cache_save_fn=_save_cache,
                log_fn=_log,
                merge_topical=not tlds,  # v28.C
            )
            rows = filter_pickable_rows(rows)
            if not rows:
                console.print("[yellow]No pickable candidates after rerun. Try refining the topic.[/]")
                continue
            _render_grid(rows, tld_list, show_renewal=show_renewal, topic=topic)
            if shortlist:
                missing = [n for n in shortlist if not any(r.name == n for r in rows)]
                if missing:
                    console.print(
                        f"[yellow]Note: shortlist has {len(missing)} name(s) not in the new grid: "
                        f"{', '.join(missing)}[/]"
                    )
            continue
        if choice in COMING_SOON_HINTS:
            console.print(f"[dim]{COMING_SOON_HINTS[choice]}[/]")
            continue
        console.print(f"[red]Type {_menu_keys_hint()} or q.[/]")

    _post_pick_flow(
        row=selected_row,
        pick_tld=selected_tld,
        topic=topic,
        env=env,
        vocab_terms=vocab_terms,
        register_domain=register_domain,
        porkbun_cart_url=porkbun_cart_url,
    )


def _post_pick_flow(*, row, pick_tld, topic, env, vocab_terms,
                    register_domain, porkbun_cart_url) -> None:
    """Defense bundle, auto-register, next-step output. Shared between the
    main picker and the expand-view picker."""
    selected = f"{row.name}{pick_tld}"
    selected_cell = row.cells.get(pick_tld)
    is_unverified = selected_cell is not None and selected_cell.available is None
    console.print(f"\n[green]✅ Selected:[/] [bold]{selected}[/]")
    if is_unverified:
        console.print("[dim](RDAP/DoH gap on this TLD — final availability check happens at registrar checkout.)[/]")

    bundle: list[str] = []
    com_cell = row.cells.get(".com")
    app_cell = row.cells.get(".app")
    if pick_tld != ".com" and com_cell is not None and com_cell.available is True and not com_cell.over_max:
        bundle.append(".com")
    if pick_tld != ".app" and app_cell is not None and app_cell.available is True and not app_cell.over_max:
        bundle.append(".app")

    if bundle:
        bundle_doms = [f"{row.name}{t}" for t in bundle]
        bundle_str = " + ".join(bundle_doms)
        bundle_prompt = f"Defense bundle available: {bundle_str}. Open Porkbun cart with bundle? [y/N]"
        if typer.confirm(bundle_prompt, default=False):
            url = porkbun_cart_url([selected] + bundle_doms)
            console.print(f"[cyan]Bundle cart URL:[/] {url}")
            console.print("[dim](Bundle items are manual click-through; never auto-charged.)[/]")

    if is_unverified:
        console.print(f"[cyan]Register manually (verify availability first):[/] {porkbun_cart_url([selected])}")
    elif typer.confirm(f"Register {selected} now via Porkbun API?", default=False):
        pk_key = env.get("PORKBUN_API_KEY", "").strip()
        pk_secret = env.get("PORKBUN_SECRET_API_KEY", "").strip()
        result = register_domain(selected, pk_key, pk_secret)
        if result.ok:
            console.print(f"[green]✓ Registered {selected}[/]" + (f" (order {result.order_id})" if result.order_id else ""))
        else:
            console.print(f"[red]Auto-register failed:[/] {result.detail}")
            console.print(f"[cyan]Manual checkout:[/] {porkbun_cart_url([selected])}")
    else:
        console.print(f"[cyan]Register manually:[/] {porkbun_cart_url([selected])}")

    console.print("\n[bold]Next step:[/]")
    console.print(f'  portfolio new bootstrap {selected} --topic="{topic}"')
    if vocab_terms:
        console.print("\n[bold]Vocab terms[/] (paste into docs/prd.md after bootstrap):")
        console.print("  " + ", ".join(vocab_terms))


def _expand_and_pick(row, visible_columns: list[str], max_price: float,
                     show_renewal: bool = False):
    """Render an expanded full-ladder view for one row, then prompt for a
    scoped pick. Returns `(row, tld)` if user picks, `None` if user typed `b`
    (back to grid) or `q` (quit propagates as None too)."""
    _render_expanded_row(row, max_price=max_price, show_renewal=show_renewal)
    while True:
        prompt = "[N | N.tld] pick · [b] back to grid · [q] quit"
        choice = typer.prompt(f"\n{prompt}", default="b", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]No domain selected.[/]")
            raise typer.Exit(0)
        if choice == "b" or not choice:
            return None
        # Pick is "N" or "N.tld" but here N is irrelevant — single-row context.
        # Accept ".tld" or "tld" or full "N.tld" (any digit).
        if choice.startswith("."):
            tld = choice
        elif "." in choice:
            tld = "." + choice.split(".", 1)[1]
        else:
            # Treat as bare TLD without dot, e.g. "app" → ".app"
            tld = "." + choice
        cell = row.cells.get(tld)
        if cell is None:
            console.print(f"[red]{tld} wasn't probed for this row.[/]")
            continue
        if cell.available is False:
            console.print(f"[red]{row.name}{tld} is taken.[/]")
            continue
        if cell.over_max:
            console.print(f"[red]{row.name}{tld} is priced over --max-price (${cell.price:.2f}).[/]")
            continue
        return row, tld


def _render_expanded_row(row, max_price: float, show_renewal: bool = False) -> None:
    """Render the expanded full-ladder view for one row."""
    console.print(f"\n─── [bold]{row.name}[/] ───────────────────")
    if row.anchors_matched:
        console.print(f"  [magenta]Anchors:[/] {' · '.join(row.anchors_matched)}")
    else:
        console.print("  [magenta]Anchors:[/] [dim](none)[/]")
    console.print(f"  [cyan]Strategy:[/] {row.strategy}")
    pick_label = row.pick_label or "-"
    console.print(f"  [cyan]Pick:[/] {pick_label}  [dim]{row.why}[/]")
    console.print()

    t = Table(box=None, padding=(0, 2))
    t.add_column("TLD")
    t.add_column("Avail")
    t.add_column("Reg", justify="right")
    t.add_column("Renew", justify="right")
    t.add_column("Notes")
    # Sort cells by TLD tier desc so good options appear first.
    from .suggest import TLD_TIER
    sorted_tlds = sorted(row.cells.keys(), key=lambda t: -TLD_TIER.get(t.lower(), 0))
    for tld in sorted_tlds:
        c = row.cells[tld]
        if c.available is True:
            avail = "[green]✓[/]"
        elif c.available is False:
            if c.com_class == "live-site":
                avail = "[red]✗ live[/]"
            elif c.com_class == "parked":
                avail = "[yellow]✗ park[/]"
            elif c.com_class == "for-sale":
                avail = "[yellow]✗ sale[/]"
            else:
                avail = "[red]✗[/]"
        elif c.error:
            avail = "[red bold]✕[/]"
        else:
            avail = "[yellow]?[/]"
        reg = f"${c.price:.2f}" if c.price is not None else "-"
        renew = f"${c.renewal:.2f}" if c.renewal is not None else "-"
        notes = []
        if c.over_max:
            notes.append("over --max-price")
        cliff = _renewal_cliff_marker(c.price, c.renewal)
        if cliff:
            # cliff includes leading space + rich tag; strip the space for column form
            notes.append(cliff.strip())
        notes_s = " · ".join(notes) if notes else ""
        t.add_row(tld, avail, reg, renew, notes_s)
    console.print(t)


def _renewal_cliff_marker(price: float | None, renewal: float | None) -> str:
    """Inline cell marker showing the renewal-cliff multiplier when significant.

    Returns ` ↑Nx` when renewal/registration > 2.0 (so the bait-and-switch
    TLDs get visual flagging without a separate column). Returns "" when
    either price is missing or the cliff is mild (≤ 2x).
    """
    if price is None or renewal is None or price <= 0:
        return ""
    ratio = renewal / price
    if ratio <= 2.0:
        return ""
    return f" [yellow]↑{ratio:.0f}x[/]"


def _cell_str(state, show_renewal: bool = False) -> str:
    """Format one grid cell: ✓ $N [↑Nx] / ✗ live|park / ? / $N!"""
    if state.over_max:
        # Available but priced out; surface so the user sees the option exists
        # (v28.D: premium topical TLDs are shown + manually pickable, never the
        # highlighted recommendation). Append renewal when it differs from reg
        # so the keep-forever cost of a premium pick is visible at a glance.
        if state.available is True and state.price is not None:
            extra = ""
            if state.renewal is not None and abs(state.renewal - state.price) >= 1:
                extra = f" r${state.renewal:.0f}"
            return f"[dim]${state.price:.0f}!{extra}[/]"
        if state.available is False:
            return "[red]✗[/]"
        return "[yellow]?[/]"
    if state.available is True:
        price_s = f"${state.price:.0f}" if state.price is not None else "-"
        cliff = _renewal_cliff_marker(state.price, state.renewal)
        if show_renewal and state.renewal is not None:
            return f"[green]✓[/] {price_s}{cliff}\n[dim]r ${state.renewal:.0f}[/]"
        return f"[green]✓[/] {price_s}{cliff}"
    if state.available is False:
        if state.com_class == "live-site":
            return "[red]✗ live[/]"
        if state.com_class == "parked":
            return "[yellow]✗ park[/]"
        if state.com_class == "for-sale":
            return "[yellow]✗ sale[/]"
        return "[red]✗[/]"
    if state.error:
        return "[red bold]✕[/]"
    return "[yellow]?[/]"


def _render_grid(rows, columns: list[str], show_renewal: bool = False,
                 *, topic: str | None = None) -> None:
    """Render the v3.D registrar grid: rows = names, cols = TLD cells + Anchors
    + Pick + Why. Anchors column shows vocab terms found in the name (the row
    differentiator); cliff markers (↑Nx) on cells flag renewal bait-and-switch
    (the column differentiator).

    When `topic` is provided, renders a one-line title above the table
    so the operator can scan the grid with the original topic in
    eyeshot — same affordance as `new validate`'s Topic line. Optional
    for backward compatibility with any caller that doesn't have the
    topic in scope.
    """
    if topic:
        console.print(f"\n[bold]Topic:[/] [cyan]{topic}[/]\n")
    t = Table(box=None, padding=(0, 1))
    t.add_column("#", justify="right")
    t.add_column("Name", style="bold")
    for c in columns:
        t.add_column(c, justify="left")
    t.add_column("Anchors", style="magenta")
    t.add_column("Pick", style="cyan")
    t.add_column("Why")
    for i, row in enumerate(rows, 1):
        cells_rendered = [_cell_str(row.cells.get(c), show_renewal=show_renewal) if row.cells.get(c) else "-" for c in columns]
        anchors = " · ".join(row.anchors_matched) if row.anchors_matched else "-"
        pick = row.pick_label or "-"
        t.add_row(str(i), row.name, *cells_rendered, anchors, pick, row.why)
    console.print(t)


def _domain_suggest_browse(
    topic: str,
    tlds: str,
    max_price: float,
    strategies: int,
    non_interactive: bool,
    no_cache: bool,
) -> None:
    """v2.A legacy per-strategy round-by-round flow (preserved behind --browse)."""
    from .availability import AvailabilityChecker
    from .suggest import (
        DEFAULT_TLDS,
        Candidate,
        already_owned_matches,
        brainstorm,
        cache_get,
        cache_set,
        filter_by_max_price,
        load_env,
        load_strategies,
        render_options,
        PORTFOLIO_ENV,
    )

    env = load_env()
    openai_key = env.get("OPENAI_API_KEY", "").strip()
    if not openai_key:
        console.print(f"[red]OPENAI_API_KEY is not set.[/]  Edit [dim]{PORTFOLIO_ENV}[/] and try again.")
        raise typer.Exit(2)

    tld_list = [t.strip() if t.strip().startswith(".") else f".{t.strip()}" for t in tlds.split(",") if t.strip()] if tlds else list(DEFAULT_TLDS)
    all_strategies = load_strategies()
    if strategies > 0:
        all_strategies = all_strategies[:strategies]

    owned = already_owned_matches(topic)
    if owned:
        console.print(f"[cyan]Already own ({len(owned)} match{'es' if len(owned) > 1 else ''}):[/]")
        for o in owned:
            console.print(f"  • {o}")
        if not non_interactive:
            cont = typer.confirm("Continue with new candidate brainstorm?", default=True)
            if not cont:
                raise typer.Exit(0)

    cached = None if no_cache else cache_get(topic, all_strategies)
    if cached:
        console.print(f"[dim](using cached brainstorm; {len(cached.get('candidates_by_strategy', {}))} strategies)[/]")
        candidates_by_strategy = {k: [Candidate(**c) for c in v] for k, v in cached["candidates_by_strategy"].items()}
    else:
        candidates_by_strategy = {}

    def _log_check(msg: str) -> None:
        console.print(f"[dim]{msg}[/]")

    checker = AvailabilityChecker(log_fn=_log_check)
    avail_fn = checker.make_check_callable()

    cfg_t = Table(box=None, padding=(0, 1), show_header=False, title="[bold]Search config (browse mode / v2.A)[/]", title_justify="left")
    cfg_t.add_column("key", style="dim"); cfg_t.add_column("value")
    cfg_t.add_row("topic", topic)
    cfg_t.add_row("max price", f"${max_price:.2f}/yr")
    cfg_t.add_row("TLD ladder", " ".join(tld_list))
    cfg_t.add_row("strategies", f"{len(all_strategies)} ({', '.join(s.name for s in all_strategies)})")
    console.print(cfg_t); console.print()

    history: list[str] = []
    selected: str | None = None
    for idx, strategy in enumerate(all_strategies, 1):
        if selected:
            break
        console.print(f"\n[bold cyan]--- Strategy {idx}/{len(all_strategies)}: {strategy.label} ---[/]")
        console.print(f"[dim]{strategy.description}[/]")

        cached_cands = candidates_by_strategy.get(strategy.name)
        if cached_cands:
            cands = cached_cands
            console.print(f"[dim](cached: {len(cands)} candidates)[/]")
        else:
            console.print("[dim]Brainstorming via OpenAI gpt-5-mini...[/]")
            try:
                cands = brainstorm(topic, strategy, history, openai_key)
            except Exception as e:
                console.print(f"[red]brainstorm failed:[/] {e}")
                continue
            if not cands:
                continue
            candidates_by_strategy[strategy.name] = cands
            cache_set(topic, all_strategies, candidates_by_strategy)

        history.extend(c.name for c in cands)

        options = render_options(cands, topic, tld_list, avail_fn)
        options = filter_by_max_price(options, max_price)
        showable = [o for o in options if o.available is not False]
        if not showable:
            console.print("[yellow]No available or candidate domains in this round.[/]")
            continue

        top = showable[:5]
        t = Table(box=None, padding=(0, 1))
        t.add_column("#", justify="right"); t.add_column("Name"); t.add_column("TLD")
        t.add_column("Avail", justify="center"); t.add_column("Price", justify="right"); t.add_column("Score", justify="right")
        for i, o in enumerate(top, 1):
            price_s = f"${o.price:,.2f}" if o.price is not None else "-"
            avail_s = "[green]✓[/]" if o.available is True else ("[red]✗[/]" if o.available is False else ("[red bold]✕[/]" if o.error else "[yellow]?[/]"))
            t.add_row(str(i), o.name, o.tld, avail_s, price_s, str(o.score))
        console.print(t)

        if non_interactive:
            continue

        choice = typer.prompt(f"\nPick (1-{len(top)}), 'n' next, 'q' quit", default="n", show_default=False).strip().lower()
        if choice == "q":
            console.print("[yellow]Aborted.[/]"); raise typer.Exit(0)
        if choice in ("n", ""):
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(top):
            selected = top[int(choice) - 1].domain

    if selected:
        console.print(f"\n[green]✅ Selected:[/] [bold]{selected}[/]")
        console.print(f"[cyan]Register at:[/] https://porkbun.com/checkout/search?q={selected}")
    elif not non_interactive:
        console.print("\n[yellow]No domain selected.[/]")


