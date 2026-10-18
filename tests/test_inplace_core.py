r"""The in-place traversal (ADR-0037): splice, line syntax, labels, tables, notes, and the oracle.

``redlines/renderers/_inplace.py`` is the one walk every in-place output
shares. Its rules are pinned here with the two sets that emit strings today,
the legacy ``none`` style and CriticMarkup, on the renderer cases and on
constructed inputs. Then the claims ADR-0037 makes on the 60 committed runs,
read back with the reference reader (``tests/helpers/criticmarkup.py``):

- accept-all equals the test rendering exactly, line for line, on 60 of 60;
- reject-all equals the source rendering as a multiset on 49 of 60 strictly
  and 59 of 60 loosely, the one loose exception being
  ``benchmark/hand/csa-1.1-to-2.0``, whose old clause numbers live only in
  ``{>>renumbered from …<<}`` notes;
- for the ``none`` style, accept-all is exact and reject-all keeps source
  order, up to whitespace and syntax heads, on 60 of 60, because the legacy
  styles strike a moved block at its origin.

The test rendering and the source rendering are the same renderer over
``compare(test, test)`` and ``compare(source, source)``.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import re
from pathlib import Path

import pytest

from redlines import Redlines
from redlines.alignment import AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.changes import Change, ChangeKind, InlineKind, InlineOp
from redlines.comparison import Comparison, compare
from redlines.enums import MarkdownStyle
from redlines.renderers._inplace import (
    Segment,
    inline_segments,
    label_text,
    layout,
    render_inplace,
)
from redlines.renderers._marks import CRITIC, LEGACY, MarkSet, custom_css
from tests.helpers import criticmarkup as cm
from tests.helpers.committed_runs import committed_runs
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
CASES = Path(__file__).parent / "renderer_cases"
CASE_NAMES = ["four_kinds", "moved_neighbour", "nested_move", "trailing_insert", "hostile"]
DIFFLIB = AlignmentConfig(similarity="difflib")
NONE = LEGACY["none"]


def case_texts(name: str) -> tuple[str, str]:
    directory = CASES / name
    with open(directory / "source.md", encoding="utf-8", newline="") as source:
        with open(directory / "test.md", encoding="utf-8", newline="") as test:
            return source.read(), test.read()


def md(source: str, test: str) -> Comparison:
    return compare(source, test, format="markdown", alignment=DIFFLIB)


def tree(*blocks: Block) -> BlockTree:
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=blocks))


def critic(comparison: Comparison, syntax: str = "markdown", roles: bool = True) -> str:
    assert syntax in ("text", "markdown")
    return render_inplace(comparison, CRITIC, syntax=syntax, roles=roles)  # type: ignore[arg-type]


def none(comparison: Comparison, syntax: str = "markdown") -> str:
    assert syntax in ("text", "markdown")
    return render_inplace(comparison, NONE, syntax=syntax, roles=False)  # type: ignore[arg-type]


def round_trips(source: str, test: str, *, syntax: str = "markdown", roles: bool = True) -> None:
    """The annotated text accepts to the test rendering and rejects to the source one."""
    annotated = critic(md(source, test), syntax, roles)
    expected_test = cm.accept_all(critic(md(test, test), syntax, roles), roles=roles)
    expected_source = cm.reject_all(critic(md(source, source), syntax, roles), roles=roles)
    assert cm.accept_all(annotated, roles=roles) == expected_test
    assert cm.multiset(cm.reject_all(annotated, roles=roles), expected_source)


# --- the inline splice --------------------------------------------------------


def _change(source: str, test: str, *ops: InlineOp) -> Change:
    return Change(
        kind=ChangeKind.MODIFY,
        source_address="/paragraph[1]",
        test_address="/paragraph[1]",
        block_kind=BlockKind.PARAGRAPH,
        matched_by="exact",
        confidence=1.0,
        source_text=source,
        test_text=test,
        inline=ops,
    )


def test_inline_segments_tile_both_texts_with_the_ops_in_order() -> None:
    change = md(
        "The Supplier shall deliver within thirty days, at its cost.",
        "The Supplier must deliver within sixty days.",
    ).changes[0]
    segments = inline_segments(change)
    assert "".join(s.test_text for s in segments) == change.test_text
    assert "".join(s.source_text for s in segments) == change.source_text
    assert [s.kind for s in segments if s.kind != "equal"] == [
        op.kind.value for op in change.inline
    ]
    assert segments[0] == Segment("equal", "The Supplier ", "The Supplier ")


def test_an_equal_run_carries_both_sides_and_ops_that_overlap_are_clamped() -> None:
    change = _change(
        "a  b c",
        "a b x",
        InlineOp(InlineKind.REPLACE, 5, 6, 4, 5, "c", "x"),
        InlineOp(InlineKind.INSERT, 3, 3, 2, 2, "", ""),  # starts before the last one ended
    )
    segments = inline_segments(change)
    assert segments[0] == Segment("equal", "a  b ", "a b ")
    assert "".join(s.test_text for s in segments) == "a b x"
    assert "".join(s.source_text for s in segments) == "a  b c"


def test_a_change_with_no_ops_is_one_equal_run() -> None:
    assert inline_segments(_change("same", "same")) == (Segment("equal", "same", "same"),)


def test_a_critic_substitution_writes_the_whitespace_both_sides_end_with_after_it() -> None:
    comparison = md("Restore within four hours.", "Restore within two hours.")
    assert critic(comparison) == "Restore within {~~four~>two~~} hours."
    assert none(comparison) == "Restore within <del>four </del><ins>two </ins>hours."


# --- the mark sets ----------------------------------------------------------------


def test_the_legacy_sets_are_the_six_styles_and_custom_css() -> None:
    assert list(LEGACY) == [style.value for style in MarkdownStyle] + ["custom_css"]
    for name, marks in LEGACY.items():
        assert marks.name == name
        assert marks.whole_moves and marks.substitution is None
        assert not marks.notes and not marks.roles and marks.escape == "none"
    assert CRITIC.notes and CRITIC.roles and not CRITIC.whole_moves


README_SOURCE = "The quick brown fox jumps over the lazy dog."
README_TEST = "The quick brown fox walks past the lazy dog."


@pytest.mark.parametrize("style", list(LEGACY))
def test_the_legacy_sets_spell_the_readme_pair_exactly_as_0_6_does(style: str) -> None:
    rendered = render_inplace(
        compare(README_SOURCE, README_TEST, format="text"),
        LEGACY[style],
        syntax="text",
        roles=False,
    )
    assert rendered == Redlines(README_SOURCE, README_TEST, markdown_style=style).output_markdown


def test_custom_css_takes_its_classes_as_0_6_does() -> None:
    marks: MarkSet = custom_css("added", "removed")
    rendered = render_inplace(
        compare(README_SOURCE, README_TEST, format="text"), marks, syntax="text", roles=False
    )
    expected = Redlines(
        README_SOURCE, README_TEST, markdown_style="custom_css", ins_class="added", del_class="removed"
    ).output_markdown
    assert rendered == expected


def test_render_inplace_refuses_an_unknown_syntax_and_roles_on_a_legacy_set() -> None:
    comparison = md("a", "b")
    with pytest.raises(ValueError, match="syntax"):
        render_inplace(comparison, CRITIC, syntax="html", roles=True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="shows no roles"):
        render_inplace(comparison, NONE, syntax="markdown", roles=True)


# --- line syntax ------------------------------------------------------------------


def test_headings_and_list_items_take_their_heads_from_attrs() -> None:
    text = "# One\n\n### Three\n\n- top\n    - nested\n        - deeper\n\n1. ordered\n"
    rendered = critic(md(text, text), roles=False)
    assert rendered.split("\n\n") == [
        "# One",
        "### Three",
        "- top",
        "    - nested",
        "        - deeper",
        "1. ordered",
    ]
    assert none(md(text, text), syntax="text").split("\n\n") == [
        "One",
        "Three",
        "top",
        "nested",
        "deeper",
        "1. ordered",
    ]


def test_a_heading_without_an_atx_level_gets_level_plus_one_hashes() -> None:
    heading = tree(Block(kind=BlockKind.HEADING, text="Title", level=2))
    assert critic(compare(heading, heading), roles=False) == "### Title"


def test_a_quote_puts_its_marker_before_every_physical_line() -> None:
    source = "> A quoted paragraph that changes slightly.\n\n> ```\n> code here\n> ```\n"
    test = "> A quoted paragraph that changes a little.\n\n> ```\n> code here too\n> ```\n"
    assert critic(md(source, test)).split("\n\n") == [
        "> A quoted paragraph that changes {~~slightly.~>a little.~~}",
        "> ```\n> code here {++too++}\n> ```",
    ]
    round_trips(source, test)
    paragraph = tree(
        Block(kind=BlockKind.PARAGRAPH, text="line one\nline two", attrs={"quote": True}, role="quote")
    )
    assert critic(compare(paragraph, paragraph)) == "> [quote] line one\n> line two"


def test_a_fence_is_one_backtick_longer_than_its_longest_run_with_marks_inside() -> None:
    source = "````js\ncode with ``` inside\n````\n"
    test = "````js\ncode with ``` inside and more\n````\n"
    assert critic(md(source, test)) == "````js\ncode with ``` inside {++and more++}\n````"
    assert none(md("Intro.\n", "Intro.\n\n```\nx = 1\n```\n")) == "Intro.\n\n```\n<ins>x = 1</ins>\n```"
    round_trips(source, test)


def test_the_text_variant_has_no_line_syntax() -> None:
    source, test = case_texts("four_kinds")
    lines = critic(md(source, test), syntax="text", roles=False).split("\n\n")
    assert not any(line.startswith(("#", "- ", "> ")) for line in lines)


# --- labels -----------------------------------------------------------------------


def _labelled(label: str, raw: str, text: str, **attrs: object) -> Block:
    return Block(
        kind=BlockKind.LIST_ITEM,
        label=label,
        text=text,
        attrs={"label_raw": raw, **attrs},
        role="clause",
    )


def test_labels_are_written_as_the_document_wrote_them() -> None:
    labelled = tree(_labelled("2", "2.", "The Supplier shall supply the Services."))
    assert critic(compare(labelled, labelled)) == "[clause] 2. The Supplier shall supply the Services."
    marker = Block(
        kind=BlockKind.LIST_ITEM,
        label="3",
        text="Third item.",
        attrs={"list_marker": "3.", "label_source": "list_marker", "list_depth": 1},
    )
    assert label_text(marker, "text") == "3."
    assert label_text(marker, "markdown") == ""
    both = Block(
        kind=BlockKind.LIST_ITEM,
        label="1.1",
        text="Access and Use.",
        attrs={"list_marker": "1.", "label_raw": "1.1", "list_depth": 1},
    )
    assert critic(compare(tree(both), tree(both)), roles=False) == "1. 1.1 Access and Use."
    assert critic(compare(tree(both), tree(both)), syntax="text", roles=False) == "1.1 Access and Use."
    bullet = Block(kind=BlockKind.LIST_ITEM, text="A bullet.", attrs={"list_marker": "-"})
    assert label_text(bullet, "text") == ""


def test_a_label_only_block_ends_at_its_label() -> None:
    schedule = tree(Block(kind=BlockKind.HEADING, label="1", text="", attrs={"label_raw": "Schedule 1.", "atx_level": 2}))
    assert critic(compare(schedule, schedule)) == "## Schedule 1."
    inserted = compare(tree(), schedule)
    assert critic(inserted) == "## {++Schedule 1.++}"
    assert none(inserted) == "## <ins>Schedule 1.</ins>"


def test_a_renumber_substitutes_the_labels_as_written() -> None:
    source = tree(_labelled("2", "2.", "The Supplier shall supply the Services."))
    test = tree(_labelled("3", "3.", "The Supplier shall supply the Services."))
    comparison = compare(source, test)
    assert [change.kind for change in comparison.changes] == [ChangeKind.RENUMBER]
    assert critic(comparison) == "[clause] {~~2.~>3.~~} The Supplier shall supply the Services."
    assert none(comparison) == "<del>2. </del><ins>3. </ins>The Supplier shall supply the Services."
    assert cm.accept_all(critic(comparison)) == ["3. The Supplier shall supply the Services."]
    assert cm.reject_all(critic(comparison)) == ["2. The Supplier shall supply the Services."]


def test_a_list_marker_renumber_is_a_note_in_markdown_and_a_substitution_in_text() -> None:
    source = "1. Alpha item text\n2. Beta item text\n"
    test = "1. New first item\n2. Alpha item text\n3. Beta item text\n"
    comparison = md(source, test)
    assert critic(comparison, roles=False).split("\n\n") == [
        "1. {++New first item++}",
        "2. {>>renumbered from 1.<<} Alpha item text",
        "3. {>>renumbered from 2.<<} Beta item text",
    ]
    assert critic(comparison, syntax="text", roles=False).split("\n\n") == [
        "{++1. New first item++}",
        "{~~1.~>2.~~} Alpha item text",
        "{~~2.~>3.~~} Beta item text",
    ]
    round_trips(source, test, syntax="text")
    annotated = critic(comparison)
    assert cm.accept_all(annotated) == cm.accept_all(critic(md(test, test)))


def test_a_role_goes_after_the_syntax_head_and_never_on_a_table_or_fence() -> None:
    source, test = case_texts("hostile")
    chunks = layout(md(source, test), CRITIC, syntax="markdown", roles=True)
    roled = 0
    for chunk in chunks:
        kinds = [piece.kind for piece in chunk.pieces]
        block = chunk.block
        if block is None or block.kind is BlockKind.TABLE or "fence" in block.attrs:
            assert "role" not in kinds
            continue
        if "role" in kinds:
            roled += 1
            assert kinds.index("role") == (1 if kinds[0] == "syntax" else 0)
    assert roled > 0
    assert critic(md(source, test)).split("\n\n")[1].startswith("[clause] 1.1 The report")


# --- moves ------------------------------------------------------------------------


def test_a_move_is_drawn_in_place_with_a_note_and_a_tombstone_at_its_origin() -> None:
    lines = critic(md(*case_texts("four_kinds"))).split("\n\n")
    assert [line.startswith("## ") for line in lines] == [
        True, False, False, False, True, False, False, False
    ]
    assert lines[1:4] == [
        "[clause] 1.1 The Supplier shall deliver the goods within {~~thirty (30~>sixty (60~~}) days of each order.",
        "{>>1.2 moved to 2.2 /section[2]/list_item[2]<<}",
        "[clause] {++1.2 The Buyer may reject goods that do not match the order.++}",
    ]
    assert lines[5:] == [
        "[clause] 2.1 The Buyer shall pay each invoice within fourteen days of receiving it.",
        "[clause] {--2.2 Late payments carry interest at two per cent a month.--}",
        "[clause] {~~1.2~>2.2~~} Risk in the goods passes to the Buyer when the goods are unloaded at the Buyer's warehouse. {>>moved from 1.2 /section[1]/list_item[2]<<}",
    ]


def test_a_nested_move_draws_the_inner_tombstone_inside_the_destination() -> None:
    lines = critic(md(*case_texts("nested_move")), roles=False).split("\n\n")
    body = [line for line in lines if not line.startswith("#")]
    assert body == [
        "7.1 Each party shall keep the other party's Confidential Information secret and use it only for this Agreement.",
        "{>>7.2 moved to 8.2 /section[2]/list_item[2]<<}",
        "8.1 Either party may terminate this Agreement on ninety days' written notice to the other party.",
        "{~~7.2~>8.2~~} Each party shall return or destroy the other party's Confidential Information on written request. {>>moved from 7.2 /section[1]/list_item[2]<<}",
        "(a) The receiving party shall certify the destruction in writing within five Business Days.",
        "{>>(b) moved to 9.2 /section[3]/list_item[2]<<}",
        "9.1 The Supplier shall keep complete records of the Services for six years after the end of the Term.",
        "{~~(b)~>9.2~~} The receiving party may keep one archival copy of the information for legal purposes only. {>>moved from (b) /section[1]/list_item[2]/list_item[2]<<}",
    ]


def test_the_legacy_sets_strike_a_moved_block_whole_at_its_origin() -> None:
    lines = none(md(*case_texts("nested_move"))).split("\n\n")
    body = [line for line in lines if not line.startswith("#")]
    assert body == [
        "7.1 Each party shall keep the other party's Confidential Information secret and use it only for this Agreement.",
        "<del>7.2 Each party shall return or destroy the other party's Confidential Information on written request.</del>",
        "<del>(a) The receiving party shall certify the destruction in writing within five Business Days.</del>",
        "<del>(b) The receiving party may keep one archival copy of the information for legal purposes only.</del>",
        "8.1 Either party may terminate this Agreement on ninety days' written notice to the other party.",
        "<ins>8.2 Each party shall return or destroy the other party's Confidential Information on written request.</ins>",
        "<ins>(a) The receiving party shall certify the destruction in writing within five Business Days.</ins>",
        "9.1 The Supplier shall keep complete records of the Services for six years after the end of the Term.",
        "<ins>9.2 The receiving party may keep one archival copy of the information for legal purposes only.</ins>",
    ]


# --- tables -----------------------------------------------------------------------


TABLE = "| Item | Due |\n| --- | :---: |\n| Setup | Week 1 |\n| Training | Week 2 |\n"


def test_a_table_is_one_block_with_its_alignment_row_in_markdown_only() -> None:
    comparison = md(TABLE, TABLE.replace("Week 2", "Week 3"))
    assert critic(comparison) == (
        "| Item | Due |\n| --- | :---: |\n| Setup | Week 1 |\n| Training | Week {~~2~>3~~} |"
    )
    assert critic(comparison, syntax="text") == (
        "| Item | Due |\n| Setup | Week 1 |\n| Training | Week {~~2~>3~~} |"
    )


def test_a_deleted_header_row_never_becomes_the_rendered_header() -> None:
    test = TABLE.replace("| Item | Due |", "| Deliverable | Owner |")
    assert critic(md(TABLE, test)) == (
        "| {++Deliverable++} | {++Owner++} |\n| --- | :---: |\n| {--Item--} | {--Due--} |\n"
        "| Setup | Week 1 |\n| Training | Week 2 |"
    )
    assert critic(md(TABLE, test), syntax="text").split("\n")[:2] == [
        "| {++Deliverable++} | {++Owner++} |",
        "| {--Item--} | {--Due--} |",
    ]
    round_trips(TABLE, test)


def test_a_wholly_deleted_table_writes_its_first_row_as_its_header() -> None:
    assert critic(md("Intro.\n\n" + TABLE, "Intro.\n")) == (
        "Intro.\n\n| {--Item--} | {--Due--} |\n| --- | :---: |\n| {--Setup--} | {--Week 1--} |\n"
        "| {--Training--} | {--Week 2--} |"
    )


def test_an_inserted_row_marks_each_cell_and_an_empty_one_marks_its_first() -> None:
    test = TABLE + "| a \\| b |  |\n|  |  |\n"
    rendered = critic(md(TABLE, test))
    assert rendered.split("\n")[-2:] == ["| {++a \\| b++} |  |", "| {++++} |  |"]
    assert none(md(TABLE, test)).split("\n")[-1] == "| <ins></ins> |  |"
    round_trips(TABLE, test)


def test_a_row_that_lost_a_cell_is_drawn_as_its_test_row_and_its_source_row() -> None:
    source = "| Item | Price | Owner |\n| --- | :---: | ---: |\n| Setup | 100 | Supplier |\n"
    test = "| Item | Price |\n| --- | :---: |\n| Setup | 100 |\n"
    annotated = critic(md(source, test))
    assert annotated == (
        "| {++Item++} | {++Price++} |\n| --- | :---: |\n| {--Item--} | {--Price--} | {--Owner--} |\n"
        "| {++Setup++} | {++100++} |\n| {--Setup--} | {--100--} | {--Supplier--} |"
    )
    assert cm.accept_all(annotated) == cm.accept_all(critic(md(test, test)))
    # Reject-all keeps every source row; the alignment row is the test's.
    source_lines = cm.reject_all(critic(md(source, source)))
    assert [line for line in cm.reject_all(annotated) if "---" not in line] == [
        line for line in source_lines if "---" not in line
    ]


def test_a_pipe_in_cell_text_is_escaped_in_both_variants() -> None:
    table = "| a \\| b | c |\n| --- | --- |\n| d | e \\| f |\n"
    assert critic(md(table, table)) == "| a \\| b | c |\n| --- | --- |\n| d | e \\| f |"
    assert none(md(table, table), syntax="text") == "| a \\| b | c |\n| d | e \\| f |"


# --- separators, whitespace, notes ------------------------------------------------


def test_blocks_are_joined_by_a_blank_line_with_no_trailing_newline() -> None:
    rendered = critic(md(*case_texts("trailing_insert")), roles=False)
    assert not rendered.endswith("\n")
    assert "\n\n\n" not in rendered
    heading, clause = rendered.split("\n\n")[-2:]
    assert re.fullmatch(r"## \{--4\.? Fees--\}", heading)
    assert clause == "{--4.1 The Client shall pay the Fees monthly.--}"


def test_a_whitespace_only_difference_is_not_a_change() -> None:
    comparison = compare("One  line here.\n\nNext.", "One line here.\n\nNext.", format="text")
    assert critic(comparison, syntax="text", roles=False) == "One line here.\n\nNext."


def test_the_header_notes_appear_only_when_true_and_in_order() -> None:
    source = "Intro.\n\n***\n\nThe first clause stays.\n"
    test = "Intro.\n\n***\n\nThe first clause stays, edited.\n"
    comparison = md(source, test)
    assert comparison.source.dropped and comparison.test.dropped
    dropped = [
        f"{{>>{side} dropped {d.count} {d.kind}: {d.reason}<<}}"
        for side, tree_ in (("source", comparison.source), ("test", comparison.test))
        for d in tree_.dropped
    ]
    assert critic(comparison).split("\n\n")[: len(dropped)] == dropped
    filtered = comparison.filter(kinds=("modify", "insert"), min_chars=1, has_inline=True)
    stopped = dataclasses.replace(
        filtered, config=dataclasses.replace(filtered.config, budget_exhausted=True)
    )
    assert critic(stopped).split("\n\n")[:2] == [
        "{>>filtered: kinds=modify,insert; min_chars=1; has_inline=true<<}",
        "{>>alignment stopped early: the comparison budget ran out<<}",
    ]
    assert critic(comparison.filter()).split("\n\n")[0] == dropped[0]
    assert "{>>" not in none(stopped) and "dropped" not in none(stopped)


def test_filter_values_in_a_note_are_escaped() -> None:
    comparison = md("1.1 Text.\n", "1.1 Text, edited.\n").filter(labels=("{++x", "a~>b"))
    assert critic(comparison).split("\n\n")[0] == "{>>filtered: labels=\\{++x,a~\\>b<<}"


# --- the renderer cases -----------------------------------------------------------


@pytest.mark.parametrize("name", CASE_NAMES)
@pytest.mark.parametrize("roles", [True, False])
def test_every_renderer_case_round_trips_through_the_reader(name: str, roles: bool) -> None:
    round_trips(*case_texts(name), roles=roles)
    source, test = case_texts(name)
    accepted = cm.tag_lines(none(md(source, test)), "accept")
    assert accepted == cm.tag_lines(none(md(test, test)), "accept")


@pytest.mark.parametrize("name", CASE_NAMES)
def test_no_live_delimiter_leaks_from_document_text(name: str) -> None:
    comparison = md(*case_texts(name))
    emitted = sum(
        1
        for chunk in layout(comparison, CRITIC, syntax="markdown", roles=True)
        for piece in chunk.pieces
        if piece.kind in ("insert", "delete", "substitution", "note")
    )
    parsed = sum(1 for token in cm.parse(critic(comparison)) if token.kind != "text")
    assert parsed == emitted


@pytest.mark.skipif(importlib.util.find_spec("rapidfuzz") is None, reason="needs the [fuzzy] extra")
@pytest.mark.parametrize("name", CASE_NAMES)
def test_difflib_and_rapidfuzz_build_the_same_change_tree_on_each_case(name: str) -> None:
    source, test = case_texts(name)
    trees = [
        compare(source, test, format="markdown", alignment=AlignmentConfig(similarity=backend))
        for backend in ("difflib", "rapidfuzz")
    ]
    assert trees[0].changes.to_dict() == trees[1].changes.to_dict()


# --- the 60 committed runs --------------------------------------------------------


def _oracle() -> dict[str, list[str]]:
    failures: dict[str, list[str]] = {
        key: []
        for key in ("accept", "accept_bare", "reject_strict", "reject_loose", "none_accept", "none_order")
    }
    removed = {"accept": 0, "reject": 0}
    for run in committed_runs():
        source, test = run.texts()
        syntax = run.format
        assert syntax in ("text", "markdown")
        comparison = compare(source, test, format=syntax)
        on_test = compare(test, test, format=syntax)
        on_source = compare(source, source, format=syntax)
        annotated = critic(comparison, syntax)
        test_rendering = critic(on_test, syntax)
        accepted = cm.accept_all(annotated)
        if not cm.exact(accepted, cm.accept_all(test_rendering)):
            failures["accept"].append(run.name)
        bare = [line.strip() for line in cm.lines(annotated, "accept") if line.strip()]
        bare_test = [line.strip() for line in cm.lines(test_rendering, "accept") if line.strip()]
        if bare != bare_test:
            failures["accept_bare"].append(run.name)
        removed["accept"] += len(bare) - len(accepted)
        rejected = cm.reject_all(annotated)
        removed["reject"] += (
            len([line for line in cm.lines(annotated, "reject") if line.strip()]) - len(rejected)
        )
        source_rendering = cm.reject_all(critic(on_source, syntax))
        if not cm.multiset(rejected, source_rendering):
            failures["reject_strict"].append(run.name)
        if not cm.loose_multiset(rejected, source_rendering):
            failures["reject_loose"].append(run.name)
        legacy = none(comparison, syntax)
        if cm.tag_lines(legacy, "accept") != cm.tag_lines(none(on_test, syntax), "accept"):
            failures["none_accept"].append(run.name)
        if cm.loose(cm.tag_lines(legacy, "reject")) != cm.loose(
            cm.tag_lines(none(on_source, syntax), "reject")
        ):
            failures["none_order"].append(run.name)
    failures["removed"] = [str(removed["accept"]), str(removed["reject"])]
    return failures


@pytest.fixture(scope="module")
def oracle() -> dict[str, list[str]]:
    return _oracle()


def test_accept_all_reproduces_the_test_rendering_on_every_committed_run(
    oracle: dict[str, list[str]],
) -> None:
    assert oracle["accept"] == []


def test_without_the_residue_rule_accept_all_holds_on_56_of_60(
    oracle: dict[str, list[str]],
) -> None:
    assert len(oracle["accept_bare"]) == 4
    assert oracle["removed"] == ["6", "33"]


def test_reject_all_is_a_loose_multiset_on_59_of_60_and_strict_on_49(
    oracle: dict[str, list[str]],
) -> None:
    assert oracle["reject_loose"] == ["benchmark/hand/csa-1.1-to-2.0"]
    assert len(oracle["reject_strict"]) == 11


def test_the_none_style_accepts_exactly_and_rejects_in_source_order_on_every_run(
    oracle: dict[str, list[str]],
) -> None:
    assert oracle["none_accept"] == []
    assert oracle["none_order"] == []


# --- determinism ------------------------------------------------------------------


def test_two_renders_are_byte_equal() -> None:
    comparison = md(*case_texts("hostile"))
    assert critic(comparison) == critic(comparison)
    assert none(comparison) == none(comparison)


def test_the_sample_pair_renders_the_same_bytes_under_every_hash_seed() -> None:
    script = """
import sys
from pathlib import Path
from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
from redlines.renderers._inplace import render_inplace
from redlines.renderers._marks import CRITIC, LEGACY
sample = Path("tests/corpus/sample_pair")
for ext, syntax in (("md", "markdown"), ("txt", "text")):
    source = (sample / f"source.{ext}").read_text(encoding="utf-8")
    test = (sample / f"test.{ext}").read_text(encoding="utf-8")
    comparison = compare(source, test, format=syntax, alignment=AlignmentConfig(similarity="difflib"))
    sys.stdout.write(render_inplace(comparison, CRITIC, syntax=syntax, roles=True) + "\\n=====\\n")
    sys.stdout.write(render_inplace(comparison, LEGACY["none"], syntax=syntax, roles=False) + "\\n=====\\n")
"""
    output = assert_byte_identical_across_hash_seeds(script, cwd=REPO_ROOT)
    assert output.count("=====") == 4
    assert "{>>" in output and "<ins>" in output
