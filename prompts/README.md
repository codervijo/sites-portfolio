# prompts/

Standing prompts used by `lamill new research` (v8.E Phase 4 onward).
Each prompt is a markdown file that the tool reads at runtime, fills
in operator-specific variables, and sends to an LLM.

These are **first-class artifacts** — they live at the repo root
alongside `tests/` and `docs/`, not buried in `src/`. Editing the
prompt is normal operator work, not a code change.

## Naming convention

```
<purpose>_v<N>.md
```

The version suffix is load-bearing. Snapshots written by the tool
record which prompt version produced their verdict. When a prompt
changes meaningfully, bump the version so old snapshots remain
reproducible.

**When to bump** (per `docs/prd.md` §10.I):
- New failure-mode checks → bump
- Structural instruction or output-shape changes → bump
- Typo / wording / formatting tweaks → don't bump

Operationally: when a snapshot's recorded `prompt_version` doesn't
match the current `_vN.md` on disk, its verdict is treated as stale
and can be re-rendered via `--no-cache=interpretive` or
`--no-cache=audit`.

## Substitution

Variables are referenced as `{{name}}` inside the prompt body. The
loader's render step substitutes them at call time. Any unfilled
`{{name}}` placeholder remaining after substitution is a hard error —
better to fail loudly than send a half-rendered prompt to the model.

Custom `{{var}}` regex was chosen (not Jinja, not `str.format()`) so
that prompts can contain literal `{` / `}` in example code blocks
without triggering a template-parser conflict (`docs/prd.md` §10.G).

## Files

| File | Purpose | First shipped |
|---|---|---|
| `niche_evaluation_v1.md` | Primary interpretive pass (Phase 4a) | v8.E |
| `adversarial_audit_v1.md` | Adversarial audit pass (Phase 4b) | v8.E |
