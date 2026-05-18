# bugs.md — sites/portfolio/

Bug journal for `portfolio` / `lamill`. Operator-driven intake;
Claude-maintained entries.

## Workflow

1. **Operator drops a brief report in chat** — a sentence or two, no
   structure required. Examples: "found a bug: X command shows N
   but Y shows M", "this thing is slow", "the help text for `foo`
   is wrong."
2. **Claude writes up the structured entry here.** Investigates
   enough to fill Repro / Expected / Actual / Where / Severity /
   Notes. Asks the operator if anything is ambiguous, but doesn't
   block on a perfect repro — captures what's known and proceeds.
3. **The current shippable phase keeps going.** Bug work doesn't
   interrupt v10.A / v10.B / etc. unless the operator escalates
   ("fix this first" / `blocker` severity).
4. **After a phase (`vN.X`) ships,** Claude reviews `## Open
   bugs` and picks up entries before starting the next phase —
   in this order:
   - any `blocker` severity (always first)
   - bugs whose fix overlaps with the just-shipped or next phase
   - everything else by date (oldest first)
5. **Fix → cut entry from `## Open bugs` → append to `## Fixed
   bugs` with the `**Fixed in**` commit SHA.** Don't delete fixed
   entries; they're the project's known-issue archive.

This file is *not* one of the five canonical doc surfaces (prd.md /
architecture.md / shipping-history.md / decisions/ / CLAUDE.md).
It's a maintained journal — same shape relationship as
`docs/Prompts.md`.

## Entry shape

One bug per dated H3 entry. Heading:

```
### YYYY-MM-DD — <one-line headline>
```

Add a sequence suffix on same-day collisions:
`### 2026-05-18 — second-bug` / `### 2026-05-18 — third-bug`.

Body fields, in this order (skip what isn't useful):

- **Repro** — exact command(s) that trigger it.
- **Expected** — what should happen (one line).
- **Actual** — what does happen, with verbatim error output.
- **Where (guess)** — file / module / area Claude suspects.
- **Severity** — `blocker` / `major` / `minor` / `cosmetic`.
  Default: `minor`.
- **Notes** — anything else (related commits, workaround,
  half-investigated hypothesis).

On fix, append a `**Fixed in**` line referencing the commit SHA +
phase:

```
**Fixed in** — `4395e1d` (v10.A — schema + parser)
```

`**Wontfix** — <reason>` or `**Dup of** YYYY-MM-DD — <headline>`
when applicable. Don't delete.

## Open bugs

### 2026-05-18 — `fleet seo --refresh` and `fleet domains` show different domain counts

**Repro**
    uv run lamill fleet seo --refresh
    uv run lamill fleet domains

**Expected**
The two commands should show consistent fleet sizes, or — if the
scope differs — surface that in the output footer so the operator
can see *why* the counts diverge.

**Actual**
`fleet seo --refresh` shows 22 domains; `fleet domains` shows 36.
No visible explanation for the 14-domain gap.

**Where (guess)**
`src/portfolio/cli.py:5324` (`fleet_domains`) and `cli.py:5334`
(`fleet_seo`). Both default `--only wip` but `fleet_seo` calls
through `check_seo` which additionally filters to
`live-site`/`forwarder` classification (the SEO probe skips
parked / dead / archived sites by design). The filter is silent
— the operator sees only the final count.

**Severity**
minor — likely an intentional scope filter, but the silent
discrepancy is a usability gap.

**Notes**
Two fix paths worth considering when this is picked up:
(a) Show a footer note when SEO is filtering: "Showing N of M
WIP domains (excluded: K parked / J dead / I archived)."
(b) Add an explicit `--scope` flag to both commands so the
operator can match scopes when comparing counts.

Either path is small (≤30 min). Defer until after v10.A-D ships,
or fold in alongside v11.A's `fleet hosting` (which has the same
"WIP vs live-site" filter question per resolution 11.B).

## Fixed bugs

(none yet)
