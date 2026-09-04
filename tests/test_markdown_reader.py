"""Tests for the markdown reader (#103, R5, D16).

Two things are being proved here. The first is that every construct a contract
written in markdown uses -- headings, nested lists, pipe tables, fences,
blockquotes -- comes out as the block the syntax says it is. The second is the
one the PRD cares about: the *twin test* at the bottom reads a plain-text
contract and its markdown twin under the built-in ``contract`` and ``markdown``
profiles and compares the two trees block by block, because PRD § 6b promises
that "a markdown contract with ``## 7. Termination`` and ``1.`` list items
therefore gets the same roles and labels as its plain-text twin". Roles arrive
with the semantic pass (#104); labels, levels, kinds and addresses are here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redlines.blocks import (
    MATCHED_BY_CONTINUATION,
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
)
from redlines.profiles import Profile
from redlines.profiles.builtin import builtin_profile
from redlines.readers import DEFAULT_MAX_CHARS, Reader, reader_for, readers
from redlines.readers.markdown import MarkdownReader
from redlines.readers.text import PlainTextReader

CASES = Path(__file__).parent / "corpus" / "markdown_cases"


@pytest.fixture
def profile() -> Profile:
    """The built-in ``markdown`` profile: what the reader is meant to be used with."""
    return builtin_profile("markdown")


def read(source: str, profile: Profile | None = None) -> BlockTree:
    """Read ``source`` with a fresh reader."""
    return MarkdownReader().read(source, profile=profile)


def case(name: str, profile: Profile | None = None) -> BlockTree:
    """Read one fixture from ``tests/corpus/markdown_cases``."""
    return read((CASES / name).read_text(encoding="utf-8"), profile)


def walk(block: Block) -> list[Block]:
    """Return ``block`` and its descendants in document order."""
    found = [block]
    for child in block.children:
        found.extend(walk(child))
    return found


def of_kind(tree: BlockTree, kind: BlockKind) -> list[Block]:
    """Return every block of ``kind``, in document order."""
    return [block for block in tree.walk() if block.kind is kind]


def only(blocks: list[Block]) -> Block:
    """Return the one block in ``blocks``, failing loudly if there is not one."""
    assert len(blocks) == 1, f"expected exactly one block, got {len(blocks)}"
    return blocks[0]


def dropped_counts(tree: BlockTree) -> dict[str, int]:
    """Return the tree's ``dropped`` report as a mapping."""
    return {report.kind: report.count for report in tree.dropped}


# --- the reader as a reader ------------------------------------------------


def test_the_markdown_reader_is_a_reader() -> None:
    assert isinstance(MarkdownReader(), Reader)
    assert MarkdownReader().name == "markdown"
    assert MarkdownReader().formats == ("markdown",)


def test_it_is_registered_for_the_markdown_format() -> None:
    """Importing `redlines.readers` registers it, as it does the text reader."""
    assert isinstance(reader_for("markdown"), MarkdownReader)
    assert readers()["markdown"].name == "markdown"


def test_it_reads_utf_8_bytes(profile: Profile) -> None:
    tree = read_bytes("## 1. Fee\n\nThe fee is 1,000.\n".encode("utf-8"), profile)

    assert only(of_kind(tree, BlockKind.HEADING)).label == "1"


def read_bytes(source: bytes, profile: Profile) -> BlockTree:
    """Read UTF-8 bytes, for the two tests that care that bytes are accepted."""
    return MarkdownReader().read(source, profile=profile)


def test_bytes_that_are_not_utf_8_are_refused(profile: Profile) -> None:
    with pytest.raises(ValueError, match="not UTF-8"):
        MarkdownReader().read(b"\xff\xfe\x00A", profile=profile)


def test_the_size_cap_is_enforced_here(profile: Profile) -> None:
    """ADR-0028: the reader bounds the text because it cannot bound the patterns."""
    with pytest.raises(ValueError, match="over the 100 character limit"):
        MarkdownReader().read("x" * 101, profile=profile, max_chars=100)

    assert MarkdownReader().read("x" * 100, profile=profile, max_chars=100)


def test_the_cap_defaults_to_the_shared_one(profile: Profile) -> None:
    assert MarkdownReader().read("# x\n", profile=profile) is not None
    assert DEFAULT_MAX_CHARS == 2_000_000


def test_the_same_input_reads_identically_every_time(profile: Profile) -> None:
    """N1: no dict order, set order or scanner state leaking into the output."""
    first = case("constructs.md", profile)
    second = case("constructs.md", profile)

    assert first == second
    assert first.to_dict() == second.to_dict()
    assert [report.kind for report in first.dropped] == [
        report.kind for report in second.dropped
    ]


def test_one_reader_instance_holds_no_state_between_reads(profile: Profile) -> None:
    reader = MarkdownReader()
    source = (CASES / "constructs.md").read_text(encoding="utf-8")
    first = reader.read(source, profile=profile)
    reader.read("## Schedule 9\n\n- an item\n\n---\n", profile=profile)

    assert reader.read(source, profile=profile) == first


def test_every_block_is_addressed(profile: Profile) -> None:
    tree = case("constructs.md", profile)

    assert tree.root.path == "/"
    for block in tree.walk():
        assert tree.block_at(block.path) == block


def test_the_root_reports_the_whole_read(profile: Profile) -> None:
    """``labelled`` counts what a profile pattern labelled, headings included --
    not the two items markdown's own ordered markers labelled."""
    root = case("twin_contract.md", profile).root

    assert root.matched_by == MATCHED_BY_DOCUMENT
    assert root.attrs == {
        "reader": "markdown",
        "profile": "markdown",
        "blocks": 13,
        "labelled": 8,
        "headings": 4,
        "numbering_resets": 1,
    }


# --- an empty document -----------------------------------------------------


def test_an_empty_document_is_an_empty_tree(profile: Profile) -> None:
    tree = read("", profile)

    assert tree.root.kind is BlockKind.DOCUMENT
    assert tree.root.children == ()
    assert tree.dropped == ()
    assert tree.fallback_count == 0


def test_a_document_of_nothing_but_blank_lines_is_empty_too(profile: Profile) -> None:
    assert read("\n\n   \n\t\n", profile).root.children == ()


# --- ATX and setext headings -----------------------------------------------


def test_an_atx_heading_is_stated_by_the_syntax(profile: Profile) -> None:
    heading = only(of_kind(read("### Governing Law\n", profile), BlockKind.HEADING))

    assert heading.text == "Governing Law"
    assert heading.matched_by == "markdown:atx"
    assert heading.confidence == 1.0
    assert heading.attrs["atx_level"] == 3


def test_a_heading_opens_a_section_that_holds_what_follows(profile: Profile) -> None:
    tree = read("# Agreement\n\nThe parties agree as follows.\n", profile)
    heading = only(of_kind(tree, BlockKind.HEADING))
    section = tree.block_at(heading.path.rsplit("/", 1)[0])

    assert section.kind is BlockKind.SECTION
    assert [child.kind for child in section.children] == [
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
    ]


def test_hash_depth_nests_headings_inside_one_another(profile: Profile) -> None:
    tree = read("# One\n\n## Two\n\n### Three\n\n## Four\n", profile)
    paths = {heading.text: heading.path for heading in of_kind(tree, BlockKind.HEADING)}

    assert paths["Two"].startswith("/section[1]/section[1]")
    assert paths["Three"].startswith(paths["Two"].rsplit("/", 1)[0])
    assert paths["Four"].startswith("/section[1]/section[2]")


def test_a_labelled_heading_takes_its_level_from_the_label(profile: Profile) -> None:
    """The twin promise in one assertion; the hash count stays in ``attrs``.

    ``## 7. Termination`` is clause 7 of the agreement whichever format it is
    written in, so its ``level`` is the label's depth, exactly as the plain-text
    reader records it. The hash count is the *nesting* signal and is kept where
    a reader can still see it.
    """
    heading = only(of_kind(read("## 7. Termination\n", profile), BlockKind.HEADING))

    assert heading.label == "7"
    assert heading.level == 1
    assert heading.attrs["atx_level"] == 2
    assert heading.attrs["label_pattern"] == "decimal"


def test_a_schedule_heading_resets_the_numbering(profile: Profile) -> None:
    tree = read(
        "## 7. Termination\n\n7.1 A clause.\n\n## Schedule 1\n\n1. An item.\n",
        profile,
    )
    schedule = only([b for b in tree.walk() if b.label == "Schedule 1"])
    item = only([b for b in tree.walk() if b.label == "1"])

    assert schedule.attrs["heading_reset"] == "schedule"
    assert schedule.level == 0
    assert item.level == 1
    assert tree.root.attrs["numbering_resets"] == 1


def test_a_setext_heading_is_read_where_it_is_cheap_to(profile: Profile) -> None:
    tree = read("Definitions\n===========\n\nSub head\n--------\n", profile)
    headings = of_kind(tree, BlockKind.HEADING)

    assert [(h.text, h.attrs["atx_level"]) for h in headings] == [
        ("Definitions", 1),
        ("Sub head", 2),
    ]
    assert {h.matched_by for h in headings} == {"markdown:setext"}


def test_a_rule_after_a_blank_line_is_not_a_setext_underline(
    profile: Profile,
) -> None:
    tree = read("A paragraph.\n\n---\n", profile)

    assert of_kind(tree, BlockKind.HEADING) == []
    assert dropped_counts(tree)["thematic_break"] == 1


def test_a_hash_without_a_space_is_not_a_heading(profile: Profile) -> None:
    tree = read("##Subject\n\n####### seven hashes\n", profile)

    assert of_kind(tree, BlockKind.HEADING) == []
    assert [block.text for block in of_kind(tree, BlockKind.PARAGRAPH)] == [
        "##Subject",
        "####### seven hashes",
    ]


def test_an_unmarked_heading_is_still_scored_under_a_profile(
    profile: Profile,
) -> None:
    """The leftover case the built-in profile's ``heading_rule`` is there for."""
    tree = read(
        "Governing Law\n\nThis Agreement is governed by English law.\n", profile
    )
    heading = only(of_kind(tree, BlockKind.HEADING))

    assert heading.text == "Governing Law"
    assert heading.matched_by == "heading:score"
    assert 0.3 <= heading.confidence < 0.7
    assert heading.attrs["heading_score"] >= heading.attrs["heading_threshold"]


# --- lists -----------------------------------------------------------------


def test_an_unordered_item_is_a_list_item_the_syntax_stated(
    profile: Profile,
) -> None:
    item = only(of_kind(read("- A deliverable.\n", profile), BlockKind.LIST_ITEM))

    assert item.text == "A deliverable."
    assert item.label is None
    assert item.level == 1
    assert item.matched_by == "markdown:list"
    assert item.confidence == 1.0
    assert item.attrs["list_marker"] == "-"
    assert item.attrs["list_ordered"] is False


def test_an_ordered_marker_is_the_item_label(profile: Profile) -> None:
    """``1.`` is what the document shows a reader, so it is what ``label`` says."""
    items = of_kind(read("1. First.\n2. Second.\n", profile), BlockKind.LIST_ITEM)

    assert [(item.label, item.level) for item in items] == [("1", 1), ("2", 1)]
    assert {item.attrs["label_source"] for item in items} == {"list_marker"}
    assert {item.matched_by for item in items} == {"markdown:list"}


def test_a_paren_marker_is_read_as_well_as_a_dot(profile: Profile) -> None:
    item = only(of_kind(read("3) Third.\n", profile), BlockKind.LIST_ITEM))

    assert item.label == "3"
    assert item.attrs["list_marker"] == "3)"


def test_lists_nest_by_indentation_three_deep(profile: Profile) -> None:
    tree = case("nested_lists.md", profile)
    items = of_kind(tree, BlockKind.LIST_ITEM)

    assert [(item.text, item.level) for item in items] == [
        ("Hosting", 1),
        ("Availability", 2),
        ("Measured monthly", 3),
        ("Backups", 2),
        ("Support", 1),
    ]
    deepest = items[2]
    assert deepest.path.count("list_item") == 3
    assert items[3].path.rsplit("/", 1)[0] == items[1].path.rsplit("/", 1)[0]


def test_a_dedent_closes_the_lists_it_left(profile: Profile) -> None:
    tree = read("- one\n  - two\n- three\n", profile)
    items = of_kind(tree, BlockKind.LIST_ITEM)

    assert [item.level for item in items] == [1, 2, 1]
    assert items[2].path == "/list_item[2]"


def test_a_lazy_continuation_line_joins_the_item_it_wraps(profile: Profile) -> None:
    """The plain-text reader's wrap rule, applied to a markdown list item."""
    tree = read(
        "- The Supplier shall provide the Services with reasonable\nskill and care.\n",
        profile,
    )
    item = only(of_kind(tree, BlockKind.LIST_ITEM))

    assert item.text == (
        "The Supplier shall provide the Services with reasonable skill and care."
    )
    assert item.attrs["rejoined_lines"] == 2


def test_a_line_the_wrap_rule_refuses_becomes_a_paragraph_under_the_item(
    profile: Profile,
) -> None:
    """Nothing is lost where the rule declines: the text moves, it does not vanish."""
    tree = read(
        "- Charges\nThe Client shall pay the Fees within thirty days.\n", profile
    )
    item = only(of_kind(tree, BlockKind.LIST_ITEM))
    body = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert item.text == "Charges"
    assert body.text == "The Client shall pay the Fees within thirty days."
    assert body.matched_by == MATCHED_BY_CONTINUATION
    assert body.path.startswith(item.path)


def test_an_item_whose_text_is_a_clause_label_is_labelled_by_the_profile(
    profile: Profile,
) -> None:
    """``1. Definitions`` and ``- 1.1 …`` are two different claims, and both are made.

    In the first the ``1.`` is markdown's own marker, which a renderer would
    renumber, so the syntax states the label and the level. In the second the
    marker carries nothing and the *text* carries ``1.1``, which is the
    document's own numbering: the profile's pattern and the numbering stack
    place it, exactly as they would in plain text.
    """
    tree = read("1. Definitions\n\n- 1.1 The Supplier shall keep records.\n", profile)
    marker_item, text_item = of_kind(tree, BlockKind.LIST_ITEM)

    assert (marker_item.label, marker_item.level) == ("1", 1)
    assert marker_item.text == "Definitions"
    assert marker_item.matched_by == "markdown:list"
    assert marker_item.attrs["label_source"] == "list_marker"

    assert (text_item.label, text_item.level) == ("1.1", 2)
    assert text_item.text == "The Supplier shall keep records."
    assert text_item.matched_by == "label:decimal"
    assert text_item.attrs["list_depth"] == 1
    assert text_item.attrs["label_pattern"] == "decimal"


def test_a_labelled_paragraph_is_a_list_item_as_it_is_in_plain_text(
    profile: Profile,
) -> None:
    """A markdown contract writes ``7.2 …`` as a paragraph at least as often."""
    item = only(
        of_kind(
            read("7.2 Termination is not retrospective.\n", profile),
            BlockKind.LIST_ITEM,
        )
    )

    assert (item.label, item.level) == ("7.2", 2)
    assert item.matched_by == "label:decimal"


# --- paragraphs ------------------------------------------------------------


def test_hard_wrapped_paragraphs_are_rejoined_as_in_plain_text(
    profile: Profile,
) -> None:
    source = (
        "The Supplier shall provide the Services with reasonable\n"
        "skill and care at all times.\n"
    )
    markdown = only(of_kind(read(source, profile), BlockKind.PARAGRAPH))
    plain = PlainTextReader().read(source, profile=builtin_profile("contract")).root

    assert markdown.text == walk(plain)[1].text
    assert markdown.attrs["rejoined_lines"] == 2


def test_a_paragraph_with_no_clause_above_it_falls_back(profile: Profile) -> None:
    tree = read("The parties agree as follows.\n", profile)
    paragraph = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert paragraph.matched_by == MATCHED_BY_FALLBACK
    assert paragraph.confidence == 0.0
    assert tree.fallback_count == 1


def test_a_paragraph_after_a_clause_continues_it(profile: Profile) -> None:
    tree = read("7.1 The fee is due.\n\nInvoices are issued monthly.\n", profile)
    body = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert body.matched_by == MATCHED_BY_CONTINUATION
    assert body.attrs["continuation_reason"] == "follows_label"
    assert body.path.startswith("/list_item[1]")


# --- pipe tables -----------------------------------------------------------


def test_a_pipe_table_is_a_table_of_rows_of_cells(profile: Profile) -> None:
    tree = case("table_only.md", profile)
    table = only(of_kind(tree, BlockKind.TABLE))

    assert table.matched_by == "markdown:pipe_table"
    assert table.confidence == 1.0
    assert [child.kind for child in table.children] == [BlockKind.ROW] * 3
    assert [cell.text for cell in table.children[0].children] == [
        "Service",
        "Fee",
        "Notes",
    ]
    assert table.children[1].children[1].path == "/table[1]/row[2]/cell[2]"


def test_the_header_row_is_flagged_and_the_others_are_not(profile: Profile) -> None:
    rows = of_kind(case("table_only.md", profile), BlockKind.ROW)

    assert [row.attrs["header"] for row in rows] == [True, False, False]
    assert all(cell.attrs["header"] for cell in rows[0].children)


def test_the_alignment_row_is_not_a_row_and_is_not_reported_as_dropped(
    profile: Profile,
) -> None:
    """It is the table's punctuation: no text was lost, so nothing was dropped."""
    tree = case("table_only.md", profile)
    table = only(of_kind(tree, BlockKind.TABLE))

    assert len(table.children) == 3
    assert table.attrs["alignments"] == ["left", "right", "center"]
    assert "alignment_row" not in dropped_counts(tree)
    assert tree.dropped == ()


def test_a_document_that_is_only_a_table_still_reads(profile: Profile) -> None:
    tree = case("table_only.md", profile)

    assert [child.kind for child in tree.root.children] == [BlockKind.TABLE]
    assert tree.fallback_count == 0
    assert tree.root.attrs["blocks"] == 1


def test_a_ragged_row_is_padded_and_says_so(profile: Profile) -> None:
    tree = read("| A | B |\n| - | - |\n| one |\n", profile)
    row = of_kind(tree, BlockKind.ROW)[1]

    assert [cell.text for cell in row.children] == ["one", ""]
    assert row.attrs["ragged"] is True


def test_an_escaped_pipe_stays_inside_its_cell(profile: Profile) -> None:
    tree = read("| A | B |\n| - | - |\n| one \\| two | three |\n", profile)
    cells = of_kind(tree, BlockKind.CELL)

    assert [cell.text for cell in cells[2:]] == ["one | two", "three"]


def test_a_line_with_a_pipe_is_not_a_table(profile: Profile) -> None:
    tree = read("The fee is 100 | 200 depending on volume.\n", profile)

    assert of_kind(tree, BlockKind.TABLE) == []
    assert len(of_kind(tree, BlockKind.PARAGRAPH)) == 1


# --- fenced code -----------------------------------------------------------


def test_a_fence_is_kept_verbatim_and_never_label_scanned(profile: Profile) -> None:
    tree = read('```python\n7.1 = "not a clause"\n\n- not an item\n```\n', profile)
    fence = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert fence.text == '7.1 = "not a clause"\n\n- not an item'
    assert fence.label is None
    assert fence.matched_by == "markdown:fence"
    assert fence.confidence == 1.0
    assert fence.attrs["fence"] == "python"


def test_a_fence_with_no_info_string_says_so(profile: Profile) -> None:
    fence = only(of_kind(read("```\nplain\n```\n", profile), BlockKind.PARAGRAPH))

    assert fence.attrs["fence"] == ""


def test_a_tilde_fence_works_too(profile: Profile) -> None:
    fence = only(of_kind(read("~~~text\na | b\n~~~\n", profile), BlockKind.PARAGRAPH))

    assert fence.text == "a | b"
    assert fence.attrs["fence"] == "text"


def test_an_unclosed_fence_runs_to_the_end_of_the_document(profile: Profile) -> None:
    fence = only(of_kind(read("```\nstill open\n", profile), BlockKind.PARAGRAPH))

    assert fence.text == "still open"


# --- blockquotes -----------------------------------------------------------


def test_a_blockquote_is_marked_and_its_labels_are_still_read(
    profile: Profile,
) -> None:
    tree = read("> 7.1 A quoted clause.\n>\n> Some quoted prose.\n", profile)
    clause = only(of_kind(tree, BlockKind.LIST_ITEM))
    prose = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert clause.label == "7.1"
    assert clause.text == "A quoted clause."
    assert clause.attrs["quote"] is True
    assert prose.attrs["quote"] is True


def test_a_quoted_line_is_never_promoted_to_a_heading(profile: Profile) -> None:
    """Quoted material is evidence in the document, not structure of it."""
    tree = read(
        "> Governing Law\n\nThe Agreement is governed by English law.\n", profile
    )

    assert of_kind(tree, BlockKind.HEADING) == []
    assert only(of_kind(tree, BlockKind.PARAGRAPH)[:1]).attrs["quote"] is True


def test_a_list_inside_a_quotation_is_still_a_list(profile: Profile) -> None:
    item = only(of_kind(read("> - a quoted bullet\n", profile), BlockKind.LIST_ITEM))

    assert item.text == "a quoted bullet"
    assert item.attrs["quote"] is True


def test_a_quoted_heading_opens_no_section_and_resets_no_numbering(
    profile: Profile,
) -> None:
    """A quoted document's headings are not this document's structure.

    Somebody quoting ``## Schedule 9`` from another agreement must not thereby
    restart this agreement's clause numbering, nor open a section that every
    clause written after the quotation falls into.
    """
    tree = read(
        "1. First clause.\n2. Second clause.\n\n"
        "> ## Schedule 9\n> Some quoted schedule reference.\n\n"
        "3. Third clause.\n",
        profile,
    )
    quoted = only([block for block in tree.walk() if block.label == "Schedule 9"])
    third = only([block for block in tree.walk() if block.label == "3"])

    assert of_kind(tree, BlockKind.SECTION) == []
    assert tree.root.attrs["numbering_resets"] == 0
    assert quoted.kind is BlockKind.PARAGRAPH
    assert quoted.matched_by == "markdown:atx"
    assert quoted.attrs["quoted_heading"] is True
    assert quoted.attrs["atx_level"] == 2
    assert third.path == "/list_item[3]"
    assert tree.heading_breadcrumb(third.path) == ()


def test_a_quoted_clause_never_closes_or_reopens_a_real_one(profile: Profile) -> None:
    """Quoted evidence attaches where the quotation sits, not where its label points."""
    tree = read(
        "1. First real clause\n\n2. Second real clause\n\n"
        "> 9. Quoted excerpt from another document\n\n"
        "3. Third real clause\n",
        profile,
    )
    quoted = only([block for block in tree.walk() if block.label == "9"])
    third = only([block for block in tree.walk() if block.label == "3"])

    assert quoted.attrs["quote"] is True
    assert quoted.path.startswith("/list_item[2]/")
    assert third.path == "/list_item[3]"


def test_a_quoted_number_does_not_join_the_documents_numbering_run(
    profile: Profile,
) -> None:
    """The quoted label is previewed against the stack, never placed on it."""
    body = "7.1 First real clause.\n\n{quote}(a) A real sub clause.\n"
    quoted = read(
        body.format(quote="> (c) A quoted sub clause from elsewhere.\n\n"), profile
    )
    clean = read(body.format(quote=""), profile)
    real = only([block for block in quoted.walk() if block.label == "(a)"])
    twin = only([block for block in clean.walk() if block.label == "(a)"])

    assert (real.level, real.confidence) == (twin.level, twin.confidence)
    assert real.attrs["numbering_run"] == twin.attrs["numbering_run"] == "first_value"


# --- nesting a list states ---------------------------------------------------


def test_a_labelled_sub_clause_stays_inside_the_item_it_is_indented_under(
    profile: Profile,
) -> None:
    """CommonMark indentation is a floor on a stack-resolved label's level.

    ``(a)`` under ``1. Introduction`` is not a top-level clause just because the
    marker above it never reached the numbering stack for the alpha style to be
    measured against: the syntax stated the nesting and cannot be wrong about it.
    """
    tree = case("nested_clauses.md", profile)
    paths = {block.label: block.path for block in tree.walk() if block.label}

    assert paths["1"] == "/list_item[1]"
    assert paths["2"] == "/list_item[2]"
    assert [block.path for block in tree.walk() if block.label == "(a)"] == [
        "/list_item[1]/list_item[1]",
        "/list_item[2]/list_item[1]",
    ]
    assert paths["(b)"] == "/list_item[1]/list_item[2]"

    first = tree.block_at("/list_item[1]/list_item[1]")
    assert (first.level, first.attrs["list_depth"]) == (2, 2)
    assert first.attrs["label_level"] == 1
    assert first.attrs["level_source"] == "list_depth"
    assert first.matched_by == "label:alpha_paren"


# --- what is dropped (R3) --------------------------------------------------


def test_rules_html_link_definitions_and_images_are_dropped_and_reported(
    profile: Profile,
) -> None:
    tree = case("constructs.md", profile)

    assert dropped_counts(tree) == {
        "thematic_break": 1,
        "html_block": 1,
        "link_reference_definition": 1,
        "image": 1,
    }
    assert all(report.reason.endswith(".") for report in tree.dropped)


def test_an_image_leaves_the_sentence_it_sat_in(profile: Profile) -> None:
    tree = read("The map ![service map](map.png) shows the estate.\n", profile)
    paragraph = only(of_kind(tree, BlockKind.PARAGRAPH))

    assert paragraph.text == "The map shows the estate."
    assert dropped_counts(tree) == {"image": 1}


def test_an_image_only_paragraph_leaves_no_block_behind(profile: Profile) -> None:
    tree = read("![a diagram](diagram.png)\n", profile)

    assert tree.root.children == ()
    assert dropped_counts(tree) == {"image": 1}


def test_a_clean_document_drops_nothing(profile: Profile) -> None:
    assert case("twin_contract.md", profile).dropped == ()


def test_control_characters_are_removed_and_reported(profile: Profile) -> None:
    tree = read("7.1 The\x00 fee\x07 is due.\n", profile)

    assert dropped_counts(tree) == {"control_character": 2}
    assert "\x00" not in only(of_kind(tree, BlockKind.LIST_ITEM)).text


def test_html_and_link_definitions_do_not_swallow_what_follows(
    profile: Profile,
) -> None:
    tree = read(
        "<div>\n  <span>raw</span>\n</div>\n\n[ref]: https://example.test\n\n# After\n",
        profile,
    )

    assert only(of_kind(tree, BlockKind.HEADING)).text == "After"
    assert dropped_counts(tree) == {"html_block": 1, "link_reference_definition": 1}


# --- without a profile -----------------------------------------------------


def test_without_a_profile_the_syntax_is_still_read() -> None:
    """The degrade path keeps what markdown states and claims nothing more."""
    tree = case("constructs.md")

    assert [block.matched_by for block in of_kind(tree, BlockKind.HEADING)] == [
        "markdown:atx",
        "markdown:setext",
        "markdown:atx",
        "markdown:atx",
        "markdown:atx",
    ]
    assert of_kind(tree, BlockKind.TABLE) != []
    assert tree.root.attrs["profile"] is None


def test_without_a_profile_nothing_is_labelled_by_a_pattern() -> None:
    tree = case("constructs.md")

    assert tree.root.attrs["labelled"] == 0
    assert [
        block.matched_by
        for block in tree.walk()
        if block.matched_by.startswith("label:")
    ] == []


def test_without_a_profile_no_paragraph_is_promoted_to_a_heading() -> None:
    tree = read("Governing Law\n\nThe Agreement is governed by English law.\n")
    paragraphs = of_kind(tree, BlockKind.PARAGRAPH)

    assert of_kind(tree, BlockKind.HEADING) == []
    assert paragraphs[0].attrs["heading_signals"] == ["no_profile"]
    assert paragraphs[0].matched_by == MATCHED_BY_FALLBACK


def test_without_a_profile_a_marker_still_labels_its_item() -> None:
    item = only(of_kind(read("1. An item.\n"), BlockKind.LIST_ITEM))

    assert item.label == "1"
    assert item.matched_by == "markdown:list"


# --- the twin test (PRD section 6b) ----------------------------------------


def twin_trees() -> tuple[BlockTree, BlockTree]:
    """Read the twin pair: the plain text under ``contract``, the markdown under
    ``markdown``. The two files are the same agreement, written twice."""
    plain = PlainTextReader().read(
        (CASES / "twin_contract.txt").read_text(encoding="utf-8"),
        profile=builtin_profile("contract"),
    )
    markdown = MarkdownReader().read(
        (CASES / "twin_contract.md").read_text(encoding="utf-8"),
        profile=builtin_profile("markdown"),
    )
    return plain, markdown


def test_the_markdown_twin_gets_the_same_labels_levels_and_kinds() -> None:
    """PRD § 6b's promise, block by block.

    ``## 7. Termination`` and ``7. Termination`` are the same clause at the same
    depth; ``1.`` written as a markdown list item and ``1.`` written as a
    plain-text label are the same item. Roles arrive with the semantic pass
    (#104); everything the readers themselves decide is compared here.
    """
    plain, markdown = twin_trees()
    plain_blocks, markdown_blocks = list(plain.walk()), list(markdown.walk())

    assert len(plain_blocks) == len(markdown_blocks)
    assert [(b.kind, b.label, b.level) for b in plain_blocks] == [
        (b.kind, b.label, b.level) for b in markdown_blocks
    ]


def test_the_twins_have_the_same_shape_and_the_same_addresses() -> None:
    """Same tree, so the same ADR-0029 addresses: `/section[2]/list_item[1]` is
    the same clause in either format, which is what M2's alignment will lean on."""
    plain, markdown = twin_trees()

    assert [block.path for block in plain.walk()] == [
        block.path for block in markdown.walk()
    ]


def test_the_twins_carry_the_same_text() -> None:
    """Including the hard-wrapped clause: both readers re-join it the same way."""
    plain, markdown = twin_trees()

    assert [block.text for block in plain.walk()] == [
        block.text for block in markdown.walk()
    ]


def test_the_twin_headings_are_the_named_clause(profile: Profile) -> None:
    """The PRD names the heading, so the test names it too."""
    _, markdown = twin_trees()
    termination = only([b for b in markdown.walk() if b.text == "Termination"])

    assert termination.kind is BlockKind.HEADING
    assert (termination.label, termination.level) == ("7", 1)
    assert markdown.heading_breadcrumb(
        only([b for b in markdown.walk() if b.label == "7.1"]).path
    ) == ("Master Services Agreement", "Termination")
