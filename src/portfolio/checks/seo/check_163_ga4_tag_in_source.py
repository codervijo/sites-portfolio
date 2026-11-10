"""CHECK_163 — the site's source loads the GA4 tag with the ID recorded in
`lamill.toml [analytics] ga4_id` (v49.C, ADR-0029).

Scans layouts, components and `index.html` (not just `index.astro`, the
CHECK_080 blind spot). The tier-1 fixer writes the committed ID, in order:

  1. Source already references the recorded ID → nothing to do.
  2. Source references a *different* real `G-` ID → manual (never overwrite).
  3. Source reads `PUBLIC_GA_ID` / `VITE_GA_ID` → wrap each read with the
     committed ID as default (`(import.meta.env.PUBLIC_GA_ID || "G-…")`);
     an env var set on the platform still overrides. If no reading file is
     a layout / app entry or imported by one, the loader isn't site-wide
     (mdburst: only tool islands) → manual.
  4. Otherwise inject per stack:
       - Astro: write `src/components/Analytics.astro` (lamill.store's
         shape) and render `<Analytics />` before `</head>` in every
         layout/page that owns a `</head>`.
       - TanStack Start / React (`.tsx`/`.jsx` owning `</head>`): gtag
         `<script>` elements before `</head>`.
       - Vite (`index.html`): gtag snippet before `</head>`.

Privacy page (v49.A (j)): where one exists and doesn't mention Google
Analytics, the fixer adds one sentence after its last paragraph. A page
that already talks about analytics some other way (e.g. "No analytics")
is left for the operator — appending would contradict it. No privacy page
→ nothing (v49 doesn't create pages).

`warn` severity; same applicability as CHECK_162.
"""
from __future__ import annotations

import re
from pathlib import Path

from portfolio.fix_helpers import FixerSpec, FixResult

from ..result import CheckResult
from .check_162_ga4_id_recorded import _SKIP_DIRS, _not_applicable, recorded_id, source_ids

CHECK_ID = "CHECK_163"
CHECK_NAME = "ga4-tag-in-source"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Site source loads gtag with the lamill.toml GA4 ID, and the privacy page "
    "(if any) mentions Google Analytics (`project fix` injects — v49.C)."
)

_ENV_READ = re.compile(r"\b((?:import\.meta\.)?env)\.(PUBLIC_GA_ID|VITE_GA_ID)\b(?!\s*(?:\|\||\?\?))")
_CODE_EXT = (".astro", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte")
_HEAD_EXT = (".astro", ".tsx", ".jsx")
_COMPONENT = Path("src/components/Analytics.astro")
_PRIVACY_PAGES = (
    "src/pages/privacy.astro", "src/pages/privacy/index.astro",
    "src/pages/privacy-policy.astro", "src/pages/privacy-policy/index.astro",
    "src/pages/privacy.md", "src/pages/privacy.mdx",
    "src/routes/privacy.tsx", "src/pages/Privacy.tsx", "src/pages/PrivacyPage.tsx",
    "src/pages/PrivacyPolicy.tsx",
)
PRIVACY_SENTENCE = (
    "This site uses Google Analytics 4 to count visits and see which pages are read. "
    "Google Analytics sets cookies and receives your browser, device and approximate "
    'location; see <a href="https://policies.google.com/technologies/partner-sites">'
    "how Google uses this data</a>."
)


def _src_files(base: Path, exts: tuple[str, ...]) -> list[Path]:
    src = base / "src"
    if not src.is_dir():
        return []
    return sorted(
        p for p in src.rglob("*")
        if p.is_file() and p.suffix in exts and not p.name.endswith(".d.ts")
        and not (_SKIP_DIRS & set(p.relative_to(base).parts))
    )


def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except OSError:
        return ""


# ---------------------------------------------------------------- snippets

def _astro_component(ga: str) -> str:
    return (
        "---\n"
        "// GA4 — LaMill Sites account. Measurement IDs are public; committed\n"
        "// here so the live tag never depends on a dashboard env var (ADR-0029).\n"
        f'const GA_ID = "{ga}";\n'
        "---\n"
        '<script is:inline async src={`https://www.googletagmanager.com/gtag/js?id=${GA_ID}`}></script>\n'
        "<script is:inline define:vars={{ GA_ID }}>\n"
        "  window.dataLayer = window.dataLayer || [];\n"
        "  function gtag() { dataLayer.push(arguments); }\n"
        '  gtag("js", new Date());\n'
        '  gtag("config", GA_ID);\n'
        "</script>\n"
    )


def _html_snippet(ga: str, indent: str) -> str:
    i = indent
    return (
        f"{i}<!-- GA4 (LaMill Sites; ID committed per ADR-0029) -->\n"
        f'{i}<script async src="https://www.googletagmanager.com/gtag/js?id={ga}"></script>\n'
        f"{i}<script>\n"
        f"{i}  window.dataLayer = window.dataLayer || [];\n"
        f"{i}  function gtag(){{dataLayer.push(arguments);}}\n"
        f"{i}  gtag('js', new Date());\n"
        f"{i}  gtag('config', '{ga}');\n"
        f"{i}</script>\n"
    )


def _jsx_snippet(ga: str, indent: str) -> str:
    i = indent
    inline = (
        "window.dataLayer = window.dataLayer || [];"
        "function gtag(){dataLayer.push(arguments);}"
        f"gtag('js', new Date());gtag('config', '{ga}');"
    )
    return (
        f'{i}{{/* GA4 (LaMill Sites; ID committed per ADR-0029) */}}\n'
        f'{i}<script async src="https://www.googletagmanager.com/gtag/js?id={ga}" />\n'
        f'{i}<script dangerouslySetInnerHTML={{{{ __html: "{inline}" }}}} />\n'
    )


def _insert_before_head_close(text: str, block_for_indent) -> str:
    """Insert the block returned by `block_for_indent(indent)` on its own
    lines just before the (first) `</head>`."""
    m = re.search(r"^([ \t]*)</head>", text, re.M)
    if m:
        indent = m.group(1) + "  "
        return text[: m.start()] + block_for_indent(indent) + text[m.start():]
    i = text.index("</head>")
    return text[:i] + "\n" + block_for_indent("") + text[i:]


def _add_astro_import(text: str, import_line: str) -> str:
    if text.startswith("---"):
        nl = text.index("\n") + 1
        return text[:nl] + import_line + "\n" + text[nl:]
    return f"---\n{import_line}\n---\n" + text


# ---------------------------------------------------------------- privacy

def _privacy_files(base: Path) -> list[Path]:
    """The privacy page plus any local Privacy* component it imports."""
    page = next((base / p for p in _PRIVACY_PAGES if (base / p).is_file()), None)
    if page is None:
        return []
    files = [page]
    for m in re.finditer(r"""from\s+["']((?:\.{1,2}|@)/[^"']*Privacy[^"']*)["']""", _read(page)):
        spec = m.group(1)
        target = (base / "src" / spec[2:]) if spec.startswith("@/") else (page.parent / spec).resolve()
        for cand in (target, *(target.with_suffix(s) for s in (".tsx", ".jsx", ".astro"))):
            if cand.is_file():
                files.append(cand)
                break
    return files


def privacy_state(base: Path) -> tuple[str, Path | None]:
    """("none"|"ok"|"conflict"|"missing", file_to_edit)."""
    files = _privacy_files(base)
    if not files:
        return "none", None
    text = "\n".join(_read(f) for f in files)
    if re.search(r"google analytics", text, re.I):
        return "ok", None
    if re.search(r"\banalytics\b", text, re.I):
        return "conflict", files[0]
    target = next((f for f in reversed(files) if "</p>" in _read(f)), None)
    return "missing", target


def _add_privacy_sentence(target: Path) -> None:
    text = _read(target)
    i = text.rindex("</p>") + len("</p>")
    line_start = text.rfind("\n", 0, text.rindex("</p>")) + 1
    indent = re.match(r"[ \t]*", text[line_start:]).group(0)
    target.write_text(text[:i] + f"\n{indent}<p>{PRIVACY_SENTENCE}</p>" + text[i:])


# ---------------------------------------------------------------- check

def _env_reads(base: Path) -> list[Path]:
    return [p for p in _src_files(base, _CODE_EXT) if _ENV_READ.search(_read(p))]


def run(repo_path: str) -> CheckResult:
    base = Path(repo_path)
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"{reason} — n/a")
    ga = recorded_id(base)
    if not ga:
        return CheckResult(status="pass", message="no GA4 ID recorded yet — CHECK_162 first")
    ids = source_ids(base)
    if ga not in ids:
        other = sorted(ids - {ga})
        why = f"source loads {', '.join(other)} instead" if other else "source doesn't load it"
        return CheckResult(status="warn", message=f"{ga}: {why} — `project fix`")
    priv, _ = privacy_state(base)
    if priv in ("missing", "conflict"):
        return CheckResult(
            status="warn",
            message=f"{ga} in source, but the privacy page doesn't mention Google Analytics",
        )
    return CheckResult(status="pass", message=f"source loads {ga}")


# ---------------------------------------------------------------- fixer

def _plan_tag(base: Path, ga: str) -> tuple[str, dict[Path, str]] | FixResult:
    """Return (summary, {path: new_text}) or a terminal FixResult."""
    ids = source_ids(base)
    if ga in ids:
        return "", {}
    if ids:
        return FixResult("manual", f"source loads {', '.join(sorted(ids))}, not {ga} — reconcile by hand", [])

    env_files = _env_reads(base)
    if env_files:
        stray = [p for p in env_files if not _site_wide(base, p)]
        if stray and len(stray) == len(env_files):
            names = ", ".join(str(p.relative_to(base)) for p in stray)
            return FixResult(
                "manual",
                f"GA loader ({names}) isn't reached from a layout or the app entry — "
                "only some pages would be tracked; wire it site-wide by hand",
                [],
            )
        writes = {
            p: _ENV_READ.sub(lambda m: f'({m.group(1)}.{m.group(2)} || "{ga}")', _read(p))
            for p in env_files
        }
        return f"default {ga} for PUBLIC_GA_ID/VITE_GA_ID ({len(writes)} file(s))", writes

    writes: dict[Path, str] = {}
    head_files = [p for p in _src_files(base, _HEAD_EXT) if "</head>" in _read(p)]
    astro_heads = [p for p in head_files if p.suffix == ".astro"]
    jsx_heads = [p for p in head_files if p.suffix != ".astro"]

    if astro_heads:
        comp = base / _COMPONENT
        if comp.exists():
            return FixResult("manual", f"{_COMPONENT} exists but doesn't load {ga} — wire it by hand", [])
        writes[comp] = _astro_component(ga)
        for p in astro_heads:
            text = _read(p)
            if re.search(r"\bAnalytics\b", text):
                return FixResult("manual", f"{p.relative_to(base)} already uses an `Analytics` name — wire by hand", [])
            rel = Path(_rel(p.parent, comp))
            text = _add_astro_import(text, f'import Analytics from "{rel.as_posix()}";')
            writes[p] = _insert_before_head_close(text, lambda ind: f"{ind}<Analytics />\n")
    for p in jsx_heads:
        writes[p] = _insert_before_head_close(_read(p), lambda ind: _jsx_snippet(ga, ind))
    if not writes:
        idx = base / "index.html"
        if idx.is_file() and "</head>" in _read(idx):
            writes[idx] = _insert_before_head_close(_read(idx), lambda ind: _html_snippet(ga, ind))
    if not writes:
        return FixResult("manual", "no `</head>` found in layouts, pages or index.html — tag by hand", [])
    names = ", ".join(str(p.relative_to(base)) for p in writes)
    return f"tag {ga} in {names}", writes


_ENTRIES = ("src/main.tsx", "src/main.ts", "src/main.jsx", "src/main.js", "index.html")


def _site_wide(base: Path, f: Path) -> bool:
    """True when `f` owns a `</head>`, is the app entry, or is imported by
    one of those (one hop, matched on the module's file stem)."""
    owners = [p for p in _src_files(base, _HEAD_EXT) if "</head>" in _read(p)]
    owners += [base / e for e in _ENTRIES if (base / e).is_file()]
    if f in owners:
        return True
    stem = re.compile(rf"""[/"']{re.escape(f.stem)}(?:\.[a-z]+)?["']""")
    return any(stem.search(_read(o)) for o in owners)


def _rel(from_dir: Path, target: Path) -> str:
    import os
    r = os.path.relpath(target, from_dir)
    return r if r.startswith(".") else f"./{r}"


def _fix(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    base = Path(project_dir)
    reason = _not_applicable(base)
    if reason:
        return FixResult("nothing-to-do", f"{reason} — n/a", [])
    ga = recorded_id(base)
    if not ga:
        return FixResult("manual", "no GA4 ID in lamill.toml — fix CHECK_162 first", [])

    plan = _plan_tag(base, ga)
    if isinstance(plan, FixResult):
        return plan
    tag_summary, writes = plan

    priv, priv_file = privacy_state(base)
    notes: list[str] = []
    if priv == "missing" and priv_file is not None:
        notes.append(f"privacy sentence → {priv_file.relative_to(base)}")
    elif priv == "missing":
        notes.append("privacy page has no <p> to append to — add the GA sentence by hand")
    elif priv == "conflict":
        notes.append(f"{priv_file.relative_to(base)} talks about analytics without naming Google Analytics — update it by hand")

    will_privacy = priv == "missing" and priv_file is not None
    if not writes and not will_privacy:
        if priv in ("conflict", "missing"):
            return FixResult("manual", notes[0], [])
        return FixResult("nothing-to-do", f"source loads {ga}", [])

    summary = "; ".join(s for s in [tag_summary, *notes] if s)
    if dry_run:
        return FixResult("would-fix", summary, [])

    touched: list[Path] = []
    for p, text in writes.items():
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
        touched.append(p)
    if will_privacy:
        _add_privacy_sentence(priv_file)
        touched.append(priv_file)
    return FixResult("fixed", summary, touched)


fix_tier_1 = FixerSpec(
    check_id="",
    tier=1,
    summary="inject GA4 tag with the committed ID (+ privacy sentence)",
    apply=_fix,
)
