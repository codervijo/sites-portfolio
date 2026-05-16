"""Operator profile loader for v8.D Phase 3.

Reads `[operator]` from `sites/portfolio/lamill.toml`. The full
`lamill.toml` schema lands in v9.A; this loader is intentionally
narrow — it only cares about the `[operator]` section and silently
ignores everything else.

Location decision (PRD §8.D P3, 2026-05-16): visible per-site path,
NOT `~/.lamill/operator.yaml`. The profile lives in the portfolio
repo itself; every other `sites/<domain>/` repo omits the section.

Three fields:
- `expertise: list[str]` — operator's strong areas (free-form labels)
- `workflow_preference: "builder" | "writer" | "mixed"` — how the
  operator likes to spend project time
- `motivation_cadence: "weekly" | "monthly" | "quarterly"` — how
  often the operator checks back on a niche

Missing file / missing section / unrecognized values all degrade to
defaults rather than raising. The tool runs without an operator
profile; the gates just skip the fit checks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .data import ROOT

LAMILL_TOML = ROOT / "lamill.toml"

WORKFLOW_VALUES = ("builder", "writer", "mixed")
CADENCE_VALUES = ("weekly", "monthly", "quarterly")

DEFAULT_WORKFLOW = "mixed"
DEFAULT_CADENCE = "monthly"


@dataclass
class OperatorProfile:
    expertise: list[str] = field(default_factory=list)
    workflow_preference: str = DEFAULT_WORKFLOW
    motivation_cadence: str = DEFAULT_CADENCE

    @property
    def configured(self) -> bool:
        """True if any non-default value is set — used by `show` to
        distinguish "no profile configured" from "all defaults"."""
        return bool(self.expertise) or (
            self.workflow_preference != DEFAULT_WORKFLOW
        ) or (
            self.motivation_cadence != DEFAULT_CADENCE
        )


def load_operator_profile(path: Path | None = None) -> OperatorProfile:
    """Load `[operator]` from `sites/portfolio/lamill.toml`.

    `path` overrides the default location (used by tests). Missing
    file, missing `[operator]` section, malformed TOML, or unknown
    enum values all return a default `OperatorProfile()` — the loader
    never raises on bad input.
    """
    import tomllib

    p = path if path is not None else LAMILL_TOML
    if not p.exists():
        return OperatorProfile()
    try:
        with p.open("rb") as f:
            doc = tomllib.load(f)
    except (OSError, ValueError):
        return OperatorProfile()

    section = doc.get("operator")
    if not isinstance(section, dict):
        return OperatorProfile()

    return OperatorProfile(
        expertise=_clean_str_list(section.get("expertise")),
        workflow_preference=_clean_enum(
            section.get("workflow_preference"),
            WORKFLOW_VALUES,
            DEFAULT_WORKFLOW,
        ),
        motivation_cadence=_clean_enum(
            section.get("motivation_cadence"),
            CADENCE_VALUES,
            DEFAULT_CADENCE,
        ),
    )


def _clean_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()]


def _clean_enum(value: object, allowed: tuple[str, ...], default: str) -> str:
    if isinstance(value, str) and value.strip().lower() in allowed:
        return value.strip().lower()
    return default
