"""Tests for v27.F — the 📝 todo focus signal.

Two layers, matching focus.py's pure/IO split:

- `build_focus_list` is driven directly with a `domain_high_todos` dict
  (no disk, no network) to pin the ranking behavior.
- The IO sweep that `focus()` performs is exercised against temp repo
  dirs via `build_project_todos` to pin the priority gate (high only)
  and the additive-optional / malformed-file invariants.
"""

from __future__ import annotations

from portfolio.focus import (
    _RANK_OK,
    _RANK_ORANGE,
    _RANK_RED,
    _RANK_TODO,
    _RANK_YELLOW,
    build_focus_list,
)


def _live_snap(*entries: dict) -> dict:
    return {"results": list(entries)}


# ---------- pure ranking (build_focus_list) ----------


def test_high_todo_produces_todo_signal():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[],
        domain_high_todos={"a.com": "wire up the contact form"},
    )
    assert len(items) == 1
    assert items[0].domain == "a.com"
    assert items[0].rank == _RANK_TODO
    emoji, headline, action = items[0].signals[0]
    assert emoji == "📝"
    assert headline == "todo"
    assert action == "wire up the contact form"


def test_no_high_todos_yields_nothing():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[],
        domain_high_todos={},
    )
    assert items == []


def test_todo_signal_ranks_below_down_same_site():
    """A 🔴 down site with a high todo surfaces once; down drives rank."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "a.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
        domain_high_todos={"a.com": "ship the blog"},
    )
    assert len(items) == 1
    assert items[0].rank == _RANK_RED
    # Worst signal leads; the todo still rides along but doesn't win.
    assert items[0].signals[0][0] == "🔴"
    glyphs = [s[0] for s in items[0].signals]
    assert "📝" in glyphs


def test_todo_signal_ranks_below_expiring_same_site():
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[("a.com", 7)],
        domain_high_todos={"a.com": "ship the blog"},
    )
    assert len(items) == 1
    # ⚠️ expiry maps to _RANK_RED in focus.py; todo must not change that.
    assert items[0].rank == _RANK_RED
    assert items[0].signals[0][0] == "⚠️"
    glyphs = [s[0] for s in items[0].signals]
    assert "📝" in glyphs


def test_todo_sorts_between_live_and_clean():
    """rank order: down (4) > seo-yellow (2) > todo (1)."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "down.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot={"rows": [
            {"domain": "buried.com", "gsc_status": "ok",
             "gsc_impressions": 5, "gsc_position": 40.0},
        ]},
        domains_with_expiry=[],
        domain_high_todos={"todo.com": "do the thing"},
    )
    ranks = [(it.domain, it.rank) for it in items]
    assert ranks == [
        ("down.com", _RANK_RED),
        ("buried.com", _RANK_YELLOW),
        ("todo.com", _RANK_TODO),
    ]


def test_ignored_category_gets_no_todo_signal():
    """A to-be-deleted site contributes no todo signal (gated centrally)."""
    items = build_focus_list(
        live_snapshot=None,
        seo_snapshot=None,
        domains_with_expiry=[],
        domain_high_todos={"junk.com": "do the thing"},
        domain_categories={"junk.com": "To be deleted immediately"},
    )
    assert items == []


def test_todo_signal_omitted_by_default_keeps_existing_callers_unchanged():
    """build_focus_list with no domain_high_todos behaves as before."""
    items = build_focus_list(
        live_snapshot=_live_snap(
            {"domain": "x.com", "variant": "bare", "classification": "dead"},
        ),
        seo_snapshot=None,
        domains_with_expiry=[],
    )
    assert len(items) == 1
    glyphs = [s[0] for s in items[0].signals]
    assert "📝" not in glyphs


# ---------- IO sweep (the gathering focus() does) ----------
#
# focus() scans list_site_dirs() and picks each site's top open high todo
# via build_project_todos. These tests pin that gathering's behavior
# directly against temp repo dirs.

from portfolio.lamill_toml import ParseError
from portfolio.todos import build_project_todos


def _write(tmp_path, name, body):
    site = tmp_path / name
    site.mkdir()
    if body is not None:
        (site / "lamill.toml").write_text(body, encoding="utf-8")
    return site


def _high_todo(site_dir):
    """Mirror focus()'s gathering: top open high todo task, or None."""
    pt = build_project_todos(site_dir, domain=site_dir.name)
    high = next((t for t in pt.open_items if t.priority == "high"), None)
    return high.task if high is not None else None


_DEPLOY = '[deploy]\nplatform = "cf-pages"\n'


def test_only_high_open_todo_surfaces(tmp_path):
    site = _write(
        tmp_path,
        "a.com",
        _DEPLOY + """
[[todo]]
status = "open"
priority = "medium"
task = "medium thing"

[[todo]]
status = "open"
priority = "low"
task = "low thing"

[[todo]]
status = "done"
task = "done thing"

[[todo]]
status = "open"
priority = "high"
task = "the real one"
""",
    )
    assert _high_todo(site) == "the real one"


def test_medium_low_done_only_yields_nothing(tmp_path):
    site = _write(
        tmp_path,
        "a.com",
        _DEPLOY + """
[[todo]]
status = "open"
priority = "medium"
task = "medium thing"

[[todo]]
status = "done"
task = "done thing"
""",
    )
    assert _high_todo(site) is None


def test_no_lamill_toml_yields_nothing(tmp_path):
    site = _write(tmp_path, "a.com", None)
    assert _high_todo(site) is None


def test_bare_deploy_only_file_yields_nothing(tmp_path):
    site = _write(tmp_path, "a.com", _DEPLOY)
    assert _high_todo(site) is None


def test_malformed_toml_is_skipped_not_fatal(tmp_path):
    good = _write(
        tmp_path,
        "good.com",
        _DEPLOY + """
[[todo]]
status = "open"
priority = "high"
task = "real task"
""",
    )
    bad = _write(tmp_path, "bad.com", "this is = = not valid toml [[[")

    # The malformed file raises ParseError on its own...
    raised = False
    try:
        build_project_todos(bad, domain=bad.name)
    except ParseError:
        raised = True
    assert raised

    # ...but focus()'s sweep guards each site, so good ones still land.
    gathered: dict[str, str] = {}
    for site in (bad, good):
        try:
            task = _high_todo(site)
        except ParseError:
            continue
        if task is not None:
            gathered[site.name.lower()] = task
    assert gathered == {"good.com": "real task"}


def test_auto_renew_off_mutes_all_focus_signals():
    """A domain with auto_renew=off (operator letting it lapse) is muted
    from focus entirely — even a hard expiring-soon signal. Registrar truth
    suppresses without a plan.md edit."""
    base = dict(live_snapshot=None, seo_snapshot=None,
                domains_with_expiry=[("dying.com", 10)])
    shown = build_focus_list(**base)
    assert any(i.domain == "dying.com" for i in shown)
    # case-insensitive set membership
    muted = build_focus_list(**base, auto_renew_off={"DYING.COM"})
    assert not any(i.domain == "dying.com" for i in muted)
