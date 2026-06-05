"""v29.E — offline backfill primitives: the `AI_AGENTS.md` → sections
parser and the gated `set_content_block` replace.

No network: the parser is pure text, and `set_content_block` never calls
the LLM (the fixer does, tested separately with a mock).
"""
from __future__ import annotations

import tomllib

from portfolio import content_derive
from portfolio import lamill_toml_edit as edit
from portfolio.lamill_toml import LAMILL_TOML_FILENAME

# A realistic AI_AGENTS.md: brief H2 sections each with the template's
# italic hint, one left as the placeholder, and a `### Post-deploy
# checklist` H3 trailing Content strategy that must NOT leak into it.
_AI_AGENTS = """# AI Agent Context — demo.com

## Summary

*one paragraph: what this site is, what it does*

Demo turns raw logs into shareable incident timelines.

## Audience

*one sentence: who this is for (broad demographic)*

(to be filled in)

## ICP

*the specific ideal customer — demographics, pain points*

Mid-market SRE teams with a compliance mandate and an existing on-call rotation.

## Goals

*1-2 sentences: primary business / product goal*

Become the reference tool SREs reach for during a postmortem.

## Tech stack

Astro project under the sites/* workspace.

## Content strategy

*what content this site needs — page types, topics, format mix*

pSEO pages like "how to write a postmortem for [incident type]"; tone is direct, technical, no fluff.

### Post-deploy checklist

- [ ] Verify in Google Search Console
- [ ] Submit the sitemap
"""


# ---- parser ---------------------------------------------------------


def test_parser_extracts_filled_brief_sections():
    out = content_derive.parse_ai_agents_sections(_AI_AGENTS)
    assert out["Summary"] == "Demo turns raw logs into shareable incident timelines."
    assert out["ICP"].startswith("Mid-market SRE teams")
    assert out["Goals"].startswith("Become the reference tool")
    assert out["Content strategy"].startswith('pSEO pages like "how to write a postmortem')


def test_parser_drops_placeholder_section():
    out = content_derive.parse_ai_agents_sections(_AI_AGENTS)
    assert "Audience" not in out  # was "(to be filled in)" → empty → dropped


def test_parser_excludes_h3_subsection_from_content_strategy():
    out = content_derive.parse_ai_agents_sections(_AI_AGENTS)
    assert "Post-deploy checklist" not in out["Content strategy"]
    assert "sitemap" not in out["Content strategy"]


def test_parser_omits_non_brief_headings():
    out = content_derive.parse_ai_agents_sections(_AI_AGENTS)
    assert "Tech stack" not in out  # not a brief section


def test_sections_from_repo_reads_file(tmp_path):
    (tmp_path / "AI_AGENTS.md").write_text(_AI_AGENTS, encoding="utf-8")
    out = content_derive.sections_from_repo(tmp_path)
    assert out["ICP"].startswith("Mid-market SRE teams")


def test_sections_from_repo_absent_file_is_empty(tmp_path):
    assert content_derive.sections_from_repo(tmp_path) == {}


# ---- set_content_block (gated replace) ------------------------------

_PREFIX = (
    "# lamill.toml for test\n"
    'schema = "lamill-toml-v1"\n'
    "\n"
    "[deploy]\n"
    'platform = "cf-pages"\n'
    "\n"
    "[[todo]]\n"
    'status = "open"\n'
    'task = "ship"\n'
    "\n"
)


def _write_toml(tmp_path, *, with_content=True):
    text = _PREFIX + (edit.CONTENT_SKELETON if with_content else "")
    (tmp_path / LAMILL_TOML_FILENAME).write_text(text)
    return tmp_path


def _content_table(tmp_path):
    raw = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    return tomllib.loads(raw)["content"]


def test_set_content_block_replaces_blank_skeleton(tmp_path):
    _write_toml(tmp_path)
    wrote = edit.set_content_block(tmp_path, {
        "site_type": "tool",
        "primary_keyword": "postmortem template",
        "secondary_keywords": ["incident timeline", "on-call postmortem"],
        "icp": 'An SRE who "owns the postmortem" after a Sev1.',
    })
    assert wrote is True
    table = _content_table(tmp_path)
    assert table["site_type"] == "tool"
    assert table["primary_keyword"] == "postmortem template"
    assert table["secondary_keywords"] == ["incident timeline", "on-call postmortem"]
    assert table["icp"].startswith("An SRE")
    # untouched fields stay empty
    assert table["penalty"] == ""


def test_set_content_block_byte_preserves_the_rest(tmp_path):
    _write_toml(tmp_path)
    edit.set_content_block(tmp_path, {"site_type": "tool"})
    new = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert new.startswith(_PREFIX)  # schema/deploy/todo untouched, byte-for-byte


def test_set_content_block_refuses_to_clobber_populated(tmp_path):
    _write_toml(tmp_path)
    assert edit.set_content_block(tmp_path, {"site_type": "tool"}) is True
    # second call on a now-populated block must not overwrite
    assert edit.set_content_block(tmp_path, {"site_type": "directory"}) is False
    assert _content_table(tmp_path)["site_type"] == "tool"


def test_set_content_block_no_real_seeds_is_noop(tmp_path):
    _write_toml(tmp_path)
    before = (tmp_path / LAMILL_TOML_FILENAME).read_text()
    assert edit.set_content_block(tmp_path, {}) is False
    assert edit.set_content_block(tmp_path, {"site_type": "", "secondary_keywords": []}) is False
    assert (tmp_path / LAMILL_TOML_FILENAME).read_text() == before


def test_set_content_block_appends_when_absent(tmp_path):
    _write_toml(tmp_path, with_content=False)
    assert edit.set_content_block(tmp_path, {"site_type": "tool"}) is True
    assert _content_table(tmp_path)["site_type"] == "tool"


def test_content_is_blank_helpers(tmp_path):
    _write_toml(tmp_path)
    assert edit.content_is_blank(edit.content_field_values(tmp_path)) is True
    edit.set_content_block(tmp_path, {"site_type": "tool"})
    assert edit.content_is_blank(edit.content_field_values(tmp_path)) is False


# ---- the "Fill in [content]" todo close (v29.F gate, second half) ----

_PREFIX_FILLIN = (
    'schema = "lamill-toml-v1"\n\n'
    "[deploy]\n"
    'platform = "cf-pages"\n\n'
    "[[todo]]\n"
    'status = "open"\n'
    'priority = "high"\n'
    'task = "Fill in [content] block (site_type, primary_keyword, icp, …)"\n\n'
    "[[todo]]\n"
    'status = "open"\n'
    'task = "ship"\n\n'
)


def test_complete_content_todo_marks_fillin_done(tmp_path):
    from portfolio import lamill_toml
    (tmp_path / LAMILL_TOML_FILENAME).write_text(_PREFIX_FILLIN + edit.CONTENT_SKELETON)
    assert edit.complete_content_todo(tmp_path) is True
    todos = lamill_toml.load(tmp_path).todos
    fillin = [t for t in todos if t.task.lower().startswith("fill in [content]")][0]
    assert fillin.status == "done"
    # the unrelated todo is untouched
    assert any(t.task == "ship" and t.status == "open" for t in todos)


def test_complete_content_todo_noop_when_no_fillin(tmp_path):
    _write_toml(tmp_path)  # only a "ship" todo
    assert edit.complete_content_todo(tmp_path) is False


def test_content_todo_blanks():
    assert edit.content_todo_blanks(None) == list(edit.CONTENT_TODO_FIELDS)
    assert "law" not in edit.CONTENT_TODO_FIELDS  # blank law is a normal end state
    one = {"site_type": "tool"}
    assert edit.content_todo_blanks(one) == [f for f in edit.CONTENT_TODO_FIELDS if f != "site_type"]
    full = {f: "x" for f in edit.CONTENT_TODO_FIELDS}
    assert edit.content_todo_blanks(full) == []
