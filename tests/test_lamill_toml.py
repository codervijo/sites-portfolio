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
    LAMILL_TOML_FILENAME,
    PLATFORM_VALUES,
    SCHEMA_VERSION,
    STACK_FRAMEWORK_VALUES,
    TODO_PRIORITY_VALUES,
    TODO_STATUS_VALUES,
    BackendBlock,
    DeployBlock,
    HostingBlock,
    LamillToml,
    ParseError,
    StackBlock,
    TodoItem,
    detect_platform_signals,
    infer_from_existing_configs,
    load,
    write,
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


# ---------- writer ----------


def test_write_creates_lamill_toml_at_repo_root(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    target = tmp_path / LAMILL_TOML_FILENAME
    assert target.exists()
    assert target.is_file()


def test_write_minimal_payload_round_trips(tmp_path: Path):
    payload = LamillToml(deploy=DeployBlock(platform="cf-pages"))
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded == payload


def test_write_full_payload_round_trips(tmp_path: Path):
    payload = LamillToml(
        schema=SCHEMA_VERSION,
        deploy=DeployBlock(
            platform="hostgator",
            account="vik@hostgator",
            production_branch="release",
            auto_deploy=False,
            custom_domains=["example.com", "www.example.com"],
        ),
        hosting=HostingBlock(
            cpanel_user="vikt",
            cpanel_url="https://gator4045.hostgator.com:2083",
            ftp_host="ftp.example.com",
            ftp_user="vikt@example.com",
            ftp_port=21,
            public_html_path="/home/vikt/public_html/example.com/",
        ),
        backend=BackendBlock(db="postgres", framework="fastapi", hosting="fly.io"),
        notes="WordPress install; planning React migration",
    )
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded == payload


def test_write_omits_unset_optional_deploy_fields(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "account" not in body
    assert "auto_deploy" not in body
    assert "custom_domains" not in body


def test_write_includes_production_branch_even_when_default(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert 'production_branch = "main"' in body


def test_write_omits_hosting_block_when_none(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "[hosting]" not in body


def test_write_omits_backend_block_when_none(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "[backend]" not in body


def test_write_omits_notes_block_when_none(tmp_path: Path):
    write(tmp_path, LamillToml(deploy=DeployBlock(platform="cf-pages")))
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "[notes]" not in body


def test_write_includes_backend_block_with_default_nones(tmp_path: Path):
    payload = LamillToml(
        deploy=DeployBlock(platform="cf-pages"),
        backend=BackendBlock(),
    )
    write(tmp_path, payload)
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "[backend]" in body
    assert 'db = "none"' in body
    assert 'framework = "none"' in body
    # Round-trip preserves the explicit declaration even when all-default.
    assert load(tmp_path) == payload


def test_write_includes_partial_hosting_block(tmp_path: Path):
    payload = LamillToml(
        deploy=DeployBlock(platform="hostgator"),
        hosting=HostingBlock(
            cpanel_user="vikt",
            public_html_path="/home/vikt/public_html/x/",
        ),
    )
    write(tmp_path, payload)
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert 'cpanel_user = "vikt"' in body
    assert "ftp_host" not in body
    assert load(tmp_path) == payload


def test_write_atomic_replaces_existing_file(tmp_path: Path):
    # First write
    first = LamillToml(deploy=DeployBlock(platform="cf-pages"))
    write(tmp_path, first)
    # Overwrite with a different payload
    second = LamillToml(
        deploy=DeployBlock(platform="vercel", account="team-a"),
    )
    write(tmp_path, second)
    # Only the target file remains — no temp files left behind.
    files = sorted(p.name for p in tmp_path.iterdir())
    assert files == [LAMILL_TOML_FILENAME]
    assert load(tmp_path) == second


@pytest.mark.parametrize("platform", PLATFORM_VALUES)
def test_round_trip_each_platform(tmp_path: Path, platform: str):
    payload = LamillToml(
        deploy=DeployBlock(platform=platform),
        hosting=(
            HostingBlock(public_html_path="/var/www/x/")
            if platform in ("hostgator", "custom")
            else None
        ),
    )
    write(tmp_path, payload)
    assert load(tmp_path) == payload


def test_round_trip_preserves_explicit_auto_deploy_false_on_cf_pages(
    tmp_path: Path,
):
    payload = LamillToml(
        deploy=DeployBlock(platform="cf-pages", auto_deploy=False),
    )
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded is not None
    assert reloaded.deploy.auto_deploy is False
    assert reloaded.deploy.effective_auto_deploy() is False


def test_round_trip_preserves_explicit_auto_deploy_true_on_hostgator(
    tmp_path: Path,
):
    payload = LamillToml(
        deploy=DeployBlock(platform="hostgator", auto_deploy=True),
        hosting=HostingBlock(public_html_path="/var/www/x/"),
    )
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded is not None
    assert reloaded.deploy.auto_deploy is True
    assert reloaded.deploy.effective_auto_deploy() is True


def test_write_load_write_byte_for_byte_determinism(tmp_path: Path):
    """write() must be a pure function of LamillToml: write → load →
    write must produce identical bytes on the second write. This is
    the core round-trip determinism guarantee."""
    payload = LamillToml(
        deploy=DeployBlock(
            platform="vercel",
            account="team-prod",
            production_branch="main",
            auto_deploy=True,
            custom_domains=["calcengine.site"],
        ),
        backend=BackendBlock(db="sqlite", framework="fastapi", hosting="fly.io"),
        notes="brief note",
    )
    write(tmp_path, payload)
    first_bytes = (tmp_path / LAMILL_TOML_FILENAME).read_bytes()
    reloaded = load(tmp_path)
    assert reloaded is not None
    write(tmp_path, reloaded)
    second_bytes = (tmp_path / LAMILL_TOML_FILENAME).read_bytes()
    assert first_bytes == second_bytes


# ---------- infer_from_existing_configs ----------


def test_detect_platform_signals_all_false_when_empty(tmp_path: Path):
    s = detect_platform_signals(tmp_path)
    assert s == {
        "cf-pages": False,
        "cf-workers": False,
        "vercel": False,
        "netlify": False,
    }


def test_detect_cf_pages_from_wrangler_jsonc(tmp_path: Path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{\n  "name": "example",\n  "pages_build_output_dir": "./dist"\n}\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-pages"] is True
    assert s["cf-workers"] is False


def test_detect_cf_pages_from_modern_assets_block_jsonc(tmp_path: Path):
    # Modern CF Pages spec — no `pages_build_output_dir`, uses an
    # `assets` block instead. The bootstrap generator writes this
    # form per the homeloom.app convention.
    (tmp_path / "wrangler.jsonc").write_text(
        '{\n'
        '  "name": "example",\n'
        '  "compatibility_date": "2026-05-18",\n'
        '  "assets": {\n'
        '    "directory": "./dist",\n'
        '    "not_found_handling": "single-page-application"\n'
        '  }\n'
        '}\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-pages"] is True
    assert s["cf-workers"] is False


def test_detect_cf_pages_from_modern_assets_block_toml(tmp_path: Path):
    (tmp_path / "wrangler.toml").write_text(
        'name = "example"\n'
        'compatibility_date = "2026-05-18"\n\n'
        '[assets]\n'
        'directory = "./dist"\n'
        'not_found_handling = "single-page-application"\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-pages"] is True
    assert s["cf-workers"] is False


def test_detect_cf_workers_from_wrangler_jsonc(tmp_path: Path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{\n  "name": "example",\n  "main": "src/index.ts"\n}\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-workers"] is True
    assert s["cf-pages"] is False


def test_detect_cf_pages_from_wrangler_toml(tmp_path: Path):
    (tmp_path / "wrangler.toml").write_text(
        'name = "example"\npages_build_output_dir = "./dist"\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-pages"] is True
    assert s["cf-workers"] is False


def test_detect_cf_workers_from_wrangler_toml(tmp_path: Path):
    (tmp_path / "wrangler.toml").write_text(
        'name = "example"\nmain = "src/worker.ts"\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["cf-workers"] is True
    assert s["cf-pages"] is False


def test_detect_vercel_from_vercel_json(tmp_path: Path):
    (tmp_path / "vercel.json").write_text('{"version": 2}\n')
    s = detect_platform_signals(tmp_path)
    assert s["vercel"] is True


def test_detect_netlify_from_netlify_toml(tmp_path: Path):
    (tmp_path / "netlify.toml").write_text(
        '[build]\npublish = "dist"\ncommand = "npm run build"\n'
    )
    s = detect_platform_signals(tmp_path)
    assert s["netlify"] is True


def test_infer_returns_none_when_no_configs(tmp_path: Path):
    assert infer_from_existing_configs(tmp_path) is None


def test_infer_cf_pages_from_wrangler_jsonc(tmp_path: Path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{"name":"x","pages_build_output_dir":"./dist"}\n'
    )
    block = infer_from_existing_configs(tmp_path)
    assert block is not None
    assert block.platform == "cf-pages"
    # All other fields stay at defaults; operator/caller fills.
    assert block.account is None
    assert block.production_branch == "main"
    assert block.auto_deploy is None
    assert block.custom_domains == []


def test_infer_cf_workers_from_wrangler_jsonc(tmp_path: Path):
    (tmp_path / "wrangler.jsonc").write_text(
        '{"name":"x","main":"src/worker.ts"}\n'
    )
    block = infer_from_existing_configs(tmp_path)
    assert block is not None
    assert block.platform == "cf-workers"


def test_infer_vercel_from_vercel_json(tmp_path: Path):
    (tmp_path / "vercel.json").write_text('{"version": 2}\n')
    block = infer_from_existing_configs(tmp_path)
    assert block is not None
    assert block.platform == "vercel"


def test_infer_netlify_from_netlify_toml(tmp_path: Path):
    (tmp_path / "netlify.toml").write_text('[build]\npublish = "dist"\n')
    block = infer_from_existing_configs(tmp_path)
    assert block is not None
    assert block.platform == "netlify"


def test_infer_returns_none_on_wrangler_plus_vercel(tmp_path: Path):
    # The drift case — lamill.io-style: wrangler.jsonc + vercel.json
    # both present. Migration must surface manually.
    (tmp_path / "wrangler.jsonc").write_text(
        '{"name":"x","pages_build_output_dir":"./dist"}\n'
    )
    (tmp_path / "vercel.json").write_text('{"version": 2}\n')
    assert infer_from_existing_configs(tmp_path) is None
    # The signals dict differentiates this from the "no configs" case.
    s = detect_platform_signals(tmp_path)
    assert sum(s.values()) == 2


def test_infer_returns_none_on_vercel_plus_netlify(tmp_path: Path):
    (tmp_path / "vercel.json").write_text('{"version": 2}\n')
    (tmp_path / "netlify.toml").write_text('[build]\npublish = "dist"\n')
    assert infer_from_existing_configs(tmp_path) is None


def test_infer_jsonc_with_line_comments(tmp_path: Path):
    # Real-world wrangler.jsonc files often have // comments.
    (tmp_path / "wrangler.jsonc").write_text(
        '// CF Pages config for example.com\n'
        '{\n'
        '  "name": "example",\n'
        '  "pages_build_output_dir": "./dist"  // build output\n'
        '}\n'
    )
    block = infer_from_existing_configs(tmp_path)
    assert block is not None
    assert block.platform == "cf-pages"


# ---------- v11.N — deploy_source field ----------


def test_hosting_block_default_deploy_source_is_dist(tmp_path: Path):
    """When [hosting].deploy_source is absent, parser falls back to
    the v11.N default `dist/`."""
    _write(tmp_path, '''
        [deploy]
        platform = "hostgator"
        account = "gator3164"

        [hosting]
        public_html_path = "/home/test/public_html/x.com"
    ''')
    t = load(tmp_path)
    assert t is not None
    assert t.hosting is not None
    assert t.hosting.deploy_source == "dist/"


def test_hosting_block_explicit_deploy_source_round_trips(tmp_path: Path):
    """Explicit `deploy_source = "public/"` survives load → write →
    load. Used by raw-PHP / WP-child-theme operators."""
    payload = LamillToml(
        deploy=DeployBlock(platform="hostgator", account="gator3164"),
        hosting=HostingBlock(
            public_html_path="/home/test/public_html/x.com",
            deploy_source="public/",
        ),
    )
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded is not None
    assert reloaded.hosting is not None
    assert reloaded.hosting.deploy_source == "public/"


def test_hosting_block_default_deploy_source_omitted_on_write(
    tmp_path: Path,
):
    """If the operator uses the default `dist/`, the serializer skips
    the field — keeps round-trip determinism + minimal files."""
    payload = LamillToml(
        deploy=DeployBlock(platform="hostgator", account="gator3164"),
        hosting=HostingBlock(
            public_html_path="/home/test/public_html/x.com",
            # deploy_source left as default "dist/"
        ),
    )
    write(tmp_path, payload)
    on_disk = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "deploy_source" not in on_disk


def test_hosting_block_deploy_source_must_be_string(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "hostgator"
        account = "gator3164"

        [hosting]
        public_html_path = "/home/test/public_html/x.com"
        deploy_source = 42
    ''')
    with pytest.raises(ParseError, match="deploy_source"):
        load(tmp_path)


# ---------- v27.B — [[todo]] + [stack] additive optional tables ----------


def test_baseline_neither_table_present_defaults_clean(tmp_path: Path):
    """Additive-optional invariant (docs/CLAUDE.md): a file with only
    schema + [deploy] must keep parsing; both new tables default to
    empty/None."""
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"
    ''')
    payload = load(tmp_path)
    assert payload.stack is None
    assert payload.todos == []


def test_load_with_stack_minimal(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [stack]
        framework = "astro"
    ''')
    payload = load(tmp_path)
    assert payload.stack == StackBlock(framework="astro", build_tool=None)


def test_load_with_stack_build_tool(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [stack]
        framework = "tanstack"
        build_tool = "vite"
    ''')
    payload = load(tmp_path)
    assert payload.stack == StackBlock(framework="tanstack", build_tool="vite")


@pytest.mark.parametrize("framework", list(STACK_FRAMEWORK_VALUES))
def test_load_each_stack_framework(tmp_path: Path, framework: str):
    _write(tmp_path, f'''
        [deploy]
        platform = "cf-pages"

        [stack]
        framework = "{framework}"
    ''')
    payload = load(tmp_path)
    assert payload.stack is not None
    assert payload.stack.framework == framework


def test_load_raises_on_missing_stack_framework(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [stack]
        build_tool = "vite"
    ''')
    with pytest.raises(ParseError, match=r"\[stack\]\.framework is required"):
        load(tmp_path)


def test_load_raises_on_bad_stack_framework(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [stack]
        framework = "ember-classic"
    ''')
    with pytest.raises(ParseError, match="not a valid framework"):
        load(tmp_path)


def test_load_raises_on_non_string_stack_build_tool(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [stack]
        framework = "astro"
        build_tool = 42
    ''')
    with pytest.raises(ParseError, match="build_tool must be a string"):
        load(tmp_path)


def test_load_with_todos_done_and_open(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "done"
        task = "Ship the landing page"

        [[todo]]
        status = "open"
        priority = "high"
        task = "Verify Lindy drafts against the live platform"
    ''')
    payload = load(tmp_path)
    assert len(payload.todos) == 2
    assert payload.todos[0] == TodoItem(
        status="done", task="Ship the landing page", priority=None,
    )
    assert payload.todos[1] == TodoItem(
        status="open", task="Verify Lindy drafts against the live platform",
        priority="high",
    )


def test_load_raises_on_bad_todo_status(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "blocked"
        task = "x"
    ''')
    with pytest.raises(ParseError, match=r"status='blocked'"):
        load(tmp_path)


def test_load_raises_on_bad_todo_priority(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "open"
        priority = "urgent"
        task = "x"
    ''')
    with pytest.raises(ParseError, match=r"priority='urgent'"):
        load(tmp_path)


def test_load_raises_on_priority_on_done_item(tmp_path: Path):
    """Locked target shape: `priority` is only valid on open items."""
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "done"
        priority = "high"
        task = "Shipped"
    ''')
    with pytest.raises(
        ParseError, match=r"status='done' — priority is only valid on open",
    ):
        load(tmp_path)


def test_load_raises_on_missing_todo_task(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "open"
    ''')
    with pytest.raises(ParseError, match="task is required"):
        load(tmp_path)


def test_load_raises_on_empty_todo_task(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [[todo]]
        status = "open"
        task = "   "
    ''')
    with pytest.raises(ParseError, match="must be a non-empty string"):
        load(tmp_path)


def test_load_raises_on_non_list_todo(tmp_path: Path):
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [todo]
        status = "done"
        task = "x"
    ''')
    with pytest.raises(ParseError, match="must be an array of tables"):
        load(tmp_path)


def test_round_trip_preserves_stack(tmp_path: Path):
    payload = LamillToml(
        deploy=DeployBlock(platform="cf-pages"),
        stack=StackBlock(framework="astro", build_tool="vite"),
    )
    write(tmp_path, payload)
    reloaded = load(tmp_path)
    assert reloaded.stack == payload.stack


def test_round_trip_preserves_todos_and_emits_canonical_comment(tmp_path: Path):
    """The writer prepends a canonical `# Tracked todos for <site>.
    status: "done" | "open".` comment above the `[[todo]]` block — the
    operator can hand-edit the file knowing this minimum context line
    survives every round-trip."""
    repo_dir = tmp_path / "drdebug.dev"
    repo_dir.mkdir()
    payload = LamillToml(
        deploy=DeployBlock(platform="cf-pages"),
        todos=[
            TodoItem(status="done", task="Shipped the landing page"),
            TodoItem(
                status="open", task="Verify drafts", priority="high",
            ),
            TodoItem(
                status="open", task="Wire GA4", priority="medium",
            ),
        ],
    )
    write(repo_dir, payload)
    body = (repo_dir / LAMILL_TOML_FILENAME).read_text()
    assert '# Tracked todos for drdebug.dev. status: "done" | "open".' in body
    reloaded = load(repo_dir)
    assert reloaded.todos == payload.todos


def test_round_trip_no_todos_omits_canonical_comment(tmp_path: Path):
    """When `todos` is empty the writer must NOT emit the header comment
    (no `[[todo]]` block to label)."""
    payload = LamillToml(deploy=DeployBlock(platform="cf-pages"))
    write(tmp_path, payload)
    body = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert "Tracked todos" not in body
    assert "[[todo]]" not in body


def test_round_trip_preserves_both_tables_together(tmp_path: Path):
    repo_dir = tmp_path / "dailyring.xyz"
    repo_dir.mkdir()
    payload = LamillToml(
        deploy=DeployBlock(platform="cf-pages"),
        stack=StackBlock(framework="astro"),
        todos=[TodoItem(status="open", task="Launch", priority="high")],
    )
    write(repo_dir, payload)
    reloaded = load(repo_dir)
    assert reloaded.stack == payload.stack
    assert reloaded.todos == payload.todos


def test_existing_v1_file_with_unknown_top_level_table_is_ignored(tmp_path: Path):
    """Forward-compat side of the additive-optional invariant: an old
    reader (no support for some future table) silently ignores it
    rather than ParseError-ing."""
    _write(tmp_path, '''
        [deploy]
        platform = "cf-pages"

        [future_feature]
        flag = "experimental"
    ''')
    payload = load(tmp_path)
    assert payload.deploy.platform == "cf-pages"
    assert payload.stack is None
    assert payload.todos == []


def test_todo_status_values_match_locked_shape():
    assert set(TODO_STATUS_VALUES) == {"done", "open"}


def test_todo_priority_values_match_locked_shape():
    assert set(TODO_PRIORITY_VALUES) == {"high", "medium", "low"}


def test_stack_framework_values_match_locked_shape():
    assert set(STACK_FRAMEWORK_VALUES) == {
        "astro", "vite-react", "tanstack", "nextjs", "sveltekit",
        "wordpress", "static", "none",
    }
