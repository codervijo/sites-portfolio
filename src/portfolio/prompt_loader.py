"""Prompt loader + renderer for v8.E Phase 4.

Loads standing prompts from `prompts/<name>.md` at the repo root,
substitutes `{{var}}` placeholders, and validates that nothing was
left unfilled. Used by `interpretive_pass` (P4.B.3) and `audit_pass`
(P4.C.1) to construct LLM system messages.

Per PRD §10.G: custom regex substitution rather than Jinja or
`str.format()`. No new dep; no collision with curly braces in code-
block examples inside prompts.

Per PRD §10.I: prompt filenames carry the version (`_v1`, `_v2`, ...).
Snapshots record which version produced their verdict; loader treats
the filename as the source of truth — no version field needed in
prompt content.
"""
from __future__ import annotations

import re
from pathlib import Path

from .data import ROOT

PROMPTS_DIR = ROOT / "prompts"

_PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}", re.IGNORECASE)
_DOC_H1 = re.compile(r"\A# [^\n]+\n+")


class PromptError(Exception):
    """Base class for prompt-layer errors."""


class PromptNotFoundError(PromptError):
    """No file at `prompts/<name>.md`."""


class UnfilledPlaceholderError(PromptError):
    """A `{{var}}` placeholder was not substituted before send.

    The unfilled-names list is on `.placeholders`. Surfaces the
    operator-facing names exactly as the prompt wrote them.
    """

    def __init__(self, placeholders: list[str]) -> None:
        self.placeholders = sorted(set(placeholders))
        super().__init__(
            f"Unfilled placeholders in prompt: {self.placeholders}"
        )


def load_prompt(name: str) -> str:
    """Read `prompts/<name>.md` (or `prompts/<name>` if it already ends
    in `.md`). Returns the prompt text with the documentation H1
    stripped — the `# <filename>.md` heading at the top of each
    standing prompt is for humans reading the file, not for the model.

    Raises `PromptNotFoundError` if the file is absent.
    """
    fname = name if name.endswith(".md") else f"{name}.md"
    p = PROMPTS_DIR / fname
    if not p.exists():
        raise PromptNotFoundError(f"Prompt not found: {p}")
    text = p.read_text(encoding="utf-8")
    return _DOC_H1.sub("", text, count=1)


def render_prompt(template: str, **substitutions: object) -> str:
    """Substitute `{{var}}` placeholders. Names are case-insensitive
    on input (matches `{{Foo}}` against `foo=`) but the substitution
    map is lowercased on lookup.

    Raises `UnfilledPlaceholderError` if any `{{name}}` remains after
    substitution — caller-side prevention of half-rendered prompts
    being sent to the model (PRD §4 P4a.6).

    Values are coerced to `str` via `str(v)`; the caller is responsible
    for rendering complex types (lists, dataclasses) into the text shape
    that should land in the prompt.
    """
    lowered: dict[str, str] = {
        k.lower(): str(v) for k, v in substitutions.items()
    }

    def sub(m: re.Match[str]) -> str:
        key = m.group(1).lower()
        return lowered.get(key, m.group(0))

    rendered = _PLACEHOLDER.sub(sub, template)
    leftovers = [m.group(1) for m in _PLACEHOLDER.finditer(rendered)]
    if leftovers:
        raise UnfilledPlaceholderError(leftovers)
    return rendered


def find_placeholders(template: str) -> list[str]:
    """Return the placeholder names referenced by a template, in
    document order with duplicates preserved. Used by tests and by
    callers that want to validate they're passing the right vars.
    """
    return [m.group(1) for m in _PLACEHOLDER.finditer(template)]
