"""Tests for v6.D.1 — per-domain check report action plan.

When `check git --domain <name>` renders the per-repo detail table,
it now appends a "Suggested fixes" block with concrete commands
per non-passing check. Categories: Tier 1, Tier 2 (--ai), manual,
design-skipped.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from portfolio.checks.result import CheckResult
from portfolio.cli import _render_action_plan, _MANUAL_HINTS


class _FakeConsole:
    """Capture console.print calls for assertions."""
    def __init__(self):
        self.output: list[str] = []
    def print(self, *args, **kwargs):
        # Strip Rich markup for easier matching.
        for a in args:
            self.output.append(str(a))


def _set_console(monkeypatch, fake):
    import portfolio.cli as cli_module
    monkeypatch.setattr(cli_module, "console", fake)


# ---------- categorization ----------


def test_action_plan_tier_1_section(monkeypatch):
    """A failing tier-1-fixable check appears in the Tier 1 section."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_006": CheckResult(status="fail", message="docs/CLAUDE.md missing"),
    }
    _render_action_plan("kwizicle.com", results)
    out = "\n".join(fake.output)
    assert "Tier 1" in out
    assert "kwizicle.com" in out
    assert "--apply --yes" in out
    assert "CHECK_006" in out


def test_action_plan_manual_section(monkeypatch):
    """A failing check without a fixer appears in the manual section
    with its hint."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_035": CheckResult(status="fail",
                                  message="vite ^5 — needs ≥6"),
    }
    _render_action_plan("lamillrentals.com", results)
    out = "\n".join(fake.output)
    assert "Manual" in out
    assert "CHECK_035" in out
    # Hint comes from _MANUAL_HINTS
    assert "pnpm update vite" in out


def test_action_plan_design_skipped_only_renders_nothing(monkeypatch):
    """When only design-skipped checks are non-passing, nothing is
    actionable and the action plan stays silent (clean UX)."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_051": CheckResult(status="warn",
                                  message="not a CF Pages project — skipped"),
        "CHECK_130": CheckResult(status="warn",
                                  message="not a content-pipeline project — skipped"),
    }
    _render_action_plan("kwizicle.com", results)
    out = "\n".join(fake.output)
    # No "Suggested fixes" header — there's nothing to suggest.
    assert "Suggested fixes" not in out


def test_action_plan_design_skipped_grouped_alongside_actionable(monkeypatch):
    """When manual + design-skipped both present, skipped gets its
    own section listing the IDs."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_035": CheckResult(status="fail", message="vite ^5"),  # manual
        "CHECK_051": CheckResult(status="warn",
                                  message="not a CF Pages project — skipped"),
        "CHECK_130": CheckResult(status="warn",
                                  message="not a content-pipeline project — skipped"),
    }
    _render_action_plan("kwizicle.com", results)
    out = "\n".join(fake.output)
    assert "Skipped" in out
    assert "CHECK_051" in out
    assert "CHECK_130" in out
    assert "design intent" in out


def test_action_plan_passes_dont_appear(monkeypatch):
    """Passing checks are filtered out — no action needed."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_001": CheckResult(status="pass", message="README present"),
        "CHECK_002": CheckResult(status="pass", message="AI_AGENTS present"),
    }
    _render_action_plan("kwizicle.com", results)
    out = "\n".join(fake.output)
    # Nothing rendered when all checks pass.
    assert "CHECK_001" not in out
    assert "Suggested fixes" not in out


def test_action_plan_empty_when_all_pass(monkeypatch):
    """No `Suggested fixes:` header when nothing is non-passing."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_001": CheckResult(status="pass", message=""),
    }
    _render_action_plan("clean.com", results)
    out = "\n".join(fake.output)
    assert out == ""


def test_action_plan_combines_categories(monkeypatch):
    """Multi-category result shows ALL applicable sections."""
    fake = _FakeConsole()
    _set_console(monkeypatch, fake)
    results = {
        "CHECK_001": CheckResult(status="pass", message="ok"),
        "CHECK_006": CheckResult(status="fail", message="missing"),    # Tier 1
        "CHECK_025": CheckResult(status="fail", message="too short"),   # Tier 2 only
        "CHECK_035": CheckResult(status="fail", message="vite ^5"),     # Manual
        "CHECK_051": CheckResult(status="warn",
                                  message="not a CF Pages project — skipped"),
    }
    _render_action_plan("kwizicle.com", results)
    out = "\n".join(fake.output)
    assert "Tier 1" in out
    assert "Tier 2" in out
    assert "Manual" in out
    assert "Skipped" in out


# ---------- hints sanity ----------


def test_manual_hints_cover_common_check_ids():
    """Spot-check that a few well-known no-fixer checks have hints."""
    for cid in ("CHECK_010", "CHECK_022", "CHECK_024", "CHECK_035",
                "CHECK_071", "CHECK_076"):
        assert cid in _MANUAL_HINTS, f"{cid} missing manual hint"
