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
BUILDER_REL_PATH = "../../builder"
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

{stack.capitalize()} (per the central multi-stack builder at `~/work/projects/builder/`).

## Project structure

- `src/` — application source
- `docs/` — PRD, Prompts log
- `Makefile` — includes the central builder; auto-detects stack
- `scripts/` *(if present)* — ingester or build-time helpers

## Building info

Stack auto-detected by the central builder at `~/work/projects/builder/`,
which provides per-stack Makefiles (`Makefile.react`, `Makefile.python`, etc.).

Two ways to build:

1. **Via sites/Makefile** (Docker-orchestrated, common): from `sites/`:
   - `make buildsh` — enter the dev container
   - `make build proj={domain}` / `make run proj={domain}` / `make test proj={domain}`

2. **From this project dir** (own Makefile + builder include):
   - `make deps` — install dependencies
   - `make build` / `make run` / `make test`

See `~/work/projects/builder/README.md` for the central builder docs.

## Deployment info

- **Platform**: cloudflare-pages
- **Live URL**: https://{domain}/  *(update once deployed)*
- **Last deployed commit**: <fill once shipped>
- **Deploy trigger**: push to main → CF Pages build hook
- **Notes**: `wrangler.toml` declares the Pages project; deploy plumbing lands in v3.C

## How to run

```bash
make deps
make run
```

## Key conventions

- Stack: {stack}
- Build via the central builder
- Cloudflare Pages constraints respected: Vite ≥6, frozen-lockfile install, no `_redirects` SPA fallback

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


def _local_makefile() -> str:
    return f"""# Per-project Makefile — delegates to the central multi-stack builder.
# See ~/work/projects/builder/README.md for target list.

BUILDER_PATH ?= {BUILDER_REL_PATH}

# Auto-detect stack; override with STACK=astro / STACK=react / STACK=vite etc.
# STACK ?= astro

include $(BUILDER_PATH)/Makefile
"""


def _wrangler_toml(domain: str) -> str:
    project = domain.replace(".", "-")
    return f"""name = "{project}"
compatibility_date = "2026-05-01"

[site]
bucket = "./dist"

# Cloudflare Pages config — adjust if your build output dir is not ./dist
"""


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
        return _local_makefile()
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


def _add_wrangler_toml(project_dir: Path, domain: str) -> bool:
    """Add wrangler.toml if missing. Returns True if added, False if already present."""
    path = project_dir / "wrangler.toml"
    if path.exists():
        return False
    path.write_text(_wrangler_toml(domain))
    return True


def _apply_cf_safety_fixes(project_dir: Path, domain: str) -> list[str]:
    """Apply Cloudflare Pages safety fixes after a genai-copy. Returns list of fix descriptions."""
    fixes: list[str] = []
    bumped = _bump_vite_version(project_dir / "package.json")
    if bumped:
        fixes.append(bumped)
    removed = _remove_redirects_files(project_dir)
    for r in removed:
        fixes.append(f"removed {r} (CF Pages convention: no SPA fallback)")
    if _add_wrangler_toml(project_dir, domain):
        fixes.append("wrote wrangler.toml (Cloudflare Pages config)")
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
        cf_fixes = _apply_cf_safety_fixes(project_dir, domain)
        result = BootstrapResult(
            project_dir=project_dir,
            stack=stack,
            path="git-url" if git_url else "genai",
            files_copied=copied,
            cf_fixes=cf_fixes,
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
    skip_existing = (result.path == "genai")
    common_written, common_skipped = _write_files(
        project_dir, COMMON_FILES, domain, stack, topic, today, skip_existing=skip_existing
    )
    result.files_written.extend(common_written)
    if common_skipped:
        result.warnings.append(f"left {len(common_skipped)} pre-existing common file(s) untouched: {', '.join(common_skipped)}")

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
