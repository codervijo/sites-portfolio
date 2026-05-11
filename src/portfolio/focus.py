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
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


# Severity rank — higher = surfaces first.
_RANK_RED = 4
_RANK_ORANGE = 3
_RANK_YELLOW = 2
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


def build_focus_list(
    *,
    live_snapshot: dict | None,
    seo_snapshot: dict | None,
    domains_with_expiry: list[tuple[str, int]],
    domain_categories: dict[str, str] | None = None,
) -> list[FocusItem]:
    """Build the ranked focus list from three pre-loaded data sources.

    `live_snapshot` is the parsed JSON of `data/checks/<latest>.json`.
    `seo_snapshot` is the parsed JSON of `data/seo/<latest>.json`.
    `domains_with_expiry` is `[(domain, days_to_expire)]` from
    `portfolio.json`. `domain_categories` maps domain → plan category
    (lowercase keys); domains in `IGNORE_CATEGORIES` are filtered out.
    None / [] for any input means "skip that signal."
    """
    domain_categories = domain_categories or {}
    items: dict[str, FocusItem] = {}

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

    # ⚠️ Expiring within 30 days.
    for d, days in domains_with_expiry:
        if days is None:
            continue
        if days <= 30:
            _add_signal(d, "⚠️", _RANK_RED,
                        f"Expiring in {days} days",
                        "→ renew at registrar before lapse")

    # 🟠 / 🟡 SEO signals.
    if seo_snapshot:
        for r in seo_snapshot.get("rows", []):
            d = (r.get("domain") or "").lower()
            if not d:
                continue
            gsc_status = r.get("gsc_status")
            imp = r.get("gsc_impressions")
            pos = r.get("gsc_position")
            # Indexed but zero impressions — content not surfacing.
            if gsc_status == "ok" and imp == 0:
                _add_signal(d, "🟠", _RANK_ORANGE,
                            "Indexed, zero impressions in 28d",
                            "→ check coverage in GSC + content gap analysis")
            # Bad position — visible but buried.
            if isinstance(pos, (int, float)) and pos > 20:
                _add_signal(d, "🟡", _RANK_YELLOW,
                            f"Ranking but buried (pos {pos:.1f})",
                            "→ improve content for the queries you're showing on")

    # Sort by rank desc, then alphabetical.
    out = list(items.values())
    out.sort(key=lambda x: (-x.rank, x.domain))
    # Drop OK rows (no signals) — they're not "to focus on."
    return [item for item in out if item.rank > _RANK_OK]


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
