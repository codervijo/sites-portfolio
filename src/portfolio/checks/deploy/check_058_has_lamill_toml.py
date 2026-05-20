"""CHECK_058 — `lamill.toml` exists at the project root.

First of the v10.E lamill.toml-conformance trio (058 has-lamill-toml /
059 lamill-toml-valid / 143 deploy-drift). v10.A-D shipped the
declaration mechanism (schema, CLI, auto-write, fleet sweep); v10.E
makes "is there one?" a fleet-visible conformance signal.

Pass / fail / warn:
  - pass: `<repo>/lamill.toml` exists
  - fail: no file
  - warn: archived / tombstoned site (skip — same convention as other
          per-project checks)

The 5 NO_GIT sibling repos (iotnews / linkedcsi / streamsgalaxy /
thoralox / whizgraphs as of 2026-05-18) will fail this check until
v6.F runs — accepted baseline, not a tool bug.
"""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from ...lamill_toml import LAMILL_TOML_FILENAME

CHECK_ID = "CHECK_058"
CHECK_NAME = "has-lamill-toml"
CATEGORY = "deploy"
SEVERITY = "error"
DESCRIPTION = (
    "Every applicable sibling repo declares its deploy target via a "
    "`lamill.toml` at the project root."
)


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path).resolve()
    try:
        from ...fleet_repos import _archived_reason
        reason = _archived_reason(base)
        if reason is not None:
            return CheckResult(status="warn",
                               message=f"archived ({reason}) — skipped")
    except Exception:
        pass

    if (base / LAMILL_TOML_FILENAME).is_file():
        return CheckResult(status="pass",
                           message=f"{LAMILL_TOML_FILENAME} present")
    return CheckResult(
        status="fail",
        message=(
            f"missing {LAMILL_TOML_FILENAME} — declare deploy target via "
            f"`lamill settings deploy set {base.name} <platform>` "
            f"(or `lamill fleet repos --add-deploy-declarations --apply` "
            f"for unambiguous bulk migration)"
        ),
    )
