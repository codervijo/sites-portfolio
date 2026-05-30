"""v27.D — `lamill project todos` + `lamill fleet todos` read views.

Pure reads of each site's `lamill.toml` `[[todo]]` table (v27.B). No
live fetch, no network — just load the declaration and render.

  `project todos <domain>` — one site's tracker: open items grouped by
  priority (high → medium → low → unset), done items dimmed at the
  bottom, with counts.

  `fleet todos [--priority --status]` — fleetwide worklist: every site's
  todos in one ranked list, filterable by priority and status.

Honors the additive-optional invariant (docs/CLAUDE.md): a site with no
`lamill.toml` — or one without a `[[todo]]` table — simply has nothing
to render. Never warns or fails just because the table is absent.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import lamill_toml
from .lamill_toml import TodoItem

# Priority sort order — lower sorts first. `None` (open item with no
# declared priority) sorts last among open items. Mirrors the locked
# `[[todo]]` shape: priority is optional even on open items.
_PRIORITY_RANK: dict[str | None, int] = {"high": 0, "medium": 1, "low": 2, None: 3}

# Per-priority display style (rich markup tag) + glyph.
_PRIORITY_STYLE: dict[str | None, str] = {
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    None: "dim",
}


def _priority_label(priority: str | None) -> str:
    return priority if priority else "unprioritized"


def _rank(item: TodoItem) -> int:
    return _PRIORITY_RANK.get(item.priority, 3)


def _sort_key(item: TodoItem) -> tuple[int, str]:
    return (_rank(item), item.task.lower())


# ---- project view ---------------------------------------------------


@dataclass
class ProjectTodos:
    """One site's todo tracker, split for rendering."""
    domain: str
    has_toml: bool
    open_items: list[TodoItem] = field(default_factory=list)
    done_items: list[TodoItem] = field(default_factory=list)
    # v27.H — todos in raw file order, 1-based. The number shown as `[n]`
    # in the read view IS the index the `--done <n>` / `--reopen <n>`
    # write verbs accept (file order, stable across priority grouping).
    numbered: list[tuple[int, TodoItem]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.open_items) + len(self.done_items)


def build_project_todos(repo_path: Path, *, domain: str) -> ProjectTodos:
    """Load `<repo_path>/lamill.toml` and split its todos for display.

    `has_toml` is False when the site has no `lamill.toml` at all — the
    caller distinguishes "no declaration" from "declared, no todos."
    A `ParseError` propagates (a malformed file is a real problem worth
    surfacing, not silent emptiness).
    """
    doc = lamill_toml.load(repo_path)
    if doc is None:
        return ProjectTodos(domain=domain, has_toml=False)

    # Sort by priority rank only — `sorted` is stable, so the operator's
    # authored order is preserved within each priority bucket.
    open_items = sorted(
        (t for t in doc.todos if t.status == "open"), key=_rank
    )
    done_items = [t for t in doc.todos if t.status == "done"]
    return ProjectTodos(
        domain=domain,
        has_toml=True,
        open_items=open_items,
        done_items=done_items,
        numbered=list(enumerate(doc.todos, start=1)),
    )


def render_project_todos(pt: ProjectTodos, console) -> None:
    """Render one site's tracker: open grouped by priority, done dimmed."""
    console.print(f"[bold]📝 {pt.domain}[/] todos")

    if not pt.has_toml:
        console.print("   [dim]no lamill.toml — nothing to track[/]")
        return
    if pt.total == 0:
        console.print("   [dim]no todos declared[/]")
        return

    # File-order index per item — what the `--done <n>` / `--reopen <n>`
    # verbs accept. Keyed by identity so duplicate task strings stay
    # distinct (sorted views reuse the same TodoItem objects).
    num_by_id = {id(item): n for n, item in pt.numbered}

    if pt.open_items:
        console.print(
            f"\n[bold]Open[/] [dim]({len(pt.open_items)})[/]"
        )
        current: str | None | object = object()  # sentinel ≠ any priority
        for item in pt.open_items:
            if item.priority != current:
                current = item.priority
                style = _PRIORITY_STYLE.get(item.priority, "dim")
                console.print(
                    f"  [{style}]{_priority_label(item.priority)}[/]"
                )
            console.print(f"    [dim]\\[{num_by_id[id(item)]}][/] • {item.task}")

    if pt.done_items:
        console.print(f"\n[dim]Done ({len(pt.done_items)})[/]")
        for item in pt.done_items:
            console.print(
                f"  [dim]\\[{num_by_id[id(item)]}] ✓ {item.task}[/]"
            )


# ---- fleet view -----------------------------------------------------


@dataclass
class FleetTodoRow:
    """One todo paired with the site it belongs to."""
    domain: str
    item: TodoItem


def build_fleet_todos(
    site_dirs: list[Path],
    *,
    priority: str | None = None,
    status: str | None = "open",
) -> list[FleetTodoRow]:
    """Collect todos across every site into one fleetwide worklist.

    `status` filters by `open` / `done` (None = both). `priority` filters
    open items to a single priority level (None = all). Sites without a
    `lamill.toml` or `[[todo]]` table contribute nothing (additive-
    optional invariant). A site whose `lamill.toml` fails to parse is
    skipped rather than aborting the whole sweep — fleet views must
    survive one bad file.

    Rows sort by priority (high → unset), then domain, then task.
    """
    rows: list[FleetTodoRow] = []
    for site_dir in site_dirs:
        try:
            doc = lamill_toml.load(site_dir)
        except lamill_toml.ParseError:
            continue
        if doc is None:
            continue
        for item in doc.todos:
            if status is not None and item.status != status:
                continue
            if priority is not None and item.priority != priority:
                continue
            rows.append(FleetTodoRow(domain=site_dir.name, item=item))

    rows.sort(key=lambda r: (_sort_key(r.item)[0], r.domain, r.item.task.lower()))
    return rows


def render_fleet_todos(
    rows: list[FleetTodoRow],
    console,
    *,
    priority: str | None = None,
    status: str | None = "open",
) -> None:
    """Render the fleetwide worklist grouped by priority."""
    filt = []
    if status is not None:
        filt.append(f"status={status}")
    if priority is not None:
        filt.append(f"priority={priority}")
    suffix = f" [dim]({', '.join(filt)})[/]" if filt else ""
    console.print(f"[bold]📝 Fleet todos[/]{suffix}")

    if not rows:
        console.print("   [dim]nothing matches[/]")
        return

    # Group by priority for open-only views; otherwise flat (done items
    # carry no priority, so grouping would be a single bucket anyway).
    if status == "open":
        current: str | None | object = object()
        for row in rows:
            if row.item.priority != current:
                current = row.item.priority
                style = _PRIORITY_STYLE.get(row.item.priority, "dim")
                console.print(
                    f"\n[{style}]{_priority_label(row.item.priority)}[/]"
                )
            console.print(f"  [bold]{row.domain}[/]  {row.item.task}")
    else:
        for row in rows:
            mark = "✓" if row.item.status == "done" else "•"
            console.print(f"  {mark} [bold]{row.domain}[/]  {row.item.task}")

    console.print(f"\n[dim]{len(rows)} item(s)[/]")
