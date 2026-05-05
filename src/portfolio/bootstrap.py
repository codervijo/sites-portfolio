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

import hashlib
import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .data import ROOT

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


# ---------- templates ----------


def _ai_agents_md(domain: str, stack: str, topic: str) -> str:
    topic_line = f"\n_Topic: {topic}_\n" if topic else ""
    return f"""# AI Agent Context — {domain}
{topic_line}
## What this project is

<1-2 sentence description — fill in>

## Stack

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

## Build tooling — Makefile + Docker

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

## Deployment

- **Platform:** Cloudflare Workers (Static Assets) — *not* Vercel.
- **Config:** `wrangler.jsonc` at the repo root — points `assets.directory` at `./dist` and uses `not_found_handling: "single-page-application"` for SPA client-side routing.
- **Headers:** `public/_headers` — cache (`/assets/*` immutable, HTML no-cache) + security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`). Vite copies `public/` into `dist/` at build, so the file ships with the assets.
- **Build:** `pnpm build` → `dist/`. Wrangler picks up `dist/` via `wrangler.jsonc`.
- **Deploy:** `wrangler deploy` (locally) or via Cloudflare's Git integration on push.
- **Vite version:** must be ≥ 6.0.0 — Wrangler's Vite integration rejects Vite 5.
- **Env vars:** set `VITE_*` vars (e.g. `VITE_GA_ID`) in the Cloudflare Workers project's environment-variable settings — they're inlined at build time.
- **Live URL:** https://{domain}/  *(update once first deploy succeeds)*
- **Legacy:** if a `vercel.json` or `.vercelignore` is present from a Lovable export, it's inert on Cloudflare and safe to delete.

### Post-deploy checklist (do these once after the first successful deploy)

- [ ] Verify in **Google Search Console** at https://search.google.com/search-console — add as `sc-domain:{domain}` property; verify via DNS TXT record. Until this is done, no SEO traffic data is observable for this site (and the workspace-wide `30 commercial sites with traffic` goal can't credit it).
- [ ] Submit the sitemap (`https://{domain}/sitemap.xml`) inside GSC.
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
`portfolio project status {domain}` (run from `sites/portfolio/`).
Conformance rules currently checked include: `own-git-repo`,
`has-category` (project listed in portfolio.json), `has-prompts-md` +
`prompts-md-format` (dated H2), `has-makefile`, `has-ai-agents-md`,
`platform-declared` (CF/Vercel/Netlify marker), `live-site` (HTTP
classification), and **`has-growth-log`** (`docs/growth.md` exists —
the per-project growth-experiment log; see Growth log section below).
v4 adds `has-prd-md`, `has-readme`, `has-gitignore`, `vite-version-ok`,
`ai-agents-md-has-building-info`, `ai-agents-md-has-deployment-info`.
The bootstrap output satisfies all of these on day zero — keep it that way.

If `project status` flags a regression, fix it. v4.D's
`portfolio project fix` will eventually auto-fix; until then, hand-edit.

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

Two-layer notation separates **external version** (what consumers see) from
**internal phasing** (how the team slices work). Letters signal *un-promised* —
nobody mistakes `v1.B` for a SemVer minor release.

Track this project's progress in `docs/prd.md` against this taxonomy. v0.A is
the bootstrap (this scaffold); v1.A is the first real shipped capability.

## Key conventions

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

## 1. Purpose

<1-2 sentence problem statement — fill in>
{topic_line}
## 2. Audience

<who uses this>

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
| **v0.A** | scaffolded | `portfolio bootstrap` ran; standard files written; git initialized | ✅ |
| **v1.A** | <fill in> | <fill in> | planned |

## 6. Open questions

- *(append-only log; mark answered with date but never delete)*
"""


def _docs_growth_md(domain: str, today: str) -> str:
    try:
        review_date = (date.fromisoformat(today) + timedelta(days=28)).isoformat()
    except ValueError:
        review_date = "<today + 28 days>"
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
- **KPI:** <what GSC metric / query / page>
- **Baseline:** <numbers at start>
- **Action:** <what was done; 1-2 lines>
- **Result:** <numbers after window; "TBD — review YYYY-MM-DD" until then>
- **Learning:** <why it worked / didn't; what to try next; "TBD" until reviewed>
```

---

## {today} — site scaffolded; growth log started
- **Status:** active
- **KPI:** any GSC traffic — clicks, impressions, indexed-page count
- **Baseline:** 0 clicks / 0 impressions (just deployed)
- **Action:** project scaffolded via `portfolio bootstrap`; first deploy
  pending. After deploy: verify in GSC as `sc-domain:{domain}` and submit
  the sitemap.
- **Result:** TBD — review {review_date}
- **Learning:** TBD
"""


def _docs_prompts_md(domain: str, today: str) -> str:
    return f"""# Prompt History — {domain}

<!-- Append new prompts at the bottom, newest last. Format:

## YYYY-MM-DD [optional title]
> <prompt text or short summary>

The dated H2 (`## YYYY-MM-DD`) is what `portfolio project status` parses
to surface "last AI prompt" per project. Keep entries append-only.
-->

## {today} — scaffolded via portfolio bootstrap

> Created project skeleton. Stack chosen, scaffolding written, git initialized.
"""


def _readme_md(domain: str) -> str:
    return f"# {domain}\n\n<placeholder>\n"


def _gitignore() -> str:
    return """# Node
node_modules/
.pnpm-store/
dist/
build/
.next/
.cache/

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
        "scripts": {
            "dev": "astro dev",
            "start": "astro dev",
            "build": "astro build",
            "preview": "astro preview",
            "astro": "astro",
            "test": "vitest run",
            "test:watch": "vitest"
        },
        "dependencies": {
            "astro": "^5.0.0"
        },
        "devDependencies": {
            "vitest": "^3.0.0"
        }
    }, indent=2) + "\n"


def _astro_config() -> str:
    return """// astro.config.mjs
import { defineConfig } from 'astro/config';

export default defineConfig({
  // site: 'https://<domain>/',  // set when deployed
  output: 'static',
});
"""


def _astro_index(domain: str) -> str:
    return f"""---
// src/pages/index.astro
const site = "https://{domain}";
const title = "{domain}";
const description = "<fill in: 1-2 sentence value prop for SEO description>";
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{{title}}</title>
    <meta name="description" content={{description}} />
    <link rel="canonical" href={{site}} />
    <link rel="icon" type="image/svg+xml" href="/favicon.svg" />

    <!-- Open Graph -->
    <meta property="og:type" content="website" />
    <meta property="og:title" content={{title}} />
    <meta property="og:description" content={{description}} />
    <meta property="og:url" content={{site}} />
    <meta property="og:site_name" content="{domain}" />

    <!-- Twitter card -->
    <meta name="twitter:card" content="summary_large_image" />
    <meta name="twitter:title" content={{title}} />
    <meta name="twitter:description" content={{description}} />

    <!-- JSON-LD structured data: Organization + WebSite -->
    <script type="application/ld+json" set:html={{JSON.stringify({{
      "@context": "https://schema.org",
      "@graph": [
        {{
          "@type": "Organization",
          "@id": `${{site}}/#organization`,
          "name": "{domain}",
          "url": site,
        }},
        {{
          "@type": "WebSite",
          "@id": `${{site}}/#website`,
          "url": site,
          "name": "{domain}",
          "description": description,
          "publisher": {{ "@id": `${{site}}/#organization` }},
        }},
      ],
    }})}} />
  </head>
  <body>
    <main>
      <h1>{{title}}</h1>
      <p>Scaffolded via <code>portfolio bootstrap</code>.</p>
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
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview",
            "test": "vitest run",
            "test:watch": "vitest"
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
      <p>Scaffolded via <code>portfolio bootstrap</code>.</p>
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


def _robots_txt(domain: str) -> str:
    return f"""User-agent: *
Allow: /

Sitemap: https://{domain}/sitemap.xml
"""


def _sitemap_xml(domain: str, today_iso: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!--
  Stub sitemap. v3.B will replace this with a build-time generator that
  scans routes/pages. Until then, it lists just the home page so Google
  can discover the site at all.
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
    ("Makefile", "makefile"),
    ("docs/prd.md", "prd"),
    ("docs/Prompts.md", "prompts"),
    ("docs/growth.md", "growth"),
]

SEO_FILES = [
    ("public/robots.txt", "robots"),
    ("public/sitemap.xml", "sitemap"),
    ("public/favicon.svg", "favicon_svg"),
    ("vitest.config.js", "vitest_config"),
    ("src/__tests__/smoke.test.js", "smoke_test"),
]

ASTRO_FILES = [
    ("package.json", "astro_pkg"),
    ("astro.config.mjs", "astro_config"),
    ("src/pages/index.astro", "astro_index"),
]

VITE_FILES = [
    ("package.json", "vite_pkg"),
    ("vite.config.js", "vite_config"),
    ("index.html", "vite_index_html"),
    ("src/main.jsx", "vite_main"),
    ("src/App.jsx", "vite_app"),
]

INGESTER_FILES = [
    ("scripts/ingest.py", "ingester"),
    ("scripts/README.md", "ingester_readme"),
]


def _render(key: str, domain: str, stack: str, topic: str, today: str) -> str:
    if key == "ai_agents":
        return _ai_agents_md(domain, stack, topic)
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
        return _docs_growth_md(domain, today)
    if key == "astro_pkg":
        return _astro_package_json(domain)
    if key == "astro_config":
        return _astro_config()
    if key == "astro_index":
        return _astro_index(domain)
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
        return _robots_txt(domain)
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
        path.write_text(_render(key, domain, stack, topic, today))
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


def detect_stack_from_pkg(project_dir: Path) -> str:
    """If package.json exists, infer stack. Default 'vite' if React; 'astro' if astro dep; else fallback."""
    pkg_path = project_dir / "package.json"
    if not pkg_path.exists():
        return "vite"
    try:
        pkg = json.loads(pkg_path.read_text())
    except json.JSONDecodeError:
        return "vite"
    deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
    if "astro" in deps:
        return "astro"
    if "vite" in deps or "react" in deps:
        return "vite"
    return "unknown"


def bootstrap(
    domain: str,
    stack: str = "astro",
    from_genai: bool = False,
    git_url: str | None = None,
    with_ingester: bool = False,
    topic: str = "",
    sites_root: Path | None = None,
    today_iso: str | None = None,
) -> BootstrapResult:
    """Top-level orchestration. Always called with already-validated domain.

    Path selection precedence:
      git_url    → create dir + clone URL into genai/ + treat as from_genai
      from_genai → genai/ must exist; copy + CF fixes
      else      → template path (dir must NOT exist)
    """
    domain = validate_domain(domain)
    sites = sites_root or SITES_ROOT
    project_dir = sites / domain
    today = today_iso or date.today().isoformat()

    if git_url:
        if project_dir.exists():
            raise BootstrapError(
                f"{project_dir} already exists — refusing to clobber. "
                f"If you already cloned to {project_dir}/genai/, use --from-genai instead."
            )
        project_dir.mkdir(parents=True)
        _clone_to_genai(project_dir, git_url)
        from_genai = True  # fall through to the same handling below

    if from_genai:
        if not project_dir.exists():
            raise BootstrapError(f"--from-genai requires {project_dir} to already exist with a genai/ subdir")
        copied, copy_warnings = _copy_from_genai(project_dir)
        # Re-detect stack from package.json after copy.
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
        # Stack-specific files first.
        stack_spec = ASTRO_FILES if stack == "astro" else VITE_FILES if stack == "vite" else None
        if stack_spec is None:
            raise BootstrapError(f"unsupported --stack: {stack!r}. Use 'astro' or 'vite'.")
        written, _skipped = _write_files(project_dir, stack_spec, domain, stack, topic, today, skip_existing=False)
        result = BootstrapResult(
            project_dir=project_dir,
            stack=stack,
            path="template",
            files_written=list(written),
        )

    # Common scaffolding files. On --from-genai, skip files that genai already provided.
    skip_existing = (result.path != "template")
    common_written, common_skipped = _write_files(
        project_dir, COMMON_FILES, domain, stack, topic, today, skip_existing=skip_existing
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

    initialized, sha = _git_init_and_commit(
        project_dir,
        f"scaffold {domain} via portfolio bootstrap ({result.path}, stack={stack})",
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
