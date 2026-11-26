"""v50.D — build check for fixers that edit site source (option A).

`project fix` / `fleet fix --apply` run each tier-1 fixer; the ones marked
`FixerSpec.edits_source` (CHECK_163 GA4 tag, CHECK_166 footer link) change
layouts / components / `index.html`. After those fixers ran on a site, the
site builds in the container — `fleet ga`'s build gate, reused:

  - pre-run bytes of every file a fixer could touch are snapshotted
    (`fleet_ga.Snapshot`) before the first fixer runs;
  - build failed → the touched files are restored → ✗ with the cause;
  - build passed → ✓ "built", ready for the operator to commit;
  - files the build itself regenerated (e.g. `public/sitemap.xml`) are put
    back either way, so the repo is left as found plus the fix.

Config-only fixes skip the build. Commit and push stay with the operator
(ADR-0003 unchanged). The build runner is injectable; `tests/conftest.py`
stubs `default_build` so the suite never starts a container.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

BuildFn = Callable[[Path], tuple[bool, str]]


def default_build(base: Path) -> tuple[bool, str]:
    from .new_site import build_in_container
    return build_in_container(base)


@dataclass
class GateOutcome:
    kind: str                 # "built" | "failed" | "skipped"
    detail: str
    reverted: list[Path] = field(default_factory=list)


class BuildGate:
    """One per site and fix run. Create before the first fixer runs,
    `record()` every fixer result, `finish()` once all fixers are done."""

    def __init__(self, base: Path, *, build: BuildFn | None = None):
        from .fleet_ga import Snapshot, _dirty
        self.base = Path(base)
        self.build = build or default_build
        self.snap = Snapshot(self.base)
        self.dirty_before = _dirty(self.base)
        self.touched: list[Path] = []
        self.by_check: dict[str, list[Path]] = {}

    def record(self, spec, result) -> None:
        if not getattr(spec, "edits_source", False) or result.status != "fixed":
            return
        files = [Path(p) for p in result.files_touched]
        self.by_check[spec.check_id] = files
        for p in files:
            if p not in self.touched:
                self.touched.append(p)

    @property
    def needed(self) -> bool:
        return any(p.name != "lamill.toml" for p in self.touched)

    def finish(self) -> GateOutcome:
        from .fleet_ga import _undo_build_side_effects
        if not self.needed:
            return GateOutcome("skipped", "no source edits — no build needed")
        try:
            ok, detail = self.build(self.base)
        except Exception as e:  # noqa: BLE001 — a crashed build is a failed build
            ok, detail = False, f"build couldn't run ({type(e).__name__}: {e})"
        try:
            _undo_build_side_effects(self.base, self.dirty_before, self.touched)
        except Exception:  # noqa: BLE001 — not a git repo, etc.
            pass
        if not ok:
            self.snap.restore(self.touched)
            return GateOutcome("failed", f"{detail} — source edits reverted "
                                         f"({', '.join(self.checks)})", list(self.touched))
        return GateOutcome("built", f"{detail} — ready to commit "
                                    f"({len(self.touched)} file(s); commit + push are yours)")

    @property
    def checks(self) -> list[str]:
        return sorted(self.by_check)


def needs_gate(specs) -> bool:
    return any(getattr(s, "edits_source", False) for s in specs if s is not None)
