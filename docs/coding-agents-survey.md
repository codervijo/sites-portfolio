# OSS coding-agent survey — choosing a `project delegate` wrapper (v37.A)

**Date:** 2026-06-13 · **Status:** point-in-time snapshot (the landscape moves
fast — re-verify flags/health before relying on any row). **Doc/repo-verified,
NOT runtime-validated** (see § Validation caveat).

## Why this exists

`project delegate` runs the `claude` CLI in a sandbox; that draws the operator's
Anthropic 5-hour cap (overage declined). **v37** adds a *provider-pluggable
fallback backend* behind the `DelegateBackend` Protocol seam — **wrap a mature
OSS coding agent, don't hand-build one** (it would reimplement repo-map
navigation / edit application / context compaction that these tools already
solved). This survey picks the wrapper for v37.A.

## Decision (2026-06-13): OpenHands, behind a *pluggable* adapter

Picked **OpenHands** as the v37 fallback agent. Among the OSI-permissive,
headless, container-friendly options that respect the operator's **"no codex"**
constraint, OpenHands covers the most of our six "misses" *natively* — a real
`str_replace` edit tool (#2) + a live JSONL event stream + exit codes (#6) that
mini-swe-agent lacks (see § Coverage of the six misses) — while leaving an
uncommitted diff and reaching any model via LiteLLM.

**Designed to be swappable (operator requirement).** The landscape moves fast
and Codex CLI is the technical winner we may revisit, so v37.B wraps OpenHands
behind a small **agent-adapter** layer — `(install cmd · headless argv builder ·
output→StreamEvent parser · error/exit mapping)` — NOT a monolithic
OpenHands-specific backend. Swapping OpenHands for mini-swe-agent / Codex /
a future tool = writing a new adapter, not a rewrite. **Revisit triggers:** the
operator reverses "no codex" (→ Codex adapter, cleanest technical fit); OpenHands'
weight or git-footgun bites in practice (→ mini-swe-agent adapter for
minimalism); or a stronger 2026 entrant appears. The adapter seam is the marker
to "get back to it later."

## Selection criteria (what the pick hinges on)

We wrap one agent as a **headless backend in a disposable container**: one
bounded task per non-interactive run → leave an **uncommitted working-tree diff**
for our verify gate to review. So:

1. **Headless / scriptable** — one CLI command / `--message` → run → exit, no TUI, no prompts.
2. **Multi-model** — OpenAI *and* others (Anthropic / OpenRouter / local), settable per-run.
3. **Edit quality + repo-map** — surgical diff/exact-match edits (not whole-file clobber) + codebase navigation.
4. **Git behavior** — leaves changes **UNCOMMITTED** (or auto-commit configurable off). We need a reviewable dirty tree, not auto-commits.
5. **Container friendliness** — pip/npm/binary install, headless Linux, key via env, **no Docker-in-Docker / no server+DB**.
6. **Structured output + exit codes** — parseable streaming (JSON events) + clear exit signals, so the wrapper maps events and **bubbles failures honestly** (v37.B). *This + #5 were the real discriminators.*
7. **Maintenance / health** — actively maintained in 2026.

## Comparison

| Tool | Headless 1-shot | Multi-model | Surgical edits + map | Uncommitted diff | Container (no DinD) | Structured output + exit codes | Maintained 2026 | License |
|---|---|---|---|---|---|---|---|---|
| **Codex CLI** | ✓ `codex exec --json` | ✓ | ✓ | ✓ default | ✓ binary (bypass sandbox) | ✓✓ JSONL + `--output-schema` | ✓✓ ~91k★ | Apache-2.0 |
| **OpenHands** | ✓ `--headless --json -t` | ✓ LiteLLM | ✓ | ✓ | ✓ `RUNTIME=process` | ✓✓ JSONL + exit 0/1/2 | ✓✓ ~77k★ | MIT |
| **Cline** | ✓ `--yolo --json` | ✓ | ✓ | ✓ (shadow-git) | ✓ binaries (+git) | ✓✓ NDJSON + exit 0/1 | ✓✓ ~63k★ | Apache-2.0 |
| **mini-swe-agent** | ✓ `-y` | ✓ litellm | ✓ patch | ✓✓ by design | ✓✓ Docker optional | partial (`.traj.json`) | ✓ ~5k★ | MIT |
| **aider** | ✓ `-f … --yes-always --no-auto-commits` | ✓ | ✓✓ repo-map | ✓ `--no-auto-commits` | ✓✓ pip | ✗ none | ✓ ~46k★ | Apache-2.0 |
| **Goose** | ✓ `run -t` | ✓ | ✓ | ✓ | ✓ (set `GOOSE_MODE=auto`) | ✓ json; exit codes ? | ✓✓ ~49k★ | Apache-2.0 |
| **opencode** | ✓ `run --format json` | ✓ | ✓ LSP | ⚠ auto-commit bug | ~ Node/Bun | ✓✓ JSONL | ✓✓ ~174k★ | MIT |
| **Continue** | ✓ `cn -p` | ✓ | partial | ✓ (gate shell) | ✓ Node | partial (undoc) | ✓ ~34k★ | Apache-2.0 |
| **gptme** | ✓ `--non-interactive` | ✓ | ✓ patch | ✓ | ✓ image | ✓ JSONL | ~ solo maint. | MIT |
| **Plandex** | partial (server) | ✓ | ✓ | ⚠ `--skip-commit` | ✗ server + Postgres | ✗ | ⚠ stalled (Oct 2025) | MIT |
| **SWE-agent** | ✓ | ✓ | ✓✓ ACI | ✓✓ patch | ⚠ Docker/instance | ✓ traj/preds | ✗ **deprecated** | MIT |
| **RA.Aid** | ✓ `--cowboy-mode` | ✓ | partial | ✓ | ✓ pip | ✗ | ✗ dormant | Apache-2.0 |

## Per-tool notes (decision-relevant)

- **Codex CLI** — OpenAI's OSS Rust agent; *multi-model despite the name* (custom `model_provider` → Anthropic/OpenRouter/Azure/Ollama). `codex exec "task" --json` (JSONL `thread.*`/`turn.*`/`item.*` events, `--output-schema`, `--output-last-message`); uncommitted by default (needs a git repo, `--skip-git-repo-check` to override). **Container wrinkle:** built-in Landlock/seccomp sandbox conflicts with container kernels → `--dangerously-bypass-approvals-and-sandbox`, let the container be the boundary.
- **OpenHands** — `openhands --headless --json -t "task"`; LiteLLM (100+ models). **2026 change:** `RUNTIME=process` removes the Docker-in-Docker requirement (CI-targeted; zero isolation in that mode → lean on the container). Gotchas: pass `--override-with-envs` (else ignores `LLM_MODEL`); the agent has bash and will commit if the task mentions git.
- **Cline** — was a VS Code extension; 2026 standalone headless CLI runs without VS Code/Electron at runtime. `cline --yolo --json "task"`; NDJSON + exit 0/1; checkpoints go to a *separate shadow git repo* (needs `git`); `CLINE_SANDBOX=1`, `--data-dir`.
- **mini-swe-agent** — the SWE-agent authors' official ~100-line successor; `-y`/`--exit-immediately`; **patch-not-commit by design** (dirty tree + `.traj.json`); Docker optional (local/docker/podman/bubblewrap); pip/uvx-thin. Best "purpose-built shape," weakest on streaming output.
- **aider** — `aider --message-file task.txt --yes-always --no-auto-commits <files>` (`--yes-always`, not the stale `--yes`; `--no-auto-commits`, not `--no-git`). Signature strength: `diff` edits + graph-ranked repo-map. **Signature weakness for us: no JSON, no event stream, undocumented run exit codes** → forces before/after `git diff` heuristics. Numbered release lags `main` (pin a commit for current models).
- **Goose** (Block, Rust, MCP) — `goose run --no-session -q -t "task"`; must set `GOOSE_MODE=auto` (else hangs on approval) + `GOOSE_DISABLE_KEYRING=1` in Docker; `--output-format json|stream-json` but **exit codes unpublished — verify**.
- **opencode** — huge momentum + clean JSONL, but **open 2026 issues (#786, #3239) report it auto-committing/pushing** despite intending uncommitted → the exact behavior we're avoiding; guard with a throwaway branch.
- **Continue** — repositioned around a headless `cn -p` CLI; `--format json` exists but **schema + exit codes undocumented**; edit surgicality unverified.
- **gptme** — `gptme --non-interactive "task"`; `patch` tool surgical; `--output-format json`; official `ghcr.io/gptme/gptme` image; single-maintainer concentration.
- **Plandex** — **client-server requiring a backend server + PostgreSQL** (no in-process mode) → disqualifying for ephemeral containers; auto-commit on by default (`--skip-commit`); stalled since Oct 2025.
- **SWE-agent** — strong ACI (windowed viewer, lint-checked edits), patch-only (doesn't touch your tree), but **officially maintenance-only; authors recommend mini-swe-agent instead** + mandatory Docker-per-instance.
- **RA.Aid** — research→plan→implement on LangGraph; native edit mechanism undocumented (surgical only via opt-in `--use-aider`); **no JSON, dormant since mid-2025.**

### Disqualified / out of scope
- **Claude Code** — `-p/--print` is the most batch-ready flag of all, but **proprietary** (no OSI license). (It's already our *primary* backend.)
- **Gemini CLI** — Apache-2.0 but Gemini-locked + consumer tier sunsets 2026-06-18 (→ Antigravity CLI). **Qwen Code** (Gemini-CLI fork, Apache-2.0, `-p` headless, BYO-key) is the viable fork.
- **Charm Crush** — single Go binary but FSL-1.1 (source-available, not OSI) + no JSON. **Amp** (proprietary hosted), **Cody** (archived Aug 2025), **Tabby** (completion daemon, not an agent).

## Licenses

We *wrap* (install + invoke the tool as a subprocess) rather than vendor/fork
its source, so license obligations are light either way — but for a dependency
we run in production, OSI-permissive matters. **Takeaway: every real contender
is OSI-permissive (MIT or Apache-2.0)** — license is *not* a discriminator among
the survey candidates. The only non-OSI entries sit in the disqualified bucket.

| Tool | License (SPDX) | OSI? | Type | Note |
|---|---|---|---|---|
| Codex CLI | `Apache-2.0` | ✓ | permissive (+ explicit patent grant) | — |
| OpenHands | `MIT` | ✓ | permissive | — |
| Cline | `Apache-2.0` | ✓ | permissive | — |
| mini-swe-agent | `MIT` | ✓ | permissive | — |
| aider | `Apache-2.0` | ✓ | permissive | — |
| Goose | `Apache-2.0` | ✓ | permissive | — |
| opencode | `MIT` | ✓ | permissive | — |
| Continue | `Apache-2.0` | ✓ | permissive | — |
| gptme | `MIT` | ✓ | permissive | — |
| Plandex | `MIT` | ✓ | permissive | code MIT, but server+Postgres arch is the real blocker |
| SWE-agent | `MIT` | ✓ | permissive | deprecated (not a license issue) |
| RA.Aid | `Apache-2.0` | ✓ | permissive | dormant (not a license issue) |
| Qwen Code | `Apache-2.0` | ✓ | permissive | Gemini-CLI fork |
| Gemini CLI | `Apache-2.0` | ✓ | permissive | OSI fine, but Gemini-model-locked |
| Charm Crush | `FSL-1.1-MIT` | ✗ | source-available (→ `MIT` after 2 yrs) | usage restrictions; fine for internal wrap, but not OSI |
| Cody (Sourcegraph) | `Apache-2.0` | ✓ | permissive | repo **archived** Aug 2025 — dead |
| Claude Code | proprietary | ✗ | commercial ToS | no source license (our existing *primary* backend) |
| Amp | proprietary | ✗ | hosted/commercial | — |

*Apache-2.0 vs MIT for our case: both permissive; Apache-2.0 adds an explicit
patent grant + a `NOTICE` requirement. Since we invoke the tool rather than
redistribute its code, neither imposes meaningful obligations — pick on the
other criteria, not the license.* (Licenses per the survey's repo checks,
2026-06-13; re-verify before relying — projects do relicense.)

## Recommendation

For *"wrap headless in a container, one bounded task per run, uncommitted diff,
multi-model, parseable output for honest error-bubbling":*

- **Technical winner: Codex CLI** — only tool that hits all 7 cleanly (JSONL +
  schema, uncommitted default, multi-model, single binary, top momentum).
  **However the operator ruled out codex earlier** (in the build-vs-codex
  framing); pending reconsideration now that we're *wrapping*, not building.
- **Best non-codex pick: OpenHands** — JSONL + documented exit codes 0/1/2,
  LiteLLM multi-model, `RUNTIME=process` removes the DinD dealbreaker.
- **Minimalist dark-horse: mini-swe-agent** — patch-not-commit by design,
  Docker-optional, pip-thin; weaker on streaming output.

**The "aider is obvious" assumption is wrong** for our needs: its lack of
structured output / exit codes directly undermines v37.B's honest-error-bubbling
— the single requirement we cared most about. Every Tier-1 alternative gives
JSONL + exit codes.

## Coverage of the six Claude-Code "misses"

Earlier (v40/v37 design) we listed six capabilities the `claude` CLI gives that
a raw model loop lacks: (1) context compaction, (2) mature edit semantics,
(3) repo-map/navigation, (4) judgment & safety, (5) tool-error self-correction,
(6) structured events. How the finalists cover them *natively* (per documented
design — verify in the smoke test):

| Miss | OpenHands | mini-swe-agent | aider | Codex CLI |
|---|---|---|---|---|
| 1. Context compaction | partial (1.0 SDK loop) | ✗ minimal/linear | partial | ✓ mature |
| 2. Edit semantics | ✓ `str_replace` tool | ✗ bash-only (`sed`/`python`) | ✓✓ `diff` edits | ✓ surgical |
| 3. Repo-map / navigation | partial (nav tools) | ✗ bash-explore | ✓✓ repo-map | ✓ |
| 4. Judgment & safety | ✗ native* | ✗ native* | ✗ native* | ✗ native* |
| 5. Tool-error self-correction | ✓ | ✓ (output fed back) | ✓ | ✓ |
| 6. Structured events | ✓ JSONL + exit 0/1/2 | ~ `.traj.json` file | ✗ none | ✓✓ JSONL + schema |

\* #4 is **irreducible for every agent** — covered the same way for all: our
container sandbox + verify gate + reviewable-diff-never-auto-commit. No agent
"has judgment"; the harness substitutes structure.

**mini-swe-agent, standalone ("is it enough if we had neither codex nor
claude?"):** it covers only **#5** natively. #1 leans on our v33.R splitting
(small bounded tasks don't overflow), #4 on our harness, #3 partly on our
context-priming — but **#2 (no edit tool) and #3 (no repo-map) are genuinely
un-filled**, leaving the raw model to edit + navigate via shell. Workable for
bounded, split sub-tasks with a strong model; it's the *floor* of viable, not a
Claude-Code-equivalent.

**Why OpenHands over mini-swe-agent:** the two misses mini can't fill — **#2**
(dedicated edit tool) and **#6** (live event stream + exit codes, which feed our
honest error-bubbling) — are exactly the two OpenHands provides itself. That's
the whole trade: mini is simpler but covers fewer misses natively; OpenHands is
heavier but fills #2 and #6. With "no codex" in force, OpenHands is the best
native coverage available.

## Validation caveat (per the operator's "verify in real use" rule)

All of the above is **doc/repo-verified, not runtime-validated**. Before
committing to a wrapper, **smoke-test the chosen tool's exact invocation in a
throwaway container** to confirm the two requirements most likely to bite:
1. it leaves the host-mounted working tree **dirty (not committed/pushed)**, and
2. its JSON/event schema matches what our error-bubbling parser will expect.

## References

Official repos / docs consulted (canonical sources; verify current state):
- aider — `github.com/Aider-AI/aider`, `aider.chat/docs`
- OpenAI Codex CLI — `github.com/openai/codex`
- OpenHands — `github.com/All-Hands-AI/OpenHands`, `docs.all-hands.dev`
- mini-swe-agent — `github.com/SWE-agent/mini-swe-agent`
- SWE-agent — `github.com/SWE-agent/SWE-agent`
- Cline — `github.com/cline/cline`
- Goose — `github.com/block/goose`
- opencode — `github.com/sst/opencode`
- Continue — `github.com/continuedev/continue`
- gptme — `github.com/gptme/gptme`
- Plandex — `github.com/plandex-ai/plandex`
- RA.Aid — `github.com/ai-christianson/RA.Aid`
- Qwen Code — `github.com/QwenLM/qwen-code`

Survey performed 2026-06-13 by a web-research subagent cross-checking the above;
synthesized for the v37.A wrapper decision.
