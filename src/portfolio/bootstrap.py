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

import json
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from datetime import date
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

## How to run

```bash
# from this dir, after `make buildsh` from sites/:
make deps      # → pnpm install via the central builder
make run       # → dev server
make build     # → dist/
make test      # → pnpm install + build + test (must be inside container)
```

## Key conventions

- Stack: {stack}
- Build path: this project's `Makefile` → `../Makefile` → `~/work/projects/builder/`
- Cloudflare deploy constraints: Vite ≥ 6, frozen-lockfile install, no `_redirects` SPA fallback (handled by `wrangler.jsonc`'s `not_found_handling` instead).

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

| Version | Theme | Acceptance |
|---|---|---|
| v0 | scaffold | minimal home page deploys to Cloudflare Pages |
| v1 | <fill in> | <fill in> |

## 5. Phases

| Phase | Theme | Features |
|---|---|---|
| **v0.A** | scaffold + deploy | initial page · `wrangler.toml` · CF Pages connection |
| **v1.A** | <fill in> | <fill in> |

## 6. Open questions

- *(append-only log; mark answered with date but never delete)*
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


def _wrangler_jsonc(domain: str, today_iso: str) -> str:
    """Modern Cloudflare Pages config (matches homeloom.app's known-good setup).

    Uses `assets.not_found_handling: "single-page-application"` for SPA routing
    instead of the legacy `_redirects` fallback. The `[site]` block of older
    `wrangler.toml` files is for Workers Sites — not CF Pages — and triggers
    build errors on the modern CF Pages pipeline.
    """
    project = re.sub(r"[^a-z0-9-]", "-", domain.lower()).strip("-")
    return json.dumps({
        "$schema": "node_modules/wrangler/config-schema.json",
        "name": project,
        "compatibility_date": today_iso,
        "assets": {
            "directory": "./dist",
            "not_found_handling": "single-page-application",
        },
    }, indent=2) + "\n"


# ---- Astro stack templates ----


def _astro_package_json(domain: str) -> str:
    project = domain.replace(".", "-")
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
            "astro": "astro"
        },
        "dependencies": {
            "astro": "^5.0.0"
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


def _astro_index() -> str:
    return """---
// src/pages/index.astro
const title = "Welcome";
---
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{title}</title>
  </head>
  <body>
    <main>
      <h1>{title}</h1>
      <p>Scaffolded via <code>portfolio bootstrap</code>.</p>
    </main>
  </body>
</html>
"""


# ---- Vite + React + JSX stack templates ----


def _vite_package_json(domain: str) -> str:
    project = domain.replace(".", "-")
    return json.dumps({
        "name": project,
        "private": True,
        "version": "0.0.1",
        "type": "module",
        "scripts": {
            "dev": "vite",
            "build": "vite build",
            "preview": "vite preview"
        },
        "dependencies": {
            "react": "^18.3.0",
            "react-dom": "^18.3.0"
        },
        "devDependencies": {
            "@vitejs/plugin-react": "^4.3.0",
            "vite": "^6.0.0"
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
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{domain}</title>
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
    if key == "astro_pkg":
        return _astro_package_json(domain)
    if key == "astro_config":
        return _astro_config()
    if key == "astro_index":
        return _astro_index()
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
