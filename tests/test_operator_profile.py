"""Tests for v8.D P3 — operator profile loader.

P3.1 — covers the `OperatorProfile` dataclass + `load_operator_profile()`
loader. Fit-check logic (P3.2) lives in a separate commit + test file.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from portfolio.operator_profile import (
    DEFAULT_CADENCE,
    DEFAULT_WORKFLOW,
    OperatorProfile,
    load_operator_profile,
)


# ---------- defaults / dataclass shape ----------


def test_operator_profile_defaults():
    p = OperatorProfile()
    assert p.expertise == []
    assert p.workflow_preference == "mixed"
    assert p.motivation_cadence == "monthly"
    assert p.configured is False


def test_operator_profile_configured_when_expertise_set():
    p = OperatorProfile(expertise=["SEO"])
    assert p.configured is True


def test_operator_profile_configured_when_workflow_non_default():
    p = OperatorProfile(workflow_preference="builder")
    assert p.configured is True


def test_operator_profile_configured_when_cadence_non_default():
    p = OperatorProfile(motivation_cadence="weekly")
    assert p.configured is True


# ---------- loader: file absence / parse errors ----------


def test_load_returns_defaults_when_file_missing(tmp_path: Path):
    missing = tmp_path / "lamill.toml"
    assert not missing.exists()
    p = load_operator_profile(missing)
    assert p == OperatorProfile()


def test_load_returns_defaults_when_section_missing(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [deploy]
        platform = "cf-pages"
    """).strip())
    p = load_operator_profile(f)
    assert p == OperatorProfile()


def test_load_returns_defaults_on_malformed_toml(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text("this is not [valid toml at all")
    p = load_operator_profile(f)
    assert p == OperatorProfile()


def test_load_returns_defaults_when_operator_not_table(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text('operator = "not a table"\n')
    p = load_operator_profile(f)
    assert p == OperatorProfile()


# ---------- loader: happy path ----------


def test_load_full_operator_section(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        expertise = ["SEO and programmatic content", "Python CLI tooling"]
        workflow_preference = "builder"
        motivation_cadence = "weekly"
    """).strip())
    p = load_operator_profile(f)
    assert p.expertise == ["SEO and programmatic content", "Python CLI tooling"]
    assert p.workflow_preference == "builder"
    assert p.motivation_cadence == "weekly"
    assert p.configured is True


def test_load_partial_operator_section_fills_defaults(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        expertise = ["SEO"]
    """).strip())
    p = load_operator_profile(f)
    assert p.expertise == ["SEO"]
    assert p.workflow_preference == DEFAULT_WORKFLOW
    assert p.motivation_cadence == DEFAULT_CADENCE


# ---------- loader: input cleaning ----------


def test_load_strips_whitespace_in_expertise(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        expertise = ["  SEO  ", "", "Python"]
    """).strip())
    p = load_operator_profile(f)
    assert p.expertise == ["SEO", "Python"]


def test_load_drops_non_string_expertise_items(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        expertise = ["SEO", 42, "Python"]
    """).strip())
    p = load_operator_profile(f)
    assert p.expertise == ["SEO", "Python"]


def test_load_returns_empty_expertise_when_not_list(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text(textwrap.dedent("""
        [operator]
        expertise = "not a list"
    """).strip())
    p = load_operator_profile(f)
    assert p.expertise == []


# ---------- loader: enum validation ----------


@pytest.mark.parametrize("value", ["builder", "writer", "mixed"])
def test_load_accepts_valid_workflow_preference(tmp_path: Path, value: str):
    f = tmp_path / "lamill.toml"
    f.write_text(f'[operator]\nworkflow_preference = "{value}"\n')
    p = load_operator_profile(f)
    assert p.workflow_preference == value


def test_load_normalizes_workflow_case(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text('[operator]\nworkflow_preference = "Builder"\n')
    p = load_operator_profile(f)
    assert p.workflow_preference == "builder"


def test_load_falls_back_to_default_on_unknown_workflow(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text('[operator]\nworkflow_preference = "ninja"\n')
    p = load_operator_profile(f)
    assert p.workflow_preference == DEFAULT_WORKFLOW


@pytest.mark.parametrize("value", ["weekly", "monthly", "quarterly"])
def test_load_accepts_valid_cadence(tmp_path: Path, value: str):
    f = tmp_path / "lamill.toml"
    f.write_text(f'[operator]\nmotivation_cadence = "{value}"\n')
    p = load_operator_profile(f)
    assert p.motivation_cadence == value


def test_load_falls_back_to_default_on_unknown_cadence(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text('[operator]\nmotivation_cadence = "yearly"\n')
    p = load_operator_profile(f)
    assert p.motivation_cadence == DEFAULT_CADENCE


def test_load_falls_back_when_non_string_enum(tmp_path: Path):
    f = tmp_path / "lamill.toml"
    f.write_text('[operator]\nworkflow_preference = 42\n')
    p = load_operator_profile(f)
    assert p.workflow_preference == DEFAULT_WORKFLOW
