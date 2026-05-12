"""Tests for v5.F.1 — `portfolio focus` ranking logic."""
from __future__ import annotations

from portfolio.focus import build_focus_list, _RANK_RED, _RANK_ORANGE, _RANK_YELLOW


def _live_snap(*entries: dict) -> dict:
    """Wrap a list of result entries in the snapshot shape."""
    return {"results": list(entries)}


def _seo_snap(*rows: dict) -> dict:
    return {"rows": list(rows)}


# ---------- single-signal cases ----------


def test_dead_classification_drives_red():
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "broken.com", "variant": "bare", "classification": "dead"}
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].domain == "broken.com"
    assert items[0].rank == _RANK_RED
    assert items[0].signals[0][0] == "🔴"
    assert "dead" in items[0].signals[0][1].lower()


def test_expiring_within_30d_drives_red():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[("expiring.com", 12)],
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_RED
    assert "12" in items[0].signals[0][1]


def test_far_expiry_does_not_trigger():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[("safe.com", 200)],
    )
    assert items == []


def test_zero_impressions_drives_orange():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "no-traffic.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": None},
        ),
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_ORANGE


def test_bad_position_drives_yellow():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "buried.com", "gsc_status": "ok",
             "gsc_impressions": 500, "gsc_position": 35.1},
        ),
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_YELLOW
    assert "35.1" in items[0].signals[0][1]


def test_good_position_does_not_trigger():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "ranking.com", "gsc_status": "ok",
             "gsc_impressions": 1000, "gsc_position": 4.2},
        ),
        domains_with_expiry=[],
    )
    assert items == []


# ---------- ranking + dedup ----------


def test_red_ranks_above_orange_above_yellow():
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "down.com", "variant": "bare", "classification": "dead"}
        ),
        seo_snapshot=_seo_snap(
            {"domain": "buried.com", "gsc_status": "ok",
             "gsc_impressions": 1, "gsc_position": 50.0},
            {"domain": "no-imp.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": None},
        ),
        domains_with_expiry=[],
    )
    domains = [i.domain for i in items]
    assert domains == ["down.com", "no-imp.com", "buried.com"]


def test_multiple_signals_on_same_domain_collapse():
    """A domain that's both expiring AND has zero impressions appears once,
    with both signals listed."""
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "doubled.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": None},
        ),
        domains_with_expiry=[("doubled.com", 5)],
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_RED  # worst signal wins
    assert len(items[0].signals) == 2


def test_both_variants_dead_flags_domain():
    """If every probed variant fails, the domain is genuinely down."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"},
            {"domain": "x.com", "variant": "www", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    # Only one "Site is dead" signal — not two from the two variants.
    assert len(items[0].signals) == 1


def test_one_variant_alive_does_not_flag_site_down():
    """www serving real content rescues a dead bare apex — don't flag.

    Mirrors the real-world linkedcsi.live case: bare timing out while
    www serves a live Astro app. Reporting the domain dead would be
    misleading.
    """
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"},
            {"domain": "x.com", "variant": "www",
             "classification": "live-site", "status": 200},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert items == []


def test_forwarder_variant_alone_does_not_flag():
    """A forwarder counts as reachable for focus purposes — even if
    other variants failed."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "forwarder",
             "status": 200},
            {"domain": "x.com", "variant": "www", "classification": "error"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert items == []


def test_site_down_action_text_is_generic_without_project_dir(monkeypatch):
    """Hardcoded "Cloudflare Pages" was misleading on Vercel /
    Namecheap-parked domains. Generic phrasing for unknown platforms."""
    from portfolio import focus as focus_mod
    monkeypatch.setattr(focus_mod, "_detect_deploy_platform", lambda d: None)
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    action = items[0].signals[0][2]
    assert "Cloudflare" not in action
    assert "deploy target" in action


def test_site_down_action_text_names_detected_platform(monkeypatch):
    """When wrangler.toml / vercel.json / netlify.toml is present,
    name the platform in the action text."""
    from portfolio import focus as focus_mod
    monkeypatch.setattr(focus_mod, "_detect_deploy_platform", lambda d: "Vercel")
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert "Vercel" in items[0].signals[0][2]


def test_ssl_broken_action_text_adapts(monkeypatch):
    from portfolio import focus as focus_mod
    monkeypatch.setattr(focus_mod, "_detect_deploy_platform",
                        lambda d: "Cloudflare Pages")
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "ssl-broken"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert "Cloudflare Pages" in items[0].signals[0][2]
    assert "SSL" in items[0].signals[0][1] or "ssl" in items[0].signals[0][1]


# ---------- empty inputs ----------


def test_empty_inputs_yield_empty_list():
    assert build_focus_list(
        live_snapshot=None, seo_snapshot=None, domains_with_expiry=[]
    ) == []


def test_clean_domains_yield_empty_list():
    """Live is fine, SEO is fine, no expiry concerns → nothing to focus on."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "ok.com", "variant": "bare",
             "classification": "live-site", "status": 200}
        ),
        seo_snapshot=_seo_snap(
            {"domain": "ok.com", "gsc_status": "ok",
             "gsc_impressions": 10000, "gsc_position": 5.0},
        ),
        domains_with_expiry=[("ok.com", 300)],
    )
    assert items == []


# ---------- ignore: domains marked "to be deleted immediately" ----------


def test_ignore_to_be_deleted_immediately():
    """Domains with category 'To be deleted immediately' (case-insensitive)
    should never appear in focus, even if they're dead / expiring."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "junk.com", "variant": "bare", "classification": "dead"},
            {"domain": "real.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[("junk.com", 5), ("real.com", 5)],
        domain_categories={
            "junk.com": "To be deleted immediately",
            "real.com": "My brand",
        },
    )
    assert [i.domain for i in items] == ["real.com"]


def test_ignore_categories_is_case_insensitive():
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "junk.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
        # Mixed casing on purpose.
        domain_categories={"junk.com": "TO BE DELETED IMMEDIATELY"},
    )
    assert items == []


def test_no_categories_falls_through_unchanged():
    """If no domain_categories map is supplied, behavior matches the
    earlier (pre-ignore) build_focus_list."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"}
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].domain == "x.com"


# ---------- age-aware SEO suppression (freshness window) ----------


def test_young_site_seo_signals_suppressed_by_default():
    """🟠 zero-imp + 🟡 bad-position are normal for sites <90d old."""
    suppressed: list[str] = []
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "fresh.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={"fresh.com": 21},  # 3 weeks old
        suppressed_young_out=suppressed,
    )
    assert items == []
    assert suppressed == ["fresh.com"]


def test_include_young_overrides_suppression():
    """--include-young surfaces those signals anyway."""
    suppressed: list[str] = []
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "fresh.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={"fresh.com": 21},
        include_young=True,
        suppressed_young_out=suppressed,
    )
    assert len(items) == 1
    assert items[0].domain == "fresh.com"
    assert suppressed == []   # nothing got suppressed since override is on


def test_old_site_seo_signals_not_suppressed():
    """Sites older than 90d see their SEO signals normally."""
    suppressed: list[str] = []
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "mature.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={"mature.com": 365},
        suppressed_young_out=suppressed,
    )
    assert len(items) == 1
    assert items[0].domain == "mature.com"
    assert suppressed == []


def test_unknown_age_does_not_suppress():
    """Conservative: if we have no age data for a domain, do not suppress.
    Better to over-flag than to silently hide a problem on a domain we
    lack metadata for."""
    suppressed: list[str] = []
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "unknown.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={"unknown.com": None},  # explicit None
        suppressed_young_out=suppressed,
    )
    assert len(items) == 1
    assert suppressed == []

    # Same outcome when the domain key is missing from the map entirely.
    suppressed = []
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "unknown.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={},
        suppressed_young_out=suppressed,
    )
    assert len(items) == 1
    assert suppressed == []


def test_age_suppression_does_not_affect_site_down_or_expiry():
    """🔴 dead/error and ⚠️ expiry are NOT suppressed for young sites —
    broken is broken, expiring is expiring, regardless of age."""
    suppressed: list[str] = []
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "fresh-dead.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=_seo_snap(
            {"domain": "fresh-buried.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 99.0},
        ),
        domains_with_expiry=[("fresh-expiring.com", 5)],
        domain_site_age_days={
            "fresh-dead.com": 10,
            "fresh-buried.com": 10,
            "fresh-expiring.com": 10,
        },
        suppressed_young_out=suppressed,
    )
    domains_flagged = {i.domain for i in items}
    assert "fresh-dead.com" in domains_flagged        # 🔴 always flagged
    assert "fresh-expiring.com" in domains_flagged    # ⚠️ always flagged
    assert "fresh-buried.com" not in domains_flagged  # 🟡 suppressed
    assert suppressed == ["fresh-buried.com"]


def test_suppressed_young_out_optional():
    """Callers that don't care about the suppressed list can omit it."""
    # Should not raise.
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=_seo_snap(
            {"domain": "fresh.com", "gsc_status": "ok",
             "gsc_impressions": 0, "gsc_position": 50.0},
        ),
        domains_with_expiry=[],
        domain_site_age_days={"fresh.com": 10},
    )
    assert items == []


# ---------- 🟡 idle (forwarder / parked) signal ----------


def test_forwarder_flagged_yellow_decision_item():
    """A domain answering 200 but classified as forwarder isn't an
    emergency, but it IS a decision item (build / retire / sell)."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "idle.com", "variant": "bare",
             "classification": "forwarder", "status": 200,
             "final_url": "http://elsewhere.com"},
            {"domain": "idle.com", "variant": "www",
             "classification": "forwarder", "status": 200,
             "final_url": "http://elsewhere.com"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].domain == "idle.com"
    assert items[0].rank == _RANK_YELLOW
    headline = items[0].signals[0][1]
    assert "forwarder" in headline


def test_parked_flagged_yellow():
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "park.com", "variant": "bare",
             "classification": "parked", "status": 200},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_YELLOW
    assert "parked" in items[0].signals[0][1]


def test_mixed_forwarder_and_parked_picks_parked():
    """If a domain has both, the more-inert label (parked) wins."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "mix.com", "variant": "bare",
             "classification": "forwarder", "status": 200},
            {"domain": "mix.com", "variant": "www",
             "classification": "parked", "status": 200},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert "parked" in items[0].signals[0][1]


def test_idle_signal_does_not_fire_when_any_variant_is_live_site():
    """If one variant serves a real site, the domain isn't idle."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare",
             "classification": "forwarder", "status": 200},
            {"domain": "x.com", "variant": "www",
             "classification": "live-site", "status": 200},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert items == []


def test_idle_signal_yields_to_site_down_red():
    """If all variants are dead → 🔴 wins; if mixed dead+forwarder we
    don't flag idle (forwarder rescues the down classification first;
    idle signal only fires when ALL variants are idle)."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "dead.com", "variant": "bare", "classification": "dead"},
            {"domain": "dead.com", "variant": "www", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert items[0].rank == _RANK_RED
    # Only one signal — the red site-down, not a duplicate idle yellow.
    assert len(items[0].signals) == 1
