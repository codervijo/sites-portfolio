# handoff.md — session snapshot (never commit)

Session-bridging notes so the next session picks up cleanly. Not a canonical
doc; never `git add` this file (per `feedback_handoff_never_commit`).

**As of:** 2026-06-15 · tip commit `554bac1` (all pushed to `origin/main`) ·
working tree clean apart from this file + `for-future-projects.md` (both
intentionally untracked).

---

## What shipped this session

1. **CF fleet consolidated onto Pages.** The fleet was *mixed + mislabeled*:
   `lamill.toml` said `cf-pages` for 8 sites that were actually **Workers**
   (`agesdk`, `cricketfansite`, `disclosur`, `donready`, `dropaudit`,
   `isitholiday`, `kwizicle`, `voltloop`), plus airsucks (TanStack, a real
   Worker). All migrated Worker→Pages (build on `pages.dev` → verify → domain
   cutover preserving the GSC TXT → decommission Worker). **No Workers left;
   `lamill.toml platform=cf-pages` is now accurate everywhere.**
   - **Pages project names use TWO conventions:** old sites = `_project_name`
     slug (`scopeguard`); migrated sites = dashed domain (`airsucks-com`,
     `agesdk-dev`). `CHECK_145`'s resolver tries both.

2. **Deploy-health check (the original ask: "lamill should notice CF build
   failures").** Rewrote `CHECK_145 deploy-fresh` to read the **CF Pages
   deployments API** (build status + deployed commit vs `origin/<branch>`) —
   the old version.json convention was *never rolled out* (0/39 served it), so
   144/145/146 were dead. New `cloudflare.latest_pages_deployment`. (v41.B)
   - `settings gsc submit-sitemap --site <d> [--force]` command added (v41.A).

3. **Delegate fully hardened** (root of the airsucks 5-hour-burn diagnosis):
   - `_detect_build` → **pnpm default** (never npm — the actual root cause).
   - **v37.E** baseline-build gate — build pristine tree before the agent;
     bail in ~2 min if the env doesn't build.
   - **v37.F** prompt upgrade — build contract + anti-thrash + injects CLAUDE.md
     + delegate-notes learnings.
   - **v37.H** parse the agent's own build outcomes from its stream (live
     `⚠ build failing ×N` + names it in the result).
   - **v37.G** circuit-breaker — `Bounds.build_fail_limit` (default 3) → bail
     `build-stuck` on N consecutive build failures.

4. **Sitemap parser namespace fix** — TanStack emits `https://` sitemap
   namespace; lamill's strict `{http://}` parsers read 0 URLs. Switched both
   (`_live.py`, `gsc_recrawl.py`) to the `{*}` wildcard.

5. **4-bug parallel sweep** (`3da6dad`): young-site grading softened, retired
   obsolete CHECK_144/146, fleet dashboard truncation fixed, fleet seo/domains
   count reconciled (scope-difference, surfaced in footer).

---

## Parked / next up

- **`docs/bugs.md` open bugs** — notably:
  - **3 duplicate sitemap parsers** (`_live.py`, `gsc_recrawl.py`,
    `indexnow.py` regex) — consolidate to one. *Own dedicated pass* (touches
    ~13 SEO consumers; don't parallelize with other SEO bugs).
  - 2 older `project seo` young-site GSC-diagnostics entries (2026-06-13).
  - older fleet/bootstrap/HG-walker bugs.
- **Eyeball `fleet dashboard`** — the truncation fix is unit-tested + agent-
  confirmed at COLUMNS=100, but my own live run timed out on the 47-site probe.
- **Optional:** hand-off-to-OSS on `build-stuck` (v37.G follow-up).

## Gotchas / context to keep

- **pnpm everywhere** — operator has no npm projects; npm is never correct.
- **CF Pages doesn't auto-build on project create** — must call
  `trigger_pages_deployment` after create.
- **Workers Builds CI API is 403** for the token; the Pages *deployments* API
  works (what CHECK_145 uses).
- **Pre-existing test failure:** `test_check_143_deploy_drift::
  test_fail_when_declared_vercel_but_actual_is_wordpress` — known/unrelated,
  long-standing. "Suite green" means "only this fails."
- **airsucks `lamill.toml`** was edited by the operator/linter (added `[stack]`
  + `[content]`) — intentional, don't revert.
- Commit/doc naming: strict two-level `vN.X`. Never auto-commit/push without an
  explicit ask. `docs/handoff.md` + `for-future-projects.md` never committed.
