"""Project bootstrap (v3.A) — scaffold a sites/<domain>/ project to ship-ready.

Three paths:

  - **Template path (default)**: target dir must NOT exist. Writes a minimal
    Astro or Vite scaffold + the standard docs/AI_AGENTS/Makefile pointing at
    the central builder repo. Pure filesystem; no network.

  - **--from-genai path**: target dir MUST exist with a `genai/` subdirectory
    (e.g. a hand-cloned Lovable export). Copies `genai/*` to project root
    then applies Cloudflare Pages safety fixes (Vite ≥6, no `_redirects` SPA
    fallback, `wrangler.toml` added).

  - **--git-url path**: target dir must NOT exist. Bootstrap creates it and
    `git clone`s the URL into `<project>/genai/`, then proceeds as if
    `--from-genai` were passed. Removes the manual clone step. (Net access
    required for this path only.)

All paths end with: writes the conformance scaffolding (AI_AGENTS.md with
Building/Deployment sections, docs/prd.md, docs/Prompts.md, README,
.gitignore), then `git init` + initial commit so the project owns its
own .git from day zero (in addition to the cloned genai/ history).
"""
from __future__ import annotations

import csv
import difflib
import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .data import DOMAINS_DIR, PORTFOLIO_JSON, ROOT

SITES_ROOT = ROOT.parent
MIN_VITE_MAJOR = 6
DOMAIN_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


@dataclass
class BootstrapResult:
    project_dir: Path
    stack: str
    path: str  # "template" or "genai"
    files_written: list[str] = field(default_factory=list)
    files_copied: list[str] = field(default_factory=list)
    cf_fixes: list[str] = field(default_factory=list)
    git_initialized: bool = False
    initial_commit_sha: str | None = None
    warnings: list[str] = field(default_factory=list)
    next_steps: list[str] = field(default_factory=list)
    # v18.D — GA4 auto-create outcome from bootstrap. ga4_status is
    # always set to one of the literal status strings below; CLI
    # renders both fields after bootstrap completes.
    ga4_status: str = ""           # "" | "created" | "skipped:<reason>" | "failed:<error>"
    ga4_measurement_id: str | None = None   # populated iff status == "created"
    # v29.D — which [content] fields were derived+seeded from the
    # authored AI_AGENTS sections (ADR-0019). Empty list = none seeded
    # (no API key / no brief / derivation failure); CLI renders a summary.
    content_seeded: list[str] = field(default_factory=list)


class BootstrapError(Exception):
    pass


# ---------- validation ----------


def validate_domain(name: str) -> str:
    n = name.strip().lower()
    if not n:
        raise BootstrapError("domain is required")
    if not DOMAIN_RE.match(n):
        raise BootstrapError(
            f"invalid domain format: {name!r} — must be lowercase, dotted, no spaces or special chars"
        )
    return n


@dataclass
class OwnedDomainCheck:
    """Result of the owned-domains inventory cross-check.

    Catches the operator-typo case (e.g. `ageskd.dev` for `agesdk.dev`)
    before any files get scaffolded. `found=True` → the requested
    domain is in the inventory; ship it. `found=False` → not in
    inventory; CLI surfaces `close_matches` (if any) + asks the
    operator to confirm via `--force`.
    """
    found: bool
    close_matches: list[str]
    inventory_size: int
    source: str  # "portfolio.json" | "csv" | "none"


def _load_owned_domains_from_portfolio_json(
    portfolio_json: Path | None = None,
) -> list[str]:
    """Read domain names from data/portfolio.json (the canonical
    inventory rebuilt by `fleet sync`). Returns [] if the file is
    missing or unreadable so the caller can fall back to CSV scan."""
    path = portfolio_json if portfolio_json is not None else PORTFOLIO_JSON
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    return [
        row.get("name", "").lower()
        for row in payload.get("domains", [])
        if row.get("name")
    ]


def _load_owned_domains_from_csvs(
    domains_dir: Path | None = None,
) -> list[str]:
    """Scan data/domains/<registrar>.csv for domain names. Used as
    fallback when portfolio.json doesn't yet exist (cold-start before
    `fleet sync` has run)."""
    directory = domains_dir if domains_dir is not None else DOMAINS_DIR
    if not directory.exists():
        return []
    out: list[str] = []
    for csv_path in sorted(directory.glob("*.csv")):
        try:
            with csv_path.open() as f:
                reader = csv.DictReader(f)
                for row in reader:
                    # Registrar CSVs vary in case + column name. Try the
                    # common variants in priority order: porkbun/godaddy
                    # use "DOMAIN" (upper); namecheap uses "Domain Name".
                    for key in ("DOMAIN", "Domain", "domain",
                                "Domain Name", "domain_name", "name"):
                        v = row.get(key)
                        if v and v.strip():
                            out.append(v.strip().lower())
                            break
        except (OSError, csv.Error):
            continue
    return out


def validate_owned_domain(
    domain: str,
    *,
    portfolio_json: Path | None = None,
    domains_dir: Path | None = None,
) -> OwnedDomainCheck:
    """Check whether `domain` appears in the operator's owned-domains
    inventory.

    Source preference: `data/portfolio.json` (rebuilt by `fleet sync`)
    is canonical when present. When portfolio.json is absent (cold
    start before the first sync), falls back to scanning each
    `data/domains/<registrar>.csv`.

    `found=False` returns the top-3 closest matches (via difflib at
    cutoff=0.7) so the CLI can suggest "Did you mean: agesdk.dev?".
    Inventory size is included so the warning can hint at whether the
    inventory's just empty (size=0 → "run fleet sync first").
    """
    d = domain.strip().lower()
    owned = _load_owned_domains_from_portfolio_json(portfolio_json)
    source = "portfolio.json"
    if not owned:
        owned = _load_owned_domains_from_csvs(domains_dir)
        source = "csv" if owned else "none"

    # Dedupe + sort for a stable close-matches result.
    owned_unique = sorted(set(owned))
    found = d in owned_unique
    close = (
        [] if found
        else difflib.get_close_matches(d, owned_unique, n=3, cutoff=0.7)
    )
    return OwnedDomainCheck(
        found=found,
        close_matches=close,
        inventory_size=len(owned_unique),
        source=source,
    )


# ---------- templates ----------


def _ai_agents_md(domain: str, stack: str, topic: str,
                  operator_inputs: dict[str, str] | None = None) -> str:
    """Render AI_AGENTS.md for a new project.

    `operator_inputs` is the {heading → content} dict the v9.B CLI
    collects (interactively or via per-section flags). Sections with
    non-empty content replace the `(to be filled in)` placeholder;
    sections with empty content keep the placeholder so CHECK_014's
    fixer can populate them later (or the operator can edit by hand).

    Backward-compatible: when `operator_inputs` is None, all five
    operator-input sections render with placeholders (matches v9.A's
    template exactly).
    """
    operator_inputs = operator_inputs or {}

    def _section_body(heading: str) -> str:
        """Return the body for an operator-input section: the
        operator's content when supplied, the canonical placeholder
        otherwise. Keeps the indentation-free body that the H2 +
        italic hint above already establish."""
        content = (operator_inputs.get(heading) or "").strip()
        return content if content else "(to be filled in)"

    topic_line = f"\n_Topic: {topic}_\n" if topic else ""
    return f"""# AI Agent Context — {domain}
{topic_line}
## Summary

*one paragraph: what this site is, what it does*

{_section_body("Summary")}

## Audience

*one sentence: who this is for (broad demographic)*

{_section_body("Audience")}

## ICP

*the specific ideal customer — demographics, pain points, what they use today. More detail than Audience: Audience is the broad demo ("homeowners with EV chargers"), ICP is the specific targetable subset ("Tesla owners in CA who installed in last 90d, paid $2k+")*

{_section_body("ICP")}

## Goals

*1-2 sentences: primary business / product goal*

{_section_body("Goals")}

## Tech stack

{stack.capitalize()} project under the sites/* workspace. Build path goes
through the parent `sites/Makefile` (Docker-orchestrated) which delegates
per-stack work to the central builder at `~/work/projects/builder/`.

## Project structure

- `src/` — application source
- `public/` — static assets copied to `dist/` at build (favicons, OG images, `_headers`)
- `docs/` — PRD, Prompts log
- `Makefile` — thin forwarder to `../Makefile`
- `wrangler.jsonc` — Cloudflare deploy config
- `scripts/` *(if present)* — ingester or build-time helpers

## Building info

All dev work runs inside the parent `sites1` docker container. The host doesn't
need Node/pnpm installed; the container does. The parent `Makefile`
(`../Makefile` from this dir) is the canonical entry point.

### Why docker

- Pinned Node + pnpm versions match Cloudflare's build env.
- Avoids polluting the host with per-project node_modules.
- Same image serves every sibling project under sites/.

### Common Makefile targets

This project's local `Makefile` forwards every target to `../Makefile` with
`proj={domain}`, so these all work either from this dir or from `sites/`:

| Command | What it does |
|---|---|
| `make buildsh` *(from `sites/`)* | Drop into a bash shell inside the docker container at `/usr/src/app` (= `sites/` mounted in). |
| `make run` *(from here)* / `make run proj={domain}` *(from `sites/`)* | `pnpm install` then start dev server (auto-detected). |
| `make check-vite proj={domain}` | Start the dev server, skipping install. |
| `make test proj={domain}` | `pnpm install` + `pnpm build` + `pnpm test`. **Hard-fails outside docker** — `make buildsh` first, or `docker exec`. |
| `make deps` | Install pnpm globally (image bootstrap). |
| `make clean` *(from `sites/`)* | Remove root `package.json`, lockfile, node_modules. Don't run inside a project dir. |

### Running Make targets from a Claude Code session

The Bash tool runs on the host as `vijo`, not inside docker. To execute a
target inside the container, find the running container and `docker exec` in:

```bash
docker ps                                               # find the sites1 container name
docker exec -w /usr/src/app <name> make test proj={domain}
```

## Deployment info

- **Platform:** Cloudflare Workers (Static Assets) — *not* Vercel.
- **Config:** `wrangler.jsonc` at the repo root — points `assets.directory` at `./dist` and uses `not_found_handling: "single-page-application"` for SPA client-side routing.
- **Headers:** `public/_headers` — cache (`/assets/*` immutable, HTML no-cache) + security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`). Vite copies `public/` into `dist/` at build, so the file ships with the assets.
- **Build:** `pnpm build` → `dist/`. Wrangler picks up `dist/` via `wrangler.jsonc`.
- **Deploy:** `wrangler deploy` (locally) or via Cloudflare's Git integration on push.
  Initial GitHub repo + CF Pages project setup is automated by the portfolio CLI:
  `cd ../portfolio && make run ARGS="deploy {domain}"` runs `gh repo create` and
  POSTs to the CF Pages API with `build_command="pnpm run build"` set explicitly
  (avoids the bun-detection trap kwizicle.com hit). Idempotent; safe to re-run.
- **Vite version:** must be ≥ 6.0.0 — Wrangler's Vite integration rejects Vite 5.
- **Env vars:** set `VITE_*` vars (e.g. `VITE_GA_ID`) in the Cloudflare Workers project's environment-variable settings — they're inlined at build time.
- **Live URL:** https://{domain}/  *(update once first deploy succeeds)*
- **Canonical host:** the **apex** (`https://{domain}/`) is the ONLY canonical host fleet-wide — `www` and `http` must 308→apex, and there is no `www`-canonical option. Set Astro's `site: "https://{domain}"` (apex, never `www`) so every `<link rel="canonical">` and the generated sitemap `<loc>` URLs use the apex. Enforced by CHECK_150 (redirect) + CHECK_158 (canonical tags) + CHECK_159 (sitemap) + CHECK_160 (GSC-registered sitemap).
- **Legacy:** if a `vercel.json` or `.vercelignore` is present from a Lovable export, it's inert on Cloudflare and safe to delete.

## Content strategy

*what content this site needs — page types, initial topics, format mix (long-form vs reference vs tool)*

{_section_body("Content strategy")}

### Post-deploy checklist (do these once after the first successful deploy)

- [ ] Verify in **Google Search Console** at https://search.google.com/search-console — add as `sc-domain:{domain}` property; verify via DNS TXT record. Until this is done, no SEO traffic data is observable for this site (and the workspace-wide `30 commercial sites with traffic` goal can't credit it).
- [ ] Submit the sitemap (`https://{domain}/sitemap-index.xml` — the apex host; `@astrojs/sitemap` emits `-index`, not `/sitemap.xml`) inside GSC. *(The deploy pipeline auto-submits the robots.txt-declared sitemap; this is the manual fallback.)*
- [ ] Update the **Live URL** above with the actual deploy URL.
- [ ] Run `make run ARGS="cleanup"` from `sites/portfolio/` so `data/portfolio.json` reflects the new project's state (and `project status {domain}` resolves cleanly).

## How to run

```bash
# from this dir, after `make buildsh` from sites/:
make deps      # → pnpm install via the central builder
make run       # → dev server
make build     # → dist/
make test      # → pnpm install + build + test (must be inside container)
```

## How this project is checked

This project is enforced against shared sites/* conventions by
`portfolio project check {domain}` (run from `sites/portfolio/`).
Conformance is driven by the universal check catalog (CHECK_*) —
e.g. CHECK_020 (own-git-repo), CHECK_002 (has-ai-agents-md),
CHECK_007 (has-docs-prompts), CHECK_008 (has-docs-growth — `docs/growth.md`
exists — the per-project growth-experiment log; see Growth log section
below), CHECK_001 (has-readme), CHECK_009 (has-gitignore), CHECK_035
(vite-version-ok), CHECK_003 / CHECK_004 (AI_AGENTS.md `## Building info` +
`## Deployment info` headings). See the full catalog with
`portfolio check catalog`. The bootstrap output satisfies all of these on
day zero — keep it that way.

If `project check` flags a regression, fix it. v6.C's `portfolio project fix`
will eventually auto-fix; until then, hand-edit.

## Growth log — per-project experiment tracker

`docs/growth.md` is this project's append-only log of growth experiments
(content, SEO, marketing, structural changes). Each entry is a dated H2
with a measurable hypothesis + KPI + observation window (default 28d).
Read **the full workflow inside `docs/growth.md`** — it's self-sustaining
so you don't have to remember the lifecycle from outside the file.

Update it whenever you do something growth-relevant on this site. The
data source is GSC (`portfolio gsc sync` from the portfolio dir); this
file narrates *why*.

## Strategy reminder — ship fast, let the market decide

This sites/* workspace is shipping commercial sites toward a
**30-site SEO-traffic goal**. The convention is **build & ship fast,
then let GSC data drive what to invest more in.** Don't over-polish
before launch. Get a minimum-viable version live, indexed, then
iterate on whichever sites actually attract traffic.

Translation for this project: prefer shipping over perfection. The
SEO baseline files (`public/robots.txt`, `public/sitemap.xml`),
deploy config, and dev tooling (`vitest`) are pre-scaffolded so you
can ship today.

## Versioning

This project follows the sites/* **canonical versioning convention** (defined
in `sites/portfolio/AI_AGENTS.md`):

- **`vN`** — major capability tier. Each is a coherent shipped capability and
  may break compat with the previous tier. SemVer-MAJOR semantics.
- **`vN.X`** — phase letter within a tier (A / B / C / …). Internal slicing of
  build work; signals "order/scope can shift." Each phase still ships
  independently.
- **`vN.X.Y`** — numeric sub-phase for follow-up work that lands AFTER `vN.X`
  shipped (e.g. polish, bug fixes, scope cuts).

Two-layer notation separates **external version** (what consumers see) from
**internal phasing** (how the team slices work). Letters signal *un-promised* —
nobody mistakes `v1.B` for a SemVer minor release.

**Always use this numbering when planning or shipping work on this project.**
Specifically:

- Every entry in `docs/prd.md`'s phases table uses `vN.X` (or `vN.X.Y`).
- Every commit message that ships a phase mentions its version (e.g.
  `v1.B — auth flow`).
- Every entry in `docs/Prompts.md` references the version of the work it
  describes when relevant.

Don't introduce a parallel scheme (no `0.1.0` / `Sprint 3` / etc.). When in
doubt, the canonical statement is `sites/portfolio/AI_AGENTS.md`.

Track this project's progress in `docs/prd.md` against this taxonomy. v0.A is
the bootstrap (this scaffold); v1.A is the first real shipped capability.

## Conventions

- Stack: {stack}
- **Package manager: pnpm only.** No `bun.lockb`, no `package-lock.json`, no `yarn.lock` — they cause CF Pages to pick the wrong manager and break the build. The `pnpm-lock.yaml` is the only lockfile that should ever be committed.
- Build path: this project's `Makefile` → `../Makefile` → `~/work/projects/builder/`
- Cloudflare deploy constraints: Vite ≥ 6, frozen-lockfile install, no `_redirects` SPA fallback (handled by `wrangler.jsonc`'s `not_found_handling` instead).
- **Versioning**: two-level `vN` / `vN.X` — see Versioning section above and `sites/portfolio/AI_AGENTS.md` for the canonical statement.

## Out of scope / don't touch

- *(leave blank — fill in when something is)*
"""


def _docs_prd_md(domain: str, topic: str) -> str:
    today = date.today().isoformat()
    topic_line = f"\n## Topic\n\n{topic}\n" if topic else ""
    return f"""---
project: {domain}
prd_version: 1
project_version: v0.A
status: planned
owner: Vijo
last_updated: {today}
---

# {domain} — PRD

## 1. Problem

<1-2 sentence problem statement — fill in: what user-facing problem
does this site solve? Who has it? Why does it matter?>
{topic_line}
## 2. Users

<who uses this — target user, what they care about, rough audience size>

## 3. Goals & non-goals

**Goals:**
- <fill in>

**Non-goals:**
- <fill in>

## 4. Versions

Two-level versioning convention (canonical: `sites/portfolio/AI_AGENTS.md`):

- `vN` = major capability tier; SemVer-MAJOR semantics.
- `vN.X` = phase letter within a tier; internal slicing.

| Version | Theme | Acceptance |
|---|---|---|
| v0 | scaffold | local builds, CF wrangler.jsonc + public/_headers in place, repo initialized |
| v1 | <fill in: first real shipped capability> | <fill in: what users get> |

## 5. Phases

| Phase | Theme | Features | Status |
|---|---|---|---|
| **v0.A** | scaffolded | `portfolio new bootstrap` ran; standard files written; git initialized | ✅ |
| **v1.A** | <fill in> | <fill in> | planned |

## 6. Open questions

- *(append-only log; mark answered with date but never delete)*
"""


def _docs_growth_md(domain: str, today: str,
                    growth_hypothesis: str = "") -> str:
    """Render docs/growth.md.

    v9.D — when `growth_hypothesis` is non-empty, the first dated H2
    entry carries the operator's stated bet under a new `Hypothesis:`
    field, and the entry's title is a short summary of that bet
    (rather than the generic "site scaffolded; growth log started").
    Empty `growth_hypothesis` reproduces the pre-v9.D template
    exactly — every entry-template field stays the same, so existing
    operator workflows around the format aren't disturbed.
    """
    try:
        review_date = (date.fromisoformat(today) + timedelta(days=28)).isoformat()
    except ValueError:
        review_date = "<today + 28 days>"

    hypothesis = (growth_hypothesis or "").strip()
    if hypothesis:
        # Short title — first ~70 chars, stopped at the first sentence-
        # ending punctuation so the H2 reads as a single intelligible
        # claim rather than a truncated fragment.
        title = _shorten_hypothesis_for_title(hypothesis)
        first_entry = (
            f"## {today} — {title}\n"
            "- **Status:** active\n"
            f"- **Hypothesis:** {hypothesis}\n"
            "- **KPI:** any GSC traffic — clicks, impressions, indexed-page count\n"
            "- **Baseline:** 0 clicks / 0 impressions (just deployed)\n"
            "- **Action:** project scaffolded via `portfolio new bootstrap`; "
            "first deploy pending. After deploy: verify in GSC as "
            f"`sc-domain:{domain}` and submit the sitemap.\n"
            f"- **Result:** TBD — review {review_date}\n"
            "- **Learning:** TBD\n"
        )
    else:
        first_entry = (
            f"## {today} — site scaffolded; growth log started\n"
            "- **Status:** active\n"
            "- **KPI:** any GSC traffic — clicks, impressions, indexed-page count\n"
            "- **Baseline:** 0 clicks / 0 impressions (just deployed)\n"
            "- **Action:** project scaffolded via `portfolio new bootstrap`; "
            "first deploy\n"
            f"  pending. After deploy: verify in GSC as `sc-domain:{domain}` and submit\n"
            "  the sitemap.\n"
            f"- **Result:** TBD — review {review_date}\n"
            "- **Learning:** TBD\n"
        )

    return f"""# Growth Log — {domain}

> **What this file is for:** an honest, append-only log of growth experiments
> on this site — what was tried, what was measured, what happened. The data
> source is GSC; this file narrates *why*. Future-you (or future-Claude)
> reads this when deciding what to try next, both on this site and on
> related sister sites.

## How to use this (workflow — re-read this when you forget)

**Add an entry whenever you do something growth-relevant.** That includes:
shipping new content, structural SEO changes (sitemap, schema, redirects,
internal linking), tech changes that affect crawl/indexing, marketing
pushes, backlink campaigns. *Not* every code commit — just things you'd
want to point at when GSC numbers move (or fail to).

**Each entry is a hypothesis you can be wrong about.** Commit to a
measurable KPI and an observation window before acting — otherwise "did
this work?" is just a feeling.

### Lifecycle of one entry

1. **Day of action** — append a new dated H2 with `Status: active`, the
   hypothesis, the KPI you'll watch, current baseline numbers, what you
   did, and the date to review (default: today + 28 days, matching GSC's
   reporting window).
2. **Review day** — pull current GSC numbers, compute delta vs baseline.
   Fill in **Result** and **Learning**. Set **Status** to `shipped` (worked,
   keep going), `failed` (didn't pay off, abandon), or extend the review
   another window if results are ambiguous.
3. **Never rewrite older entries.** Wrong hypotheses are the most valuable
   data — they tell you what NOT to repeat on the next site. Append, don't
   edit.

### Where to get the numbers

```bash
cd ~/work/projects/sites/portfolio && make run ARGS="gsc sync"
```

Then read the row for `{domain}`. Or pull from
https://search.google.com/search-console directly.

### Format

```
## YYYY-MM-DD — <one-line hypothesis or action>
- **Status:** active | testing | shipped | failed | abandoned
- **Hypothesis:** <what you're betting will work — only on initial / new-bet entries>
- **KPI:** <what GSC metric / query / page>
- **Baseline:** <numbers at start>
- **Action:** <what was done; 1-2 lines>
- **Result:** <numbers after window; "TBD — review YYYY-MM-DD" until then>
- **Learning:** <why it worked / didn't; what to try next; "TBD" until reviewed>
```

---

{first_entry}"""


def _shorten_hypothesis_for_title(hypothesis: str, max_chars: int = 70) -> str:
    """Trim an operator's hypothesis paragraph to a one-liner usable
    as an H2 title.

    Prefers cutting at the first sentence end (period, question mark,
    exclamation) under `max_chars` so the title reads cleanly. Falls
    back to a word-boundary cut + ellipsis when no sentence-ending
    punctuation appears in range. Multi-line input is flattened to
    a single line.
    """
    flat = " ".join(hypothesis.split())   # collapse newlines + extra spaces
    if len(flat) <= max_chars:
        return flat
    # Look for the first sentence end within max_chars.
    window = flat[:max_chars]
    for terminator in (". ", "! ", "? "):
        idx = window.rfind(terminator)
        if idx > 0:
            return flat[:idx + 1]
    # Fall back to a word boundary.
    space = window.rfind(" ")
    if space > 0:
        return flat[:space] + "…"
    return window + "…"


def _docs_prompts_md(domain: str, today: str) -> str:
    return f"""# Prompt History — {domain}

<!-- Append new prompts at the bottom, newest last. Format:

## YYYY-MM-DD [optional title]
> <prompt text or short summary>

The dated H2 (`## YYYY-MM-DD`) is what `portfolio project check` parses
to surface "last AI prompt" per project. Keep entries append-only.
-->

## {today} — scaffolded via portfolio new bootstrap

> Created project skeleton. Stack chosen, scaffolding written, git initialized.
"""


def _readme_md(domain: str) -> str:
    return f"# {domain}\n\n<placeholder>\n"


def _ci_workflow() -> str:
    """Starter GitHub Actions workflow — runs `make test` on push and
    PRs. Satisfies CHECK_024 has-ci-workflow day-zero. Users can
    extend this with deploy steps as projects mature."""
    return """name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
        with:
          version: 9
      - uses: actions/setup-node@v4
        with:
          node-version: 20
          cache: pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm run build
      - run: pnpm test --if-present
"""


def _gitignore() -> str:
    return """# Node
node_modules/
.pnpm-store/
dist/
build/
.next/
.cache/

# Astro (generated content cache + types — never tracked; keeps the
# working tree clean for `project delegate`'s dirty-tree precondition)
.astro/

# Env / secrets
.env
.env.*
*.env
*.env.*

# Editor / OS
.DS_Store
*.swp
*~
.vscode/
.idea/

# Cloudflare
.wrangler/

# Caches
.eslintcache
"""


def _local_makefile(domain: str) -> str:
    return f"""PROJ := {domain}

.DEFAULT_GOAL := help

# Verify parent Makefile exists — this project is part of the sites/ workspace.
ifeq ($(wildcard ../Makefile),)
$(error This Makefile is meant to be run inside the sites/ workspace. Parent Makefile not found.)
endif

# Forward every target to the parent Makefile with proj set to this project.
# `make buildsh` (parent) drops you into the dev container; `make run` etc.
# delegate to the central builder repo (~/work/projects/builder/) under the hood.
%:
\t$(MAKE) -C .. $@ proj=$(PROJ)
"""


def _project_name(domain: str) -> str:
    """Convert a domain to a CF-friendly project name.

    Drops the TLD and any subdomain dots. e.g. `kwizicle.com` → `kwizicle`,
    `app.foo.io` → `app-foo`. Matches the user's preferred naming after
    several CF build iterations on kwizicle.
    """
    base = domain.lower().rsplit(".", 1)[0]
    base = re.sub(r"[^a-z0-9-]", "-", base).strip("-")
    return base or domain.lower().replace(".", "-")


def _wrangler_jsonc(domain: str, today_iso: str) -> str:
    """Modern Cloudflare Pages config (matches homeloom.app's known-good setup).

    Uses `assets.not_found_handling: "single-page-application"` for SPA routing
    instead of the legacy `_redirects` fallback. The `[site]` block of older
    `wrangler.toml` files is for Workers Sites — not CF Pages — and triggers
    build errors on the modern CF Pages pipeline.
    """
    return json.dumps({
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": _project_name(domain),
        "compatibility_date": today_iso,
        "assets": {
            "directory": "./dist",
            "not_found_handling": "single-page-application",
        },
    }, indent=2) + "\n"


# ---- Astro stack templates ----


def _astro_package_json(domain: str) -> str:
    project = _project_name(domain)
    return json.dumps({
        "name": project,
        "type": "module",
        "version": "0.0.1",
        "private": True,
        "homepage": f"https://{domain}/",   # CHECK_029
        "scripts": {
            "dev": "astro dev",
            "start": "astro dev",
            "build": "astro build",
            "preview": "astro preview",
            "astro": "astro",
            "test": "vitest run",
            "test:watch": "vitest",
            "test:seo": "vitest run src/__tests__/seo.test.js"
        },
        "dependencies": {
            "astro": "^5.0.0",
            "@astrojs/sitemap": "^3.2.0"
        },
        "devDependencies": {
            "vitest": "^3.0.0"
        }
    }, indent=2) + "\n"



def _astro_index(domain: str) -> str:
    return f"""---
// src/pages/index.astro
const site = "https://{domain}";
const title = "{domain}";
const description = "<fill in: 1-2 sentence value prop for SEO description>";
// Canonical MUST match the served URL incl. trailing slash (trailingSlash:
// 'always' in astro.config.mjs). For a sub-page, derive it the same way:
//   const canonical = `${{site}}/<route>/`;   // e.g. `${{site}}/about/`
// A no-slash canonical 308-redirects and breaks indexing (CHECK_161).
const canonical = `${{site}}/`;
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{title}}</title>
    <meta name="description" content={{description}} />
    <link rel="canonical" href={{canonical}} />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />

    <!-- Open Graph -->
    <meta property="og:type" content="website" />
    <meta property="og:title" content={{title}} />
    <meta property="og:description" content={{description}} />
    <meta property="og:url" content={{canonical}} />
    <meta property="og:site_name" content="{domain}" />

    <!-- Twitter card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content={{title}} />
    <meta name="twitter:description" content={{description}} />

    <!-- JSON-LD structured data: Organization + WebSite (static; domain
         is known at scaffold time. Update description by hand if needed.) -->
    <script type="application/ld+json">
{{
  "@context": "https://schema.org",
  "@graph": [
    {{
      "@type": "Organization",
      "@id": "https://{domain}/#organization",
      "name": "{domain}",
      "url": "https://{domain}/"
    }},
    {{
      "@type": "WebSite",
      "@id": "https://{domain}/#website",
      "url": "https://{domain}/",
      "name": "{domain}",
      "publisher": {{ "@id": "https://{domain}/#organization" }}
    }}
  ]
}}
    </script>
  </head>
  <body>
    <main>
      <h1>{{title}}</h1>
      <p>Scaffolded via <code>portfolio new bootstrap</code>.</p>
    </main>
  </body>
</html>
"""


# ---- Vite + React + JSX stack templates ----


def _vite_package_json(domain: str) -> str:
    project = _project_name(domain)
    return json.dumps({
        "name": project,
        "private": True,
        "version": "0.0.1",
        "type": "module",
        "homepage": f"https://{domain}/",   # CHECK_029
        "scripts": {
            "dev": "vite",
            "build": "vite build && node scripts/generate-sitemap.mjs",
            "preview": "vite preview",
            "test": "vitest run",
            "test:watch": "vitest",
            "test:seo": "vitest run src/__tests__/seo.test.js"
        },
        "dependencies": {
            "react": "^18.3.0",
            "react-dom": "^18.3.0"
        },
        "devDependencies": {
            "@vitejs/plugin-react": "^4.3.0",
            "vite": "^6.0.0",
            "vitest": "^3.0.0",
            "jsdom": "^25.0.0"
        }
    }, indent=2) + "\n"


def _vite_config() -> str:
    return """// vite.config.js
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
});
"""


def _vite_index_html(domain: str) -> str:
    site = f"https://{domain}"
    json_ld = json.dumps({
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Organization",
                "@id": f"{site}/#organization",
                "name": domain,
                "url": site,
            },
            {
                "@type": "WebSite",
                "@id": f"{site}/#website",
                "url": site,
                "name": domain,
                "publisher": {"@id": f"{site}/#organization"},
            },
        ],
    }, indent=2)
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{domain}</title>
    <meta name="description" content="<fill in: 1-2 sentence value prop for SEO description>" />
    <link rel="canonical" href="{site}" />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />

    <!-- Open Graph -->
    <meta property="og:type" content="website" />
    <meta property="og:title" content="{domain}" />
    <meta property="og:description" content="<fill in description>" />
    <meta property="og:url" content="{site}" />
    <meta property="og:site_name" content="{domain}" />

    <!-- Twitter card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content="{domain}" />
    <meta name="twitter:description" content="<fill in description>" />

    <!-- JSON-LD structured data: Organization + WebSite -->
    <script type="application/ld+json">
{json_ld}
    </script>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
"""


def _vite_main_jsx() -> str:
    return """import React from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';

createRoot(document.getElementById('root')).render(<App />);
"""


def _vite_app_jsx() -> str:
    return """export default function App() {
  return (
    <main>
      <h1>Welcome</h1>
      <p>Scaffolded via <code>portfolio new bootstrap</code>.</p>
    </main>
  );
}
"""


# ---- Favicon SVG monogram ----


FAVICON_PALETTE = (
    "#0ea5e9", "#6366f1", "#8b5cf6", "#a855f7", "#ec4899",
    "#ef4444", "#f97316", "#f59e0b", "#10b981", "#14b8a6",
    "#06b6d4", "#3b82f6",
)


def _favicon_color(domain: str) -> str:
    """Deterministic palette pick based on domain. Same domain → same color forever."""
    h = hashlib.sha256(domain.encode()).digest()
    return FAVICON_PALETTE[h[0] % len(FAVICON_PALETTE)]


def _favicon_svg(domain: str) -> str:
    """Single-letter monogram SVG. Browsers render SVG favicons natively at any size.
    No raster conversion needed — Vite's build pipeline can do it later if a
    legacy .ico is required.
    """
    base = domain.split(".")[0] or domain
    initial = (base[0] if base else "?").upper()
    color = _favicon_color(domain)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="12" fill="{color}"/>
  <text x="32" y="32"
        font-family="ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"
        font-size="40" font-weight="700" fill="white"
        text-anchor="middle" dominant-baseline="central">{initial}</text>
</svg>
"""


# ---- SEO + test scaffolding ----


def _robots_txt(domain: str, stack: str) -> str:
    # Astro uses @astrojs/sitemap, which emits sitemap-index.xml (NOT /sitemap.xml);
    # Vite uses scripts/generate-sitemap.mjs, which emits dist/sitemap.xml. Point
    # robots at whichever this stack actually produces, or Google fetches a 404.
    sitemap = "sitemap-index.xml" if stack == "astro" else "sitemap.xml"
    return f"""User-agent: *
Allow: /

Sitemap: https://{domain}/{sitemap}
"""


def _sitemap_xml(domain: str, today_iso: str) -> str:
    # Vite-only pre-build placeholder — scripts/generate-sitemap.mjs overwrites
    # dist/sitemap.xml on build. Astro never ships this (it would shadow
    # @astrojs/sitemap's sitemap-index.xml); see SEO_FILES vs VITE_FILES.
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Pre-build placeholder; the build's generate-sitemap.mjs replaces this with a
  full route scan. Lists just the home page so Google can discover the site
  before the first build runs.
-->
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://{domain}/</loc>
    <lastmod>{today_iso}</lastmod>
    <changefreq>weekly</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""


def _vitest_config() -> str:
    return """// vitest.config.js
import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    environment: 'jsdom',
    globals: true,
  },
});
"""


def _smoke_test() -> str:
    return """// src/__tests__/smoke.test.js
import { describe, it, expect } from 'vitest';

describe('smoke', () => {
  it('environment runs', () => {
    expect(1 + 1).toBe(2);
  });
});
"""


def _vite_sitemap_script(domain: str) -> str:
    """Post-build sitemap generator for Vite. Scans dist/ for .html files and
    emits dist/sitemap.xml. No deps; uses Node's built-ins.

    Matches cricketfansite.com's existing convention: chained into the
    package.json `build` script as `vite build && node scripts/generate-sitemap.mjs`.
    """
    return f"""// scripts/generate-sitemap.mjs
// Post-build sitemap generator. Scans dist/ for .html files and emits
// dist/sitemap.xml. Run via the chained build script.

import {{ readdirSync, statSync, writeFileSync }} from 'node:fs';
import {{ join, posix }} from 'node:path';

const SITE = (process.env.VITE_SITE_URL || 'https://{domain}').replace(/\\/$/, '');
const DIST = 'dist';

function scan(dir, base = '') {{
  const out = [];
  for (const entry of readdirSync(dir)) {{
    const full = join(dir, entry);
    const stat = statSync(full);
    if (stat.isDirectory()) {{
      out.push(...scan(full, posix.join(base, entry)));
    }} else if (entry.endsWith('.html')) {{
      const route = entry === 'index.html'
        ? (base ? '/' + base : '/')
        : '/' + posix.join(base, entry.replace(/\\.html$/, ''));
      out.push(route);
    }}
  }}
  return out;
}}

let routes;
try {{
  routes = scan(DIST).sort();
}} catch (err) {{
  console.error(`generate-sitemap: cannot read ${{DIST}}/ — did vite build run?`);
  process.exit(1);
}}

const today = new Date().toISOString().slice(0, 10);
const xml = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${{routes.map(r => `  <url>
    <loc>${{SITE}}${{r}}</loc>
    <lastmod>${{today}}</lastmod>
    <changefreq>weekly</changefreq>
  </url>`).join('\\n')}}
</urlset>
`;
writeFileSync(join(DIST, 'sitemap.xml'), xml);
console.log(`generate-sitemap: wrote ${{routes.length}} URL(s) to ${{DIST}}/sitemap.xml`);
"""


def _astro_config_with_sitemap(domain: str) -> str:
    return f"""// astro.config.mjs
import {{ defineConfig }} from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({{
  site: 'https://{domain}',
  // trailingSlash: 'always' — directory format serves /<page>/ and
  // @astrojs/sitemap lists /<page>/, so a page's <link rel="canonical">
  // MUST also end in a slash. A canonical of /<page> (no slash) 308-redirects
  // to /<page>/ — Google then can't settle on a canonical and the page comes
  // back "URL is unknown to Google". Make it explicit so every page's
  // canonical matches its served URL. Enforced by CHECK_161.
  trailingSlash: 'always',
  integrations: [sitemap()],
  output: 'static',
}});
"""


def _seo_test_vite(domain: str) -> str:
    domain_re = domain.replace(".", "\\\\.")
    return """// src/__tests__/seo.test.js
// Technical-SEO regression check. Asserts that the v3.B SEO baseline tags
// remain present in index.html. Catches regressions if a future edit
// accidentally strips the meta block.
//
// Does NOT assert the description placeholder has been filled in — that's
// your job. It only checks the structural pieces are still there.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const html = readFileSync(join(process.cwd(), 'index.html'), 'utf8');

describe('SEO baseline (index.html)', () => {
  it('has a <title>', () => {
    expect(html).toMatch(/<title>[^<]+<\\/title>/);
  });

  it('has <meta name="description">', () => {
    expect(html).toMatch(/<meta\\s+name="description"\\s+content="[^"]+"/);
  });

  it('has <link rel="canonical">', () => {
    expect(html).toMatch(/<link\\s+rel="canonical"\\s+href="https?:\\/\\/[^"]+"/);
  });

  it('has Open Graph tags', () => {
    expect(html).toMatch(/property="og:title"/);
    expect(html).toMatch(/property="og:url"/);
    expect(html).toMatch(/property="og:type"/);
  });

  it('has Twitter card meta', () => {
    expect(html).toMatch(/name="twitter:card"/);
  });

  it('has favicon link', () => {
    expect(html).toMatch(/<link\\s+rel="icon"[^>]*href="\\/favicon\\.svg"/);
  });

  it('has JSON-LD Organization + WebSite', () => {
    expect(html).toMatch(/<script\\s+type="application\\/ld\\+json"/);
    expect(html).toMatch(/"@type":\\s*"Organization"/);
    expect(html).toMatch(/"@type":\\s*"WebSite"/);
  });

  it('canonical URL points to __DOMAIN__', () => {
    expect(html).toMatch(/canonical"\\s+href="https?:\\/\\/__DOMAIN_RE__/);
  });
});
""".replace("__DOMAIN__", domain).replace("__DOMAIN_RE__", domain_re)


def _seo_test_astro(domain: str) -> str:
    return """// src/__tests__/seo.test.js
// Technical-SEO regression check for Astro. Reads src/pages/index.astro,
// strips frontmatter, asserts the v3.B SEO baseline tags remain.

import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';

const raw = readFileSync(join(process.cwd(), 'src', 'pages', 'index.astro'), 'utf8');
// Strip frontmatter (between leading `---` markers) so we just check the HTML body.
const html = raw.replace(/^---[\\s\\S]*?---\\n/, '');

describe('SEO baseline (src/pages/index.astro)', () => {
  it('has a <title>', () => {
    expect(html).toMatch(/<title>/);
  });

  it('has <meta name="description">', () => {
    expect(html).toMatch(/<meta\\s+name="description"/);
  });

  it('has <link rel="canonical">', () => {
    expect(html).toMatch(/<link\\s+rel="canonical"/);
  });

  it('has Open Graph tags', () => {
    expect(html).toMatch(/property="og:title"/);
    expect(html).toMatch(/property="og:url"/);
  });

  it('has Twitter card meta', () => {
    expect(html).toMatch(/name="twitter:card"/);
  });

  it('has favicon link', () => {
    expect(html).toMatch(/<link\\s+rel="icon"[^>]*href="\\/favicon\\.svg"/);
  });

  it('has JSON-LD Organization + WebSite', () => {
    expect(html).toMatch(/application\\/ld\\+json/);
    expect(html).toMatch(/"@type":\\s*"Organization"/);
    expect(html).toMatch(/"@type":\\s*"WebSite"/);
  });
});
"""


# ---- Ingester template ----


def _ingester_template() -> str:
    return '''"""ingest.py — template for projects that scrape data and feed the app.

Edit this to your specific data source. Run periodically via cron, GitHub
Actions, or a manual `make ingest`.
"""
from __future__ import annotations

import json
from pathlib import Path


DATA_OUT = Path(__file__).resolve().parents[1] / "src" / "data" / "items.json"


def fetch() -> list[dict]:
    """Fetch raw data from the source. Replace with your scraping logic."""
    return [
        {"id": 1, "title": "Example item", "url": "https://example.com/"}
    ]


def transform(raw: list[dict]) -> list[dict]:
    """Normalize, dedupe, enrich. Project-specific."""
    return raw


def write(items: list[dict]) -> None:
    DATA_OUT.parent.mkdir(parents=True, exist_ok=True)
    DATA_OUT.write_text(json.dumps(items, indent=2) + "\\n")


if __name__ == "__main__":
    items = transform(fetch())
    write(items)
    print(f"wrote {len(items)} items to {DATA_OUT}")
'''


def _ingester_readme() -> str:
    return """# scripts/

Build-time / data-pipeline helpers for this project.

- `ingest.py` — template ingester. Edit for your data source. Output goes to
  `src/data/items.json` by default; the app reads from there.

Run manually: `python scripts/ingest.py`
Run scheduled: wire into a `make ingest` target or GitHub Action.
"""


# ---------- file writers ----------


COMMON_FILES = [
    ("AI_AGENTS.md", "ai_agents"),
    ("README.md", "readme"),
    (".gitignore", "gitignore"),
    (".env.example", "env_example"),               # CHECK_011
    ("Makefile", "makefile"),
    ("docs/prd.md", "prd"),
    ("docs/CLAUDE.md", "claude"),                  # CHECK_006 + CHECK_026
    ("docs/Prompts.md", "prompts"),
    ("docs/growth.md", "growth"),
    (".github/workflows/ci.yml", "ci_workflow"),   # CHECK_024
]

# NOTE: public/sitemap.xml is intentionally NOT here — it's stack-specific.
# Astro emits sitemap-index.xml via @astrojs/sitemap (a stub would shadow it);
# Vite ships the stub as a pre-build placeholder (see VITE_FILES).
SEO_FILES = [
    ("public/robots.txt", "robots"),
    ("public/favicon.svg", "favicon_svg"),
    ("vitest.config.js", "vitest_config"),
    ("src/__tests__/smoke.test.js", "smoke_test"),
]

ASTRO_FILES = [
    ("package.json", "astro_pkg"),
    ("astro.config.mjs", "astro_config"),
    ("src/pages/index.astro", "astro_index"),
    ("src/__tests__/seo.test.js", "seo_test_astro"),
]

VITE_FILES = [
    ("package.json", "vite_pkg"),
    ("vite.config.js", "vite_config"),
    ("index.html", "vite_index_html"),
    ("src/main.jsx", "vite_main"),
    ("src/App.jsx", "vite_app"),
    ("public/sitemap.xml", "sitemap"),
    ("scripts/generate-sitemap.mjs", "vite_sitemap_script"),
    ("src/__tests__/seo.test.js", "seo_test_vite"),
]

INGESTER_FILES = [
    ("scripts/ingest.py", "ingester"),
    ("scripts/README.md", "ingester_readme"),
]


def _render(key: str, domain: str, stack: str, topic: str, today: str,
            operator_inputs: dict[str, str] | None = None,
            growth_hypothesis: str = "") -> str:
    if key == "ai_agents":
        return _ai_agents_md(domain, stack, topic, operator_inputs)
    if key == "readme":
        return _readme_md(domain)
    if key == "gitignore":
        return _gitignore()
    if key == "makefile":
        return _local_makefile(domain)
    if key == "prd":
        return _docs_prd_md(domain, topic)
    if key == "prompts":
        return _docs_prompts_md(domain, today)
    if key == "growth":
        return _docs_growth_md(domain, today, growth_hypothesis)
    if key == "claude":
        # v6.A.1: write docs/CLAUDE.md to satisfy CHECK_006 + CHECK_026 day-zero.
        from . import templates as _templates
        return _templates.docs_claude_md(domain)
    if key == "env_example":
        # v6.A.1: write .env.example to satisfy CHECK_011 day-zero.
        from . import templates as _templates
        return _templates.env_example()
    if key == "ci_workflow":
        # v6.A.1: write a starter GitHub Actions workflow so CHECK_024
        # passes day-zero. Runs `make test` on push to main + PRs.
        return _ci_workflow()
    if key == "astro_pkg":
        return _astro_package_json(domain)
    if key == "astro_config":
        return _astro_config_with_sitemap(domain)
    if key == "astro_index":
        return _astro_index(domain)
    if key == "seo_test_astro":
        return _seo_test_astro(domain)
    if key == "vite_sitemap_script":
        return _vite_sitemap_script(domain)
    if key == "seo_test_vite":
        return _seo_test_vite(domain)
    if key == "vite_pkg":
        return _vite_package_json(domain)
    if key == "vite_config":
        return _vite_config()
    if key == "vite_index_html":
        return _vite_index_html(domain)
    if key == "vite_main":
        return _vite_main_jsx()
    if key == "vite_app":
        return _vite_app_jsx()
    if key == "robots":
        return _robots_txt(domain, stack)
    if key == "sitemap":
        return _sitemap_xml(domain, today)
    if key == "favicon_svg":
        return _favicon_svg(domain)
    if key == "vitest_config":
        return _vitest_config()
    if key == "smoke_test":
        return _smoke_test()
    if key == "ingester":
        return _ingester_template()
    if key == "ingester_readme":
        return _ingester_readme()
    raise BootstrapError(f"unknown template key: {key}")


def _write_files(
    project_dir: Path,
    spec: list[tuple[str, str]],
    domain: str,
    stack: str,
    topic: str,
    today: str,
    skip_existing: bool,
    operator_inputs: dict[str, str] | None = None,
    growth_hypothesis: str = "",
) -> tuple[list[str], list[str]]:
    """Write spec files to project_dir. Returns (written, skipped) relative paths."""
    written: list[str] = []
    skipped: list[str] = []
    for rel, key in spec:
        path = project_dir / rel
        if path.exists() and skip_existing:
            skipped.append(rel)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(_render(key, domain, stack, topic, today,
                                operator_inputs, growth_hypothesis))
        written.append(rel)
    return written, skipped


# ---------- genai copy + CF safety ----------


def _copy_from_genai(project_dir: Path) -> tuple[list[str], list[str]]:
    """Copy contents of project_dir/genai/ to project_dir/. Returns (copied, warnings)."""
    src = project_dir / "genai"
    if not src.exists() or not src.is_dir():
        raise BootstrapError(f"genai/ not found at {src}")
    pkg = src / "package.json"
    if not pkg.exists():
        raise BootstrapError(f"genai/package.json not found — is this a real project export?")

    copied: list[str] = []
    warnings: list[str] = []
    for item in src.iterdir():
        if item.name in (".git", "node_modules", ".pnpm-store"):
            warnings.append(f"skipped {item.name} from genai (would be re-installed)")
            continue
        dest = project_dir / item.name
        if dest.exists():
            warnings.append(f"target {item.name} exists; left genai's copy in place under genai/")
            continue
        if item.is_dir():
            shutil.copytree(item, dest)
        else:
            shutil.copy2(item, dest)
        copied.append(item.name)
    return copied, warnings


def _bump_vite_version(pkg_path: Path) -> str | None:
    """If package.json declares vite < MIN_VITE_MAJOR, bump to ^MIN_VITE_MAJOR.0.0. Returns the change message or None."""
    if not pkg_path.exists():
        return None
    try:
        pkg = json.loads(pkg_path.read_text())
    except json.JSONDecodeError:
        return None
    changed = None
    for key in ("dependencies", "devDependencies"):
        deps = pkg.get(key) or {}
        v = deps.get("vite")
        if not v:
            continue
        m = re.search(r"(\d+)", v)
        if not m:
            continue
        current_major = int(m.group(1))
        if current_major < MIN_VITE_MAJOR:
            new = f"^{MIN_VITE_MAJOR}.0.0"
            deps["vite"] = new
            pkg[key] = deps
            changed = f"bumped vite {v} → {new} in {key}"
    if changed:
        pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
    return changed


def _remove_redirects_files(project_dir: Path) -> list[str]:
    """Remove _redirects files (per Cloudflare Pages convention: no SPA fallback). Returns list of paths removed."""
    removed: list[str] = []
    for candidate in (project_dir / "_redirects", project_dir / "public" / "_redirects"):
        if candidate.exists():
            candidate.unlink()
            removed.append(str(candidate.relative_to(project_dir)))
    return removed


def _add_wrangler_jsonc(project_dir: Path, domain: str, today_iso: str) -> bool:
    """Add wrangler.jsonc if missing. Returns True if added, False if already present."""
    path = project_dir / "wrangler.jsonc"
    if path.exists():
        return False
    path.write_text(_wrangler_jsonc(domain, today_iso))
    return True


CF_HEADERS_TEMPLATE = """/assets/*
  Cache-Control: public, max-age=31536000, immutable

/*.html
  Cache-Control: public, max-age=0, must-revalidate

/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
"""


def _add_cf_headers(project_dir: Path) -> bool:
    """Add public/_headers (CF cache + security) if missing. Returns True if added."""
    path = project_dir / "public" / "_headers"
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(CF_HEADERS_TEMPLATE)
    return True


NON_PNPM_LOCKFILES = (
    ("bun.lockb", "bun"),
    ("bun.lock", "bun"),
    ("package-lock.json", "npm"),
    ("yarn.lock", "yarn"),
)
NON_PNPM_CONFIG_FILES = (
    ".bunfig.toml",
    ".npmrc.bun",
)


def _ensure_pnpm_only(project_dir: Path) -> list[str]:
    """Strip non-pnpm lockfiles + config so CF Pages picks pnpm deterministically.

    Lovable exports often ship multiple lockfiles (bun.lockb + package-lock.json
    + pnpm-lock.yaml). CF picks one — sometimes the wrong one — and the build
    fails. Removing all but pnpm-lock.yaml fixes this.

    Also normalizes `packageManager` field in package.json to pnpm if it's
    set to bun or yarn.
    """
    fixes: list[str] = []
    for name, mgr in NON_PNPM_LOCKFILES:
        path = project_dir / name
        if path.exists():
            path.unlink()
            fixes.append(f"removed {name} (pnpm-only convention; CF Pages was picking {mgr} and breaking)")
    for name in NON_PNPM_CONFIG_FILES:
        path = project_dir / name
        if path.exists():
            path.unlink()
            fixes.append(f"removed {name} (pnpm-only convention)")

    pkg_path = project_dir / "package.json"
    if pkg_path.exists():
        try:
            pkg = json.loads(pkg_path.read_text())
        except json.JSONDecodeError:
            pkg = None
        if pkg and "packageManager" in pkg:
            current = pkg["packageManager"]
            if not current.startswith("pnpm"):
                pkg["packageManager"] = "pnpm@9.0.0"
                pkg_path.write_text(json.dumps(pkg, indent=2) + "\n")
                fixes.append(f"normalized package.json packageManager: {current} → pnpm@9.0.0")

    return fixes


# v18.D — GA4 property auto-creation.
# Returns (measurement_id, status_message). Bootstrap stores both on
# the result and writes measurement_id into lamill.toml [analytics]
# when present. All failure modes are soft (bootstrap continues
# without GA4 wired) — GA4 is a per-site nice-to-have, not a
# load-bearing prerequisite for the actual deploy.
def _maybe_create_ga4_property(
    domain: str, *, skip_ga4: bool,
) -> tuple[str | None, str]:
    """Try to provision a GA4 property + web stream for `domain`.

    Returns `(measurement_id, status)` where:
      - `(G-XXXXXX, "created")` on success
      - `(None, "skipped:<reason>")` for any expected skip path
      - `(None, "failed:<truncated error>")` on Admin API failure

    Skip paths (in priority order):
      1. `skip_ga4=True` — operator passed `--skip-ga4`
      2. GA4 OAuth not configured (no `~/lamill/ga4/token.json`)
      3. `GA4_ACCOUNT_ID` not set in apikeys

    Caller (bootstrap) writes status + measurement_id to
    `BootstrapResult`; CLI renders both after bootstrap completes.
    """
    if skip_ga4:
        return (None, "skipped:--skip-ga4")

    from . import apikeys, ga4_admin

    if not ga4_admin.has_token():
        return (
            None,
            "skipped:GA4 OAuth not configured "
            "(run `lamill settings ga4 auth`)",
        )

    account_id = apikeys.get_key("GA4_ACCOUNT_ID")
    if not account_id:
        return (
            None,
            "skipped:GA4_ACCOUNT_ID not set "
            "(run `lamill settings apikeys set GA4_ACCOUNT_ID <id>`)",
        )

    try:
        property_id = ga4_admin.create_property(account_id, domain)
        _stream_id, measurement_id = ga4_admin.create_web_stream(
            property_id, f"https://{domain}/",
        )
    except ga4_admin.GA4AdminError as e:
        msg = str(e)
        if len(msg) > 200:
            msg = msg[:200] + "..."
        return (None, f"failed:{msg}")

    return (measurement_id, "created")


def _remove_legacy_wrangler_toml(project_dir: Path) -> bool:
    """Remove any wrangler.toml left from older bootstraps (legacy Workers Sites
    format breaks modern CF Pages builds). Returns True if removed."""
    path = project_dir / "wrangler.toml"
    if not path.exists():
        return False
    path.unlink()
    return True


def _apply_cf_safety_fixes(project_dir: Path, domain: str, today_iso: str) -> list[str]:
    """Apply Cloudflare Pages safety fixes after a genai-copy. Returns list of fix descriptions."""
    fixes: list[str] = []
    bumped = _bump_vite_version(project_dir / "package.json")
    if bumped:
        fixes.append(bumped)
    fixes.extend(_ensure_pnpm_only(project_dir))
    removed = _remove_redirects_files(project_dir)
    for r in removed:
        fixes.append(f"removed {r} (handled by wrangler.jsonc not_found_handling instead)")
    if _remove_legacy_wrangler_toml(project_dir):
        fixes.append("removed legacy wrangler.toml (Workers Sites format breaks CF Pages)")
    if _add_wrangler_jsonc(project_dir, domain, today_iso):
        fixes.append("wrote wrangler.jsonc with assets + SPA not_found_handling (matches homeloom.app convention)")
    if _add_cf_headers(project_dir):
        fixes.append("wrote public/_headers (cache + security headers, copied to dist/ at build)")
    return fixes


# ---------- git ----------


def _git_init_and_commit(project_dir: Path, msg: str) -> tuple[bool, str | None]:
    """Run git init + git add . + git commit. Returns (initialized, sha)."""
    try:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "add", "."], cwd=project_dir, check=True, capture_output=True, text=True)
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=project_dir, check=True, capture_output=True, text=True)
        rc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project_dir, capture_output=True, text=True)
        sha = rc.stdout.strip() if rc.returncode == 0 else None
        return True, sha
    except subprocess.CalledProcessError:
        return False, None
    except FileNotFoundError:
        return False, None


def _clone_to_genai(project_dir: Path, git_url: str) -> None:
    """Clone a remote into project_dir/genai/. Project dir must already exist."""
    target = project_dir / "genai"
    if target.exists():
        raise BootstrapError(f"target {target} already exists — refusing to clone over it")
    try:
        subprocess.run(
            ["git", "clone", "--quiet", git_url, str(target)],
            check=True, capture_output=True, text=True,
        )
    except subprocess.CalledProcessError as e:
        raise BootstrapError(f"git clone failed: {e.stderr.strip() or e.stdout.strip() or 'unknown error'}")
    except FileNotFoundError:
        raise BootstrapError("git not found on PATH; install git to use --git-url")
    inner_git = target / ".git"
    if inner_git.exists() and inner_git.is_dir():
        # Detach the cloned history — we'll create a fresh project repo below.
        # The cloned source's git log isn't useful at the project root.
        shutil.rmtree(inner_git)


# ---------- main ----------


# v29.D — [content] fields whose blankness gates the "Fill in [content]"
# starter todo. The canonical list lives in `lamill_toml_edit`
# (`CONTENT_TODO_FIELDS`, derived from `_CONTENT_FIELDS`, `law` excluded)
# and is reused by the v29.F backfill fixer — single source of truth.
from .lamill_toml_edit import CONTENT_TODO_FIELDS as _CONTENT_TODO_FIELDS


def _content_blanks(content_values: dict | None) -> list[str]:
    """The `_CONTENT_TODO_FIELDS` left blank by derivation. `None` (no
    derivation attempted) → all of them, preserving pre-v29.D behavior
    where the fill-in todo always fired."""
    if not content_values:
        return list(_CONTENT_TODO_FIELDS)
    return [f for f in _CONTENT_TODO_FIELDS if not content_values.get(f)]


def bootstrap_starter_todos(today=None, content_values=None):
    """v27.I — the starter-set todos `new bootstrap` seeds into a new
    site's `[[todo]]` table.

    Due dates are text-only (baked into the task string) per the v27
    decision — no schema field. The SEO check is `medium` so it doesn't
    surface in `fleet focus` (high-only) the day the site is bootstrapped;
    the `[content]` fill-in is `high` so focus nudges it until done.
    `today` is injectable for deterministic tests.

    v29.D — `content_values` is the derived `[content]` dict (ADR-0019).
    The "Fill in [content]" todo is seeded only for the fields left blank,
    naming them; a fully-derived block ships todo-free. With
    `content_values=None` (no derivation) the todo lists every field, as
    before.
    """
    from .lamill_toml import TodoItem
    from .lamill_toml_edit import due_hint
    todos = []
    blanks = _content_blanks(content_values)
    if blanks:
        todos.append(TodoItem(
            status="open", priority="high",
            task="Fill in [content] block: " + ", ".join(blanks)))
    todos += [
        TodoItem(status="open", priority="medium",
                 task="Check SEO: GSC indexation + coverage" + due_hint("+14d", today=today)),
        TodoItem(status="open", priority="medium",
                 task="Verify GA4 is receiving data (check Realtime after first traffic)"),
        TodoItem(status="open", priority="low",
                 task="Confirm GSC verification + sitemap submitted (re-run deploy if it timed out)"),
    ]
    return todos


def detect_stack_from_pkg(project_dir: Path) -> str:
    """If package.json exists, infer stack. Default 'vite' if React; 'astro'
    if astro dep; else fallback. Crude astro/vite/unknown vocab on purpose —
    this is the new-bootstrap path, distinct from `stack_classifier` (fleet
    drift) and `stack_translate` (Lovable port). Shares only the dep-merge
    primitive (v35.C)."""
    from .stack_classifier import merged_deps

    pkg_path = project_dir / "package.json"
    if not pkg_path.exists():
        return "vite"
    try:
        pkg = json.loads(pkg_path.read_text())
    except json.JSONDecodeError:
        return "vite"
    deps = merged_deps(pkg)
    if "astro" in deps:
        return "astro"
    if "vite" in deps or "react" in deps:
        return "vite"
    return "unknown"


def _rollback_project_dir(project_dir: Path) -> None:
    """v15.K — best-effort rollback after a bootstrap failure.

    Removes `project_dir` and everything inside it. When the dir
    contains Docker-owned files (e.g. `genai/node_modules/` from
    Lovable exports built inside Docker), `shutil.rmtree` may hit
    PermissionError from the host's perspective. We catch + warn-
    skip + leave the residue for the operator to clean up manually
    (instructions provided).

    Called from the `bootstrap()` exception handler. Never re-raises
    from inside this function — the underlying bootstrap failure is
    the signal the caller surfaces.
    """
    import shutil

    if not project_dir.exists():
        return
    try:
        shutil.rmtree(project_dir)
        print(f"[rollback] removed {project_dir}")
    except PermissionError:
        # Likely Docker-owned files inside genai/node_modules/.
        # Best-effort: ignore_errors=True cleans what we can.
        shutil.rmtree(project_dir, ignore_errors=True)
        leftover = project_dir if project_dir.exists() else None
        if leftover is not None:
            print(
                f"[rollback] partial cleanup of {project_dir}: some files "
                f"(likely root-owned from Docker builds) need manual "
                f"removal. Inside the sites docker container, run: "
                f"`rm -rf /usr/src/app/{project_dir.name}`."
            )
        else:
            print(f"[rollback] removed {project_dir}")


def bootstrap(
    domain: str,
    stack: str = "astro",
    from_genai: bool = False,
    git_url: str | None = None,
    with_ingester: bool = False,
    topic: str = "",
    sites_root: Path | None = None,
    today_iso: str | None = None,
    operator_inputs: dict[str, str] | None = None,
    growth_hypothesis: str = "",
    platform: str | None = None,
    translation_budget_usd: float | None = None,
    translate_now: bool = False,
    skip_ga4: bool = False,
) -> BootstrapResult:
    """Top-level orchestration. Always called with already-validated domain.

    Path selection precedence:
      git_url    → create dir + clone URL into genai/ + treat as from_genai
      from_genai → genai/ must exist; copy + CF fixes
      else      → template path (dir must NOT exist)

    `operator_inputs` (v9.B) is a {heading → content} dict carrying
    operator-supplied content for the 5 AI_AGENTS canonical
    operator-input sections (Summary / Audience / ICP / Goals /
    Content strategy). Sections with non-empty content land in the
    rendered file; empty values keep the `(to be filled in)`
    placeholder. None = no operator input (all placeholders).

    `growth_hypothesis` (v9.D) is the operator's stated bet for how
    the site reaches its audience — gets embedded as the first dated
    H2 entry in `docs/growth.md` under a new `Hypothesis:` field
    (and the entry's H2 title becomes a short summary of that bet).
    Empty string → docs/growth.md ships with the pre-v9.D "site
    scaffolded; growth log started" entry.
    """
    domain = validate_domain(domain)
    sites = sites_root or SITES_ROOT
    project_dir = sites / domain
    today = today_iso or date.today().isoformat()

    # v15.K — transactional rollback. Track whether THIS run created
    # the project dir; on any exception in the body below, remove it
    # so the operator can re-run from clean state. Pre-existing dirs
    # (operator-typo or stale state) detected at pre-flight + refused
    # with a "won't clobber" BootstrapError — those errors fire BEFORE
    # the flag is set, so they don't trigger rollback.
    _we_created_dir = False

    try:
        return _bootstrap_inner(
            domain=domain, stack=stack, from_genai=from_genai,
            git_url=git_url, with_ingester=with_ingester, topic=topic,
            sites_root=sites_root, sites=sites, project_dir=project_dir,
            today=today,
            operator_inputs=operator_inputs,
            growth_hypothesis=growth_hypothesis,
            platform=platform,
            translation_budget_usd=translation_budget_usd,
            translate_now=translate_now,
            skip_ga4=skip_ga4,
            _dir_tracker=lambda: _set_we_created_dir(),
        )
    except Exception:
        # Rollback only if we created the dir in this run.
        if _we_created_dir_value[0]:
            _rollback_project_dir(project_dir)
        raise


# Helper closure for the v15.K rollback bookkeeping. Python's
# nested-function variable rebinding is awkward; using a 1-element
# list lets the inner function flip the flag observably from the
# outer try/except.
_we_created_dir_value: list[bool] = [False]


def _set_we_created_dir() -> None:
    _we_created_dir_value[0] = True


def _bootstrap_inner(
    *,
    domain: str, stack: str, from_genai: bool,
    git_url: str | None, with_ingester: bool, topic: str,
    sites_root: Path | None, sites: Path, project_dir: Path,
    today: str,
    operator_inputs: dict[str, str] | None,
    growth_hypothesis: str,
    platform: str | None,
    translation_budget_usd: float | None,
    translate_now: bool,
    skip_ga4: bool,
    _dir_tracker,
) -> BootstrapResult:
    """Inner body of bootstrap. Wrapped by `bootstrap()` for v15.K
    transactional rollback."""

    # Reset the rollback-tracker for this run (covers consecutive
    # in-process calls in tests).
    _we_created_dir_value[0] = False

    if git_url:
        if project_dir.exists():
            raise BootstrapError(
                f"{project_dir} already exists — refusing to clobber. "
                f"If you already cloned to {project_dir}/genai/, use --from-genai instead."
            )
        project_dir.mkdir(parents=True)
        _dir_tracker()
        _clone_to_genai(project_dir, git_url)
        from_genai = True  # fall through to the same handling below

    if from_genai:
        if not project_dir.exists():
            raise BootstrapError(f"--from-genai requires {project_dir} to already exist with a genai/ subdir")

        # v15.H per ADR-0013 — detect the cloned repo's stack. If
        # non-Astro, translate to Astro+Vite via Claude subprocess
        # BEFORE running `_copy_from_genai` (which would otherwise
        # copy non-Astro source verbatim to root).
        from .stack_translate import (
            STACK_ASTRO,
            STACK_UNKNOWN,
            StackTranslationError,
            detect_stack,
            translate_to_astro,
            validate_translation,
        )

        genai_dir = project_dir / "genai"
        stack_detection = detect_stack(genai_dir)

        if stack_detection.stack == STACK_ASTRO:
            # Source is already Astro+Vite — existing direct-copy path.
            copied, copy_warnings = _copy_from_genai(project_dir)
        elif stack_detection.stack == STACK_UNKNOWN:
            # No translation policy for unknown stacks — bail.
            raise BootstrapError(
                f"genai/ stack is unknown (signals: "
                f"{', '.join(stack_detection.signals)}). lamill can only "
                f"bootstrap Astro+Vite projects via --git-url. Either fix "
                f"the source repo's package.json or use blank bootstrap "
                f"(no --git-url)."
            )
        else:
            # v15.M (ADR-0013) — non-Astro source. Decoupled translation:
            # bootstrap finishes fast by scaffolding a blank Astro+Vite
            # project at root + leaving `genai/` untouched as untranslated
            # reference. Operator runs `lamill project translate <domain>`
            # separately when ready — that verb does the slow Claude-driven
            # port from `genai/` into the existing scaffold (smaller delta
            # than the v15.H from-scratch translation).
            #
            # v15.H synchronous translation preserved via `translate_now`
            # parameter (still useful for tests + operators who want it).
            if translate_now:
                console_translate_msg = (
                    f"genai/ stack is `{stack_detection.stack}` "
                    f"(signals: {', '.join(stack_detection.signals)}); "
                    f"translating to Astro+Vite via Claude subprocess "
                    f"synchronously (ADR-0013; --translate-now)..."
                )
                print(console_translate_msg)
                translate_kwargs = {"detection": stack_detection}
                if translation_budget_usd is not None:
                    translate_kwargs["budget_usd"] = translation_budget_usd
                result = translate_to_astro(project_dir, **translate_kwargs)
                if not result.ok:
                    raise StackTranslationError(
                        f"Claude translation failed: {result.error}. "
                        f"Output: {result.raw_output[:300]}"
                    )
                validation = validate_translation(project_dir)
                if not validation.ok:
                    raise StackTranslationError(
                        f"Translator output failed validation: "
                        f"{'; '.join(validation.issues)}"
                    )
                copied = ["<translated by Claude subprocess>"]
                copy_warnings = []
                stack = "astro"
            else:
                # Default path: defer translation. Scaffold blank Astro at
                # root using the template path; mark translation as pending
                # via a `.lamill-translation-pending` marker file so
                # `lamill project translate` knows what to port.
                print(
                    f"genai/ stack is `{stack_detection.stack}` "
                    f"(signals: {', '.join(stack_detection.signals)}); "
                    f"scaffolding blank Astro+Vite + deferring translation "
                    f"(v15.M)..."
                )
                # Write Astro template files at project root. The genai/
                # subdir stays untouched as untranslated reference.
                from_genai_stack_spec = ASTRO_FILES
                written, _skipped = _write_files(
                    project_dir, from_genai_stack_spec, domain, "astro", topic,
                    today, skip_existing=False,
                    operator_inputs=operator_inputs,
                    growth_hypothesis=growth_hypothesis,
                )
                # Marker file for `project translate` to read.
                marker = project_dir / ".lamill-translation-pending"
                marker.write_text(
                    json.dumps({
                        "schema": 1,
                        "source_stack": stack_detection.stack,
                        "source_signals": list(stack_detection.signals),
                        "scaffolded_at": today,
                        "next_step": (
                            "Run `lamill project translate <domain>` to "
                            "port pages/components from genai/ into the "
                            "Astro scaffold. Budget defaults to $5.00, "
                            "timeout to 30 minutes; both configurable via "
                            "--budget / --timeout flags."
                        ),
                    }, indent=2),
                )
                copied = list(written)
                copy_warnings = [
                    f"genai/ contains untranslated {stack_detection.stack} "
                    f"source — run `lamill project translate {domain}` to "
                    f"port pages/components into the Astro scaffold."
                ]
                stack = "astro"

        # Re-detect stack from package.json after copy/translation.
        if stack_detection.stack == STACK_ASTRO:
            detected = detect_stack_from_pkg(project_dir)
            if detected != "unknown":
                stack = detected
        result = BootstrapResult(
            project_dir=project_dir,
            stack=stack,
            path="git-url" if git_url else "genai",
            files_copied=copied,
            warnings=list(copy_warnings),
        )
    else:
        if project_dir.exists():
            raise BootstrapError(
                f"{project_dir} already exists — refusing to clobber. "
                "Use --from-genai if you have a Lovable export at sites/<domain>/genai/, "
                "or --git-url=<url> to clone one."
            )
        project_dir.mkdir(parents=True)
        _dir_tracker()
        # Stack-specific files first.
        stack_spec = ASTRO_FILES if stack == "astro" else VITE_FILES if stack == "vite" else None
        if stack_spec is None:
            raise BootstrapError(f"unsupported --stack: {stack!r}. Use 'astro' or 'vite'.")
        written, _skipped = _write_files(project_dir, stack_spec, domain, stack, topic, today, skip_existing=False, operator_inputs=operator_inputs, growth_hypothesis=growth_hypothesis)
        result = BootstrapResult(
            project_dir=project_dir,
            stack=stack,
            path="template",
            files_written=list(written),
        )

    # Common scaffolding files. On --from-genai, skip files that genai already provided.
    skip_existing = (result.path != "template")
    common_written, common_skipped = _write_files(
        project_dir, COMMON_FILES, domain, stack, topic, today,
        skip_existing=skip_existing, operator_inputs=operator_inputs,
        growth_hypothesis=growth_hypothesis,
    )
    result.files_written.extend(common_written)
    if common_skipped:
        result.warnings.append(f"left {len(common_skipped)} pre-existing common file(s) untouched: {', '.join(common_skipped)}")

    # CF safety fixes apply to BOTH paths — every bootstrapped project ships with
    # wrangler.jsonc + public/_headers matching the homeloom.app convention.
    result.cf_fixes = _apply_cf_safety_fixes(project_dir, domain, today)

    # SEO + test baseline: robots.txt, sitemap.xml stub, vitest config, smoke test.
    # Skip if the project already has them (genai exports often include their own).
    seo_written, _ = _write_files(project_dir, SEO_FILES, domain, stack, topic, today, skip_existing=True)
    result.files_written.extend(seo_written)

    if with_ingester:
        ing_written, _ = _write_files(project_dir, INGESTER_FILES, domain, stack, topic, today, skip_existing=skip_existing)
        result.files_written.extend(ing_written)

    # v18.D — try to auto-provision a GA4 property + web stream for
    # this domain before writing lamill.toml so the measurement ID
    # (if any) can land in the [analytics] block. All failure modes
    # are soft — bootstrap continues without GA4 wired.
    measurement_id, ga4_status = _maybe_create_ga4_property(
        domain, skip_ga4=skip_ga4,
    )
    result.ga4_status = ga4_status
    result.ga4_measurement_id = measurement_id

    # v10.C — write `lamill.toml` declaring the deploy target.
    # Platform priority: explicit `--platform` flag → infer from
    # on-disk configs (wrangler.jsonc / vercel.json / netlify.toml
    # — by now the CF safety fixes have written wrangler.jsonc so
    # the template path always detects cf-pages) → default `cf-pages`
    # (per `prd.md` v10 design notes resolution 10.C).
    if not (project_dir / "lamill.toml").exists():
        from .lamill_toml import (
            AnalyticsBlock,
            DeployBlock,
            HOSTING_REQUIRED_PLATFORMS,
            LamillToml,
            PLATFORM_VALUES,
            STACK_FRAMEWORK_VALUES,
            StackBlock,
            infer_from_existing_configs,
        )
        from .lamill_toml import write as _write_lamill_toml
        from . import lamill_toml_edit as _lt_edit
        from .stack_classifier import classify_stack
        if platform is not None:
            if platform not in PLATFORM_VALUES:
                raise BootstrapError(
                    f"unsupported --platform: {platform!r}. "
                    f"Use one of {', '.join(PLATFORM_VALUES)}."
                )
            if platform in HOSTING_REQUIRED_PLATFORMS:
                raise BootstrapError(
                    f"--platform={platform!r} can't be set at bootstrap "
                    f"time — it requires a [hosting] section that "
                    f"bootstrap doesn't prompt for. Bootstrap with the "
                    f"default platform first, then run `lamill settings "
                    f"deploy set {domain} {platform}` to "
                    f"populate the cpanel + FTP breadcrumbs."
                )
            chosen_platform = platform
        else:
            inferred = infer_from_existing_configs(project_dir)
            # v15.I (ADR-0012): cf-workers is the new default. The
            # unified Pages-API deploy pipeline serves both cf-pages
            # and cf-workers via the same git-integrated flow, but
            # cf-workers is the operator's preferred platform value
            # going forward (it's where CF unified Workers + Pages).
            chosen_platform = (
                inferred.platform if inferred is not None else "cf-workers"
            )
        # v27.I — auto-declare [stack] from the canonical classifier
        # (same source of truth as the v27.C backfill + CHECK_151 drift),
        # so new sites start with a declaration and don't show as drift.
        detected_framework = classify_stack(project_dir).framework
        stack_block = (
            StackBlock(framework=detected_framework)
            if detected_framework in STACK_FRAMEWORK_VALUES
            else None
        )

        # v29.D — derive [content] from the authored AI_AGENTS sections
        # (ADR-0019): icp copied verbatim, the other fields via one
        # best-effort LLM call. Never raises — no key / no brief / failure
        # yields {} (or just icp), leaving fields blank for the operator.
        from . import content_derive
        from .apikeys import get_key
        content_values = content_derive.derive_content(
            operator_inputs or {},
            api_key=get_key("OPENAI_API_KEY"),
        )
        result.content_seeded = sorted(content_values)

        _write_lamill_toml(
            project_dir,
            LamillToml(
                deploy=DeployBlock(
                    platform=chosen_platform,
                    custom_domains=[domain],
                ),
                stack=stack_block,
                analytics=(
                    AnalyticsBlock(ga4_id=measurement_id)
                    if measurement_id else None
                ),
                # v27.I — seed the approved starter-set todos; v29.D — the
                # "fill in [content]" todo is gated on the derived block's
                # blank fields.
                todos=bootstrap_starter_todos(content_values=content_values),
            ),
        )
        # v27.I — match the fleet file shape: header pointer + [content]
        # block (surgical, idempotent). v29.D — seed it with the derived
        # values; a blank/partial block re-seeds the "fill in" starter todo.
        _lt_edit.ensure_content_block(project_dir, content_values)
        _lt_edit.ensure_header_comment(project_dir)
        result.files_written.append("lamill.toml")

        # v30.D — provision IndexNow so the new site ships with a key file
        # (public/<key>.txt) on its first deploy + an [index] table. Best-
        # effort: a miss is caught later by CHECK_153 indexnow-key-present.
        try:
            from . import indexnow
            indexnow.provision(project_dir)
        except Exception:
            pass

    initialized, sha = _git_init_and_commit(
        project_dir,
        f"scaffold {domain} via portfolio new bootstrap ({result.path}, stack={stack})",
    )
    result.git_initialized = initialized
    result.initial_commit_sha = sha
    if not initialized:
        result.warnings.append("git init / initial commit failed — run manually")

    result.next_steps = [
        f"cd ../{domain}",
        "make deps        # install dependencies via the central builder",
        "make dev         # start dev server (or `make run`)",
        "# review the scaffold, then push: git remote add origin <repo> && git push -u origin main",
    ]
    return result
