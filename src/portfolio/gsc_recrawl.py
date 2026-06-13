"""GSC URL-inspection helper — `lamill settings gsc recrawl`.

Given a site and a baseline timestamp, query Google's URL Inspection
API for each URL and report which ones Google has re-crawled since the
baseline. Useful for confirming that a deploy was actually picked up.

Read-only. Uses the existing `webmasters.readonly` OAuth scope — no
widening. Cannot trigger a re-crawl (Google's Indexing API restricts
that to JobPosting / BroadcastEvent content; using it for general web
pages violates ToS and Google silently ignores the submissions —
documented in the CLI command's help and in the README).
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .gsc import authenticate, coverage_map, get_service, list_properties
from .project import SITES_ROOT


# ---------- dataclasses ----------


@dataclass
class UrlInspection:
    """One URL's inspection state."""
    url: str
    status: str            # "ok" | "skipped" | "error"
    last_crawl_time: datetime | None = None
    page_fetch_state: str | None = None
    indexing_state: str | None = None
    coverage_state: str | None = None
    verdict: str | None = None
    error: str | None = None

    def crawled_since(self, baseline: datetime) -> bool:
        if self.last_crawl_time is None:
            return False
        return self.last_crawl_time >= baseline


@dataclass
class RecrawlReport:
    site: str
    property_url: str
    baseline: datetime
    inspections: list[UrlInspection] = field(default_factory=list)

    def crawled_count(self) -> int:
        return sum(1 for i in self.inspections if i.crawled_since(self.baseline))

    def total_count(self) -> int:
        return len(self.inspections)

    def errored_count(self) -> int:
        return sum(1 for i in self.inspections if i.status == "error")


# ---------- baseline resolution ----------


class RecrawlError(RuntimeError):
    """Raised when the recrawl run can't proceed (no site dir, no GSC
    property, etc.). CLI catches and prints a friendly message."""


def resolve_site_dir(site: str) -> Path:
    """Return the on-disk path for `<sites>/<site>/`. Raises if missing."""
    p = SITES_ROOT / site
    if not p.is_dir():
        raise RecrawlError(f"site directory not found: {p}")
    return p


def head_commit_time(site_dir: Path) -> datetime:
    """Return the UTC datetime of HEAD's commit in the site repo."""
    try:
        out = subprocess.check_output(
            ["git", "-C", str(site_dir), "log", "-1", "--format=%cI"],
            text=True,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError) as e:
        raise RecrawlError(f"could not read HEAD commit time: {e}") from e
    try:
        # `%cI` is strict ISO-8601 with offset; fromisoformat handles it.
        return datetime.fromisoformat(out)
    except ValueError as e:
        raise RecrawlError(f"unparseable HEAD timestamp: {out!r} ({e})") from e


def resolve_baseline(site_dir: Path, since: str | None) -> datetime:
    """If `since` is provided, parse it as ISO-8601. Otherwise return the
    site's HEAD commit time."""
    if since is None:
        return head_commit_time(site_dir)
    s = since.strip()
    # Tolerate the trailing-Z form (datetime.fromisoformat is pre-3.11 strict).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError as e:
        raise RecrawlError(f"could not parse --since {since!r}: {e}") from e
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------- URL source ----------


def read_urls_from_file(path: Path) -> list[str]:
    """Read a newline-separated list of URLs from `path`.
    Ignores blank lines and `#` comments."""
    lines = path.read_text().splitlines()
    urls: list[str] = []
    for line in lines:
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        urls.append(s)
    return urls


# Inline minimal sitemap fetcher used when `--urls` is not passed.
#
# NOTE: a richer version of this lives in `checks/seo/_live.py` as part
# of the Task A (CHECK_090–095 live-runtime SEO) work on a separate
# branch. Once that branch merges, this should collapse to:
#     from .checks.seo._live import get_sitemap_urls, LiveFetchError
# For now we duplicate the minimal logic so this PR is reviewable
# without a hard dependency on Task A landing first.

_SITEMAP_FALLBACK_PATHS = ("/sitemap.xml", "/sitemap-index.xml", "/sitemap_index.xml")
_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
_GOOGLEBOT_UA = (
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"
)


def _parse_robots_sitemap_urls(robots_text: str) -> list[str]:
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


def _extract_locs(xml_text: str) -> tuple[list[str], list[str]]:
    """Return (urls, nested_sitemaps) from a sitemap or sitemap-index body."""
    from xml.etree import ElementTree as ET
    urls: list[str] = []
    nested: list[str] = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return [], []

    def _find_loc(elem):
        loc = elem.find(f"{_SITEMAP_NS}loc")
        if loc is None:
            loc = elem.find("loc")
        if loc is None or not loc.text:
            return None
        return loc.text.strip()

    if root.tag.endswith("sitemapindex"):
        for sm in list(root.findall(f"{_SITEMAP_NS}sitemap")) + list(root.findall("sitemap")):
            text = _find_loc(sm)
            if text:
                nested.append(text)
    elif root.tag.endswith("urlset"):
        for u in list(root.findall(f"{_SITEMAP_NS}url")) + list(root.findall("url")):
            text = _find_loc(u)
            if text:
                urls.append(text)
    return urls, nested


def fetch_sitemap_urls(origin: str, *, limit: int = 50) -> list[str]:
    """Pull URLs from the live sitemap for `origin`. Raises RecrawlError
    if no sitemap can be reached."""
    import httpx
    from urllib.parse import urljoin

    with httpx.Client(timeout=10.0, follow_redirects=True,
                      headers={"User-Agent": _GOOGLEBOT_UA}) as client:
        # Try robots.txt declarations first.
        sm_url: str | None = None
        try:
            r = client.get(urljoin(origin + "/", "robots.txt"))
            if r.status_code == 200:
                for declared in _parse_robots_sitemap_urls(r.text):
                    try:
                        s = client.get(declared)
                    except httpx.HTTPError:
                        continue
                    if s.status_code == 200:
                        sm_url = declared
                        break
        except httpx.HTTPError:
            pass
        if sm_url is None:
            for path in _SITEMAP_FALLBACK_PATHS:
                candidate = urljoin(origin + "/", path.lstrip("/"))
                try:
                    s = client.get(candidate)
                except httpx.HTTPError:
                    continue
                if s.status_code == 200:
                    sm_url = candidate
                    break
        if sm_url is None:
            raise RecrawlError(f"no sitemap reachable from {origin}")

        # Walk one level into sitemap-indexes.
        seen: set[str] = set()
        queue = [sm_url]
        urls: list[str] = []
        while queue and len(urls) < limit:
            current = queue.pop(0)
            if current in seen:
                continue
            seen.add(current)
            try:
                r = client.get(current)
            except httpx.HTTPError as e:
                raise RecrawlError(
                    f"sitemap fetch failed: {type(e).__name__}: {e}") from e
            if r.status_code != 200:
                continue
            found, nested = _extract_locs(r.text)
            for u in found:
                if len(urls) >= limit:
                    break
                if u not in urls:
                    urls.append(u)
            queue.extend(nested)
        return urls


# ---------- GSC property resolution ----------


def find_gsc_property(domain: str, service=None) -> str:
    """Return the GSC property URL covering `domain`. Prefers the
    `sc-domain:` property when multiple cover the same host."""
    service = service or get_service()
    props = list_properties(service)
    cov = coverage_map(props)
    matches = cov.get(domain.lower(), [])
    if not matches:
        raise RecrawlError(
            f"no GSC property covers {domain!r}. Available domains: "
            f"{', '.join(sorted(cov.keys())[:10])}"
        )
    # Prefer sc-domain: form (covers both www and bare).
    for p in matches:
        if p["siteUrl"].startswith("sc-domain:"):
            return p["siteUrl"]
    return matches[0]["siteUrl"]


# ---------- inspection ----------


def _parse_last_crawl(s: str | None) -> datetime | None:
    if not s:
        return None
    text = s.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def inspect_one_url(service, site_url: str, url: str) -> UrlInspection:
    """Call `urlInspection.index.inspect` for one URL. Returns a
    UrlInspection with status="ok" on success, "error" otherwise."""
    try:
        resp = service.urlInspection().index().inspect(body={
            "inspectionUrl": url,
            "siteUrl": site_url,
        }).execute()
    except Exception as e:    # noqa: BLE001 — googleapiclient raises many
        return UrlInspection(url=url, status="error", error=f"{type(e).__name__}: {e}")
    result = resp.get("inspectionResult", {}) if isinstance(resp, dict) else {}
    idx = result.get("indexStatusResult", {}) or {}
    return UrlInspection(
        url=url,
        status="ok",
        last_crawl_time=_parse_last_crawl(idx.get("lastCrawlTime")),
        page_fetch_state=idx.get("pageFetchState"),
        indexing_state=idx.get("indexingState"),
        coverage_state=idx.get("coverageState"),
        verdict=idx.get("verdict"),
    )


def run_recrawl(site: str, *, urls: Iterable[str] | None = None,
                since: str | None = None,
                service=None) -> RecrawlReport:
    """Top-level orchestrator. Resolves baseline, GSC property, URL list,
    and inspects each. Returns a RecrawlReport."""
    site_dir = resolve_site_dir(site)
    baseline = resolve_baseline(site_dir, since)

    if service is None:
        creds = authenticate()
        service = get_service(creds)

    property_url = find_gsc_property(site, service=service)

    if urls is None:
        # Derive origin from the GSC property URL (or fall back to https://<site>).
        if property_url.startswith("sc-domain:"):
            origin = f"https://{property_url[len('sc-domain:'):]}"
        else:
            origin = property_url.rstrip("/")
        url_list = fetch_sitemap_urls(origin)
    else:
        url_list = list(urls)

    report = RecrawlReport(
        site=site, property_url=property_url, baseline=baseline,
        inspections=[inspect_one_url(service, property_url, u) for u in url_list],
    )
    return report


# ---------- markdown report ----------


def _fmt_dt(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def format_markdown_report(report: RecrawlReport, *,
                           now: datetime | None = None) -> str:
    """Render the report as a markdown block. Format:

    ## GSC recrawl — <site> — <ISO date>

    | URL | Last crawl | Re-crawled? | Fetch | Indexing | Verdict |
    | ... |
    """
    now = now or datetime.now(timezone.utc)
    lines: list[str] = []
    lines.append(f"## GSC recrawl — {report.site} — {now.strftime('%Y-%m-%d')}")
    lines.append("")
    lines.append(f"- Property: `{report.property_url}`")
    lines.append(f"- Baseline: {_fmt_dt(report.baseline)}")
    lines.append(
        f"- Re-crawled since baseline: **{report.crawled_count()}/{report.total_count()}**"
        + (f" · {report.errored_count()} errored" if report.errored_count() else "")
    )
    lines.append("")
    lines.append("| URL | Last crawl | Re-crawled? | Fetch | Indexing | Verdict |")
    lines.append("|---|---|:---:|---|---|---|")
    for i in report.inspections:
        if i.status == "error":
            lines.append(
                f"| `{i.url}` | — | ✗ | — | — | error: {i.error or '?'} |"
            )
            continue
        crawled_glyph = "✓" if i.crawled_since(report.baseline) else "✗"
        lines.append(
            f"| `{i.url}` | {_fmt_dt(i.last_crawl_time)} | {crawled_glyph} | "
            f"{i.page_fetch_state or '—'} | {i.indexing_state or '—'} | "
            f"{i.verdict or '—'} |"
        )
    lines.append("")
    return "\n".join(lines)


def append_to_growth_md(site_dir: Path, markdown: str) -> Path:
    """Append `markdown` to `<site>/docs/growth.md`. Creates the file
    (with a small header) if absent. Returns the path written to."""
    p = site_dir / "docs" / "growth.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if p.exists():
        existing = p.read_text()
    elif True:
        existing = "# Growth log\n\nDated entries from `lamill` tooling.\n\n"
    if existing and not existing.endswith("\n"):
        existing += "\n"
    new_content = existing + "\n" + markdown + "\n"
    p.write_text(new_content)
    return p


# ---------- GSC Exchange v1 contract — producer side -------------------
#
# Writes `sites/<domain>/.lamill/gsc.json` per the `gsc-exchange-v1`
# contract (canonical: sites/rankmill/docs/contracts/gsc-exchange.md;
# vendored: docs/contracts/gsc-exchange.md + .schema.json; ADR-0025).
# lamill produces, rankmill consumes — file is the entire interface; the
# data is the same `UrlInspection` set `run_recrawl` already computes.

EXCHANGE_SCHEMA = "gsc-exchange-v1"
EXCHANGE_SOURCE = "url-inspection"
EXCHANGE_RELPATH = Path(".lamill") / "gsc.json"
_VALID_VERDICTS = {"PASS", "PARTIAL", "FAIL", "NEUTRAL"}


def _iso_z(dt: datetime | None) -> str | None:
    """UTC ISO-8601 with a trailing `Z` (contract L3), or None. A naive
    datetime is assumed UTC; an aware one is converted."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _inspection_to_page(insp: UrlInspection) -> dict:
    """Map one internal `UrlInspection` → a contract `pages[]` record.
    Drops the internal `status` field; defaults the two schema-required
    string fields when GSC returned nothing (errored/unknown URLs still
    carry the truth in `error`)."""
    return {
        "url": insp.url,
        "verdict": insp.verdict if insp.verdict in _VALID_VERDICTS else "NEUTRAL",
        "coverage_state": insp.coverage_state or "URL is unknown to Google",
        "indexing_state": insp.indexing_state,
        "page_fetch_state": insp.page_fetch_state,
        "last_crawl_time": _iso_z(insp.last_crawl_time),
        "error": insp.error,
    }


def build_exchange_payload(
    report: RecrawlReport, *, fetched_at: datetime, error: str | None = None,
) -> dict:
    """Build the `gsc-exchange-v1` payload from a RecrawlReport. Pure —
    `fetched_at` is injected so the producer test is deterministic."""
    return {
        "schema": EXCHANGE_SCHEMA,
        "domain": report.site.strip().lower(),
        "property": report.property_url,
        "fetched_at": _iso_z(fetched_at),
        "source": EXCHANGE_SOURCE,
        "error": error,
        "pages": [_inspection_to_page(i) for i in report.inspections],
    }


def write_exchange_file(site_dir: Path, payload: dict) -> Path:
    """Atomically write `<site_dir>/.lamill/gsc.json` (contract L5): write
    a temp file in the same dir, then `os.replace` (atomic on one fs) so a
    crash never leaves a partial file a reader could observe."""
    out = site_dir / EXCHANGE_RELPATH
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.parent / f".gsc.json.tmp.{os.getpid()}"
    tmp.write_text(json.dumps(payload, indent=2) + "\n")
    os.replace(tmp, out)   # atomic same-filesystem rename
    return out


def ensure_lamill_gitignored(site_dir: Path) -> bool:
    """Ensure `.lamill/` is in `<site_dir>/.gitignore` (contract P5 — the
    exchange file is transient, refreshed per crawl, never committed).
    Idempotent; returns True if a line was added."""
    gi = site_dir / ".gitignore"
    existing = gi.read_text() if gi.exists() else ""
    lines = {ln.strip().rstrip("/") for ln in existing.splitlines()}
    if ".lamill" in lines:
        return False
    block = "" if (not existing or existing.endswith("\n")) else "\n"
    block += "\n# lamill consumer-data exchange (transient, refreshed per crawl)\n.lamill/\n"
    gi.write_text(existing + block)
    return True


def export_exchange_file(
    report: RecrawlReport, site_dir: Path, *, fetched_at: datetime | None = None,
) -> Path:
    """Build + atomically write the exchange file for a successful recrawl,
    and ensure `.lamill/` is gitignored. Returns the written path."""
    fetched_at = fetched_at or datetime.now(timezone.utc)
    payload = build_exchange_payload(report, fetched_at=fetched_at)
    path = write_exchange_file(site_dir, payload)
    ensure_lamill_gitignored(site_dir)
    return path
