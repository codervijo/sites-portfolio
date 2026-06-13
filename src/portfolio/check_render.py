"""v35.F incr 7 — fleet/project check + SEO/status/GSC render cluster,
extracted from cli.py (behavior-preserving, H1).

Pure renderers + their shared formatting leaves (_fmt_* / _color_value /
classification + verdict colour maps / category labels). Self-contained:
depends only on stdlib, rich, typer, the neutral .console, and read helpers
from .check / .data. cli.py re-exports every name so callers + tests using
`from portfolio.cli import X` are unchanged.
"""
from __future__ import annotations

from collections import Counter

import typer
from rich.table import Table

from .check import best_per_domain, load_snapshot, previous_snapshot
from .console import console
from .data import load_domains


CLASSIFICATION_COLORS = {
    "live-site": "green",
    "forwarder": "cyan",
    "for-sale": "yellow",
    "parked": "yellow",
    "error": "red",
    "ssl-broken": "red",
    "dead": "red",
}


def _render_status(snapshot_path) -> None:
    snap = load_snapshot(snapshot_path)
    best = best_per_domain(snap)
    prev_path = previous_snapshot()
    prev_best = best_per_domain(load_snapshot(prev_path)) if (prev_path and prev_path != snapshot_path) else {}

    t = Table(title=f"Site status — {snapshot_path.name} (scope={snap.get('scope', '?')})")
    t.add_column("Domain")
    t.add_column("Var")
    t.add_column("HTTP", justify="right")
    t.add_column("Class")
    t.add_column("Final URL")
    t.add_column("ms", justify="right")
    t.add_column("Δ vs prev")

    for dom in sorted(best):
        r = best[dom]
        c = r["classification"]
        cls_str = f"[{CLASSIFICATION_COLORS.get(c, 'white')}]{c}[/]"
        prev_c = prev_best.get(dom, {}).get("classification")
        if prev_c and prev_c != c:
            delta = f"[bold yellow]{prev_c} → {c}[/]"
        elif prev_c:
            delta = ""
        else:
            delta = "[dim]new[/]" if prev_best else ""
        t.add_row(
            dom,
            r["variant"],
            str(r["status"]) if r["status"] is not None else "-",
            cls_str,
            (r["final_url"] or r.get("error") or "-")[:80],
            f"{r['response_time_ms']}" if r["response_time_ms"] is not None else "-",
            delta,
        )
    console.print(t)

    counts = Counter(r["classification"] for r in best.values())
    summary = "  ".join(f"[{CLASSIFICATION_COLORS.get(k, 'white')}]{k}[/]={v}" for k, v in counts.most_common())
    console.print(f"\nTotals ({len(best)} domains): {summary}")
    if prev_path and prev_path != snapshot_path:
        console.print(f"[dim]Compared against {prev_path.name}[/]")


# Render order for category-grouped output.
_CATEGORY_ORDER = (
    "scaffold", "docs", "git", "ci", "stack", "deploy", "seo", "content",
)


_CATEGORY_LABEL = {
    "scaffold": "Scaffold",
    "docs": "Docs",
    "git": "Git",
    "ci": "CI",
    "stack": "Stack",
    "deploy": "Deploy",
    "seo": "SEO",
    "content": "Content",
}


def _render_summary_table(per_repo: dict[str, dict], catalog_specs: list) -> None:
    total = len(catalog_specs)
    spec_by_id = {s.id: s for s in catalog_specs}

    # Per-repo summary table — fails/warns ordered by category so related
    # gaps cluster visually instead of being interleaved by ID.
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]check --git — {len(per_repo)} repos · {total} checks[/]",
              title_justify="left")
    t.add_column("Repo")
    t.add_column("Score", justify="right")
    t.add_column("Fails")
    t.add_column("Warns")
    # Per-repo (name, passes, fails, warns, skipped_count). Skipped checks
    # are warns whose message contains "skipped" — they don't apply to this
    # project (e.g. astro-version-ok on a Vite project, or no-.git checks
    # on an unversioned dir). They get filtered from the Warns column and
    # excluded from the score denominator so it reflects only applicable
    # checks.
    rows: list[tuple[str, int, list[str], list[str], int]] = []
    for repo_name, results in per_repo.items():
        passed = [cid for cid, r in results.items() if r.status == "pass"]
        fails = _sort_ids_by_category(
            [cid for cid, r in results.items() if r.status == "fail"], spec_by_id)
        all_warns = [cid for cid, r in results.items() if r.status == "warn"]
        skipped = [cid for cid in all_warns
                   if "skipped" in results[cid].message.lower()]
        real_warns = _sort_ids_by_category(
            [cid for cid in all_warns if cid not in set(skipped)], spec_by_id)
        rows.append((repo_name, len(passed), fails, real_warns, len(skipped)))
    rows.sort(key=lambda r: (r[1], r[0]))  # worst score first
    for repo_name, score, fails, warns, skipped_n in rows:
        applicable = total - skipped_n
        score_color = ("red" if score < applicable * 0.5
                       else "yellow" if score < applicable * 0.8
                       else "green")
        score_cell = f"[{score_color}]{score}/{applicable}[/]"
        if skipped_n:
            score_cell += f" [dim]({skipped_n} n/a)[/]"
        t.add_row(
            repo_name,
            score_cell,
            ", ".join(fails) if fails else "[dim]—[/]",
            ", ".join(warns) if warns else "[dim]—[/]",
        )
    console.print(t)
    n_clean = sum(1 for r in rows if not r[2] and not r[3])
    # Average score now reflects applicable checks per repo, not catalog size.
    avg_applicable = (sum(r[1] for r in rows) /
                      sum((total - r[4]) for r in rows)
                      if rows else 0)
    total_skipped = sum(r[4] for r in rows)
    console.print(
        f"\n[dim]Totals: {len(rows)} repos · "
        f"avg {avg_applicable*100:.0f}% pass · "
        f"{n_clean} all-pass · "
        f"{total_skipped} skipped checks fleetwide (non-applicable)[/]"
    )

    # Aggregate "most common failures" view across all repos. Surfaces the
    # patterns worth fixing fleetwide rather than per-repo.
    _render_common_failures(per_repo, spec_by_id, n_repos=len(rows))


def _sort_ids_by_category(ids: list[str], spec_by_id: dict) -> list[str]:
    """Order check IDs by (category render order, then ID) so the rendered
    fails/warns column reads as Scaffold → Docs → Git → CI → Stack → Deploy."""
    cat_index = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    def key(cid: str):
        spec = spec_by_id.get(cid)
        cat = spec.category if spec else ""
        return (cat_index.get(cat, len(_CATEGORY_ORDER)), cid)
    return sorted(ids, key=key)


def _render_common_failures(per_repo: dict[str, dict],
                            spec_by_id: dict,
                            *, n_repos: int,
                            top_n: int = 10) -> None:
    """Print "Most common failures across N repos" — top check IDs by repo
    count, where a repo "has" a failure if status is fail or warn (skips
    don't count). Grouped by category in render order."""
    if n_repos == 0:
        return
    counts: dict[str, int] = {}
    for results in per_repo.values():
        for cid, r in results.items():
            if r.status in ("fail", "warn") and "skipped" not in r.message:
                counts[cid] = counts.get(cid, 0) + 1
    if not counts:
        return
    # Filter to checks that hit ≥ 30% of repos to keep signal-noise high.
    threshold = max(2, int(n_repos * 0.3))
    common = [(cid, n) for cid, n in counts.items() if n >= threshold]
    if not common:
        return
    cat_index = {c: i for i, c in enumerate(_CATEGORY_ORDER)}
    common.sort(key=lambda t: (
        cat_index.get(spec_by_id.get(t[0]).category if t[0] in spec_by_id else "",
                      len(_CATEGORY_ORDER)),
        -t[1],
        t[0],
    ))
    common = common[:top_n]
    console.print(f"\n[bold]Most common failures across {n_repos} repos:[/]")
    last_cat = None
    for cid, n in common:
        spec = spec_by_id.get(cid)
        cat = spec.category if spec else "?"
        if cat != last_cat:
            console.print(f"  [bold cyan]{_CATEGORY_LABEL.get(cat, cat)}[/]")
            last_cat = cat
        name = spec.name if spec else "?"
        console.print(f"    {cid}  {name:<30}  [yellow]{n}/{n_repos}[/] repos")


def _render_per_repo_detail(repo_name: str, results: dict, catalog_specs: list) -> None:
    spec_by_id = {s.id: s for s in catalog_specs}
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]{repo_name}[/]",
              title_justify="left")
    t.add_column("ID")
    t.add_column("Status")
    t.add_column("Name")
    t.add_column("Message")
    for cid in _sort_ids_by_category(list(results), spec_by_id):
        r = results[cid]
        spec = spec_by_id.get(cid)
        # Skipped (warn whose message says "skipped") gets a softer icon
        # so the reader can tell at a glance "this didn't apply" vs
        # "this is an actionable warn."
        is_skipped = (r.status == "warn" and "skipped" in r.message.lower())
        if is_skipped:
            icon = "[dim]· n/a[/]"
        else:
            icon = {"pass": "[green]✓ pass[/]", "fail": "[red]✗ fail[/]",
                    "warn": "[yellow]~ warn[/]"}.get(r.status, r.status)
        t.add_row(cid, icon, spec.name if spec else "?", r.message)
    console.print(t)
    n_pass = sum(1 for r in results.values() if r.status == "pass")
    n_fail = sum(1 for r in results.values() if r.status == "fail")
    warns = [r for r in results.values() if r.status == "warn"]
    n_skipped = sum(1 for r in warns if "skipped" in r.message.lower())
    n_warn = len(warns) - n_skipped
    console.print(
        f"  [dim]{n_pass} pass · {n_fail} fail · {n_warn} warn · "
        f"{n_skipped} n/a[/]"
    )
    _render_action_plan(repo_name, results)


# v6.D.1 — manual-fix hints for checks without a registered fixer.
# Keyed by CHECK_ID. For checks not in this dict, we fall back to the
# check's `message` field as the hint (still useful, just less polished).
_MANUAL_HINTS = {
    "CHECK_010": "mkdir tests/ and add at least one .test.{js,ts,py}",
    "CHECK_022": "git status; commit or stash uncommitted changes",
    "CHECK_024": "add .github/workflows/ci.yml — copy from a bootstrapped project",
    "CHECK_029": 'add `"homepage": "https://<domain>/"` to package.json',
    "CHECK_035": "pnpm update vite@^6 && pnpm run build  (verify nothing breaks)",
    "CHECK_036": "pnpm update astro@^5",
    "CHECK_039": "tsc --init  (only if you want TypeScript)",
    "CHECK_071": "edit <head> meta description — keep it 120-160 chars",
    "CHECK_073": 'add <meta name="viewport" content="width=device-width, initial-scale=1">',
    "CHECK_074": 'add lang="en" (or appropriate code) to <html>',
    "CHECK_075": 'add <meta name="robots" content="index, follow">',
    "CHECK_076": "add the 5 og:* meta tags (title, description, url, type, image)",
    "CHECK_077": 'add <meta name="twitter:card" content="summary_large_image">',
    "CHECK_078": 'add <script type="application/ld+json"> with WebSite + Organization',
    "CHECK_079": "JSON-LD must include @type Organization or WebSite",
    "CHECK_080": "wire analytics (GA4 / Plausible / CF Web Analytics)",
    "CHECK_148": "fix GA4 measurement ID (must match `G-[A-Z0-9]{6,12}`)",
    "CHECK_149": 'add `<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXX">` loader before the inline gtag() calls',
    "CHECK_141": "git submodule deinit + rm -rf the gitlink (CF Pages won't clone)",
}


def _render_action_plan(repo_name: str, results: dict) -> None:
    """Print suggested fix commands per non-passing check.
    Categorizes into Tier 1 (templated), Tier 2 (--ai), manual,
    and design-skip. Manual hints come from `_MANUAL_HINTS` or fall
    back to the check's own message text.
    """
    from .fix_registry import fixable_check_ids

    tier_1 = fixable_check_ids(tier=1)
    tier_2 = fixable_check_ids(tier=2)

    actionable_t1: list[str] = []
    actionable_t2_only: list[str] = []
    manual: list[tuple[str, str]] = []
    design_skipped: list[str] = []

    for cid, r in results.items():
        if r.status == "pass":
            continue
        # Skip-by-design (auto-skipped by stack-aware checks). Identified
        # by "skipped" in the message text.
        if r.status == "warn" and "skipped" in r.message.lower():
            design_skipped.append(cid)
            continue
        if cid in tier_1:
            actionable_t1.append(cid)
        elif cid in tier_2:
            actionable_t2_only.append(cid)
        else:
            manual.append((cid, r.message))

    if not (actionable_t1 or actionable_t2_only or manual):
        return  # nothing to suggest

    console.print()
    console.print("[bold]Suggested fixes:[/]")

    if actionable_t1:
        console.print()
        console.print(f"  [cyan]• Tier 1[/] [dim](templated; ~5s):[/]")
        console.print(f"    [bold]portfolio project fix {repo_name} --apply --yes[/]")
        console.print(
            f"    [dim]Closes: {', '.join(sorted(actionable_t1))}[/]"
        )

    # Tier 2 fixers may share check IDs with Tier 1 (e.g. CHECK_026/027).
    # Only mention "Tier 2 only" for IDs WITHOUT a Tier 1 fixer.
    # Plus, mention --ai upgrades for the dual-tier ones.
    dual_tier = [c for c in actionable_t1 if c in tier_2]
    if actionable_t2_only or dual_tier:
        console.print()
        console.print(f"  [magenta]• Tier 2[/] [dim](Claude --ai; ~$0.05–0.10 per check):[/]")
        console.print(f"    [bold]portfolio project fix {repo_name} --apply --yes --ai[/]")
        if actionable_t2_only:
            console.print(
                f"    [dim]Closes (Tier 2 only): {', '.join(sorted(actionable_t2_only))}[/]"
            )
        if dual_tier:
            console.print(
                f"    [dim]Upgrades content (after Tier 1): {', '.join(sorted(dual_tier))}[/]"
            )

    if manual:
        console.print()
        console.print(f"  [yellow]• Manual ({len(manual)})[/] [dim](no auto-fix):[/]")
        for cid, msg in sorted(manual):
            hint = _MANUAL_HINTS.get(cid, msg)
            console.print(f"    [yellow]{cid}[/]  [dim]{hint}[/]")

    if design_skipped:
        console.print()
        console.print(
            f"  [dim]• Skipped ({len(design_skipped)}): "
            f"{', '.join(sorted(design_skipped))}  — design intent (no action)[/]"
        )


def _render_single_check_table(check_id: str, per_repo: dict, spec) -> None:
    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]{check_id} — {spec.name}[/]",
              title_justify="left")
    t.add_column("Repo")
    t.add_column("Status")
    t.add_column("Message")
    rows = []
    for repo_name, results in per_repo.items():
        r = results.get(check_id)
        if r is None:
            continue
        rows.append((repo_name, r))
    # Sort: fails first, then warns, then passes
    order = {"fail": 0, "warn": 1, "pass": 2}
    rows.sort(key=lambda x: (order.get(x[1].status, 99), x[0]))
    for repo_name, r in rows:
        icon = {"pass": "[green]✓ pass[/]", "fail": "[red]✗ fail[/]",
                "warn": "[yellow]~ warn[/]"}.get(r.status, r.status)
        t.add_row(repo_name, icon, r.message)
    console.print(t)
    n_pass = sum(1 for _, r in rows if r.status == "pass")
    n_fail = sum(1 for _, r in rows if r.status == "fail")
    n_warn = sum(1 for _, r in rows if r.status == "warn")
    console.print(f"\n[dim]{n_pass} pass · {n_fail} fail · {n_warn} warn  "
                  f"({spec.severity} severity)[/]")


_EMOJI_TO_RICH_COLOR = {
    "🟢": "green",
    "🟡": "yellow",
    "🟠": "orange3",
    "🔴": "red",
    "⚪": "dim",
}


def _color_value(emoji: str, text: str) -> str:
    """Wrap `text` in a Rich color tag derived from a status emoji.
    Lets us put the color *into* the cell value (so right-justified
    numeric columns stay aligned) instead of prepending an emoji that
    eats horizontal space and breaks justification."""
    color = _EMOJI_TO_RICH_COLOR.get(emoji, "default")
    if color == "default":
        return text
    return f"[{color}]{text}[/]"


def _fmt_int(n: int | None) -> str:
    return f"{n:,}" if isinstance(n, int) else "—"


def _fmt_pct(v: float | None, *, impressions: int | None) -> str:
    """CTR is meaningless when there are no impressions — show `—`, not `0.0%`."""
    if not isinstance(v, float):
        return "—"
    if not impressions:
        return "—"
    return f"{v * 100:.1f}%"


def _fmt_pos(v: float | None) -> str:
    return f"{v:.1f}" if isinstance(v, float) else "—"


def _fmt_ms(v: float | None) -> str:
    if v is None:
        return "—"
    if v >= 1000:
        return f"{v / 1000:.2f}s"
    return f"{int(v)}ms"


def _fmt_cls(v: float | None) -> str:
    return f"{v:.2f}" if isinstance(v, float) else "—"


def _fmt_compact_int(n: float) -> str:
    """Compact magnitude for Δ cells: 79 → `79`, 8000 → `8.0k`, 2.1e6 → `2.1M`."""
    n = abs(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{int(round(n))}"


def _fmt_delta_part(delta: float | None, flat: bool, *, kind: str) -> str:
    """One sub-value of a Δ cell. `+`/▲/green == improvement for either
    metric (the sign is already normalized so positive == better)."""
    if delta is None:
        return "[dim]—[/]"
    if flat:
        return "[dim]=[/]"
    up = delta > 0
    arrow = "▲" if up else "▼"
    color = "green" if up else "red"
    sign = "+" if up else "-"
    body = f"{abs(delta):.1f}" if kind == "pos" else _fmt_compact_int(delta)
    return f"[{color}]{arrow}{sign}{body}[/]"


def _fmt_delta_metric(delta, *, kind: str) -> str:
    """One metric's Δ for the split ΔImp / ΔPos columns (each sits right
    beside its value). New domains show `· new`; flat shows `=`; a missing
    value shows `—`; empty when Δ wasn't requested for the row."""
    if delta is None:
        return ""
    if delta.is_new:
        return "[dim]· new[/]"
    if kind == "pos":
        return _fmt_delta_part(delta.pos_delta, delta.pos_flat, kind="pos")
    return _fmt_delta_part(delta.imp_delta, delta.imp_flat, kind="imp")


def _render_seo_table(rows: list, *, days: int, sort_by: str,
                      deltas: dict | None = None,
                      delta_meta=None) -> None:
    from .dashboard import _site_age_days
    from .data import load_domains
    from .seo_runtime import gsc_sitemap_cell, overall_status, row_statuses

    # P4 — build domain → site_age_days map for age-aware grading.
    # `overall_status` masks imp + pos cells for sites <90d old so the
    # grade reflects structural SEO (robots / sitemap / GSC presence),
    # not "no traffic yet" on a freshly-launched site.
    age_by_domain: dict[str, int | None] = {}
    try:
        for d in load_domains():
            age_by_domain[d.name.lower()] = _site_age_days(d.name, d.launched)
    except Exception:
        # If portfolio.json can't load (e.g., test environments), fall
        # back to no-mask behavior — matches pre-P4 grading.
        pass

    # Hide CrUX columns when nobody has CrUX data — saves three columns
    # of "⚪ —" noise. We still surface a one-line footer hint so the
    # user knows why those columns are gone.
    crux_uniformly_empty = bool(rows) and all(
        r.crux_status in ("no-key", "no-data", "unknown") for r in rows
    )

    t = Table(box=None, padding=(0, 1), show_header=True,
              title=f"[bold]check --seo · {len(rows)} domains · GSC {days}d · sort={sort_by}[/]",
              title_justify="left")
    t.add_column("SEO")
    t.add_column("Domain")
    t.add_column("HTTP")
    t.add_column("Robots", justify="center")
    t.add_column("Sitemap", justify="center")
    t.add_column("GSC", justify="center")
    # GSC sitemap cell — merges presence (submitted or not) with per-sitemap
    # processing health (errors / warnings from GSC's Sitemaps API). 🔴 = GSC
    # reported errors on a submitted sitemap ("Sitemap could not be read"),
    # 🟡 = warnings, 🟢 = submitted and clean, ❌ = none submitted, ⚪ = no data.
    t.add_column("GSC sm", justify="center")
    # v40 — Δ vs an earlier snapshot, each metric's delta sitting right
    # beside its value (Imp│ΔImp … Pos│ΔPos). Only present when the caller
    # paired a baseline; sort + the value columns are untouched.
    show_delta = deltas is not None
    t.add_column("Imp", justify="right")
    if show_delta:
        t.add_column("ΔImp", justify="right")
    t.add_column("Clicks", justify="right")
    t.add_column("CTR", justify="right")
    t.add_column("Pos", justify="right")
    if show_delta:
        t.add_column("ΔPos", justify="right")
    if not crux_uniformly_empty:
        t.add_column("LCP", justify="right")
        t.add_column("INP", justify="right")
        t.add_column("CLS", justify="right")

    for row in rows:
        s = row_statuses(row)
        http_cell = f"{s['http']} {row.http_status}" if row.http_status is not None else f"{s['http']} err"
        site_age = age_by_domain.get(row.domain.lower())
        d = deltas.get(row.domain.lower()) if show_delta else None
        cells = [
            overall_status(row, site_age_days=site_age),
            row.domain,
            http_cell,
            s["robots"],
            s["sitemap"],
            s["gsc"],
            gsc_sitemap_cell(row),
        ]
        cells.append(_color_value(s["imp"], _fmt_int(row.gsc_impressions)))
        if show_delta:
            cells.append(_fmt_delta_metric(d, kind="imp"))
        cells.append(_fmt_int(row.gsc_clicks))
        cells.append(_fmt_pct(row.gsc_ctr, impressions=row.gsc_impressions))
        cells.append(_color_value(s["pos"], _fmt_pos(row.gsc_position)))
        if show_delta:
            cells.append(_fmt_delta_metric(d, kind="pos"))
        if not crux_uniformly_empty:
            cells.extend([
                _color_value(s["lcp"], _fmt_ms(row.crux_lcp_p75)),
                _color_value(s["inp"], _fmt_ms(row.crux_inp_p75)),
                _color_value(s["cls"], _fmt_cls(row.crux_cls_p75)),
            ])
        t.add_row(*cells)
    console.print(t)

    # v40 — name the Δ baseline + the lookback actually used (gap can be
    # smaller than requested when history doesn't reach back N days yet).
    if show_delta and delta_meta is not None:
        if delta_meta.exact:
            console.print(
                f"\n[dim]Δ vs {delta_meta.snapshot_date} "
                f"({delta_meta.since_days}d).[/]"
            )
        else:
            console.print(
                f"\n[dim]Δ vs {delta_meta.snapshot_date} "
                f"({delta_meta.since_days}d requested, {delta_meta.gap_days}d "
                f"actual — closest earlier snapshot).[/]"
            )
    elif show_delta:
        console.print(
            "\n[dim]Δ unavailable — no earlier snapshot on disk to diff "
            "against (need a second dated run).[/]"
        )

    # Footer counts: how many domains hit each tier of overall status.
    from collections import Counter
    counts = Counter(
        overall_status(r, site_age_days=age_by_domain.get(r.domain.lower()))
        for r in rows
    )
    summary_parts = []
    for emoji, label in (("🟢", "green"), ("🟡", "yellow"),
                         ("🟠", "orange"), ("🔴", "red"), ("⚪", "—")):
        if counts.get(emoji):
            summary_parts.append(f"{emoji} {counts[emoji]} {label}")
    if summary_parts:
        console.print("\n[dim]" + " · ".join(summary_parts) + "[/]")

    # Call out sites that are in GSC but have no sitemap submitted —
    # easy fix, but invisible without this surface.
    missing_sm = [r.domain for r in rows
                  if r.gsc_status == "ok"
                  and r.gsc_sitemap_count == 0]
    if missing_sm:
        sample = ", ".join(missing_sm[:3])
        more = f" + {len(missing_sm) - 3} more" if len(missing_sm) > 3 else ""
        console.print(
            f"[dim]❌ {len(missing_sm)} site(s) in GSC with no sitemap submitted "
            f"({sample}{more}) — submit at search.google.com/search-console "
            f"→ Sitemaps.[/]"
        )

    # Call out sites where GSC reported errors on a SUBMITTED sitemap —
    # "Sitemap could not be read" lives here. Different fix from missing
    # submission: the sitemap exists in GSC but Google can't process it.
    broken_sm = [r for r in rows
                 if r.gsc_status == "ok"
                 and (r.gsc_sitemap_errors or 0) > 0]
    if broken_sm:
        sample = ", ".join(r.domain for r in broken_sm[:3])
        more = f" + {len(broken_sm) - 3} more" if len(broken_sm) > 3 else ""
        console.print(
            f"[dim]🔴 {len(broken_sm)} site(s) with sitemap errors in GSC "
            f"({sample}{more}) — open Search Console → Sitemaps and "
            f"inspect the failing entry; common causes: stale edge cache, "
            f"sitemap URL not in current build, malformed XML.[/]"
        )

    # P4 — note when young sites had imp/pos masked so the reader knows
    # the grade is age-aware (otherwise a 🟡 row with imp=0 looks wrong).
    young = [r.domain for r in rows
             if (age_by_domain.get(r.domain.lower()) is not None
                 and age_by_domain[r.domain.lower()] < 90)]
    if young:
        sample = ", ".join(young[:3])
        more = f" + {len(young) - 3} more" if len(young) > 3 else ""
        console.print(
            f"[dim]🌱 {len(young)} young site(s) <90d ({sample}{more}) — "
            f"imp + pos masked from grade (freshness window).[/]"
        )

    # Surface GSC + CrUX status when most rows are missing data.
    n = len(rows)
    if n:
        gsc_skipped = sum(1 for r in rows if r.gsc_status == "auth-skipped")
        if gsc_skipped == n:
            console.print("[dim]GSC: not authenticated — run `portfolio gsc auth` to enable GSC columns.[/]")
        if crux_uniformly_empty:
            crux_no_key = sum(1 for r in rows if r.crux_status == "no-key")
            crux_no_data = sum(1 for r in rows if r.crux_status == "no-data")
            if crux_no_key == n:
                console.print("[dim]CrUX columns hidden: CRUX_API_KEY missing — see portfolio.env.[/]")
            elif crux_no_data >= n - 1:  # tolerate a single error
                console.print(
                    "[dim]CrUX columns hidden: API key works, but Google has no field data "
                    "for these origins.\n"
                    "       CrUX only publishes p75 metrics for origins above a Chrome-traffic "
                    "threshold (~10k+ monthly visits with\n"
                    "       metrics-reporting enabled). Personal-portfolio-scale sites typically "
                    "fall below it.[/]"
                )
            else:
                console.print(
                    "[dim]CrUX columns hidden: mixed errors. Verify CRUX_API_KEY has the Chrome "
                    "UX Report API enabled at\n"
                    "       https://console.cloud.google.com/apis/library/chromeuxreport.googleapis.com[/]"
                )


def _render_gsc_snapshot(snapshot: dict) -> None:
    period = snapshot["period"]
    t = Table(title=f"GSC totals — {period['start']} → {period['end']}")
    t.add_column("Domain")
    t.add_column("Clicks", justify="right")
    t.add_column("Impressions", justify="right")
    t.add_column("CTR", justify="right")
    t.add_column("Position", justify="right")
    t.add_column("Notes")

    ok_rows = [r for r in snapshot["results"] if r.get("status") == "ok"]
    ok_rows.sort(key=lambda r: r["clicks"], reverse=True)

    for r in ok_rows:
        notes = ""
        if len(r.get("properties", [])) > 1:
            notes = f"[dim]merged {len(r['properties'])} properties[/]"
        ctr = f"{r['ctr'] * 100:.2f}%" if r["impressions"] else "-"
        pos = f"{r['position']:.1f}" if r.get("position") is not None else "-"
        t.add_row(
            r["domain"],
            f"{r['clicks']:,}",
            f"{r['impressions']:,}",
            ctr,
            pos,
            notes,
        )
    console.print(t)

    not_in_gsc = [r["domain"] for r in snapshot["results"] if r.get("status") == "not-in-gsc"]
    if not_in_gsc:
        console.print(f"\n[yellow]Skipped — not verified in GSC ({len(not_in_gsc)}):[/]")
        for d in sorted(not_in_gsc):
            console.print(f"  • {d}")

    total_clicks = sum(r.get("clicks", 0) for r in ok_rows)
    total_imp = sum(r.get("impressions", 0) for r in ok_rows)
    console.print(
        f"\n[bold]Portfolio total:[/] {total_clicks:,} clicks  /  {total_imp:,} impressions  "
        f"(across {len(ok_rows)} domains)"
    )


VERDICT_COLORS = {
    "Misconfigured": "red",
    "Active": "green",
    "Quiet": "yellow",
    "Stalled": "yellow",
    "Dormant": "red",
    "Fresh": "cyan",
}


LIVE_CLS_COLORS = {
    "live-site": "green",
    "forwarder": "cyan",
    "for-sale": "yellow",
    "parked": "yellow",
    "ssl-broken": "red",
    "dead": "red",
    "error": "red",
}


def _render_project_status(result: dict) -> None:
    if result.get("error") == "not-found":
        console.print(f"[red]No project matches '{result['input']}' in plan.md.[/]")
        raise typer.Exit(1)
    if result.get("error") == "ambiguous":
        console.print(f"[yellow]'{result['input']}' is ambiguous. Candidates:[/]")
        for c in result["candidates"]:
            console.print(f"  • {c}")
        raise typer.Exit(2)

    console.print(f"[bold]{result['resolved']}[/]  [dim](resolved from '{result['input']}')[/]")
    verdict = result["verdict"]
    color = VERDICT_COLORS.get(verdict, "white")
    console.print(f"Verdict: [{color}]{verdict}[/]")
    console.print(f"Plan:    {result.get('plan_category') or '[dim](no plan category)[/]'}")
    console.print(f"Dir:     {result['dir']}{'' if result['dir_exists'] else ' [red](missing)[/]'}")

    g = result["git"]
    t = Table(title="Git", show_header=False, box=None, padding=(0, 1))
    t.add_column("Field")
    t.add_column("Value")
    if g["own_repo_pass"]:
        t.add_row("Repo", "[green]own .git[/]")
        if g["branch"]:
            if g["clean"]:
                clean_str = "[green]clean[/]"
            else:
                clean_str = f"[yellow]{g['modified_count']} modified, {g['untracked_count']} untracked[/]"
            t.add_row("Branch", f"{g['branch']} ({clean_str})")
        last = g["last_commit"]
        if last:
            t.add_row(
                "Last commit",
                f'{last["short_sha"]} "{last["subject"]}" — {last["age_days"]}d ago, by {last["author"]}',
            )
        else:
            t.add_row("Last commit", "[yellow](no commits yet)[/]")
        if g["total_commits"] is not None:
            t.add_row(
                "Activity",
                f"{g['commits_7d']} in 7d · {g['commits_30d']} in 30d · {g['total_commits']} total",
            )
    else:
        failed = result["conformance"]["failed"]
        own = next((f for f in failed if f["rule"] == "CHECK_020"), {})
        reason = own.get("reason", "?")
        t.add_row("Repo", f"[red]{reason}[/]")
    console.print(t)

    p = result["prompts_md"]
    if p["exists"] and p["last_entry"]:
        le = p["last_entry"]
        title = f' — {le["title"]}' if le["title"] else ""
        warn = f" [yellow]({p['format_warning']})[/]" if p.get("format_warning") else ""
        console.print(f"\n[bold]Last AI prompt:[/]  {le['date']}{title}{warn}")
        console.print(f"  [dim]{le['summary']}[/]")
    elif p["exists"]:
        console.print("\n[bold]Last AI prompt:[/] [yellow](Prompts.md exists but is empty)[/]")
    else:
        console.print("\n[bold]Last AI prompt:[/] [dim]docs/Prompts.md not found[/]")

    d = result["deployment"]
    plat = d["platform"]
    plat_color = "green" if plat not in ("unknown", "n/a") else ("dim" if plat == "n/a" else "yellow")
    plat_extra = f" ({d['kind']})" if plat == "n/a" else ""
    plat_evidence = f"  [dim]via: {', '.join(d['evidence'])}[/]" if d["evidence"] else ""
    console.print(f"\n[bold]Deployment:[/]  [{plat_color}]{plat}[/]{plat_extra}{plat_evidence}")

    live = d.get("live")
    if live:
        cls = live["classification"]
        cls_color = LIVE_CLS_COLORS.get(cls, "white")
        ms = f", {live['response_time_ms']}ms" if live.get("response_time_ms") is not None else ""
        url = f"  → {live['final_url']}" if live.get("final_url") else ""
        http_status = live.get("http_status")
        console.print(
            f"  Live: [{cls_color}]{cls}[/] (HTTP {http_status if http_status is not None else '?'}{ms}){url}  [dim]{live['snapshot']}[/]"
        )
    elif plat != "n/a":
        console.print("  [dim]Live: no check snapshot covers this domain yet[/]")

    conf = result["conformance"]
    if conf["failed"]:
        console.print(f"\n[red]Conformance failures ({len(conf['failed'])}):[/]")
        for f in conf["failed"]:
            rule = f["rule"]
            name = f.get("name")
            label = f"[bold]{rule}[/] {name}" if name else f"[bold]{rule}[/]"
            console.print(f"  ✗ {label} — {f.get('reason', '?')}")
            if f.get("fix"):
                console.print(f"    [dim]fix: {f['fix']}[/]")
    if conf["passed"]:
        console.print(
            f"[green]Passed ({len(conf['passed'])}):[/] [dim]"
            + ", ".join(conf["passed"])
            + "[/]"
        )
    if conf["skipped"]:
        console.print(
            f"[dim]Skipped ({len(conf['skipped'])}): "
            + ", ".join(s["rule"] for s in conf["skipped"])
            + "[/]"
        )
