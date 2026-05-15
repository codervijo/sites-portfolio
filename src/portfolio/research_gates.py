"""v8.D Phase 2 — three-gate decision logic.

Pure logic, no I/O, no CLI. Takes a `research-cluster-v2` snapshot
(produced by `research_v2.py` in Phase 1) and returns gate results +
overall verdict.

The three gates:

  1. **Market** (`evaluate_gate_1`) — pollution-adjusted search-volume
     estimate. PASS when the cluster has ≥5K SV/month after polluted
     queries are zeroed out. The volume proxy itself is LLM-estimated
     and flagged low-confidence (PRD §8.A option 1).

  2. **SERP** (`evaluate_gate_2`) — seven classifiers run over the
     merged top-10 across cluster queries. Kill-tier classifiers
     (specialty incumbent / programmatic-at-scale / locked intents)
     force FAIL; sufficient `POTENTIALLY_BEATABLE` results force PASS;
     anything between is WEAK PASS with a niche-down finding.

  3. **Moat** (`evaluate_gate_3`) — interactive. Required only when
     Gate 2 detected a specialty incumbent / programmatic incumbent.
     Caller passes the user's typed sentence (or None for FAIL).

Verdict synthesis lives in `synthesize_verdict()` per PRD §P2.5.

The functions in this module accept dicts (the cluster snapshot shape)
and return dicts so they're trivially serializable into the
`research-cluster-v2` schema's `gates` / `verdict` slots without
adapter code in the CLI layer.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

# Labels for the gate-result `label` field. Kept as constants so callers
# can pattern-match without remembering capitalization.
LABEL_PASS = "PASS"
LABEL_FAIL = "FAIL"
LABEL_WEAK_PASS = "WEAK-PASS"
LABEL_PENDING = "PENDING"

# Verdicts emitted by synthesize_verdict().
VERDICT_GO = "GO"
VERDICT_NICHE_DOWN = "NICHE-DOWN"
VERDICT_NO_GO = "NO-GO"

# Gate 1 threshold (PRD §P2.2). Pollution-adjusted volume below this
# fails the market gate.
GATE_1_VOLUME_THRESHOLD = 5000

# Gate 2 PASS threshold (PRD §P2.3). Number of beatable results required
# across the merged cluster top-10s.
GATE_2_BEATABLE_THRESHOLD = 3


# ---------- dataclasses ----------


@dataclass
class GateResult:
    """One gate's outcome.

    `passed=None` is reserved for Gate 3 in `--non-interactive` / `--json`
    mode where the user hasn't been prompted yet. In that case `label`
    is `PENDING` and the verdict treats it as if it had failed.
    """
    passed: bool | None
    label: str
    findings: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class OperatorFitResult:
    """Operator-profile findings layered on top of the gates.

    Empty in Phase 2 — populated by Phase 3 when operator.toml exists.
    Carrying the dataclass through Phase 2 keeps the snapshot schema
    forward-compatible.
    """
    warnings: list[str] = field(default_factory=list)
    auto_fail_gate_2: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GateResults:
    """All gates + operator fit + final verdict for one cluster."""
    gate_1_market: GateResult
    gate_2_serp: GateResult
    gate_3_moat: GateResult
    operator_fit: OperatorFitResult
    verdict: str
    suggested_reductions: list[str] = field(default_factory=list)
    moat_required: bool = False
    moat_provided: str | None = None

    def to_dict(self) -> dict:
        return {
            "gate_1_market": self.gate_1_market.to_dict(),
            "gate_2_serp": self.gate_2_serp.to_dict(),
            "gate_3_moat": self.gate_3_moat.to_dict(),
            "operator_fit": self.operator_fit.to_dict(),
            "verdict": self.verdict,
            "suggested_reductions": list(self.suggested_reductions),
            "moat_required": self.moat_required,
            "moat_provided": self.moat_provided,
        }


# ---------- gate stubs (filled in by P2.B / P2.C / P2.D) ----------


def evaluate_gate_1(cluster: dict) -> GateResult:
    """Gate 1 (Market) — pollution-adjusted search-volume check.

    Stub: returns PENDING. P2.B replaces this with the real logic.
    """
    return GateResult(
        passed=None, label=LABEL_PENDING,
        findings=["Gate 1 not yet implemented (P2.B)"],
        raw={"stub": True},
    )


def evaluate_gate_2(cluster: dict) -> GateResult:
    """Gate 2 (SERP) — seven classifiers + pass/fail/weak-pass.

    Stub: returns PENDING. P2.C replaces this with the real logic.
    """
    return GateResult(
        passed=None, label=LABEL_PENDING,
        findings=["Gate 2 not yet implemented (P2.C)"],
        raw={"stub": True},
    )


def evaluate_gate_3(gate_2: GateResult, moat_sentence: str | None,
                    *, non_interactive: bool = False) -> GateResult:
    """Gate 3 (Moat) — required only when Gate 2 detected a specialty
    or programmatic incumbent.

    The moat-required check inspects `gate_2.raw["classifications"]`
    for the kill-tier classifier flags. When required:
      - `moat_sentence` non-empty → PASS, sentence stored on `.raw`
      - `moat_sentence` empty/None AND `non_interactive` → PENDING
      - `moat_sentence` empty/None AND interactive → FAIL

    When not required, returns PASS with an explanatory finding.

    Stub returns PENDING for now. P2.D fills it in.
    """
    return GateResult(
        passed=None, label=LABEL_PENDING,
        findings=["Gate 3 not yet implemented (P2.D)"],
        raw={"stub": True},
    )


# ---------- verdict synthesis (filled in by P2.E) ----------


def synthesize_verdict(g1: GateResult, g2: GateResult, g3: GateResult,
                       *, op_fit: OperatorFitResult | None = None) -> str:
    """Compose final verdict per PRD §P2.5.

    The table:
      | Gates                                          | Verdict       |
      |------------------------------------------------|---------------|
      | Gate 1 FAIL                                    | NO-GO         |
      | Gate 2 FAIL AND Gate 3 PROVIDED                | NICHE-DOWN    |
      | Gate 2 FAIL AND no moat                        | NO-GO         |
      | G1 PASS + G2 WEAK-PASS + Gate 3 not required   | NICHE-DOWN    |
      | All gates PASS                                 | GO            |

    Operator-fit's `auto_fail_gate_2` flag (Phase 3) is honored by
    treating Gate 2 as FAIL even if its label is PASS / WEAK-PASS.

    Stub returns NO-GO until P2.E fills it in.
    """
    return VERDICT_NO_GO


# ---------- helpers (shared across gates) ----------


def is_moat_required(gate_2: GateResult) -> bool:
    """True when Gate 2's findings include a SPECIALTY_INCUMBENT or
    PROGRAMMATIC_AT_SCALE classifier hit.

    Used by callers to decide whether to prompt the user before
    invoking `evaluate_gate_3`.
    """
    cls = gate_2.raw.get("classifications", {}) if gate_2.raw else {}
    if cls.get("specialty_incumbent"):
        return True
    if cls.get("programmatic_at_scale"):
        return True
    return False


def evaluate_cluster(cluster: dict, *, moat_sentence: str | None = None,
                     non_interactive: bool = False,
                     operator_fit: OperatorFitResult | None = None) -> GateResults:
    """Run all three gates against a cluster snapshot and return the
    composed `GateResults`. The orchestrator entry point used by the CLI.

    Phase 2's CLI will call this once Gate 1 + Gate 2 + Gate 3 are real.
    Today it returns a fully-PENDING result so callers can wire the
    plumbing without waiting on P2.B/C/D.
    """
    g1 = evaluate_gate_1(cluster)
    g2 = evaluate_gate_2(cluster)
    g3 = evaluate_gate_3(g2, moat_sentence, non_interactive=non_interactive)
    op_fit = operator_fit or OperatorFitResult()
    verdict = synthesize_verdict(g1, g2, g3, op_fit=op_fit)
    return GateResults(
        gate_1_market=g1,
        gate_2_serp=g2,
        gate_3_moat=g3,
        operator_fit=op_fit,
        verdict=verdict,
        suggested_reductions=[],
        moat_required=is_moat_required(g2),
        moat_provided=moat_sentence,
    )
