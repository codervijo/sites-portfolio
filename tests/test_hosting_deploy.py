"""Tests for v11.N — UAPI file-upload deploy for hostgator/custom.

Covers:
  * UAPI helpers (`_hg_upload_file`, `_hg_mkdir`, `_hg_rename`,
    `_hg_delete_dir`) and the local-FS walker (`_walk_deploy_source`).
  * The `deploy_hg_files` orchestrator — dry-run vs apply paths,
    WP-skip, missing-source, swap rollback.

Mocking pattern mirrors `test_hosting_hostgator.py` (`_FakeClient`)
but adds `.post()` support for multipart uploads. No real HTTP, no
real subprocess.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from portfolio.hosting import (
    PROVIDER_HOSTGATOR,
    PROVIDER_VERCEL,
    HostingRow,
    HgDeployRow,
    _fmt_bytes,
    _hg_delete_dir,
    _hg_mkdir,
    _hg_rename,
    _hg_upload_file,
    _walk_deploy_source,
    deploy_hg_files,
)
from portfolio.lamill_toml import (
    DeployBlock,
    HostingBlock,
    LamillToml,
)


# ---- _FakeClient with GET + POST support --------------------------


class _FakeResponse:
    def __init__(self, status_code: int, body: Any):
        self.status_code = status_code
        self._body = body

    def json(self) -> Any:
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _FakeClient:
    """Endpoint-keyed dispatcher for both GET (mkdir/rename/remove)
    and POST (upload_files). Records every call for assertions."""

    def __init__(self, endpoint_responses: dict[str, dict]):
        self.responses = dict(endpoint_responses)
        self.calls: list[dict] = []

    def _dispatch(self, method: str, url: str, **kw) -> _FakeResponse:
        self.calls.append({
            "method": method,
            "url": url,
            "params": kw.get("params"),
            "data": kw.get("data"),
            "files_keys": list((kw.get("files") or {}).keys()),
            "headers": kw.get("headers"),
        })
        for key, spec in self.responses.items():
            if key in url:
                return _FakeResponse(spec["status"], spec.get("body", {}))
        raise AssertionError(f"No fake response for URL: {url}")

    def get(self, url: str, **kw) -> _FakeResponse:
        return self._dispatch("GET", url, **kw)

    def post(self, url: str, **kw) -> _FakeResponse:
        return self._dispatch("POST", url, **kw)

    def close(self) -> None:
        pass


def _ok(data: Any = None) -> dict:
    return {"status": 1, "errors": [], "messages": [], "data": data}


def _err(errs: list[str]) -> dict:
    return {"status": 0, "errors": errs, "messages": [], "data": None}


def _build_hg_row(
    *, domain: str = "iotnews.today",
    account: str = "gator4216",
    install_path: str = "/home4/foundervijo/public_html/iotnews.today",
    wp_version: str | None = None,
) -> HostingRow:
    return HostingRow(
        domain=domain,
        provider=PROVIDER_HOSTGATOR,
        hg_account_id=account,
        install_path=install_path,
        wp_version=wp_version,
    )


def _build_lamill(
    *,
    platform: str = "hostgator",
    account: str = "gator4216",
    public_html_path: str = "/home4/foundervijo/public_html/iotnews.today",
    deploy_source: str = "dist/",
) -> LamillToml:
    return LamillToml(
        deploy=DeployBlock(platform=platform, account=account),
        hosting=HostingBlock(
            public_html_path=public_html_path,
            deploy_source=deploy_source,
        ),
    )


# =====================================================================
# Helper: _fmt_bytes
# =====================================================================


def test_fmt_bytes_under_1k_renders_bytes():
    assert _fmt_bytes(0) == "0 B"
    assert _fmt_bytes(512) == "512 B"


def test_fmt_bytes_kilobytes_one_decimal():
    assert _fmt_bytes(1536) == "1.5 KB"


def test_fmt_bytes_megabytes_one_decimal():
    assert _fmt_bytes(2_500_000) == "2.4 MB"


# =====================================================================
# Helper: _walk_deploy_source
# =====================================================================


def test_walk_deploy_source_returns_relative_posix_paths(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.css").write_text("body{}")
    (tmp_path / "assets" / "img").mkdir()
    (tmp_path / "assets" / "img" / "logo.png").write_bytes(b"\x89PNG")
    files = _walk_deploy_source(tmp_path)
    rels = [r for _, r in files]
    assert "index.html" in rels
    assert "assets/main.css" in rels
    assert "assets/img/logo.png" in rels


def test_walk_deploy_source_skips_directories(tmp_path):
    (tmp_path / "empty-dir").mkdir()
    (tmp_path / "f.txt").write_text("x")
    files = _walk_deploy_source(tmp_path)
    assert [r for _, r in files] == ["f.txt"]


def test_walk_deploy_source_returns_sorted(tmp_path):
    for n in ("z.txt", "a.txt", "m.txt"):
        (tmp_path / n).write_text("x")
    files = _walk_deploy_source(tmp_path)
    assert [r for _, r in files] == ["a.txt", "m.txt", "z.txt"]


# =====================================================================
# UAPI helpers
# =====================================================================


def test_hg_mkdir_calls_fileman_mkdir(tmp_path):
    client = _FakeClient({"Fileman/mkdir": {"status": 200, "body": _ok()}})
    err, is_auth = _hg_mkdir(
        client, "tok", "gator4216", "foundervijo",
        parent="/home4/foundervijo/public_html",
        name="iotnews.today.next",
    )
    assert err is None
    assert is_auth is False
    assert client.calls[0]["params"] == {
        "path": "/home4/foundervijo/public_html",
        "name": "iotnews.today.next",
    }


def test_hg_mkdir_returns_error_on_uapi_status_zero():
    client = _FakeClient({
        "Fileman/mkdir": {
            "status": 200, "body": _err(["File exists"]),
        }
    })
    err, _ = _hg_mkdir(
        client, "tok", "gator4216", "foundervijo",
        parent="/x", name="y",
    )
    assert err is not None
    assert "exists" in err.lower()


def test_hg_rename_calls_fileman_rename():
    client = _FakeClient({"Fileman/rename": {"status": 200, "body": _ok()}})
    err, _ = _hg_rename(
        client, "tok", "gator4216", "foundervijo",
        directory="/home4/foundervijo/public_html",
        oldname="iotnews.today.next",
        newname="iotnews.today",
    )
    assert err is None
    assert client.calls[0]["params"] == {
        "directory": "/home4/foundervijo/public_html",
        "oldname": "iotnews.today.next",
        "newname": "iotnews.today",
    }


def test_hg_delete_dir_calls_remove_files():
    client = _FakeClient({
        "Fileman/remove_files": {"status": 200, "body": _ok()},
    })
    err, _ = _hg_delete_dir(
        client, "tok", "gator4216", "foundervijo",
        path="/home4/foundervijo/public_html/iotnews.today.prev",
    )
    assert err is None
    assert client.calls[0]["params"] == {
        "file": "/home4/foundervijo/public_html/iotnews.today.prev",
    }


def test_hg_upload_file_posts_multipart(tmp_path):
    f = tmp_path / "index.html"
    f.write_text("<!doctype html>hello")
    client = _FakeClient({
        "Fileman/upload_files": {"status": 200, "body": _ok()},
    })
    err, is_auth = _hg_upload_file(
        client, "tok", "gator4216", "foundervijo",
        remote_dir="/home4/foundervijo/public_html/iotnews.today.next",
        local_path=f,
    )
    assert err is None
    assert is_auth is False
    call = client.calls[0]
    assert call["method"] == "POST"
    assert call["data"] == {
        "dir": "/home4/foundervijo/public_html/iotnews.today.next",
    }
    assert call["files_keys"] == ["file-1"]


def test_hg_upload_file_401_returns_auth_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    client = _FakeClient({
        "Fileman/upload_files": {"status": 401, "body": {}},
    })
    err, is_auth = _hg_upload_file(
        client, "tok", "gator4216", "foundervijo",
        remote_dir="/x", local_path=f,
    )
    assert is_auth is True
    assert "401" in err


def test_hg_upload_file_500_returns_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    client = _FakeClient({
        "Fileman/upload_files": {"status": 500, "body": {}},
    })
    err, is_auth = _hg_upload_file(
        client, "tok", "gator4216", "foundervijo",
        remote_dir="/x", local_path=f,
    )
    assert is_auth is False
    assert "500" in err


def test_hg_upload_file_uapi_status_zero_returns_error(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    client = _FakeClient({
        "Fileman/upload_files": {
            "status": 200, "body": _err(["Permission denied"]),
        },
    })
    err, _ = _hg_upload_file(
        client, "tok", "gator4216", "foundervijo",
        remote_dir="/x", local_path=f,
    )
    assert err is not None
    assert "Permission denied" in err


# =====================================================================
# deploy_hg_files — guard paths
# =====================================================================


def test_deploy_wrong_provider_returns_failed(tmp_path):
    row = HostingRow(domain="x.com", provider=PROVIDER_VERCEL)
    lt = _build_lamill()
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True,
    )
    assert out.action == "failed"
    assert "only handles" in out.error


def test_deploy_wp_site_skipped_with_clear_notes(tmp_path):
    row = _build_hg_row(wp_version="6.7.1")
    lt = _build_lamill()
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True,
    )
    assert out.action == "skipped_wp"
    assert "WordPress" in out.notes
    assert "6.7.1" in out.notes


def test_deploy_missing_hosting_block_skipped(tmp_path):
    row = _build_hg_row()
    lt = LamillToml(
        deploy=DeployBlock(platform="hostgator", account="gator4216"),
        hosting=None,
    )
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True,
    )
    assert out.action == "skipped_no_path"


def test_deploy_missing_source_dir_skipped(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    # No sites/<domain>/dist/ created.
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True,
    )
    assert out.action == "skipped_no_source"
    assert "missing" in out.notes


def test_deploy_empty_source_dir_skipped(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    (tmp_path / "iotnews.today" / "dist").mkdir(parents=True)
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True,
    )
    assert out.action == "skipped_no_source"
    assert "no files" in out.notes


# =====================================================================
# deploy_hg_files — dry-run path
# =====================================================================


def _seed_dist(tmp_path: Path, domain: str = "iotnews.today") -> Path:
    dist = tmp_path / domain / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html>")
    (dist / "robots.txt").write_text("User-agent: *\n")
    (dist / "assets").mkdir()
    (dist / "assets" / "main.css").write_text("body{margin:0}")
    return dist


def test_deploy_dry_run_returns_would_deploy_with_counts(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _FakeClient({})  # no UAPI calls expected
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True, client=client,
    )
    assert out.action == "would_deploy"
    assert out.file_count == 3
    assert out.total_bytes > 0
    assert client.calls == []  # no remote ops


def test_deploy_dry_run_includes_target_in_notes(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=True, client=_FakeClient({}),
    )
    assert "iotnews.today.next" in out.notes


# =====================================================================
# deploy_hg_files — apply path
# =====================================================================


def _wire_happy_apply_client(*, prev_exists: bool = True) -> _FakeClient:
    """Pre-load a client that succeeds on every UAPI call. If
    `prev_exists` is False, the first rename (current → .prev) fails
    cleanly to model the first-time-deploy case."""
    return _FakeClient({
        "Fileman/mkdir": {"status": 200, "body": _ok()},
        "Fileman/upload_files": {"status": 200, "body": _ok()},
        "Fileman/rename": {
            "status": 200,
            "body": _ok() if prev_exists else _err(["No such file"]),
        },
        "Fileman/remove_files": {"status": 200, "body": _ok()},
    })


def test_deploy_apply_uploads_files_then_renames(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client()
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    # Note: the all-rename-200 fixture has rename succeed, so the
    # second rename (.next → current) also "succeeds" — that's the
    # one whose success determines `deployed` action.
    assert out.action == "deployed"
    assert out.file_count == 3

    # At minimum: 1 mkdir for .next + 1 mkdir for assets subdir +
    # 3 uploads + 2 renames + 1 remove. Some calls may be more
    # (mkdir is idempotent in our fixture).
    methods = [c["method"] for c in client.calls]
    assert methods.count("POST") == 3  # 3 file uploads
    # 2 successful renames + 1 remove = 3 GETs minimum after the
    # mkdirs. mkdirs are also GETs in our fixture.
    assert "GET" in methods


def test_deploy_apply_uploads_to_next_dir_not_current(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client()
    deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    # Every upload's `dir` form field must be inside the .next dir.
    uploads = [c for c in client.calls if c["method"] == "POST"]
    for c in uploads:
        assert c["data"]["dir"].endswith("iotnews.today.next") or (
            ".next/" in c["data"]["dir"]
        )


def test_deploy_apply_renames_next_to_current(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client()
    deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    renames = [
        c["params"] for c in client.calls
        if c["method"] == "GET" and c["params"]
        and "oldname" in c["params"]
    ]
    # Look for the swap call: oldname=.next, newname=current
    swap = [
        p for p in renames
        if p["oldname"] == "iotnews.today.next"
        and p["newname"] == "iotnews.today"
    ]
    assert len(swap) == 1


def test_deploy_apply_first_time_skips_prev_delete(tmp_path):
    """If current dir doesn't exist (first-time deploy), the first
    rename fails cleanly — we should NOT then issue a delete."""
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client(prev_exists=False)
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    # All renames return failure in this fixture (No such file),
    # which means the swap also "fails" — so action=failed and we
    # rolled back. This exercises the rollback branch. The
    # invariant we DO want: no remove_files calls in this flow
    # (no .prev to delete because none was created).
    removes = [
        c for c in client.calls
        if c["method"] == "GET"
        and "remove_files" in c["url"]
    ]
    assert removes == []


def test_deploy_apply_upload_failure_returns_failed(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _FakeClient({
        "Fileman/mkdir": {"status": 200, "body": _ok()},
        "Fileman/upload_files": {
            "status": 200, "body": _err(["disk quota exceeded"]),
        },
        "Fileman/rename": {"status": 200, "body": _ok()},
        "Fileman/remove_files": {"status": 200, "body": _ok()},
    })
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    assert out.action == "failed"
    assert "upload" in out.error
    assert "disk quota" in out.error
    # Critical safety check: no rename happened (we bailed before swap).
    renames = [
        c for c in client.calls
        if c["method"] == "GET" and "rename" in c["url"]
    ]
    assert renames == []


def test_deploy_apply_mkdir_failure_returns_failed(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _FakeClient({
        "Fileman/mkdir": {
            "status": 200, "body": _err(["Permission denied"]),
        },
    })
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    assert out.action == "failed"
    assert "mkdir" in out.error


def test_deploy_apply_swap_failure_rolls_back_prev(tmp_path):
    """If the .next → current swap fails after .prev was created,
    we must rename .prev back to current so prod stays up."""
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)

    # Track rename calls in order: 1st succeeds (current → .prev),
    # 2nd fails (.next → current), 3rd should be rollback
    # (.prev → current).
    call_count = {"rename": 0}

    class _SwapFailClient(_FakeClient):
        def __init__(self):
            super().__init__({
                "Fileman/mkdir": {"status": 200, "body": _ok()},
                "Fileman/upload_files": {"status": 200, "body": _ok()},
            })

        def _dispatch(self, method, url, **kw):
            if "rename" in url:
                self.calls.append({
                    "method": method, "url": url,
                    "params": kw.get("params"),
                    "data": kw.get("data"),
                    "files_keys": list((kw.get("files") or {}).keys()),
                    "headers": kw.get("headers"),
                })
                call_count["rename"] += 1
                if call_count["rename"] == 2:
                    return _FakeResponse(200, _err(["swap failed"]))
                return _FakeResponse(200, _ok())
            return super()._dispatch(method, url, **kw)

    client = _SwapFailClient()
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    assert out.action == "failed"
    assert "swap" in out.error
    # Verify the rollback happened: 3rd rename call rewinds .prev.
    rename_calls = [
        c for c in client.calls if "rename" in c.get("url", "")
    ]
    assert len(rename_calls) == 3
    rollback = rename_calls[2]["params"]
    assert rollback["oldname"] == "iotnews.today.prev"
    assert rollback["newname"] == "iotnews.today"


def test_deploy_apply_calls_remove_files_after_successful_swap(
    tmp_path,
):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client()
    deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    removes = [
        c for c in client.calls
        if c["method"] == "GET" and "remove_files" in c["url"]
    ]
    assert len(removes) == 1
    assert removes[0]["params"]["file"].endswith("iotnews.today.prev")


def test_deploy_apply_creates_subdir_for_nested_files(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill()
    _seed_dist(tmp_path)
    client = _wire_happy_apply_client()
    deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    # Look for a mkdir that creates the "assets" subdir.
    mkdir_calls = [
        c["params"] for c in client.calls
        if "mkdir" in c.get("url", "") and c["params"]
    ]
    assets_mkdir = [
        p for p in mkdir_calls
        if p.get("name") == "assets"
        and p.get("path", "").endswith("iotnews.today.next")
    ]
    assert len(assets_mkdir) == 1


def test_deploy_apply_uses_configured_deploy_source(tmp_path):
    row = _build_hg_row()
    lt = _build_lamill(deploy_source="public/")
    (tmp_path / "iotnews.today" / "public").mkdir(parents=True)
    (tmp_path / "iotnews.today" / "public" / "index.php").write_text(
        "<?php echo 'hi';"
    )
    client = _wire_happy_apply_client()
    out = deploy_hg_files(
        row, lamill_toml=lt, token="tok", cpanel_user="foundervijo",
        sites_root=tmp_path, dry_run=False, client=client,
    )
    assert out.action == "deployed"
    assert out.file_count == 1
