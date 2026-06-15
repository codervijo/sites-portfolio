"""v37 — provider-pluggable OSS coding-agent backend for `project delegate`.

A *second* `DelegateBackend` (the first is `delegate.DockerBackend` → the
`claude` CLI) for when Claude hits the 5-hour usage cap. Per the v37 decision
(see `docs/coding-agents-survey.md`) we **wrap a mature OSS coding agent
(OpenHands)** rather than build one — and keep the wrapped agent **swappable**
behind a small `AgentAdapter`, so Codex / mini-swe-agent become future adapters
rather than rewrites.

Division of labour:
  * `OSSAgentBackend` owns the container lifecycle + stream/stderr-drain/exit-
    code/debug/evidence plumbing — mirrored from the proven `DockerBackend`
    (the Claude path), but driven by the adapter instead of hardcoding claude.
  * the `AgentAdapter` owns everything agent-specific: which image, how to
    install/verify, the headless argv, the env it needs, how to parse the
    agent's stdout into `StreamEvent`s, and how to diagnose its failures.

Honest-error-bubbling (reuses v33.O): stderr is drained + retained, the exit
code captured, both exposed via `last_run_evidence`, and the adapter maps the
agent's own failure signals — never a generic "no result".

NOTE: the OpenHands-specific bits (exact install, JSON event schema) are marked
PROVISIONAL until confirmed by a real run; the adapter seam localizes any delta.
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Deque, Iterator, Protocol

from .delegate import RunEvidence, StreamEvent, _str_or_none

# Synthetic terminal line the OSSAgentBackend yields on a clean (exit 0) run —
# agents like OpenHands have no explicit "result" event, so without this
# run_delegate's honesty layer would see no result and mis-report success as
# "no result". parse_line maps it to a non-error `result` StreamEvent.
_OSS_TERMINAL_OK = "\x00__oss_terminal_ok__\x00"


# ---------- the agent-adapter seam (swap this to swap the wrapped agent) ----------


class AgentAdapter(Protocol):
    """Everything agent-specific about driving one OSS coding agent headless in
    the container. Implement this to wrap a new agent (OpenHands today; Codex /
    mini-swe-agent are future adapters — see the survey's revisit triggers)."""

    name: str
    image: str          # container image (pre-built with the agent baked in)

    def install_cmd(self) -> str | None:
        """Shell run once at container start to install the agent. Return None
        when the image already has it baked in (the b2b/ai/openhands image)."""

    def verify_cmd(self) -> str:
        """Shell that exits 0 iff the agent is on PATH / runnable."""

    def run_argv(self, prompt: str, *, home: str) -> list[str]:
        """The in-container argv (after `docker exec …`) for one bounded,
        non-interactive task that leaves an UNCOMMITTED diff in /work."""

    def env(self) -> dict[str, str]:
        """Env vars to pass into the exec (model + API key, etc.)."""

    def parse_line(self, line: str) -> StreamEvent | None:
        """Map one stdout line from the agent into a `StreamEvent` the
        supervisor consumes (tool_use / text / result / error). None for
        blank/unparseable lines (tolerant by design)."""

    def diagnose(self, *, exit_code: int | None, stderr_tail: str) -> str | None:
        """Agent-specific honest reason for a no-result/failed run, or None to
        fall back to the generic `delegate.diagnose_no_result`."""


# ---------- OpenHands adapter (PROVISIONAL specifics — see module docstring) ----------

# The b2b/ai/openhands image bakes OpenHands in (built from that Dockerfile), so
# install_cmd() is None by default. `runtime_install` flips it to install at
# container start (slower; used when the pre-built image isn't available).
_OPENHANDS_IMAGE = "lamill-openhands:latest"
# Coverage states / how OpenHands signals are PROVISIONAL until a real run's
# JSONL is captured; parse_line is tolerant so an unknown shape degrades to
# "other"/None rather than crashing the supervisor.


@dataclass
class OpenHandsAdapter:
    """Wraps OpenHands' headless CLI: `openhands --headless --json -t "<task>"
    --override-with-envs`, leaving an uncommitted diff in /work."""
    model: str = "gpt-4o-mini"
    api_key: str = ""
    image: str = _OPENHANDS_IMAGE
    runtime_install: bool = False
    name: str = "openhands"

    def install_cmd(self) -> str | None:
        if not self.runtime_install:
            return None                 # baked into the pre-built image
        # Fallback runtime install (the pre-built image is preferred). pip's
        # naive `openhands` hits a dep conflict; uv tool install is the path
        # confirmed by the v37.A smoke test.
        return ("command -v openhands >/dev/null 2>&1 && exit 0; "
                "pip install -q uv 2>&1 | tail -2; "
                "export PATH=\"$HOME/.local/bin:/root/.local/bin:$PATH\"; "
                "uv tool install openhands --python 3.12 2>&1 | tail -20")

    def verify_cmd(self) -> str:
        return ('export PATH="$HOME/.local/bin:/root/.local/bin:$PATH"; '
                "command -v openhands >/dev/null 2>&1")

    def run_argv(self, prompt: str, *, home: str) -> list[str]:
        return ["openhands", "--headless", "--json", "-t", prompt,
                "--override-with-envs"]

    def env(self) -> dict[str, str]:
        # OpenHands honors LLM_MODEL/LLM_API_KEY with --override-with-envs;
        # LiteLLM reads OPENAI_API_KEY for openai/* models. Set all three.
        return {
            "LLM_MODEL": self.model,
            "LLM_API_KEY": self.api_key,
            "OPENAI_API_KEY": self.api_key,
            "PATH": "/root/.local/bin:/usr/local/bin:/usr/bin:/bin",
        }

    def parse_line(self, line: str) -> StreamEvent | None:
        """Map one OpenHands JSONL line → StreamEvent. Schema confirmed by a
        real run (v37.A smoke, 2026-06-14): each event has `kind` + `source`
        (user/agent/environment); an **agent** event with `action` is a tool
        action (progress); an **environment** event (`observation`/`tool_name`)
        is the tool result; `llm_message` events are chat. There is NO explicit
        result/cost event — completion is signalled by exit 0 (the
        OSSAgentBackend synthesizes the terminal `result`). Non-JSON footer
        lines (e.g. "Conversation ID: …") → 'other'. Tolerant: unknown → 'other'."""
        line = line.strip()
        if not line:
            return None
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return StreamEvent("other", None, None)   # plain-text footer lines
        if not isinstance(obj, dict):
            return None
        source = obj.get("source")
        kind = str(obj.get("kind") or "")
        # error events
        if "error" in kind.lower() or obj.get("error"):
            err = obj.get("error")
            status = (obj.get("error_id") or obj.get("status")
                      or (err.get("type") if isinstance(err, dict) else None))
            msg = obj.get("message") or (err if isinstance(err, str) else None)
            return StreamEvent("error", None, None,
                               api_error_status=_str_or_none(status),
                               text=_str_or_none(msg))
        # agent action → tool_use (the progress signal the supervisor watches)
        action = obj.get("action")
        if source == "agent" and action is not None:
            if isinstance(action, dict):
                name = str(action.get("kind") or action.get("name") or "action")
                target = (action.get("path") or action.get("command")
                          or action.get("file_path") or "")
            else:
                name, target = str(action), ""
            return StreamEvent("tool_use", f"{name}:{str(target).strip()}".rstrip(":"))
        # environment observation / agent or user message → text activity
        if source in ("agent", "user", "environment") or obj.get("observation"):
            return StreamEvent("text", None, None)
        return StreamEvent("other", None, None)

    def diagnose(self, *, exit_code: int | None, stderr_tail: str) -> str | None:
        s = (stderr_tail or "")
        low = s.lower()
        if "rate limit" in low or "429" in s or "rate_limit" in low:
            return ("OpenHands hit an OpenAI rate limit (429) — short backoff, "
                    "not the 5h cap. Re-run.")
        if "authentication" in low or "invalid api key" in low or "401" in s:
            return ("OpenHands auth failed — check OPENAI_API_KEY "
                    "(`lamill settings apikeys`).")
        if exit_code == 127:
            return ("the OpenHands CLI was not found in the container — the "
                    "image/install is broken (see the build).")
        return None     # let delegate.diagnose_no_result handle the rest


# ---------- the OSS-agent container backend ----------


class OSSAgentBackend:
    """Throwaway-container backend driven by an `AgentAdapter`. Mirrors
    `delegate.DockerBackend`'s lifecycle/stream/evidence plumbing, but installs
    + runs the adapter's agent (not claude) and parses with the adapter. Mounts
    ONLY `sites/<domain>/` RW — no claude auth; the agent authenticates via the
    OpenAI key in the adapter's env. Implements the `DelegateBackend` Protocol
    + the optional `parse_line` / `last_run_evidence` capabilities."""

    def __init__(self, domain: str, adapter: AgentAdapter, *,
                 docker_cmd: list[str] | None = None, poll_s: float = 2.0,
                 debug_path: Path | None = None):
        safe = domain.replace(".", "-").replace("/", "-")
        self.container = f"lamill-delegate-oss-{safe}"
        self.adapter = adapter
        self.image = adapter.image
        self.docker = docker_cmd or ["docker"]
        self.poll_s = poll_s
        # The agent runs as ROOT in the disposable container (the uv-installed
        # `openhands` lives in /root/.local/bin; running as the host uid can't
        # reach it). HOME=/root keeps the agent's state off /work. To avoid
        # leaving root-owned files in the operator's site dir, `/work` is
        # chowned back to the host uid:gid at teardown (`kill`).
        self._HOME = "/root"
        self._stderr_tail: Deque[str] = deque(maxlen=400)
        self._exit_code: int | None = None
        self._debug_path = debug_path
        self._debug_fh = None
        self._debug_lock = threading.Lock()
        self._uid, self._gid = os.getuid(), os.getgid()
        self._proc: subprocess.Popen | None = None
        self._started = False

    # ----- generic plumbing (mirrors DockerBackend) -----

    def _run(self, args: list[str], **kw) -> subprocess.CompletedProcess:
        return subprocess.run(self.docker + args, capture_output=True,
                              text=True, check=False, **kw)

    def _open_debug(self) -> None:
        if self._debug_path is None or self._debug_fh is not None:
            return
        try:
            self._debug_fh = open(self._debug_path, "w", encoding="utf-8")
        except OSError:
            self._debug_fh = None

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

    def last_run_evidence(self) -> RunEvidence:
        return RunEvidence(
            exit_code=self._exit_code,
            stderr_tail="\n".join(self._stderr_tail),
            debug_path=str(self._debug_path) if self._debug_path else None,
        )

    def parse_line(self, line: str) -> StreamEvent | None:
        """run_delegate uses this (via getattr) instead of the claude parser.
        Recognizes the backend's synthetic terminal-OK marker (→ a non-error
        `result`); everything else goes to the adapter."""
        if line.strip() == _OSS_TERMINAL_OK:
            return StreamEvent("result", None, None, is_error=False)
        return self.adapter.parse_line(line)

    def diagnose(self, *, exit_code: int | None, stderr_tail: str) -> str | None:
        """run_delegate's no-result path uses this (via getattr) for an
        agent-specific honest reason before the generic fallback."""
        return self.adapter.diagnose(exit_code=exit_code, stderr_tail=stderr_tail)

    # ----- lifecycle -----

    def start(self, site_dir: Path) -> None:
        self._open_debug()
        self._run(["rm", "-f", self.container])
        run_args = [
            "run", "-d", "--name", self.container, "--network=host",
            "-v", f"{site_dir}:/work", "-w", "/work",
            self.image, "tail", "-f", "/dev/null",
        ]
        r = self._run(run_args)
        if r.returncode != 0:
            raise RuntimeError(
                f"OSS-agent container start failed (image {self.image}): "
                f"{r.stderr.strip()}")
        self._started = True
        install = self.adapter.install_cmd()
        if install:
            ins = self._run(["exec", self.container, "sh", "-lc", install],
                            timeout=900)
            self._debug_write("install", (ins.stdout or "") + (ins.stderr or ""))
        present = self._run(["exec", self.container, "sh", "-lc",
                             self.adapter.verify_cmd()])
        if present.returncode != 0:
            out = self._run(["exec", self.container, "sh", "-lc", install or "true"]).stdout
            raise RuntimeError(
                f"{self.adapter.name} not runnable in the container after "
                f"start (image {self.image}). Build the image from "
                f"b2b/ai/openhands, or set runtime_install=True. {out[-800:]}")

    def _exec_argv(self, prompt: str) -> list[str]:
        # Run as root (the uv-installed agent binary is root-owned); /work is
        # chowned back to the host uid at teardown.
        argv = self.docker + ["exec", "-e", f"HOME={self._HOME}"]
        for k, v in self.adapter.env().items():
            argv += ["-e", f"{k}={v}"]
        argv += [self.container] + self.adapter.run_argv(prompt, home=self._HOME)
        return argv

    def stream(self, prompt: str,
               system_prompt: str | None = None) -> Iterator[str]:
        import select
        cmd = self._exec_argv(prompt)
        # Mask the API key in the debug transcript.
        self._debug_write("argv", " ".join(
            "***" if "API_KEY=" in a else a for a in cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True,
                                      bufsize=1)
        out, err = self._proc.stdout, self._proc.stderr
        assert out is not None and err is not None

        def _drain_stderr() -> None:
            for line in err:
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
                    if line == "":
                        break
                    self._debug_write("stdout", line.rstrip("\n"))
                    yield line
                else:
                    yield ""           # heartbeat
            # EOF — agent finished. Capture the exit code, then synthesize a
            # terminal `result` on success (OpenHands has no explicit result
            # event) so run_delegate marks a clean run `done`, not "no result".
            self._exit_code = self._proc.wait()
            stderr_thread.join(timeout=2.0)
            self._debug_write("meta", f"exit_code={self._exit_code}")
            if self._exit_code == 0:
                yield _OSS_TERMINAL_OK
        finally:
            if self._exit_code is None:            # killed mid-stream
                self._exit_code = self._proc.poll()
                stderr_thread.join(timeout=2.0)

    def exec(self, shell_cmd: str, *, timeout: int = 600) -> tuple[int, str]:
        r = self._run(
            ["exec", "-e", f"HOME={self._HOME}", self.container,
             "sh", "-lc", shell_cmd],
            timeout=timeout)
        return r.returncode, (r.stdout or "") + (r.stderr or "")

    def kill(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        if self._started:
            # Chown /work back to the host uid:gid so the operator's site dir
            # isn't left root-owned (the agent + verify build ran as root).
            self._run(["exec", self.container, "sh", "-lc",
                       f"chown -R {self._uid}:{self._gid} /work 2>/dev/null || true"])
            self._run(["rm", "-f", self.container])
            self._started = False
        self._close_debug()
