"""Content-pipeline category checks (CHECK_130–CHECK_137) — the
hybridautopart.com pattern: a `seo/` subdirectory under the project
root with its own Python tooling for content generation.

The pattern groups together: pyproject.toml + uv.lock for the SEO
worker, a CLAUDE.md for orientation, a SEO_PIPELINE_PROMPT.md describing
the generation flow, a content-plan JSON (typically `topics.json`), a
Makefile.pipeline that wires the steps together, and a tests/ dir.

All checks in this category auto-skip on projects without a `seo/`
directory at root — most sites don't run content pipelines, and we
don't want to noise the catalog output with N "missing" failures on
every web project.
"""
from __future__ import annotations

from pathlib import Path


def _is_content_project(repo_path: str) -> bool:
    """A project is a content-pipeline project iff it has a `seo/`
    subdirectory at root. The directory presence is the gate; CHECK_130
    formalizes this as the catalog signal."""
    return (Path(repo_path) / "seo").is_dir()
