# 0031 — `lamill project code <domain>`: interactive Claude sessions in a per-site container, on the host's paths, logged from Claude Code's transcript

- **Status:** Accepted
- **Date:** 2026-11-25 (v53.A)
- **Supersedes:** — (extends the container sandbox of ADR-0023 to a second,
  interactive use; does not change `project delegate`)

## Context

The operator works on each site by opening Claude Code by hand in the
site's repo. He wants lamill to start those sessions (2026-11-25): a **live,
back-and-forth session** (not `project delegate`'s supervised one-shot
run), **inside a container**, with the site's **context loaded** up front,
the **previous session resumed** where one exists, and a **summarised log**
written to the site's `docs/Prompts.md` afterwards. The interface must stay
minimal: one command, one argument.

Three facts shape the design:

- `project delegate` mounts the site at `/work` with `HOME=/cc`. Claude Code
  files sessions under `~/.claude/projects/<cwd with non-alphanumerics → ->/`,
  so every delegate run on every site lands in one `-work` folder — useless
  for "resume this site's last session", and disjoint from the operator's
  host sessions.
- A resumed Claude Code conversation reuses the system prompt recorded on
  its first request (until compaction); `--system-prompt-snapshot off`
  rebuilds it on every request (Claude Code CLI reference, checked
  2026-11-25).
- Session transcripts (`~/.claude/projects/<dir>/<session-id>.jsonl`) are
  deleted after `cleanupPeriodDays` (default 30) and their format is
  documented as internal and liable to change.

## Decision

1. **Command:** `lamill project code <domain>` — scope-first CLI, no
   subcommands, no options in v53.
2. **Runs in a per-site container** `lamill-code-<domain>` from a prebuilt
   `lamill-code` image (the site toolchain — node, corepack, git; built once
   on first use), started per session and removed on exit. **Claude Code is
   the host's own binary, mounted read-only** *(amended in v53.B,
   2026-11-26)*: npm's `@anthropic-ai/claude-code` lagged the native build
   (2.1.197 vs the host's 2.1.332) and lacked `--system-prompt-snapshot`; the
   mount keeps container and host on one version — one transcript format for
   the shared history — with nothing to rebuild when Claude updates. **Normal
   permission prompts** (operator, 2026-11-25) — not delegate's
   `--dangerously-skip-permissions`.
3. **Same paths as the host.** The site is mounted at its real host path and
   used as the working directory; `HOME` is the host's home with `~/.claude`
   (and `~/.claude.json`) mounted there. Container and host sessions for a
   site therefore share one Claude Code project folder and one history.
4. **Resume by directory:** `claude --continue` — the site's most recent
   session (container or host) when its transcript still exists, else a
   fresh one. `/clear` inside the session starts fresh. No session IDs
   tracked by lamill.
5. **Context pack** (site `AI_AGENTS.md` summary, PRD next open phases, open
   `growth.md` entries, latest GSC numbers, latest `--deep` findings,
   relevant `fleet-learnings.md` sections, a `docs/` map; capped ~20 KB) is
   passed with `--append-system-prompt` and `--system-prompt-snapshot off`,
   so a resumed session sees current context. If that flag doesn't behave as
   documented, a `SessionStart` hook (which re-runs on resume) is the
   fallback.
6. **One live session per site**; a second `code`, or `code` alongside
   `delegate`, on the same site is refused. Sessions on different sites run
   in parallel.
7. **Summary:** after `claude` exits, lamill reads the newest transcript in
   the site's project folder, extracts the conversation text, summarises it
   with `claude -p`, and appends a dated entry to `docs/Prompts.md` (v33.H
   shape). No transcript, or nothing extractable → `✗` in plain words, never
   a silent skip.
8. **Never commits** — prints the summary, the uncommitted diff stat and the
   commit command.

## Consequences

- One history per site across lamill and hand-started sessions; resuming is
  Claude Code's own `--continue`.
- **Dependency on an internal format:** the transcript reader can break on a
  Claude Code update. The loud-failure rule makes that visible; the reader
  is the one piece to re-check after upgrades.
- Normal permission prompts keep the operator in the loop at the cost of
  approve-each-edit friction; revisit only if it becomes real friction.
- Delegate's `/work` + `HOME=/cc` layout is left as is; moving delegate to
  the same-path layout is a separate decision.
- The operator's other per-site uses of Claude (being collected) arrive as
  later v53 phases, not options on this command.
