"""v51 — `project seo <site> --deep`: indexing root-cause diagnostic.

Read-only. Answers *why* Google knows a site's sitemap but not its pages,
at per-URL depth. Builds on `seo_diagnose` (v36) — sitemap discovery and
the render heuristics are imported, not copied.

v51.B (this file, so far) — the crawl probe + link graph, all from raw
HTML (Googlebot's pre-render view; no headless browser):

  * `parse_robots` / `RobotsRules.check` — Google's robots.txt semantics:
    the `googlebot` group (else `*`), `*` / `$` wildcards, longest match
    wins, `Allow` wins a tie.
  * `probe_url` — one URL: redirect chain (followed by hand, so every hop
    is recorded), final status, robots allow/deny, canonical (self /
    other / host-mismatch / cross-site / missing / multiple), `noindex`
    (meta + `X-Robots-Tag`), server-rendered title + body text, and the
    page's followable internal links.
  * `crawl_site` — probe every sitemap URL plus a bounded same-host BFS
    from `/`, then build the link graph: inbound links per URL, click
    depth from the homepage, sitemap **orphans** (no internal inbound
    link), and pages reachable by links but missing from the sitemap.

I/O is injected (`client=`) so everything is testable with
`httpx.MockTransport`.
"""
from __future__ import annotations

import re
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Literal
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx

from ._httpapi import managed_client
from .gsc_recrawl import _GOOGLEBOT_UA
from .seo_diagnose import _discover_pages, _has_title

# ---------- tunables ----------

MAX_REDIRECTS = 10
HTTP_TIMEOUT = 10.0
# Extra non-sitemap pages the BFS may fetch beyond the sitemap itself.
CRAWL_EXTRA_PAGES = 100
# Hard ceiling on total fetched pages, whatever the sitemap size.
CRAWL_PAGE_CEILING = 2000
CRAWL_WORKERS = 8
SHINGLE_WORDS = 5


# ---------- URL helpers ----------


def _site_host(host: str) -> str:
    """Host with a leading `www.` dropped — apex and www are one site."""
    host = (host or "").lower()
    return host[4:] if host.startswith("www.") else host


def url_key(url: str) -> str:
    """Graph key for a URL: lowercase scheme+host, `www.` dropped, no
    fragment, no trailing slash (except root). Query is kept. Two spellings
    Google would treat as one *link target* map to one key; the exact
    spelling (slash, www) is still kept on each probe for redirect findings."""
    p = urlsplit(url.strip())
    path = p.path or "/"
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/") or "/"
    if path.endswith("/index.html"):
        path = path[: -len("index.html")].rstrip("/") or "/"
    return urlunsplit((p.scheme.lower() or "https", _site_host(p.netloc),
                       path, p.query, ""))


def same_site(url: str, origin: str) -> bool:
    return _site_host(urlsplit(url).netloc) == _site_host(urlsplit(origin).netloc)


# ---------- robots.txt (Google semantics) ----------


@dataclass(frozen=True)
class RobotsRule:
    allow: bool
    path: str

    def _regex(self) -> re.Pattern:
        anchored = self.path.endswith("$")
        body = self.path[:-1] if anchored else self.path
        pat = "".join(".*" if ch == "*" else re.escape(ch) for ch in body)
        return re.compile(pat + ("$" if anchored else ""))

    def matches(self, path: str) -> bool:
        return bool(self._regex().match(path))


@dataclass
class RobotsRules:
    """Parsed robots.txt. `status` is the robots.txt HTTP status (None on
    transport error). Per Google: 4xx → allow everything; 5xx / unreachable
    → treat the whole site as disallowed."""
    status: int | None
    rules: list[RobotsRule] = field(default_factory=list)
    group: str = "*"              # which group applied: "googlebot" or "*"

    def check(self, url: str) -> tuple[bool, str | None]:
        """(allowed, matching rule text or None)."""
        if self.status is None or self.status >= 500:
            return False, f"robots.txt unreachable (HTTP {self.status})"
        if 400 <= self.status < 500:
            return True, None
        p = urlsplit(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best: RobotsRule | None = None
        for r in self.rules:
            if not r.path:                     # empty `Disallow:` = allow all
                continue
            if not r.matches(path):
                continue
            if (best is None or len(r.path) > len(best.path)
                    or (len(r.path) == len(best.path) and r.allow)):
                best = r
        if best is None:
            return True, None
        return best.allow, f"{'Allow' if best.allow else 'Disallow'}: {best.path}"


def parse_robots(text: str, status: int | None = 200) -> RobotsRules:
    """Parse robots.txt into the rule set Googlebot obeys: the `googlebot`
    group(s) if any exist, else the `*` group(s)."""
    groups: list[tuple[list[str], list[RobotsRule]]] = []
    agents: list[str] = []
    rules: list[RobotsRule] = []
    in_rules = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip().lower(), val.strip()
        if key == "user-agent":
            if in_rules:                       # a new group starts
                groups.append((agents, rules))
                agents, rules, in_rules = [], [], False
            agents.append(val.lower())
        elif key in ("allow", "disallow"):
            in_rules = True
            rules.append(RobotsRule(allow=(key == "allow"), path=val))
    if agents:
        groups.append((agents, rules))

    def _collect(match: Callable[[str], bool]) -> list[RobotsRule]:
        out: list[RobotsRule] = []
        for ags, rs in groups:
            if any(match(a) for a in ags):
                out.extend(rs)
        return out

    gb = _collect(lambda a: a == "googlebot")
    if any(a == "googlebot" for ags, _ in groups for a in ags):
        return RobotsRules(status=status, rules=gb, group="googlebot")
    return RobotsRules(status=status, rules=_collect(lambda a: a == "*"), group="*")


def fetch_robots(origin: str, client: httpx.Client) -> RobotsRules:
    try:
        r = client.get(origin.rstrip("/") + "/robots.txt", follow_redirects=True)
    except httpx.HTTPError:
        return RobotsRules(status=None)
    if r.status_code != 200:
        return RobotsRules(status=r.status_code)
    return parse_robots(r.text, 200)


# ---------- one URL ----------

# self          — points at this URL exactly
# variant       — same page, different spelling (trailing slash / index.html)
# other         — a different page on this host (Google may fold this URL into it)
# host_mismatch — same site, other host (www vs apex, http vs https host)
# cross_site    — another domain
# missing / multiple — none, or >1 (Google ignores conflicting canonicals)
CanonicalKind = Literal["self", "variant", "other", "host_mismatch",
                        "cross_site", "missing", "multiple"]


@dataclass
class RedirectHop:
    url: str
    status: int


@dataclass
class UrlProbe:
    """Everything raw HTML says about one URL."""
    url: str                                   # as requested
    in_sitemap: bool = False
    status: int | None = None                  # final status
    final_url: str | None = None
    redirects: list[RedirectHop] = field(default_factory=list)
    robots_allowed: bool = True
    robots_rule: str | None = None
    content_type: str | None = None
    canonical: str | None = None               # resolved absolute href
    canonical_kind: CanonicalKind = "missing"
    noindex: bool = False
    noindex_source: str | None = None          # "meta" | "header"
    title: str | None = None
    has_title: bool = False
    body_chars: int = 0
    internal_links: list[str] = field(default_factory=list)   # absolute, followable, deduped
    nofollow_links: int = 0
    words: int = 0                             # visible words (v51.D)
    # Hashed 5-word shingles of the visible text — template / near-duplicate
    # analysis (v51.D). Not part of repr; never serialized.
    shingles: frozenset = field(default_factory=frozenset, repr=False)
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200

    @property
    def redirected(self) -> bool:
        return bool(self.redirects)

    @property
    def has_body_text(self) -> bool:
        return self.body_chars >= _MIN_BODY_CHARS

    @property
    def empty_shell(self) -> bool:
        return self.ok and _is_html(self.content_type) and not (
            self.has_title and self.has_body_text)


_MIN_BODY_CHARS = 40                           # same bar as seo_diagnose
_SKIP_SCHEMES = ("mailto:", "tel:", "javascript:", "data:", "sms:")


def _is_html(content_type: str | None) -> bool:
    return content_type is None or "html" in content_type.lower()


def _soup(html: str):
    from .checks.seo import _bs4  # wrapped import (typed error on broken install)
    return _bs4()(html, "html.parser")


def _visible_text(soup) -> str:
    for t in soup(["script", "style", "noscript", "template"]):
        t.decompose()
    body = soup.body or soup
    return " ".join(body.get_text(" ").split())


def _robots_directives(value: str) -> set[str]:
    return {d.strip().lower() for d in value.split(",") if d.strip()}


# Directives that legitimately contain a colon — not a UA scope prefix.
_COLON_DIRECTIVES = ("unavailable_after", "max-snippet", "max-image-preview",
                     "max-video-preview")


def _header_noindex(headers: httpx.Headers) -> bool:
    """`X-Robots-Tag: noindex` or `X-Robots-Tag: googlebot: noindex`. A value
    scoped to another crawler (`bingbot: noindex`) doesn't bind Googlebot."""
    for v in headers.get_list("x-robots-tag"):
        scope, sep, rest = v.partition(":")
        scope_l = scope.strip().lower()
        if sep and "," not in scope and scope_l not in _COLON_DIRECTIVES:
            if scope_l != "googlebot":
                continue
            v = rest
        if _robots_directives(v) & {"noindex", "none"}:
            return True
    return False


def _classify_canonical(href: str | None, count: int, final_url: str,
                        origin: str) -> tuple[str | None, CanonicalKind]:
    if count > 1:
        return (urljoin(final_url, href) if href else None), "multiple"
    if not href:
        return None, "missing"
    absolute = urljoin(final_url, href.strip())
    if not same_site(absolute, origin):
        return absolute, "cross_site"
    if urlsplit(absolute).netloc.lower() != urlsplit(final_url).netloc.lower():
        return absolute, "host_mismatch"
    if url_key(absolute) != url_key(final_url):
        return absolute, "other"
    a, f = urlsplit(absolute), urlsplit(final_url)
    if (a.path or "/") == (f.path or "/") and a.query == f.query:
        return absolute, "self"
    return absolute, "variant"


def analyze_html(probe: UrlProbe, html: str, origin: str) -> None:
    """Fill the HTML-derived fields of `probe` in place."""
    soup = _soup(html)
    canon_tags = [t for t in soup.find_all("link", href=True)
                  if "canonical" in [r.lower() for r in (t.get("rel") or [])]]
    href = canon_tags[0].get("href") if canon_tags else None
    probe.canonical, probe.canonical_kind = _classify_canonical(
        href, len(canon_tags), probe.final_url or probe.url, origin)

    for m in soup.find_all("meta"):
        name = (m.get("name") or "").lower()
        if name in ("robots", "googlebot") and \
                _robots_directives(m.get("content") or "") & {"noindex", "none"}:
            probe.noindex, probe.noindex_source = True, "meta"
            break

    probe.has_title = _has_title(html)
    t = soup.find("title")
    probe.title = " ".join(t.get_text().split()) if t else None

    base = probe.final_url or probe.url
    links: list[str] = []
    seen: set[str] = set()
    for a in soup.find_all("a", href=True):
        h = a["href"].strip()
        if not h or h.startswith("#") or h.lower().startswith(_SKIP_SCHEMES):
            continue
        absolute = urljoin(base, h)
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        if not same_site(absolute, origin):
            continue
        if "nofollow" in [r.lower() for r in (a.get("rel") or [])]:
            probe.nofollow_links += 1
            continue
        absolute = urlunsplit(urlsplit(absolute)._replace(fragment=""))
        k = url_key(absolute)
        if k not in seen:
            seen.add(k)
            links.append(absolute)
    probe.internal_links = links
    text = _visible_text(soup)
    probe.body_chars = len(text)
    toks = text.lower().split()
    probe.words = len(toks)
    probe.shingles = frozenset(
        hash(" ".join(toks[i:i + SHINGLE_WORDS]))
        for i in range(max(0, len(toks) - SHINGLE_WORDS + 1)))


def probe_url(url: str, *, origin: str, robots: RobotsRules,
              client: httpx.Client, in_sitemap: bool = False) -> UrlProbe:
    """Fetch `url` as Googlebot, following redirects by hand so every hop
    is recorded. Never raises — failures land in `.error`."""
    probe = UrlProbe(url=url, in_sitemap=in_sitemap)
    probe.robots_allowed, probe.robots_rule = robots.check(url)
    current = url
    visited: set[str] = set()
    try:
        for _ in range(MAX_REDIRECTS + 1):
            r = client.get(current, follow_redirects=False)
            if r.is_redirect and r.headers.get("location"):
                probe.redirects.append(RedirectHop(current, r.status_code))
                nxt = urljoin(current, r.headers["location"])
                if nxt in visited:
                    probe.status, probe.final_url = r.status_code, nxt
                    probe.error = "redirect loop"
                    return probe
                visited.add(current)
                current = nxt
                continue
            break
        else:
            probe.error = f"more than {MAX_REDIRECTS} redirects"
            probe.final_url = current
            return probe
    except httpx.HTTPError as e:
        probe.error = f"{type(e).__name__}"
        probe.final_url = current
        return probe

    probe.status = r.status_code
    probe.final_url = str(r.url)
    probe.content_type = r.headers.get("content-type")
    if _header_noindex(r.headers):
        probe.noindex, probe.noindex_source = True, "header"
    if r.status_code == 200 and _is_html(probe.content_type):
        was_header = probe.noindex
        analyze_html(probe, r.text, origin)
        if was_header:
            probe.noindex, probe.noindex_source = True, "header"
    return probe


# ---------- whole-site crawl + link graph ----------


@dataclass
class CrawlResult:
    origin: str
    sitemap_url: str | None
    sitemap_urls: list[str]
    sitemap_error: str | None
    robots: RobotsRules
    probes: dict[str, UrlProbe]                # url_key → probe
    inbound: dict[str, set[str]]               # url_key → linking url_keys
    depth: dict[str, int]                      # url_key → clicks from home
    crawl_capped: bool = False
    page_cap: int = 0

    def key_for(self, url: str) -> str:
        return url_key(url)

    @property
    def home_key(self) -> str:
        return url_key(self.origin.rstrip("/") + "/")

    def inbound_count(self, url: str) -> int:
        return len(self.inbound.get(url_key(url), ()))

    def depth_of(self, url: str) -> int | None:
        return self.depth.get(url_key(url))

    @property
    def orphans(self) -> list[str]:
        """Sitemap URLs (not the homepage) that no crawled page links to."""
        return [u for u in self.sitemap_urls
                if url_key(u) != self.home_key and not self.inbound.get(url_key(u))]

    @property
    def unreachable_from_home(self) -> list[str]:
        """Sitemap URLs a crawler can't reach by following links from `/`
        (orphans, plus pages only linked from other unreachable pages)."""
        return [u for u in self.sitemap_urls if url_key(u) not in self.depth]

    @property
    def linked_not_in_sitemap(self) -> list[str]:
        sm = {url_key(u) for u in self.sitemap_urls}
        return sorted(p.url for k, p in self.probes.items()
                      if k not in sm and p.ok and not p.redirected
                      and _is_html(p.content_type))


def _build_graph(probes: dict[str, UrlProbe], home_key: str
                 ) -> tuple[dict[str, set[str]], dict[str, int]]:
    # A link to a URL that redirects counts toward the redirect target too —
    # Google follows it — so map each requested key to its final key.
    alias: dict[str, str] = {}
    for k, p in probes.items():
        if p.final_url:
            alias[k] = url_key(p.final_url)

    def resolve(k: str) -> str:
        return alias.get(k, k)

    inbound: dict[str, set[str]] = {}
    edges: dict[str, list[str]] = {}
    for src, p in probes.items():
        s = resolve(src)
        outs = []
        for link in p.internal_links:
            dst = url_key(link)
            d = resolve(dst)
            if d == s:
                continue
            inbound.setdefault(d, set()).add(s)
            if dst != d:
                inbound.setdefault(dst, set()).add(s)
            outs.append(d)
        edges.setdefault(s, []).extend(outs)

    depth: dict[str, int] = {}
    start = resolve(home_key)
    if start in edges or start in probes:
        depth[start] = 0
        if home_key != start:
            depth[home_key] = 0
        q = deque([start])
        while q:
            cur = q.popleft()
            for nxt in edges.get(cur, ()):
                if nxt not in depth:
                    depth[nxt] = depth[cur] + 1
                    q.append(nxt)
    # A requested (pre-redirect) key inherits its target's depth.
    for k, final in alias.items():
        if k not in depth and final in depth:
            depth[k] = depth[final]
    return inbound, depth


def crawl_site(origin: str, *, client: httpx.Client | None = None,
               sitemap_urls: list[str] | None = None,
               page_cap: int | None = None,
               workers: int = CRAWL_WORKERS,
               on_progress: Callable[[int, int, str], None] | None = None,
               ) -> CrawlResult:
    """Probe every sitemap URL + a same-site BFS from `/`, then build the
    link graph. `sitemap_urls` skips discovery (tests, or a caller that
    already has them). `page_cap` bounds total fetches (default: sitemap
    size + `CRAWL_EXTRA_PAGES`, ≤ `CRAWL_PAGE_CEILING`)."""
    origin = origin.rstrip("/")

    def _factory() -> httpx.Client:
        return httpx.Client(timeout=HTTP_TIMEOUT,
                            headers={"User-Agent": _GOOGLEBOT_UA})

    with managed_client(client, _factory) as c:
        robots = fetch_robots(origin, c)
        sm_err: str | None = None
        sm_file: str | None = None
        if sitemap_urls is None:
            sm_file, sitemap_urls, sm_err = _discover_pages(origin, c, 50_000)
        sitemap_urls = list(dict.fromkeys(sitemap_urls))
        cap = page_cap if page_cap is not None else min(
            len(sitemap_urls) + CRAWL_EXTRA_PAGES, CRAWL_PAGE_CEILING)
        cap = max(cap, 1)

        sm_keys = {url_key(u) for u in sitemap_urls}
        probes: dict[str, UrlProbe] = {}
        home = origin + "/"
        frontier: list[str] = [home] + [u for u in sitemap_urls
                                         if url_key(u) != url_key(home)]
        queued: set[str] = {url_key(u) for u in frontier}
        capped = False

        def _one(u: str) -> UrlProbe:
            return probe_url(u, origin=origin, robots=robots, client=c,
                             in_sitemap=url_key(u) in sm_keys)

        with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
            while frontier:
                room = cap - len(probes)
                if room <= 0:
                    capped = True
                    break
                batch, frontier = frontier[:room], frontier[room:]
                done = list(pool.map(_one, batch))
                for p in done:
                    probes[url_key(p.url)] = p
                    if on_progress:
                        on_progress(len(probes), min(cap, len(queued)), p.url)
                # BFS: enqueue newly discovered same-site links.
                for p in done:
                    for link in p.internal_links:
                        k = url_key(link)
                        if k not in queued:
                            queued.add(k)
                            frontier.append(link)
            if frontier:
                capped = True

    inbound, depth = _build_graph(probes, url_key(home))
    return CrawlResult(
        origin=origin, sitemap_url=sm_file, sitemap_urls=sitemap_urls,
        sitemap_error=sm_err, robots=robots, probes=probes,
        inbound=inbound, depth=depth, crawl_capped=capped, page_cap=cap,
    )


# ======================================================================
# v51.C — full URL Inspection sweep (quota-aware, same-day cache)
# ======================================================================
#
# Records live in today's GSC snapshot (`data/gsc/<domain>/<UTC-date>.json`)
# under their own section, `deep_inspections` = {url: record}. A separate
# section — not `v16c_inspections` — because CHECK_147 rewrites that one
# wholesale with its top-10 sample; per-URL merge into our own section is
# the v36.D "merge, never clobber" rule applied at URL granularity.

DEEP_SECTION = "deep_inspections"
# Stay under Google's 600/min per property with headroom.
SWEEP_PER_MINUTE = 550
# Persist partial progress every N inspections, so Ctrl-C / a crash resumes.
SAVE_EVERY = 10


class GscUnavailable(RuntimeError):
    """GSC preflight / property lookup failed. Message is operator-facing
    (plain words + fix), straight from the BUG-104 staged preflight."""


@dataclass
class SweepResult:
    property_url: str | None
    records: dict[str, dict]                  # url → inspection record
    from_cache: int = 0
    inspected: int = 0
    errors: int = 0
    not_inspected: list[str] = field(default_factory=list)
    stopped_reason: str | None = None         # "quota" | "budget" | None
    budget: int = 0

    @property
    def complete(self) -> bool:
        return not self.not_inspected


def inspection_record(insp) -> dict:
    """`gsc_recrawl.UrlInspection` → JSON-safe dict, stamped with when."""
    from dataclasses import asdict
    from datetime import datetime, timezone
    d = asdict(insp)
    lct = d.get("last_crawl_time")
    d["last_crawl_time"] = lct.isoformat() if lct is not None else None
    d["inspected_at"] = datetime.now(timezone.utc).isoformat()
    return d


def load_today_records(domain: str) -> dict[str, dict]:
    """Today's (UTC) `deep_inspections`, or {} — the same-day cache."""
    from datetime import datetime, timezone
    from . import gsc_detail_cache as gdc
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = gdc._domain_dir(domain) / f"{today}.json"
    if not path.exists():
        return {}
    try:
        sec = gdc.load_snapshot(path).get(DEEP_SECTION)
    except (OSError, ValueError):
        return {}
    return dict(sec) if isinstance(sec, dict) else {}


def inspections_used_today(domain: str) -> int:
    """URL Inspection calls lamill recorded today for this property: our
    own `deep_inspections` stamped today + CHECK_147's `v16c_inspections`
    if today's snapshot carries them. Calls made outside lamill aren't
    visible — Google's 429 stays the real authority."""
    from datetime import datetime, timezone
    from . import gsc_detail_cache as gdc
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = gdc._domain_dir(domain) / f"{today}.json"
    if not path.exists():
        return 0
    try:
        snap = gdc.load_snapshot(path)
    except (OSError, ValueError):
        return 0
    deep = snap.get(DEEP_SECTION) or {}
    n = sum(1 for r in deep.values()
            if isinstance(r, dict) and str(r.get("inspected_at", "")).startswith(today))
    v16 = snap.get("v16c_inspections")
    return n + (len(v16) if isinstance(v16, list) else 0)


def save_records(domain: str, records: dict[str, dict]) -> None:
    """Merge `records` into today's `deep_inspections` per URL, preserving
    every other section and every URL not in `records`."""
    from . import gsc_detail_cache as gdc
    merged = load_today_records(domain)
    merged.update(records)
    gdc.save_snapshot(domain, {DEEP_SECTION: merged})


def _is_quota_error(insp) -> bool:
    if insp.status != "error":
        return False
    if insp.http_status == 429:
        return True
    msg = (insp.error or "").lower()
    return "quota" in msg or "ratelimitexceeded" in msg or "rate limit" in msg


class _Throttle:
    """At most `per_minute` calls/min, as an even minimum interval."""
    def __init__(self, per_minute: int, clock, sleep):
        self.gap = 60.0 / max(1, per_minute)
        self.clock, self.sleep = clock, sleep
        self.last: float | None = None

    def wait(self) -> None:
        now = self.clock()
        if self.last is not None and now - self.last < self.gap:
            self.sleep(self.gap - (now - self.last))
            now = self.clock()
        self.last = now


def sweep_inspections(
    domain: str, urls: list[str], *, service, property_url: str,
    fresh: bool = False, budget: int | None = None,
    per_minute: int = SWEEP_PER_MINUTE,
    inspect=None, load_cache=None, save=None,
    clock=None, sleep=None,
    on_progress: Callable[[int, int, str, str], None] | None = None,
) -> SweepResult:
    """Inspect every URL in `urls` within the day's budget.

    * Same-day cache: a URL already inspected today (status ok) is reused
      unless `fresh`.
    * Budget: `URL_INSPECTION_DAILY_QUOTA` minus what lamill recorded
      today (override with `budget=`). URLs past the budget are listed in
      `not_inspected`; the next run picks them up from the cache.
    * A quota 429 from Google stops the sweep immediately (the failing URL
      counts as not inspected, not as an error).
    * Throttled under 600/min; progress saved every `SAVE_EVERY` calls.
    `on_progress(i, n, url, outcome)` — outcome is cached|ok|error|quota.
    """
    import time as _time
    from .gsc_recrawl import inspect_one_url
    from .project_seo_diagnostics import URL_INSPECTION_DAILY_QUOTA

    inspect = inspect or inspect_one_url
    load_cache = load_cache or load_today_records
    save = save or save_records
    clock = clock or _time.monotonic
    sleep = sleep or _time.sleep

    urls = list(dict.fromkeys(urls))
    cached = {} if fresh else load_cache(domain)
    if budget is None:
        budget = max(0, URL_INSPECTION_DAILY_QUOTA - inspections_used_today(domain))
    res = SweepResult(property_url=property_url, records={}, budget=budget)
    throttle = _Throttle(per_minute, clock, sleep)
    pending: dict[str, dict] = {}
    spent = 0

    def _flush() -> None:
        if pending:
            save(domain, dict(pending))
            pending.clear()

    try:
        for i, url in enumerate(urls, 1):
            hit = cached.get(url)
            if hit and hit.get("status") == "ok":
                res.records[url] = hit
                res.from_cache += 1
                if on_progress:
                    on_progress(i, len(urls), url, "cached")
                continue
            if res.stopped_reason or spent >= budget:
                res.stopped_reason = res.stopped_reason or "budget"
                res.not_inspected.append(url)
                continue
            throttle.wait()
            insp = inspect(service, property_url, url)
            spent += 1
            if _is_quota_error(insp):
                res.stopped_reason = "quota"
                res.not_inspected.append(url)
                if on_progress:
                    on_progress(i, len(urls), url, "quota")
                continue
            rec = inspection_record(insp)
            res.records[url] = rec
            pending[url] = rec
            if insp.status == "ok":
                res.inspected += 1
            else:
                res.errors += 1
            if on_progress:
                on_progress(i, len(urls), url, "ok" if insp.status == "ok" else "error")
            if len(pending) >= SAVE_EVERY:
                _flush()
    finally:
        _flush()
    return res


def open_gsc(domain: str):
    """BUG-104 staged preflight → (service, property_url). Raises
    `GscUnavailable` with the preflight's plain-words cause + fix."""
    from .gsc import get_service
    from .gsc_recrawl import pick_property
    from .seo_runtime import GscPreflightError, gsc_preflight
    try:
        creds, coverage = gsc_preflight()
    except GscPreflightError as e:
        raise GscUnavailable(str(e)) from e
    host = _site_host(domain.strip().lower())
    matches = coverage.get(host) or coverage.get("www." + host) or []
    if not matches:
        raise GscUnavailable(
            f"no Search Console property covers {host}. Add it in "
            f"https://search.google.com/search-console/welcome or run "
            f"`lamill new deploy {host}` (Step 9 registers it).")
    return get_service(creds), pick_property(matches)


# ======================================================================
# v51.D — baseline comparison (well-indexed fleet sites vs the target)
# ======================================================================
#
# Baselines cost zero URL Inspection quota (v51.A c): they're HTTP-crawled
# with the v51.B probe, their index state comes from the cache, and their
# GSC sitemap state from `sitemaps.list` (a different, unmetered-for-us API).

BASELINE_COUNT = 3
BASELINE_MIN_INSPECTED = 5
# A shingle on ≥ this share of pages is template boilerplate (nav, footer,
# shared intro copy) — only computed with ≥ 4 pages.
BOILERPLATE_SHARE = 0.5
NEAR_DUP_JACCARD = 0.8
NEAR_DUP_MAX_PAGES = 400          # O(n²) pair scan — sample above this


def _repo_age_days(domain: str) -> int | None:
    """Days since `launched` (portfolio.json) or the repo's root commit —
    the same rule as the dashboard's site age (BUG-105 fixed the shared
    helper, so this no longer carries its own git read)."""
    from datetime import date
    try:
        from .data import load_domains
        for d in load_domains():
            if d.name.lower() == domain and getattr(d, "launched", None):
                return (date.today() - d.launched).days
    except Exception:  # noqa: BLE001
        pass
    try:
        from .project import SITES_ROOT, fetch_first_commit_date
        first = fetch_first_commit_date(SITES_ROOT / domain)
        return (date.today() - first).days if first else None
    except Exception:  # noqa: BLE001
        return None


def _stack_of(domain: str) -> tuple[str | None, str | None]:
    """(framework, platform) from `sites/<domain>/lamill.toml`; (None, None)
    when absent (additive-optional invariant — never an error)."""
    try:
        from . import lamill_toml
        from .project import SITES_ROOT
        t = lamill_toml.load(SITES_ROOT / domain)
    except Exception:  # noqa: BLE001
        return None, None
    if t is None:
        return None, None
    fw = t.stack.framework if t.stack else None
    plat = t.deploy.platform if getattr(t, "deploy", None) else None
    return fw, plat


def _cached_index_counts(domain: str) -> tuple[int, int, str | None]:
    """(indexed, inspected, source) from the newest cached inspections —
    today's `deep_inspections` if present, else the newest `v16c_inspections`."""
    from .project_seo_diagnostics import _normalize_coverage_state
    deep = load_today_records(domain)
    recs = [r for r in deep.values() if isinstance(r, dict) and r.get("status") == "ok"]
    source = "deep_inspections (today)"
    if not recs:
        from .seo_diagnose import latest_inspections
        v16, day = latest_inspections(domain)
        recs, source = (v16 or []), (f"v16c_inspections ({day})" if v16 else None)
    states = [_normalize_coverage_state(r.get("coverage_state")) for r in recs]
    return sum(1 for s in states if s == "submitted_indexed"), len(states), source


@dataclass
class BaselinePick:
    domain: str
    framework: str | None
    platform: str | None
    indexed: int
    inspected: int
    source: str | None
    reason: str


def pick_baselines(target: str, *, n: int = BASELINE_COUNT,
                   override: list[str] | None = None,
                   candidates: list[str] | None = None) -> list[BaselinePick]:
    """Well-indexed comparison sites. `override` (`--baseline`) wins as-is.
    Otherwise: every domain with a GSC cache, ≥ `BASELINE_MIN_INSPECTED`
    cached inspections, ALL indexed; ranked same framework + same platform
    first, then same framework, then more inspected URLs, then name."""
    target = target.lower()
    t_fw, t_plat = _stack_of(target)
    if override:
        out = []
        for d in override:
            fw, plat = _stack_of(d.lower())
            idx, ins, src = _cached_index_counts(d.lower())
            out.append(BaselinePick(d.lower(), fw, plat, idx, ins, src, "operator --baseline"))
        return out
    if candidates is None:
        from . import gsc_detail_cache as gdc
        root = gdc.GSC_DETAIL_DIR
        candidates = sorted(p.name for p in root.iterdir()
                            if p.is_dir() and "." in p.name) if root.exists() else []
    scored = []
    for d in candidates:
        if d.lower() == target:
            continue
        idx, ins, src = _cached_index_counts(d)
        if ins < BASELINE_MIN_INSPECTED or idx != ins:
            continue
        fw, plat = _stack_of(d)
        same_fw = bool(t_fw) and fw == t_fw
        same_plat = bool(t_plat) and plat == t_plat
        rank = (0 if same_fw and same_plat else 1 if same_fw else 2, -ins, d)
        why = ("same framework + platform" if rank[0] == 0 else
               "same framework" if rank[0] == 1 else "fully indexed (other stack)")
        scored.append((rank, BaselinePick(d, fw, plat, idx, ins, src,
                                          f"{idx}/{ins} indexed · {why}")))
    scored.sort(key=lambda x: x[0])
    return [b for _, b in scored[:n]]


# ---------- sitemap shape (live file) + GSC sitemap state ----------


@dataclass
class SitemapShape:
    file_url: str | None
    is_index: bool = False
    child_count: int = 0
    url_count: int = 0
    lastmod_count: int = 0
    loc_hosts: list[str] = field(default_factory=list)   # distinct hosts in <loc>
    error: str | None = None

    @property
    def lastmod_share(self) -> float:
        return self.lastmod_count / self.url_count if self.url_count else 0.0


def sitemap_shape(origin: str, file_url: str | None,
                  client: httpx.Client) -> SitemapShape:
    """Re-read the discovered sitemap for the fields `_extract_locs` drops:
    index-vs-flat, `<lastmod>` coverage, hosts used in `<loc>`."""
    from xml.etree import ElementTree as ET
    shape = SitemapShape(file_url=file_url)
    if not file_url:
        shape.error = "no sitemap"
        return shape
    hosts: set[str] = set()

    def _read(url: str):
        r = client.get(url, follow_redirects=True)
        if r.status_code != 200:
            raise ValueError(f"HTTP {r.status_code} on {url}")
        return ET.fromstring(r.text)

    try:
        root = _read(file_url)
        files = [root]
        if root.tag.endswith("sitemapindex"):
            shape.is_index = True
            kids = [e.findtext("{*}loc", "").strip() for e in root.findall("{*}sitemap")]
            shape.child_count = len(kids)
            files = []
            for k in kids:
                if k:
                    hosts.add(urlsplit(k).netloc.lower())
                    try:
                        files.append(_read(k))
                    except (ValueError, ET.ParseError, httpx.HTTPError):
                        continue
        for f in files:
            for u in f.findall("{*}url"):
                loc = (u.findtext("{*}loc") or "").strip()
                if not loc:
                    continue
                shape.url_count += 1
                hosts.add(urlsplit(loc).netloc.lower())
                if (u.findtext("{*}lastmod") or "").strip():
                    shape.lastmod_count += 1
    except (ValueError, ET.ParseError, httpx.HTTPError) as e:
        shape.error = f"{type(e).__name__}: {e}"
    shape.loc_hosts = sorted(hosts)
    return shape


@dataclass
class GscSitemap:
    path: str
    last_submitted: str | None
    last_downloaded: str | None
    is_pending: bool
    is_index: bool
    errors: int
    warnings: int
    submitted: int | None        # `contents[type=web].submitted`


def gsc_sitemaps(service, property_url: str) -> list[GscSitemap] | None:
    """`sitemaps.list` for the property — what GSC has on file. None when
    the call fails (never raises). Note: `contents[].indexed` is always 0
    in the current API and is deliberately not read."""
    try:
        raw = service.sitemaps().list(siteUrl=property_url).execute().get("sitemap") or []
    except Exception:  # noqa: BLE001
        return None
    out = []
    for s in raw:
        web = next((c for c in (s.get("contents") or []) if c.get("type") == "web"), {})
        try:
            submitted = int(web.get("submitted")) if web.get("submitted") is not None else None
        except (TypeError, ValueError):
            submitted = None
        out.append(GscSitemap(
            path=s.get("path", ""), last_submitted=s.get("lastSubmitted"),
            last_downloaded=s.get("lastDownloaded"), is_pending=bool(s.get("isPending")),
            is_index=bool(s.get("isSitemapsIndex")),
            errors=int(s.get("errors") or 0), warnings=int(s.get("warnings") or 0),
            submitted=submitted))
    return out


# ---------- template / near-duplicate analysis ----------


@dataclass
class TextStats:
    pages: int
    median_words: float
    median_unique_words: float        # words not in site-wide boilerplate
    median_boilerplate_share: float   # share of a page's shingles that are boilerplate
    near_duplicate_pages: int         # pages ≥ NEAR_DUP_JACCARD to another, after boilerplate
    sampled: bool = False


def _median(xs: list[float]) -> float:
    xs = sorted(xs)
    if not xs:
        return 0.0
    m = len(xs) // 2
    return float(xs[m]) if len(xs) % 2 else (xs[m - 1] + xs[m]) / 2


def text_stats(probes: list[UrlProbe]) -> TextStats:
    pages = [p for p in probes if p.ok and p.shingles]
    if not pages:
        return TextStats(0, 0.0, 0.0, 0.0, 0)
    from collections import Counter
    boiler: set = set()
    if len(pages) >= 4:
        df = Counter(sh for p in pages for sh in p.shingles)
        cut = BOILERPLATE_SHARE * len(pages)
        boiler = {sh for sh, n in df.items() if n >= cut}
    shares, uniq, cores = [], [], []
    for p in pages:
        b = len(p.shingles & boiler) / len(p.shingles)
        shares.append(b)
        uniq.append(p.words * (1 - b))
        cores.append(p.shingles - boiler)
    sampled = len(cores) > NEAR_DUP_MAX_PAGES
    if sampled:
        step = len(cores) / NEAR_DUP_MAX_PAGES
        cores = [cores[int(i * step)] for i in range(NEAR_DUP_MAX_PAGES)]
    dup = set()
    for i in range(len(cores)):
        a = cores[i]
        if not a:
            continue
        for j in range(i + 1, len(cores)):
            b = cores[j]
            if b and len(a & b) / len(a | b) >= NEAR_DUP_JACCARD:
                dup.update((i, j))
    return TextStats(len(pages), _median([p.words for p in pages]),
                     _median(uniq), _median(shares), len(dup), sampled)


# ---------- site profile ----------


@dataclass
class SiteProfile:
    domain: str
    framework: str | None
    platform: str | None
    age_days: int | None
    indexed: int
    inspected: int
    index_source: str | None
    sitemap: SitemapShape
    gsc_sitemaps: list[GscSitemap] | None
    sitemap_urls: int
    probed: int
    crawl_capped: bool
    non_200: int
    redirected: int
    noindex: int
    robots_blocked: int
    empty_shells: int
    canonical_kinds: dict[str, int]
    home_outlinks: int
    share_linked_from_home: float
    median_depth: float
    max_depth: int | None
    orphans: int
    unreachable: int
    median_inbound: float
    linked_not_in_sitemap: int
    text: TextStats

    @property
    def index_rate(self) -> float | None:
        return self.indexed / self.inspected if self.inspected else None

    @property
    def gsc_sitemap_days(self) -> int | None:
        """Days since the most recent GSC sitemap submission among the
        property's sitemaps (oldest `lastSubmitted`). NOT the first-ever
        submission — the API only keeps the latest, so a resubmit resets it
        and this says nothing about how long Google has known the site."""
        return _days_since(min((g.last_submitted for g in (self.gsc_sitemaps or [])
                                if g.last_submitted), default=None))

    @property
    def gsc_downloaded_days(self) -> int | None:
        """Days since Google last downloaded any of the property's sitemaps."""
        return _days_since(max((g.last_downloaded for g in (self.gsc_sitemaps or [])
                                if g.last_downloaded), default=None))


def _days_since(iso: str | None) -> int | None:
    if not iso:
        return None
    from datetime import datetime, timezone
    try:
        ts = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - ts).days


def profile_site(domain: str, crawl: CrawlResult, *, service=None,
                 property_url: str | None = None,
                 client: httpx.Client | None = None) -> SiteProfile:
    domain = domain.lower()
    fw, plat = _stack_of(domain)
    idx, ins, src = _cached_index_counts(domain)

    def _factory() -> httpx.Client:
        return httpx.Client(timeout=HTTP_TIMEOUT, headers={"User-Agent": _GOOGLEBOT_UA})

    with managed_client(client, _factory) as c:
        shape = sitemap_shape(crawl.origin, crawl.sitemap_url, c)
    gsm = gsc_sitemaps(service, property_url) if service and property_url else None

    sm = [crawl.probes.get(url_key(u)) for u in crawl.sitemap_urls]
    sm = [p for p in sm if p is not None]
    home = crawl.probes.get(crawl.home_key)
    home_links = {url_key(u) for u in (home.internal_links if home else [])}
    non_home = [u for u in crawl.sitemap_urls if url_key(u) != crawl.home_key]
    depths = [d for d in (crawl.depth_of(u) for u in crawl.sitemap_urls) if d is not None]
    canon: dict[str, int] = {}
    for p in sm:
        if p.ok:
            canon[p.canonical_kind] = canon.get(p.canonical_kind, 0) + 1
    return SiteProfile(
        domain=domain, framework=fw, platform=plat, age_days=_repo_age_days(domain),
        indexed=idx, inspected=ins, index_source=src,
        sitemap=shape, gsc_sitemaps=gsm,
        sitemap_urls=len(crawl.sitemap_urls), probed=len(crawl.probes),
        crawl_capped=crawl.crawl_capped,
        non_200=sum(1 for p in sm if p.status != 200 or p.error),
        redirected=sum(1 for p in sm if p.redirected),
        noindex=sum(1 for p in sm if p.noindex),
        robots_blocked=sum(1 for p in sm if not p.robots_allowed),
        empty_shells=sum(1 for p in sm if p.empty_shell),
        canonical_kinds=canon,
        home_outlinks=len(home_links),
        share_linked_from_home=(sum(1 for u in non_home if url_key(u) in home_links)
                                / len(non_home)) if non_home else 0.0,
        median_depth=_median(depths), max_depth=max(depths) if depths else None,
        orphans=len(crawl.orphans), unreachable=len(crawl.unreachable_from_home),
        median_inbound=_median([crawl.inbound_count(u) for u in non_home]),
        linked_not_in_sitemap=len(crawl.linked_not_in_sitemap),
        text=text_stats(sm),
    )


# ---------- the comparison ----------

Better = Literal["higher", "lower", "none"]


@dataclass
class Contrast:
    signal: str
    label: str
    target: float | int | str | None
    baselines: dict[str, float | int | str | None]
    better: Better
    outside: bool          # target outside the baselines' [min, max]
    worse: bool            # outside AND on the bad side (only when better != none)


def _ratio(n: int, d: int) -> float:
    return n / d if d else 0.0


# (signal, label, getter, better)
_SIGNALS: list[tuple[str, str, Callable[[SiteProfile], float | None], Better]] = [
    ("index_rate", "share of inspected URLs indexed", lambda p: p.index_rate, "higher"),
    ("age_days", "site age (days, root commit / launched)", lambda p: p.age_days, "none"),
    ("gsc_sitemap_days", "days since the sitemap was last submitted to GSC",
     lambda p: p.gsc_sitemap_days, "none"),
    ("gsc_downloaded_days", "days since Google last downloaded the sitemap",
     lambda p: p.gsc_downloaded_days, "lower"),
    ("sitemap_urls", "sitemap URL count", lambda p: p.sitemap_urls, "none"),
    ("lastmod_share", "sitemap URLs with <lastmod>", lambda p: p.sitemap.lastmod_share, "none"),
    ("non_200_share", "sitemap URLs not 200", lambda p: _ratio(p.non_200, p.sitemap_urls), "lower"),
    ("redirect_share", "sitemap URLs that redirect", lambda p: _ratio(p.redirected, p.sitemap_urls), "lower"),
    ("noindex_share", "sitemap URLs with noindex", lambda p: _ratio(p.noindex, p.sitemap_urls), "lower"),
    ("non_self_canonical_share", "sitemap URLs not self-canonical",
     lambda p: _ratio(p.sitemap_urls - p.canonical_kinds.get("self", 0), p.sitemap_urls), "lower"),
    ("empty_shell_share", "sitemap URLs that render empty (no SSR)",
     lambda p: _ratio(p.empty_shells, p.sitemap_urls), "lower"),
    ("home_outlinks", "internal links on the homepage", lambda p: p.home_outlinks, "higher"),
    ("share_linked_from_home", "sitemap URLs linked from the homepage",
     lambda p: p.share_linked_from_home, "higher"),
    ("median_depth", "median clicks from / to a sitemap URL", lambda p: p.median_depth, "lower"),
    ("orphan_share", "sitemap URLs with no internal link",
     lambda p: _ratio(p.orphans, p.sitemap_urls), "lower"),
    ("median_inbound", "median internal links into a sitemap URL", lambda p: p.median_inbound, "higher"),
    ("median_words", "median words per page", lambda p: p.text.median_words, "higher"),
    ("median_unique_words", "median non-template words per page",
     lambda p: p.text.median_unique_words, "higher"),
    ("boilerplate_share", "median share of a page that is template",
     lambda p: p.text.median_boilerplate_share, "lower"),
    ("near_dup_share", "pages near-duplicate of another (after template)",
     lambda p: _ratio(p.text.near_duplicate_pages, max(p.text.pages, 1)), "lower"),
]


def compare(target: SiteProfile, baselines: list[SiteProfile]) -> list[Contrast]:
    """One `Contrast` per numeric signal. `outside` = target beyond the
    baselines' observed range; `worse` = outside on the bad side. No
    thresholds invented — the baselines' own spread is the yardstick."""
    out: list[Contrast] = []
    for sig, label, get, better in _SIGNALS:
        t = get(target)
        bvals = {b.domain: get(b) for b in baselines}
        nums = [v for v in bvals.values() if v is not None]
        outside = worse = False
        if t is not None and nums:
            lo, hi = min(nums), max(nums)
            outside = t < lo or t > hi
            if outside and better != "none":
                worse = (t < lo) if better == "higher" else (t > hi)
        out.append(Contrast(sig, label, t, bvals, better, outside, worse))
    return out


def categorical_notes(target: SiteProfile, baselines: list[SiteProfile]) -> list[str]:
    """Non-numeric differences worth stating (stack, sitemap form, GSC state)."""
    notes = []

    def _vals(get):
        return {b.domain: get(b) for b in baselines}
    for label, get in (("framework", lambda p: p.framework),
                       ("platform", lambda p: p.platform),
                       ("sitemap is an index", lambda p: p.sitemap.is_index)):
        t, bs = get(target), _vals(get)
        if any(v != t for v in bs.values()):
            notes.append(f"{label}: {target.domain}={t} vs " +
                         ", ".join(f"{d}={v}" for d, v in bs.items()))
    hosts_t = set(target.sitemap.loc_hosts)
    if len(hosts_t) > 1:
        notes.append(f"sitemap <loc> uses {len(hosts_t)} hosts: {', '.join(sorted(hosts_t))}")
    if target.gsc_sitemaps is not None:
        live = target.sitemap.file_url
        paths = [g.path for g in target.gsc_sitemaps]
        if not paths:
            notes.append("GSC has no sitemap on file for this property")
        elif live and live not in paths:
            notes.append(f"GSC's submitted sitemap(s) {paths} ≠ the live one ({live})")
        for g in target.gsc_sitemaps:
            if g.is_pending or g.errors or g.warnings:
                notes.append(f"GSC sitemap {g.path}: pending={g.is_pending} "
                             f"errors={g.errors} warnings={g.warnings}")
    return notes


@dataclass
class Comparison:
    target: SiteProfile
    baselines: list[SiteProfile]
    picks: list[BaselinePick]
    contrasts: list[Contrast]
    notes: list[str]

    @property
    def worse(self) -> list[Contrast]:
        return [c for c in self.contrasts if c.worse]


def compare_with_baselines(
    domain: str, target_crawl: CrawlResult, *, service=None,
    property_url: str | None = None, override: list[str] | None = None,
    n: int = BASELINE_COUNT, client: httpx.Client | None = None,
    crawl=None, on_baseline: Callable[[str], None] | None = None,
) -> Comparison:
    """Profile the target (from its v51.B crawl), pick + crawl baselines,
    and compare. Baselines' GSC sitemap state comes from `sitemaps.list`
    on their own property when `service` is given; never URL Inspection."""
    from .gsc_recrawl import pick_property
    crawl = crawl or crawl_site
    picks = pick_baselines(domain, n=n, override=override)
    target = profile_site(domain, target_crawl, service=service,
                          property_url=property_url, client=client)
    coverage = None
    if service is not None:
        try:
            from .gsc import coverage_map, list_properties
            coverage = coverage_map(list_properties(service))
        except Exception:  # noqa: BLE001
            coverage = None
    profiles = []
    for b in picks:
        if on_baseline:
            on_baseline(b.domain)
        bc = crawl(f"https://{b.domain}", client=client)
        bprop = None
        if coverage and coverage.get(b.domain):
            bprop = pick_property(coverage[b.domain])
        profiles.append(profile_site(b.domain, bc, service=service,
                                     property_url=bprop, client=client))
    return Comparison(target, profiles, picks, compare(target, profiles),
                      categorical_notes(target, profiles))


# ======================================================================
# v51.E — root-cause findings, per-URL status, JSON report
# ======================================================================
#
# Confidence tiers (v51.A e), no percentages:
#   confirmed — directly observed (a fetched page / an API field says so)
#   likely    — ≥ 2 independent signals agree, or a clear baseline contrast
#   possible  — one heuristic signal
# Ranked tier first, then by URLs affected. Fixes are text only — v51
# never applies them (read-only diagnostic).

REPORT_SCHEMA = "seo-deep-v1"
Tier = Literal["confirmed", "likely", "possible"]
Impact = Literal["high", "medium", "low"]
_TIER_ORDER = {"confirmed": 0, "likely": 1, "possible": 2}
_IMPACT_ORDER = {"high": 0, "medium": 1, "low": 2}
URL_SAMPLE = 5


@dataclass
class Finding:
    id: str
    title: str
    tier: Tier
    impact: Impact
    affected: int                           # URLs affected (0 = site-wide)
    evidence: list[str]
    fix: str
    urls: list[str] = field(default_factory=list)   # sample


@dataclass
class UrlStatus:
    """One sitemap URL: what Google says + what the crawl saw."""
    url: str
    coverage_state: str | None
    coverage_meaning: str
    last_crawl: str | None
    in_gsc_sitemap: bool | None             # Google ties the URL to a sitemap
    referring_urls: int | None
    google_canonical: str | None
    user_canonical: str | None
    http_status: int | None
    redirects: int
    canonical_kind: str
    noindex: bool
    robots_allowed: bool
    depth: int | None
    inbound: int
    words: int
    inspected: bool

    @property
    def discovery(self) -> str:
        """indexed / crawled / known / unknown / not-inspected — the
        discovery funnel stage, from the inspection."""
        from .project_seo_diagnostics import _normalize_coverage_state
        if not self.inspected:
            return "not-inspected"
        st = _normalize_coverage_state(self.coverage_state) or ""
        if st == "submitted_indexed":
            return "indexed"
        if self.last_crawl:
            return "crawled"
        if st == "url_is_unknown_to_google":
            return "unknown"
        return "known"


def url_statuses(crawl: CrawlResult, records: dict[str, dict]) -> list[UrlStatus]:
    from .project_seo_diagnostics import _normalize_coverage_state
    from .seo_diagnose import coverage_text
    out = []
    for u in crawl.sitemap_urls:
        p = crawl.probes.get(url_key(u)) or UrlProbe(url=u, in_sitemap=True)
        r = records.get(u)
        ok = bool(r) and r.get("status") == "ok"
        cov = r.get("coverage_state") if ok else None
        out.append(UrlStatus(
            url=u, coverage_state=cov,
            coverage_meaning=(coverage_text(cov)[0] if ok and cov and
                              _normalize_coverage_state(cov) != "submitted_indexed" else ""),
            last_crawl=r.get("last_crawl_time") if ok else None,
            in_gsc_sitemap=bool(r.get("sitemaps")) if ok else None,
            referring_urls=len(r.get("referring_urls") or []) if ok else None,
            google_canonical=r.get("google_canonical") if ok else None,
            user_canonical=r.get("user_canonical") if ok else None,
            http_status=p.status, redirects=len(p.redirects),
            canonical_kind=p.canonical_kind, noindex=p.noindex,
            robots_allowed=p.robots_allowed, depth=crawl.depth_of(u),
            inbound=crawl.inbound_count(u), words=p.words, inspected=ok,
        ))
    return out


def _sample(urls: list[str]) -> list[str]:
    return urls[:URL_SAMPLE]


def _pct(n: int, d: int) -> str:
    return f"{n}/{d}"


def derive_findings(crawl: CrawlResult, sweep: SweepResult | None,
                    comparison: Comparison | None,
                    statuses: list[UrlStatus]) -> list[Finding]:
    """Every rule reads observed data only. A rule that can't run (no
    inspection data, no baselines) emits nothing rather than guessing."""
    F: list[Finding] = []
    n = len(crawl.sitemap_urls)
    sm_probes = [crawl.probes.get(url_key(u)) for u in crawl.sitemap_urls]
    sm_probes = [p for p in sm_probes if p is not None]

    def urls_where(pred) -> list[str]:
        return [p.url for p in sm_probes if pred(p)]

    # ---- confirmed: site-wide blockers ----
    if crawl.robots.status is None or (crawl.robots.status or 0) >= 500:
        F.append(Finding(
            "robots-unreachable", "robots.txt is unreachable — Google treats the whole site as blocked",
            "confirmed", "high", n,
            [f"GET /robots.txt → {crawl.robots.status or 'no response'}"],
            "Make /robots.txt return 200 (or 404 if you have no rules)."))
    if not crawl.sitemap_urls:
        F.append(Finding(
            "sitemap-unreachable", "No sitemap could be read", "confirmed", "high", 0,
            [crawl.sitemap_error or "no sitemap found"],
            "Ship a valid sitemap and declare it in robots.txt (`Sitemap:` line)."))

    # ---- confirmed: per-URL technical problems (crawl) ----
    def per_url(fid, title, impact, pred, evidence, fix):
        hit = urls_where(pred)
        if hit:
            F.append(Finding(fid, title.format(k=len(hit), n=n), "confirmed", impact,
                             len(hit), [evidence.format(k=len(hit), n=n)], fix, _sample(hit)))

    per_url("robots-blocked", "{k} sitemap URL(s) blocked by robots.txt", "high",
            lambda p: not p.robots_allowed, "robots.txt rule matches {k}/{n} sitemap URLs",
            "Unblock them in robots.txt, or remove them from the sitemap.")
    per_url("noindex", "{k} sitemap URL(s) carry noindex", "high",
            lambda p: p.noindex, "noindex (meta or X-Robots-Tag) on {k}/{n} sitemap URLs",
            "Drop the noindex on pages that should rank; remove the rest from the sitemap.")
    per_url("non-200", "{k} sitemap URL(s) don't return 200", "high",
            lambda p: p.status != 200 or p.error is not None,
            "final status ≠ 200 (or fetch failed) on {k}/{n} sitemap URLs",
            "Fix or remove the failing URLs; the sitemap should list only live pages.")
    per_url("empty-shell", "{k} sitemap URL(s) render empty without JavaScript", "high",
            lambda p: p.empty_shell,
            "raw HTML has no title or < 40 chars of text on {k}/{n} sitemap URLs",
            "Server-render or pre-render these routes so crawlers see the content.")
    per_url("redirects", "{k} sitemap URL(s) redirect", "medium",
            lambda p: p.redirected, "{k}/{n} sitemap URLs answer with a 3xx",
            "List the final URL in the sitemap and link to it directly.")
    per_url("canonical-elsewhere", "{k} sitemap URL(s) declare a canonical pointing elsewhere",
            "medium", lambda p: p.ok and p.canonical_kind in ("other", "host_mismatch", "cross_site"),
            "<link rel=canonical> points to a different URL / host on {k}/{n} sitemap URLs",
            "Make each indexable page self-canonical, or drop non-canonical URLs from the sitemap.")
    per_url("canonical-conflict", "{k} sitemap URL(s) have conflicting canonical tags", "medium",
            lambda p: p.ok and p.canonical_kind == "multiple",
            "more than one <link rel=canonical> on {k}/{n} pages (Google ignores them all)",
            "Emit exactly one canonical per page.")
    orphans = crawl.orphans
    if orphans:
        F.append(Finding(
            "orphans", f"{len(orphans)} sitemap URL(s) have no internal link", "confirmed",
            "medium", len(orphans),
            [f"no crawled page links to {len(orphans)}/{n} sitemap URLs"],
            "Link every sitemap URL from at least one crawlable page (a hub or the homepage).",
            _sample(orphans)))
    hosts = None
    if comparison is not None:
        hosts = comparison.target.sitemap.loc_hosts
        if len(hosts) > 1:
            F.append(Finding(
                "sitemap-hosts", "Sitemap mixes hosts in <loc>", "confirmed", "medium", 0,
                [f"<loc> hosts: {', '.join(hosts)}"],
                "List only the canonical host (apex) in the sitemap."))

    # ---- confirmed: what GSC itself says ----
    gsm = comparison.target.gsc_sitemaps if comparison is not None else None
    live_sm = crawl.sitemap_url
    if gsm is not None:
        if not gsm:
            F.append(Finding(
                "gsc-no-sitemap", "No sitemap is submitted in Search Console", "confirmed",
                "high", 0, ["sitemaps.list returned nothing for the property"],
                f"Submit {live_sm or 'the sitemap'} in Search Console "
                "(`lamill settings gsc submit-sitemap`)."))
        else:
            paths = [g.path for g in gsm]
            if live_sm and live_sm not in paths:
                F.append(Finding(
                    "gsc-sitemap-mismatch", "Search Console has a different sitemap than the live one",
                    "confirmed", "high", 0, [f"GSC: {', '.join(paths)} · live: {live_sm}"],
                    f"Submit {live_sm} in Search Console and remove stale entries."))
            for g in gsm:
                if g.is_pending or g.errors or g.warnings:
                    F.append(Finding(
                        "gsc-sitemap-state", f"Search Console reports problems with {g.path}",
                        "confirmed", "medium", 0,
                        [f"pending={g.is_pending} errors={g.errors} warnings={g.warnings}"],
                        "Open the sitemap in Search Console → Sitemaps for the specific errors."))

    insp = [s for s in statuses if s.inspected]
    canon_diff = [s.url for s in insp if s.google_canonical and s.user_canonical
                  and url_key(s.google_canonical) != url_key(s.user_canonical)]
    if canon_diff:
        F.append(Finding(
            "google-canonical-differs", f"Google chose a different canonical for {len(canon_diff)} URL(s)",
            "confirmed", "medium", len(canon_diff),
            ["URL Inspection googleCanonical ≠ userCanonical"],
            "Make links, sitemap and canonical agree on one URL per page, or differentiate the content.",
            _sample(canon_diff)))

    # ---- inference: the discovery picture (needs inspections) ----
    if insp:
        from .project_seo_diagnostics import _normalize_coverage_state
        st = lambda s: _normalize_coverage_state(s.coverage_state) or ""
        unknown = [s for s in insp if st(s) == "url_is_unknown_to_google"]
        discovered = [s for s in insp if st(s) == "discovered_not_indexed"]
        crawled_no = [s for s in insp if st(s) == "crawled_not_indexed"]
        crawled = [s for s in insp if s.last_crawl]
        home = next((s for s in insp if url_key(s.url) == crawl.home_key), None)
        g_dl = comparison.target.gsc_downloaded_days if comparison else None
        g_sub = comparison.target.gsc_sitemap_days if comparison else None
        contrast = {c.signal: c for c in comparison.contrasts} if comparison else {}

        if unknown:
            ev = [f"{len(unknown)}/{len(insp)} inspected URLs: \"URL is unknown to Google\" "
                  "(never crawled, no referring pages)"]
            signals = 1
            # The API's `sitemap` field is empty even on indexed URLs of
            # well-indexed sc-domain properties (verified 2026-11-16 on
            # cottagefoodmap.com), so "empty everywhere" says nothing. Only a
            # MIXED picture — some URLs tied to the sitemap, the unknown ones
            # not — is evidence.
            with_ref = [s for s in insp if s.in_gsc_sitemap]
            unk_no_ref = [s for s in unknown if s.in_gsc_sitemap is False]
            if with_ref and unk_no_ref:
                ev.append(f"Google ties {len(with_ref)} inspected URL(s) to the sitemap but "
                          f"none of the {len(unk_no_ref)} unknown ones")
                signals += 1
            if g_dl is not None:
                # Google has the sitemap, so "never told about the URLs" is
                # ruled out — that's what makes "not queued" the reading.
                ev.append(f"Google last downloaded the sitemap {g_dl} day(s) ago"
                          + (f" (last resubmitted {g_sub} day(s) ago)" if g_sub is not None else ""))
                signals += 1
            # `lastSubmitted` is the latest resubmit, not first contact, so a
            # recency contrast with baselines is NOT evidence (calcengine:
            # resubmitted 2026-10-06, but its URLs were unknown since 2026-04).
            if home and home.last_crawl:
                ev.append(f"homepage last crawled {home.last_crawl[:10]}; "
                          f"{len(crawled)}/{len(insp)} inspected URLs ever crawled")
            F.append(Finding(
                "not-discovered",
                f"Google has read the sitemap but hasn't queued {len(unknown)} URL(s) for crawling",
                "likely" if signals >= 2 else "possible", "high", len(unknown), ev,
                "Raise crawl demand: link key pages from the homepage and hubs, earn external "
                "links to the site, and re-check after Google's next sitemap downloads. In "
                "Search Console, \"Request indexing\" on the most important pages (an operator "
                "action — lamill doesn't send indexing requests).",
                _sample([s.url for s in unknown])))
        if discovered:
            F.append(Finding(
                "discovered-not-crawled", f"{len(discovered)} URL(s) known to Google but not crawled",
                "confirmed", "medium", len(discovered),
                [f"coverage \"Discovered – currently not indexed\" on {len(discovered)} URLs"],
                "Usually low crawl priority: more internal links from strong pages, external links, time.",
                _sample([s.url for s in discovered])))
        if crawled_no:
            ev = [f"coverage \"Crawled – currently not indexed\" on {len(crawled_no)} URLs"]
            tier: Tier = "possible"
            for sig in ("median_unique_words", "boilerplate_share", "near_dup_share"):
                c = contrast.get(sig)
                if c and c.worse:
                    ev.append(f"{c.label}: {c.target:.2f} vs baselines "
                              f"{', '.join(f'{v:.2f}' for v in c.baselines.values() if v is not None)}")
                    tier = "likely"
            F.append(Finding(
                "crawled-not-indexed", f"Google crawled {len(crawled_no)} URL(s) and declined to index them",
                tier, "high", len(crawled_no), ev,
                "Treat as a quality signal: deepen each page with original content, cut "
                "templated / near-duplicate pages, or drop thin pages from the sitemap.",
                _sample([s.url for s in crawled_no])))

    # ---- inference: baseline contrasts not already explained ----
    if comparison is not None:
        contrast = {c.signal: c for c in comparison.contrasts}
        link_sigs = [contrast[s] for s in ("median_inbound", "share_linked_from_home",
                                           "home_outlinks", "median_depth", "orphan_share")
                     if s in contrast and contrast[s].worse]
        if link_sigs:
            F.append(Finding(
                "weak-internal-links", "Internal linking is weaker than on well-indexed sites",
                "likely" if len(link_sigs) >= 2 else "possible", "medium", 0,
                [f"{c.label}: {_fmt(c.target)} vs baselines "
                 f"{', '.join(_fmt(v) for v in c.baselines.values())}" for c in link_sigs],
                "Add contextual links between related pages and from hubs; aim for every page "
                "to have several internal links pointing in."))
        content_sigs = [contrast[s] for s in ("median_unique_words", "boilerplate_share",
                                              "near_dup_share", "median_words")
                        if s in contrast and contrast[s].worse]
        if content_sigs and not any(f.id == "crawled-not-indexed" for f in F):
            F.append(Finding(
                "thin-or-templated", "Pages are thinner or more templated than on well-indexed sites",
                "likely" if len(content_sigs) >= 2 else "possible", "medium", 0,
                [f"{c.label}: {_fmt(c.target)} vs baselines "
                 f"{', '.join(_fmt(v) for v in c.baselines.values())}" for c in content_sigs],
                "Add original, page-specific content; reduce shared template copy."))

    F.sort(key=lambda f: (_TIER_ORDER[f.tier], -f.affected, _IMPACT_ORDER[f.impact]))
    return F


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.2f}" if v < 10 else f"{v:.0f}"
    return str(v)


def prioritized_fixes(findings: list[Finding]) -> list[Finding]:
    """Same findings, ordered by impact for the "what to do first" list."""
    return sorted(findings, key=lambda f: (_IMPACT_ORDER[f.impact],
                                           _TIER_ORDER[f.tier], -f.affected))


@dataclass
class DeepReport:
    domain: str
    generated_at: str
    property_url: str | None
    crawl: CrawlResult
    sweep: SweepResult | None
    comparison: Comparison | None
    statuses: list[UrlStatus]
    findings: list[Finding]
    notes: list[str] = field(default_factory=list)

    def to_json(self) -> dict:
        from dataclasses import asdict
        cr = self.crawl
        cmp = self.comparison
        return {
            "schema": REPORT_SCHEMA,
            "domain": self.domain,
            "generated_at": self.generated_at,
            "property": self.property_url,
            "notes": self.notes,
            "sitemap": {"url": cr.sitemap_url, "urls": len(cr.sitemap_urls),
                        "error": cr.sitemap_error},
            "robots": {"status": cr.robots.status, "group": cr.robots.group},
            "crawl": {"pages_fetched": len(cr.probes), "capped": cr.crawl_capped,
                      "page_cap": cr.page_cap, "orphans": cr.orphans,
                      "unreachable_from_home": cr.unreachable_from_home,
                      "linked_not_in_sitemap": cr.linked_not_in_sitemap},
            "inspection": None if self.sweep is None else {
                "inspected": self.sweep.inspected, "from_cache": self.sweep.from_cache,
                "errors": self.sweep.errors, "not_inspected": self.sweep.not_inspected,
                "stopped_reason": self.sweep.stopped_reason, "budget": self.sweep.budget},
            "findings": [asdict(f) for f in self.findings],
            "fixes": [f.id for f in prioritized_fixes(self.findings)],
            "comparison": None if cmp is None else {
                "baselines": [asdict(b) for b in cmp.picks],
                "contrasts": [asdict(c) for c in cmp.contrasts],
                "notes": cmp.notes},
            "urls": [{**asdict(s), "discovery": s.discovery} for s in self.statuses],
        }


def build_report(domain: str, crawl: CrawlResult, *, sweep: SweepResult | None,
                 comparison: Comparison | None, property_url: str | None,
                 notes: list[str] | None = None) -> DeepReport:
    from datetime import datetime, timezone
    statuses = url_statuses(crawl, sweep.records if sweep else {})
    notes = list(notes or [])
    if crawl.crawl_capped:
        notes.append(f"crawl stopped at {crawl.page_cap} pages — link graph is partial")
    if sweep and sweep.not_inspected:
        notes.append(f"{len(sweep.not_inspected)} URL(s) not inspected "
                     f"({sweep.stopped_reason}); re-run tomorrow to resume from the cache")
    return DeepReport(
        domain=domain, generated_at=datetime.now(timezone.utc).isoformat(),
        property_url=property_url, crawl=crawl, sweep=sweep, comparison=comparison,
        statuses=statuses, findings=derive_findings(crawl, sweep, comparison, statuses),
        notes=notes)


def report_path(domain: str):
    from datetime import datetime, timezone
    from .data import ROOT
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return ROOT / "data" / "seo_deep" / domain.lower() / f"{day}.json"


def save_report(report: DeepReport, path=None):
    """Write the JSON report atomically (temp file + replace)."""
    import json
    import os
    path = path or report_path(report.domain)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report.to_json(), indent=2, default=str) + "\n")
    os.replace(tmp, path)
    return path
