"""v12.D — reconciliation between the primary verdict + adversarial audit.

Pure logic — no LLM calls, no I/O. Takes the `ParsedVerdict` from
`interpretive_pass` (v8.E) and the `ParsedAudit` from `audit_pass`
(v12.B) and produces a `Reconciliation` that the operator sees.

Three reconciliation paths, keyed on `audit.agreement_level`:

  - **full**: audit fully agrees → primary verdict + confidence
    preserved verbatim. No caveats.
  - **partial**: audit raises specific concerns but doesn't reject
    the verdict → primary verdict kept, confidence downgraded one
    notch (HIGH→MEDIUM, MEDIUM→LOW, LOW→LOW), caveats populated from
    audit.specific_concerns.
  - **disagree**: audit's counter_verdict differs from primary →
    final verdict is `REVIEW_REQUIRED`. Intentionally NO auto-
    resolution per PRD §6 v12 — the operator reads both verdicts
    and decides. Final confidence is `LOW` to signal "human required."
    Caveats carry the audit's specific_concerns so the disagreement
    is concretely grounded.

Why no auto-resolution on disagree: the audit's value is precisely
that it caught something the primary missed. Picking a side
mechanically (e.g., "audit wins on HIGH-confidence disagree")
would erode the human's judgment loop, which the verdict gate
exists to support. The operator is the tiebreaker.

The `REVIEW_REQUIRED` token is reserved for reconciliation — it
does NOT appear in either the primary's verdict set
({GO, NICHE-DOWN, NO-GO}) or the audit's agreement-level set
({full, partial, disagree}). Downstream renderers can dispatch on
the token; v12.E surfaces both verdicts side-by-side when this
fires.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from .audit_pass import ParsedAudit
from .interpretive_pass import ParsedVerdict

REVIEW_REQUIRED: Final[str] = "REVIEW_REQUIRED"

# Confidence downgrade ladder for partial-agreement reconciliation.
# The audit raised concerns the primary didn't see; even if the
# verdict stands, the operator should know the model uncertainty is
# higher than the primary's HIGH/MEDIUM stamp implied. LOW saturates
# (no further downgrade possible).
_CONFIDENCE_DOWNGRADE: Final[dict[str, str]] = {
    "HIGH": "MEDIUM",
    "MEDIUM": "LOW",
    "LOW": "LOW",
}


@dataclass
class Reconciliation:
    """Combined output of the primary + audit passes after
    reconciliation. The renderer (v12.E) reads `final_verdict` for
    dispatch and consults `primary` + `audit` for the rich detail.

    Field stability matters — v12.F's snapshot persistence layer will
    serialize this. Avoid renaming after first commit; add new fields
    instead of repurposing.
    """
    final_verdict: str          # GO | NICHE-DOWN | NO-GO | REVIEW_REQUIRED
    final_confidence: str       # HIGH | MEDIUM | LOW
    caveats: list[str] = field(default_factory=list)
    primary: ParsedVerdict | None = None  # always present in practice
    audit: ParsedAudit | None = None      # always present in practice

    @property
    def requires_review(self) -> bool:
        """True when the two passes disagreed and produced
        REVIEW_REQUIRED. Convenience accessor for the renderer +
        CLI exit-code logic in v12.E."""
        return self.final_verdict == REVIEW_REQUIRED


def reconcile(primary: ParsedVerdict, audit: ParsedAudit) -> Reconciliation:
    """Combine the primary's verdict with the audit's response.

    Dispatch is keyed on `audit.agreement_level`:

      - "full":     final = primary.verdict, confidence preserved,
                    caveats empty
      - "partial":  final = primary.verdict, confidence downgraded
                    one notch, caveats = audit.specific_concerns
      - "disagree": final = REVIEW_REQUIRED, confidence = LOW,
                    caveats = audit.specific_concerns. The primary
                    and audit dataclasses are preserved on the
                    result so the renderer can show both verdicts
                    side-by-side.

    Pure: no I/O, no LLM calls. Same (primary, audit) input always
    produces the same Reconciliation — important for snapshot
    determinism.

    Doesn't validate that `audit.counter_verdict_token` differs from
    `primary.verdict` on disagree — the parser already enforced the
    audit prompt's contract (counter required when agreement=disagree).
    Trust the LLM's self-categorization rather than re-deriving it.
    """
    if audit.agreement_level == "full":
        return Reconciliation(
            final_verdict=primary.verdict,
            final_confidence=primary.confidence,
            caveats=[],
            primary=primary,
            audit=audit,
        )

    if audit.agreement_level == "partial":
        return Reconciliation(
            final_verdict=primary.verdict,
            final_confidence=_CONFIDENCE_DOWNGRADE[primary.confidence],
            caveats=list(audit.specific_concerns),
            primary=primary,
            audit=audit,
        )

    # agreement_level == "disagree" (parser enforces the trichotomy,
    # so the else-branch is exhaustive — no defensive fallback).
    return Reconciliation(
        final_verdict=REVIEW_REQUIRED,
        final_confidence="LOW",
        caveats=list(audit.specific_concerns),
        primary=primary,
        audit=audit,
    )
