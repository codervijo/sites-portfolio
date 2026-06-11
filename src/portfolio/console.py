"""Shared rich Console singleton + small progress helpers.

Extracted (v35.F incr 4) so that cli.py and the modules split out of it
(`cli_domain.py`, …) can each `from .console import console` and depend on
this neutral leaf instead of on each other — breaking the would-be
cli ↔ cli_domain import cycle.
"""
from __future__ import annotations

import contextlib
import time

from rich.console import Console

console = Console()


class _SpinnerCounter:
    """Callable progress sink yielded by `spinner_counter`.

    Pass it straight to a `progress_callback=`, or call it manually as
    `cb(done, total, item)` inside a hand-rolled loop. Read `.elapsed`
    after the loop to compose the final summary line.
    """

    def __init__(self, label: str, status, start: float) -> None:
        self._label = label
        self._status = status
        self._start = start

    def __call__(self, done: int, total: int, item: str = "") -> None:
        if self._status is None:
            return  # non-TTY: stay quiet, no per-item spam
        tail = f" · {item}" if item else ""
        self._status.update(
            f"[cyan]{self._label}[/]  [dim]{done}/{total}{tail}[/]")

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._start


@contextlib.contextmanager
def spinner_counter(label: str, total: int):
    """Live 'spinner + counter' progress for a per-item loop — one animated
    in-place line instead of one log line per item.

    On a TTY: `⠹ {label}  3/43 · item`, redrawn in place, gone on exit.
    Off a TTY (piped / cron): a single start notice, then silence — logs
    don't fill with per-item spam.

    Yields a `_SpinnerCounter`. The caller prints the final `✓` summary
    (it knows the result paths); read the yielded value's `.elapsed` for
    the timing.
    """
    is_tty = console.is_terminal
    if not is_tty:
        console.print(f"[cyan]{label} ({total} domains)…[/]")
    status_cm = (
        console.status(f"[cyan]{label}[/]  [dim]0/{total}[/]", spinner="dots")
        if is_tty else contextlib.nullcontext()
    )
    with status_cm as status:
        yield _SpinnerCounter(label, status, time.monotonic())
