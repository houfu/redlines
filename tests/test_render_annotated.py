r"""``Comparison.output_annotated`` (#181, ADR-0037): signature, grammar, goldens and the round trip.

The traversal is the render core's, pinned in ``tests/test_inplace_core.py``.
This file holds the public method to what ADR-0037 promises of it, calling
``output_annotated`` and nothing lower:

- **the signature** (decision D14): ``syntax=None`` follows the format the
  test side was read as, ``"html"`` is accepted and not yet rendered, any
  other value is a ``ValueError``, and both parameters are keyword-only;
- **the grammar**, one named test per production, on the renderer case that
  shows it, or on a pair of a few lines where no case does;
- **the goldens** of the five renderer cases, byte for byte;
- **hostile input**: the markdown variant accepts to ``test.md``'s own lines
  and rejects to ``source.md``'s, so every escape site, role-shaped text and
  pipe in a cell survives both ways, and the reader finds exactly the marks
  the renderer wrote;
- **the round trip** over the 60 committed runs, read back with the reference
  reader (``tests/helpers/criticmarkup.py``), with roles on and off:
  accept-all equals the test rendering exactly on all 60, and reject-all
  equals the source rendering as a multiset on 49 strictly and on 59 loosely.
  Every exception is named by run id, with its cause;
- **determinism** across ``PYTHONHASHSEED`` values.

The test rendering and the source rendering are the same method over
``compare(test, test)`` and ``compare(source, source)``.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from redlines.alignment import AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.comparison import BLOCKS_FORMAT, Comparison, compare
from redlines.pipeline import read_document
from redlines.renderers._inplace import layout, render_inplace
from redlines.renderers._marks import CRITIC
from tests.helpers import criticmarkup as cm
from tests.helpers.committed_runs import COMMITTED_RUN_COUNT, committed_runs
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = REPO_ROOT / "tests" / "renderer_cases"
CASE_NAMES = ("four_kinds", "hostile", "moved_neighbour", "nested_move", "trailing_insert")
GOLDENS = (("annotated.markdown.md", "markdown"), ("annotated.text.txt", "text"))
DIFFLIB = AlignmentConfig(similarity="difflib")
CSA = "benchmark/hand/csa-1.1-to-2.0"


def read(path: Path) -> str:
    with open(path, encoding="utf-8", newline="") as handle:
        return handle.read()


def case_texts(name: str) -> tuple[str, str]:
    return read(CASES / name / "source.md"), read(CASES / name / "test.md")


def md(source: str, test: str) -> Comparison:
    return compare(source, test, format="markdown", alignment=DIFFLIB)


def case(name: str) -> Comparison:
    return md(*case_texts(name))


def blocks(annotated: str) -> list[str]:
    """The output's blocks, which a blank line separates."""
    return annotated.split("\n\n")


def tree(*children: Block) -> BlockTree:
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=children))


def own_lines(document: str) -> list[str]:
    """A document's own non-blank lines, stripped: what the reader should give back."""
    return [line.strip() for line in document.split("\n") if line.strip()]


# --- the signature -------------------------------------------------------------------


def test_syntax_none_is_markdown_for_a_test_document_read_as_markdown() -> None:
    comparison = case("four_kinds")
    assert comparison.config.test_format == "markdown"
    assert comparison.output_annotated() == comparison.output_annotated(syntax="markdown")
    assert blocks(comparison.output_annotated())[0] == "## 1. Delivery"


def test_syntax_none_is_text_for_a_test_document_read_as_text() -> None:
    comparison = compare(
        "1. Delivery\n\n1.1 The Supplier shall deliver the goods.\n",
        "1. Delivery\n\n1.1 The Supplier must deliver the goods.\n",
        format="text",
        alignment=DIFFLIB,
    )
    assert comparison.config.test_format == "text"
    assert comparison.output_annotated() == (
        "1. Delivery\n\n[clause] 1.1 The Supplier {~~shall~>must~~} deliver the goods."
    )
    assert comparison.output_annotated(syntax="markdown").startswith("## 1. Delivery\n\n")


def test_syntax_none_follows_the_test_side_when_one_side_is_a_block_tree() -> None:
    source = "## 1. Delivery\n\n1.1 The Supplier shall deliver the goods.\n"
    test = "## 1. Delivery\n\n1.1 The Supplier must deliver the goods.\n"
    to_markdown = compare(read_document(source, format="markdown"), test, format="markdown")
    assert (to_markdown.config.source_format, to_markdown.config.test_format) == (
        BLOCKS_FORMAT,
        "markdown",
    )
    assert to_markdown.output_annotated().startswith("## 1. Delivery\n\n")
    to_tree = compare(source, read_document(test, format="markdown"), format="markdown")
    assert to_tree.config.test_format == BLOCKS_FORMAT
    assert to_tree.output_annotated().startswith("1. Delivery\n\n")


def test_syntax_none_is_text_for_a_comparison_of_two_block_trees() -> None:
    heading = Block(
        kind=BlockKind.HEADING,
        label="1",
        text="Delivery",
        level=1,
        attrs={"label_raw": "1.", "atx_level": 2},
    )
    comparison = compare(tree(heading), tree(heading))
    assert comparison.config.test_format == BLOCKS_FORMAT
    assert comparison.output_annotated() == "1. Delivery"
    assert comparison.output_annotated(syntax="markdown") == "## 1. Delivery"


def test_syntax_html_is_accepted_and_renders_the_document_view() -> None:
    rendered = case("four_kinds").output_annotated(syntax="html")
    assert rendered.startswith('<section class="redlines" data-redlines-view="document"')


@pytest.mark.parametrize("syntax", ["HTML", "Markdown", "TEXT", "md", "rich", "annotated", "", " text"])
def test_any_other_syntax_is_a_value_error_naming_the_accepted_ones(syntax: str) -> None:
    with pytest.raises(ValueError) as raised:
        case("four_kinds").output_annotated(syntax=syntax)  # type: ignore[arg-type]
    message = str(raised.value)
    for accepted in ("None", "'text'", "'markdown'", "'html'", repr(syntax)):
        assert accepted in message, message


def test_syntax_and_roles_are_keyword_only() -> None:
    comparison = case("four_kinds")
    with pytest.raises(TypeError):
        comparison.output_annotated("markdown")  # type: ignore[misc]


def test_roles_false_writes_no_role_prefix_and_needs_no_line_start_escape() -> None:
    comparison = case("hostile")
    with_roles = blocks(comparison.output_annotated())
    without = blocks(comparison.output_annotated(roles=False))
    assert with_roles[1].startswith("[clause] 1.1 The report")
    assert without[1].startswith("1.1 The report")
    # The document's own "[clause] " is escaped only where a reader would
    # otherwise strip it as a role prefix.
    own = "[clause] This paragraph begins like a role prefix."
    escaped = next(chunk for chunk in with_roles if "This paragraph begins" in chunk)
    as_written = next(chunk for chunk in without if "This paragraph begins" in chunk)
    assert escaped.startswith("\\" + own)
    assert as_written.startswith(own)
    # Otherwise the two differ by exactly the prefixes and the escapes: each,
    # read back with its own setting, gives the same lines.
    for syntax in ("markdown", "text"):
        on = comparison.output_annotated(syntax=syntax)  # type: ignore[arg-type]
        off = comparison.output_annotated(syntax=syntax, roles=False)  # type: ignore[arg-type]
        assert on != off
        for side in ("accept", "reject"):
            assert cm.lines(on, side, roles=True) == cm.lines(off, side, roles=False)


# --- the grammar ---------------------------------------------------------------------


def test_an_insertion_is_one_mark_with_the_syntax_head_and_role_outside_it() -> None:
    inline = md("Restore the Services within hours.\n", "Restore the Services within four hours.\n")
    assert inline.output_annotated() == "Restore the Services within {++four ++}hours."
    assert blocks(case("four_kinds").output_annotated())[3] == (
        "[clause] {++1.2 The Buyer may reject goods that do not match the order.++}"
    )
    subtree = md(
        "## 1. One\n\n1.1 First clause stays.\n",
        "## 1. One\n\n1.1 First clause stays.\n\n## 2. Two\n\n2.1 First new clause.\n\n"
        "(a) A new sub-clause under it.\n",
    )
    # Every text-bearing block of an inserted subtree is wrapped on its own.
    assert blocks(subtree.output_annotated()) == [
        "## 1. One",
        "[clause] 1.1 First clause stays.",
        "## {++2. Two++}",
        "[clause] {++2.1 First new clause.++}",
        "[sub_clause] {++(a) A new sub-clause under it.++}",
    ]


def test_a_deletion_stands_where_it_stood_with_the_syntax_head_and_role_outside_it() -> None:
    inline = md("Restore the Services within four hours.\n", "Restore the Services within hours.\n")
    assert inline.output_annotated() == "Restore the Services within {--four --}hours."
    assert blocks(case("trailing_insert").output_annotated())[-3:] == [
        "[clause] {++3.3 The Supplier may engage subcontractors with consent.++}",
        "## {--4. Fees--}",
        "[clause] {--4.1 The Client shall pay the Fees monthly.--}",
    ]
    assert blocks(case("four_kinds").output_annotated())[5:7] == [
        "[clause] 2.1 The Buyer shall pay each invoice within fourteen days of receiving it.",
        "[clause] {--2.2 Late payments carry interest at two per cent a month.--}",
    ]


def test_a_replacement_is_one_substitution_with_shared_trailing_whitespace_after_it() -> None:
    assert blocks(case("four_kinds").output_annotated())[1] == (
        "[clause] 1.1 The Supplier shall deliver the goods within "
        "{~~thirty (30~>sixty (60~~}) days of each order."
    )
    replaced = md("Restore within four hours.\n", "Restore within two hours.\n")
    assert replaced.output_annotated() == "Restore within {~~four~>two~~} hours."
    for name in CASE_NAMES:
        annotated = case(name).output_annotated()
        for spaced in ("{++ ", " ++}", "{-- ", " --}", "{~~ ", " ~~}", "{>> ", " <<}"):
            assert spaced not in annotated, (name, spaced)


def test_a_move_is_drawn_at_its_destination_with_a_note_and_a_tombstone_at_its_origin() -> None:
    for syntax in ("markdown", "text"):
        drawn = blocks(case("four_kinds").output_annotated(syntax=syntax))  # type: ignore[arg-type]
        # The origin line has no syntax head and no role, and stands where 1.2 stood.
        assert drawn[2] == "{>>1.2 moved to 2.2 /section[2]/list_item[2]<<}"
        assert drawn[-1] == (
            "[clause] {~~1.2~>2.2~~} Risk in the goods passes to the Buyer when the goods are "
            "unloaded at the Buyer's warehouse. {>>moved from 1.2 /section[1]/list_item[2]<<}"
        )
    neighbour = blocks(case("moved_neighbour").output_annotated())
    assert neighbour[2:5] == [
        "[clause] 7.2 Neither party shall make a public announcement about this Agreement "
        "without consent.",
        "{>>7.3 moved to 8.2 /section[2]/list_item[2]<<}",
        "[clause] {--7.4 This clause survives termination for a period of three years.--}",
    ]
    assert neighbour[-1].endswith(" {>>moved from 7.3 /section[1]/list_item[3]<<}")


def test_a_nested_move_draws_the_inner_tombstone_inside_the_outer_destination() -> None:
    assert blocks(case("nested_move").output_annotated()) == [
        "## 7. Confidentiality",
        "[clause] 7.1 Each party shall keep the other party's Confidential Information secret "
        "and use it only for this Agreement.",
        "{>>7.2 moved to 8.2 /section[2]/list_item[2]<<}",
        "## 8. Termination",
        "[clause] 8.1 Either party may terminate this Agreement on ninety days' written notice "
        "to the other party.",
        "[clause] {~~7.2~>8.2~~} Each party shall return or destroy the other party's "
        "Confidential Information on written request. "
        "{>>moved from 7.2 /section[1]/list_item[2]<<}",
        "[sub_clause] (a) The receiving party shall certify the destruction in writing within "
        "five Business Days.",
        "{>>(b) moved to 9.2 /section[3]/list_item[2]<<}",
        "## 9. Records",
        "[clause] 9.1 The Supplier shall keep complete records of the Services for six years "
        "after the end of the Term.",
        "[clause] {~~(b)~>9.2~~} The receiving party may keep one archival copy of the "
        "information for legal purposes only. "
        "{>>moved from (b) /section[1]/list_item[2]/list_item[2]<<}",
    ]


RENUMBER_SOURCE = (
    "## 3. Services\n\n3.1 The Supplier shall supply the Services.\n\n"
    "3.2 The Supplier shall meet the Service Levels.\n"
)
RENUMBER_TEST = (
    "## 3. Services\n\n3.1 The Supplier shall supply the Services.\n\n"
    "3.2 The Supplier may engage subcontractors with consent.\n\n"
    "3.3 The Supplier shall meet the Service Levels.\n"
)


def test_a_renumber_is_a_substitution_as_the_label_part() -> None:
    comparison = md(RENUMBER_SOURCE, RENUMBER_TEST)
    assert [change.kind.value for change in comparison.changes] == ["insert", "renumber"]
    for syntax in ("markdown", "text"):
        annotated = comparison.output_annotated(syntax=syntax)  # type: ignore[arg-type]
        assert blocks(annotated)[-1] == (
            "[clause] {~~3.2~>3.3~~} The Supplier shall meet the Service Levels."
        )
        assert cm.accept_all(annotated)[-1] == "3.3 The Supplier shall meet the Service Levels."
        assert cm.reject_all(annotated)[-1] == "3.2 The Supplier shall meet the Service Levels."


LIST_SOURCE = "1. Alpha item text\n2. Beta item text\n"
LIST_TEST = "1. New first item\n2. Alpha item text\n3. Beta item text\n"


def test_a_list_marker_renumber_is_a_note_in_markdown_and_a_substitution_in_text() -> None:
    comparison = md(LIST_SOURCE, LIST_TEST)
    markdown = comparison.output_annotated()
    assert blocks(markdown) == [
        "1. [clause] {++New first item++}",
        "2. [clause] {>>renumbered from 1.<<} Alpha item text",
        "3. [clause] {>>renumbered from 2.<<} Beta item text",
    ]
    assert blocks(comparison.output_annotated(syntax="text")) == [
        "[clause] {++1. New first item++}",
        "[clause] {~~1.~>2.~~} Alpha item text",
        "[clause] {~~2.~>3.~~} Beta item text",
    ]
    # The old marker lives only in the note, so reject-all keeps the test's
    # syntax head: equal to the source up to syntax heads, not strictly.
    source_rendering = cm.reject_all(md(LIST_SOURCE, LIST_SOURCE).output_annotated())
    rejected = cm.reject_all(markdown)
    assert rejected == ["2. Alpha item text", "3. Beta item text"]
    assert not cm.multiset(rejected, source_rendering)
    assert cm.loose_multiset(rejected, source_rendering)


def test_a_role_prefix_follows_the_syntax_head_in_markdown_and_opens_the_line_in_text() -> None:
    heading = Block(
        kind=BlockKind.HEADING,
        label="1",
        text="Background",
        level=1,
        role="recital",
        attrs={"label_raw": "1.", "atx_level": 2},
    )
    item = Block(
        kind=BlockKind.LIST_ITEM,
        label="3",
        text="The Supplier shall report monthly.",
        role="schedule",
        attrs={"list_marker": "3.", "label_source": "list_marker", "list_depth": 1},
    )
    quote = Block(
        kind=BlockKind.PARAGRAPH, text="line one\nline two", role="quote", attrs={"quote": True}
    )
    odd = Block(kind=BlockKind.PARAGRAPH, text="Odd role.", role="a]b r~s%")
    comparison = compare(tree(heading, item, quote, odd), tree(heading, item, quote, odd))
    assert blocks(comparison.output_annotated(syntax="markdown")) == [
        "## [recital] 1. Background",
        "3. [schedule] The Supplier shall report monthly.",
        "> [quote] line one\n> line two",
        "[a%5Db%20r%7Es%25] Odd role.",
    ]
    assert blocks(comparison.output_annotated(syntax="text")) == [
        "[recital] 1. Background",
        "[schedule] 3. The Supplier shall report monthly.",
        "[quote] line one\nline two",
        "[a%5Db%20r%7Es%25] Odd role.",
    ]
    assert blocks(comparison.output_annotated(syntax="markdown", roles=False)) == [
        "## 1. Background",
        "3. The Supplier shall report monthly.",
        "> line one\n> line two",
        "Odd role.",
    ]
    # The encoding is reversible: the reader gets the role back as it was.
    assert cm.split_role("[a%5Db%20r%7Es%25] Odd role.")[1] == "a]b r~s%"


def test_a_role_prefix_is_never_written_on_a_table_a_fence_or_a_tombstone() -> None:
    cell = Block(kind=BlockKind.CELL, text="a", role="schedule")
    row = Block(kind=BlockKind.ROW, role="schedule", children=(cell,))
    table = Block(kind=BlockKind.TABLE, role="schedule", children=(row,))
    fence = Block(kind=BlockKind.PARAGRAPH, text="x = 1", role="code", attrs={"fence": "python"})
    comparison = compare(tree(table, fence), tree(table, fence))
    assert blocks(comparison.output_annotated(syntax="markdown")) == [
        "| a |\n| --- |",
        "```python\nx = 1\n```",
    ]
    moved = case("four_kinds")
    origin = next(change for change in moved.changes if change.kind.value == "move")
    assert origin.role == "clause"
    assert "{>>1.2 moved to 2.2 /section[2]/list_item[2]<<}" in blocks(moved.output_annotated())


DROPPING_SOURCE = "Intro.\n\n***\n\nThe first clause stays.\n"
DROPPING_TEST = "Intro.\n\n***\n\nThe first clause stays, edited.\n"


def test_the_header_notes_appear_only_when_true_and_in_order() -> None:
    assert not case("four_kinds").output_annotated().startswith("{>>")
    comparison = md(DROPPING_SOURCE, DROPPING_TEST)
    assert comparison.source.dropped and comparison.test.dropped
    dropped = [
        f"{{>>{side} dropped {item.count} {item.kind}: {item.reason}<<}}"
        for side, side_tree in (("source", comparison.source), ("test", comparison.test))
        for item in side_tree.dropped
    ]
    assert blocks(comparison.output_annotated())[: len(dropped)] == dropped
    assert blocks(comparison.output_annotated())[len(dropped)] == "Intro."
    filtered = comparison.filter(kinds=("modify", "insert"), min_chars=1, has_inline=True)
    stopped = dataclasses.replace(
        filtered, config=dataclasses.replace(filtered.config, budget_exhausted=True)
    )
    assert blocks(stopped.output_annotated())[: 2 + len(dropped)] == [
        "{>>filtered: kinds=modify,insert; min_chars=1; has_inline=true<<}",
        "{>>alignment stopped early: the comparison budget ran out<<}",
        *dropped,
    ]
    # A filter whose every field is empty narrows nothing and says nothing.
    assert blocks(comparison.filter().output_annotated())[0] == dropped[0]
    # The notes come off with the reader's strip_notes and leave no residue.
    assert cm.accept_all(stopped.output_annotated()) == cm.accept_all(
        md(DROPPING_TEST, DROPPING_TEST).output_annotated()
    )


def _table(annotated: str) -> str:
    return next(chunk for chunk in blocks(annotated) if chunk.startswith("| Item | Note |"))


def test_a_table_is_marked_one_cell_at_a_time_with_pipes_in_cells_escaped() -> None:
    table = _table(case("hostile").output_annotated())
    assert table == (
        "| Item | Note |\n"
        "| --- | --- |\n"
        "| a \\| b | plain |\n"
        "| ~\\> | {~~x++\\}~>y++\\}~~} |\n"
        "| {++new \\| row++} | {++\\{++z++\\}++} |"
    )
    text_table = _table(case("hostile").output_annotated(syntax="text"))
    assert text_table == "\n".join(line for line in table.split("\n") if line != "| --- | --- |")
    # No mark spans a cell separator: each row's cells parse on their own.
    for row in table.split("\n"):
        for cell in re.split(r"(?<!\\) \| ", row.strip("| ")):
            cm.parse(cell)


def test_a_fence_carries_its_marks_inside_and_outgrows_its_longest_backtick_run() -> None:
    assert blocks(case("hostile").output_annotated())[-1] == (
        '```python\nif a { b++ }\nprint({~~"++\\}"~>"++\\} --\\}"~~})\n```'
    )
    longer = md("````js\ncode with ``` inside\n````\n", "````js\ncode with ``` inside and more\n````\n")
    assert longer.output_annotated() == "````js\ncode with ``` inside {++and more++}\n````"
    assert longer.output_annotated(syntax="text") == "code with ``` inside {++and more++}"


def test_a_filtered_comparison_marks_only_its_own_nodes() -> None:
    comparison = case("four_kinds")
    filtered = comparison.filter(kinds=("modify",))
    assert blocks(filtered.output_annotated()) == [
        "{>>filtered: kinds=modify<<}",
        "## 1. Delivery",
        "[clause] 1.1 The Supplier shall deliver the goods within "
        "{~~thirty (30~>sixty (60~~}) days of each order.",
        "[clause] 1.2 The Buyer may reject goods that do not match the order.",
        "## 2. Payment",
        "[clause] 2.1 The Buyer shall pay each invoice within fourteen days of receiving it.",
        "[clause] 2.2 Risk in the goods passes to the Buyer when the goods are unloaded at the "
        "Buyer's warehouse.",
    ]
    test = case_texts("four_kinds")[1]
    test_rendering = md(test, test).output_annotated()
    assert cm.accept_all(filtered.output_annotated()) == cm.accept_all(test_rendering)


# --- the goldens ---------------------------------------------------------------------


@pytest.mark.parametrize("golden, syntax", GOLDENS)
@pytest.mark.parametrize("name", CASE_NAMES)
def test_each_renderer_case_matches_its_golden(name: str, golden: str, syntax: str) -> None:
    rendered = case(name).output_annotated(syntax=syntax)  # type: ignore[arg-type]
    assert rendered == read(CASES / name / golden), (
        f"tests/renderer_cases/{name}/{golden} no longer matches output_annotated(). If the "
        "change is intentional, regenerate with: uv run python tests/renderer_cases/regenerate.py"
    )


# --- hostile input -------------------------------------------------------------------


@pytest.mark.parametrize("roles", [True, False], ids=["roles", "no_roles"])
@pytest.mark.parametrize("name", CASE_NAMES)
def test_each_case_accepts_to_its_own_test_document_and_rejects_to_its_source(
    name: str, roles: bool
) -> None:
    """The input files are the oracle here, not another rendering."""
    source, test = case_texts(name)
    annotated = md(source, test).output_annotated(roles=roles)
    assert cm.accept_all(annotated, roles=roles) == own_lines(test)
    assert Counter(cm.reject_all(annotated, roles=roles)) == Counter(own_lines(source))


def test_every_escape_site_in_the_hostile_case_is_escaped_where_it_is_written() -> None:
    annotated = case("hostile").output_annotated()
    for escaped in (
        "A literal \\{++x++\\} and an arrow ~\\> stay as typed",  # opener, closer, separator
        "{~~\\\\\\{--this--\\}.~>",  # a backslash before an opener: one becomes three
        "C:\\dir\\\\{--(old)--}",  # a run ending the text before a live delimiter is doubled
        "ends in a backslash \\\\++}",  # likewise before a closer
        "says ~\\> and ++\\} and <<\\} and",
        "\\[clause] This paragraph begins like a role prefix.",  # the line-start site
        "- \\[x] A task item",  # the line-start site after a syntax head
        "- \\\\\\[y] A second task item",  # the line-start site with a backslash run
        "| a \\| b | plain |",  # a pipe in a cell
    ):
        assert escaped in annotated, escaped
    accepted = cm.accept_all(annotated)
    for line in (
        "1.2 A literal {++x++} and an arrow ~> stay as typed, and so does \\{--this--} and {--that--}.",
        "1.5 An inserted clause says ~> and ++} and <<} and ends in a backslash \\",
        "[clause] This paragraph begins like a role prefix.",
        "- [x] A task item that looks like a role, edited.",
        "- \\[y] A second task item with a backslash before its bracket.",
        '| new \\| row | {++z++} |',
        'print("++} --}")',
    ):
        assert line in accepted, line
    rejected = cm.reject_all(annotated)
    for line in (
        "1.4 Archives are kept in C:\\dir\\(old)",
        "1.6 This clause goes, with <b>bold</b> & {~~a substitution~>of its own~~}.",
        "| ~> | x++} |",
        'print("++}")',
    ):
        assert line in rejected, line


@pytest.mark.parametrize("roles", [True, False], ids=["roles", "no_roles"])
@pytest.mark.parametrize("syntax", ["markdown", "text"])
@pytest.mark.parametrize("name", CASE_NAMES)
def test_the_reader_finds_exactly_the_marks_the_renderer_wrote(
    name: str, syntax: str, roles: bool
) -> None:
    """No live delimiter is left in document text: every mark parsed is one the layout wrote."""
    comparison = case(name)
    written = [
        piece.kind
        for chunk in layout(comparison, CRITIC, syntax=syntax, roles=roles)  # type: ignore[arg-type]
        for piece in chunk.pieces
        if piece.kind in ("insert", "delete", "substitution", "note")
    ]
    annotated = comparison.output_annotated(syntax=syntax, roles=roles)  # type: ignore[arg-type]
    assert [token.kind for token in cm.parse(annotated) if token.kind != "text"] == written


# --- the 60 committed runs -----------------------------------------------------------


WHITESPACE_RUNS = (
    "tests/corpus/course_lesson6",
    "tests/corpus/whitespace_after_equal",
    "benchmark/synthetic/adr-moves-mixed",
    "benchmark/synthetic/msa-markdown-table",
    "benchmark/synthetic/msa-text-heavy",
)
"""Reject-all differs from the source rendering in whitespace only: unchanged
runs carry the test's whitespace at change boundaries."""

SYNTAX_HEAD_RUNS = (
    "benchmark/synthetic/msa-markdown-mixed",
    "benchmark/synthetic/msa-markdown-move-heavy",
    "benchmark/synthetic/msa-markdown-renumber-storm",
    "benchmark/synthetic/msa-markdown-structure",
    "benchmark/hand/sla-1.0-to-2.0",
)
"""Reject-all differs in syntax heads too, which come from the test block:
shifted ordered-list numbers, or a paragraph that became a list item."""

NOTE_RUNS = (CSA,)
"""Reject-all cannot restore what lives only in a note: csa-1.1-to-2.0's test
turned numbered paragraphs into an ordered list, so old clause numbers are in
``{>>renumbered from …<<}`` notes."""

STRICT_EXCEPTIONS = sorted(WHITESPACE_RUNS + SYNTAX_HEAD_RUNS + NOTE_RUNS)
LOOSE_EXCEPTIONS = sorted(NOTE_RUNS)
BARE_ACCEPT_EXCEPTIONS = sorted(
    (
        "benchmark/synthetic/msa-markdown-table",
        "benchmark/synthetic/twin-markdown-heavy",
        "benchmark/synthetic/twin-markdown-mixed",
        CSA,
    )
)
"""Where accept-all needs the residue rule: a removed mark leaves a bare syntax
head, an empty row or an orphaned alignment row behind."""

_WHITESPACE = re.compile(r"\s+")


def _without_whitespace(lines: list[str]) -> list[str]:
    return [_WHITESPACE.sub("", line) for line in lines]


def _sweep(roles: bool) -> dict[str, list[str]]:
    """Every committed run through output_annotated and back through the reader."""
    found: dict[str, list[str]] = {
        key: [] for key in ("wiring", "accept", "accept_bare", "strict", "loose", "whitespace")
    }
    for run in committed_runs():
        source, test = run.texts()
        comparison = compare(source, test, format=run.format)
        annotated = comparison.output_annotated(roles=roles)
        if annotated != render_inplace(
            comparison, CRITIC, syntax=run.format, roles=roles  # type: ignore[arg-type]
        ):
            found["wiring"].append(run.name)
        test_rendering = compare(test, test, format=run.format).output_annotated(roles=roles)
        if not cm.exact(cm.accept_all(annotated, roles=roles), cm.accept_all(test_rendering, roles=roles)):
            found["accept"].append(run.name)
        bare = [line.strip() for line in cm.lines(annotated, "accept", roles=roles) if line.strip()]
        bare_test = [
            line.strip() for line in cm.lines(test_rendering, "accept", roles=roles) if line.strip()
        ]
        if bare != bare_test:
            found["accept_bare"].append(run.name)
        rejected = cm.reject_all(annotated, roles=roles)
        source_rendering = cm.reject_all(
            compare(source, source, format=run.format).output_annotated(roles=roles), roles=roles
        )
        if not cm.multiset(rejected, source_rendering):
            found["strict"].append(run.name)
            if cm.multiset(_without_whitespace(rejected), _without_whitespace(source_rendering)):
                found["whitespace"].append(run.name)
        if not cm.loose_multiset(rejected, source_rendering):
            found["loose"].append(run.name)
    return {key: sorted(names) for key, names in found.items()}


@pytest.fixture(scope="module", params=[True, False], ids=["roles", "no_roles"])
def sweep(request: pytest.FixtureRequest) -> dict[str, list[str]]:
    roles = request.param
    assert isinstance(roles, bool)
    return _sweep(roles)


def test_the_committed_runs_are_the_sixty_the_adr_measured() -> None:
    runs = committed_runs()
    assert len(runs) == COMMITTED_RUN_COUNT == 60
    assert len({(run.source, run.test, run.format) for run in runs}) == 59


def test_output_annotated_is_the_core_criticmarkup_rendering_in_the_runs_own_syntax(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["wiring"] == []


def test_accept_all_reproduces_the_test_rendering_exactly_on_all_60_runs(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["accept"] == []


def test_without_the_residue_rule_accept_all_fails_on_exactly_these_four_runs(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["accept_bare"] == BARE_ACCEPT_EXCEPTIONS


def test_reject_all_is_a_strict_multiset_on_49_runs_and_these_11_are_the_exceptions(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["strict"] == STRICT_EXCEPTIONS
    assert len(STRICT_EXCEPTIONS) == 11


def test_the_strict_exceptions_differ_in_whitespace_or_in_syntax_heads_or_in_notes(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["whitespace"] == sorted(WHITESPACE_RUNS)
    loose_only = sorted(set(sweep["strict"]) - set(sweep["whitespace"]) - set(sweep["loose"]))
    assert loose_only == sorted(SYNTAX_HEAD_RUNS)


def test_reject_all_is_a_loose_multiset_on_59_runs_with_csa_the_one_exception(
    sweep: dict[str, list[str]],
) -> None:
    assert sweep["loose"] == LOOSE_EXCEPTIONS == [CSA]


def _with_renumber_notes_as_labels(annotated: str) -> list[str]:
    """Reject-all, with each ``{>>renumbered from OLD<<}`` read as the label ``OLD``."""
    tokens = [
        cm.Token("text", token.text.removeprefix("renumbered from "))
        if token.kind == "note" and token.text.startswith("renumbered from ")
        else token
        for token in cm.parse(annotated)
    ]
    resolved = cm.resolve(tokens, "reject").split("\n")
    return cm.residue([cm.read_line(line) for line in resolved])


def test_csa_misses_only_old_labels_that_live_in_notes_and_one_dot_only_relabel() -> None:
    """Why csa-1.1-to-2.0 is the loose exception, line by line.

    26 source lines are missing from its reject-all. 25 come back as soon as
    each renumber note's old label is read as the line's label, which is what
    "except where an old list-marker label moved into a note" means. The 26th
    is clause 2.1, written ``2.1`` in the source and ``2.1.`` in the test:
    equal labels make no change node, so nothing marks the full stop.
    """
    run = next(run for run in committed_runs() if run.name == CSA)
    source, test = run.texts()
    annotated = compare(source, test, format=run.format).output_annotated()
    source_rendering = cm.loose(
        cm.reject_all(compare(source, source, format=run.format).output_annotated())
    )
    missing = Counter(source_rendering) - Counter(cm.loose(cm.reject_all(annotated)))
    assert sum(missing.values()) == 26
    restored = Counter(cm.loose(_with_renumber_notes_as_labels(annotated)))
    assert Counter(source_rendering) - restored == Counter({"2.1RestrictionsonCustomer.": 1})
    assert restored - Counter(source_rendering) == Counter({"2.1.RestrictionsonCustomer.": 1})


# --- determinism ---------------------------------------------------------------------


def test_the_renderer_cases_render_the_same_bytes_under_every_hash_seed() -> None:
    """Every output under five hash seeds, as ASCII-safe JSON: the hostile case is not ASCII."""
    script = """
import json
import sys
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
cases = Path("tests/renderer_cases")
outputs = {}
for name in ("four_kinds", "hostile", "moved_neighbour", "nested_move", "trailing_insert"):
    with open(cases / name / "source.md", encoding="utf-8", newline="") as handle:
        source = handle.read()
    with open(cases / name / "test.md", encoding="utf-8", newline="") as handle:
        test = handle.read()
    comparison = compare(source, test, format="markdown", alignment=AlignmentConfig(similarity="difflib"))
    for syntax in ("markdown", "text"):
        for roles in (True, False):
            outputs[f"{name}/{syntax}/{roles}"] = comparison.output_annotated(syntax=syntax, roles=roles)
sys.stdout.write(json.dumps(outputs))
"""
    outputs = json.loads(assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT))
    assert len(outputs) == len(CASE_NAMES) * 4
    for name in CASE_NAMES:
        for golden, syntax in GOLDENS:
            assert outputs[f"{name}/{syntax}/True"] == read(CASES / name / golden), (name, golden)
