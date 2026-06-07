"""Shared rich Console singleton.

Extracted (v35.F incr 4) so that cli.py and the modules split out of it
(`cli_domain.py`, …) can each `from .console import console` and depend on
this neutral leaf instead of on each other — breaking the would-be
cli ↔ cli_domain import cycle.
"""
from __future__ import annotations

from rich.console import Console

console = Console()
