# 0026 — `project delegate` gets a second, provider-pluggable backend: OpenHands/OpenAI takes over when Claude hits the 5-hour cap

- **Status:** Accepted
- **Date:** 2026-06-14
- **Extends:** [0023](0023-delegate-containerized-supervised-agent-run.md)

## Context

ADR-0023 established `project delegate`: open-ended, multi-step site changes
authored by Claude running headless in a sandboxed container, supervised,
verify-gated, ending at an uncommitted diff. v33.O–R then hardened the *single
provider* against its dominant real-world failure — the Claude 5-hour usage cap
— with resume-on-cap, quota self-healing, auto-split, and adaptive splitting.

Those all share one assumption: **the only agent is Claude.** In real use that
assumption is the bottleneck. A large request (e.g. the airsucks.com "enable
TanStack Start prerendering across 8 routes + sitemap" delegate) splits into
sub-tasks, burns the window, caps, and then the operator's only options are
*wait it out* (observed: `~282m` — nearly five hours of dead time) or
*re-run later*. Overage is explicitly off the table (operator constraint). A
half-finished tree sits idle while a perfectly good second provider —
OpenAI — is available and uncapped.

The fix is a **second backend** that takes over on cap. The design question was
which agent to wrap. Building a coding agent in-house was rejected (reinvents
the edit-tool/event-loop/tool-approval machinery that mature OSS already has;
see `docs/coding-agents-survey.md`). Among OSS options, OpenHands was chosen: it
covers the two capabilities a bare OpenAI chat-completions loop misses — a real
structured **edit tool** and a streamed **event log** — which the supervisor and
the honest-diagnosis paths (ADR-0023) depend on. The survey doc captures the
full 12-tool comparison and the license table; it is intentionally generic so
other projects can reuse it.

## Decision

1. **The backend is a seam, and so is the wrapped agent.** `DelegateBackend`
   (ADR-0023's Protocol) already abstracted "how a run is driven." v37 adds a
   second implementation, `OSSAgentBackend`, and *inside it* a second, finer
   seam — `AgentAdapter` — so the wrapped OSS tool is swappable without touching
   the orchestration. `OpenHandsAdapter` is the first adapter; replacing it with
   an aider/mini-swe-agent adapter is a new dataclass, not a rewrite.

2. **Claude-primary, OSS-on-cap, and that is the default.** `--backend` takes
   `auto` (default) | `claude` | `oss`. `auto` runs Claude and hands off to the
   OSS backend the moment a hard cap is hit — **mid-run *or* at pre-flight**
   (the account can already be capped before the sandbox comes up; both paths
   honor the hand-off). The hand-off is *immediate* — no wait. Waiting out the
   cap only happens when no fallback is configured (`--backend claude`).

3. **The OSS backend mirrors ADR-0023's contract, with provider-specific
   plumbing.** Disposable container, streamed events, stderr drain, exit-code
   capture, `last_run_evidence` for honest diagnosis, ends at an uncommitted
   diff. Differences forced by the wrapped tool: runs as **root** (the
   `uv`-installed CLI is root-owned) with a teardown `chown` of `/work` back to
   the host uid:gid; and because OpenHands emits **no result event**, exit 0 is
   converted to a synthetic terminal-OK sentinel so the supervisor sees a clean
   completion.

4. **Honest errors bubble, per-provider.** The adapter owns `diagnose()`
   (OpenAI rate-limit / auth / missing-binary → operator-facing reason); the
   generic no-result diagnosis is the fallback. Same posture as v33.O — never
   a silent empty success.

## Consequences

- **A capped large request now finishes the same sitting** instead of idling
  ~5h. The operator-felt friction that drove this (airsucks delegate, observed
  `~282m left`) is removed by default.
- **Reuses all of v33.O–R.** Resume-on-cap, split, adaptive re-split, and the
  supervisor are provider-agnostic — the OSS backend slots in under them with no
  orchestration changes.
- **Two new external dependencies, both opt-in at hand-off:** an `OPENAI_API_KEY`
  (via `apikeys`) and the `lamill-openhands:latest` image (built from
  `b2b/ai/openhands/Dockerfile`; `uv tool install openhands`, not `pip`, which
  hits a lmnr/openhands-sdk resolution conflict). If either is absent the
  hand-off raises a typed error rather than failing silently.
- **The wrapped agent is a detail, not a commitment.** Swapping OpenHands for a
  future better OSS agent is one new `AgentAdapter`. The survey doc is the
  durable artifact; OpenHands is "for now."
- **Two providers, two cost models.** Claude work is on the subscription; OSS
  fallback work bills OpenAI per-token. The operator opts into that by
  configuring the key — no surprise spend without it.
