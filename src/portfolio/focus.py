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
    if live_snapshot:
        # Pick the bare variant when both bare and www exist; only flag if
        # both variants of a domain are bad (dedup by domain).
        seen: dict[str, dict] = {}
        for r in live_snapshot.get("results", []):
            d = r.get("domain", "").lower()
            if not d:
                continue
            if d not in seen or r.get("variant") == "bare":
                seen[d] = r
        for d, r in seen.items():
            cls = r.get("classification")
            status = r.get("status")
            if cls in ("dead", "ssl-broken", "error"):
                action = {
                    "dead": "site is unreachable — check DNS + Cloudflare Pages deployment",
                    "ssl-broken": "SSL handshake failed — check certificate / Cloudflare TLS settings",
                    "error": r.get("error") or "fetch errored",
                }.get(cls, "investigate")
                _add_signal(d, "🔴", _RANK_RED,
                            f"Site is {cls}", f"→ {action}")
            elif isinstance(status, int) and not (200 <= status < 300):
                _add_signal(d, "🔴", _RANK_RED,
                            f"HTTP {status}",
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


def domains_with_expiry_from_portfolio(domains) -> list[tuple[str, int]]:
    """Pull (domain, days_to_expire) from the loaded Domain list."""
    today = date.today()
    out: list[tuple[str, int]] = []
    for d in domains:
        if d.expires is None:
            continue
        out.append((d.name.lower(), (d.expires - today).days))
    return out
