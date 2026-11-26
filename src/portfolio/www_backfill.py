"""v46.E — one-shot fleet backfill: `www.<apex>` resolves and 301s to the apex.

`fleet fix` only runs a fixer when its check fails, and CHECK_150 still
passes sites whose `www` doesn't resolve at all until v46.F flips that rule
(fix-first, enforce-last). So the backfill runs CHECK_150's own fixer
(`fix_tier_1` — CF: proxied `www` CNAME + Single Redirect rule; Vercel:
www→apex domain redirect) directly, regardless of check status.

Same site list and exclusions as `fleet fix` (ignore_repos, dark sites,
"to be deleted" category); the fixer's own guard skips any apex that isn't
a live 200 (parked / broken outliers). Idempotent per site (ADR-0015 rules).

    uv run python -m portfolio.www_backfill            # dry run (default)
    uv run python -m portfolio.www_backfill --apply    # write

Gated per the v46.E row: dry run → operator review → explicit --apply.
Not a CLI verb on purpose — a one-shot that goes away once the fleet is
clean and v46.F enforces the rule.
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Callable

from .fix_helpers import FixResult

DEFAULT_WORKERS = 8
_MARK = {"fixed": "✓", "nothing-to-do": "✓", "would-fix": "↷",
         "manual": "✗", "error": "✗"}


def eligible_sites() -> list[tuple[str, Path]]:
    from .fix_cli import _list_fleet_eligible_projects
    return _list_fleet_eligible_projects()


def run(sites: list[tuple[str, Path]], *, apply: bool, workers: int = DEFAULT_WORKERS,
        fixer: Callable[[Path, bool, bool], FixResult] | None = None,
        on_result: Callable[[str, FixResult], None] | None = None,
        ) -> dict[str, FixResult]:
    """Run the CHECK_150 fixer on every site, `workers` at a time. Never
    raises for one site's failure — an exception becomes that site's
    `error` result so the rest of the fleet still runs."""
    if fixer is None:
        from .checks.seo.check_150_apex_canonical_redirect import fix_tier_1
        fixer = fix_tier_1.apply
    results: dict[str, FixResult] = {}

    def one(domain: str, path: Path) -> tuple[str, FixResult]:
        try:
            return domain, fixer(path, not apply, True)
        except Exception as e:  # noqa: BLE001 — isolate per-site failures
            return domain, FixResult(status="error",
                                     summary=f"{type(e).__name__}: {e}", files_touched=[])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = [pool.submit(one, d, p) for d, p in sites]
        for f in as_completed(futs):
            domain, res = f.result()
            results[domain] = res
            if on_result:
                on_result(domain, res)
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m portfolio.www_backfill",
                                 description=__doc__.split("\n\n")[0])
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--only", nargs="*", help="limit to these domains")
    args = ap.parse_args(argv)

    sites = eligible_sites()
    if args.only:
        want = {d.lower() for d in args.only}
        sites = [(d, p) for d, p in sites if d.lower() in want]
    mode = "APPLY" if args.apply else "dry run"
    print(f"v46.E www→apex backfill — {mode} — {len(sites)} site(s), "
          f"{args.workers} at a time", flush=True)

    def show(domain: str, res: FixResult) -> None:
        print(f"{_MARK.get(res.status, '·')} {domain:26} {res.status:13} "
              f"{res.summary.splitlines()[0] if res.summary else ''}", flush=True)

    results = run(sites, apply=args.apply, workers=args.workers, on_result=show)
    counts: dict[str, int] = {}
    for r in results.values():
        counts[r.status] = counts.get(r.status, 0) + 1
    print("summary: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())), flush=True)
    return 1 if counts.get("error") else 0


if __name__ == "__main__":
    sys.exit(main())
