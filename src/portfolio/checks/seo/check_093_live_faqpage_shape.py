"""CHECK_093 — Live FAQPage JSON-LD blocks have the required shape.

A `FAQPage` block must have a non-empty `mainEntity`, and every
question item inside must have an `acceptedAnswer.text`. Empty or
malformed FAQ schemas get rejected by Google's structured-data
validator and yield zero rich-result eligibility — silently.

What's checked, per FAQPage node found on every live sitemap URL:
  - `mainEntity` is present and is a non-empty list
  - each item in `mainEntity` has `@type: Question`
  - each Question has a `name` (the question text)
  - each Question has `acceptedAnswer` as a dict
  - the acceptedAnswer has non-empty `text`

A page with no FAQPage block is fine (FAQ markup is optional;
CHECK_093 only fires when the markup exists but is malformed).
"""
from __future__ import annotations

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

CHECK_ID = "CHECK_093"
CHECK_NAME = "live-faqpage-shape"
CATEGORY = "seo"
SEVERITY = "warn"
DESCRIPTION = (
    "Every FAQPage JSON-LD block has a non-empty mainEntity, and every "
    "Question has acceptedAnswer.text."
)


def _validate_faqpage(url: str, node: dict) -> list[str]:
    """Return findings for one FAQPage node. Empty list = clean."""
    findings: list[str] = []
    main = node.get("mainEntity")
    if not isinstance(main, list) or not main:
        findings.append(f"{url}: FAQPage mainEntity missing or empty")
        return findings

    for i, q in enumerate(main, 1):
        if not isinstance(q, dict):
            findings.append(f"{url}: FAQPage mainEntity[{i}] is not an object")
            continue
        types = node_type(q)
        if "Question" not in types:
            findings.append(
                f"{url}: FAQPage mainEntity[{i}] @type={types or 'missing'} "
                "(expected Question)"
            )
            continue
        name = q.get("name")
        q_label = (
            (name if isinstance(name, str) and name.strip() else f"#{i}")[:40]
        )
        if not isinstance(name, str) or not name.strip():
            findings.append(f"{url}: FAQPage Question #{i} has no `name`")

        ans = q.get("acceptedAnswer")
        if not isinstance(ans, dict):
            findings.append(
                f"{url}: FAQPage Question {q_label!r} has no acceptedAnswer object"
            )
            continue
        text = ans.get("text")
        if not isinstance(text, str) or not text.strip():
            findings.append(
                f"{url}: FAQPage Question {q_label!r} has empty acceptedAnswer.text"
            )
    return findings


def _check_one_url(url: str) -> list[str]:
    try:
        html = fetch_html(url)
    except LiveFetchError:
        return []   # CHECK_090 reports per-URL transport errors
    out: list[str] = []
    for block in parse_jsonld_blocks(html):
        if block.parsed is None:
            continue
        for node in iter_jsonld_nodes(block.parsed):
            if not isinstance(node, dict):
                continue
            if "FAQPage" not in node_type(node):
                continue
            out.extend(_validate_faqpage(url, node))
    return out


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
    faqpages_seen = 0
    fetched = 0
    for url in urls:
        try:
            html = fetch_html(url)
        except LiveFetchError:
            continue
        fetched += 1
        for block in parse_jsonld_blocks(html):
            if block.parsed is None:
                continue
            for node in iter_jsonld_nodes(block.parsed):
                if isinstance(node, dict) and "FAQPage" in node_type(node):
                    faqpages_seen += 1
                    findings.extend(_validate_faqpage(url, node))

    if fetched == 0:
        return CheckResult(
            status="warn",
            message=f"all {len(urls)} sitemap URL(s) unreachable",
        )

    if not findings:
        if faqpages_seen == 0:
            return CheckResult(
                status="pass",
                message=f"no FAQPage blocks found across {fetched} URL(s)",
            )
        return CheckResult(
            status="pass",
            message=f"{faqpages_seen} FAQPage block(s) across {fetched} URL(s) are well-formed",
        )

    sample = "; ".join(findings[:3])
    return CheckResult(
        status="fail",
        message=f"{len(findings)} FAQPage shape issue(s) — {sample}",
    )
