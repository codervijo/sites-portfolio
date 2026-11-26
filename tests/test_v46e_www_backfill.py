"""v46.E — www→apex backfill runner (postponed; built, dry-run only)."""
from __future__ import annotations

from pathlib import Path

from portfolio import www_backfill as wb
from portfolio.fix_helpers import FixResult


def test_run_passes_dry_run_flag_and_isolates_failures(tmp_path):
    seen = []

    def fixer(path: Path, dry_run: bool, assume_yes: bool) -> FixResult:
        seen.append((path.name, dry_run, assume_yes))
        if path.name == "bad.com":
            raise RuntimeError("boom")
        return FixResult(status="would-fix" if dry_run else "fixed", summary="x", files_touched=[])

    sites = [(n, tmp_path / n) for n in ("a.com", "bad.com", "c.com")]
    out = wb.run(sites, apply=False, workers=3, fixer=fixer)
    assert {k: v.status for k, v in out.items()} == {"a.com": "would-fix", "bad.com": "error", "c.com": "would-fix"}
    assert all(dry and yes for _, dry, yes in seen)
    out = wb.run(sites[:1], apply=True, workers=1, fixer=fixer)
    assert out["a.com"].status == "fixed"


def test_main_defaults_to_dry_run_and_filters_only(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(wb, "eligible_sites", lambda: [("a.com", tmp_path), ("b.com", tmp_path)])
    calls = {}

    def fake_run(sites, *, apply, workers, on_result=None, fixer=None):
        calls.update(sites=[d for d, _ in sites], apply=apply)
        return {}
    monkeypatch.setattr(wb, "run", fake_run)
    assert wb.main(["--only", "b.com"]) == 0
    assert calls == {"sites": ["b.com"], "apply": False}
    assert "dry run" in capsys.readouterr().out
