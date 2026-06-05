"""IndexNow provisioning (v30.A) + submission (v30.B).

v30.A: per-site IndexNow key provisioning — generate a key, serve it at
`public/<key>.txt`, and record it in `lamill.toml [index]`. The key file
deploys with the site (CF Pages serves `public/` at the domain root) and is
self-authenticating, so no Bing-Webmaster account is needed. A later ping
(v30.B) reaches Bing/Yandex/Naver/Seznam/Yep in one POST — Google does not
participate. See ADR-0020 + docs/indexing-module-plan.md.
"""
from __future__ import annotations

import secrets
from pathlib import Path

from . import lamill_toml, lamill_toml_edit

KEY_DIR = "public"


def generate_key() -> str:
    """A fresh IndexNow key — 32 hex chars, within the spec's 8–128
    `[a-zA-Z0-9-]` range."""
    return secrets.token_hex(16)


def key_file_path(repo: Path, key: str) -> Path:
    return repo / KEY_DIR / f"{key}.txt"


def is_provisioned(repo: Path) -> bool:
    """True when `[index]` carries a key AND `public/<key>.txt` exists with
    exactly that key as its content."""
    doc = lamill_toml.load(repo)
    if doc is None or doc.index is None or not doc.index.indexnow_key:
        return False
    p = key_file_path(repo, doc.index.indexnow_key)
    return p.is_file() and p.read_text().strip() == doc.index.indexnow_key


def provision(repo: Path) -> tuple[str, list[Path]]:
    """Idempotently provision IndexNow for `repo`: reuse the existing
    `[index]` key or generate one, write `public/<key>.txt`, and upsert the
    `[index]` table (surgical, ADR-0018). Returns `(key, files_written)` —
    `files_written` is empty when everything was already in place.

    Requires `lamill.toml` to exist (the caller — CHECK_153's fixer —
    gates on it).
    """
    doc = lamill_toml.load(repo)
    idx = doc.index if doc else None
    key = (idx.indexnow_key if idx and idx.indexnow_key else None) or generate_key()
    enabled = idx.indexnow_enabled if idx else True

    written: list[Path] = []
    kf = key_file_path(repo, key)
    if not (kf.is_file() and kf.read_text().strip() == key):
        kf.parent.mkdir(parents=True, exist_ok=True)
        kf.write_text(key + "\n")
        written.append(kf)

    if idx is None or idx.indexnow_key != key:
        lamill_toml_edit.set_table(
            repo, "index",
            {"indexnow_key": key, "indexnow_enabled": enabled},
        )
        written.append(repo / lamill_toml.LAMILL_TOML_FILENAME)

    return key, written
