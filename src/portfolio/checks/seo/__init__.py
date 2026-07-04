"""SEO-category checks.

Two sub-families:

  - Static-source (CHECK_060–080) — read files on disk (favicon,
    robots.txt, sitemap.xml, meta tags parsed from index.html or
    src/pages/index.astro). Run by `lamill project check`.

  - Live-runtime (CHECK_090–095, v5.D) — fetch the deployed URLs as
    Googlebot and validate what indexers see. Shared helpers in
    `_live.py`; each check fetches every sitemap URL through a
    per-process cache so the cluster runs in one round-trip. Network
    failures degrade to `warn`, not `fail`.
"""
from __future__ import annotations

import re
from pathlib import Path

# Top-level entry points where SEO meta lives. Vite stack uses index.html;
# Astro stack uses src/pages/index.astro. Either is acceptable.
_HTML_CANDIDATE_PATHS = [
    "index.html",
    "src/pages/index.astro",
    "src/pages/index.html",
]


def _read_index_html(repo_path: str) -> str | None:
    """Return the contents of the project's main HTML/Astro index, or None
    if no recognized entry point exists."""
    base = Path(repo_path)
    for rel in _HTML_CANDIDATE_PATHS:
        p = base / rel
        if p.is_file():
            try:
                return p.read_text(errors="replace")
            except OSError:
                continue
    return None


def _is_web_project(repo_path: str) -> bool:
    return (Path(repo_path) / "package.json").is_file()


def _bs4():
    """Return the `BeautifulSoup` class, wrapping the lazy import with a
    typed error that names the fix command (v35.D — global rule: lazy
    imports of optional/heavy deps must raise an actionable error, not a
    raw ModuleNotFoundError, on a partial/broken install). bs4 is the
    heaviest SEO-check dep + the most likely to be missing. Shared by the
    SEO checks (`_live`, `check_095`) so the wrap lives in one place."""
    try:
        from bs4 import BeautifulSoup
    except ImportError as e:  # pragma: no cover - bs4 is a core dep
        raise RuntimeError(
            f"beautifulsoup4 not importable ({e}). Run `uv sync` to install."
        ) from e
    return BeautifulSoup


def _parse_html(text: str):
    """Parse the index HTML/Astro content into a BeautifulSoup tree.
    Astro frontmatter (between leading `---` markers) is stripped first
    so the parser sees only the template body."""
    if text.startswith("---"):
        # Astro file: skip frontmatter
        end = text.find("\n---", 3)
        if end != -1:
            text = text[end + 4:]
    return _bs4()(text, "html.parser")


# ---------------------------------------------------------------------------
# SSR-head resolution (docs/bugs.md 2026-06-29).
#
# The meta checks (070/071/076/077) historically read only a static
# index.html / index.astro. Stacks that define the document head in code
# (TanStack Start route `head()`, Astro layouts, Next `metadata`) ship no
# such file, so those checks skipped — a `title: "Lovable App"` sailed
# through. `_read_head_html` falls back to synthesizing a <head> from the
# in-code definition so the same bs4-based checks work unchanged.
# ---------------------------------------------------------------------------

# Homepage route heads come first (their title wins), then the root/layout
# fallback head. Order matters: bs4 `.find("title")` returns the first.
_SSR_HEAD_FILES = [
    "src/routes/index.tsx", "src/routes/index.jsx",
    "src/app/page.tsx", "app/page.tsx",
    "src/routes/__root.tsx", "src/routes/__root.jsx", "src/routes/__root.ts",
    "src/app/layout.tsx", "app/layout.tsx",
]
# Astro puts the head in a layout; scan those too.
_SSR_HEAD_GLOB = ("src/layouts", "*.astro")

# A file is only mined for head content if it actually looks like a head
# definition — keeps a stray `title:`/`content:` prop in some component
# from synthesizing a bogus tag.
_HEAD_MARKERS = (
    "head:", "createRootRoute", "export const metadata", "<head",
)

_JS_TITLE_RE = re.compile(r"""\btitle:\s*['"`]([^'"`]+)['"`]""")
_JS_KEYTYPE_RE = re.compile(r"""\b(name|property):\s*['"`]([^'"`]+)['"`]""")
_JS_CONTENT_RE = re.compile(r"""\bcontent:\s*['"`]([^'"`]*)['"`]""")
_HTML_HEAD_TAG_RE = re.compile(r"<title>.*?</title>|<meta\b[^>]*>",
                               re.IGNORECASE | re.DOTALL)


def _looks_like_head_def(text: str) -> bool:
    return any(m in text for m in _HEAD_MARKERS)


def _synth_head_from_js(text: str) -> str:
    """Turn JS head/meta object literals (TanStack Start / Next metadata
    style) into equivalent HTML head tags. `{ title: "X" }` -> <title>X…,
    `{ name|property: "K", content: "V" }` -> <meta …>."""
    tags: list[str] = []
    m = _JS_TITLE_RE.search(text)
    if m:
        tags.append(f"<title>{m.group(1)}</title>")
    for block in re.findall(r"\{[^{}]*\}", text):
        kt = _JS_KEYTYPE_RE.search(block)
        ct = _JS_CONTENT_RE.search(block)
        if kt and ct:
            tags.append(f'<meta {kt.group(1)}="{kt.group(2)}" content="{ct.group(1)}">')
    return "\n".join(tags)


def _synthesize_head_from_source(repo_path: str) -> str | None:
    """Build a minimal <head> HTML from a project's in-code head
    definition, for SSR-head stacks that ship no static index. Returns
    None if nothing head-like is found."""
    base = Path(repo_path)
    paths = [base / rel for rel in _SSR_HEAD_FILES]
    glob_dir = base / _SSR_HEAD_GLOB[0]
    if glob_dir.is_dir():
        paths.extend(sorted(glob_dir.glob(_SSR_HEAD_GLOB[1])))

    fragments: list[str] = []
    for p in paths:
        if not p.is_file():
            continue
        try:
            text = p.read_text(errors="replace")
        except OSError:
            continue
        if not _looks_like_head_def(text):
            continue
        fragments.extend(_HTML_HEAD_TAG_RE.findall(text))  # raw HTML (Astro/JSX)
        js = _synth_head_from_js(text)                      # JS object literals
        if js:
            fragments.append(js)
        fragments.extend(_jsonld_scripts(text))             # framework JSON-LD idioms

    head = "\n".join(f for f in fragments if f.strip())
    if not head.strip():
        return None
    return f"<!doctype html><html><head>\n{head}\n</head><body></body></html>"


# --- Astro static head resolution (docs/bugs.md 2026-07-03) ----------------
# Astro pages write `<title>{title}</title>` (interpolating a frontmatter
# const) and delegate <html>/<head> to an imported layout. Reading the raw
# .astro made 070/071/073/074 false-fail (literal `{title}`, no <html>).
# Resolve statically: substitute frontmatter consts into head expressions and
# merge the imported layout's head.
_ASTRO_CONST_RE = re.compile(
    r"""^\s*const\s+(\w+)\s*=\s*(['"`])(.*?)\2\s*;?\s*$""", re.M
)
_ASTRO_LAYOUT_IMPORT_RE = re.compile(
    r"""import\s+\w+\s+from\s+['"]([^'"]*[Ll]ayout[^'"]*\.astro)['"]"""
)


def _astro_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Split an .astro file into ({const: string_value}, body-after-fence)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end == -1:
        return {}, text
    fm, body = text[3:end], text[end + 4:]
    consts = {m.group(1): m.group(3) for m in _ASTRO_CONST_RE.finditer(fm)}
    return consts, body


def _resolve_astro_exprs(body: str, consts: dict[str, str]) -> str:
    """`attr={const}` -> `attr="value"` and bare `{const}` -> `value` for the
    string consts we know. Unknown expressions are left untouched."""
    def attr(m):
        v = consts.get(m.group(1))
        return f'="{v}"' if v is not None else m.group(0)

    def txt(m):
        v = consts.get(m.group(1))
        return v if v is not None else m.group(0)

    body = re.sub(r"=\{(\w+)\}", attr, body)
    return re.sub(r"\{(\w+)\}", txt, body)


def _astro_layout_head(page_path: Path, text: str, _depth: int = 0) -> str:
    """Head/HTML contributed by an imported Astro layout (which holds <html>,
    <head>, base meta). Follows the layout chain, depth-capped."""
    if _depth > 3:
        return ""
    m = _ASTRO_LAYOUT_IMPORT_RE.search(text)
    if not m:
        return ""
    layout_path = (page_path.parent / m.group(1)).resolve()
    if not layout_path.is_file():
        return ""
    try:
        ltext = layout_path.read_text(errors="replace")
    except OSError:
        return ""
    lconsts, lbody = _astro_frontmatter(ltext)
    parent = _astro_layout_head(layout_path, ltext, _depth + 1)
    return parent + "\n" + _resolve_astro_exprs(lbody, lconsts)


_ASTRO_JSONLD_TYPE_RE = re.compile(r"""["']@type["']\s*:\s*["']([A-Za-z]+)["']""")


def _extract_balanced(text: str, start: int) -> str | None:
    """Return the balanced `{…}` / `[…]` substring beginning at `start`."""
    open_c = text[start]
    close_c = {"{": "}", "[": "]"}.get(open_c)
    if close_c is None:
        return None
    depth = 0
    for j in range(start, len(text)):
        if text[j] == open_c:
            depth += 1
        elif text[j] == close_c:
            depth -= 1
            if depth == 0:
                return text[start:j + 1]
    return None


def _astro_const_object(text: str, name: str) -> str | None:
    m = re.search(rf"\bconst\s+{re.escape(name)}\s*=\s*[\{{\[]", text)
    return _extract_balanced(text, m.end() - 1) if m else None


# Framework idioms that hide JSON-LD from a raw-source parse: Astro's
# `set:html={JSON.stringify(…)}` and TanStack/unhead's `"script:ld+json": …`.
_JSONLD_ANCHORS = (
    re.compile(r"set:html=\{\s*JSON\.stringify\("),
    re.compile(r"""["']script:ld\+json["']\s*:\s*"""),
)


def _jsonld_arg_object(text: str, i: int) -> str | None:
    """From index `i` (start of a JSON-LD argument), return the balanced
    object/array literal — inline, or resolved from a `const NAME = …`."""
    while i < len(text) and text[i] in " \t\r\n":
        i += 1
    if i >= len(text):
        return None
    if text[i] in "{[":
        return _extract_balanced(text, i)
    nm = re.match(r"\w+", text[i:])
    return _astro_const_object(text, nm.group(0)) if nm else None


def _jsonld_scripts(text: str) -> list[str]:
    """Emit parseable ld+json <script>s capturing the @type(s) declared via
    the framework idioms above (inline object/array OR a const), which are
    unparseable in raw source — so the JSON-LD checks can see the type.
    docs/bugs.md 2026-07-03."""
    scripts: list[str] = []
    for anchor in _JSONLD_ANCHORS:
        for m in anchor.finditer(text):
            obj = _jsonld_arg_object(text, m.end())
            if not obj:
                continue
            for t in _ASTRO_JSONLD_TYPE_RE.findall(obj):
                scripts.append(
                    '<script type="application/ld+json">'
                    f'{{"@context":"https://schema.org","@type":"{t}"}}</script>'
                )
    return scripts


def _resolve_astro_head(page_path: Path, text: str) -> str | None:
    """Best-effort rendered-head reconstruction for an Astro page: frontmatter
    const substitution + merged layout head + JSON-LD from the `set:html`
    idiom. None if no head tags surface. Clean synthesized scripts are placed
    before the raw body so bs4 parses them even if the original malformed
    `set:html` tag confuses the parser."""
    consts, body = _astro_frontmatter(text)
    body = _resolve_astro_exprs(body, consts)
    jsonld = "\n".join(_jsonld_scripts(text))
    blob = _astro_layout_head(page_path, text) + "\n" + jsonld + "\n" + body
    if not re.search(r"<(title|meta|html|script)\b", blob, re.I):
        return None
    return f"<!doctype html>\n{blob}"


# --- vite-react-ssg / React head-component resolution (docs/bugs.md 2026-07-03)
# Sites where index.html is a bare mount shell and the head is a React
# component using vite-react-ssg's <Head> — e.g. `<Seo title=… description=…
# jsonLd={[…]} />`. Reconstruct title/meta/JSON-LD from the homepage usage +
# the head component's tag structure.

def _safe_read(p: Path) -> str:
    try:
        return p.read_text(errors="replace")
    except OSError:
        return ""


def _iter_tsx(base: Path, subdirs: tuple[str, ...]):
    for sub in subdirs:
        d = base / sub
        if not d.is_dir():
            continue
        for p in sorted(d.rglob("*.tsx")) + sorted(d.rglob("*.jsx")):
            if "node_modules" not in p.parts:
                yield p


def _react_head_template(base: Path) -> str:
    """Inner `<Head>…</Head>` of a vite-react-ssg head component, or ''."""
    for p in _iter_tsx(base, ("src/components", "src")):
        t = _safe_read(p)
        if "vite-react-ssg" in t and "<Head>" in t:
            m = re.search(r"<Head>(.*?)</Head>", t, re.S)
            if m:
                return m.group(1)
    return ""


def _homepage_seo_usage(base: Path) -> str | None:
    """Source of the page whose `<Seo …/>` feeds the homepage head. Prefers a
    page with `path="/"` or an index/home filename."""
    best, best_score = None, -1
    for p in _iter_tsx(base, ("src/pages", "src/routes")):
        t = _safe_read(p)
        if not re.search(r'\btitle\s*=\s*["\']', t):
            continue
        if "Seo" not in t and "Head" not in t:
            continue
        score = (2 if re.search(r'\bpath\s*=\s*["\']/["\']', t) else 0)
        score += (1 if p.stem.lower() in ("index", "home") else 0)
        if score > best_score:
            best, best_score = t, score
    return best


def _jsx_seo_props(text: str) -> dict[str, str]:
    """title=/description= string props from the component tag bearing title=."""
    seg = text
    for m in re.finditer(r"<[A-Z]\w*\b(.*?)/>", text, re.S):
        if re.search(r'\btitle\s*=\s*["\']', m.group(1)):
            seg = m.group(1)
            break
    out: dict[str, str] = {}
    for key in ("title", "description"):
        m = re.search(rf'\b{key}\s*=\s*["\']([^"\']+)["\']', seg)
        if m:
            out[key] = m.group(1)
    return out


def _react_prop_jsonld(usage: str) -> list[str]:
    """JSON-LD from a `jsonLd={[constA, constB]}` prop — resolve each const's
    @type. docs/bugs.md 2026-07-03."""
    m = re.search(r"\bjsonLd\s*=\s*\{", usage)
    if not m:
        return []
    block = _extract_balanced(usage, m.end() - 1)
    if not block:
        return []
    scripts: list[str] = []
    for name in dict.fromkeys(re.findall(r"[A-Za-z_]\w*", block)):
        obj = _astro_const_object(usage, name)
        if obj:
            for t in _ASTRO_JSONLD_TYPE_RE.findall(obj):
                scripts.append(
                    '<script type="application/ld+json">'
                    f'{{"@context":"https://schema.org","@type":"{t}"}}</script>')
    return scripts


def _react_ssg_head(repo_path: str) -> str | None:
    """Reconstruct the head for a vite-react-ssg site whose index.html is a
    bare shell: title/description from the homepage `<Seo>` props, og/twitter
    tags from the head component's structure (values filled where known,
    present-placeholder otherwise), and JSON-LD from the jsonLd prop consts."""
    base = Path(repo_path)
    usage = _homepage_seo_usage(base)
    if usage is None:
        return None
    props = _jsx_seo_props(usage)
    title, desc = props.get("title"), props.get("description")
    jsonld = _react_prop_jsonld(usage)
    if not (title or desc or jsonld):
        return None
    tags: list[str] = []
    if title:
        tags.append(f"<title>{title}</title>")
    if desc:
        tags.append(f'<meta name="description" content="{desc}">')
    keys = (set(re.findall(r'property="(og:[\w:]+)"', _react_head_template(base)))
            | set(re.findall(r'name="(twitter:[\w:]+)"', _react_head_template(base))))
    for k in sorted(keys):
        attr = "property" if k.startswith("og:") else "name"
        if k.endswith("title"):
            v = title or "…"
        elif k.endswith("description"):
            v = desc or "…"
        elif k == "og:type":
            v = "website"
        elif k == "twitter:card":
            v = "summary"
        else:
            v = "…"          # og:url / og:image — present placeholder
        tags.append(f'<meta {attr}="{k}" content="{v}">')
    tags.extend(jsonld)
    return "\n".join(tags)


def _read_head_html(repo_path: str) -> str | None:
    """Head HTML for the SEO meta checks. Prefers a static index — resolving
    Astro pages (frontmatter `{const}` + imported layout head) and merging a
    reconstructed head for bare vite-react-ssg shells (`<Seo>`/`<Head>`) — and
    falls back to synthesizing from in-code definitions for SSR-head stacks
    (TanStack Start / Next). docs/bugs.md 2026-06-29 + 2026-07-03."""
    base = Path(repo_path)
    for rel in _HTML_CANDIDATE_PATHS:
        p = base / rel
        if not p.is_file():
            continue
        text = _safe_read(p)
        if p.suffix == ".astro":
            resolved = _resolve_astro_head(p, text)
            if resolved is not None:
                return resolved
            return text
        # Bare mount shell (no <title>): merge in the React/SSG component head.
        if "<title" not in text.lower():
            extra = _react_ssg_head(str(base))
            if extra:
                return text + "\n" + extra
        return text
    return _synthesize_head_from_source(str(base))
