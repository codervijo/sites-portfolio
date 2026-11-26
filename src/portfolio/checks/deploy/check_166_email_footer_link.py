"""CHECK_166 — the site's shared footer shows a `mailto:` link to its contact
address (v50.D).

Every page, not just the homepage: the check looks at the footer the whole
site renders, picked per stack in this order:

  1. a `*Footer*` component (`.astro` / `.tsx` / `.jsx`) holding a
     `<footer>` and reached from a layout, the app entry or `App`
     (two import hops);
  2. otherwise every layout / root that owns `</head>` (Astro layout,
     TanStack `__root.tsx`) or is the app shell (`App.tsx`) and holds a
     `<footer>` — all of them, so no page is missed;
  3. otherwise `index.html` with a `<footer>` (plain Vite).

  pass  — every footer found has a `mailto:` on the site's own domain
          (or a templated `mailto:` lamill can't resolve from source).
  warn  — no own-domain `mailto:` in the footer (`project fix` adds it),
          or no shared footer found (add the link by hand).

The address: an own-domain `mailto:` already used elsewhere in the source
(e.g. a contact page) when mail for it works, else `hello@<site>`.

Fixer (tier 1, edits source → `project fix` builds the site afterwards,
v50.D build check): **never publishes an address that would bounce.** It
adds the link only when CHECK_165 is ✓ (Cloudflare Email Routing on, rule
present, destination verified), or the domain's mail is handled by another
provider *and* the source already uses an own-domain address for it. The
link copies the footer's existing link style (`class` / `className` /
`style` of its last literal link, and its `<li>` / `<p>` wrapper);
a footer with no plain link gets `<p><a href="mailto:…">…</a></p>`.

`add_footer_link()` is the same edit without the mail gate — `new
bootstrap` uses it (v50.G): the site isn't public until `new deploy`, which
turns on routing.

Not applicable: same scoping as CHECK_165 (non-domain dirs, archived, dark,
HostGator, client-owned). `warn` severity.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from pathlib import Path

from portfolio.fix_helpers import FixerSpec, FixResult

from ..result import CheckResult
from .check_165_email_routing_ready import _not_applicable

CHECK_ID = "CHECK_166"
CHECK_NAME = "email-footer-link"
CATEGORY = "deploy"
SEVERITY = "warn"
DESCRIPTION = (
    "The shared footer (every page) links mailto: the site's contact address, "
    "hello@<site> by default (`project fix` adds it once CHECK_165 is ✓ — v50.D)."
)

_FOOTER_EXT = (".astro", ".tsx", ".jsx")
_CODE_EXT = (".astro", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue", ".svelte", ".md", ".mdx")
_SKIP_DIRS = {"node_modules", "dist", ".astro", ".output", "build", ".vercel", ".git", "genai"}
_ENTRIES = ("src/main.tsx", "src/main.ts", "src/main.jsx", "src/main.js", "index.html")
_SHELL_STEMS = {"app", "__root", "root", "layout", "baselayout", "rootlayout", "mainlayout"}
_FOOTER_OPEN = re.compile(r"<footer\b[^>]*>", re.I)
_ANCHOR = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.S | re.I)
_STYLE_ATTR = re.compile(r"""\s(class|className|style)=("[^"]*"|'[^']*'|\{[^{}]*\})""")
_TEMPLATED_MAILTO = re.compile(r"""mailto:(?:\$\{|\{|["'`]\s*\+)""")


# ---------------------------------------------------------------- files

def _read(p: Path) -> str:
    try:
        return p.read_text(errors="ignore")
    except OSError:
        return ""


def _src_files(base: Path, exts: tuple[str, ...]) -> list[Path]:
    src = base / "src"
    if not src.is_dir():
        return []
    return sorted(
        p for p in src.rglob("*")
        if p.is_file() and p.suffix in exts and not p.name.endswith(".d.ts")
        and not (_SKIP_DIRS & set(p.relative_to(base).parts))
    )


def _refs(text: str, f: Path) -> bool:
    stem = re.compile(rf"""[/"']{re.escape(f.stem)}(?:\.[a-z]+)?["']""")
    return bool(stem.search(text))


def _owners(base: Path) -> list[Path]:
    """Files every page goes through: `</head>` owners + the app entry."""
    out = [p for p in _src_files(base, _FOOTER_EXT) if "</head>" in _read(p)]
    out += [base / e for e in _ENTRIES if (base / e).is_file()]
    return out


def _site_wide(base: Path, f: Path, owners: list[Path] | None = None) -> bool:
    """`f` is an owner, or is imported by one, or by a file an owner imports
    (two hops — `main.tsx` → `App.tsx` → `Footer.tsx`)."""
    owners = owners if owners is not None else _owners(base)
    if f in owners:
        return True
    texts = {o: _read(o) for o in owners}
    if any(_refs(t, f) for t in texts.values()):
        return True
    for mid in _src_files(base, _FOOTER_EXT + (".ts", ".js")):
        if mid != f and mid not in owners and _refs(_read(mid), f):
            if any(_refs(t, mid) for t in texts.values()):
                return True
    return False


def footer_targets(base: Path) -> list[Path]:
    """The footer file(s) every page renders; [] when none is found."""
    files = [p for p in _src_files(base, _FOOTER_EXT) if _FOOTER_OPEN.search(_read(p))]
    owners = _owners(base)
    comps = [p for p in files if "footer" in p.stem.lower() and _site_wide(base, p, owners)]
    if comps:
        return comps
    shells = [
        p for p in files
        if "</head>" in _read(p)
        or ((p.stem.lower() in _SHELL_STEMS or "layouts" in p.parts)
            and _site_wide(base, p, owners))
    ]
    if shells:
        return shells
    idx = base / "index.html"
    if idx.is_file() and _FOOTER_OPEN.search(_read(idx)):
        return [idx]
    return []


def _footer_span(text: str) -> tuple[int, int] | None:
    """(start of the last `<footer …>` tag's body, index of its `</footer>`)."""
    opens = list(_FOOTER_OPEN.finditer(text))
    if not opens:
        return None
    m = opens[-1]
    close = text.lower().find("</footer>", m.end())
    if close < 0:
        return None
    return m.end(), close


def _own_mailto(domain: str) -> re.Pattern:
    return re.compile(rf"mailto:([A-Za-z0-9._%+-]+@(?:[a-z0-9-]+\.)*{re.escape(domain)})\b", re.I)


def footer_has_link(text: str, domain: str) -> bool:
    span = _footer_span(text)
    if span is None:
        return False
    body = text[span[0]:span[1]]
    return bool(_own_mailto(domain).search(body) or _TEMPLATED_MAILTO.search(body))


def source_addresses(base: Path, domain: str) -> list[str]:
    """Own-domain addresses the source already links, most used first."""
    rx = _own_mailto(domain)
    files = _src_files(base, _CODE_EXT)
    if (base / "index.html").is_file():
        files.append(base / "index.html")
    seen: Counter[str] = Counter()
    for p in files:
        for m in rx.finditer(_read(p)):
            seen[m.group(1).lower()] += 1
    return [a for a, _ in seen.most_common()]


# ---------------------------------------------------------------- edit

def _style_attrs(attrs: str) -> str:
    return "".join(f" {m.group(1)}={m.group(2)}" for m in _STYLE_ATTR.finditer(attrs))


def _new_anchor(addr: str, attrs: str = "") -> str:
    return f'<a href="mailto:{addr}"{attrs}>{addr}</a>'


def insert_link(text: str, addr: str) -> str | None:
    """Return `text` with a mailto link added to its (last) footer, in the
    style of the footer's last plain link. None if there is no footer."""
    span = _footer_span(text)
    if span is None:
        return None
    b0, close = span
    body = text[b0:close]
    pick = None
    for a in _ANCHOR.finditer(body):
        start, end = b0 + a.start(), b0 + a.end()
        ls = text.rfind("\n", 0, start) + 1
        le = text.find("\n", end)
        le = len(text) if le < 0 else le
        item = text[ls:le]
        literal = re.search(r"""\bhref=["']""", a.group(1))
        mapped = "=>" in item or ".map(" in item or "{" in a.group(2)
        if literal and not mapped:
            pick = (a, start, end, ls, le, item)
    if pick is None:
        ls = text.rfind("\n", 0, close) + 1
        line = text[ls:close]
        if line.strip():  # `</footer>` shares its line with content
            return text[:close] + f"<p>{_new_anchor(addr)}</p>" + text[close:]
        indent = line + "  "
        return text[:ls] + f"{indent}<p>{_new_anchor(addr)}</p>\n" + text[ls:]
    a, start, end, ls, le, item = pick
    new = _new_anchor(addr, _style_attrs(a.group(1)))
    def _text_only(s: str) -> str:
        return re.sub(r"<[^>]*>", "", s).strip()

    several = len(re.findall(r"<a\b", item, re.I)) > 1
    if several or _text_only(text[ls:start]) or _text_only(text[end:le]):
        # Several links (or link + text, e.g. "© 2026 <a>…</a>") on one line:
        # add ours right after the last link, reusing the separator between
        # the previous two links when it's plain text.
        prev = list(_ANCHOR.finditer(text, ls, start))
        sep = " · "
        if prev:
            gap = text[prev[-1].end():start]
            if "<" not in gap and len(gap) <= 12:
                sep = gap
        return text[:end] + sep + new + text[end:]
    clone = text[ls:start] + new + text[end:le]
    return text[:le] + "\n" + clone + text[le:]


def add_footer_link(base: Path, addr: str, *, dry_run: bool) -> FixResult:
    """The edit alone, no mail gate (used by the fixer and `new bootstrap`)."""
    domain = base.name.lower()
    targets = footer_targets(base)
    if not targets:
        return FixResult("manual", "no shared footer found (Footer component, layout "
                                   "or index.html with <footer>) — add a mailto: "
                                   f"{addr} link to the site footer by hand", [])
    writes: dict[Path, str] = {}
    for p in targets:
        text = _read(p)
        if footer_has_link(text, domain):
            continue
        new = insert_link(text, addr)
        if new is None:
            return FixResult("manual", f"{_rel(base, p)}: <footer> isn't closed in the same "
                                       f"file — add a mailto: {addr} link by hand", [])
        writes[p] = new
    if not writes:
        return FixResult("nothing-to-do", "footer already links an own-domain address", [])
    names = ", ".join(_rel(base, p) for p in writes)
    if dry_run:
        return FixResult("would-fix", f"add mailto:{addr} to the footer in {names}",
                         list(writes))
    for p, t in writes.items():
        p.write_text(t)
    return FixResult("fixed", f"footer links mailto:{addr} ({names})", list(writes))


def _rel(base: Path, p: Path) -> str:
    return os.path.relpath(p, base)


# ---------------------------------------------------------------- check

def run(repo_path: str) -> CheckResult:
    base = Path(repo_path).resolve()
    reason = _not_applicable(base)
    if reason:
        return CheckResult(status="pass", message=f"{reason} — n/a")
    domain = base.name.lower()
    targets = footer_targets(base)
    if not targets:
        return CheckResult(status="warn",
                           message="no shared footer found — add a mailto: link to "
                                   "the site's contact address by hand")
    missing = [p for p in targets if not footer_has_link(_read(p), domain)]
    if missing:
        names = ", ".join(_rel(base, p) for p in missing)
        return CheckResult(status="warn",
                           message=f"footer ({names}) has no mailto: on {domain} — "
                                   "`project fix` adds it once CHECK_165 is ✓")
    return CheckResult(status="pass",
                       message=f"footer links an own-domain address ({len(targets)} file(s))")


# ---------------------------------------------------------------- fixer

def _mail_address(base: Path) -> tuple[str | None, str]:
    """(address to publish, why) — None when publishing would risk a bounce."""
    from portfolio import email_routing as er
    domain = base.name.lower()
    try:
        st = er.inspect(domain, forward_to=er.forward_to_for(base),
                        local_parts=er.local_parts_for(base))
    except er.EmailRoutingError as e:
        return None, f"can't confirm hello@{domain} receives mail ({e}) — re-run later"
    except Exception as e:  # network / DNS
        return None, f"can't confirm hello@{domain} receives mail ({type(e).__name__}: {e})"
    known = source_addresses(base, domain)
    if st.other_provider:
        if known:
            return known[0], f"mail handled by {st.other_provider}"
        return None, (f"mail is handled by {st.other_provider} and the source names no "
                      f"{domain} address — add the footer link by hand with an address "
                      "that exists there")
    if not st.ready():
        return None, (f"hello@{domain} doesn't receive mail yet — run "
                      f"`lamill project fix {domain} --rule CHECK_165 --apply` first "
                      "(never publish an address that bounces)")
    routed = [a for a in known if a in st.addresses]
    return (routed[0] if routed else f"hello@{domain}"), "routing on, destination verified"


def _apply(project_dir: Path, dry_run: bool, assume_yes: bool) -> FixResult:
    base = Path(project_dir).resolve()
    reason = _not_applicable(base)
    if reason:
        return FixResult("nothing-to-do", f"{reason} — n/a", [])
    domain = base.name.lower()
    targets = footer_targets(base)
    if targets and all(footer_has_link(_read(p), domain) for p in targets):
        return FixResult("nothing-to-do", "footer already links an own-domain address", [])
    if not targets:
        return add_footer_link(base, f"hello@{domain}", dry_run=True)  # → manual
    addr, why = _mail_address(base)
    if addr is None:
        return FixResult("manual", why, [])
    return add_footer_link(base, addr, dry_run=dry_run)


fix_tier_1 = FixerSpec(
    check_id="",   # registry rewrites at discovery time
    tier=1,
    summary="add a mailto: link to the site footer (only once the address receives mail)",
    apply=_apply,
    edits_source=True,
)
