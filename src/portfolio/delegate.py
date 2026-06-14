"""v33 — `lamill project delegate <domain> "<request>"`.

Hands a `sites/<domain>/` site a slightly-complicated, multi-step
instruction and lets Claude implement it semi-autonomously — sandboxed in
a container, host-side-supervised, verify-gated, stopping at an uncommitted
reviewable diff. See ADR-0023 + `docs/prd.md § v33`.

This module holds the **container-independent** core (v33.B):

  * preflight — resolve the site dir + refuse on a dirty tree (with a
    clear cause + safe-recovery message);
  * the **two-axis supervisor** — the load-bearing safety piece. Token
    flow proves the run is *alive* (liveness), not that it's *getting
    anywhere* (progress). The supervisor watches both, plus wall-clock +
    budget backstops, and names the exit reason;
  * the stream parser (`claude -p --output-format stream-json` line →
    `StreamEvent`) + prompt assembly.

The container lifecycle + `docker exec` streaming + the verify gate
(v33.C/D) wire on top of this and live elsewhere; they call the
supervisor with real timestamps, real stream events, and a real
working-tree-churn sampler. Everything here is pure and unit-testable.
"""
from __future__ import annotations

import json
import re
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Deque, Iterator, Literal, Protocol

from .fix_helpers import project_context
from .project import SITES_ROOT


# ---------- result + bounds types ----------

# Why the run ended. `done` is the only success terminal; the rest are
# supervisor/backstop kills, each clean-killing the container and leaving
# whatever uncommitted diff exists for operator review.
DelegateStatus = Literal[
    "done",         # agent finished + verify gate clean (or no verify)
    "idle",         # no stream activity for `idle_s` — liveness axis
    "spinning",     # active but no net progress for the window — progress axis
    "timeout",      # wall-clock cap hit
    "budget",       # budget cap hit
    "refused",      # preflight refused (dirty tree, missing site, …) — no run
    "error",        # container/exec failure
    "verify-fail",  # agent ran, but build or `project check` regressed (v33.C)
    "needs-review", # changes look good but visual auto-probe couldn't confirm
                    # (v33.D) — left for the operator to eyeball + confirm
]

# Supervisor kill reasons (the subset of DelegateStatus the supervisor can
# return mid-run; `done`/`refused`/`error` are decided by the caller).
KillReason = Literal["idle", "spinning", "timeout", "budget"]


@dataclass(frozen=True)
class Bounds:
    """Supervision envelope for one delegate run. Defaults are deliberately
    generous (a long reasoning/build burst shouldn't trip them); v33.E tunes
    them from real runs."""
    wall_clock_s: int = 1200      # 20 min hard ceiling
    budget_usd: float = 3.0       # cost cap (mirrors run_claude's, larger)
    idle_s: int = 90              # no stream activity at all → idle
    progress_window_s: int = 210  # ~3.5 min of no net progress → spinning
    min_events_for_spin: int = 4  # need real activity before calling it spin
    novelty_floor: float = 0.5    # ≤ this fraction unique ⇒ repeating itself
    diff_epsilon: int = 0         # net new diff lines that still counts as "no progress"


@dataclass(frozen=True)
class StreamEvent:
    """One parsed line from `claude -p --output-format stream-json`.

    `fingerprint` identifies a tool action as `(tool):(target)` so the
    progress axis can spot repetition (same edit/command over and over).
    `cost_usd` rides on the terminal `result` event."""
    kind: Literal["tool_use", "text", "result", "other", "rate_limit", "error"]
    fingerprint: str | None = None
    cost_usd: float | None = None
    is_error: bool | None = None   # set on the terminal `result` event
    text: str | None = None        # v33.M — agent's final summary (result event)
    # v33.O — debuggability: the terminal `result` carries `api_error_status`,
    # standalone `error` lines carry an error type, and `rate_limit_event`
    # carries the usage-cap state. A silent no-result run is almost always one
    # of these — capture them so the failure can be diagnosed honestly instead
    # of guessed as "sandbox/auth".
    api_error_status: str | None = None   # result.api_error_status / error line
    rate_limit: dict | None = None        # {status, resets_at, overage_status, …}


@dataclass
class VerifyResult:
    """Outcome of the post-run verify gate (v33.C build + `project check`;
    v33.D visual probe). `None` on a field means that link didn't run.

    `visual` degrades gracefully per the operator contract: `pass` only
    when the probe positively confirmed the change renders; `fail` /
    `unavailable` both mean "human, please look" (the run reports
    `needs-review` and does NOT auto-progress)."""
    build_ok: bool | None = None
    build_detail: str = ""
    check_ok: bool | None = None
    check_new_failures: list[str] = field(default_factory=list)
    visual: Literal["pass", "fail", "unavailable", "skipped"] = "skipped"
    visual_detail: str = ""
    screenshot: str | None = None


@dataclass
class DelegateResult:
    """Outcome of one delegate run (the runner fills this; the verify gate
    v33.C/D populates `verify`)."""
    status: DelegateStatus
    reason: str
    cost_usd: float = 0.0
    duration_s: float = 0.0
    changed_files: list[str] = field(default_factory=list)
    message: str = ""
    verify: VerifyResult | None = None
    summary: str = ""               # v33.M — agent's final summary text
    rate_limit: dict | None = None  # v33.P — the last rate_limit_event seen
                                    # (status / resets_at / overage_status), so
                                    # the quota-aware wrapper can wait + retry
    capped_out: bool = False        # v33.R — set True only on a quota give-up
                                    # that signals "too big / not converging"
                                    # (max retries exhausted, or a resumed
                                    # window with no net progress), so the
                                    # splitter knows to re-split this sub-task.


@dataclass
class RunEvidence:
    """v33.O — post-run forensics a backend can expose for honest failure
    diagnosis: the process exit code, a tail of the agent's stderr (the real
    error claude prints there), and the debug-transcript path if one was
    written. Optional capability — `run_delegate` reads it defensively, so a
    backend that doesn't surface it simply yields no extra evidence."""
    exit_code: int | None = None
    stderr_tail: str = ""
    debug_path: str | None = None


def _stderr_tail_for_msg(stderr_tail: str, *, max_lines: int = 6,
                         max_chars: int = 600) -> str:
    """Format a stderr tail for an operator-facing reason line (last few
    lines, bounded). Empty string when there's nothing to show."""
    s = (stderr_tail or "").strip()
    if not s:
        return ""
    text = "\n".join(s.splitlines()[-max_lines:])
    if len(text) > max_chars:
        text = "…" + text[-max_chars:]
    return f" — stderr:\n{text}"


def diagnose_no_result(*, exit_code: int | None, stderr_tail: str,
                       rate_limit: dict | None,
                       api_error: str | None) -> str:
    """Turn whatever evidence a no-result run left behind into an honest
    reason. Ordered by how decisively each signal explains the silence; the
    "sandbox/auth" guess is the LAST resort, used only when nothing else fits
    (per the operator: don't misdiagnose a rate-limit/API error as auth)."""
    # 1. Rate-limit is the most common silent no-result (5h cap exhausted,
    #    org-level overage disabled → claude emits the event and no result).
    if rate_limit:
        status = (rate_limit.get("status") or "").lower()
        overage = (rate_limit.get("overage_status") or "").lower()
        if overage == "rejected" or status in ("exhausted", "rejected",
                                               "blocked", "throttled"):
            bits = ["rate-limited — usage cap reached"]
            if rate_limit.get("resets_at"):
                bits.append(f"resets at {rate_limit['resets_at']}")
            if rate_limit.get("overage_disabled_reason"):
                bits.append(f"overage {rate_limit['overage_disabled_reason']}")
            return "; ".join(bits) + ". Nothing changed."
    # 2. An explicit API error from the stream.
    if api_error:
        return f"API error: {api_error}. Nothing changed."
    # 3. Non-zero exit code (+ whatever stderr explains it).
    if exit_code is not None and exit_code != 0:
        return (f"claude exited {exit_code}{_stderr_tail_for_msg(stderr_tail)}"
                ". Nothing changed.")
    # 4. Exit 0 (or unknown) but stderr has content — surface it.
    if (stderr_tail or "").strip():
        return (f"agent produced no result{_stderr_tail_for_msg(stderr_tail)}"
                ". Nothing changed.")
    # 5. Truly no evidence — the original guess, but flagged as a guess.
    return ("agent produced no result and emitted no error output — possible "
            "sandbox/auth issue (claude may not have started). Re-run with "
            "--debug to capture the full transcript. Nothing changed.")


def _read_backend_evidence(backend: object) -> RunEvidence:
    """Defensively pull `RunEvidence` off a backend that exposes
    `last_run_evidence()`. Backends without it (e.g. test fakes) yield an
    empty evidence record — the diagnoser then falls back to stream-only
    signals."""
    fn = getattr(backend, "last_run_evidence", None)
    if callable(fn):
        try:
            ev = fn()
        except Exception:
            return RunEvidence()
        if isinstance(ev, RunEvidence):
            return ev
    return RunEvidence()


class DelegateRefused(Exception):
    """Preflight refusal — carries the operator-facing message. Never a
    bug; it's the clean 'won't run, here's why + how to fix' path."""


# ---------- preflight ----------


def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    """Run a git command in `cwd`; return (rc, stripped-stdout)."""
    try:
        r = subprocess.run(
            ["git"] + args, cwd=str(cwd), capture_output=True, text=True,
            check=False, timeout=10,
        )
        return r.returncode, r.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return -1, ""


def resolve_site_dir(domain: str, sites_root: Path | None = None) -> Path:
    """Resolve `sites/<domain>/`. Raises DelegateRefused with a clear
    message if it doesn't exist or isn't a git repo (delegate reports its
    result as a diff, so a git repo is required)."""
    root = sites_root or SITES_ROOT
    site_dir = root / domain
    if not site_dir.is_dir():
        raise DelegateRefused(
            f"✗ Won't delegate — no site directory at {site_dir}.\n\n"
            f"  delegate operates on a local sites/<domain>/ checkout.\n"
            f"  Check the domain spelling, or bootstrap/clone it first."
        )
    if not (site_dir / ".git").exists():
        raise DelegateRefused(
            f"✗ Won't delegate — {site_dir} is not a git repository.\n\n"
            f"  delegate hands the working tree to an agent and reports the\n"
            f"  result as a git diff, so the site must be under git.\n"
            f"  Initialize it first:  git -C {site_dir} init"
        )
    return site_dir


def working_tree_dirty(site_dir: Path) -> list[str]:
    """Return `git status --porcelain` lines for `site_dir` (empty ⇒ clean).
    A `-1` git rc (git missing) is treated as 'cannot prove clean' → returns
    a sentinel so the caller refuses rather than risk a muddied diff."""
    rc, out = _git(["status", "--porcelain"], site_dir)
    if rc != 0:
        return ["?? <git status unavailable>"]
    return [ln for ln in out.splitlines() if ln.strip()]


def format_dirty_tree_error(domain: str, site_dir: Path,
                            dirty: list[str]) -> str:
    """The refuse-on-dirty message: cause first, then the dirty files, then
    two safe recoveries with copy-paste commands; `--force` demoted to a
    parenthetical (per the global error-hint rule — lead with safe recovery,
    not bypass)."""
    listing = "\n".join(f"    {ln}" for ln in dirty[:12])
    if len(dirty) > 12:
        listing += f"\n    … and {len(dirty) - 12} more"
    return (
        f"✗ Won't delegate — {site_dir} has uncommitted changes.\n\n"
        f"  delegate hands the working tree to an autonomous agent and\n"
        f"  reports the result as a git diff. With pre-existing changes,\n"
        f"  that diff would blend your edits with the agent's — you couldn't\n"
        f"  tell which is which, and a bad run couldn't be cleanly discarded.\n\n"
        f"  Working tree:\n{listing}\n\n"
        f"  Fix one of these, then re-run:\n"
        f"    • commit your work     git -C {site_dir} commit -am \"wip\"\n"
        f"    • or stash it          git -C {site_dir} stash\n\n"
        f"  (--force runs anyway, but the resulting diff will be muddied —\n"
        f"   not recommended.)"
    )


def preflight(domain: str, *, force: bool = False,
              sites_root: Path | None = None) -> Path:
    """Resolve the site dir and enforce the clean-tree precondition.
    Returns the resolved site dir on success; raises DelegateRefused with an
    operator-facing message otherwise. `force=True` skips the dirty-tree
    gate (but still resolves the dir)."""
    site_dir = resolve_site_dir(domain, sites_root=sites_root)
    if not force:
        dirty = working_tree_dirty(site_dir)
        if dirty:
            raise DelegateRefused(
                format_dirty_tree_error(domain, site_dir, dirty)
            )
    return site_dir


# ---------- stream parsing ----------


def _tool_fingerprint(name: str, tool_input: dict) -> str:
    """Stable `(tool):(target)` fingerprint for a tool_use block. Target is
    the most identifying field available (file path > command > pattern),
    whitespace-normalized so cosmetically-different repeats still collide."""
    target = (
        tool_input.get("file_path")
        or tool_input.get("path")
        or tool_input.get("command")
        or tool_input.get("pattern")
        or ""
    )
    target = " ".join(str(target).split())
    return f"{name.lower()}:{target}".rstrip(":")


def _str_or_none(v: object) -> str | None:
    """Coerce a JSON scalar to a non-empty string, or None."""
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def parse_stream_line(line: str) -> StreamEvent | None:
    """Map one `--output-format stream-json` line to a StreamEvent.
    Returns None for blank/unparseable lines (tolerant by design — a
    malformed line must not crash the supervisor)."""
    line = line.strip()
    if not line:
        return None
    try:
        obj = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(obj, dict):
        return None
    t = obj.get("type")
    if t == "result":
        cost = obj.get("total_cost_usd")
        summary = obj.get("result")
        return StreamEvent("result", None,
                           float(cost) if cost is not None else None,
                           is_error=bool(obj.get("is_error")),
                           text=str(summary) if summary else None,
                           api_error_status=_str_or_none(obj.get("api_error_status")))
    if t == "rate_limit_event":
        info = obj.get("rate_limit_info") or {}
        return StreamEvent("rate_limit", None, None, rate_limit={
            "status": info.get("status"),
            "resets_at": info.get("resetsAt"),
            "overage_status": info.get("overageStatus"),
            "overage_disabled_reason": info.get("overageDisabledReason"),
        })
    if t in ("error", "api_error"):
        # Standalone error line. Shape varies across claude versions, so pull
        # the status/type from the likeliest keys and keep a message tail.
        err = obj.get("error")
        status = (obj.get("api_error_status") or obj.get("status")
                  or (err.get("type") if isinstance(err, dict) else None))
        msg = obj.get("message") or (err if isinstance(err, str) else
                                     (err or {}).get("message") if isinstance(err, dict) else None)
        return StreamEvent("error", None, None,
                           api_error_status=_str_or_none(status),
                           text=_str_or_none(msg))
    if t == "assistant":
        content = (obj.get("message") or {}).get("content") or []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                fp = _tool_fingerprint(
                    str(block.get("name") or "tool"),
                    block.get("input") or {},
                )
                return StreamEvent("tool_use", fp, None)
        return StreamEvent("text", None, None)
    return StreamEvent("other", None, None)


# ---------- the two-axis supervisor ----------


class Supervisor:
    """Decides when an in-flight delegate run must be killed, on two axes:

      * **liveness** — has the stream gone silent for `idle_s`? (`idle`)
      * **progress** — is it active but getting nowhere over the rolling
        `progress_window_s`? (`spinning`)

    plus the dumb backstops `timeout` (wall-clock) and `budget` (cost).

    The caller drives it: each loop iteration calls `tick(now,
    net_diff_lines, event=...)`, where `now` is a monotonic timestamp,
    `net_diff_lines` is the cumulative working-tree diff size (so progress =
    its growth), and `event` is the StreamEvent just observed (or None).
    `tick` returns a KillReason to stop, or None to continue. Pure: no I/O,
    no clock of its own — which is exactly what makes it unit-testable."""

    def __init__(self, bounds: Bounds, *, start: float):
        self.b = bounds
        self.start = start
        self.last_event_at = start
        self.cost_usd = 0.0
        # rolling window of (time, fingerprint) for tool actions
        self._actions: Deque[tuple[float, str]] = deque()
        # rolling window of (time, net_diff_lines) progress samples
        self._diff: Deque[tuple[float, int]] = deque()

    def tick(self, now: float, net_diff_lines: int,
             event: StreamEvent | None = None) -> KillReason | None:
        if event is not None:
            self.last_event_at = now
            if event.cost_usd is not None:
                self.cost_usd = event.cost_usd
            if event.kind == "tool_use" and event.fingerprint:
                self._actions.append((now, event.fingerprint))
        self._diff.append((now, net_diff_lines))
        self._evict(now)

        # backstops first (hard caps), then the two axes.
        if self.cost_usd >= self.b.budget_usd:
            return "budget"
        if now - self.start >= self.b.wall_clock_s:
            return "timeout"
        if now - self.last_event_at >= self.b.idle_s:
            return "idle"
        if self._is_spinning(now):
            return "spinning"
        return None

    def _evict(self, now: float) -> None:
        """Drop samples older than the progress window."""
        cutoff = now - self.b.progress_window_s
        while self._actions and self._actions[0][0] < cutoff:
            self._actions.popleft()
        while len(self._diff) > 1 and self._diff[0][0] < cutoff:
            self._diff.popleft()

    def _is_spinning(self, now: float) -> bool:
        """Active, but no net progress across the window: enough actions,
        ~zero net diff growth, and a high repeat ratio (low novelty)."""
        # Only judge once we've actually been running a full window.
        if now - self.start < self.b.progress_window_s:
            return False
        n = len(self._actions)
        if n < self.b.min_events_for_spin:
            return False  # not enough activity to call it spinning (vs idle)
        growth = self._diff[-1][1] - self._diff[0][1]
        if growth > self.b.diff_epsilon:
            return False  # the tree is still growing → real progress
        unique = len({fp for _, fp in self._actions})
        novelty = unique / n
        return novelty <= self.b.novelty_floor


# ---------- prompt assembly ----------


def docs_listing(site_dir: Path) -> str:
    """v33.G — a cheap MAP of the site's `docs/`: filenames only, never
    contents. The in-container agent has Read/Glob/Grep, so it fetches the
    docs that matter itself; pre-loading the whole tree would pay full token
    cost every run and eat the budget. Returns "" when there's no `docs/`."""
    docs = site_dir / "docs"
    if not docs.is_dir():
        return ""
    names = sorted(
        p.name for p in docs.iterdir()
        if p.is_file() and not p.name.startswith("."))
    if not names:
        return ""
    return "docs/ contains: " + ", ".join(names)


def build_delegate_system_prompt(site_dir: Path) -> str:
    """v33.G — the agent's *system* prompt (passed via `--append-system-
    prompt`): guardrails + site context + a `docs/` map. The operator's
    request is the separate user turn. The build/verify steps run *after*
    the agent, in the verify gate (v33.C/D), so they're described, not
    invoked here."""
    parts = [
        "You are implementing a change in this site's working tree, in place.",
        "Follow the site's existing conventions, structure, and styling.",
        "Make the smallest coherent change that fully satisfies the request.",
        "Do not commit; leave your changes uncommitted for review.",
        # v33.H — relevance-gated doc trail (the agent's half). lamill owns
        # docs/Prompts.md (the run log) and writes it separately, so the agent
        # must not touch it.
        "If this change meaningfully alters what the site does, update "
        "docs/prd.md (behaviour/features); if it alters the site's structure "
        "or conventions, update docs/CLAUDE.md. Skip doc updates for cosmetic "
        "or copy-only changes. Do not edit docs/Prompts.md — lamill maintains "
        "that log.",
    ]
    listing = docs_listing(site_dir)
    if listing:
        parts.append(
            "Before implementing, read AI_AGENTS.md and any relevant files "
            f"under docs/ to understand this site's conventions. {listing}.")
    ctx = project_context(site_dir)
    if ctx:
        parts += ["", "=== SITE CONTEXT ===", ctx]
    return "\n".join(parts)


_PROMPTS_MD_HEADER = """# Prompt History — {domain}

<!-- Append new prompts at the bottom, newest last. Format:

## YYYY-MM-DD [optional title]
> <prompt text or short summary>

The dated H2 (`## YYYY-MM-DD`) is what `portfolio project check` parses
to surface "last AI prompt" per project. Keep entries append-only.
-->
"""


def append_delegate_prompt_log(site_dir: Path, domain: str, request: str, *,
                               files: int, cost: float, today: str) -> bool:
    """v33.H — append a dated delegate entry to `docs/Prompts.md` (creating it
    from the standard skeleton if absent). Orchestrator-owned + deterministic:
    lamill knows the request / date / cost / file-count and the parseable
    `## YYYY-MM-DD` H2 that `project check` reads — not trusted to the agent.
    Returns True if the entry was written."""
    first = next((ln.strip() for ln in request.splitlines() if ln.strip()),
                 "agent change")
    entry = (f"\n## {today} — delegate\n"
             f"> {first[:100].rstrip()} · {files} file(s) · ${cost:.2f}\n")
    prompts = site_dir / "docs" / "Prompts.md"
    try:
        if prompts.exists():
            with prompts.open("a", encoding="utf-8") as fh:
                fh.write(entry)
        else:
            prompts.parent.mkdir(parents=True, exist_ok=True)
            prompts.write_text(
                _PROMPTS_MD_HEADER.format(domain=domain) + entry,
                encoding="utf-8")
        return True
    except OSError:
        return False


# ---------- orchestration ----------

Clock = Callable[[], float]
DiffSampler = Callable[[Path], int]


class DelegateBackend(Protocol):
    """The container seam. `run_delegate` is written against this so it can
    be driven by a fake in tests; `DockerBackend` is the real throwaway-
    container implementation."""

    def start(self, site_dir: Path) -> None:
        """Bring up the sandbox (a fresh, disposable container) with the
        site dir mounted RW + host ~/.claude mounted, and ensure `claude`
        is available inside it."""

    def stream(self, prompt: str,
               system_prompt: str | None = None) -> Iterator[str]:
        """Run the agent and yield raw stream-json lines as they arrive.
        `prompt` is the operator's request (the user turn); `system_prompt`
        (v33.G) carries guardrails + site context via `--append-system-
        prompt`. Yields "" as a heartbeat when no line has arrived within a
        poll interval, so the supervisor can still evaluate idle/timeout
        while the stream is quiet."""

    def kill(self) -> None:
        """Tear the sandbox down. Must be idempotent — `run_delegate` may
        call it on the break path AND in `finally`."""

    def exec(self, shell_cmd: str, *, timeout: int = 600) -> tuple[int, str]:
        """Run a shell command inside the live sandbox as the host user;
        return (returncode, combined-output). Used by the verify gate to
        build / screenshot in-container."""

    # Optional (v33.O). Backends MAY expose post-run forensics so a silent
    # no-result run can be diagnosed honestly. `run_delegate` reads it
    # defensively via `_read_backend_evidence`, so implementing it is not
    # required (test fakes omit it).
    def last_run_evidence(self) -> "RunEvidence":  # pragma: no cover - optional
        """Exit code + stderr tail + debug-transcript path from the last
        `stream()` run."""
        ...


class Verifier(Protocol):
    """The verify-gate seam (v33.C/D). Called once, after a clean agent run
    that changed files, while the container is still alive."""

    def __call__(self, site_dir: Path,
                 backend: DelegateBackend) -> VerifyResult: ...


def working_tree_diff_size(site_dir: Path) -> int:
    """Cumulative working-tree churn: summed added+deleted lines across
    tracked changes, plus the line count of new untracked files. The
    supervisor watches this *grow* — flatness while active is the progress
    signal that catches 'tokens but stuck'."""
    total = 0
    _, numstat = _git(["diff", "--numstat"], site_dir)
    for ln in numstat.splitlines():
        cols = ln.split("\t")
        if len(cols) >= 2:
            a, d = cols[0], cols[1]
            total += (int(a) if a.isdigit() else 0) + (int(d) if d.isdigit() else 0)
    _, untracked = _git(["ls-files", "--others", "--exclude-standard"], site_dir)
    for rel in untracked.splitlines():
        try:
            total += len((site_dir / rel).read_text(errors="replace").splitlines())
        except OSError:
            pass
    return total


def changed_files(site_dir: Path) -> list[str]:
    """`git status --porcelain` → changed path names (rename-aware)."""
    _, out = _git(["status", "--porcelain"], site_dir)
    names: list[str] = []
    for ln in out.splitlines():
        if not ln.strip():
            continue
        # Porcelain: 2-char status, then the path. Strip the status field
        # robustly (don't assume exactly one separating space).
        path = ln[2:].strip()
        if " -> " in path:          # rename: "old -> new" — keep the new name
            path = path.split(" -> ", 1)[1]
        names.append(path)
    return names


def run_delegate(domain: str, request: str, *,
                 backend: DelegateBackend,
                 bounds: Bounds | None = None,
                 force: bool = False,
                 verifier: "Verifier | None" = None,
                 clock: Clock = time.monotonic,
                 diff_sampler: DiffSampler = working_tree_diff_size,
                 on_progress: "Callable[[str, str], None] | None" = None,
                 sites_root: Path | None = None) -> DelegateResult:
    """Orchestrate one delegate run: preflight → start sandbox → supervise
    the agent stream on two axes → clean-kill → report the uncommitted diff.

    `on_progress(kind, detail)` (v33.L) is an optional presentation hook —
    `kind` ∈ {"phase", "action"} — so the caller can surface live progress
    during the otherwise-silent sandbox bringup + agent run. delegate.py
    stays console-free; the CLI renders.

    Never raises for the expected paths: a preflight refusal returns
    `status="refused"` (message carries the operator-facing text); a backend
    failure returns `status="error"`. The container is always torn down."""
    bounds = bounds or Bounds()

    def emit(kind: str, detail: str = "") -> None:
        if on_progress is not None:
            on_progress(kind, detail)
    try:
        site_dir = preflight(domain, force=force, sites_root=sites_root)
    except DelegateRefused as e:
        return DelegateResult(status="refused", reason="preflight",
                              message=str(e))

    system_prompt = build_delegate_system_prompt(site_dir)
    user_prompt = request.strip()
    start = clock()
    sup = Supervisor(bounds, start=start)
    status: DelegateStatus = "done"
    reason = "agent finished within bounds"
    verify: VerifyResult | None = None

    saw_result = False
    result_is_error = False
    summary = ""
    # v33.O — evidence captured off the stream for honest no-result diagnosis.
    last_rate_limit: dict | None = None
    last_api_error: str | None = None
    # v33.L — the sandbox bringup is the silent gap: a `docker run` (first
    # run pulls the image) + the in-container claude install, all before the
    # first stream line. Announce it so the terminal isn't dead.
    emit("phase", "starting sandbox… (first run pulls the image + installs "
                  "claude — up to a minute)")
    backend.start(site_dir)
    emit("phase", "agent starting…")
    try:
        for raw in backend.stream(user_prompt, system_prompt=system_prompt):
            now = clock()
            event = parse_stream_line(raw) if raw else None
            if event is not None and event.kind == "tool_use" and event.fingerprint:
                emit("action", event.fingerprint)
            if event is not None:
                if event.kind == "rate_limit" and event.rate_limit:
                    last_rate_limit = event.rate_limit
                if event.api_error_status:
                    last_api_error = event.api_error_status
            if event is not None and event.kind == "result":
                saw_result = True
                result_is_error = bool(event.is_error)
                if event.text:
                    summary = event.text
            net = diff_sampler(site_dir)
            kill = sup.tick(now, net, event)
            if kill is not None:
                status, reason = kill, _KILL_REASONS[kill]
                break

        # Honesty: stream-EOF is NOT success. Trust the terminal `result`
        # event — no result, or an errored result, must not report `done`. (A
        # supervisor kill already owns the status; only re-judge the natural-
        # end path.) v33.O — on a no-result run, diagnose from real evidence
        # (exit code, stderr tail, last rate-limit / api_error) instead of
        # blindly guessing "sandbox/auth".
        if status == "done":
            if not saw_result:
                evidence = _read_backend_evidence(backend)
                status, reason = "error", diagnose_no_result(
                    exit_code=evidence.exit_code,
                    stderr_tail=evidence.stderr_tail,
                    rate_limit=last_rate_limit,
                    api_error=last_api_error,
                )
            elif result_is_error:
                detail = f" ({last_api_error})" if last_api_error else ""
                status, reason = "error", f"agent reported an error result{detail}"

        # Verify gate (v33.C/D) — only on a clean `done` that actually
        # changed something, while the container is still alive.
        if status == "done" and verifier is not None and changed_files(site_dir):
            emit("phase", "verifying the change (build + checks)…")
            verify = verifier(site_dir, backend)
            if verify.build_ok is False:
                status, reason = ("verify-fail",
                                  "build failed after the change: "
                                  + verify.build_detail[:200])
            elif verify.check_ok is False:
                status, reason = ("verify-fail",
                                  "conformance regressed: "
                                  + ", ".join(verify.check_new_failures))
            elif verify.visual in ("fail", "unavailable"):
                # Operator contract (v33.D): a failed/unavailable visual
                # probe is NOT a hard fail — leave it for the operator to
                # eyeball, and do not auto-progress (no iterate) until they
                # confirm complete.
                status, reason = ("needs-review",
                                  f"visual auto-probe could not confirm "
                                  f"({verify.visual}: {verify.visual_detail[:160]})"
                                  f" — review the change manually before continuing")
    except Exception as e:  # backend / exec failure — never leak a traceback
        status, reason = "error", f"sandbox error: {e}"
    finally:
        try:
            backend.kill()
        except Exception:
            pass

    return DelegateResult(
        status=status,
        reason=reason,
        cost_usd=sup.cost_usd,
        duration_s=clock() - start,
        changed_files=changed_files(site_dir),
        verify=verify,
        summary=summary,
        rate_limit=last_rate_limit,
    )


_KILL_REASONS: dict[str, str] = {
    "idle": "no agent activity for the idle window (stalled)",
    "spinning": "active but no net progress (spinning)",
    "timeout": "wall-clock cap reached",
    "budget": "budget cap reached",
}


# ---------- the real throwaway-container backend ----------


class DockerBackend:
    """Runs the agent inside a **fresh, disposable** container per delegate
    run (never the shared interactive `mb1` — a delegate run kills its
    container on exit, which must not touch the operator's dev session).

    Mounts ONLY `sites/<domain>/` RW + host `~/.claude` for auth (the
    rankmill/threadradar no-API-key pattern). Installs `claude` on start.

    NOTE: requires a working Docker + the builder stack image on the
    operator's machine — exercised end-to-end there, not in unit tests
    (which drive `run_delegate` via a fake backend)."""

    # Where the host's claude auth is mounted inside the container. NOT
    # `/root` — claude refuses `--dangerously-skip-permissions` as root, so
    # the agent runs as the host user with HOME here (see `stream`).
    _HOME = "/cc"

    def __init__(self, domain: str, *, image: str = "node:20-bookworm",
                 docker_cmd: list[str] | None = None,
                 budget_usd: float = 3.0, poll_s: float = 2.0,
                 claude_home: Path | None = None,
                 claude_json: Path | None = None,
                 debug_path: Path | None = None):
        import os
        import threading
        safe = domain.replace(".", "-").replace("/", "-")
        self.container = f"lamill-delegate-{safe}"
        self.image = image
        self.docker = docker_cmd or ["docker"]
        self.budget_usd = budget_usd
        self.poll_s = poll_s
        # v33.O — debuggability state. stderr is drained concurrently into a
        # bounded tail (so a full stderr pipe can't deadlock the stdout loop);
        # the exit code is captured after wait(); `--debug` tees the raw
        # stream-json + stderr + docker argv to a post-mortem transcript.
        self._stderr_tail: Deque[str] = deque(maxlen=400)
        self._exit_code: int | None = None
        self._debug_path = debug_path
        self._debug_fh = None
        self._debug_lock = threading.Lock()
        # Both halves of claude's on-disk state must be mounted: the
        # `~/.claude` directory AND the `~/.claude.json` config file (which
        # holds account/auth). Mounting only the dir leaves claude
        # unconfigured → "config file not found" → it never runs.
        self.claude_home = claude_home or (Path.home() / ".claude")
        self.claude_json = claude_json or (Path.home() / ".claude.json")
        self._uid, self._gid = os.getuid(), os.getgid()
        self._proc: subprocess.Popen | None = None
        self._started = False

    def _run(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(self.docker + args, capture_output=True,
                              text=True, check=False, **kw)

    # ----- v33.O debug transcript (opt-in via --debug / debug_path) -----

    def _open_debug(self) -> None:
        if self._debug_path is None or self._debug_fh is not None:
            return
        try:
            self._debug_fh = open(self._debug_path, "w", encoding="utf-8")
        except OSError:
            self._debug_fh = None     # never let debug I/O break a real run

    def _debug_write(self, channel: str, text: str) -> None:
        if self._debug_path is None:
            return
        with self._debug_lock:
            self._open_debug()
            if self._debug_fh is None:
                return
            try:
                self._debug_fh.write(f"[{channel}] {text}\n")
                self._debug_fh.flush()
            except (OSError, ValueError):
                pass

    def _close_debug(self) -> None:
        with self._debug_lock:
            if self._debug_fh is not None:
                try:
                    self._debug_fh.close()
                finally:
                    self._debug_fh = None

    def last_run_evidence(self) -> "RunEvidence":
        """v33.O — exit code + stderr tail + debug path from the last run."""
        return RunEvidence(
            exit_code=self._exit_code,
            stderr_tail="\n".join(self._stderr_tail),
            debug_path=str(self._debug_path) if self._debug_path else None,
        )

    def start(self, site_dir: Path) -> None:
        self._open_debug()
        # Clean any stale container from a previous interrupted run.
        self._run(["rm", "-f", self.container])
        run_args = [
            "run", "-d", "--name", self.container, "--network=host",
            "-v", f"{site_dir}:/work",
            "-v", f"{self.claude_home}:{self._HOME}/.claude",
            "-v", f"{self.claude_json}:{self._HOME}/.claude.json",
            "-w", "/work", self.image, "tail", "-f", "/dev/null",
        ]
        r = self._run(run_args)
        if r.returncode != 0:
            raise RuntimeError(f"container start failed: {r.stderr.strip()}")
        self._started = True
        # Install claude as root (npm -g needs it); the agent itself runs as
        # the host user (see `stream`). v33.O — capture the install output
        # (was `>/dev/null 2>&1`, swallowing failures) and PROVE claude is on
        # PATH afterward. A failed install used to be invisible → the agent
        # silently no-op'd → misreported as "sandbox/auth failure".
        install = self._run(
            ["exec", self.container, "sh", "-lc",
             "command -v claude >/dev/null 2>&1 && exit 0; "
             "npm i -g @anthropic-ai/claude-code 2>&1"],
            timeout=600)
        present = self._run(["exec", self.container, "sh", "-lc",
                             "command -v claude >/dev/null 2>&1"])
        if present.returncode != 0:
            out = ((install.stdout or "") + (install.stderr or "")).strip()
            self._debug_write("install", out)
            raise RuntimeError(
                "claude CLI is not available in the sandbox after install "
                f"(npm exit {install.returncode}). Install output:\n"
                + (out[-1500:] or "(no output captured)"))

    def _claude_cmd(self, prompt: str,
                    system_prompt: str | None = None) -> list[str]:
        """Assemble the `docker exec … claude -p` argv. Extracted from
        `stream` so the flag wiring (notably v33.G's `--append-system-
        prompt`) is unit-testable without spawning a container."""
        cmd = self.docker + [
            "exec",
            # Run as the host user (mounts are host-owned + claude refuses
            # skip-permissions as root), with HOME pointing at the mounted
            # claude config.
            "--user", f"{self._uid}:{self._gid}",
            "-e", f"HOME={self._HOME}",
            self.container, "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--allowedTools", "Read Write Edit Glob Grep Bash",
            "--dangerously-skip-permissions",   # safe: disposable sandbox
            "--max-budget-usd", str(self.budget_usd),
        ]
        if system_prompt:
            cmd += ["--append-system-prompt", system_prompt]
        return cmd

    def stream(self, prompt: str,
               system_prompt: str | None = None) -> Iterator[str]:
        import select
        import threading
        cmd = self._claude_cmd(prompt, system_prompt)
        self._debug_write("argv", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True,
                                      bufsize=1)
        out, err = self._proc.stdout, self._proc.stderr
        assert out is not None and err is not None

        # Drain stderr on its own thread. claude prints the real failure
        # cause (auth, bad flag, rate-limit) to stderr; if we never read it
        # the pipe buffer can fill and DEADLOCK the stdout loop. The tail is
        # retained for `last_run_evidence` + the debug transcript.
        def _drain_stderr() -> None:
            for line in err:                # blocks per line until EOF
                line = line.rstrip("\n")
                self._stderr_tail.append(line)
                self._debug_write("stderr", line)
        stderr_thread = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_thread.start()

        try:
            while True:
                ready, _, _ = select.select([out], [], [], self.poll_s)
                if ready:
                    line = out.readline()
                    if line == "":     # EOF — agent finished
                        break
                    self._debug_write("stdout", line.rstrip("\n"))
                    yield line
                else:
                    yield ""           # heartbeat — let the supervisor tick
        finally:
            # Capture the exit code (was discarded) so a no-result run can be
            # diagnosed honestly, and flush the stderr drain.
            self._exit_code = self._proc.wait()
            stderr_thread.join(timeout=2.0)
            self._debug_write("meta", f"exit_code={self._exit_code}")

    def exec(self, shell_cmd: str, *, timeout: int = 600) -> tuple[int, str]:
        # Same identity as the agent run: host user + HOME at the mounted
        # claude config, so output written to /work is host-owned (no
        # root-owned node_modules left in the operator's site dir).
        r = self._run(
            ["exec", "--user", f"{self._uid}:{self._gid}",
             "-e", f"HOME={self._HOME}", self.container, "sh", "-lc", shell_cmd],
            timeout=timeout,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        if self._started:
            self._run(["rm", "-f", self.container])
            self._started = False
        self._close_debug()


# ---------- the verify gate (v33.C build + check; v33.D visual) ----------


def run_project_checks(site_dir: Path) -> dict[str, str]:
    """Host-side: run the conformance catalog for one site dir and return
    `{check_id: status}` (pass/warn/fail). Used to take a before/after
    baseline so the verify gate flags only *new* failures. Lazy import keeps
    `delegate` decoupled from the check registry until actually used."""
    try:
        from .checks import list_checks, run_checks
        from .checks.config import load_config
    except ImportError as e:  # pragma: no cover - defensive
        raise RuntimeError(f"check registry unavailable ({e})") from e
    cfg = load_config()
    ids = [s.id for s in list_checks()]
    results = run_checks(str(site_dir), ids=ids, skip_checks=cfg.skip_checks)
    return {cid: r.status for cid, r in results.items()}


def _detect_build(site_dir: Path) -> tuple[str | None, str]:
    """Return (build_shell_cmd, package_manager) or (None, reason) when there
    is nothing to build. Package manager from lockfile; build via the
    project's own `build` script. pnpm/yarn come from corepack (with a
    writable COREPACK_HOME); npm is built in."""
    import json
    pkg_path = site_dir / "package.json"
    if not pkg_path.is_file():
        return None, "no package.json"
    try:
        pkg = json.loads(pkg_path.read_text())
    except (OSError, ValueError):
        return None, "unreadable package.json"
    if "build" not in (pkg.get("scripts") or {}):
        return None, "no build script"
    if (site_dir / "pnpm-lock.yaml").is_file():
        install, build, pm = "corepack pnpm install", "corepack pnpm run build", "pnpm"
    elif (site_dir / "yarn.lock").is_file():
        install, build, pm = "corepack yarn install", "corepack yarn run build", "yarn"
    else:
        install, build, pm = "npm install", "npm run build", "npm"
    env = "export COREPACK_HOME=/tmp/cc-corepack COREPACK_ENABLE_DOWNLOAD_PROMPT=0;"
    return f"{env} {install} && {build}", pm


class DockerVerifier:
    """Verify gate (v33.C/D), run after a clean agent change while the
    container is alive:

      * **build** (v33.C) — the site's own build, in-container, as the host
        user (`make`-equivalent for the stack; never host `pnpm`). A break
        here ⇒ `verify-fail`.
      * **conformance** (v33.C) — host-side `project check`; a check that
        flips pass→fail vs the pre-run baseline ⇒ `verify-fail`.
      * **visual** (v33.D) — best-effort Playwright screenshot + Claude
        judge. Per the operator contract, this NEVER hard-fails the run:
        any failure (no browser, serve error, judge inconclusive) →
        `unavailable` → the run reports `needs-review` and waits for the
        operator's manual eyeball + confirmation (no auto-iterate)."""

    def __init__(self, request: str, *, check_baseline: dict[str, str],
                 check_runner: Callable[[Path], dict[str, str]] = run_project_checks,
                 do_visual: bool = True):
        self.request = request
        self.check_baseline = check_baseline
        self.check_runner = check_runner
        self.do_visual = do_visual

    def __call__(self, site_dir: Path, backend: DelegateBackend) -> VerifyResult:
        vr = VerifyResult()
        # 1) build
        cmd, _info = _detect_build(site_dir)
        if cmd is None:
            vr.build_ok, vr.build_detail = None, f"build skipped ({_info})"
        else:
            rc, out = backend.exec(cmd, timeout=900)
            vr.build_ok = rc == 0
            vr.build_detail = "build OK" if rc == 0 else out[-400:]
            if not vr.build_ok:
                return vr
        # 2) conformance regression (host-side)
        try:
            after = self.check_runner(site_dir)
            new_fail = sorted(
                cid for cid, st in after.items()
                if st == "fail" and self.check_baseline.get(cid) != "fail"
            )
            vr.check_ok, vr.check_new_failures = (not new_fail), new_fail
            if not vr.check_ok:
                return vr
        except Exception as e:  # never let the gate itself crash the run
            vr.check_ok = None
            vr.check_new_failures = []
            vr.build_detail += f" (check skipped: {e})"
        # 3) visual probe — best-effort, degrades to `unavailable`
        if self.do_visual:
            vr.visual, vr.visual_detail, vr.screenshot = self._visual(backend)
        return vr

    def _visual(self, backend: DelegateBackend) -> tuple[str, str, str | None]:
        """Best-effort: screenshot the built output and let Claude judge it.
        Returns (visual, detail, screenshot_path). ANY failure → 'unavailable'
        so the run becomes `needs-review` for a human check (never a hard
        fail). Live browser-install path is heavy and validated by the
        operator on first real use."""
        shot = "/work/.delegate-visual.png"
        probe = (
            "export COREPACK_HOME=/tmp/cc-corepack "
            "COREPACK_ENABLE_DOWNLOAD_PROMPT=0; "
            "test -d dist || { echo NO_DIST; exit 3; }; "
            "npx --yes playwright install chromium >/dev/null 2>&1 || true; "
            "npx --yes http-server dist -p 8765 >/tmp/srv.log 2>&1 & "
            "sleep 2; "
            "npx --yes playwright screenshot --wait-for-timeout=1500 "
            f"http://localhost:8765/ {shot} 2>&1"
        )
        rc, out = backend.exec(probe, timeout=600)
        _, chk = backend.exec(f"test -f {shot} && echo OK || echo MISS")
        if "OK" not in chk:
            return "unavailable", f"could not capture a screenshot: {out[-200:]}", None
        # Claude-as-judge on the screenshot.
        judge = (
            f"export HOME=/cc; claude -p "
            f"\"Look at the screenshot at {shot}. Does the page satisfy this "
            f"request: '{self.request}'? Reply with exactly PASS or FAIL then "
            f"a one-line reason.\" --output-format text "
            f"--allowedTools 'Read' --dangerously-skip-permissions 2>&1"
        )
        jrc, jout = backend.exec(judge, timeout=300)
        verdict = jout.strip().upper()
        if jrc == 0 and verdict.startswith("PASS"):
            return "pass", jout.strip()[:200], shot
        if jrc == 0 and verdict.startswith("FAIL"):
            return "fail", jout.strip()[:200], shot
        return "unavailable", f"judge inconclusive: {jout.strip()[:200]}", shot


# ---------- v33.P — quota-aware, self-healing on the 5-hour cap ----------
#
# delegate dies when the account's 5-hour usage cap is exhausted (claude emits
# a `rate_limit_event` with `status: rejected` + no result). v33.O made that
# *honest*; v33.P makes it *self-healing*: detect the cap (pre-flight or
# mid-run), revert any partial diff, wait out the reset with a live countdown,
# and retry — so the operator never runs the manual
# run→rate-limited→discard→wait→retry loop by hand.
#
# HONESTY (operator contract): quota can be checked to *start*, not to *finish*
# — the 5-hour cap depletes continuously and run cost is unpredictable. So we
# never promise one-shot completion; a mid-run exhaustion reverts + waits +
# retries (bounded), or fails fast under --no-wait.

# Shown in help + every rate-limit failure: the real fix vs the workaround.
OVERAGE_NOTE = (
    "Note: this is the account's hard 5-hour usage cap. The wait/retry is a "
    "workaround — enabling org-level overage billing removes the hard stop "
    "entirely (the real fix)."
)

# Small cushion added to a reported reset time before retrying — the cap can
# lag the advertised `resetsAt` by a few seconds.
_RESET_MARGIN_S = 20
# When the cap is detected but no `resetsAt` is given, fall back to this.
_BLIND_BACKOFF_S = 15 * 60


@dataclass(frozen=True)
class QuotaStatus:
    """Parsed quota state from a `rate_limit_event` (v33.O parses the raw
    dict; this interprets it)."""
    capped: bool
    resets_at: datetime | None = None    # tz-aware UTC
    reason: str | None = None            # e.g. "org_level_disabled"


# rate_limit_info.status values that mean "blocked right now".
_CAPPED_STATUSES = frozenset({"rejected", "exhausted", "blocked", "throttled"})


def parse_resets_at(value: object) -> datetime | None:
    """Parse a `resetsAt` value (ISO-8601 string or epoch seconds) into a
    tz-aware UTC datetime. None/garbage → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    s = str(value).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def quota_from_rate_limit(rate_limit: dict | None) -> QuotaStatus | None:
    """Interpret a captured `rate_limit` dict (StreamEvent.rate_limit /
    DelegateResult.rate_limit). Returns None when there's nothing to act on,
    a `QuotaStatus(capped=…)` otherwise."""
    if not rate_limit:
        return None
    status = (rate_limit.get("status") or "").lower()
    overage = (rate_limit.get("overage_status") or "").lower()
    capped = overage == "rejected" or status in _CAPPED_STATUSES
    if not capped:
        return None
    return QuotaStatus(
        capped=True,
        resets_at=parse_resets_at(rate_limit.get("resets_at")),
        reason=rate_limit.get("overage_disabled_reason") or status or None,
    )


def result_quota(result: DelegateResult) -> QuotaStatus | None:
    """Did this completed run end on a rate-limit? (None ⇒ no.)"""
    return quota_from_rate_limit(result.rate_limit)


def revert_tree(site_dir: Path) -> None:
    """Discard the working-tree changes a (doomed) run left behind so the
    retry starts clean. Scoped to `site_dir`; resets tracked files to HEAD and
    removes untracked files/dirs. Best-effort — a revert failure must not crash
    the loop."""
    _git(["checkout", "--", "."], site_dir)
    _git(["clean", "-fd"], site_dir)


def checkpoint_partial(site_dir: Path, *, label: str) -> str | None:
    """Drop a **recoverable backup** of the current tracked changes into a
    labeled stash entry **without touching the working tree** — `git stash
    create` + `git stash store` — so the operator can recover it later (`git
    stash list` → `git stash apply <ref>`). The tree is left intact (the
    primary resume path is the in-tree partial itself). Returns the `label` on
    success, or None when there's nothing to back up (clean tree, or only
    untracked files — which `git stash create` doesn't capture, but which the
    in-tree resume keeps anyway). Best-effort: any git error yields None rather
    than crashing the self-healing loop."""
    rc, sha = _git(["stash", "create"], site_dir)
    sha = sha.strip()
    if rc != 0 or not sha:
        return None
    _git(["stash", "store", "-m", label, sha], site_dir)
    return label


def format_local(dt: datetime | None) -> str:
    """A reset time in the operator's local zone for messages. UTC-naive
    fallback when the local zone can't be resolved."""
    if dt is None:
        return "an unknown time"
    try:
        return dt.astimezone().strftime("%-I:%M %p %Z").strip()
    except (ValueError, OSError):
        return dt.strftime("%H:%M UTC")


def _wait_for_reset(
    resets_at: datetime | None, *, budget_s: float,
    on_tick: "Callable[[float, datetime | None], None] | None",
    sleep: Callable[[float], None], now_fn: Callable[[], datetime],
) -> bool:
    """Sleep until `resets_at` (+ margin), ticking `on_tick(remaining_s,
    target)` ~once/second so the caller can animate a countdown. Returns True
    on reset reached, False when `budget_s` (the remaining --max-wait) would be
    exceeded first. Propagates KeyboardInterrupt (Ctrl-C) for a clean abort."""
    if resets_at is not None:
        target = resets_at + timedelta(seconds=_RESET_MARGIN_S)
        remaining = (target - now_fn()).total_seconds()
    else:
        # No reset advertised — blind backoff, still bounded by the budget.
        remaining = min(_BLIND_BACKOFF_S, budget_s)
        target = now_fn() + timedelta(seconds=remaining)
    if remaining > budget_s:
        return False
    while True:
        remaining = (target - now_fn()).total_seconds()
        if remaining <= 0:
            return True
        if on_tick is not None:
            on_tick(remaining, target)
        sleep(min(1.0, remaining))


@dataclass
class ResilientConfig:
    """Knobs for the self-healing loop (CLI maps flags onto these)."""
    wait: bool = True             # wait-by-default; --no-wait / non-TTY ⇒ False
    max_wait_s: float = 6 * 3600  # --max-wait (total across all waits)
    max_retries: int = 2          # --max-retries (post-cap re-runs)


def run_delegate_resilient(
    domain: str, request: str, *,
    backend_factory: "Callable[[], DelegateBackend]",
    config: ResilientConfig | None = None,
    bounds: "Bounds | None" = None,
    force: bool = False,
    verifier: "Verifier | None" = None,
    preflight_probe: "Callable[[], QuotaStatus | None] | None" = None,
    on_progress: "Callable[[str, str], None] | None" = None,
    on_wait: "Callable[[float, datetime | None], None] | None" = None,
    sites_root: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    clock: Clock = time.monotonic,
) -> DelegateResult:
    """Quota-aware wrapper around `run_delegate`. Pre-flight-probes the cap
    (when a probe is supplied), then runs — and on a rate-limit (pre-flight or
    mid-run) waits out the reset with a live countdown and retries, bounded by
    `max_wait_s` + `max_retries`.

    **Resume-on-cap:** a rate-limit retry does NOT throw away the agent's
    partial work — it preserves the dirty tree and the retry continues from it
    (`force` past the clean-tree preflight), so a task too big for one quota
    window converges across windows instead of restarting each time. The tree
    is only reverted to clean on the explicit opt-outs: `wait=False`
    (fail-fast) and Ctrl-C (the CLI's abort). Giving up after `max_retries`
    PRESERVES the accumulated progress (re-run to continue).

    Pure orchestration: `sleep`/`now_fn`/`backend_factory`/`preflight_probe`
    are injected, so the whole loop is unit-testable without docker or real
    time. KeyboardInterrupt during a wait propagates (the CLI reverts + reports
    a clean abort)."""
    config = config or ResilientConfig()

    # Resolve the site dir up-front (also enforces the clean-tree precondition
    # for the FIRST run; retries reuse it with `force` to resume the partial).
    try:
        site_dir = preflight(domain, force=force, sites_root=sites_root)
    except DelegateRefused as e:
        return DelegateResult(status="refused", reason="preflight", message=str(e))

    waited_total = 0.0

    def _wait_out(q: QuotaStatus) -> bool:
        """Wait until the reset, ticking the countdown. True = reset reached
        (proceed); False = waiting would exceed --max-wait (bail). Tree-neutral
        — the caller owns checkpoint/revert disposition."""
        nonlocal waited_total
        start = now_fn()
        ok = _wait_for_reset(
            q.resets_at, budget_s=config.max_wait_s - waited_total,
            on_tick=on_wait, sleep=sleep, now_fn=now_fn)
        waited_total += (now_fn() - start).total_seconds()
        if ok and on_progress:
            on_progress("reset", format_local(q.resets_at))   # "✓ quota reset…"
        return ok

    # Pre-flight: don't even bring up the sandbox if we're already capped (the
    # tree is clean here — nothing to checkpoint/revert).
    if preflight_probe is not None:
        try:
            q = preflight_probe()
        except Exception:  # noqa: BLE001 — probe is best-effort
            q = None
        if q and q.capped:
            until = format_local(q.resets_at)
            if not config.wait:
                return DelegateResult(
                    status="error", rate_limit={"resets_at": q.resets_at.isoformat() if q.resets_at else None},
                    reason=(f"rate-limited until {until} — re-run later, or drop "
                            f"--no-wait to wait it out. Nothing changed. "
                            f"{OVERAGE_NOTE}"))
            if on_progress:
                on_progress("phase", "pre-flight: account is rate-limited")
            if not _wait_out(q):
                hrs = config.max_wait_s / 3600
                return DelegateResult(
                    status="error", rate_limit={"resets_at": q.resets_at.isoformat() if q.resets_at else None},
                    reason=(f"rate-limited until {until}, which exceeds "
                            f"--max-wait ({hrs:g}h). {OVERAGE_NOTE}"))

    attempt = 0
    preserved = False
    prev_diff_size = 0           # v33.R — working-tree churn at the last cap
    while True:
        # Resume-on-cap: after a cap we KEEP the agent's partial in the tree, so
        # the retry continues from it (`force` past the clean-tree preflight)
        # instead of restarting. The prompt re-runs as-is — an idempotent
        # request ("make every route SSR + verify") just finishes the rest.
        result = run_delegate(
            domain, request, backend=backend_factory(),
            bounds=bounds, force=force or preserved, verifier=verifier,
            on_progress=on_progress, sites_root=sites_root, clock=clock)
        q = result_quota(result)
        if q is None:
            return result                       # not a cap — done (good or bad)

        until = format_local(q.resets_at)
        files = changed_files(site_dir)
        cur_diff = working_tree_diff_size(site_dir)
        # v33.R — cross-window no-progress: a RESUMED window (attempt > 0) that
        # caps again WITHOUT growing the diff means this sub-task isn't
        # converging (too big to finish in one window, or no incremental
        # checkpoints). Bail early so the splitter can re-split it instead of
        # burning more 5-hour windows.
        no_progress = attempt > 0 and cur_diff <= prev_diff_size
        prev_diff_size = cur_diff
        # Disposition: NEVER hard-discard meaningful progress. Keep the partial
        # in the tree (so the retry — or a manual re-run — resumes from it) +
        # drop a recoverable backup stash. Only hard-revert an EMPTY diff.
        if files:
            stash_label = checkpoint_partial(
                site_dir, label=f"delegate-wip {domain} #{attempt + 1}")
            preserved = True
        else:
            revert_tree(site_dir)
            stash_label = None
            preserved = False

        def _bail(reason_core: str, *, capped_out: bool = False) -> DelegateResult:
            backup = f", backup stash '{stash_label}'" if stash_label else ""
            kept = (f" Partial progress kept in the tree ({len(files)} file(s)"
                    f"{backup}) — re-run with --force to continue from here, or "
                    f"`git -C sites/{domain} checkout -- . && git -C "
                    f"sites/{domain} clean -fd` to discard." if files
                    else " Nothing changed.")
            return DelegateResult(status="error", changed_files=files,
                                  reason=reason_core + kept + f" {OVERAGE_NOTE}",
                                  rate_limit=result.rate_limit, capped_out=capped_out)

        if not config.wait:           # --no-wait / non-TTY opt-out (operator's call)
            return _bail(f"rate-limited until {until} — re-run later, or drop "
                         f"--no-wait to wait it out.")
        if no_progress:               # not converging → signal a re-split
            return _bail(
                f"rate-limited again with NO net progress since the last quota "
                f"window — this sub-task isn't converging (likely too big to "
                f"finish in one window); next reset {until}.", capped_out=True)
        if attempt >= config.max_retries:
            return _bail(f"rate-limited (cap hit {attempt + 1}×, --max-retries "
                         f"reached); next reset {until}.", capped_out=True)

        # Wait out the reset, then RESUME from the in-tree partial.
        if not _wait_out(q):          # --max-wait exceeded
            hrs = config.max_wait_s / 3600
            return _bail(f"rate-limited until {until}, which exceeds --max-wait "
                         f"({hrs:g}h).")
        attempt += 1


def probe_quota_host(
    *, docker_cmd: list[str] | None = None,
    runner: "Callable[[list[str]], subprocess.CompletedProcess] | None" = None,
) -> QuotaStatus | None:
    """Best-effort pre-flight quota probe via a tiny HOST-side `claude -p`
    (the host has claude auth — delegate mounts it into the sandbox). Avoids
    docker bringup entirely. Returns a `QuotaStatus` when a `rate_limit_event`
    shows the cap, None when not capped OR the probe can't run (no claude on
    PATH, timeout, parse miss) — callers treat None as "proceed"."""
    cmd = ["claude", "-p", "ok", "--output-format", "stream-json", "--verbose",
           "--max-budget-usd", "0.05"]

    def _default_runner(c: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(c, capture_output=True, text=True, check=False,
                              timeout=60)
    run = runner or _default_runner
    try:
        proc = run(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    for line in (proc.stdout or "").splitlines():
        ev = parse_stream_line(line)
        if ev is not None and ev.kind == "rate_limit":
            return quota_from_rate_limit(ev.rate_limit)
    return None


# ---------- v33.Q — auto-split a too-big request into sub-tasks ----------
#
# A single huge request ("make all 7 routes SSR + verify each") burns a whole
# quota window and is hard to checkpoint. Auto-split runs a cheap HOST-side
# planner first that decomposes the request into ordered, INDEPENDENT,
# separately-verifiable sub-tasks, then runs each through the resume-on-cap
# loop in turn — accumulating in the working tree. Default-on; `--no-split`
# opts out. The planner degrades to a single task (no split) whenever it's
# unavailable, capped, or returns one item — so a small/atomic request just
# runs once, and a capped account falls through to resume-on-cap's wait.

_PLANNER_PROMPT = (
    "You are planning an autonomous coding task for the website in the local "
    "directory sites/{domain}.\n\n"
    "Break the request below into an ORDERED list of the SMALLEST INDEPENDENT, "
    "separately-verifiable sub-tasks. Each sub-task will be run by a fresh "
    "agent in its own bounded session, so size matters: a sub-task that's too "
    "big to finish in one focused sitting is a failure.\n"
    "Rules:\n"
    "- ERR TOWARD MORE, SMALLER sub-tasks. Each should be completable + "
    "verifiable in well under an hour of focused work. When unsure, split.\n"
    "- If the request ENUMERATES concrete items (routes, pages, files, "
    "components, endpoints), make roughly ONE sub-task PER ITEM — do not lump "
    "them into a single 'do it for all of them' step.\n"
    "- SEPARATE enabling a capability (config / setup / scaffolding) from "
    "making each item actually satisfy it. E.g. 'turn on prerendering in the "
    "config' is one sub-task; 'confirm route /X renders non-empty HTML, fixing "
    "its loader/data if needed' is one sub-task PER route.\n"
    "- Each sub-task is self-contained and independently verifiable (it builds "
    "and has a concrete check).\n"
    "- Phrase each IDEMPOTENTLY — describe the END STATE, never \"continue\" / "
    "\"next\"; a fresh agent must be able to run it against a partially-done "
    "tree and do only what's missing.\n"
    "- Carry over any explicit verification the user asked for into each "
    "sub-task it applies to.\n"
    "- If the request is genuinely small / atomic, return it as a SINGLE "
    "item.\n"
    "- Never return more than {max_subtasks} items.\n\n"
    "Return ONLY a JSON array of strings (the sub-task prompts) and nothing "
    "else.\n\nRequest:\n{request}"
)


def _parse_subtask_json(text: str) -> list[str]:
    """Pull the first JSON array-of-strings out of the planner's reply
    (tolerant of surrounding prose / code fences). Returns [] on any miss."""
    m = re.search(r"\[.*\]", text or "", re.DOTALL)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except (json.JSONDecodeError, ValueError):
        return []
    if not isinstance(arr, list):
        return []
    return [str(x).strip() for x in arr if isinstance(x, str) and str(x).strip()]


def plan_subtasks(
    domain: str, request: str, *,
    runner: "Callable[[list[str]], subprocess.CompletedProcess] | None" = None,
    max_subtasks: int = 8,
) -> list[str]:
    """Host-side planner: decompose `request` into ordered independent,
    separately-verifiable sub-tasks. Returns `[request]` unchanged when the
    task is atomic, the planner is unavailable / capped, or the output doesn't
    parse — so auto-split always degrades safely to a single run. `runner` is
    injectable for tests."""
    prompt = _PLANNER_PROMPT.format(
        domain=domain, request=request.strip(), max_subtasks=max_subtasks)
    cmd = ["claude", "-p", prompt, "--output-format", "text",
           "--max-budget-usd", "0.15"]

    def _default_runner(c: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(c, capture_output=True, text=True, check=False,
                              timeout=120)
    run = runner or _default_runner
    try:
        proc = run(cmd)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return [request]
    tasks = _parse_subtask_json(proc.stdout or "")
    if len(tasks) <= 1:
        return [request]
    return tasks[:max_subtasks]


@dataclass
class SplitResult:
    """Outcome of an auto-split delegate run: the plan + one DelegateResult per
    ATTEMPTED sub-task (fewer than `subtasks` when the chain stopped early on a
    non-`done` sub-task)."""
    subtasks: list[str]
    outcomes: list["DelegateResult"] = field(default_factory=list)

    @property
    def was_split(self) -> bool:
        return len(self.subtasks) > 1

    @property
    def all_done(self) -> bool:
        return (len(self.outcomes) == len(self.subtasks)
                and all(o.status == "done" for o in self.outcomes))

    @property
    def final(self) -> "DelegateResult | None":
        return self.outcomes[-1] if self.outcomes else None


def run_delegate_split(
    domain: str, request: str, *,
    backend_factory: "Callable[[], DelegateBackend]",
    make_verifier: "Callable[[str], Verifier | None] | None" = None,
    config: ResilientConfig | None = None,
    bounds: "Bounds | None" = None,
    force: bool = False,
    planner: "Callable[[str, str], list[str]] | None" = None,
    preflight_probe: "Callable[[], QuotaStatus | None] | None" = None,
    on_progress: "Callable[[str, str], None] | None" = None,
    on_wait: "Callable[[float, datetime | None], None] | None" = None,
    on_subtask: "Callable[[int, int, str], None] | None" = None,
    sites_root: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    clock: Clock = time.monotonic,
    max_resplit_depth: int = 1,
) -> SplitResult:
    """Plan the request into sub-tasks, then run each through
    `run_delegate_resilient` in order, **accumulating in the working tree**
    (sub-task 2+ run with `force` to start from the prior sub-tasks' work).

    **Adaptive re-split (v33.R):** when a sub-task *caps out* — gives up on the
    5-hour cap still not converging (`DelegateResult.capped_out`, set by the
    resilient loop's max-retries / no-net-progress bails) — it's too big, so
    (up to `max_resplit_depth` levels) we re-plan THAT sub-task into smaller
    pieces and run those in its place, rather than failing the chain. Any
    OTHER non-`done` (verify-fail, real error) stops the chain — the completed
    work stays in the tree for review / re-run.

    A single-item plan (atomic request, or planner unavailable) runs exactly
    like a lone `run_delegate_resilient`. Pure orchestration over injected
    `planner`/`sleep`/`now_fn`/`backend_factory`, so it's unit-testable without
    docker, the network, or real time."""
    plan_fn = planner or plan_subtasks
    plan = plan_fn(domain, request)
    # Work queue of (sub-task, resplit-depth). Re-split pieces are pushed to the
    # FRONT so a too-big sub-task is broken down before the chain moves on.
    queue: list[tuple[str, int]] = [(s, 0) for s in plan]
    attempted: list[str] = []
    outcomes: list[DelegateResult] = []
    while queue:
        sub, depth = queue.pop(0)
        i = len(attempted)
        if on_subtask is not None:
            on_subtask(i, i + 1 + len(queue), sub)   # best-effort running total
        res = run_delegate_resilient(
            domain, sub, backend_factory=backend_factory, config=config,
            # force past the clean-tree preflight for any sub-task that starts
            # from accumulated work: a later sub-task (i>0) OR a re-split piece
            # (depth>0, where the capped-out parent's partial is in the tree).
            bounds=bounds, force=force or i > 0 or depth > 0,
            verifier=make_verifier(sub) if make_verifier else None,
            # Quota pre-flight only before the very first sub-task; mid-chain
            # caps are caught + resumed by the resilient loop itself.
            preflight_probe=preflight_probe if i == 0 else None,
            on_progress=on_progress, on_wait=on_wait, sites_root=sites_root,
            sleep=sleep, now_fn=now_fn, clock=clock)

        if res.status != "done" and res.capped_out and depth < max_resplit_depth:
            pieces = plan_fn(domain, sub)
            if len(pieces) > 1:
                if on_progress is not None:
                    on_progress("phase", f"sub-task too big — re-split into "
                                          f"{len(pieces)} smaller steps")
                queue[:0] = [(p, depth + 1) for p in pieces]
                continue                # don't record the capped-out attempt
        attempted.append(sub)
        outcomes.append(res)
        if res.status != "done":
            break                       # genuine non-done → stop the chain
    return SplitResult(subtasks=attempted, outcomes=outcomes)
