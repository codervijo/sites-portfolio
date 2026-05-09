"""v5.A — CheckResult dataclass.

The catalog's universal return shape. Every check function returns a
CheckResult; renderers and aggregators consume them uniformly.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CheckResult:
    """One check's verdict against a single repo / project / domain.

    `status` is one of:
      - "pass" — the check is satisfied
      - "fail" — the check is not satisfied (action recommended)
      - "warn" — soft signal (informational; e.g. "GitHub token not set,
        skipped"); also used for `info`-severity checks where a metric is
        being reported but no pass/fail verdict applies.

    `message` is a short human-readable line. May include rendered values
    (e.g. "12 commits in last 7d", "Vite 5.4.2 — needs ≥6").
    """
    status: str
    message: str = ""

    def is_pass(self) -> bool:
        return self.status == "pass"

    def is_fail(self) -> bool:
        return self.status == "fail"

    def is_warn(self) -> bool:
        return self.status == "warn"
