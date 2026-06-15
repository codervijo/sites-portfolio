"""v5.D — shared helpers for live-runtime SEO checks (CHECK_090–095).

The static-source SEO checks (CHECK_060–080) read files on disk. These
runtime checks fetch deployed URLs and validate what Googlebot actually
sees — which is where the washcalc.app regression hid (prerendered
JSON-LD shipping `url: <homepage>` on every page despite per-page
canonicals).

Each check imports from this module to share:

  - `resolve_live_url(repo_path)` — find the project's live origin
    (package.json `homepage` → README/AI_AGENTS scan → directory-name
    fallback if it looks like a domain).
  - `get_sitemap_urls(origin)` — discover the sitemap via robots.txt
    `Sitemap:` directive (or fall back to `/sitemap.xml` /
    `/sitemap-index.xml`) and extract every `<loc>` (recursing into
    nested sitemap indexes).
  - `fetch_html(url)` — Googlebot-UA fetch with retries, returning the
    HTML body. Per-process cache so CHECK_090–095 only fetch each URL
    once per `project check` invocation.
  - `parse_jsonld_blocks(html)` — extract every `<script
    type="application/ld+json">` block and try to JSON-parse it.
  - `parse_canonical(html)` — extract the `<link rel="canonical">` href.

Network failures (timeouts, connection refused, 5xx) raise
`LiveFetchError`. Checks should catch this and return
`CheckResult(status="warn", ...)` — flaky CI shouldn't fail-grade an
SEO check on a transient outage.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

import httpx

# Googlebot UA string — public canonical form. Real Googlebot rotates,
# but this is the one Google publishes for rendering identification.
GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)
HTTP_TIMEOUT = 10.0
SITEMAP_FALLBACK_PATHS = ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml")

# Cap how many URLs we'll fetch from a site's sitemap inside a single
# check run. Sites with thousands of URLs would otherwise hang the
# check loop — the audit value diminishes after the first ~50.
SITEMAP_URL_LIMIT = 50


class LiveFetchError(RuntimeError):
    """Raised when a runtime fetch fails (network, timeout, 5xx).
    Checks catch this and emit `warn`, not `fail`."""


@dataclass
class JsonLdBlock:
    """One parsed JSON-LD block from a page.

    `parsed` is None when `error` is non-None (parse failure). The raw
    text is preserved for diagnostic findings ("block 2 of 3 didn't
    parse: <preview>").
    """
    raw: str
    parsed: object | None
    error: str | None


# ---------- live-URL resolution ----------


_URL_RE = re.compile(r"https?://[a-z0-9.-]+\.[a-z]{2,}(?:/[^\s\"']*)?", re.IGNORECASE)


def _read_package_homepage(repo_path: str) -> str | None:
    p = Path(repo_path) / "package.json"
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(errors="replace"))
    except (OSError, ValueError):
        return None
    hp = data.get("homepage")
    if isinstance(hp, str) and hp.strip().startswith(("http://", "https://")):
        return hp.strip().rstrip("/")
    return None


def _scan_docs_for_url(repo_path: str) -> str | None:
    """Same heuristic as CHECK_029 — search README / AI_AGENTS / docs/CLAUDE
    for an `https://` near a "live"/"production"/"deployed" hint."""
    base = Path(repo_path)
    for fname in ("README.md", "AI_AGENTS.md", "docs/CLAUDE.md"):
        p = base / fname
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            low = line.lower()
            if any(h in low for h in ("live", "production", "deployed", "homepage")):
                m = _URL_RE.search(line)
                if m:
                    url = m.group(0)
                    if not any(s in url for s in ("example.com", "localhost", "127.0.0.1")):
                        return url.rstrip("/")
    return None


def _derive_from_dirname(repo_path: str) -> str | None:
    """Last-resort: if the directory is named like a domain (contains a
    dot + non-empty TLD), assume https://<dirname>."""
    name = Path(repo_path).name
    if not name or "." not in name:
        return None
    if name.startswith(".") or name.endswith("."):
        return None
    # Looks like a domain — at least one dot, and the trailing piece
    # has 2+ alpha chars. Avoids treating "src.legacy" as a domain.
    parts = name.split(".")
    if len(parts[-1]) < 2 or not parts[-1].isalpha():
        return None
    return f"https://{name}"


def resolve_live_url(repo_path: str) -> str | None:
    """Return the project's live origin (no trailing slash) or None.

    Tries in order: package.json `homepage`, README/AI_AGENTS scan,
    directory-name fallback. Returns origin form (scheme + host) only —
    even when the source field is a deeper URL, we strip to origin so
    `urljoin` works cleanly for sitemap discovery.
    """
    for candidate in (
        _read_package_homepage(repo_path),
        _scan_docs_for_url(repo_path),
        _derive_from_dirname(repo_path),
    ):
        if candidate:
            parsed = urlparse(candidate)
            if parsed.scheme and parsed.netloc:
                return f"{parsed.scheme}://{parsed.netloc}"
    return None


# ---------- HTTP session + per-process fetch cache ----------


_FETCH_CACHE: dict[str, str] = {}


def _build_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": GOOGLEBOT_UA},
    )


def fetch_html(url: str, *, client: httpx.Client | None = None) -> str:
    """Fetch `url` as Googlebot. Returns the response body.

    Cached per-process — repeated calls for the same URL inside one
    `project check` invocation hit the cache instead of the network.
    Caller may inject a client (used by tests for transport mocks).
    """
    if url in _FETCH_CACHE:
        return _FETCH_CACHE[url]

    own_client = client is None
    if client is None:
        client = _build_client()
    try:
        try:
            resp = client.get(url)
        except httpx.HTTPError as e:
            raise LiveFetchError(f"{type(e).__name__}: {e}") from e
        if resp.status_code >= 500:
            raise LiveFetchError(f"HTTP {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx is not a network problem — we record it (so CHECK_090
            # can flag it as a real failure) instead of treating as warn.
            # The caller distinguishes via the status code in a wrapper
            # helper (`fetch_response_status`) below.
            raise LiveFetchError(f"HTTP {resp.status_code}")
        _FETCH_CACHE[url] = resp.text
        return resp.text
    finally:
        if own_client:
            client.close()


def fetch_response_status(url: str, *,
                          client: httpx.Client | None = None) -> int:
    """Like fetch_html but returns the final status code instead of
    raising on 4xx. Used by CHECK_090 (sitemap-fetches) which needs to
    DISTINGUISH "page 404s" from "network is flaky."

    Still raises LiveFetchError on actual transport failures + 5xx.
    """
    own_client = client is None
    if client is None:
        client = _build_client()
    try:
        try:
            resp = client.get(url)
        except httpx.HTTPError as e:
            raise LiveFetchError(f"{type(e).__name__}: {e}") from e
        if resp.status_code >= 500:
            raise LiveFetchError(f"HTTP {resp.status_code}")
        if 200 <= resp.status_code < 300:
            _FETCH_CACHE[url] = resp.text
        return resp.status_code
    finally:
        if own_client:
            client.close()


def clear_cache() -> None:
    """Reset the per-process fetch cache. Tests call this between cases."""
    _FETCH_CACHE.clear()


# ---------- sitemap discovery ----------


# Wildcard namespace, not the literal `{http://www.sitemaps.org/...}`. The
# sitemap protocol mandates the http:// URI, but real generators vary — TanStack
# Start emits the `https://` scheme (a *different* XML namespace by exact-string
# compare). Google parses those fine (verified 2026-06-15: GSC reported
# submitted=8/errors=0 for a https://-namespaced sitemap a strict parser read as
# 0). `{*}` matches any namespace incl. none, so we match Google's leniency.
_SITEMAP_NS = "{*}"


def _parse_robots_sitemap_urls(robots_text: str) -> list[str]:
    """Parse Sitemap: directives from robots.txt (case-insensitive,
    absolute URLs only)."""
    out: list[str] = []
    for line in robots_text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        if key.strip().lower() != "sitemap":
            continue
        u = val.strip()
        if u.startswith(("http://", "https://")):
            out.append(u)
    return out


def _discover_sitemap_url(origin: str, *,
                          client: httpx.Client | None = None) -> str | None:
    """Find the canonical sitemap URL for `origin`. Reads robots.txt
    first; falls back to common paths. Returns None if none respond 200."""
    own_client = client is None
    if client is None:
        client = _build_client()
    try:
        # Try robots.txt declarations first.
        try:
            r = client.get(urljoin(origin + "/", "robots.txt"))
            if r.status_code == 200:
                for declared in _parse_robots_sitemap_urls(r.text):
                    try:
                        s = client.get(declared)
                    except httpx.HTTPError:
                        continue
                    if s.status_code == 200:
                        return declared
        except httpx.HTTPError:
            pass
        # Fallback paths under the origin.
        for path in SITEMAP_FALLBACK_PATHS:
            url = urljoin(origin + "/", path.lstrip("/"))
            try:
                s = client.get(url)
            except httpx.HTTPError:
                continue
            if s.status_code == 200:
                return url
    finally:
        if own_client:
            client.close()
    return None


def _find_loc(elem) -> str | None:
    """Return the text of `<loc>` under `elem`. `_SITEMAP_NS` is the `{*}`
    wildcard, which matches `<loc>` in any namespace *and* no namespace, so a
    single find covers every case. (`is None` rather than truthiness —
    ElementTree.Element is falsy when childless, which would misfire on the
    text-only `<loc>` elements we want.)"""
    loc = elem.find(f"{_SITEMAP_NS}loc")
    if loc is None or not loc.text:
        return None
    return loc.text.strip()


def _extract_sitemap_locs(xml_text: str) -> tuple[list[str], list[str]]:
    """Parse a sitemap XML body. Returns `(urls, nested_sitemaps)`.

    `nested_sitemaps` is non-empty when the document is a
    `<sitemapindex>`; the caller is expected to recurse into each.
    """
    urls: list[str] = []
    nested: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []
    tag = root.tag
    # `_SITEMAP_NS` is the `{*}` wildcard — matches the child elements in any
    # namespace (http://, the non-standard https://, or none), so one findall
    # each. (A bare-name fallback would double-count no-namespace docs.)
    if tag.endswith("sitemapindex"):
        for sm in root.findall(f"{_SITEMAP_NS}sitemap"):
            text = _find_loc(sm)
            if text:
                nested.append(text)
    elif tag.endswith("urlset"):
        for u in root.findall(f"{_SITEMAP_NS}url"):
            text = _find_loc(u)
            if text:
                urls.append(text)
    return urls, nested


def get_sitemap_urls(origin: str, *, limit: int = SITEMAP_URL_LIMIT,
                     client: httpx.Client | None = None) -> list[str]:
    """Return every URL declared in the site's sitemap (recursing into
    sitemap-indexes if needed). Capped at `limit` URLs to bound check
    runtime on large sites.

    Raises LiveFetchError if no sitemap can be reached.
    """
    own_client = client is None
    if client is None:
        client = _build_client()
    try:
        sm_url = _discover_sitemap_url(origin, client=client)
        if not sm_url:
            raise LiveFetchError(f"no sitemap reachable from {origin}")
        seen_sitemaps: set[str] = set()
        queue = [sm_url]
        urls: list[str] = []
        while queue and len(urls) < limit:
            current = queue.pop(0)
            if current in seen_sitemaps:
                continue
            seen_sitemaps.add(current)
            try:
                r = client.get(current)
            except httpx.HTTPError as e:
                raise LiveFetchError(
                    f"sitemap fetch failed: {type(e).__name__}: {e}") from e
            if r.status_code != 200:
                continue
            found, nested = _extract_sitemap_locs(r.text)
            for u in found:
                if len(urls) >= limit:
                    break
                if u not in urls:
                    urls.append(u)
            queue.extend(nested)
        return urls
    finally:
        if own_client:
            client.close()


# ---------- HTML parsing helpers ----------


def _parse_html(html: str):
    """Whole-document parse via BeautifulSoup html.parser. The audit's
    prerendered washcalc HTML is on a single line — line-based regex
    breaks for these checks, so always use the parser."""
    from . import _bs4  # v35.D — wrapped bs4 import (typed error on broken install)
    return _bs4()(html, "html.parser")


def parse_jsonld_blocks(html: str) -> list[JsonLdBlock]:
    """Extract every `<script type="application/ld+json">` block from
    the page. Returns one `JsonLdBlock` per block. Parse failures are
    recorded as `error` on the block (CHECK_091 fails on these)."""
    soup = _parse_html(html)
    scripts = soup.find_all("script", attrs={"type": "application/ld+json"})
    out: list[JsonLdBlock] = []
    for s in scripts:
        raw = s.string or s.get_text() or ""
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            out.append(JsonLdBlock(raw=raw, parsed=None, error=str(e)))
        else:
            out.append(JsonLdBlock(raw=raw, parsed=parsed, error=None))
    return out


def parse_canonical(html: str) -> str | None:
    """Return the page's `<link rel="canonical">` href, or None if absent."""
    soup = _parse_html(html)
    link = soup.find("link", attrs={"rel": "canonical"})
    if link is None:
        return None
    href = link.get("href")
    if not href:
        return None
    return str(href).strip()


def iter_jsonld_nodes(parsed_obj: object):
    """Yield every dict node inside a parsed JSON-LD value, descending
    into `@graph` arrays and nested lists. Useful for checks that
    inspect every typed object regardless of nesting."""
    if isinstance(parsed_obj, dict):
        yield parsed_obj
        graph = parsed_obj.get("@graph")
        if isinstance(graph, list):
            for item in graph:
                yield from iter_jsonld_nodes(item)
    elif isinstance(parsed_obj, list):
        for item in parsed_obj:
            yield from iter_jsonld_nodes(item)


def node_type(node: dict) -> list[str]:
    """Return a list of @type strings on a node (handles both string
    and list forms)."""
    t = node.get("@type")
    if isinstance(t, str):
        return [t]
    if isinstance(t, list):
        return [x for x in t if isinstance(x, str)]
    return []


# ---------- Per-check runtime context ----------


def run_check_or_warn(repo_path: str, fn) -> object:
    """Helper: run a live-check body that takes `(origin, sitemap_urls)`
    and turn any LiveFetchError into a `warn` CheckResult.

    Most CHECK_090+ check bodies share this preamble:
      - resolve live URL (warn if missing)
      - fetch sitemap URLs (warn on LiveFetchError)
      - run check-specific logic over the URLs

    Returning a CheckResult here keeps each check file thin.
    """
    from ..result import CheckResult
    from . import _is_web_project

    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")
    try:
        urls = get_sitemap_urls(origin)
    except LiveFetchError as e:
        return CheckResult(status="warn", message=f"sitemap unreachable ({e})")
    if not urls:
        return CheckResult(status="warn", message=f"sitemap empty at {origin}")
    try:
        return fn(origin, urls)
    except LiveFetchError as e:
        return CheckResult(status="warn", message=f"network: {e}")
