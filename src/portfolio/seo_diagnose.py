"""v36 — `project seo` problem-surfacing diagnostic (project-scoped).

Turns the per-project SEO view from a green dashboard into a blocker
surfacer: it answers *why a site earns no traffic* across crawl /
discovery / index, even when lamill can't fix the cause. Project-scoped
by design — the heavy per-URL probes here NEVER run across the fleet
(`fleet seo` / dashboard keep their cheap emoji grade unchanged).

The pieces, smallest-blast-radius first:

  * `compute_state` — the pure aggregator. Maps signals (impressions,
    age, index insights, sitemap audit, render issues) to an explicit
    `State` (healthy / unproven / blocked) + a prioritized `Blocker`
    list. This is the honesty core: a 0-impression site with a
    not-indexed homepage is **blocked**, never green.
  * `read_index_insights` — surface the per-URL index state already
    cached at `data/gsc/<domain>/<date>.json` (`v16c_inspections`),
    which the old diagnostics block hid behind "no URLs inspected".
  * `audit_sitemap` — honest sitemap analysis (URL count + submitted +
    reachable + thinness), following robots `Sitemap:`, redirects, and
    recursing `<sitemapindex>` (mirrors rankmill ADR-0014) so the false
    "unreachable" goes away.
  * `probe_render` — fetch a URL's raw HTML and flag empty shells
    (no `<title>` / no body text) that render blank to crawlers (no SSR).

I/O (HTTP, cache reads) is injected so the aggregator + analyzers are
unit-testable without the network.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Literal

import httpx

from ._httpapi import managed_client
from .gsc_recrawl import (
    _GOOGLEBOT_UA,
    _SITEMAP_FALLBACK_PATHS,
    _extract_locs,
    _parse_robots_sitemap_urls,
)
from .project_seo_diagnostics import _normalize_coverage_state


# ---------- types ----------

# The honest replacement for the green grade (project-seo only).
State = Literal["healthy", "unproven", "blocked"]

# coverage_state tokens that mean "Google has this URL in the index".
# Everything else (crawled/discovered-not-indexed, 404, soft-404, robots-
# blocked, redirect/server error, unknown) is a discovery/index problem.
_INDEXED_STATES = frozenset({"submitted_indexed"})

# Default freshness window — mirrors seo_runtime.YOUNG_SITE_THRESHOLD_DAYS.
YOUNG_SITE_THRESHOLD_DAYS = 90


@dataclass(frozen=True)
class Blocker:
    """One detected reason the site earns no traffic, with a next action
    even when lamill can't fix it. `kind` ⛔ (hard — drives `blocked`) vs
    ⚠ (warn — a real problem, but not a state-defining one on its own)."""
    kind: Literal["blocker", "warn"]
    title: str
    detail: str
    next_action: str

    @property
    def glyph(self) -> str:
        return "⛔" if self.kind == "blocker" else "⚠"


@dataclass(frozen=True)
class IndexInsight:
    """Per-URL index state, read from the cached GSC URL-inspection."""
    url: str
    coverage_state: str | None    # normalized token, e.g. crawled_not_indexed
    coverage_label: str           # human text as GSC reported it
    verdict: str | None
    last_crawl_at: str | None

    @property
    def is_indexed(self) -> bool:
        return (self.coverage_state or "") in _INDEXED_STATES


@dataclass
class SitemapAudit:
    """Honest sitemap state — replaces the /sitemap.xml-returns-200 cell."""
    reachable: bool                 # we could fetch + parse a sitemap
    url_count: int                  # # of page URLs (recursed through indexes)
    sitemap_url: str | None         # the sitemap file we found (for "submit X")
    submitted_to_gsc: bool          # GSC has it in sites/.../sitemaps
    page_urls: list[str] = field(default_factory=list)
    error: str | None = None        # why unreachable, when reachable is False

    @property
    def thin(self) -> bool:
        # "only the homepage" — 1 URL (or 0) is suspicious for any real site.
        return self.reachable and self.url_count <= 1

    @property
    def healthy(self) -> bool:
        # Green only if submitted AND reachable AND more than one URL.
        return self.submitted_to_gsc and self.reachable and self.url_count > 1


@dataclass(frozen=True)
class RenderIssue:
    """One URL's crawler-render check: does the raw HTML carry a title +
    visible body, or is it an empty SSR-less shell?"""
    url: str
    has_title: bool
    has_body_text: bool
    error: str | None = None

    @property
    def empty_shell(self) -> bool:
        return self.error is None and not (self.has_title and self.has_body_text)


# ---------- index insights (from the v16c cache) ----------


def read_index_insights(
    domain: str,
    *,
    loader: Callable[[str], list[dict] | None] | None = None,
) -> list[IndexInsight]:
    """Surface the per-URL index state already cached under
    `data/gsc/<domain>/<date>.json` (`v16c_inspections`). The old
    diagnostics block hid this behind a failed *live* fetch ("no URLs
    inspected"); here we read what's on disk. `loader` is injectable for
    tests; the default reads the freshest snapshot.
    """
    raw = (loader or _default_inspections_loader)(domain)
    if not raw:
        return []
    out: list[IndexInsight] = []
    for insp in raw:
        if not isinstance(insp, dict) or insp.get("status") == "error":
            continue
        label = insp.get("coverage_state") or ""
        out.append(IndexInsight(
            url=str(insp.get("url") or ""),
            coverage_state=_normalize_coverage_state(label) if label else None,
            coverage_label=label,
            verdict=insp.get("verdict"),
            last_crawl_at=insp.get("last_crawl_time"),
        ))
    return out


def _default_inspections_loader(domain: str) -> list[dict] | None:
    """Read `v16c_inspections` from the freshest per-domain snapshot.
    Tolerant of a missing/old cache — returns None so callers degrade."""
    from .gsc_detail_cache import latest_snapshot, load_snapshot
    latest = latest_snapshot(domain)
    if latest is None:
        return None
    try:
        snap = load_snapshot(latest)
    except (OSError, ValueError):
        return None
    insp = snap.get("v16c_inspections")
    return insp if isinstance(insp, list) else None


# ---------- sitemap audit (robots → redirects → recurse index) ----------


def audit_sitemap(
    origin: str,
    *,
    submitted_to_gsc: bool,
    client: httpx.Client | None = None,
    max_urls: int = 5000,
) -> SitemapAudit:
    """Honestly analyze the live sitemap for `origin` (e.g.
    `https://airsucks.com`): discover via robots.txt `Sitemap:` then the
    standard fallback paths, follow redirects, and recurse one level of
    `<sitemapindex>` (rankmill ADR-0014). Returns counts + reachability +
    the sitemap file URL (for a "submit X to GSC" action).

    Fixes the false "unreachable": the previous probe gave up if
    `/sitemap.xml` wasn't a literal 200, ignoring robots declarations and
    `<sitemapindex>` children.
    """
    def _factory() -> httpx.Client:
        return httpx.Client(
            timeout=10.0, follow_redirects=True,
            headers={"User-Agent": _GOOGLEBOT_UA},
        )

    with managed_client(client, _factory) as c:
        sitemap_url, page_urls, err = _discover_pages(origin, c, max_urls)

    return SitemapAudit(
        reachable=sitemap_url is not None,
        url_count=len(page_urls),
        sitemap_url=sitemap_url,
        submitted_to_gsc=submitted_to_gsc,
        page_urls=page_urls,
        error=err,
    )


def _candidate_sitemaps(origin: str, client: httpx.Client) -> list[str]:
    """robots.txt `Sitemap:` declarations first (authoritative, matches
    Googlebot), then the standard fallback paths."""
    declared: list[str] = []
    try:
        r = client.get(origin.rstrip("/") + "/robots.txt")
        if r.status_code == 200:
            declared = _parse_robots_sitemap_urls(r.text)
    except httpx.HTTPError:
        pass
    fallbacks = [origin.rstrip("/") + p for p in _SITEMAP_FALLBACK_PATHS]
    # Preserve order, dedupe.
    seen: set[str] = set()
    out: list[str] = []
    for u in declared + fallbacks:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _discover_pages(
    origin: str, client: httpx.Client, max_urls: int,
) -> tuple[str | None, list[str], str | None]:
    """Return (sitemap_file_url, page_urls, error). Walks one level of
    `<sitemapindex>`. The first candidate that parses into a urlset OR a
    sitemapindex wins as the canonical `sitemap_url`."""
    candidates = _candidate_sitemaps(origin, client)
    sitemap_url: str | None = None
    pages: list[str] = []
    seen_pages: set[str] = set()
    last_err: str | None = None

    for cand in candidates:
        try:
            r = client.get(cand)
        except httpx.HTTPError as e:
            last_err = f"{type(e).__name__} on {cand}"
            continue
        if r.status_code != 200 or not r.text.strip():
            last_err = f"HTTP {r.status_code} on {cand}"
            continue
        try:
            urls, nested = _extract_locs(r.text)
        except Exception as e:  # noqa: BLE001 — malformed XML, any parser error
            last_err = f"unparseable XML on {cand}: {e}"
            continue
        # This candidate is a real sitemap (urlset or index).
        sitemap_url = str(r.url)        # post-redirect URL
        for u in urls:
            if u not in seen_pages:
                seen_pages.add(u)
                pages.append(u)
        # Recurse one level into nested sitemaps.
        for child in nested:
            if len(pages) >= max_urls:
                break
            try:
                cr = client.get(child)
            except httpx.HTTPError:
                continue
            if cr.status_code != 200:
                continue
            try:
                child_urls, _ = _extract_locs(cr.text)
            except Exception:  # noqa: BLE001
                continue
            for u in child_urls:
                if u not in seen_pages and len(pages) < max_urls:
                    seen_pages.add(u)
                    pages.append(u)
        break  # first usable sitemap wins

    if sitemap_url is None:
        return None, [], last_err or "no sitemap found"
    return sitemap_url, pages, None


# ---------- render / crawlability probe ----------

_TITLE_RE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
# Minimum visible body characters to count as "renders content".
_MIN_BODY_CHARS = 40


def probe_render(
    url: str, *, client: httpx.Client | None = None,
) -> RenderIssue:
    """Fetch a URL's raw HTML (as a crawler sees it, no JS) and check it
    carries a non-empty `<title>` AND visible body text. A client-rendered
    SPA route with an empty `<div id="root">` shell fails both → flagged as
    "renders empty to crawlers (no SSR)"."""
    def _factory() -> httpx.Client:
        return httpx.Client(
            timeout=10.0, follow_redirects=True,
            headers={"User-Agent": _GOOGLEBOT_UA},
        )
    try:
        with managed_client(client, _factory) as c:
            r = c.get(url)
        if r.status_code != 200:
            return RenderIssue(url, False, False, error=f"HTTP {r.status_code}")
        html = r.text
    except httpx.HTTPError as e:
        return RenderIssue(url, False, False, error=type(e).__name__)

    return RenderIssue(
        url=url,
        has_title=_has_title(html),
        has_body_text=_has_body_text(html),
    )


def _has_title(html: str) -> bool:
    m = _TITLE_RE.search(html)
    return bool(m and m.group(1).strip())


def _has_body_text(html: str) -> bool:
    """Visible text = HTML with script/style stripped, tags removed,
    whitespace collapsed. An SSR-less shell collapses to near-empty."""
    body = _SCRIPT_STYLE_RE.sub(" ", html)
    body = _TAG_RE.sub(" ", body)
    text = " ".join(body.split())
    return len(text) >= _MIN_BODY_CHARS


# ---------- the aggregator (pure) ----------


def _homepage_urls(origin: str) -> set[str]:
    """The handful of spellings that mean 'the homepage' for `origin`."""
    o = origin.rstrip("/")
    return {o, o + "/", o + "/index.html"}


def compute_state(
    *,
    origin: str,
    impressions: int | None,
    site_age_days: int | None,
    index_insights: list[IndexInsight],
    sitemap_audit: SitemapAudit | None,
    render_issues: list[RenderIssue] | None = None,
    content_configured: bool | None = None,
    young_threshold_days: int = YOUNG_SITE_THRESHOLD_DAYS,
) -> tuple[State, list[Blocker]]:
    """The honesty core. Detect every blocker, then derive State:

      * `healthy`  — earning traffic (impressions > 0).
      * `blocked`  — 0 traffic AND a hard blocker (⛔), OR 0 traffic past
                     the freshness window (the absence of traffic IS the
                     problem once the site is no longer new).
      * `unproven` — young, 0 traffic yet, nothing else detected wrong.

    Returns (state, blockers) with blockers ordered ⛔ before ⚠.
    """
    render_issues = render_issues or []
    homes = _homepage_urls(origin)
    blockers: list[Blocker] = []

    # --- index state (the headline) ---
    for ins in index_insights:
        if ins.is_indexed:
            continue
        is_home = ins.url.rstrip("/") + "/" in {h.rstrip("/") + "/" for h in homes}
        label = ins.coverage_label or ins.coverage_state or "not indexed"
        if is_home:
            blockers.append(Blocker(
                kind="blocker",
                title=f'Homepage "{label}" (GSC)',
                detail="Google has crawled the homepage but is not indexing it "
                       "— a content/authority signal, not a technical fault.",
                next_action="Strengthen the page (substantive original content, "
                            "internal links, backlinks); not lamill-fixable.",
            ))
        else:
            blockers.append(Blocker(
                kind="warn",
                title=f'{ins.url} "{label}" (GSC)',
                detail="URL is known to Google but not indexed.",
                next_action="Improve the page or remove it from the sitemap.",
            ))

    # --- sitemap honesty ---
    if sitemap_audit is not None:
        if not sitemap_audit.reachable:
            blockers.append(Blocker(
                kind="blocker",
                title="Sitemap unreachable",
                detail=f"No sitemap could be fetched/parsed "
                       f"({sitemap_audit.error or 'unknown'}). Google can't "
                       f"discover the site's URLs.",
                next_action="Ship a valid sitemap.xml (and declare it in "
                            "robots.txt).",
            ))
        else:
            if sitemap_audit.thin:
                blockers.append(Blocker(
                    kind="warn",
                    title=f"Sitemap lists only {sitemap_audit.url_count} URL"
                          f"{'' if sitemap_audit.url_count == 1 else 's'}",
                    detail="The site's other routes are undiscoverable — they "
                           "aren't in the sitemap.",
                    next_action="Add every indexable route to the sitemap.",
                ))
            if not sitemap_audit.submitted_to_gsc:
                target = sitemap_audit.sitemap_url or f"{origin.rstrip('/')}/sitemap.xml"
                blockers.append(Blocker(
                    kind="warn",
                    title="Sitemap not submitted to GSC",
                    detail="Google isn't being told where the sitemap is.",
                    next_action=f"Submit {target} in Search Console "
                                f"(or `lamill project sitemap resubmit {_host(origin)}`).",
                ))

    # --- render / crawlability ---
    empty = [ri for ri in render_issues if ri.empty_shell]
    if empty:
        sample = ", ".join(ri.url for ri in empty[:3])
        more = f" (+{len(empty) - 3} more)" if len(empty) > 3 else ""
        blockers.append(Blocker(
            kind="warn",
            title=f"{len(empty)} URL(s) render empty to crawlers (no SSR)",
            detail=f"These return an empty shell with no title/body to a "
                   f"non-JS crawler: {sample}{more}.",
            next_action="Server-render or pre-render these routes so crawlers "
                        "see real content.",
        ))

    # --- content identity ---
    if content_configured is False:
        blockers.append(Blocker(
            kind="warn",
            title="[content] unconfigured",
            detail="lamill.toml has no [content] block — the site has no "
                   "declared SEO identity (title/description/keywords).",
            next_action="Populate [content] in the site's lamill.toml.",
        ))

    # --- derive state ---
    young = site_age_days is not None and site_age_days < young_threshold_days
    has_hard = any(b.kind == "blocker" for b in blockers)
    if impressions and impressions > 0:
        state: State = "healthy"
    elif has_hard:
        state = "blocked"
    elif impressions == 0 and not young:
        # KNOWN-zero impressions past the freshness window: the silence IS
        # the blocker, even if nothing else was independently detected.
        # (impressions=None means "unknown" — don't fabricate a blocker.)
        age_txt = (f"after {site_age_days}d" if site_age_days is not None
                   else "and past the freshness window")
        blockers.append(Blocker(
            kind="blocker",
            title=f"0 impressions {age_txt}",
            detail="The site is no longer new but earns nothing — it isn't "
                   "being discovered, indexed, or ranked.",
            next_action="Work through the blockers above; if none, the gap "
                        "is content/authority.",
        ))
        state = "blocked"
    else:
        # young (still in the freshness window), or impressions unknown with
        # no hard blocker detected.
        state = "unproven"

    blockers.sort(key=lambda b: 0 if b.kind == "blocker" else 1)
    return state, blockers


def _host(origin: str) -> str:
    return origin.split("://", 1)[-1].strip("/").lower()


# Operator-facing one-liners for the State header.
STATE_RENDER: dict[State, tuple[str, str]] = {
    "healthy": ("🟢", "healthy — earning traffic"),
    "unproven": ("🌱", "unproven — young, no traffic yet (nothing else wrong)"),
    "blocked": ("⛔", "blocked — earning no traffic, blockers below"),
}


# ---------- orchestrator (real I/O; wired into `project seo`) ----------


@dataclass
class SeoDiagnosis:
    """The assembled per-domain diagnosis the renderer consumes."""
    domain: str
    origin: str
    state: State
    blockers: list[Blocker]
    impressions: int | None
    site_age_days: int | None
    index_insights: list[IndexInsight] = field(default_factory=list)
    sitemap_audit: SitemapAudit | None = None
    render_probed: int = 0          # how many URLs the render probe covered
    notes: list[str] = field(default_factory=list)


# Cap the per-URL render probe so an interactive `project seo` on a large
# sitemap stays fast. The thinness/index/sitemap signals don't need it.
_RENDER_PROBE_CAP = 20


def gather_seo_diagnosis(domain: str, *,
                         render_probe_cap: int = _RENDER_PROBE_CAP) -> SeoDiagnosis:
    """Assemble every signal for `domain` and compute State + Blockers.
    Each source degrades independently — a missing seo snapshot, an
    unreachable sitemap, or an absent local repo never crashes the view;
    they just narrow what can be asserted (recorded in `notes`)."""
    domain = domain.lower()
    origin = f"https://{domain}"

    impressions, submitted_to_gsc, notes = _impressions_and_submitted(domain)
    site_age_days = _resolve_age(domain)
    index_insights = read_index_insights(domain)

    sitemap_audit: SitemapAudit | None = None
    try:
        sitemap_audit = audit_sitemap(origin, submitted_to_gsc=submitted_to_gsc)
    except Exception as e:  # noqa: BLE001 — never crash the view on a probe
        notes.append(f"sitemap audit failed: {type(e).__name__}")

    # Render-probe the sitemap's page URLs (homepage at minimum), capped.
    render_issues: list[RenderIssue] = []
    probe_targets = list(sitemap_audit.page_urls) if sitemap_audit else []
    if origin + "/" not in probe_targets and origin not in probe_targets:
        probe_targets.insert(0, origin + "/")
    probe_targets = probe_targets[:render_probe_cap]
    for u in probe_targets:
        try:
            render_issues.append(probe_render(u))
        except Exception:  # noqa: BLE001
            pass
    if sitemap_audit and len(sitemap_audit.page_urls) > render_probe_cap:
        notes.append(f"render probe sampled {render_probe_cap}/"
                     f"{len(sitemap_audit.page_urls)} URLs")

    content_configured = _content_configured(domain)

    state, blockers = compute_state(
        origin=origin,
        impressions=impressions,
        site_age_days=site_age_days,
        index_insights=index_insights,
        sitemap_audit=sitemap_audit,
        render_issues=render_issues,
        content_configured=content_configured,
    )
    return SeoDiagnosis(
        domain=domain, origin=origin, state=state, blockers=blockers,
        impressions=impressions, site_age_days=site_age_days,
        index_insights=index_insights, sitemap_audit=sitemap_audit,
        render_probed=len(probe_targets), notes=notes,
    )


def _impressions_and_submitted(domain: str) -> tuple[int | None, bool, list[str]]:
    """Read impressions + sitemap-submitted from the freshest `fleet seo`
    snapshot. Impressions=None when no snapshot exists (→ State stays
    'unproven', never fabricated as blocked)."""
    notes: list[str] = []
    try:
        from .seo_cache import latest_snapshot, load_snapshot, rows_from_snapshot
        latest = latest_snapshot()
        if latest is None:
            notes.append("no fleet-seo snapshot — impressions unknown "
                         "(run `fleet seo --refresh`)")
            return None, False, notes
        rows = rows_from_snapshot(load_snapshot(latest))
        for r in rows:
            if r.domain.lower() == domain:
                submitted = bool(r.gsc_sitemap_count and r.gsc_sitemap_count > 0)
                return r.gsc_impressions, submitted, notes
        notes.append(f"{domain} not in the latest seo snapshot")
    except Exception as e:  # noqa: BLE001
        notes.append(f"seo snapshot read failed: {type(e).__name__}")
    return None, False, notes


def _resolve_age(domain: str) -> int | None:
    try:
        from .dashboard import _site_age_days
        from .data import load_domains
        launched = None
        for d in load_domains():
            if d.name.lower() == domain:
                launched = getattr(d, "launched", None)
                break
        return _site_age_days(domain, launched)
    except Exception:  # noqa: BLE001
        return None


def _content_configured(domain: str) -> bool | None:
    """True/False when the local repo's `lamill.toml` is readable (does it
    declare a `[content]` block?), None when there's no local repo to check
    (so the aggregator skips the blocker rather than guessing)."""
    try:
        from .project import SITES_ROOT
        toml_path = SITES_ROOT / domain / "lamill.toml"
        if not toml_path.exists():
            return None
        import tomllib
        with open(toml_path, "rb") as fh:
            data = tomllib.load(fh)
        return bool(data.get("content"))
    except Exception:  # noqa: BLE001
        return None
