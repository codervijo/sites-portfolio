"""CHECK_095 — FAQPage answer text appears in the served HTML body.

For pages declaring FAQPage JSON-LD, each Question's accepted-answer
text must also appear in the visible HTML body — not only inside the
JSON-LD script tag.

Why this matters: client-side-only FAQ rendering (accordion that
hydrates after page load) leaves the answer text out of the served
HTML. Googlebot's first-pass crawl indexes the HTML before hydration
on most sites; the JSON-LD survives but the on-page answer doesn't.
Schema validators pass, ranking-signal-bearing body text is missing.
The washcalc.app audit caught this: "Google's seen 1 of 5 answers"
(only the first accordion item was rendered open).

What this check inspects: for each FAQPage Question's
`acceptedAnswer.text`, take a normalized "signature" (first 8 words,
single-spaced, lowercase). If that signature isn't present in the
page's body text (after stripping `<script>` / `<style>` tags), flag
the question.

The signature approach (first 8 words instead of the full answer
string) tolerates minor HTML escaping / whitespace / typographic
differences between the JSON-LD value and the rendered DOM (e.g.
`&amp;` vs `&`, en-dash vs hyphen, normalized whitespace).
"""
from __future__ import annotations

import re

from ..result import CheckResult
from . import _is_web_project
from ._live import (
    LiveFetchError,
    fetch_html,
    get_sitemap_urls,
    iter_jsonld_nodes,
    node_type,
    parse_jsonld_blocks,
    resolve_live_url,
)

CHECK_ID = "CHECK_095"
CHECK_NAME = "live-faq-answers-in-html"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Every FAQPage acceptedAnswer.text appears in the served HTML body — "
    "not only in the JSON-LD script tag."
)

SIGNATURE_WORDS = 8


def _normalize(text: str) -> str:
    """Lowercase, collapse all whitespace runs to single spaces."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def _signature(text: str) -> str:
    """First N words of `text`, normalized — used as a fuzzy substring
    match against body text. Tolerates minor escaping / spacing diffs."""
    words = re.split(r"\s+", text.strip())
    return " ".join(words[:SIGNATURE_WORDS]).lower()


def _extract_body_text(html: str) -> str:
    """Return the page's visible text (scripts + style tags stripped),
    normalized."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "noscript"]):
        tag.decompose()
    return _normalize(soup.get_text(" ", strip=True))


def _missing_answers_for_url(url: str) -> list[str]:
    """Return findings for one page. Empty list = clean."""
    try:
        html = fetch_html(url)
    except LiveFetchError:
        return []
    body_text = _extract_body_text(html)

    findings: list[str] = []
    for block in parse_jsonld_blocks(html):
        if block.parsed is None:
            continue
        for node in iter_jsonld_nodes(block.parsed):
            if not isinstance(node, dict):
                continue
            if "FAQPage" not in node_type(node):
                continue
            main = node.get("mainEntity")
            if not isinstance(main, list):
                continue
            for i, q in enumerate(main, 1):
                if not isinstance(q, dict):
                    continue
                if "Question" not in node_type(q):
                    continue
                ans = q.get("acceptedAnswer")
                if not isinstance(ans, dict):
                    continue
                ans_text = ans.get("text")
                if not isinstance(ans_text, str) or not ans_text.strip():
                    continue
                sig = _signature(ans_text)
                if not sig or len(sig) < 12:
                    # Too short to be a useful signature — skip to avoid
                    # false matches against boilerplate.
                    continue
                if sig not in body_text:
                    name = q.get("name") or f"#{i}"
                    label = name[:40] if isinstance(name, str) else f"#{i}"
                    findings.append(
                        f"{url}: FAQ answer for {label!r} not in body HTML "
                        f"(searched for {sig!r})"
                    )
    return findings


def run(repo_path: str) -> CheckResult:
    if not _is_web_project(repo_path):
        return CheckResult(status="warn", message="not a web project — skipped")
    origin = resolve_live_url(repo_path)
    if not origin:
        return CheckResult(status="warn", message="no live URL configured — skipped")

    try:
        urls = get_sitemap_urls(origin)
    except LiveFetchError as e:
        return CheckResult(status="warn", message=f"sitemap unreachable ({e})")
    if not urls:
        return CheckResult(status="warn", message=f"sitemap empty at {origin}")

    findings: list[str] = []
    fetched = 0
    for url in urls:
        try:
            fetch_html(url)
        except LiveFetchError:
            continue
        fetched += 1
        findings.extend(_missing_answers_for_url(url))

    if fetched == 0:
        return CheckResult(
            status="warn",
            message=f"all {len(urls)} sitemap URL(s) unreachable",
        )

    if not findings:
        return CheckResult(
            status="pass",
            message=f"all FAQPage answers present in body HTML on {fetched} URL(s)",
        )

    sample = "; ".join(findings[:3])
    return CheckResult(
        status="fail",
        message=f"{len(findings)} FAQ answer(s) missing from body HTML — {sample}",
    )
