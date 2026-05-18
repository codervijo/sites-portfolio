# 0002 — Python + uv for the portfolio CLI

- **Status:** Accepted
- **Date:** 2026-04-28 *(retroactively recorded 2026-05-18 — predates ADR adoption)*

## Context

`portfolio` (now also aliased `lamill`) is the personal CLI that
manages a multi-registrar domain inventory, scaffolds sibling
`sites/<domain>/` projects, runs a universal conformance check catalog,
performs SEO/CrUX/GSC live probes, and (post-v8) does SERP research
plus LLM interpretive passes against domain ideas.

Alternative runtimes considered at project start (April 2026):

- **Go.** Single static binary; fast; common in CLI tooling.
- **Node.js / TypeScript.** Aligns with the sites/* stack (Vite +
  Astro + pnpm). Operator already writes a lot of JS/TS.
- **Rust.** Performance + safety; canonical CLI ecosystem (`clap`).
- **Python ≥3.11 + uv.** Operator's primary language; ecosystem
  strong for data, HTTP, integration glue.

Forces / constraints at the time of the decision:

- This is a personal tool, single-user. Speed of iteration matters
  far more than performance.
- The CLI's core job is *integration glue*: registrar CSVs, GSC OAuth,
  CrUX, Porkbun, Cloudflare, Vercel, SerpAPI, OpenAI, Anthropic. All
  have first-class Python SDKs or well-supported `httpx`/`requests`
  HTTP clients.
- Data-shape work (cluster analysis, CSV adapters, JSON snapshots,
  TOML/YAML I/O) is more natural in Python than in Go.
- The operator's existing fluency: Python > TS > Rust > Go.
- `uv` (released by Astral 2024–2025) replaced the historical
  Python-project-management pain (`pip` + `venv` + `pyproject.toml`
  ceremony) with a single fast, deterministic tool. Removed the
  longstanding reason to avoid Python for new CLI tools.

## Decision

Use **Python ≥3.11 with `uv`** as the runtime and project manager
for the `portfolio` CLI.

- `pyproject.toml` (`hatchling`-packaged) declares dependencies and
  the `portfolio` / `lamill` entry points under
  `[project.scripts]`.
- `uv sync`, `uv run pytest`, `uv run portfolio …` are the canonical
  command shapes.
- The `Makefile` wraps these for convenience (`make run ARGS="..."`,
  `make test`, `make build`).
- Stack libraries: `typer` (CLI), `rich` (TTY output), `httpx`
  (async HTTP), `tldextract` (domain parsing),
  `google-api-python-client` (GSC). All stable, well-maintained.

This project is **deliberately exempt** from the central `builder/`
repo's multi-stack pipeline — the central builder targets web app
stacks (React / Tauri / Expo / Vite / Astro), and `portfolio` is a
CLI that lives entirely in Python land with its own self-contained
build. See ADR-0009 for the central-builder convention itself.

## Consequences

**Positive.**
- Fast iteration; the operator's primary language fluency applies.
- Strong ecosystem for integration glue (every external API the tool
  touches has a Python client or trivial HTTP wrapper).
- `uv` removes historical Python-tooling friction (single tool,
  fast lock resolution, hermetic envs).
- `typer` + `rich` produce excellent operator-grade CLI output
  with minimal code.

**Negative.**
- No single-binary distribution. Operator (or any future
  collaborator) needs Python ≥3.11 + uv installed. For a personal
  CLI that runs only on the operator's machine + scheduled-routine
  environments, this is acceptable.
- Slower cold-start than a Go binary (a few hundred ms). Not
  meaningful for a CLI invoked manually a few times per day.
- Diverges from the sites/* stack (which is JS-based via Vite/Astro).
  Trade-off accepted: `portfolio` is a control plane, not part of the
  websites themselves.

**Trade-offs accepted.**
- No native-binary deploy story. If `portfolio` ever needs to ship
  as a binary to non-Python environments, this ADR would be
  superseded — but no such requirement exists today.

## References

- `pyproject.toml` (`[project.scripts]` for `portfolio` + `lamill`).
- `AI_AGENTS.md` § Stack, § Building info.
- `docs/CLAUDE.md` § Project.
- ADR-0009 — Makefile forwards to central builder (the convention
  this project explicitly opts out of).
- [uv documentation](https://docs.astral.sh/uv/).
