# 0015 — `new deploy` pipeline must remain idempotent; --watch is opt-in

- **Status:** Accepted
- **Date:** 2026-05-23

## Context

`lamill new deploy <domain>` orchestrates a 9-step pipeline that touches
external state: GitHub, Cloudflare (zones, Pages projects, DNS records,
custom domains, builds), the registrar (Porkbun NS), and Google Search
Console. Several of these states settle on timescales that the pipeline
can't control or shorten:

- **NS propagation** (Porkbun → CF resolvers): 5 minutes to multiple
  hours, depending on the old registrar's NS TTLs.
- **CF zone activation** (`pending` → `active`): triggers when CF detects
  the new NS at the registrar; typically 5–30 minutes for fresh domains.
- **CF Pages first build**: queued on project creation; takes 30s–3min
  to start, then 30s–2min to complete.
- **CF edge SSL provisioning** for the new custom domain: a few more
  minutes after build completes.
- **DNS resolver caches** at the operator's machine + ISP + Google's
  resolvers: several minutes after zone activation.

Total worst-case end-to-end time from `new deploy` invocation to
`https://<domain>/` returning `200 OK` is **5–30 minutes for typical
cases, hours in worst case.**

During the 2026-05-22/23 sessions (agesdk.dev, then permittruck.xyz)
the operator considered making `new deploy` **always-wait** for full
resolution before exiting. The trade-offs were debated:

- **Always-wait advantages**: single-command experience; operator sees
  full state in one run; no manual re-runs needed.
- **Always-wait disadvantages**: ties up the shell for 5–30 min (or
  more) on every fresh-domain deploy; bounded timeout that fires often
  means operator re-runs anyway; silent blocking violates the
  vicarious-building output-discipline rule (operator can't pattern-
  match progress); operator can't switch terminals to do other work
  during the wait.

The push-back: every step in the pipeline already had idempotency
probes (`get-then-post`, `list-then-create`, `status-equality` checks
before re-writing). Re-running a `new deploy` after partial completion
is *cheap* — ~10s of API probes that all skip. That's the natural
recovery model and matches the operator's preferred rhythm of "run →
switch tasks → re-run when ready."

The operator confirmed (2026-05-23 PM, "making deploy idempotent was
the right call, kudos") that quick + idempotent default is the right
shape — followed shortly by "i might forget in 6 months, make sure
future you finds it and follows this rule," which is the trigger for
this ADR.

## Decision

**Every step of `_deploy_cf_unified` (and any future variant of the
deploy pipeline) MUST be idempotent.** Concretely:

1. **Probe before act.** Before any state-changing API call, probe the
   current state and skip the write if it would be a no-op. Patterns
   used: `get_pages_project()` → check `domains[]` → POST only if
   missing; `list_dns_records()` → check for the expected TXT → create
   only if absent; `ensure_zone()` returns existing zone without
   re-creating.
2. **Treat "already X" responses as success.** CF, GitHub, Porkbun,
   and Google APIs all have "already exists" semantics that surface
   variously as HTTP 200 with a duplicate flag, HTTP 409, or
   provider-specific HTTP 400 + error code (e.g., CF code 8000018 for
   "custom domain already added"). Each such response MUST map to a
   success outcome (return `False` to signal "no change") in the
   helper, not a raised exception.
3. **Soft-fail non-load-bearing failures.** Auxiliary integrations
   (GSC verify/add/submit at Step 9) MUST capture failure in a status
   field and let the main pipeline continue. Re-running picks up where
   the last run stopped.
4. **No destructive irreversible actions on re-run.** Re-running
   `new deploy <domain>` on a fully-completed deploy MUST be safe —
   no record deletion, project re-creation, branch reset, etc.
5. **Default behavior is quick (~30s–2min).** The pipeline reports
   `↷ <state>` for steps that depend on external settlement and tells
   the operator how to recover ("re-run after X minutes"). It does
   NOT block waiting for settlement.

**`--watch` is the opt-in flag** for the "babysit this through to
fully live" use case. It runs after Step 9, polls every 20s for
zone-active + build-success + live-200, exits when all three green
or on a 30-min timeout, and is cleanly Ctrl-C cancellable.

## Consequences

**Positive:**
- Re-running `new deploy` is always safe — composes with operator's
  natural workflow ("run, switch tasks, re-run when ready").
- Default-fast pipeline matches the global `~/.claude/CLAUDE.md`
  vicarious-building output rule (no silent multi-minute blocks).
- Each new step added to the pipeline has a clear contract: "must be
  idempotent" is not negotiable.
- Bug-class eliminated: "deploy failed because state was already
  partially set up" — every state should now be probe-and-skip.
- `--watch` lets operators opt into single-command-confirmation
  without imposing it on the default flow.

**Negative / accepted trade-offs:**
- Implementing each new step requires the extra "probe before act"
  thinking; one-shot POST is not acceptable.
- Some CF errors carry "already exists" semantics in non-obvious
  shapes (HTTP 400 + provider-specific codes); each new such pattern
  needs a targeted catch (see commit `ac3ea52` for the 8000018
  example — `attach_pages_custom_domain` falls back through a 409
  branch AND a `400 + 8000018` branch).
- Documentation overhead: this ADR + the `cli.py` invariant comment
  + the per-project `docs/CLAUDE.md` convention entry.

## Enforcement

To make sure future contributors (including future Claude sessions)
don't accidentally regress this:

1. **In-code marker** — top of `_deploy_cf_unified` in
   `src/portfolio/cli.py` carries a docstring callout referencing
   this ADR.
2. **Per-project convention** — `docs/CLAUDE.md § Locked target
   shapes` lists "deploy idempotency" as a load-bearing invariant
   with a link here.
3. **Code-review heuristic** — for any change in `cli.py` to a step
   inside `_deploy_cf_unified`, ask: "if the operator re-runs this
   exact command immediately, does the second run succeed cleanly
   without modifying state?" If no, the change isn't ready.
4. **Memory** — saved at
   `feedback_quick_idempotent_default_over_blocking_waits.md`
   in the Claude memory store so future sessions pick up the rule
   at conversation start.

## References

- Operator confirmation: 2026-05-23 PM session (chat).
- Triggering bug: commit `ac3ea52` — Step 6 Pages attach didn't
  handle CF's `400 + 8000018` "already added" response on re-runs.
- Implementation: commit `2a007be` — `--watch` flag landed alongside
  the explicit default-quick decision.
- Related ADRs:
  - ADR-0012 (git-integrated CF Pages API deploys) — the pipeline
    this ADR governs.
  - ADR-0014 (multi-method verification + zone-level probe) — both
    sub-systems depend on the same idempotency contract.
- Related global rule: `~/.claude/CLAUDE.md § Output discipline`
  vicarious-building output rule.
