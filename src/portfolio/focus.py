"""v5.F.1 — `portfolio focus`: top-5 domains to focus on today.

Pulls four priority signals from existing caches (never blocks on a live
fetch) and ranks domains by the worst signal each one carries:

  🔴 Site down       — `data/checks/<latest>.json` classification
                       ∈ {dead, ssl-broken, error}, OR HTTP non-2xx
  ⚠️  Expiring soon   — `data/portfolio.json`, days_to_expire ≤ 30
  🟠 Indexed but 0 imp — `data/seo/<latest>.json` gsc_status=ok and
                       gsc_impressions == 0
  🟡 Bad position     — `data/seo/<latest>.json` gsc_position > 20

Each signal carries an actionable one-liner. The output is the top 5
by severity (red > orange > yellow > grey), then alphabetical for ties.
`--all` prints the full ranked list.

Age-aware suppression: the two SEO signals (🟠 zero-imp and 🟡 bad
position) are normal for fresh sites — Google parks new origins at
high positions and slow-rolls indexing during the freshness window.
Sites with `site_age_days < YOUNG_SITE_THRESHOLD_DAYS` (default 90)
have those signals suppressed so the focus list shows real problems,
not "your 3-week-old site looks like a 3-week-old site." Site age
comes from `portfolio.json.launched` (manual) or first-commit
inference (same source as the dashboard). 🔴 site-down and ⚠️
expiry signals are not suppressed — broken is broken regardless.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# Severity rank — higher = surfaces first.
_RANK_RED = 4
_RANK_ORANGE = 3
_RANK_YELLOW = 2
# v27.F — a tracked high-priority todo is below every live problem: a
# declared task shouldn't outrank a site that's actually down / buried.
_RANK_TODO = 1
_RANK_OK = 0


@dataclass
class FocusItem:
    """One row in the focus ranking. `signals` carries every triggered
    signal; the worst one drives `rank` and the first emoji shown."""
    domain: str
    rank: int = _RANK_OK
    signals: list[tuple[str, str, str]] = field(default_factory=list)
    # Each signal: (emoji, headline, action)


# Categories whose domains should NEVER appear in focus output. A domain
# the user has explicitly marked for deletion isn't worth surfacing as
# a problem to fix.
IGNORE_CATEGORIES = frozenset({"to be deleted immediately"})

# Sites younger than this in days don't get 🟠 zero-impressions or 🟡
# bad-position signals — those are normal in the Google freshness window.
YOUNG_SITE_THRESHOLD_DAYS = 90


def build_focus_list(
    *,
    live_snapshot: dict | None,
    seo_snapshot: dict | None,
    domains_with_expiry: list[tuple[str, int]],
    domain_categories: dict[str, str] | None = None,
    domain_site_age_days: dict[str, int | None] | None = None,
    domain_check_failures: dict[str, dict] | None = None,
    domain_high_todos: dict[str, str] | None = None,
    include_young: bool = False,
    young_threshold_days: int = YOUNG_SITE_THRESHOLD_DAYS,
    suppressed_young_out: list[str] | None = None,
) -> list[FocusItem]:
    """Build the ranked focus list from three pre-loaded data sources.

    `live_snapshot` is the parsed JSON of `data/checks/<latest>.json`.
    `seo_snapshot` is the parsed JSON of `data/seo/<latest>.json`.
    `domains_with_expiry` is `[(domain, days_to_expire)]` from
    `portfolio.json`. `domain_categories` maps domain → plan category
    (lowercase keys); domains in `IGNORE_CATEGORIES` are filtered out.
    `domain_site_age_days` maps domain → site age in days (None when
    unknown). When `include_young` is False (the default), domains
    younger than `young_threshold_days` have their 🟠/🟡 SEO signals
    suppressed — flagging "buried" or "zero impressions" on a 3-week-old
    site is noise, not actionable advice. None / [] for any input
    means "skip that signal."

    `suppressed_young_out`, if provided, is mutated in place with the
    sorted list of young-site domains whose SEO signals were filtered
    out. Lets callers render a transparency note ("3 young sites
    suppressed from focus") without changing the return shape.

    `domain_check_failures` maps domain → {check_id: failure_message}.
    Used to surface specific deploy/ops checks (currently CHECK_057 —
    stale Cloudflare edge cache) as focus signals without requiring
    the focus path to re-run network probes itself. None / empty means
    "skip the check-driven signals."

    `domain_high_todos` maps domain → the text of that site's top open
    `high`-priority todo (from its `lamill.toml` `[[todo]]` table). Each
    becomes a 📝 signal at `_RANK_TODO` — below every live signal. The
    caller (`focus()`) gathers this from disk, so the signal is available
    even when `refresh=False` and no live snapshot exists (honors focus's
    "never blocks on a live fetch" contract). None / empty means "skip."
    """
    domain_check_failures = domain_check_failures or {}
    domain_high_todos = domain_high_todos or {}
    domain_categories = domain_categories or {}
    domain_site_age_days = domain_site_age_days or {}
    items: dict[str, FocusItem] = {}
    suppressed_young: set[str] = set()

    def _is_young(d: str) -> bool:
        age = domain_site_age_days.get(d.lower())
        if age is None:
            # Unknown age — don't suppress. Better to over-flag than miss
            # a real problem on a domain we lack metadata for.
            return False
        return age < young_threshold_days

    def _is_ignored(d: str) -> bool:
        cat = domain_categories.get(d.lower(), "").lower()
        return cat in IGNORE_CATEGORIES

    def _get(d: str) -> FocusItem:
        if d not in items:
            items[d] = FocusItem(domain=d)
        return items[d]

    def _add_signal(d: str, emoji: str, rank: int, headline: str, action: str) -> None:
        if _is_ignored(d):
            return
        item = _get(d)
        item.signals.append((emoji, headline, action))
        if rank > item.rank:
            item.rank = rank

    # 🔴 Site-down signals from the live snapshot.
    # Only flag a domain as down when *every* probed variant (bare + www)
    # failed. A common DNS setup has bare timing out while www serves the
    # real site; reporting the domain dead in that case was misleading
    # (focus.py used to dedup-by-bare and miss this).
    if live_snapshot:
        bad_classes = ("dead", "ssl-broken", "error")
        good_classes = ("live-site", "forwarder", "parked")
        by_domain: dict[str, list[dict]] = {}
        for r in live_snapshot.get("results", []):
            d = r.get("domain", "").lower()
            if not d:
                continue
            by_domain.setdefault(d, []).append(r)
        for d, variants in by_domain.items():
            has_good = any(v.get("classification") in good_classes for v in variants)
            if has_good:
                # At least one variant works → the site is reachable, even
                # if the apex or www-only variant is broken. Don't flag.
                continue
            # All variants bad. Pick the worst one for the headline.
            worst = next((v for v in variants if v.get("classification") in bad_classes), None)
            if worst is not None:
                cls = worst.get("classification")
                action = _site_down_action(d, cls, worst.get("error"))
                _add_signal(d, "🔴", _RANK_RED,
                            f"Site is {cls}", f"→ {action}")
                continue
            # No good and no recognized-bad → check for non-2xx HTTP only
            # if every variant is non-2xx (a single good 200 wins above).
            non2xx = next(
                (v for v in variants
                 if isinstance(v.get("status"), int)
                 and not (200 <= v["status"] < 300)),
                None,
            )
            if non2xx is not None:
                _add_signal(d, "🔴", _RANK_RED,
                            f"HTTP {non2xx['status']}",
                            "→ check deploy logs / origin server")

        # 🟡 Forwarder / parked — domain answers but isn't serving real content
        # here. Mirrors the dashboard's Live-dot convention (both forwarder
        # and parked are yellow). A WIP-scoped forwarder/parked domain is a
        # decision item: either build something or stop holding it idle.
        # Skip if already flagged 🔴 — those signals win.
        for d, variants in by_domain.items():
            existing = items.get(d)
            if existing is not None and existing.rank >= _RANK_RED:
                continue
            classes = [v.get("classification") for v in variants]
            idle_classes = {"forwarder", "parked"}
            if classes and all(c in idle_classes for c in classes):
                # `parked` is the more inert state — surface it specifically.
                cls = "parked" if "parked" in classes else "forwarder"
                _add_signal(d, "🟡", _RANK_YELLOW,
                            f"Domain {cls} — not serving real content here",
                            "→ build site here, retire, or sell")

    # ⚠️ Expiring within 30 days.
    for d, days in domains_with_expiry:
        if days is None:
            continue
        if days <= 30:
            _add_signal(d, "⚠️", _RANK_RED,
                        f"Expiring in {days} days",
                        "→ renew at registrar before lapse")

    # 🟠 / 🟡 / ❌ SEO signals.
    if seo_snapshot:
        for r in seo_snapshot.get("rows", []):
            d = (r.get("domain") or "").lower()
            if not d:
                continue
            # Dark sites (robots.txt blocks crawlers, or lamill.toml marks
            # the row dark) are intentionally invisible to Google — none
            # of the SEO-discovery signals below apply. Skip the whole
            # row so we don't list "no sitemap submitted" / "zero
            # impressions" / "sitemap parse errors" against a site that
            # by design isn't in GSC.
            if r.get("robots_intent") == "dark":
                continue
            gsc_status = r.get("gsc_status")
            imp = r.get("gsc_impressions")
            pos = r.get("gsc_position")
            sitemap_count = r.get("gsc_sitemap_count")
            sitemap_errors = r.get("gsc_sitemap_errors")
            sitemap_warnings = r.get("gsc_sitemap_warnings")
            young = (not include_young) and _is_young(d)

            # ❌ Site is in GSC but has zero sitemaps submitted. Structural
            # ops gap — applies regardless of site age (no young-suppress).
            # Fires before the young-suppress short-circuit below.
            if gsc_status == "ok" and sitemap_count == 0:
                _add_signal(d, "❌", _RANK_YELLOW,
                            "GSC: no sitemap submitted",
                            "→ submit at search.google.com/search-console → Sitemaps")

            # 🔴 GSC reported parse errors on a submitted sitemap — "Sitemap
            # could not be read." This is the broken-state signal the dashboard
            # was silently green on before the gsc_sitemap_health wire-up. Ranks
            # red because GSC has the file and is rejecting it — discovery is
            # blocked until it's fixed. Age-independent: a freshly launched
            # site with a broken sitemap is still broken.
            if gsc_status == "ok" and isinstance(sitemap_errors, int) and sitemap_errors > 0:
                _add_signal(
                    d, "🔴", _RANK_RED,
                    f"GSC: sitemap parse errors ({sitemap_errors})",
                    "→ open Search Console → Sitemaps; common causes: stale "
                    "edge cache serving old XML, sitemap URL not in current "
                    "build, malformed XML",
                )
            # 🟡 Warnings on a submitted sitemap — readable but flagged
            # (e.g., URLs outside the property, slow-fetch). Only surface
            # when there are NO errors (the red signal above already covers
            # the louder case).
            elif (gsc_status == "ok"
                  and isinstance(sitemap_warnings, int) and sitemap_warnings > 0):
                _add_signal(
                    d, "🟡", _RANK_YELLOW,
                    f"GSC: sitemap warnings ({sitemap_warnings})",
                    "→ check Search Console → Sitemaps for the specific warning",
                )

            # Indexed but zero impressions — content not surfacing.
            zero_imp_trigger = (gsc_status == "ok" and imp == 0)
            bad_pos_trigger = isinstance(pos, (int, float)) and pos > 20
            if (zero_imp_trigger or bad_pos_trigger) and young:
                suppressed_young.add(d)
                continue
            if zero_imp_trigger:
                _add_signal(d, "🟠", _RANK_ORANGE,
                            "Indexed, zero impressions in 28d",
                            "→ check coverage in GSC + content gap analysis")
            if bad_pos_trigger:
                _add_signal(d, "🟡", _RANK_YELLOW,
                            f"Ranking but buried (pos {pos:.1f})",
                            "→ improve content for the queries you're showing on")

    # 🔴 Stale Cloudflare edge cache on critical paths. Surfaces failing
    # CHECK_057 — the donready failure mode where /sitemap.xml lingers
    # at the edge after a build that no longer produces the file. Fix
    # is tier-1 automated: `portfolio project fix <domain> --apply` purges the stale
    # paths via the CF API. Age-independent: stale critical files block
    # discovery the same way on a 3-day-old site as on a 3-year-old one.
    # Not suppressed on dark sites — cache is a deploy hygiene signal,
    # not a discovery signal.
    for d, failures in domain_check_failures.items():
        if "CHECK_057" not in failures:
            continue
        message = failures.get("CHECK_057") or "stale edge cache on critical path(s)"
        _add_signal(
            d.lower(), "🔴", _RANK_RED,
            f"Stale CF edge cache: {message}",
            f"→ run 'portfolio project fix {d} --apply' (purges via CF API)",
        )

    # 📝 Top open high-priority todo per site (v27.F). Feeds the same
    # _add_signal plumbing as every other signal, so ignored-category
    # gating + dedup-per-domain come for free. Ranks below all live
    # signals — a tracked task is the least-urgent thing on the list.
    for d, task in domain_high_todos.items():
        _add_signal(d.lower(), "📝", _RANK_TODO, "todo", task)

    # Sort by rank desc, then alphabetical.
    out = list(items.values())
    out.sort(key=lambda x: (-x.rank, x.domain))
    # Drop OK rows (no signals) — they're not "to focus on."
    filtered = [item for item in out if item.rank > _RANK_OK]
    if suppressed_young_out is not None:
        suppressed_young_out.extend(sorted(suppressed_young))
    return filtered


def _site_down_action(domain: str, cls: str | None, error: str | None) -> str:
    """Build a contextual action message for a down site.

    For `dead` / `ssl-broken` we used to hardcode "Cloudflare Pages" —
    misleading for Vercel / Netlify / Namecheap-parked domains. Inspect
    the project dir for deploy markers and reference the real platform
    when we can; otherwise keep the message generic.
    """
    platform = _detect_deploy_platform(domain)
    if cls == "dead":
        if platform:
            return f"site is unreachable — check DNS + {platform} deployment"
        return "site is unreachable — check DNS + deploy target"
    if cls == "ssl-broken":
        if platform:
            return f"SSL handshake failed — check certificate / {platform} TLS settings"
        return "SSL handshake failed — check certificate / TLS settings on the origin"
    if cls == "error":
        return error or "fetch errored"
    return "investigate"


def _detect_deploy_platform(domain: str) -> str | None:
    """Return a human-readable platform name for `sites/<domain>/` if a
    deploy-config marker is present. Returns None when no project dir
    exists or no marker is found."""
    try:
        from .project import SITES_ROOT
    except ImportError:
        return None
    project_dir = SITES_ROOT / domain
    if not project_dir.exists():
        return None
    if (project_dir / "wrangler.toml").exists():
        return "Cloudflare Pages"
    if (project_dir / "vercel.json").exists():
        return "Vercel"
    if (project_dir / "netlify.toml").exists():
        return "Netlify"
    return None


def domains_with_expiry_from_portfolio(domains) -> list[tuple[str, int]]:
    """Pull (domain, days_to_expire) from the loaded Domain list."""
    today = date.today()
    out: list[tuple[str, int]] = []
    for d in domains:
        if d.expires is None:
            continue
        out.append((d.name.lower(), (d.expires - today).days))
    return out
