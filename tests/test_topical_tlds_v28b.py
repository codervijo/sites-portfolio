"""v28.B — topical-TLD set + theme map + renewal lookup.

Pins the curated allow-set + theme resolution that the v28.C LLM selector
is constrained to, and the renewal-price lookup that v28 surfaces (the true
keep-forever cost on reg-cheap / renew-expensive topical TLDs).
"""
from __future__ import annotations

from portfolio import availability
from portfolio.suggest import THEME_MAP, TOPICAL_TLDS, topical_tlds_for


# ---- theme map / allow-set ------------------------------------------


def test_allow_set_is_flat_dedup_of_theme_map():
    expected = {t for tlds in THEME_MAP.values() for t in tlds}
    assert set(TOPICAL_TLDS) == expected
    assert ".family" in TOPICAL_TLDS and ".fm" in TOPICAL_TLDS


def test_family_theme_resolves_in_order():
    assert topical_tlds_for(["family"]) == (".family", ".gift", ".photos", ".life")


def test_multiple_themes_dedup_and_keep_order():
    # voice → (.fm); video → (.video, .cam); .fm leads, no dupes
    assert topical_tlds_for(["voice", "video"]) == (".fm", ".video", ".cam")


def test_overlapping_themes_dedup():
    # family + memories share .photos / .life / .gift — each appears once
    out = topical_tlds_for(["family", "memories"])
    assert len(out) == len(set(out))
    assert ".family" in out and ".video" in out  # union across both


def test_unknown_theme_ignored():
    assert topical_tlds_for(["totally-unknown"]) == ()
    assert topical_tlds_for([]) == ()


def test_theme_keys_case_insensitive():
    assert topical_tlds_for(["FAMILY"]) == topical_tlds_for(["family"])


# ---- renewal lookup --------------------------------------------------

_PRICING = {
    "family": {"registration": "5.66", "renewal": "31.41"},
    "fm": {"registration": "87.85", "renewal": "87.85"},
    "com": {"registration": "11.08", "renewal": "11.08"},
}


def test_lookup_renewal_returns_renewal_not_registration():
    assert availability.lookup_renewal("anchorrec.family", _PRICING) == 31.41
    assert availability.lookup_price("anchorrec.family", _PRICING) == 5.66


def test_lookup_renewal_flat_tld():
    assert availability.lookup_renewal("x.fm", _PRICING) == 87.85


def test_lookup_renewal_missing_tld_is_none():
    assert availability.lookup_renewal("x.zzz", _PRICING) is None


def test_lookup_renewal_empty_pricing_is_none():
    assert availability.lookup_renewal("x.family", {}) is None
