# 0017 — Additive-optional `lamill.toml` tables stay on schema = `lamill-toml-v1`

- **Status:** Accepted
- **Date:** 2026-05-29

## Context

`lamill.toml` carries a top-level `schema = "lamill-toml-v1"` string —
the format version the loader uses to recognize the file. v27 adds two
new optional tables (`[[todo]]` for per-site work tracking and `[stack]`
for the frontend-stack declaration) and future tiers will almost
certainly want more (analytics policies, deploy hooks, env scopes, …).
The same question recurs each time: **does adding a new optional table
bump the schema string?**

The forces in play:

- **The fleet has ~30 `lamill.toml` files.** Bumping the schema means a
  fleetwide migration sweep for every additive change — write the v2
  file shape, decide how the loader treats v1 files (warn? auto-
  upgrade? hard-require v2?), update every site, ship a migration
  command. This treadmill is the implicit cost of any version bump.
- **The loader is already permissive.** `_parse_doc` reads each section
  via `doc.get(name)`, so unknown tables are silently ignored on read.
  An optional table is backward-compatible in **both** directions: a v1
  file (no new table) parses fine in the new code, and a file with the
  new table parses fine in an old reader (it just doesn't see the
  section).
- **The schema string still has real work to do.** It exists to gate
  *breaking* changes — renamed/removed fields, changed types, changed
  enum semantics, newly-required tables. As long as `lamill-toml-v1`
  covers both files-with-tables and files-without, the string carries
  slightly less precise information, but the precise version of any
  given optional table's schema isn't needed for parsing (the loader
  only needs to know whether the section can appear).
- **A companion invariant already exists.** `docs/CLAUDE.md § 🔒
  lamill.toml additive-optional invariant` (also accepted 2026-05-29)
  requires that no parser or consumer treats a missing optional table
  as an error. As long as that invariant holds, a v1 reader on a file
  with new tables is safe.

## Decision

**Adding an optional table to `lamill.toml` does NOT bump the schema
string.** `schema = "lamill-toml-v1"` covers every shape the file can
take so long as each new section is:

1. **Additive** — does not rename, remove, or change the meaning of
   any existing field.
2. **Optional** — absent is the baseline state; the loader defaults to
   the empty / `None` form when the section isn't present.
3. **Compatible with the `lamill.toml` additive-optional invariant** —
   no consumer requires it; consumers fall back when it's missing;
   drift checks skip quietly with no declaration to compare; test
   plans cover the "neither present" baseline.

`schema = "lamill-toml-v2"` is reserved for genuinely breaking changes:
renames, type changes, removed fields, changed enum semantics, or
mandatory tables.

## Consequences

**Positive:**

- No fleetwide migration sweep for additive changes. v27.C backfills
  `[stack]` site-by-site as policy, not as a parser requirement; sites
  without `[[todo]]` keep working forever.
- Old `lamill` binaries continue to read files with new optional
  tables (the unknown tables are ignored, not rejected). Forward and
  backward compatibility for free.
- New tables get added without the ceremony of a version-bump
  migration command. Lower friction for each new lamill feature that
  wants a `lamill.toml` corner.

**Negative:**

- The schema string is less informative — `lamill-toml-v1` doesn't tell
  a reader which optional tables it might find. Consumers must always
  use `doc.get()` defensively and never assume a section is present.
  (This is enforced by the additive-optional invariant.)
- Future readers can't quickly assert "this file has been migrated to
  the new shape" — they have to check for the table directly. In
  practice this hasn't been needed; each table is read on its own
  terms.
- A real breaking change someday will still need a version bump and
  the full migration ceremony. This ADR doesn't make that easier; it
  just delays the first occasion that needs it.

## References

- `docs/prd.md` § v27 — per-site todo + stack tracking in `lamill.toml`
- `docs/CLAUDE.md` § Locked target shapes § 🔒 `lamill.toml`
  additive-optional invariant
- `docs/CLAUDE.md` § Locked target shapes § 🔒 `lamill.toml` `[[todo]]`
  shape · 🔒 `lamill.toml` `[stack]` shape
- `src/portfolio/lamill_toml.py` — loader (`_parse_doc`)
