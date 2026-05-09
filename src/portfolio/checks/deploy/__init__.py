"""Deploy-category checks: deploy-target marker uniqueness, wrangler.jsonc
safety rules (CF Pages bun-detection trap), vercel.json sanity, builder-repo
reference in Makefile."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _read_jsonc(path: Path) -> dict[str, Any] | None:
    """Read a JSONC file (JSON with comments). Strips //-style and /* ... */
    comments before parsing. Returns None on parse failure."""
    if not path.is_file():
        return None
    try:
        text = path.read_text()
    except OSError:
        return None
    # Strip // ... line comments (but not inside strings — naive but works for
    # wrangler.jsonc which has simple comment usage).
    text = re.sub(r"^\s*//.*$", "", text, flags=re.MULTILINE)
    # Strip /* ... */ block comments.
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _deploy_target_files(repo_path: str) -> list[str]:
    """Return the list of deploy-target marker filenames present in the repo."""
    base = Path(repo_path)
    out = []
    if (base / "wrangler.jsonc").is_file() or (base / "wrangler.toml").is_file():
        out.append("wrangler")
    if (base / "vercel.json").is_file():
        out.append("vercel")
    if (base / "netlify.toml").is_file():
        out.append("netlify")
    return out
