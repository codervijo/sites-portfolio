"""v27.G — surgical `lamill.toml` upsert editor.

Mutates an existing `lamill.toml` *in place*, touching only the region
being changed and leaving everything else — comments, `[content]`, table
ordering, blank lines — byte-for-byte identical.

This is the **upsert** counterpart to `lamill_toml.write()` (a full-file
*rewrite* that drops unknown tables + comments). Per ADR-0018, every CLI
mutation of `lamill.toml` must go through an upsert like this, never a
rewrite — so an operator's hand-authored content is never silently lost.

Scope today: the `[[todo]]` array-of-tables (v27.H write verbs). The
strategy generalizes — locate a region's char span in the raw text,
regenerate just that region, splice it back — so future upserts
(`[stack]`, `[deploy]` keys, …) follow the same shape when the legacy
rewrite paths migrate (v27.J).

Mechanism for `[[todo]]`:
  1. `lamill_toml.load()` parses + validates the whole file (so we never
     write on top of a malformed file) and gives the todos in file order.
  2. Mutate that ordered list in memory (append / toggle status).
  3. Re-emit ONLY the `[[todo]]` region via the shared canonical emitter
     (`lamill_toml.todo_region_text`) and splice it over the old region's
     char span. Everything outside the span is untouched.

Freeform comments *inside* the `[[todo]]` region are not preserved (the
canonical header is regenerated) — that matches `write()`'s documented
v27.B behavior. Comments and tables *outside* the region are preserved.
"""
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

import tomli_w

from . import lamill_toml
from .lamill_toml import LAMILL_TOML_FILENAME, ParseError, TodoItem

_VALID_PRIORITIES = {"high", "medium", "low"}
_REL_DUE = re.compile(r"^\+(\d+)([dw])$")


class TodoEditError(RuntimeError):
    """A todo upsert couldn't be applied (no file, bad index, bad input)."""


def resolve_due_date(spec: str, *, today: date | None = None) -> date:
    """Parse a due spec — relative (`+14d`, `+2w`) or ISO (`2026-06-13`)
    — into a concrete date. Raises `TodoEditError` on a bad spec."""
    today = today or date.today()
    s = spec.strip()
    m = _REL_DUE.match(s)
    if m:
        n = int(m.group(1))
        return today + timedelta(days=n * (7 if m.group(2) == "w" else 1))
    try:
        return date.fromisoformat(s)
    except ValueError as e:
        raise TodoEditError(
            f"--due must be +Nd / +Nw or an ISO date (YYYY-MM-DD); got {spec!r}"
        ) from e


def due_hint(spec: str, *, today: date | None = None) -> str:
    """The text-only due suffix appended to a task, e.g.
    `" (revisit ~2026-06-13)"`. Dates are text per the v27 decision — no
    schema field — so this is just human-readable task content."""
    return f" (revisit ~{resolve_due_date(spec, today=today).isoformat()})"


def _load_todos(repo_path: Path) -> list[TodoItem]:
    """Parse the file (validating the whole thing) and return its todos
    in file order. Raises `TodoEditError` when there's no declaration."""
    doc = lamill_toml.load(repo_path)
    if doc is None:
        raise TodoEditError(
            f"{repo_path / LAMILL_TOML_FILENAME} does not exist — "
            f"run `lamill new bootstrap` first."
        )
    return list(doc.todos)


def _todo_region_span(text: str) -> tuple[int, int] | None:
    """Char span `[start, end)` of the `[[todo]]` region in `text`,
    including any contiguous leading `#` header-comment lines, or `None`
    when the file has no `[[todo]]` table.

    `end` is the start of the next top-level table line (`[`/`[[` at
    column 0 that isn't `[[todo]]`) or EOF — so the span swallows the
    blank line(s) between the last todo block and the following table;
    the caller re-inserts the canonical single blank-line separator.
    """
    lines = text.splitlines(keepends=True)
    first = next(
        (i for i, ln in enumerate(lines) if ln.strip() == "[[todo]]"), None
    )
    if first is None:
        return None

    # Extend the start upward over contiguous comment lines directly
    # above the first `[[todo]]` (the canonical header) — stop at a blank
    # line or non-comment line.
    start_line = first
    j = first - 1
    while j >= 0 and lines[j].lstrip().startswith("#"):
        start_line = j
        j -= 1

    # End at the next top-level table header after the todo blocks.
    end_line = len(lines)
    for k in range(first + 1, len(lines)):
        if lines[k].startswith("[") and lines[k].strip() != "[[todo]]":
            end_line = k
            break

    start = sum(len(ln) for ln in lines[:start_line])
    end = sum(len(ln) for ln in lines[:end_line])
    return start, end


def _write_todos(repo_path: Path, items: list[TodoItem]) -> None:
    """Splice the regenerated `[[todo]]` region into the raw file text,
    preserving everything outside it. Atomic (tmpfile + rename)."""
    target = repo_path / LAMILL_TOML_FILENAME
    text = target.read_text()
    region = lamill_toml.todo_region_text(repo_path.name, items)
    span = _todo_region_span(text)

    if span is not None:
        start, end = span
        # Keep one blank line before the following table; or a single
        # trailing newline when the region runs to EOF.
        sep = "\n\n" if end < len(text) else "\n"
        new_text = text[:start] + region + sep + text[end:]
    else:
        # No existing `[[todo]]` region. Insert before `[content]` if
        # present (todos sit above the content block in fleet files),
        # else append at EOF.
        lines = text.splitlines(keepends=True)
        content_line = next(
            (i for i, ln in enumerate(lines) if ln.startswith("[content]")),
            None,
        )
        if content_line is not None:
            pos = sum(len(ln) for ln in lines[:content_line])
            new_text = text[:pos] + region + "\n\n" + text[pos:]
        else:
            new_text = text.rstrip("\n") + "\n\n" + region + "\n"

    lamill_toml._atomic_write(target, new_text)


# ---- public verbs ---------------------------------------------------


def add_todo(
    repo_path: Path,
    *,
    task: str,
    priority: str | None = None,
) -> TodoItem:
    """Append a new open todo. Returns the created item.

    `priority` (if given) must be one of high/medium/low — it's only
    valid on open items, which a freshly-added todo always is.
    """
    task = task.strip()
    if not task:
        raise TodoEditError("todo task text cannot be empty.")
    if priority is not None and priority not in _VALID_PRIORITIES:
        raise TodoEditError(
            f"--priority must be one of: high, medium, low (got {priority!r})."
        )
    items = _load_todos(repo_path)
    new_item = TodoItem(status="open", task=task, priority=priority)
    items.append(new_item)
    _write_todos(repo_path, items)
    return new_item


def _set_status(repo_path: Path, index: int, new_status: str) -> TodoItem:
    items = _load_todos(repo_path)
    if not items:
        raise TodoEditError("no todos to modify.")
    if not (1 <= index <= len(items)):
        raise TodoEditError(
            f"index {index} out of range — there are {len(items)} todo(s) "
            f"(1-{len(items)})."
        )
    cur = items[index - 1]
    if new_status == "done":
        # `priority` is invalid on done items (locked shape) — strip it.
        updated = TodoItem(status="done", task=cur.task, priority=None)
    else:
        # Reopen: keep whatever priority the item carried (None if it was
        # completed earlier — reopened items start unprioritized).
        updated = TodoItem(status="open", task=cur.task, priority=cur.priority)
    items[index - 1] = updated
    _write_todos(repo_path, items)
    return updated


def _single_table_span(text: str, name: str) -> tuple[int, int] | None:
    """Char span `[start, end)` of a single top-level table `[name]` in
    `text` (header line through the line before the next top-level
    table/array-of-tables header, or EOF), or `None` if absent.

    Only valid for *flat* tables (no nested `[name.sub]` sub-tables) —
    `[deploy]` and `[hosting]` qualify. Leading comments above the table
    are NOT included in the span, so they're preserved across a replace.
    """
    lines = text.splitlines(keepends=True)
    header = next(
        (i for i, ln in enumerate(lines) if ln.strip() == f"[{name}]"), None
    )
    if header is None:
        return None
    end_line = len(lines)
    for k in range(header + 1, len(lines)):
        s = lines[k].lstrip()
        if s.startswith("[") and not s.startswith("[["):
            end_line = k
            break
        if lines[k].startswith("[["):
            end_line = k
            break
    start = sum(len(ln) for ln in lines[:header])
    end = sum(len(ln) for ln in lines[:end_line])
    return start, end


def set_table(repo_path: Path, name: str, body: dict | None) -> None:
    """Surgically upsert (or remove) a single top-level table `[name]`,
    leaving the rest of the file — comments, `[content]`, `[[todo]]`,
    `[stack]`, table ordering — byte-identical (ADR-0018).

    `body=None` removes the table. A new table is inserted just above the
    first of `[stack]` / `[[todo]]` / `[content]` (so tool-managed config
    stays above operator content), else appended at EOF. Requires the
    file to exist; flat tables only.
    """
    target = repo_path / LAMILL_TOML_FILENAME
    text = target.read_text()
    span = _single_table_span(text, name)

    if body is None:
        if span is None:
            return
        start, end = span
        new_text = (text[:start].rstrip("\n") + "\n\n" + text[end:].lstrip("\n")
                    if text[:start].strip() and text[end:].strip()
                    else text[:start] + text[end:])
    else:
        import tomli_w
        region = tomli_w.dumps({name: body}).rstrip("\n")
        if span is not None:
            start, end = span
            sep = "\n\n" if end < len(text) else "\n"
            new_text = text[:start] + region + sep + text[end:]
        else:
            lines = text.splitlines(keepends=True)
            anchor = next(
                (i for i, ln in enumerate(lines)
                 if ln.strip() in ("[stack]", "[[todo]]", "[content]")),
                None,
            )
            if anchor is not None:
                pos = sum(len(ln) for ln in lines[:anchor])
                new_text = text[:pos] + region + "\n\n" + text[pos:]
            else:
                new_text = text.rstrip("\n") + "\n\n" + region + "\n"

    lamill_toml._atomic_write(target, new_text)


def complete_todo(repo_path: Path, index: int) -> TodoItem:
    """Mark the 1-based file-order todo `index` done (strips priority)."""
    return _set_status(repo_path, index, "done")


def reopen_todo(repo_path: Path, index: int) -> TodoItem:
    """Reopen the 1-based file-order todo `index` (status → open)."""
    return _set_status(repo_path, index, "open")


# ---- file-shape skeletons (v27.I bootstrap closure) -----------------

# Canonical 3-line header pointer + [content] skeleton — the same shape
# the 2026-05-30 fleet migration applied. Kept here as the single source
# of truth so `new bootstrap` produces files consistent with the fleet.
HEADER_COMMENT = (
    "# lamill.toml — per-site config consumed by lamill (portfolio/ops) and rankmill (content/audits).\n"
    "# [content] = stable identity, authored by hand. [todo] = volatile work state.\n"
    "# rankmill output lives in sites/<domain>/rankmill-output/, not here.\n"
)

CONTENT_SKELETON = '''[content]
# Declarative content identity for this site.
# Authored by the human; consumed by rankmill to generate drafts and run audits.
# Leave fields empty until you have a deliberate answer. Empty is better than wrong.
site_type = ""            # e.g. "legal-compliance", "tool", "directory", "blog", "b2c"
primary_keyword = ""      # the one phrase this site should rank for
secondary_keywords = []   # 3-8 supporting phrases
icp = ""                  # ideal customer profile — one sentence, specific role + context
urgency_trigger = ""      # what makes the reader act now (deadline, penalty, pain)
penalty = ""              # cost of inaction, in their terms (dollars, risk, time)
tone = ""                 # e.g. "direct, technical, no fluff" or "warm, plainspoken"
law = ""                  # statute or regulation if applicable, else empty
'''

# v29.B — the `[content]` field spec, single source of truth for both the
# empty skeleton and value-seeded renders. Each row: (field name, empty-
# default literal, guidance comment). The comments + column alignment
# below reproduce CONTENT_SKELETON byte-for-byte when no values are given
# (asserted in tests); a seeded field drops its guidance comment because
# the value itself documents the field.
_CONTENT_INTRO = (
    "[content]\n"
    "# Declarative content identity for this site.\n"
    "# Authored by the human; consumed by rankmill to generate drafts and run audits.\n"
    "# Leave fields empty until you have a deliberate answer. Empty is better than wrong.\n"
)

_CONTENT_FIELDS: list[tuple[str, str, str]] = [
    ("site_type", '""', 'e.g. "legal-compliance", "tool", "directory", "blog", "b2c"'),
    ("primary_keyword", '""', "the one phrase this site should rank for"),
    ("secondary_keywords", "[]", "3-8 supporting phrases"),
    ("icp", '""', "ideal customer profile — one sentence, specific role + context"),
    ("urgency_trigger", '""', "what makes the reader act now (deadline, penalty, pain)"),
    ("penalty", '""', "cost of inaction, in their terms (dollars, risk, time)"),
    ("tone", '""', 'e.g. "direct, technical, no fluff" or "warm, plainspoken"'),
    ("law", '""', "statute or regulation if applicable, else empty"),
]

# `name = default` is left-padded to this width, then `   # comment`.
# 23 = len("secondary_keywords = []"), the widest empty field line.
_CONTENT_COMMENT_COL = 23


def _emit_toml_value(value: object) -> str:
    """Render a Python scalar/list as its TOML right-hand side via
    `tomli_w`, so quoting, escaping (quotes / apostrophes / newlines in a
    pasted ICP paragraph), and list formatting are all correct and
    round-trip. `tomli_w.dumps({"_": v})` yields `_ = <repr>\\n`; strip
    the `_ = ` prefix and trailing newline to get just the value."""
    return tomli_w.dumps({"_": value}).strip()[len("_ = "):]


def content_block(values: dict | None = None) -> str:
    """Render the `[content]` block, seeding any provided field values.

    `values` maps a `[content]` field name → value (a string, or a
    list[str] for `secondary_keywords`). A field that is absent, None,
    or empty (`""` / `[]`) renders as its empty default *with* the
    guidance comment and column alignment — so `content_block()` with no
    values is byte-for-byte `CONTENT_SKELETON`. A seeded field renders
    `name = <toml value>` with no inline comment.

    Unknown keys in `values` are ignored — only the canonical fields are
    emitted, in their canonical order.
    """
    values = values or {}
    lines: list[str] = []
    for name, empty_default, comment in _CONTENT_FIELDS:
        v = values.get(name)
        if v in (None, "", []):
            lhs = f"{name} = {empty_default}"
            lines.append(f"{lhs:<{_CONTENT_COMMENT_COL}}   # {comment}")
        else:
            lines.append(f"{name} = {_emit_toml_value(v)}")
    return _CONTENT_INTRO + "\n".join(lines) + "\n"


def ensure_header_comment(repo_path: Path) -> bool:
    """Prepend the canonical header pointer if the file has no top
    comment. Idempotent — returns True only when it added the header."""
    p = repo_path / LAMILL_TOML_FILENAME
    text = p.read_text()
    first_nonblank = next((ln for ln in text.splitlines() if ln.strip()), "")
    if first_nonblank.lstrip().startswith("#"):
        return False
    lamill_toml._atomic_write(p, HEADER_COMMENT + "\n" + text)
    return True


def ensure_content_block(repo_path: Path, values: dict | None = None) -> bool:
    """Append the `[content]` block if absent, seeding any provided field
    `values` (v29.B). Idempotent — returns True only when it added the
    block; a file that already has `[content]` is left untouched (values
    are NOT merged into an existing block). Surgical append, so any
    existing `[[todo]]` / other tables are byte-preserved.

    With no `values`, the appended block is the empty `CONTENT_SKELETON`,
    matching pre-v29.B behavior."""
    p = repo_path / LAMILL_TOML_FILENAME
    text = p.read_text()
    if any(ln.strip() == "[content]" for ln in text.splitlines()):
        return False
    lamill_toml._atomic_write(p, text.rstrip("\n") + "\n\n" + content_block(values))
    return True
