"""v7.B-pre — `fleet repos`: audit + categorize per-site git state.

Surfaces three signals that the rest of the fleet commands don't:

  1. Which sites have own .git, which don't, which are caught in the
     "tracked-by-both-monorepo-and-standalone" anti-pattern.
  2. Which standalone repos have a remote configured, which are
     local-only.
  3. Which existing remotes follow the full-domain naming convention
     (enforced separately by CHECK_040) vs. truncated.

Read-only by design — pure classifier + renderer. The `--fix` write
mode is intentionally deferred; see docs/CLAUDE.md.

State definitions:

  clean        — own .git + remote + not tracked in the outer monorepo
                 (the canonical target state)

  nested       — own .git + outer monorepo tracks files at this path
                 (the lamill.io / airsucks-pre-bootstrap / csinorcal.church
                 pattern). Mechanical fix: `git rm --cached -r <dir>` from
                 the outer + add to outer .gitignore.

  unpublished  — own .git but no `origin` remote configured. Needs
                 `gh repo create` + push.

  monorepo     — tracked in outer with content, no own .git. Promote to
                 standalone via `git init` + initial commit.

  unversioned  — content exists on disk, no .git anywhere (not in outer,
                 no inner). Same fix as monorepo but without the
                 outer-untrack step.

  stub         — directory exists but no real content (≤ 2 files or
                 < 2KB total). Likely a placeholder; skip in fix flow.

  unknown      — couldn't classify (transient error reading the dir).
  archived     — the user has intentionally retired this site. Detected
                 via either (a) presence of a `TOMBSTONE.md` marker file
                 in the project root, or (b) portfolio.json category in
                 ARCHIVED_CATEGORIES. Listed separately in the audit and
                 NOT flagged as a violation regardless of other state
                 (no-remote, nested, etc. don't matter for a project
                 that's being wound down).
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .project import SITES_ROOT


# Directories under sites/ that aren't actual projects.
_NON_PROJECT_NAMES = frozenset({
    "portfolio", "node_modules", "harmonia", "tarball", "levents",
    "__pycache__",
})

# Portfolio.json categories that mean "this site is being retired."
# Lowercase for case-insensitive matching. Order doesn't matter.
ARCHIVED_CATEGORIES = frozenset({
    "to be deleted immediately",
    "archived",
    "tombstoned",
})

# Filename used as a per-directory tombstone marker. If present at the
# project root, the site is treated as archived even if the canonical
# portfolio.json category hasn't been updated yet (or never gets updated
# because the dir is being deleted soon anyway).
TOMBSTONE_MARKER = "TOMBSTONE.md"

# Files commonly present in a barely-initialized stub. If everything in the
# directory is in this set, treat it as a stub (not worth `--fix`).
_STUB_ONLY_FILES = frozenset({
    "AI_AGENTS.md", "README.md", "docs", ".gitignore", ".claudeignore",
})


@dataclass
class RepoState:
    """One site's git-layer state — what `fleet repos` audits."""
    name: str
    path: Path
    state: str                             # see module docstring
    inner_git: bool = False                # has own .git/
    inner_remote: str | None = None        # `origin` URL if configured
    inner_remote_basename: str | None = None
    naming_ok: bool | None = None          # full-domain naming match
    outer_tracked: int = 0                 # count of files tracked by outer
    outer_modified: int = 0                # count of files modified in outer WT
    archived_reason: str | None = None     # why we classified this as archived
    notes: list[str] = field(default_factory=list)


def list_site_dirs(sites_root: Path | None = None) -> list[Path]:
    """All real sites/<dir>/ directories, excluding obvious non-projects."""
    root = sites_root or SITES_ROOT
    if not root.exists():
        return []
    out: list[Path] = []
    for p in sorted(root.iterdir()):
        if not p.is_dir():
            continue
        if p.name.startswith("."):
            continue
        if p.name in _NON_PROJECT_NAMES:
            continue
        out.append(p)
    return out


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command, capture stdout. Returns (rc, stripped-stdout)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=cwd, capture_output=True, text=True,
            check=False, timeout=10,
        )
        return r.returncode, r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def _remote_basename(url: str) -> str | None:
    """Trailing `<repo>` from an SSH/HTTPS remote URL, stripping `.git`."""
    import re
    m = re.search(r"[/:]([^/:]+)/?$", url.strip().rstrip("/"))
    if not m:
        return None
    name = m.group(1)
    if name.endswith(".git"):
        name = name[:-4]
    return name or None


def _outer_track_state(name: str, sites_root: Path) -> tuple[int, int]:
    """How many files at <name>/ are tracked in the outer monorepo, and
    how many of those are currently modified in the outer working tree.
    Returns (tracked_count, modified_count). (0, 0) if there is no outer
    repo or the path isn't tracked."""
    if not (sites_root / ".git").exists():
        return (0, 0)
    rc, out = _git(["ls-files", "--", name + "/"], cwd=sites_root)
    if rc != 0:
        return (0, 0)
    tracked = len([line for line in out.splitlines() if line.strip()])
    rc, out = _git(["status", "--porcelain", "--", name + "/"], cwd=sites_root)
    if rc != 0:
        return (tracked, 0)
    modified = sum(1 for line in out.splitlines()
                   if line and not line.startswith("??"))
    return (tracked, modified)


def _is_stub(p: Path) -> bool:
    """A directory is a stub when it has at most a handful of doc files
    + standard scaffolding placeholders. Not worth promoting to its own
    repo until real content lands."""
    try:
        entries = list(p.iterdir())
    except OSError:
        return False
    real = [e for e in entries if e.name != ".git"]
    if len(real) > 3:
        return False
    return all(e.name in _STUB_ONLY_FILES for e in real)


def _archived_reason(site_dir: Path) -> str | None:
    """If this site is archived/tombstoned, return a human-readable
    reason; otherwise None.

    Two detection signals (checked in order):
      1. `TOMBSTONE.md` file at the project root — per-directory marker
         (works even before portfolio.json is updated, and survives the
         portfolio.json reload cycle).
      2. portfolio.json category in ARCHIVED_CATEGORIES — the canonical
         data-layer signal (e.g., "To be deleted immediately").

    The marker file wins so the user has a fast, local override that
    doesn't require touching shared inventory.
    """
    if (site_dir / TOMBSTONE_MARKER).exists():
        return f"{TOMBSTONE_MARKER} present"
    try:
        from .data import load_domains
        for d in load_domains():
            if d.name.lower() == site_dir.name.lower():
                cat = (d.category or "").lower()
                if cat in ARCHIVED_CATEGORIES:
                    return f"category={d.category!r}"
                return None
    except Exception:
        # If we can't load portfolio.json, fall through — don't auto-
        # classify as archived on a transient I/O error.
        return None
    return None


def classify_site(site_dir: Path, sites_root: Path | None = None) -> RepoState:
    """Build a `RepoState` for one site directory.

    Pure function — read-only filesystem inspection. The decision tree:

       archived?         yes  →  archived (overrides everything)
                         |
                         v no
       has .git?         no   →  outer tracks it?  yes  →  monorepo
                         |                          no   →  stub  or  unversioned
                         v
                         yes  →  outer tracks it?  yes  →  nested
                                                   no   →  has remote?  yes/clean
                                                                        no/unpublished
    """
    name = site_dir.name
    sites_root = sites_root or SITES_ROOT

    # Archive check runs first — overrides every other state. We still
    # collect the git layer info so detail-mode can show it (and so that
    # un-archiving a project later just removes the marker and the
    # classifier picks up the underlying state again).
    archived_reason = _archived_reason(site_dir)

    inner_git = (site_dir / ".git").exists()
    inner_remote = None
    inner_basename = None
    naming_ok = None

    if inner_git:
        rc, url = _git(["remote", "get-url", "origin"], cwd=site_dir)
        if rc == 0 and url:
            inner_remote = url
            inner_basename = _remote_basename(url)
            naming_ok = (inner_basename == name)

    outer_tracked, outer_modified = _outer_track_state(name, sites_root)

    if archived_reason:
        state = "archived"
    elif inner_git:
        if outer_tracked > 0:
            state = "nested"
        elif inner_remote is None:
            state = "unpublished"
        else:
            state = "clean"
    else:
        if outer_tracked > 0:
            state = "monorepo"
        elif _is_stub(site_dir):
            state = "stub"
        else:
            state = "unversioned"

    rs = RepoState(
        name=name,
        path=site_dir,
        state=state,
        inner_git=inner_git,
        inner_remote=inner_remote,
        inner_remote_basename=inner_basename,
        naming_ok=naming_ok,
        outer_tracked=outer_tracked,
        outer_modified=outer_modified,
        archived_reason=archived_reason,
    )

    # Notes — useful context. Archived sites get only the archive note;
    # we skip the other "you should fix this" notes since they don't apply.
    if state == "archived":
        rs.notes.append(f"archived: {archived_reason}")
        return rs

    if state == "nested" and outer_modified > 0:
        rs.notes.append(
            f"outer has {outer_modified} modified file(s) — verify they "
            f"exist in standalone before any --fix run"
        )
    if state == "unpublished":
        rs.notes.append("no origin remote — run `gh repo create` + push")
    if naming_ok is False and inner_basename:
        rs.notes.append(
            f"remote name `{inner_basename}` truncates domain "
            f"(expected `{name}`) — CHECK_040 flags this"
        )

    return rs


def audit(sites_root: Path | None = None) -> list[RepoState]:
    """Classify every site under `sites_root`."""
    return [classify_site(p, sites_root) for p in list_site_dirs(sites_root)]


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


_STATE_LABEL = {
    "clean":       ("✓", "clean standalone"),
    "nested":      ("⚠", "nested anti-pattern"),
    "unpublished": ("⚠", "standalone unpublished"),
    "monorepo":    ("⚠", "monorepo-only"),
    "unversioned": ("⚠", "unversioned"),
    "stub":        ("·", "empty stub"),
    "archived":    ("🪦", "archived / tombstoned"),
    "unknown":     ("?", "unknown"),
}
# Clean first, then the action-required states, then stub/archived
# (informational, no fix recommended), then unknown.
_STATE_ORDER = ("clean", "nested", "unpublished", "monorepo",
                "unversioned", "stub", "archived", "unknown")


def render_summary(rows: list[RepoState], console) -> None:
    """Top-level audit table — counts per state + naming-violation list."""
    from collections import defaultdict
    from rich.table import Table

    by_state: dict[str, list[RepoState]] = defaultdict(list)
    for r in rows:
        by_state[r.state].append(r)

    outer_remote = _outer_remote_url()
    header = f"fleet repos · {len(rows)} sites"
    if outer_remote:
        header += f" · outer: {outer_remote}"
    console.print(f"[bold]{header}[/]\n")

    t = Table(box=None, padding=(0, 1), show_header=True)
    t.add_column(" ")
    t.add_column("State")
    t.add_column("Count", justify="right")
    t.add_column("Sites")
    for state in _STATE_ORDER:
        sites_in_state = by_state.get(state, [])
        if not sites_in_state:
            continue
        marker, label = _STATE_LABEL[state]
        names = ", ".join(r.name for r in sites_in_state[:6])
        if len(sites_in_state) > 6:
            names += f" + {len(sites_in_state) - 6} more"
        t.add_row(marker, label, str(len(sites_in_state)),
                  "" if state == "clean" else names)
    console.print(t)

    # Naming check (separate axis from state — a clean standalone can still
    # have a truncated remote name). Skip archived sites — naming violations
    # don't matter for a project being wound down.
    bad_names = [r for r in rows
                 if r.naming_ok is False and r.state != "archived"]
    if bad_names:
        console.print(
            f"\n[bold]Naming check (CHECK_040): "
            f"{len(bad_names)} remote(s) truncated[/]"
        )
        for r in bad_names:
            console.print(
                f"  [red]✗[/]  {r.name:<24} → "
                f"[dim]{r.inner_remote_basename}[/] "
                f"(expected [cyan]{r.name}[/])"
            )

    # Footer guidance. Archived sites are deliberately excluded from
    # the "needs action" counts since they're being retired.
    fix_count = sum(1 for r in rows
                    if r.state in ("nested", "monorepo", "unversioned"))
    publish_count = sum(1 for r in rows if r.state == "unpublished")
    archived_count = sum(1 for r in rows if r.state == "archived")
    hints = []
    if fix_count or publish_count:
        hints.append(
            f"[dim]Run `fleet repos --detail` for per-site plans.[/]"
        )
    if not hints and not bad_names:
        console.print(f"\n[green]All sites clean. No action needed.[/]")
        if archived_count:
            console.print(
                f"[dim]({archived_count} archived site(s) excluded "
                f"from violation checks.)[/]"
            )
    else:
        for h in hints:
            console.print(f"\n{h}")
        if archived_count:
            console.print(
                f"[dim]{archived_count} archived site(s) excluded "
                f"from violation checks.[/]"
            )


def render_detail(rows: list[RepoState], console) -> None:
    """Verbose per-site detail — fix plan and warnings for every non-clean
    entry, naming violations for any entry with a truncated remote."""
    n_detailed = 0
    for r in rows:
        if r.state == "clean" and r.naming_ok is not False:
            continue
        n_detailed += 1
        marker, label = _STATE_LABEL.get(r.state, ("?", r.state))
        console.print(f"\n[bold]{r.name}[/]")
        console.print(f"  [cyan]state:[/]    {marker} {label}")
        if r.inner_git:
            origin = r.inner_remote or "(no origin)"
            console.print(f"  [cyan]inner:[/]    own .git — origin: {origin}")
        else:
            console.print(f"  [cyan]inner:[/]    no .git")
        if r.outer_tracked:
            console.print(
                f"  [cyan]outer:[/]    tracks {r.outer_tracked} files"
                + (f", {r.outer_modified} currently modified"
                   if r.outer_modified else "")
            )
        else:
            console.print(f"  [cyan]outer:[/]    not tracked")
        if r.naming_ok is False:
            console.print(
                f"  [cyan]naming:[/]   [red]✗[/] CHECK_040 fails — "
                f"`{r.inner_remote_basename}` (expected `{r.name}`)"
            )

        # Fix plan (read-only — text only; --fix mode is deferred).
        plan = _fix_plan(r)
        if plan:
            console.print("  [cyan]fix plan:[/]")
            for line in plan:
                console.print(f"    [dim]{line}[/]")
        if r.notes:
            console.print("  [cyan]notes:[/]")
            for n in r.notes:
                console.print(f"    [yellow]·[/] {n}")
    if n_detailed == 0:
        console.print(
            "[green]All sites clean and conforming. Nothing to detail.[/]"
        )


def render_json(rows: list[RepoState], console) -> None:
    """Machine-readable audit dump."""
    payload = {
        "outer_repo": _outer_remote_url(),
        "sites": [
            {
                "name": r.name,
                "state": r.state,
                "inner_git": r.inner_git,
                "inner_remote": r.inner_remote,
                "inner_remote_basename": r.inner_remote_basename,
                "naming_ok": r.naming_ok,
                "outer_tracked": r.outer_tracked,
                "outer_modified": r.outer_modified,
                "notes": r.notes,
                "fix_plan": _fix_plan(r),
            }
            for r in rows
        ],
    }
    console.print(json.dumps(payload, indent=2))


def _fix_plan(r: RepoState) -> list[str]:
    """Read-only fix-plan text — what `--fix` *would* run when it lands.
    Useful for the detail view and JSON output even before --fix exists.

    Archived sites get an empty plan — they're being retired, not fixed.
    """
    if r.state == "archived":
        return []
    if r.state == "nested":
        return [
            f"git -C <outer> rm --cached -r {r.name}",
            f"echo /{r.name}/ >> <outer>/.gitignore",
            f"git -C <outer> add .gitignore && commit",
        ]
    if r.state == "monorepo":
        return [
            f"git -C sites/{r.name} init",
            f"git -C sites/{r.name} add . && commit -m 'snapshot'",
            f"git -C <outer> rm --cached -r {r.name}",
            f"echo /{r.name}/ >> <outer>/.gitignore",
        ]
    if r.state == "unversioned":
        return [
            f"git -C sites/{r.name} init",
            f"git -C sites/{r.name} add . && commit -m 'snapshot'",
        ]
    if r.state == "unpublished":
        return [
            f"gh repo create codervijo/{r.name} --private --source=. --push",
        ]
    return []


def _outer_remote_url() -> str | None:
    """The outer monorepo's origin remote, if it exists. Used only for
    the audit header line so the user knows what `<outer>` refers to."""
    sites_root = SITES_ROOT
    if not (sites_root / ".git").exists():
        return None
    rc, url = _git(["remote", "get-url", "origin"], cwd=sites_root)
    if rc != 0 or not url:
        return None
    name = _remote_basename(url) or url
    return name
