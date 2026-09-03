"""Tests for the block model: addressing, breadcrumbs and serialisation (#98, #99, #106)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from redlines.blocks import (
    BLOCK_KINDS,
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    RECOMMENDED_ROLES,
    RECOMMENDED_SPAN_TYPES,
    ROOT_PATH,
    Block,
    BlockKind,
    BlockTree,
    Dropped,
    Span,
    assign_paths,
    block_at,
    child_path,
    heading_breadcrumb,
    iter_blocks,
    matched_by_heading,
    matched_by_label,
    matched_by_markdown,
)


def document() -> Block:
    """A path-less tree with nesting, repeated kinds, and a table.

    Shaped to make every addressing rule visible at once: two sections, a
    heading that does not disturb the paragraph numbering beside it, list
    items nested under a section, and a table of rows of cells.
    """
    return Block(
        kind=BlockKind.DOCUMENT,
        matched_by=MATCHED_BY_DOCUMENT,
        confidence=1.0,
        children=(
            Block(
                kind=BlockKind.HEADING,
                text="Master Services Agreement",
                role="title",
                matched_by=matched_by_heading("all_caps"),
                confidence=0.6,
            ),
            Block(
                kind=BlockKind.SECTION,
                label="1",
                matched_by=matched_by_heading("reset"),
                confidence=0.8,
                children=(
                    Block(
                        kind=BlockKind.HEADING,
                        text="Interpretation",
                        label="1",
                        matched_by=matched_by_heading("reset"),
                        confidence=0.8,
                    ),
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text="In this agreement:",
                        matched_by=MATCHED_BY_FALLBACK,
                    ),
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text='"Services" means the services in Schedule 1.',
                        label="1.1",
                        level=2,
                        role="definition",
                        spans=(Span(type="defined_term", start=1, end=9),),
                        matched_by=matched_by_label("decimal_dotted"),
                        confidence=0.9,
                    ),
                    Block(
                        kind=BlockKind.LIST_ITEM,
                        text="Headings do not affect interpretation.",
                        label="1.2",
                        level=2,
                        role="clause",
                        matched_by=matched_by_label("decimal_dotted"),
                        confidence=0.9,
                    ),
                    Block(
                        kind=BlockKind.PARAGRAPH,
                        text="This paragraph continues clause 1.2.",
                        matched_by="continuation",
                        confidence=0.5,
                    ),
                ),
            ),
            Block(
                kind=BlockKind.SECTION,
                label="2",
                matched_by=matched_by_heading("reset"),
                confidence=0.8,
                children=(
                    Block(
                        kind=BlockKind.HEADING,
                        text="Charges",
                        label="2",
                        matched_by=matched_by_heading("reset"),
                        confidence=0.8,
                    ),
                    Block(
                        kind=BlockKind.TABLE,
                        matched_by=matched_by_markdown("pipe_table"),
                        confidence=1.0,
                        children=(
                            Block(
                                kind=BlockKind.ROW,
                                matched_by=matched_by_markdown("pipe_table"),
                                confidence=1.0,
                                children=(
                                    Block(kind=BlockKind.CELL, text="Service"),
                                    Block(kind=BlockKind.CELL, text="Fee"),
                                    Block(kind=BlockKind.CELL, text="Notes"),
                                ),
                            ),
                            Block(
                                kind=BlockKind.ROW,
                                matched_by=matched_by_markdown("pipe_table"),
                                confidence=1.0,
                                children=(
                                    Block(kind=BlockKind.CELL, text="Support"),
                                    Block(kind=BlockKind.CELL, text="$1,000"),
                                    Block(kind=BlockKind.CELL, text="Monthly"),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        ),
    )


def tree() -> BlockTree:
    """The document above, addressed, with one dropped report."""
    return BlockTree.build(
        document(),
        dropped=(Dropped(kind="footnote", count=2, reason="footnotes are not read"),),
    )


# --- the closed structural vocabulary --------------------------------------


def test_block_kinds_are_the_closed_set_from_r1() -> None:
    assert BLOCK_KINDS == (
        "document",
        "section",
        "heading",
        "paragraph",
        "list_item",
        "table",
        "row",
        "cell",
        "unknown",
    )


def test_a_kind_is_its_own_name() -> None:
    # A BlockKind is a str, so it compares, formats and serialises as one.
    kind: str = BlockKind.LIST_ITEM
    assert kind == "list_item"
    assert str(BlockKind.LIST_ITEM) == "list_item"
    assert f"{BlockKind.LIST_ITEM}" == "list_item"
    assert BlockKind.LIST_ITEM.value == "list_item"


def test_a_string_kind_is_accepted_and_converted() -> None:
    block = Block(kind="paragraph")  # type: ignore[arg-type]
    assert block.kind is BlockKind.PARAGRAPH


def test_a_kind_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a block kind"):
        Block(kind="clause")  # type: ignore[arg-type]


def test_the_rejection_names_the_whole_set() -> None:
    with pytest.raises(ValueError) as error:
        Block(kind="recital")  # type: ignore[arg-type]
    for kind in BLOCK_KINDS:
        assert kind in str(error.value)


def test_the_recommended_vocabularies_are_documented_not_enforced() -> None:
    assert "definition" in RECOMMENDED_ROLES
    assert "cross_reference" in RECOMMENDED_SPAN_TYPES
    # A role and a span type outside the recommended set are accepted, which
    # is the point of an open semantic layer (ADR-0005).
    block = Block(
        kind=BlockKind.PARAGRAPH,
        text="A catchword line.",
        role="catchword",
        spans=(Span(type="neutral_citation", start=0, end=1),),
    )
    assert block.role == "catchword"
    assert block.spans[0].type == "neutral_citation"


# --- validation ------------------------------------------------------------


@pytest.mark.parametrize("confidence", [-0.01, 1.01, -1.0, 2.0])
def test_confidence_outside_zero_to_one_is_rejected(confidence: float) -> None:
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        Block(kind=BlockKind.PARAGRAPH, confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 0.5, 1.0])
def test_confidence_at_and_inside_the_bounds_is_accepted(confidence: float) -> None:
    assert (
        Block(kind=BlockKind.PARAGRAPH, confidence=confidence).confidence == confidence
    )


def test_matched_by_must_name_something() -> None:
    with pytest.raises(ValueError, match="matched_by"):
        Block(kind=BlockKind.PARAGRAPH, matched_by="")


def test_a_negative_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="level"):
        Block(kind=BlockKind.PARAGRAPH, level=-1)


def test_a_block_defaults_to_claiming_nothing() -> None:
    block = Block(kind=BlockKind.PARAGRAPH, text="Anything.")
    assert block.matched_by == MATCHED_BY_FALLBACK
    assert block.confidence == 0.0
    assert block.role is None
    assert block.spans == ()
    assert block.attrs == {}


def test_a_span_cannot_end_before_it_starts() -> None:
    with pytest.raises(ValueError, match="before its start"):
        Span(type="date", start=10, end=4)


def test_a_span_cannot_start_before_the_text() -> None:
    with pytest.raises(ValueError, match="negative"):
        Span(type="date", start=-1, end=4)


def test_a_dropped_report_cannot_count_backwards() -> None:
    with pytest.raises(ValueError, match="negative"):
        Dropped(kind="footnote", count=-1, reason="impossible")


def test_attrs_are_copied_not_aliased() -> None:
    attrs: dict[str, Any] = {"line": 4}
    block = Block(kind=BlockKind.PARAGRAPH, attrs=attrs)
    attrs["line"] = 9
    assert block.attrs == {"line": 4}


def test_children_and_spans_are_frozen_into_tuples() -> None:
    block = Block(
        kind=BlockKind.SECTION,
        # Text for the span to lie inside, which `Block` now checks.
        text="x",
        children=[Block(kind=BlockKind.PARAGRAPH)],  # type: ignore[arg-type]
        spans=[Span(type="date", start=0, end=1)],  # type: ignore[arg-type]
    )
    assert isinstance(block.children, tuple)
    assert isinstance(block.spans, tuple)


# --- path assignment (ADR-0029) --------------------------------------------


def test_the_root_is_the_root_path() -> None:
    assert BlockTree.build(document()).root.path == ROOT_PATH == "/"


def test_paths_are_xpath_style_kind_and_one_based_index() -> None:
    addressed = assign_paths(document())
    paths = [block.path for block in iter_blocks(addressed)]
    assert paths == [
        "/",
        "/heading[1]",
        "/section[1]",
        "/section[1]/heading[1]",
        "/section[1]/paragraph[1]",
        "/section[1]/list_item[1]",
        "/section[1]/list_item[2]",
        "/section[1]/paragraph[2]",
        "/section[2]",
        "/section[2]/heading[1]",
        "/section[2]/table[1]",
        "/section[2]/table[1]/row[1]",
        "/section[2]/table[1]/row[1]/cell[1]",
        "/section[2]/table[1]/row[1]/cell[2]",
        "/section[2]/table[1]/row[1]/cell[3]",
        "/section[2]/table[1]/row[2]",
        "/section[2]/table[1]/row[2]/cell[1]",
        "/section[2]/table[1]/row[2]/cell[2]",
        "/section[2]/table[1]/row[2]/cell[3]",
    ]


def test_indices_count_only_same_kind_siblings() -> None:
    # The two paragraphs are the first and second paragraph of the section,
    # even though two list items sit between them.
    addressed = assign_paths(document())
    section = addressed.children[1]
    kinds_and_paths = [(block.kind.value, block.path) for block in section.children]
    assert kinds_and_paths == [
        ("heading", "/section[1]/heading[1]"),
        ("paragraph", "/section[1]/paragraph[1]"),
        ("list_item", "/section[1]/list_item[1]"),
        ("list_item", "/section[1]/list_item[2]"),
        ("paragraph", "/section[1]/paragraph[2]"),
    ]


def test_the_documents_own_kind_is_not_in_its_childrens_paths() -> None:
    addressed = assign_paths(document())
    assert not any("document[" in block.path for block in iter_blocks(addressed))


def test_assign_paths_does_not_touch_the_tree_it_was_given() -> None:
    original = document()
    assign_paths(original)
    assert all(block.path == "" for block in iter_blocks(original))


def test_assign_paths_keeps_every_other_field() -> None:
    original = document()
    addressed = assign_paths(original)
    for before, after in zip(iter_blocks(original), iter_blocks(addressed)):
        assert (before.kind, before.text, before.label, before.level) == (
            after.kind,
            after.text,
            after.label,
            after.level,
        )
        assert (before.role, before.spans, before.matched_by, before.confidence) == (
            after.role,
            after.spans,
            after.matched_by,
            after.confidence,
        )


def test_assigning_paths_twice_changes_nothing() -> None:
    once = assign_paths(document())
    assert assign_paths(once) == once


def test_child_path_builds_one_step() -> None:
    assert child_path(ROOT_PATH, BlockKind.SECTION, 7) == "/section[7]"
    assert child_path("/section[7]", "list_item", 2) == "/section[7]/list_item[2]"
    assert (
        child_path("/table[1]/row[2]", BlockKind.CELL, 3) == "/table[1]/row[2]/cell[3]"
    )


def test_child_path_rejects_a_zero_index() -> None:
    with pytest.raises(ValueError, match="1-based"):
        child_path(ROOT_PATH, BlockKind.SECTION, 0)


def test_child_path_rejects_something_that_is_not_an_address() -> None:
    with pytest.raises(ValueError, match="not a block address"):
        child_path("section[1]", BlockKind.CELL, 1)


# --- resolving an address --------------------------------------------------


def test_block_at_resolves_an_address() -> None:
    built = tree()
    assert built.block_at("/section[1]/list_item[2]").label == "1.2"
    assert built.block_at("/section[2]/table[1]/row[2]/cell[2]").text == "$1,000"
    assert built.block_at(ROOT_PATH) is built.root


def test_block_at_works_before_paths_are_assigned() -> None:
    assert block_at(document(), "/section[1]/list_item[1]").label == "1.1"


def test_block_at_raises_for_an_address_the_tree_has_no_block_for() -> None:
    with pytest.raises(KeyError, match="no block at"):
        tree().block_at("/section[9]")


def test_block_at_rejects_a_malformed_address() -> None:
    with pytest.raises(ValueError, match="not a block address"):
        tree().block_at("/section")


def test_every_assigned_path_resolves_back_to_its_own_block() -> None:
    built = tree()
    for block in built.walk():
        assert built.block_at(block.path) == block


# --- the heading breadcrumb ------------------------------------------------


def test_breadcrumb_collects_the_headings_above_a_block() -> None:
    built = tree()
    assert built.heading_breadcrumb("/section[1]/list_item[2]") == (
        "Master Services Agreement",
        "Interpretation",
    )
    assert built.heading_breadcrumb("/section[2]/table[1]/row[2]/cell[1]") == (
        "Master Services Agreement",
        "Charges",
    )


def test_a_block_never_appears_in_its_own_breadcrumb() -> None:
    built = tree()
    assert built.heading_breadcrumb("/section[1]/heading[1]") == (
        "Master Services Agreement",
    )


def test_the_root_has_no_breadcrumb() -> None:
    assert tree().heading_breadcrumb(ROOT_PATH) == ()


def test_a_block_before_any_heading_has_no_breadcrumb() -> None:
    flat = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            children=(
                Block(kind=BlockKind.PARAGRAPH, text="A preamble."),
                Block(kind=BlockKind.HEADING, text="1. Term"),
                Block(kind=BlockKind.PARAGRAPH, text="A clause."),
            ),
        )
    )
    assert flat.heading_breadcrumb("/paragraph[1]") == ()


def test_breadcrumb_follows_a_flat_tree_of_sibling_headings() -> None:
    flat = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            children=(
                Block(kind=BlockKind.HEADING, text="1. Term"),
                Block(kind=BlockKind.PARAGRAPH, text="A clause."),
                Block(kind=BlockKind.HEADING, text="2. Charges"),
                Block(kind=BlockKind.PARAGRAPH, text="Another clause."),
            ),
        )
    )
    # Only the nearest preceding heading, not every heading before it.
    assert flat.heading_breadcrumb("/paragraph[2]") == ("2. Charges",)


def test_breadcrumb_picks_up_a_heading_that_owns_its_children() -> None:
    nested = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            children=(
                Block(
                    kind=BlockKind.HEADING,
                    text="Schedule 1",
                    children=(
                        Block(kind=BlockKind.PARAGRAPH, text="A schedule item."),
                    ),
                ),
            ),
        )
    )
    assert nested.heading_breadcrumb("/heading[1]/paragraph[1]") == ("Schedule 1",)


def test_heading_breadcrumb_is_also_a_plain_function() -> None:
    assert heading_breadcrumb(assign_paths(document()), "/section[2]/heading[1]") == (
        "Master Services Agreement",
    )


# --- matched_by, confidence, fallback and dropped (ADR-0030) ---------------


def test_matched_by_builders_use_the_recommended_families() -> None:
    assert matched_by_label("decimal_dotted") == "label:decimal_dotted"
    assert matched_by_heading("all_caps") == "heading:all_caps"
    assert matched_by_markdown("atx") == "markdown:atx"


def test_fallback_count_agrees_with_matched_by() -> None:
    built = tree()
    counted = [
        block for block in built.walk() if block.matched_by == MATCHED_BY_FALLBACK
    ]
    assert built.fallback_count == len(counted)
    # The document above has one paragraph nothing recognised, plus the six
    # table cells left at their default.
    assert built.fallback_count == 7


def test_the_root_is_not_counted_as_a_fallback() -> None:
    empty = BlockTree.build(
        Block(kind=BlockKind.DOCUMENT, matched_by=MATCHED_BY_DOCUMENT, confidence=1.0)
    )
    assert empty.fallback_count == 0


def test_a_document_block_defaults_to_the_reserved_document_value() -> None:
    # A reader that forgets the keyword must not make every count one too
    # high, which is the reason ADR-0030 reserves the value at all.
    assert Block(kind=BlockKind.DOCUMENT).matched_by == MATCHED_BY_DOCUMENT
    assert BlockTree.build(Block(kind=BlockKind.DOCUMENT)).fallback_count == 0


def test_saying_a_document_fell_through_is_corrected_rather_than_counted() -> None:
    stated = Block(kind=BlockKind.DOCUMENT, matched_by=MATCHED_BY_FALLBACK)
    assert stated.matched_by == MATCHED_BY_DOCUMENT


def test_every_other_kind_still_defaults_to_fallback() -> None:
    for kind in BlockKind:
        if kind is BlockKind.DOCUMENT:
            continue
        assert Block(kind=kind).matched_by == MATCHED_BY_FALLBACK


def test_a_fully_recognised_tree_counts_no_fallbacks() -> None:
    recognised = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            confidence=1.0,
            children=(
                Block(
                    kind=BlockKind.LIST_ITEM,
                    text="A clause.",
                    label="1.1",
                    matched_by=matched_by_label("decimal_dotted"),
                    confidence=0.9,
                ),
            ),
        )
    )
    assert recognised.fallback_count == 0


def test_dropped_is_reported_on_the_tree() -> None:
    built = tree()
    assert built.dropped == (
        Dropped(kind="footnote", count=2, reason="footnotes are not read"),
    )


def test_a_reader_that_drops_nothing_reports_an_empty_tuple() -> None:
    assert BlockTree.build(document()).dropped == ()


def test_dropped_is_frozen_into_a_tuple() -> None:
    built = BlockTree(
        root=document(),
        dropped=[Dropped(kind="image", count=1, reason="images are not read")],  # type: ignore[arg-type]
    )
    assert isinstance(built.dropped, tuple)


# --- serialisation ---------------------------------------------------------


def test_to_dict_from_dict_round_trips_to_an_equal_tree() -> None:
    built = tree()
    assert BlockTree.from_dict(built.to_dict()) == built


def test_the_round_trip_survives_json() -> None:
    built = tree()
    restored = BlockTree.from_dict(json.loads(json.dumps(built.to_dict())))
    assert restored == built
    assert restored.to_dict() == built.to_dict()


def test_to_dict_carries_every_field_of_a_block() -> None:
    block = tree().block_at("/section[1]/list_item[1]")
    assert block.to_dict() == {
        "kind": "list_item",
        "text": '"Services" means the services in Schedule 1.',
        "label": "1.1",
        "level": 2,
        "path": "/section[1]/list_item[1]",
        "role": "definition",
        "spans": [
            {"type": "defined_term", "start": 1, "end": 9, "value": None},
        ],
        "matched_by": "label:decimal_dotted",
        "confidence": 0.9,
        "attrs": {},
        "children": [],
    }


def test_to_dict_reports_the_fallback_count() -> None:
    built = tree()
    assert built.to_dict()["fallback_count"] == built.fallback_count


def test_from_dict_recomputes_the_fallback_count_rather_than_trusting_it() -> None:
    data = tree().to_dict()
    data["fallback_count"] = 999
    assert BlockTree.from_dict(data).fallback_count == 7


def test_from_dict_needs_a_kind() -> None:
    with pytest.raises(ValueError, match="missing the key 'kind'"):
        Block.from_dict({"text": "no kind here"})


def test_from_dict_needs_a_root() -> None:
    with pytest.raises(ValueError, match="missing the key 'root'"):
        BlockTree.from_dict({"dropped": []})


def test_from_dict_rejects_a_key_the_model_does_not_know() -> None:
    with pytest.raises(ValueError, match="unknown key"):
        Block.from_dict({"kind": "paragraph", "confidance": 0.9})


def test_from_dict_rejects_a_kind_outside_the_closed_set() -> None:
    with pytest.raises(ValueError, match="not a block kind"):
        Block.from_dict({"kind": "clause"})


def test_a_minimal_block_dict_fills_in_the_defaults() -> None:
    block = Block.from_dict({"kind": "paragraph"})
    assert block == Block(kind=BlockKind.PARAGRAPH)


def test_attrs_round_trip() -> None:
    built = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            attrs={"reader": "paragraph", "source_line": 1},
        )
    )
    assert BlockTree.from_dict(built.to_dict()).root.attrs == {
        "reader": "paragraph",
        "source_line": 1,
    }


# --- determinism (N1) ------------------------------------------------------


def test_the_same_input_builds_an_identical_tree() -> None:
    assert BlockTree.build(document()) == BlockTree.build(document())


def test_the_same_tree_serialises_to_identical_json() -> None:
    first = json.dumps(BlockTree.build(document()).to_dict())
    second = json.dumps(BlockTree.build(document()).to_dict())
    assert first == second


def test_key_order_is_stable_across_blocks() -> None:
    built = tree()
    orders = {tuple(block.to_dict()) for block in built.walk()}
    assert len(orders) == 1
