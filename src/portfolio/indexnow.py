"""IndexNow provisioning (v30.A) + submission (v30.B).

v30.A: per-site IndexNow key provisioning — generate a key, serve it at
`public/<key>.txt`, and record it in `lamill.toml [index]`. The key file
deploys with the site (CF Pages serves `public/` at the domain root) and is
self-authenticating, so no Bing-Webmaster account is needed. A later ping
(v30.B) reaches Bing/Yandex/Naver/Seznam/Yep in one POST — Google does not
participate. See ADR-0020 + docs/indexing-module-plan.md.
"""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx

from . import lamill_toml, lamill_toml_edit
from .data import ROOT

KEY_DIR = "public"

INDEX_DIR = ROOT / "data" / "index"
INDEXNOW_ENDPOINT = "https://api.indexnow.org/indexnow"
_HTTP_TIMEOUT = 10.0
_LOC_RE = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)
_SITEMAP_RE = re.compile(r"^\s*Sitemap:\s*(\S+)", re.IGNORECASE | re.MULTILINE)


class IndexNowError(RuntimeError):
    """A permanent IndexNow submission failure (bad key / non-429 4xx)."""


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


# ---- per-domain submission ledger (append-only, v30.B) --------------


def _domain_dir(domain: str) -> Path:
    return INDEX_DIR / domain.strip().lower()


def ledger_path(domain: str) -> Path:
    return _domain_dir(domain) / "_ledger.json"


def load_ledger(domain: str) -> list[dict]:
    """The per-domain submission ledger entries (`[]` when none / unreadable)."""
    p = ledger_path(domain)
    if not p.is_file():
        return []
    try:
        return json.loads(p.read_text()).get("entries", [])
    except (OSError, ValueError):
        return []


def ledger_urls(domain: str) -> set[str]:
    return {e["url"] for e in load_ledger(domain) if e.get("url")}


def append_ledger(domain: str, urls: list[str], *, when: str | None = None,
                  endpoint: str = INDEXNOW_ENDPOINT) -> None:
    """Append submitted `urls` to the ledger (atomic tmpfile+replace)."""
    if not urls:
        return
    stamp = when or datetime.now(timezone.utc).isoformat()
    entries = load_ledger(domain)
    entries.extend({"url": u, "submitted_at": stamp, "endpoint": endpoint} for u in urls)
    d = _domain_dir(domain)
    d.mkdir(parents=True, exist_ok=True)
    payload = {"domain": domain.strip().lower(), "entries": entries}
    tmp = ledger_path(domain).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    tmp.replace(ledger_path(domain))


# ---- sitemap fetch (robots.txt-derived; handles sitemapindex) -------


def _sitemap_url_from_robots(domain: str, client: httpx.Client) -> str | None:
    """The `Sitemap:` line from the live robots.txt — the canonical pointer
    `@astrojs/sitemap` & friends populate. None when absent/unreachable."""
    try:
        r = client.get(f"https://{domain}/robots.txt")
    except httpx.HTTPError:
        return None
    if r.status_code != 200:
        return None
    m = _SITEMAP_RE.search(r.text)
    return m.group(1).strip() if m else None


def fetch_sitemap_urls(domain: str, *, client: httpx.Client | None = None) -> list[str]:
    """Page URLs from the site's sitemap. Resolves the sitemap URL from
    robots.txt (`Sitemap:` line), falling back to `/sitemap.xml`, and
    expands a `<sitemapindex>` into its child sitemaps' URLs. Best-effort:
    `[]` on any fetch/parse failure."""
    own = client is None
    c = client or httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        sm = _sitemap_url_from_robots(domain, c) or f"https://{domain}/sitemap.xml"
        try:
            text = c.get(sm).text
        except httpx.HTTPError:
            return []
        if "<sitemapindex" in text.lower():
            urls: list[str] = []
            for child in _LOC_RE.findall(text):
                try:
                    urls.extend(_LOC_RE.findall(c.get(child).text))
                except httpx.HTTPError:
                    continue
            return urls
        return _LOC_RE.findall(text)
    finally:
        if own:
            c.close()


def new_urls(domain: str, current: list[str]) -> list[str]:
    """Sitemap URLs not yet in the ledger (order-preserving, de-duped)."""
    seen = ledger_urls(domain)
    out: list[str] = []
    added: set[str] = set()
    for u in current:
        if u not in seen and u not in added:
            out.append(u)
            added.add(u)
    return out


# ---- IndexNow submission (POST) -------------------------------------


def submit_urls(domain: str, key: str, urls: list[str], *,
                endpoint: str = INDEXNOW_ENDPOINT,
                client: httpx.Client | None = None) -> int:
    """POST `urls` to IndexNow (one batch, ≤10k → Bing/Yandex/Naver/Seznam/Yep;
    Google does not participate). Returns the count submitted (0 for an empty
    list). Raises `IndexNowError` on a permanent non-429 4xx; lets transient
    httpx errors (429 / 5xx / network) propagate for the caller to back off."""
    if not urls:
        return 0
    own = client is None
    c = client or httpx.Client(timeout=_HTTP_TIMEOUT)
    try:
        batch = urls[:10000]
        body = {
            "host": domain,
            "key": key,
            "keyLocation": f"https://{domain}/{key}.txt",
            "urlList": batch,
        }
        r = c.post(endpoint, json=body)
        if r.status_code in (200, 202):
            return len(batch)
        if r.status_code == 429 or r.status_code >= 500:
            r.raise_for_status()  # transient → httpx.HTTPStatusError
        raise IndexNowError(f"IndexNow {r.status_code}: {r.text[:200]}")
    finally:
        if own:
            c.close()


def key_is_live(domain: str, key: str, *, client: httpx.Client | None = None) -> bool:
    """True when `https://<domain>/<key>.txt` serves exactly `key` — the
    pre-flight before submitting, so we never ping against a key the engines
    can't verify."""
    own = client is None
    c = client or httpx.Client(timeout=_HTTP_TIMEOUT, follow_redirects=True)
    try:
        r = c.get(f"https://{domain}/{key}.txt")
        return r.status_code == 200 and r.text.strip() == key
    except httpx.HTTPError:
        return False
    finally:
        if own:
            c.close()
