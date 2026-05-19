# 0011 — Remote-host writes as a separate write-surface category

- **Status:** Accepted
- **Date:** 2026-05-19

## Context

ADR-0003 ("Two write surfaces only") caps local-FS write surfaces
into sibling `sites/<domain>/` project directories at two:
`new bootstrap` and `project fix`. The cap exists so the operator
(and any agent helping them) has a tight audit story for changes to
sibling repos — any unexpected mutation traces to one of those two
verbs.

v11.N introduces a new verb behavior: `new deploy <domain>` for
`platform=hostgator` and `platform=custom` pushes built artifacts
from `sites/<domain>/<deploy_source>` to a remote `public_html_path`
via cPanel UAPI (`Fileman/upload_file` + `Fileman/rename` for the
stage-then-rename atomicity dance). This **does not write to any
sibling project directory** — the project dir is read-only on this
path; only the remote host receives bytes.

Question: does v11.N count against ADR-0003's cap of two? If yes,
ADR-0003 needs supersession to three. If no, what constraints does
the remote-write category carry on its own?

(The original PRD spec referred to "ADR-0009" as the gate — that
slot is already taken by `0009-makefile-forwards-to-central-builder`,
so this ADR takes the next free number.)

## Decision

ADR-0003 stays in force, unchanged. Its scope is and remains
**local-FS writes into sibling project directories**.

This ADR establishes a second, **separate** category:
**remote-host writes** — operations that push bytes to an external
host (cPanel UAPI, future SSH/SFTP, future hosted-platform APIs). The
two categories are independent: counting v11.N against ADR-0003 would
conflate two genuinely different risk surfaces (local FS audit vs.
remote-host atomicity).

**Permitted remote-host writes (as of 2026-05-19):**

1. `new deploy <domain>` when `platform ∈ {hostgator, custom}` —
   pushes the configured `[hosting].deploy_source` payload to the
   declared `[hosting].public_html_path` on the cPanel-managed host.
   See v11.N for the stage-then-rename implementation.

**Constraints on every remote-host write surface** (applied via code
review, not the conformance catalog):

- **Idempotent.** Same input must produce the same remote end-state
  on a re-run.
- **Dry-run default.** Each verb defaults to dry-run; an explicit
  `--apply` flag is required to actually send bytes. Mirrors the
  v6.D / v10.C convention for local writes.
- **Per-site allowlist.** Each invocation acts on exactly one site
  declared via `lamill.toml`. No fleet-wide remote writes — operator
  drives them one domain at a time, with the declaration as the
  consent record.
- **Atomicity where the platform allows it.** For cPanel UAPI:
  stage-then-rename (upload to `<path>.next/`, rename current to
  `.prev/`, rename `.next/` to current, delete `.prev/`). Brief
  downtime window is acceptable for static sites; WP and other
  stateful content surfaces are deferred.
- **No credentials baked into the payload.** Auth lives in
  `portfolio.env` (per `settings apikeys`), never embedded in
  `lamill.toml` or the uploaded files.

## Consequences

**Positive.**
- ADR-0003's tight local-FS write boundary stays intact; the audit
  story for sibling project dirs is unchanged ("any unexpected
  change traces to `new bootstrap` or `project fix`").
- Future remote write surfaces (a hypothetical S3 push, a GitHub
  API push) inherit this ADR's constraint list — no re-litigation
  per addition.
- The cPanel UAPI stage-then-rename pattern is documented as the
  reference atomicity story for shared-hosting writes; new providers
  can either match it or argue for a different shape via ADR
  supersession.

**Negative.**
- Two categories of write surface to keep straight. CLAUDE.md and
  AI_AGENTS.md must mention both (local-FS via ADR-0003;
  remote-host via this ADR) so future agents don't conflate them.
- A "deploy everything that's changed" fleet command would need
  explicit ADR amendment — the per-site-allowlist constraint
  forbids it at the v11.N tier.
- The dry-run default + explicit `--apply` adds a step for the
  operator each push. Worth it for the safety posture; acknowledged
  trade-off vs. silent push-on-save.

## References

- ADR-0003 — Two write surfaces only (local-FS scope).
- `docs/prd.md` § 6 — v11 tier, resolution 11.S.
- v11.M commit (`84ca891`) — polymorphic dispatcher that this ADR
  guards on the `hostgator` / `custom` branch.
- v11.N implementation — `deploy_hg_files()` in
  `src/portfolio/hosting.py` and the UAPI helpers `_hg_upload_file`,
  `_hg_rename`, `_hg_delete_dir`.
