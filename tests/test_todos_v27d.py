"""v27.D — `project todos` + `fleet todos` read views.

Covers the build functions (pure, path-driven) including the
additive-optional baseline: a `lamill.toml` with only `schema` +
`[deploy]` and a site with no `lamill.toml` at all must both work.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from portfolio import todos as todos_mod
from portfolio.lamill_toml import LAMILL_TOML_FILENAME


def _site(root: Path, name: str, body: str | None) -> Path:
    d = root / name
    d.mkdir()
    if body is not None:
        (d / LAMILL_TOML_FILENAME).write_text(body)
    return d


_BASE = 'schema = "lamill-toml-v1"\n[deploy]\nplatform = "cf-pages"\n'

_WITH_TODOS = _BASE + (
    '[[todo]]\nstatus = "open"\ntask = "wire analytics"\npriority = "low"\n'
    '[[todo]]\nstatus = "open"\ntask = "fix canonical redirect"\npriority = "high"\n'
    '[[todo]]\nstatus = "open"\ntask = "tidy footer"\n'  # no priority
    '[[todo]]\nstatus = "done"\ntask = "ship v1"\n'
)


# ---- build_project_todos --------------------------------------------


def test_project_no_toml(tmp_path: Path):
    pt = todos_mod.build_project_todos(tmp_path / "nope", domain="nope")
    assert pt.has_toml is False
    assert pt.total == 0


def test_project_baseline_no_todos(tmp_path: Path):
    d = _site(tmp_path, "bare.com", _BASE)
    pt = todos_mod.build_project_todos(d, domain="bare.com")
    assert pt.has_toml is True
    assert pt.open_items == []
    assert pt.done_items == []


def test_project_open_sorted_by_priority(tmp_path: Path):
    d = _site(tmp_path, "site.com", _WITH_TODOS)
    pt = todos_mod.build_project_todos(d, domain="site.com")
    # Grouped by priority rank (high → low → unprioritized); within a
    # bucket the operator's authored file order is preserved (stable
    # sort). Here each bucket has one item, so order is high, low, none.
    assert [t.task for t in pt.open_items] == [
        "fix canonical redirect", "wire analytics", "tidy footer",
    ]
    assert pt.open_items[0].priority == "high"
    assert pt.open_items[-1].priority is None
    assert [t.task for t in pt.done_items] == ["ship v1"]
    assert pt.total == 4


def test_project_preserves_authored_order_within_bucket(tmp_path: Path):
    body = _BASE + (
        '[[todo]]\nstatus = "open"\ntask = "zebra task"\npriority = "high"\n'
        '[[todo]]\nstatus = "open"\ntask = "apple task"\npriority = "high"\n'
    )
    d = _site(tmp_path, "ord.com", body)
    pt = todos_mod.build_project_todos(d, domain="ord.com")
    # Both high → file order kept (NOT alpha-sorted).
    assert [t.task for t in pt.open_items] == ["zebra task", "apple task"]


def test_project_malformed_raises(tmp_path: Path):
    from portfolio import lamill_toml
    bad = _BASE + '[[todo]]\nstatus = "open"\ntask = "x"\npriority = "urgent"\n'
    d = _site(tmp_path, "bad.com", bad)
    with pytest.raises(lamill_toml.ParseError):
        todos_mod.build_project_todos(d, domain="bad.com")


# ---- build_fleet_todos ----------------------------------------------


def _fleet(tmp_path: Path) -> list[Path]:
    a = _site(tmp_path, "alpha.com", _WITH_TODOS)
    b = _site(tmp_path, "beta.com", _BASE)              # declared, no todos
    c = _site(tmp_path, "gamma.com", None)              # no lamill.toml
    return [a, b, c]


def test_fleet_open_default(tmp_path: Path):
    rows = todos_mod.build_fleet_todos(_fleet(tmp_path))
    # Only alpha has open todos; beta/gamma contribute nothing. Fleet
    # view groups by priority rank across the fleet: high → low → unset.
    assert {r.domain for r in rows} == {"alpha.com"}
    assert [r.item.task for r in rows] == [
        "fix canonical redirect", "wire analytics", "tidy footer",
    ]


def test_fleet_priority_filter(tmp_path: Path):
    rows = todos_mod.build_fleet_todos(_fleet(tmp_path), priority="high")
    assert len(rows) == 1
    assert rows[0].item.task == "fix canonical redirect"


def test_fleet_status_done(tmp_path: Path):
    rows = todos_mod.build_fleet_todos(_fleet(tmp_path), status="done")
    assert [r.item.task for r in rows] == ["ship v1"]


def test_fleet_status_all(tmp_path: Path):
    rows = todos_mod.build_fleet_todos(_fleet(tmp_path), status=None)
    assert len(rows) == 4


def test_fleet_skips_malformed(tmp_path: Path):
    _site(tmp_path, "alpha.com", _WITH_TODOS)
    bad = _BASE + '[[todo]]\nstatus = "open"\ntask = "x"\npriority = "urgent"\n'
    _site(tmp_path, "bad.com", bad)
    # A bad file in the sweep must not abort the whole fleet view.
    rows = todos_mod.build_fleet_todos(sorted(tmp_path.iterdir()))
    assert {r.domain for r in rows} == {"alpha.com"}


def test_fleet_sort_priority_then_domain(tmp_path: Path):
    # Two sites with a high item each → grouped by priority, then domain.
    hi = _BASE + '[[todo]]\nstatus = "open"\ntask = "t"\npriority = "high"\n'
    _site(tmp_path, "zeta.com", hi)
    _site(tmp_path, "alpha.com", hi)
    rows = todos_mod.build_fleet_todos(sorted(tmp_path.iterdir()))
    assert [r.domain for r in rows] == ["alpha.com", "zeta.com"]


def test_fleet_empty(tmp_path: Path):
    _site(tmp_path, "bare.com", _BASE)
    rows = todos_mod.build_fleet_todos(sorted(tmp_path.iterdir()))
    assert rows == []
