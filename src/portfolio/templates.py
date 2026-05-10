"""v6.C — Public template module.

Single source of truth for the boilerplate text that gets written by
both `new bootstrap` (creating a new project) and `project fix`
(remediating a missing/incomplete file in an existing project).

The bulk of the templates already live as private functions in
`bootstrap.py`. This module re-exports them under cleaner names plus
adds the few that bootstrap doesn't currently produce
(`docs/CLAUDE.md`, `.env.example`, individual section emitters for
section-injection fixers).

Why a thin wrapper instead of moving definitions: bootstrap.py is
1000+ LOC; a wholesale move risks subtle whitespace / behavioral
drift in current bootstrap output. The wrapper preserves byte-
identical bootstrap behavior while letting fixers reuse the same
strings. Future cleanup: collapse this into bootstrap.py once the
fixers stabilize.
"""
from __future__ import annotations

from .bootstrap import (
    _ai_agents_md as _bootstrap_ai_agents_md,
    _docs_growth_md as _bootstrap_docs_growth_md,
    _docs_prd_md as _bootstrap_docs_prd_md,
    _docs_prompts_md as _bootstrap_docs_prompts_md,
    _gitignore as _bootstrap_gitignore,
    _local_makefile as _bootstrap_local_makefile,
    _readme_md as _bootstrap_readme_md,
)


# ---------- whole-file templates ----------


def readme_md(domain: str) -> str:
    return _bootstrap_readme_md(domain)


def ai_agents_md(domain: str, stack: str = "vite", topic: str = "") -> str:
    """AI_AGENTS.md scaffold — already includes the `## Building info` and
    `## Deployment info` headings expected by CHECK_003/004."""
    return _bootstrap_ai_agents_md(domain, stack, topic)


def docs_prd_md(domain: str, topic: str = "") -> str:
    """docs/prd.md scaffold — includes `## Problem` and `## Users`
    headings expected by CHECK_027 (well, the bootstrap version does;
    this template ensures it)."""
    return _bootstrap_docs_prd_md(domain, topic)


def docs_prompts_md(domain: str, today: str) -> str:
    return _bootstrap_docs_prompts_md(domain, today)


def docs_growth_md(domain: str, today: str) -> str:
    return _bootstrap_docs_growth_md(domain, today)


def gitignore() -> str:
    return _bootstrap_gitignore()


def local_makefile(domain: str) -> str:
    return _bootstrap_local_makefile(domain)


def env_example() -> str:
    """`.env.example` — placeholder file the user replaces with real env-var
    template comments per project. Keeps the conformance check passing
    while making clear it's a starter."""
    return (
        "# .env.example — copy to .env (gitignored) and fill in real values.\n"
        "# Document each env var below with a one-line comment about what it does.\n"
        "\n"
        "# Example:\n"
        "# OPENAI_API_KEY=          # Used by the content pipeline.\n"
    )


def docs_claude_md(domain: str) -> str:
    """docs/CLAUDE.md scaffold — Claude-specific orientation file (CHECK_006).
    Includes the `## Project` and `## Commands` sections required by CHECK_026.
    Bootstrap doesn't currently write this file; this is a new template
    introduced by v6.C.
    """
    return f"""# CLAUDE.md — {domain}

Per-project orientation for Claude. Read this first when picking up
work on this site. Index of conventions, deferred decisions, and
non-features that aren't obvious from the code or git history.

## Project

<1-2 sentence description — fill in: what does this site do, who is
the user, what is the stack ({domain} runs on the sites/* workspace
shared infra: Vite or Astro + pnpm + Cloudflare Pages, with Makefile
forwarding to the central builder).>

## Commands

```bash
# Build / dev (forwards to the parent Makefile)
make deps           # install deps via the central builder
make dev            # local dev server
make build          # production build → dist/

# Test (per-stack — adjust as needed)
make test           # if a test suite is wired in

# Deploy
git push            # Cloudflare Pages auto-builds on push to main
```

## Conventions

  - Build path: this project's `Makefile` → `../Makefile` (parent
    workspace) → `~/work/projects/builder/` (central builder).
  - Stack: pnpm-only. No `package-lock.json` / `bun.lockb` / `yarn.lock`.
  - Deploy: Cloudflare Pages via `wrangler.jsonc`. No `_redirects`
    SPA fallback (uses CF's `not_found_handling` instead).

## Deferred decisions

<Things deliberately *not* shipped. Append entries with rationale so
future Claude sessions don't re-propose them.>
"""


# ---------- section-injection emitters ----------
# These produce just the section block to APPEND to an existing file
# whose top-level structure is otherwise fine. Fixers for CHECK_003,
# CHECK_004, CHECK_026, CHECK_027 use these.


def ai_agents_section_building() -> str:
    return """\
## Building info

This project's `Makefile` forwards every target to `../Makefile`
(the sites/ workspace) which delegates per-stack work to the central
builder at `~/work/projects/builder/`. Common: `make deps`, `make dev`,
`make build`. Don't duplicate build logic per-site.
"""


def ai_agents_section_deployment() -> str:
    return """\
## Deployment info

Cloudflare Pages. Push to `main` triggers an auto-build via the
`wrangler.jsonc` config; build output is `dist/`. Custom domain
configured via the CF Pages dashboard.
"""


def claude_md_section_project(domain: str) -> str:
    return f"""\
## Project

<1-2 sentence description — fill in what {domain} does and who the
user is. The stack uses the sites/* workspace shared infra: Vite or
Astro + pnpm + Cloudflare Pages, with Makefile forwarding to the
central builder at `~/work/projects/builder/`.>
"""


def claude_md_section_commands() -> str:
    return """\
## Commands

```bash
# Build / dev (forwards to the parent Makefile)
make deps           # install deps via the central builder
make dev            # local dev server
make build          # production build → dist/

# Deploy
git push            # Cloudflare Pages auto-builds on push to main
```
"""


def prd_md_section_problem() -> str:
    return """\
## Problem

<1-2 sentences: what is the user-facing problem this site solves?
Who has it? Why does it matter?>
"""


def prd_md_section_users() -> str:
    return """\
## Users

<Who's the target user? What do they care about? Roughly how many
exist? What's their willingness to pay / engage?>
"""
