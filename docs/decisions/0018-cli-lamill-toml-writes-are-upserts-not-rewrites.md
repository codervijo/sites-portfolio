# 0018 — CLI `lamill.toml` mutations are surgical upserts, not full-file rewrites

- **Status:** Accepted
- **Date:** 2026-05-30

## Context

`lamill.toml` is per-site, git-tracked, **human-authored** config. As of
the 2026-05-30 fleet migration every site's file carries a hand-authored
`[content]` block (rankmill's content-identity source of truth) with
inline comment guidance, plus a header pointer comment — none of which
lamill's parser models.

The existing writer, `lamill_toml.write()`, is a **full-file rewrite**:
it serializes a `LamillToml` struct via `to_dict() → tomli_w.dumps()` and
overwrites the file. `to_dict()` only emits the tables it knows
(`schema/deploy/stack/hosting/backend/analytics/notes/todo`). Proven on
2026-05-30: a `load() → to_dict()` round-trip on a real file **drops the
`[content]` block entirely**, and `tomli_w` strips all comments and
reorders tables.

v27.G/H add CLI verbs that mutate `[[todo]]` (`project todos --add /
--done / --reopen`). If those verbs went through `write()`, every todo
edit would silently erase the operator's `[content]` block and comments
on that site. The same latent hazard already exists in four legacy write
paths (`settings deploy set`, the deploy pipeline ×2, `hosting`).

A storage change (e.g. SQLite) was considered and rejected: the data is
tiny per-site config that must stay git-diffable, human-editable, and
readable by a second tool (rankmill). The problem is the *write
discipline*, not the format.

## Decision

**Every CLI mutation of an existing `lamill.toml` must be a surgical
upsert that leaves the rest of the file byte-for-byte intact** —
comments, unknown tables (`[content]`, future additions), and table
ordering all preserved. Full-file rewrites via `write()` are reserved
for creating a **brand-new** file (`new bootstrap`), where there is
nothing to preserve.

Mechanism (v27.G, `lamill_toml_edit.py`): parse + validate the whole
file, mutate the target structure in memory, regenerate **only** that
region's text, and splice it back over the region's character span.
Everything outside the span is untouched. The `[[todo]]` region reuses
the canonical emitter (`lamill_toml.todo_region_text`) shared with
`write()` so formatting stays identical.

This is a **write-surface posture**, parallel to ADR-0003 (local-FS
write surfaces) and ADR-0015 (deploy idempotency): future write paths
inherit the rule rather than re-deciding it.

## Consequences

- **`[content]` and comments survive todo edits.** v27.H verbs use the
  upsert helper; `[content]` is preserved (verified by tests).
- **Freeform comments *inside* a regenerated region are not preserved** —
  the canonical `[[todo]]` header is regenerated (matches the documented
  v27.B behavior). Only the mutated region loses freeform comments;
  everything outside it is byte-identical.
- **The four legacy rewrite paths remain a known gap.** They still call
  `write()` and would clobber `[content]` on a content-bearing site.
  Tracked in `docs/bugs.md` (2026-05-30 entry) and queued as **v27.J** —
  migrate them to the upsert helper.
- **`write()` keeps a narrow, documented role:** brand-new files only;
  its docstring now warns it is a rewrite that drops unknown tables.
- **The upsert primitive generalizes.** Today it covers the `[[todo]]`
  array-of-tables; the same locate-span → regenerate → splice shape
  extends to `[stack]` / `[deploy]`-key upserts when v27.J lands.

## See also

- `docs/bugs.md` — 2026-05-30 legacy-rewrite-paths entry (v27.J)
- ADR-0017 — additive-optional tables (why `[content]` parses cleanly as
  an unknown table)
- `docs/CLAUDE.md § 🔒 lamill.toml additive-optional invariant`
- `src/portfolio/lamill_toml_edit.py`, `src/portfolio/lamill_toml.py`
