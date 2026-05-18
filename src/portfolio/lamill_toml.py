"""v10.A — `lamill.toml` per-site deploy declaration: schema + parser.

Reads `<repo_path>/lamill.toml` into a typed `LamillToml` struct.
Strict on read — raises `ParseError` on malformed files or schema
violations. (Contrast `operator_profile.load_operator_profile()`,
which is permissive on its narrow `[operator]` slice.)

This loader ignores the `[operator]` section; that stays the
responsibility of `operator_profile.py` (v8.D Phase 3). The two
loaders co-exist while the portfolio repo's `lamill.toml` carries
both `[deploy]` (when v10.A ships against the portfolio's own repo)
and `[operator]` (already shipped).

Spec: `docs/prd.md` § 6 → v10 → Design notes.
Schema: `docs/architecture.md` § 4 Schemas (sites/<domain>/lamill.toml).
"""
from __future__ import annotations

import os
import shutil
import tempfile
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import tomli_w


# ---- schema constants -----------------------------------------------

SCHEMA_VERSION = "lamill-toml-v1"
LAMILL_TOML_FILENAME = "lamill.toml"

PLATFORM_VALUES: tuple[str, ...] = (
    "cf-pages",
    "cf-workers",
    "vercel",
    "netlify",
    "github-pages",
    "hostgator",
    "custom",
    "none",
)

# Platforms with native git integration → `auto_deploy` defaults true.
# Anything not in this set defaults to false.
_AUTO_DEPLOY_TRUE_PLATFORMS: frozenset[str] = frozenset(
    {"cf-pages", "vercel", "netlify", "github-pages"}
)

# Platforms that require a `[hosting]` section to be reachable. The
# CLI surface in `project_deploy.py` (v10.B) reads this to decide
# which prompts / flags must be filled.
HOSTING_REQUIRED_PLATFORMS: frozenset[str] = frozenset({"hostgator", "custom"})

# `[backend]` enum values (scope expansion 2026-05-17). All default
# to "none" — the slot exists so non-JS-rendering server stacks can
# declare what they run, but a vanilla static site has nothing to fill.
DB_VALUES: tuple[str, ...] = ("postgres", "sqlite", "duckdb", "redis", "none")
FRAMEWORK_VALUES: tuple[str, ...] = (
    "go-fiber",
    "fastapi",
    "express",
    "node-bare",
    "rust-axum",
    "none",
)
BACKEND_HOSTING_VALUES: tuple[str, ...] = ("fly.io", "managed-provider", "none")


class ParseError(Exception):
    """Raised when `lamill.toml` is malformed or violates the schema."""


# ---- dataclasses ----------------------------------------------------


@dataclass
class DeployBlock:
    platform: str
    account: str | None = None
    production_branch: str = "main"
    auto_deploy: bool | None = None
    custom_domains: list[str] = field(default_factory=list)

    def effective_auto_deploy(self) -> bool:
        """Resolve `auto_deploy` to its concrete bool value.

        Default: true for platforms with native git integration
        (cf-pages / vercel / netlify / github-pages); false for the
        rest. An explicit value in the file wins.
        """
        if self.auto_deploy is not None:
            return self.auto_deploy
        return self.platform in _AUTO_DEPLOY_TRUE_PLATFORMS


@dataclass
class HostingBlock:
    cpanel_user: str | None = None
    cpanel_url: str | None = None
    ftp_host: str | None = None
    ftp_user: str | None = None
    ftp_port: int | None = None
    public_html_path: str | None = None


@dataclass
class BackendBlock:
    db: str = "none"
    framework: str = "none"
    hosting: str = "none"


@dataclass
class LamillToml:
    deploy: DeployBlock
    schema: str = SCHEMA_VERSION
    hosting: HostingBlock | None = None
    backend: BackendBlock | None = None
    notes: str | None = None


# ---- loader ---------------------------------------------------------


def load(repo_path: Path) -> LamillToml | None:
    """Load `<repo_path>/lamill.toml` into a `LamillToml` struct.

    Returns `None` if the file doesn't exist (no declaration on this
    project). Raises `ParseError` on TOML syntax errors, missing
    required sections / fields, invalid enum values, or wrong-type
    fields.
    """
    p = repo_path / LAMILL_TOML_FILENAME
    if not p.exists():
        return None

    try:
        with p.open("rb") as f:
            doc = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ParseError(f"{p}: invalid TOML — {e}") from e
    except OSError as e:
        raise ParseError(f"{p}: cannot read — {e}") from e

    return _parse_doc(doc, source=p)


def _parse_doc(doc: dict, *, source: Path) -> LamillToml:
    schema = doc.get("schema", SCHEMA_VERSION)
    if not isinstance(schema, str):
        raise ParseError(f"{source}: top-level `schema` must be a string")

    deploy_raw = doc.get("deploy")
    if not isinstance(deploy_raw, dict):
        raise ParseError(f"{source}: missing required [deploy] section")
    deploy = _parse_deploy(deploy_raw, source=source)

    hosting_raw = doc.get("hosting")
    if hosting_raw is not None and not isinstance(hosting_raw, dict):
        raise ParseError(
            f"{source}: [hosting] must be a table, "
            f"got {type(hosting_raw).__name__}"
        )
    hosting = (
        _parse_hosting(hosting_raw, source=source)
        if hosting_raw is not None
        else None
    )

    if deploy.platform in HOSTING_REQUIRED_PLATFORMS and hosting is None:
        raise ParseError(
            f"{source}: platform={deploy.platform!r} requires a "
            f"[hosting] section"
        )

    backend_raw = doc.get("backend")
    if backend_raw is not None and not isinstance(backend_raw, dict):
        raise ParseError(
            f"{source}: [backend] must be a table, "
            f"got {type(backend_raw).__name__}"
        )
    backend = (
        _parse_backend(backend_raw, source=source)
        if backend_raw is not None
        else None
    )

    notes = _parse_notes(doc.get("notes"), source=source)

    return LamillToml(
        schema=schema,
        deploy=deploy,
        hosting=hosting,
        backend=backend,
        notes=notes,
    )


def _parse_deploy(raw: dict, *, source: Path) -> DeployBlock:
    platform = raw.get("platform")
    if not isinstance(platform, str):
        raise ParseError(
            f"{source}: [deploy].platform is required and must be a string"
        )
    if platform not in PLATFORM_VALUES:
        raise ParseError(
            f"{source}: [deploy].platform={platform!r} is not a valid "
            f"platform (expected one of {', '.join(PLATFORM_VALUES)})"
        )

    account = raw.get("account")
    if account is not None and not isinstance(account, str):
        raise ParseError(f"{source}: [deploy].account must be a string")

    production_branch = raw.get("production_branch", "main")
    if not isinstance(production_branch, str):
        raise ParseError(
            f"{source}: [deploy].production_branch must be a string"
        )

    auto_deploy = raw.get("auto_deploy")
    if auto_deploy is not None and not isinstance(auto_deploy, bool):
        raise ParseError(f"{source}: [deploy].auto_deploy must be a bool")

    custom_domains_raw = raw.get("custom_domains", [])
    if not isinstance(custom_domains_raw, list):
        raise ParseError(
            f"{source}: [deploy].custom_domains must be a list of strings"
        )
    custom_domains: list[str] = []
    for d in custom_domains_raw:
        if not isinstance(d, str):
            raise ParseError(
                f"{source}: [deploy].custom_domains entries must be strings"
            )
        custom_domains.append(d)

    return DeployBlock(
        platform=platform,
        account=account,
        production_branch=production_branch,
        auto_deploy=auto_deploy,
        custom_domains=custom_domains,
    )


def _parse_hosting(raw: dict, *, source: Path) -> HostingBlock:
    def _str(key: str) -> str | None:
        v = raw.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            raise ParseError(f"{source}: [hosting].{key} must be a string")
        return v

    ftp_port = raw.get("ftp_port")
    if ftp_port is not None and (
        not isinstance(ftp_port, int) or isinstance(ftp_port, bool)
    ):
        raise ParseError(f"{source}: [hosting].ftp_port must be an integer")

    return HostingBlock(
        cpanel_user=_str("cpanel_user"),
        cpanel_url=_str("cpanel_url"),
        ftp_host=_str("ftp_host"),
        ftp_user=_str("ftp_user"),
        ftp_port=ftp_port,
        public_html_path=_str("public_html_path"),
    )


def _parse_backend(raw: dict, *, source: Path) -> BackendBlock:
    def _enum(key: str, allowed: tuple[str, ...]) -> str:
        v = raw.get(key, "none")
        if not isinstance(v, str):
            raise ParseError(f"{source}: [backend].{key} must be a string")
        if v not in allowed:
            raise ParseError(
                f"{source}: [backend].{key}={v!r} not in "
                f"{{{', '.join(allowed)}}}"
            )
        return v

    return BackendBlock(
        db=_enum("db", DB_VALUES),
        framework=_enum("framework", FRAMEWORK_VALUES),
        hosting=_enum("hosting", BACKEND_HOSTING_VALUES),
    )


def _parse_notes(raw: object, *, source: Path) -> str | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ParseError(
            f"{source}: [notes] must be a table, got {type(raw).__name__}"
        )
    text = raw.get("text")
    if text is None:
        return None
    if not isinstance(text, str):
        raise ParseError(f"{source}: [notes].text must be a string")
    return text


# ---- writer ---------------------------------------------------------


def write(repo_path: Path, payload: LamillToml) -> None:
    """Atomically write `<repo_path>/lamill.toml`.

    Uses tmpfile + rename so partial writes can't corrupt an existing
    file. Comments are NOT preserved — tomli-w doesn't carry them
    through a round-trip, and operator edits go through `$EDITOR`
    directly (the writer is only invoked from `new bootstrap`,
    `project set-deploy`, and the migration sweep — paths where the
    operator hasn't hand-annotated the file yet).
    """
    target = repo_path / LAMILL_TOML_FILENAME
    doc = _serialize(payload)
    body = tomli_w.dumps(doc)
    _atomic_write(target, body)


def _serialize(payload: LamillToml) -> dict:
    """Convert a `LamillToml` into a tomli_w-serializable dict.

    Stable key order: `schema`, then `[deploy]`, then optional
    `[hosting]` / `[backend]` / `[notes]` blocks. Each block writes
    only the fields the operator set (None / empty-list values are
    omitted) so round-trip determinism holds.
    """
    out: dict = {"schema": payload.schema}

    deploy: dict = {"platform": payload.deploy.platform}
    if payload.deploy.account is not None:
        deploy["account"] = payload.deploy.account
    # production_branch always written — its dataclass default "main"
    # is meaningful to operators reading the file; being explicit is
    # cheap and avoids the "where's production_branch?" confusion.
    deploy["production_branch"] = payload.deploy.production_branch
    if payload.deploy.auto_deploy is not None:
        deploy["auto_deploy"] = payload.deploy.auto_deploy
    if payload.deploy.custom_domains:
        deploy["custom_domains"] = list(payload.deploy.custom_domains)
    out["deploy"] = deploy

    if payload.hosting is not None:
        out["hosting"] = _serialize_hosting(payload.hosting)

    if payload.backend is not None:
        out["backend"] = {
            "db": payload.backend.db,
            "framework": payload.backend.framework,
            "hosting": payload.backend.hosting,
        }

    if payload.notes is not None:
        out["notes"] = {"text": payload.notes}

    return out


def _serialize_hosting(h: HostingBlock) -> dict:
    out: dict = {}
    if h.cpanel_user is not None:
        out["cpanel_user"] = h.cpanel_user
    if h.cpanel_url is not None:
        out["cpanel_url"] = h.cpanel_url
    if h.ftp_host is not None:
        out["ftp_host"] = h.ftp_host
    if h.ftp_user is not None:
        out["ftp_user"] = h.ftp_user
    if h.ftp_port is not None:
        out["ftp_port"] = h.ftp_port
    if h.public_html_path is not None:
        out["public_html_path"] = h.public_html_path
    return out


def _atomic_write(target: Path, content: str) -> None:
    """Write `content` to `target` via tmpfile + rename for atomicity.

    Mirrors `apikeys._atomic_write`. Assumes `target.parent` exists.
    """
    fd, tmp = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        shutil.move(tmp, target)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---- inference from existing platform-config files ------------------


def _wrangler_platform(repo_path: Path) -> str | None:
    """CF Pages vs Workers from a wrangler config file.

    The Pages-mode signal is the `pages_build_output_dir` key — Pages
    config carries it, Workers config doesn't. Looks at
    `wrangler.jsonc` first, then `wrangler.toml`. Returns `None` if
    no wrangler file is present.

    Comment-aware enough for the fleet's actual files — text-search
    on the raw bytes. A `pages_build_output_dir` inside a JSONC
    comment is a theoretical false positive but the operator almost
    never writes such a comment.
    """
    for fname in ("wrangler.jsonc", "wrangler.toml"):
        path = repo_path / fname
        if path.is_file():
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            return (
                "cf-pages"
                if "pages_build_output_dir" in text
                else "cf-workers"
            )
    return None


def detect_platform_signals(repo_path: Path) -> dict[str, bool]:
    """Per-platform presence map from on-disk config files.

    Lets a caller differentiate "no signals" from "multiple
    signals" — the v10.A migration command surfaces the latter case
    for manual review. For the common "what platform is this?" use,
    prefer `infer_from_existing_configs()` which collapses to
    `DeployBlock | None`.

    Keys are platform values from `PLATFORM_VALUES`. Platforms
    without a canonical config file (`hostgator`, `custom`,
    `github-pages`, `none`) are omitted — those are inferrable only
    via the operator declaring intent.
    """
    wrangler_mode = _wrangler_platform(repo_path)
    return {
        "cf-pages": wrangler_mode == "cf-pages",
        "cf-workers": wrangler_mode == "cf-workers",
        "vercel": (repo_path / "vercel.json").is_file(),
        "netlify": (repo_path / "netlify.toml").is_file(),
    }


def infer_from_existing_configs(repo_path: Path) -> DeployBlock | None:
    """Best-guess `DeployBlock` from filesystem markers.

    Returns a `DeployBlock` with `platform` set when exactly one
    platform signal is detected. Returns `None` when no signals are
    found OR when multiple conflicting signals exist — the migration
    command (v10.A's later slice) uses `detect_platform_signals()`
    to differentiate those two cases.

    All other `DeployBlock` fields stay at their defaults; the
    caller fills `account` / `custom_domains` / etc. interactively
    or from the operator profile.
    """
    signals = detect_platform_signals(repo_path)
    present = [p for p, found in signals.items() if found]
    if len(present) != 1:
        return None
    return DeployBlock(platform=present[0])
