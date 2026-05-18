"""Tests for v10.A — `lamill.toml` schema + parser.

Covers `DeployBlock` / `HostingBlock` / `BackendBlock` / `LamillToml`
dataclass shape, `load()` happy path across all eight platforms,
`load()` failure modes (missing required, invalid enum, wrong type),
and the hosting-required-when-platform-needs-it invariant.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from portfolio.lamill_toml import (
    BACKEND_HOSTING_VALUES,
    DB_VALUES,
    FRAMEWORK_VALUES,
    PLATFORM_VALUES,
    SCHEMA_VERSION,
    BackendBlock,
    DeployBlock,
    HostingBlock,
    LamillToml,
    ParseError,
    load,
)


def _write(repo_dir: Path, body: str) -> Path:
    """Write `lamill.toml` under `repo_dir` and return the dir."""
    repo_dir.mkdir(parents=True, exist_ok=True)
    (repo_dir / "lamill.toml").write_text(textwrap.dedent(body).strip() + "\n")
    return repo_dir


# ---------- dataclass shape ----------


def test_deploy_block_effective_auto_deploy_git_native_defaults_true():
    for platform in ("cf-pages", "vercel", "netlify", "github-pages"):
        d = DeployBlock(platform=platform)
        assert d.effective_auto_deploy() is True, platform


def test_deploy_block_effective_auto_deploy_non_git_native_defaults_false():
    for platform in ("cf-workers", "hostgator", "custom", "none"):
        d = DeployBlock(platform=platform)
        assert d.effective_auto_deploy() is False, platform


def test_deploy_block_explicit_auto_deploy_overrides_default():
    # Explicit False on a git-native platform.
    d = DeployBlock(platform="cf-pages", auto_deploy=False)
    assert d.effective_auto_deploy() is False
    # Explicit True on a non-git-native platform.
    d = DeployBlock(platform="hostgator", auto_deploy=True)
    assert d.effective_auto_deploy() is True


def test_lamill_toml_default_schema_is_v1():
    t = LamillToml(deploy=DeployBlock(platform="cf-pages"))
    assert t.schema == SCHEMA_VERSION
    assert t.hosting is None
    assert t.backend is None
    assert t.notes is None


# ---------- loader: file absence ----------


def test_load_returns_none_when_file_missing(tmp_path: Path):
    assert load(tmp_path) is None


# ---------- loader: happy paths ----------


def test_load_minimal_valid_file(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"
    """)
    t = load(tmp_path)
    assert t is not None
    assert t.schema == SCHEMA_VERSION
    assert t.deploy.platform == "cf-pages"
    assert t.deploy.account is None
    assert t.deploy.production_branch == "main"
    assert t.deploy.auto_deploy is None
    assert t.deploy.effective_auto_deploy() is True
    assert t.deploy.custom_domains == []
    assert t.hosting is None
    assert t.backend is None
    assert t.notes is None


@pytest.mark.parametrize("platform", PLATFORM_VALUES)
def test_load_each_platform_value(tmp_path: Path, platform: str):
    hosting_block = (
        '\n[hosting]\npublic_html_path = "/var/www/x/"\n'
        if platform in ("hostgator", "custom")
        else ""
    )
    _write(tmp_path, f"""
        [deploy]
        platform = "{platform}"
        {hosting_block}
    """)
    t = load(tmp_path)
    assert t is not None
    assert t.deploy.platform == platform


def test_load_with_all_optional_sections(tmp_path: Path):
    _write(tmp_path, """
        schema = "lamill-toml-v1"

        [deploy]
        platform = "hostgator"
        account = "vik@hostgator"
        production_branch = "release"
        auto_deploy = false
        custom_domains = ["example.com", "www.example.com"]

        [hosting]
        cpanel_user = "vikt"
        cpanel_url = "https://gator4045.hostgator.com:2083"
        ftp_host = "ftp.example.com"
        ftp_user = "vikt@example.com"
        ftp_port = 21
        public_html_path = "/home/vikt/public_html/example.com/"

        [backend]
        db = "postgres"
        framework = "fastapi"
        hosting = "fly.io"

        [notes]
        text = "transitional WordPress install; React migration planned"
    """)
    t = load(tmp_path)
    assert t is not None
    assert t.deploy.platform == "hostgator"
    assert t.deploy.account == "vik@hostgator"
    assert t.deploy.production_branch == "release"
    assert t.deploy.auto_deploy is False
    assert t.deploy.custom_domains == ["example.com", "www.example.com"]
    assert t.hosting == HostingBlock(
        cpanel_user="vikt",
        cpanel_url="https://gator4045.hostgator.com:2083",
        ftp_host="ftp.example.com",
        ftp_user="vikt@example.com",
        ftp_port=21,
        public_html_path="/home/vikt/public_html/example.com/",
    )
    assert t.backend == BackendBlock(
        db="postgres", framework="fastapi", hosting="fly.io"
    )
    assert t.notes == "transitional WordPress install; React migration planned"


def test_load_ignores_operator_section(tmp_path: Path):
    # The [operator] section is owned by operator_profile.py; the
    # v10.A loader sees it but doesn't carry it on LamillToml.
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"

        [operator]
        expertise = ["SEO"]
        workflow_preference = "builder"
    """)
    t = load(tmp_path)
    assert t is not None
    assert t.deploy.platform == "cf-pages"


def test_load_backend_defaults_when_keys_omitted(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"

        [backend]
    """)
    t = load(tmp_path)
    assert t is not None
    assert t.backend == BackendBlock(db="none", framework="none", hosting="none")


# ---------- loader: malformed TOML ----------


def test_load_raises_on_invalid_toml_syntax(tmp_path: Path):
    _write(tmp_path, "this is not [valid toml at all")
    with pytest.raises(ParseError, match="invalid TOML"):
        load(tmp_path)


# ---------- loader: schema violations ----------


def test_load_raises_on_missing_deploy_section(tmp_path: Path):
    _write(tmp_path, """
        [notes]
        text = "no deploy block"
    """)
    with pytest.raises(ParseError, match=r"\[deploy\] section"):
        load(tmp_path)


def test_load_raises_on_missing_platform(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        account = "x"
    """)
    with pytest.raises(ParseError, match="platform is required"):
        load(tmp_path)


def test_load_raises_on_invalid_platform(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "fly-io"
    """)
    with pytest.raises(ParseError, match="not a valid platform"):
        load(tmp_path)


@pytest.mark.parametrize("platform", ("hostgator", "custom"))
def test_load_raises_when_platform_requires_hosting(
    tmp_path: Path, platform: str
):
    _write(tmp_path, f"""
        [deploy]
        platform = "{platform}"
    """)
    with pytest.raises(ParseError, match="requires a \\[hosting\\] section"):
        load(tmp_path)


def test_load_raises_on_invalid_auto_deploy_type(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"
        auto_deploy = "yes"
    """)
    with pytest.raises(ParseError, match="auto_deploy must be a bool"):
        load(tmp_path)


def test_load_raises_on_non_list_custom_domains(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"
        custom_domains = "example.com"
    """)
    with pytest.raises(ParseError, match="custom_domains must be a list"):
        load(tmp_path)


def test_load_raises_on_non_string_custom_domain_entry(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"
        custom_domains = ["example.com", 42]
    """)
    with pytest.raises(ParseError, match="custom_domains entries must be strings"):
        load(tmp_path)


def test_load_raises_on_invalid_backend_enum_value(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"

        [backend]
        db = "mongo"
    """)
    with pytest.raises(ParseError, match=r"\[backend\].db='mongo' not in"):
        load(tmp_path)


def test_load_raises_on_non_string_notes_text(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "cf-pages"

        [notes]
        text = 42
    """)
    with pytest.raises(ParseError, match=r"\[notes\].text must be a string"):
        load(tmp_path)


def test_load_raises_on_hosting_ftp_port_type(tmp_path: Path):
    _write(tmp_path, """
        [deploy]
        platform = "hostgator"

        [hosting]
        public_html_path = "/var/www/"
        ftp_port = "21"
    """)
    with pytest.raises(ParseError, match="ftp_port must be an integer"):
        load(tmp_path)


def test_load_raises_on_non_string_schema(tmp_path: Path):
    _write(tmp_path, """
        schema = 1

        [deploy]
        platform = "cf-pages"
    """)
    with pytest.raises(ParseError, match="`schema` must be a string"):
        load(tmp_path)


# ---------- enum coverage spot-checks ----------


def test_db_values_includes_expected_set():
    assert set(DB_VALUES) == {"postgres", "sqlite", "duckdb", "redis", "none"}


def test_framework_values_includes_expected_set():
    assert set(FRAMEWORK_VALUES) == {
        "go-fiber",
        "fastapi",
        "express",
        "node-bare",
        "rust-axum",
        "none",
    }


def test_backend_hosting_values_includes_expected_set():
    assert set(BACKEND_HOSTING_VALUES) == {"fly.io", "managed-provider", "none"}
