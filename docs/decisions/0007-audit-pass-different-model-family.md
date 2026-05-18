# 0007 — Audit pass uses different model family

- **Status:** Accepted
- **Date:** 2026-05-17 *(v12 tier split)*

## Context

The v8 / v12 adversarial-audit arc runs two LLM passes against a SERP
cluster:

1. **Primary interpretive pass** — turns mechanical SERP signal into
   a verdict (GO / NICHE-DOWN / NO-GO) with reasoning, moat prompt,
   reductions, operator-fit warnings, and a `blind_spot_self_report`.
2. **Adversarial audit pass** — reads the primary's verdict (minus
   the self-report, to avoid anchoring) and produces an
   `agreement_level` (full / partial / disagree) with `confidence`,
   `specific_concerns`, optional `counter_verdict`, optional
   `audit_self_check`.

The audit's *entire purpose* is to surface blind spots the primary
missed. If both passes use the same model, they share training-data
biases, RLHF patterns, and refusal/agreement tendencies. The audit
becomes near-useless — agreement reflects shared blind spots, not
genuine validation.

## Decision

**Different model families per pass.**

- Primary pass: Claude (`claude-sonnet-4-6` default, override via
  `--model`).
- Audit pass: OpenAI (`gpt-4o` default, override via
  `--audit-model`).
- The CLI **rejects same-model setups** at the validation layer —
  if `--model X --audit-model X` resolves to the same model id (or
  the same provider when only one is configured), the command errors
  out before either call is made.
- The audit prompt is in a separate file
  (`prompts/adversarial_audit_v1.md`) with its own response-format
  spec — schemas are intentionally different to keep the audit
  visually + structurally distinct from the primary.

## Consequences

**Positive.**
- The `REVIEW_REQUIRED` reconciliation verdict (when models
  disagree) is genuinely informative — not an artifact of shared
  blind spots.
- Operator gets real adversarial signal, especially on novel niches
  where shared-training-data assumptions might be wrong.

**Negative.**
- Two SDKs / two HTTP clients (Anthropic + OpenAI). Two API keys.
- ~2× cost per `--verify` invocation (primary + audit).
- Two prompt-template formats. Two response parsers
  (`parse_verdict` for primary, `parse_audit` for audit). More
  surface area for drift between providers.
- Same-model rejection logic must understand provider aliases
  (e.g., Claude via OpenRouter vs. Claude direct) to avoid
  accidental same-model bypass.

**Trade-offs accepted.**
- The cost doubles only on `--verify`; default is primary-only.
- Audit is opt-in until v12.F lands `verify_by_default` operator
  flag.

## References

- `prompts/niche_evaluation_v1.md` (primary).
- `prompts/adversarial_audit_v1.md` (audit).
- `src/portfolio/interpretive_pass.py` (primary runner).
- `src/portfolio/audit_pass.py` (audit runner — v12.A shipped;
  v12.B–G in flight).
- v12.A note in `docs/prd.md` § Versions.
- v8.J — audit payload builder; explicit
  `_reconstruct_primary_markdown` strips the `blind_spot_self_report`
  before passing to audit.
