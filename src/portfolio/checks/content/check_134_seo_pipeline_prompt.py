"""CHECK_134 — `seo/SEO_PIPELINE_PROMPT.md` exists (codifies the generation flow)."""
from __future__ import annotations

from pathlib import Path

from ..result import CheckResult
from . import _is_content_project

CHECK_ID = "CHECK_134"
CHECK_NAME = "seo-pipeline-prompt"
CATEGORY = "content"
SEVERITY = "warn"
DESCRIPTION = (
    "seo/SEO_PIPELINE_PROMPT.md (or SEO_PIPELINE.md) exists — the prompt "
    "template that drives content-worker LLM steps."
)

# Accept either the full canonical name or the shorter SEO_PIPELINE.md
# variant some projects use.
_CANDIDATES = ("SEO_PIPELINE_PROMPT.md", "SEO_PIPELINE.md", "PIPELINE_PROMPT.md")


def run(repo_path: str) -> CheckResult:
    if not _is_content_project(repo_path):
        return CheckResult(status="warn", message="not a content-pipeline project — skipped")
    seo = Path(repo_path) / "seo"
    for name in _CANDIDATES:
        if (seo / name).is_file():
            return CheckResult(status="pass", message=f"seo/{name} present")
    return CheckResult(status="fail",
                       message="seo/SEO_PIPELINE_PROMPT.md missing")
