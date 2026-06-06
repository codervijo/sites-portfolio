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
import subprocess
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Iterator, Literal, Protocol

from .fix_helpers import project_context
from .project import SITES_ROOT


# ---------- result + bounds types ----------

# Why the run ended. `done` is the only success terminal; the rest are
# supervisor/backstop kills, each clean-killing the container and leaving
# whatever uncommitted diff exists for operator review.
DelegateStatus = Literal[
    "done",       # agent finished on its own within bounds
    "idle",       # no stream activity for `idle_s` — liveness axis
    "spinning",   # active but no net progress for the window — progress axis
    "timeout",    # wall-clock cap hit
    "budget",     # budget cap hit
    "refused",    # preflight refused (dirty tree, missing site, …) — no run
    "error",      # container/exec failure
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
    kind: Literal["tool_use", "text", "result", "other"]
    fingerprint: str | None = None
    cost_usd: float | None = None


@dataclass
class DelegateResult:
    """Outcome of one delegate run (the runner fills this; verify phases
    v33.C/D extend it)."""
    status: DelegateStatus
    reason: str
    cost_usd: float = 0.0
    duration_s: float = 0.0
    changed_files: list[str] = field(default_factory=list)
    message: str = ""


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
        return StreamEvent("result", None,
                           float(cost) if cost is not None else None)
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


def build_delegate_prompt(site_dir: Path, request: str) -> str:
    """Assemble the agent prompt: the operator's request + brief site
    context (AI_AGENTS.md + package.json) so Claude inherits the site's
    conventions. The build/verify steps run *after* the agent, in the
    verify gate (v33.C/D), so they're described, not invoked here."""
    ctx = project_context(site_dir)
    parts = [
        "You are implementing a change in this site's working tree, in place.",
        "Follow the site's existing conventions, structure, and styling.",
        "Make the smallest coherent change that fully satisfies the request.",
        "Do not commit; leave your changes uncommitted for review.",
        "",
        "=== REQUEST ===",
        request.strip(),
    ]
    if ctx:
        parts += ["", "=== SITE CONTEXT ===", ctx]
    return "\n".join(parts)


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

    def stream(self, prompt: str) -> Iterator[str]:
        """Run the agent and yield raw stream-json lines as they arrive.
        Yields "" as a heartbeat when no line has arrived within a poll
        interval, so the supervisor can still evaluate idle/timeout while
        the stream is quiet."""

    def kill(self) -> None:
        """Tear the sandbox down. Must be idempotent — `run_delegate` may
        call it on the break path AND in `finally`."""


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
        path = ln[3:]
        if " -> " in path:          # rename: "old -> new" — keep the new name
            path = path.split(" -> ", 1)[1]
        names.append(path)
    return names


def run_delegate(domain: str, request: str, *,
                 backend: DelegateBackend,
                 bounds: Bounds | None = None,
                 force: bool = False,
                 clock: Clock = time.monotonic,
                 diff_sampler: DiffSampler = working_tree_diff_size,
                 sites_root: Path | None = None) -> DelegateResult:
    """Orchestrate one delegate run: preflight → start sandbox → supervise
    the agent stream on two axes → clean-kill → report the uncommitted diff.

    Never raises for the expected paths: a preflight refusal returns
    `status="refused"` (message carries the operator-facing text); a backend
    failure returns `status="error"`. The container is always torn down."""
    bounds = bounds or Bounds()
    try:
        site_dir = preflight(domain, force=force, sites_root=sites_root)
    except DelegateRefused as e:
        return DelegateResult(status="refused", reason="preflight",
                              message=str(e))

    prompt = build_delegate_prompt(site_dir, request)
    start = clock()
    sup = Supervisor(bounds, start=start)
    status: DelegateStatus = "done"
    reason = "agent finished within bounds"

    backend.start(site_dir)
    try:
        for raw in backend.stream(prompt):
            now = clock()
            event = parse_stream_line(raw) if raw else None
            net = diff_sampler(site_dir)
            kill = sup.tick(now, net, event)
            if kill is not None:
                status, reason = kill, _KILL_REASONS[kill]
                break
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

    def __init__(self, domain: str, *, image: str = "node:20-bookworm",
                 docker_cmd: list[str] | None = None,
                 budget_usd: float = 3.0, poll_s: float = 2.0,
                 claude_home: Path | None = None):
        safe = domain.replace(".", "-").replace("/", "-")
        self.container = f"lamill-delegate-{safe}"
        self.image = image
        self.docker = docker_cmd or ["docker"]
        self.budget_usd = budget_usd
        self.poll_s = poll_s
        self.claude_home = claude_home or (Path.home() / ".claude")
        self._proc: subprocess.Popen | None = None
        self._started = False

    def _run(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(self.docker + args, capture_output=True,
                              text=True, check=False, **kw)

    def start(self, site_dir: Path) -> None:
        # Clean any stale container from a previous interrupted run.
        self._run(["rm", "-f", self.container])
        run_args = [
            "run", "-d", "--name", self.container, "--network=host",
            "-v", f"{site_dir}:/work",
            "-v", f"{self.claude_home}:/root/.claude",
            "-w", "/work", self.image, "tail", "-f", "/dev/null",
        ]
        r = self._run(run_args)
        if r.returncode != 0:
            raise RuntimeError(f"container start failed: {r.stderr.strip()}")
        self._started = True
        # Ensure claude is available inside the sandbox (install-on-start).
        self._run(["exec", self.container, "sh", "-lc",
                   "command -v claude >/dev/null 2>&1 || "
                   "npm i -g @anthropic-ai/claude-code >/dev/null 2>&1"],
                  timeout=600)

    def stream(self, prompt: str) -> Iterator[str]:
        import select
        cmd = self.docker + [
            "exec", self.container, "claude", "-p", prompt,
            "--output-format", "stream-json", "--verbose",
            "--allowedTools", "Read Write Edit Glob Grep Bash",
            "--dangerously-skip-permissions",   # safe: disposable sandbox
            "--max-budget-usd", str(self.budget_usd),
        ]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True,
                                      bufsize=1)
        out = self._proc.stdout
        assert out is not None
        while True:
            ready, _, _ = select.select([out], [], [], self.poll_s)
            if ready:
                line = out.readline()
                if line == "":     # EOF — agent finished
                    break
                yield line
            else:
                yield ""           # heartbeat — let the supervisor tick
        self._proc.wait()

    def kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        if self._started:
            self._run(["rm", "-f", self.container])
            self._started = False
