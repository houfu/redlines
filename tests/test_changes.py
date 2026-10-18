"""Tests for the change tree (#136, ADR-0033).

Four kinds of test live here.

The first are unit tests over the value types -- `redlines.changes.Change`,
`redlines.changes.InlineOp` and `redlines.changes.ChangeTree` -- covering the
closed vocabularies, the shapes the model refuses to hold, the three derived
numbers, and the round trip through ``to_dict``/``from_dict``.

The second run `redlines.changes.build_change_tree` over trees built by hand
in this file, one rule per test: kind precedence, topmost-wins granularity,
"an address shift alone is never a change", where a delete sits in a
document-ordered list, and what `redlines.changes.Change.span_types` means.

The third pin the inline ops in characters: an op's own text is a *slice* of
the block's text at its own offsets, which is what makes R27a's recovery exact
and what makes "which spans did this touch?" an interval overlap.

The fourth is the extraction: ``Redlines.changes`` and the change tree now
read one differ's opcodes through one function, so a test compares the two.
"""

from __future__ import annotations

import pytest

from redlines import Redlines
from redlines.alignment import AlignedPair, Alignment, AlignmentConfig, align
from redlines.blocks import Block, BlockKind, BlockTree, Span
from redlines.changes import (
    CHANGE_KINDS,
    RESERVED_CHANGE_KINDS,
    UNMATCHED,
    Change,
    ChangeKind,
    ChangeTree,
    InlineKind,
    InlineOp,
    build_change_tree,
    inline_ops_from_opcodes,
    redlines_from_opcodes,
)
from redlines.processor import NUPUNKT_AVAILABLE, NupunktProcessor, WholeDocumentProcessor

# --- helpers ---------------------------------------------------------------


def block(
    kind: str,
    text: str = "",
    *,
    label: str | None = None,
    role: str | None = None,
    spans: tuple[Span, ...] = (),
    children: tuple[Block, ...] = (),
) -> Block:
    """One block, with only the fields the change tree reads."""
    return Block(
        kind=BlockKind(kind),
        text=text,
        label=label,
        role=role,
        spans=spans,
        children=children,
    )


def tree(*children: Block) -> BlockTree:
    """Wrap children in a ``document`` root and address the result."""
    return BlockTree.build(block("document", children=children))


def built(source: BlockTree, test: BlockTree) -> ChangeTree:
    """Align two trees and build the change tree, the way `compare` does."""
    return build_change_tree(align(source, test), source, test)


def summary(changes: ChangeTree) -> list[tuple[str, str | None, str | None]]:
    """Each node as (kind, source address, test address), in order."""
    return [
        (str(change.kind), change.source_address, change.test_address)
        for change in changes
    ]


def op(
    kind: str,
    *,
    source_start: int = 0,
    source_end: int = 0,
    test_start: int = 0,
    test_end: int = 0,
    source_text: str = "",
    test_text: str = "",
) -> InlineOp:
    """An inline op with every offset defaulting to zero."""
    return InlineOp(
        kind=InlineKind(kind),
        source_start=source_start,
        source_end=source_end,
        test_start=test_start,
        test_end=test_end,
        source_text=source_text,
        test_text=test_text,
    )


# --- the vocabulary --------------------------------------------------------


def test_the_five_kinds_are_the_whole_vocabulary_in_1_0() -> None:
    """`split` and `merge` are reserved names, deliberately not enum members.

    ADR-0009 puts them in 1.1. A consumer switching exhaustively on
    `ChangeKind` today should not have to handle a value nothing emits, so
    they are recorded as a constant instead and widening the enum in 1.1 is
    the additive minor bump ADR-0011 describes.
    """
    assert CHANGE_KINDS == ("insert", "delete", "modify", "move", "renumber")
    assert RESERVED_CHANGE_KINDS == ("split", "merge")
    assert set(RESERVED_CHANGE_KINDS).isdisjoint(CHANGE_KINDS)
    assert [str(kind) for kind in ChangeKind] == list(CHANGE_KINDS)
    assert [str(kind) for kind in InlineKind] == ["insert", "delete", "replace"]
    # A ``str`` enum, so a kind compares equal to its own wire name; the
    # annotation is what stops mypy calling that a non-overlapping check.
    modify: str = ChangeKind.MODIFY
    assert modify == "modify"


def test_a_change_carries_the_alignment_pass_not_the_readers() -> None:
    """`Change.matched_by` is alignment's field, and its vocabulary is closed.

    ADR-0030 reserves the name for exactly this second use. A reader's own
    ``matched_by`` -- ``label:numeric``, ``markdown:atx`` and the rest -- is an
    open vocabulary and belongs on the block, not here.
    """
    Change(
        kind=ChangeKind.MODIFY,
        source_address="/paragraph[1]",
        test_address="/paragraph[1]",
        block_kind=BlockKind.PARAGRAPH,
        matched_by="fuzzy",
        confidence=0.5,
    )
    with pytest.raises(ValueError, match="is not an alignment pass"):
        Change(
            kind=ChangeKind.MODIFY,
            source_address="/paragraph[1]",
            test_address="/paragraph[1]",
            block_kind=BlockKind.PARAGRAPH,
            matched_by="label:numeric",
        )


@pytest.mark.parametrize(
    ("kind", "source_address", "test_address", "complaint"),
    [
        ("modify", None, "/paragraph[1]", "needs a source address"),
        ("modify", "/paragraph[1]", None, "needs a test address"),
        ("move", None, "/paragraph[1]", "needs a source address"),
        ("renumber", "/paragraph[1]", None, "needs a test address"),
        ("delete", "/paragraph[1]", "/paragraph[1]", "no test address"),
        ("insert", "/paragraph[1]", "/paragraph[1]", "no source address"),
        ("insert", None, None, "needs a test address"),
    ],
)
def test_only_an_insert_may_lack_a_source_and_only_a_delete_a_test(
    kind: str, source_address: str | None, test_address: str | None, complaint: str
) -> None:
    """Both addresses on every node, except where a side genuinely is not there.

    A `modify` inside a moved clause has two different addresses, which is why
    every node carries both; the model refuses both halves of the mistake --
    a node missing an address it should have, and an insert or a delete
    claiming one for a document the block is not in.
    """
    with pytest.raises(ValueError, match=complaint):
        Change(
            kind=ChangeKind(kind),
            source_address=source_address,
            test_address=test_address,
            block_kind=BlockKind.PARAGRAPH,
        )


def test_a_delete_may_have_no_test_address_and_an_insert_no_source() -> None:
    """The two shapes that are legitimate."""
    deleted = Change(
        kind=ChangeKind.DELETE,
        source_address="/paragraph[1]",
        test_address=None,
        block_kind=BlockKind.PARAGRAPH,
    )
    inserted = Change(
        kind=ChangeKind.INSERT,
        source_address=None,
        test_address="/paragraph[1]",
        block_kind=BlockKind.PARAGRAPH,
    )
    assert (deleted.test_address, inserted.source_address) == (None, None)


def test_an_inline_op_needs_offsets_that_could_be_a_slice() -> None:
    """An end before its start is not a range, and never comes from the differ."""
    with pytest.raises(ValueError, match="source_start <= source_end"):
        op("replace", source_start=5, source_end=2)
    with pytest.raises(ValueError, match="test_start <= test_end"):
        op("replace", test_start=-1, test_end=-1)


# --- the derived numbers ---------------------------------------------------


def test_the_derived_numbers_are_defined_over_the_inline_ops() -> None:
    """`chars_added`, `chars_deleted` and `tokens_changed`, exactly as ADR-0033 states.

    They are properties rather than fields so the filter (#138) and the
    statistics (#139) cannot end up with two definitions of the same number.
    """
    change = Change(
        kind=ChangeKind.MODIFY,
        source_address="/paragraph[1]",
        test_address="/paragraph[1]",
        block_kind=BlockKind.PARAGRAPH,
        matched_by="exact",
        confidence=1.0,
        inline=(
            op("replace", source_text="four hours", test_text="two hours"),
            op("insert", test_text="and no more"),
        ),
    )
    assert change.has_inline is True
    assert change.chars_added == len("two hours") + len("and no more")
    assert change.chars_deleted == len("four hours")
    assert change.tokens_changed == 2 + 2 + 3


def test_a_node_with_no_inline_ops_has_nothing_to_count() -> None:
    """A move or a renumber of untouched text is not zero characters by accident."""
    change = Change(
        kind=ChangeKind.RENUMBER,
        source_address="/list_item[3]",
        test_address="/list_item[4]",
        block_kind=BlockKind.LIST_ITEM,
        source_label="3.3",
        test_label="3.4",
        matched_by="exact",
        confidence=1.0,
    )
    assert (change.has_inline, change.chars_added, change.chars_deleted) == (
        False,
        0,
        0,
    )
    assert change.tokens_changed == 0


# --- serialisation ---------------------------------------------------------


def test_a_change_tree_round_trips_through_from_dict() -> None:
    """`to_dict` output rebuilds into an equal tree, keys in the authored order."""
    original = ChangeTree(
        changes=(
            Change(
                kind=ChangeKind.MOVE,
                source_address="/list_item[5]",
                test_address="/list_item[6]",
                block_kind=BlockKind.LIST_ITEM,
                source_label="7.5",
                test_label="9.6",
                role="clause",
                span_types=("party",),
                matched_by="move",
                confidence=0.8123456,
                source_text="text",
                test_text="text",
                inline=(op("replace", source_end=4, test_end=4),),
                breadcrumb=("Master Services Agreement",),
            ),
        )
    )
    payload = original.to_dict()
    assert list(payload["changes"][0]) == [
        "kind",
        "source_address",
        "test_address",
        "block_kind",
        "source_label",
        "test_label",
        "role",
        "span_types",
        "matched_by",
        "confidence",
        "source_text",
        "test_text",
        "inline",
        "breadcrumb",
    ]
    assert payload["changes"][0]["confidence"] == 0.8123
    assert ChangeTree.from_dict(payload).changes[0].source_label == "7.5"


def test_a_change_tree_is_a_sequence_of_its_nodes() -> None:
    """Iterating, counting and indexing read the way a list of changes should."""
    node = Change(
        kind=ChangeKind.INSERT,
        source_address=None,
        test_address="/paragraph[1]",
        block_kind=BlockKind.PARAGRAPH,
    )
    changes = ChangeTree(changes=(node,))
    assert len(changes) == 1
    assert changes[0] is node
    assert list(changes) == [node]


def test_an_unknown_key_is_rejected_rather_than_dropped() -> None:
    """The strictness `redlines.blocks` sets: a typo is an error where it was made."""
    with pytest.raises(ValueError, match="change has unknown key"):
        Change.from_dict({"kind": "insert", "block_kind": "paragraph", "spam": 1})
    with pytest.raises(ValueError, match="inline op has unknown key"):
        InlineOp.from_dict({"kind": "insert", "spam": 1})
    with pytest.raises(ValueError, match="change tree has unknown key"):
        ChangeTree.from_dict({"changes": [], "spam": 1})


# --- what becomes a node, and what does not --------------------------------


def test_an_address_shift_alone_is_never_a_change() -> None:
    """One inserted paragraph makes one node, not one per block below it.

    The rule that keeps a single insertion near the top of a document from
    producing a hundred nodes (ADR-0033).
    """
    source = tree(block("paragraph", "alpha"), block("paragraph", "omega"))
    test = tree(
        block("paragraph", "alpha"),
        block("paragraph", "middle"),
        block("paragraph", "omega"),
    )
    assert summary(built(source, test)) == [
        ("insert", None, "/paragraph[2]")
    ]


def test_a_difference_the_differ_cannot_see_is_not_a_change() -> None:
    """Whitespace the tokeniser normalises away produces no node at all.

    The same rule the sample pair's hard-wrapped notices clause relies on:
    two blocks whose text differs only in the whitespace between tokens have
    no inline ops, and a `modify` with no ops would be a change with nothing
    in it.
    """
    source = tree(block("paragraph", "a  notice   given"))
    test = tree(block("paragraph", "a notice given"))
    assert summary(built(source, test)) == []


def test_kind_precedence_keeps_the_edit_on_a_renumbered_clause() -> None:
    """`move > renumber > modify`, and the losing kind's inline ops survive.

    Read literally, "inline ops nest under `modify`" would make a renumbered
    and edited clause a `renumber` node with its text edit silently dropped.
    ADR-0033 settles it the other way: the kind is the strongest thing that
    happened, and the node keeps everything.
    """
    source = tree(
        block(
            "section",
            children=(
                block("heading", "Charges"),
                block("list_item", "pay within thirty days", label="4.1"),
            ),
        )
    )
    test = tree(
        block(
            "section",
            children=(
                block("heading", "Charges"),
                block("list_item", "pay within sixty days", label="4.2"),
            ),
        )
    )
    changes = built(source, test)
    assert summary(changes) == [
        ("renumber", "/section[1]/list_item[1]", "/section[1]/list_item[1]")
    ]
    assert (changes[0].source_label, changes[0].test_label) == ("4.1", "4.2")
    assert changes[0].has_inline is True
    assert changes[0].inline[0].source_text == "thirty "


def test_an_inserted_subtree_is_one_node_at_its_topmost_block() -> None:
    """Topmost wins: the subtree is in the test tree, at that address."""
    source = tree(block("paragraph", "kept"))
    test = tree(
        block("paragraph", "kept"),
        block(
            "section",
            children=(block("heading", "New"), block("paragraph", "brand new")),
        ),
    )
    assert summary(built(source, test)) == [("insert", None, "/section[1]")]


def test_a_deleted_subtree_is_one_node_at_its_topmost_block() -> None:
    """The same rule from the other end: one `delete`, not one per lost block."""
    source = tree(
        block("paragraph", "kept"),
        block(
            "section",
            children=(block("heading", "Gone"), block("paragraph", "also gone")),
        ),
    )
    test = tree(block("paragraph", "kept"))
    assert summary(built(source, test)) == [("delete", "/section[1]", None)]


def test_a_delete_sorts_after_the_block_it_used_to_follow() -> None:
    """A delete has no test address, so it is placed by its surviving neighbour.

    That is where a reader looking at the amended document notices it
    missing, and it is what keeps the flat list in document order.
    """
    source = tree(
        block("paragraph", "one"),
        block("paragraph", "two"),
        block("paragraph", "three"),
    )
    test = tree(block("paragraph", "one"), block("paragraph", "three edited"))
    assert summary(built(source, test)) == [
        ("delete", "/paragraph[2]", None),
        ("modify", "/paragraph[3]", "/paragraph[2]"),
    ]


def test_a_move_carries_both_addresses_and_its_child_edit_is_its_own_node() -> None:
    """ADR-0009's demo case in miniature: the move and the edit are separable."""
    moved = (
        "Each party shall return or destroy the other party's Confidential "
        "Information within ten Business Days of a written request."
    )
    source = tree(
        block(
            "section",
            children=(
                block("heading", "Confidentiality"),
                block(
                    "list_item",
                    moved,
                    label="7.5",
                    children=(block("paragraph", "The obligations continue for three years."),),
                ),
            ),
        ),
        block("section", children=(block("heading", "Termination"),)),
    )
    test = tree(
        block("section", children=(block("heading", "Confidentiality"),)),
        block(
            "section",
            children=(
                block("heading", "Termination"),
                block(
                    "list_item",
                    moved,
                    label="9.6",
                    children=(block("paragraph", "The obligations continue for five years."),),
                ),
            ),
        ),
    )
    changes = built(source, test)
    kinds = {str(change.kind) for change in changes}
    assert "move" in kinds
    move = next(change for change in changes if str(change.kind) == "move")
    assert move.source_address == "/section[1]/list_item[1]"
    assert move.test_address == "/section[2]/list_item[1]"
    assert (move.source_label, move.test_label) == ("7.5", "9.6")
    assert move.inline == ()

    body = next(
        change
        for change in changes
        if change.test_address == "/section[2]/list_item[1]/paragraph[1]"
    )
    assert str(body.kind) == "modify"
    assert body.source_address == "/section[1]/list_item[1]/paragraph[1]"
    assert body.inline[0].source_text == "three "


# --- span types ------------------------------------------------------------


def test_span_types_on_an_edit_are_the_spans_the_edit_touched() -> None:
    """ADR-0005's word read strictly, which is the whole point of the field.

    A block with a party span at the front and a cross-reference at the back
    reports only the one the edit landed on; reporting both would bury the
    signal PRD § 3a promises.
    """
    text = "The Client may terminate under clause 3.3."
    spans = (
        Span(type="party", start=4, end=10),
        Span(type="cross_reference", start=38, end=41, value="3.3"),
    )
    source = tree(block("paragraph", text, spans=spans))
    test = tree(
        block(
            "paragraph",
            "The Client may terminate under clause 3.4.",
            spans=(
                Span(type="party", start=4, end=10),
                Span(type="cross_reference", start=38, end=41, value="3.4"),
            ),
        )
    )
    changes = built(source, test)
    assert changes[0].span_types == ("cross_reference",)


def test_span_types_on_an_insert_are_every_span_on_the_block() -> None:
    """For a whole new block there is no "part that changed": all of it did."""
    source = tree(block("paragraph", "kept"))
    test = tree(
        block("paragraph", "kept"),
        block(
            "paragraph",
            "The Client pays on 1 March 2026.",
            spans=(
                Span(type="party", start=4, end=10),
                Span(type="date", start=19, end=31, value="2026-03-01"),
                Span(type="party", start=4, end=10),
            ),
        ),
    )
    changes = built(source, test)
    assert changes[0].span_types == ("date", "party")


# --- inline ops, in characters ---------------------------------------------


def test_an_inline_op_is_a_slice_of_the_block_it_belongs_to() -> None:
    """Offsets are into each block's own text, and the op's text proves it.

    R27a's recovery is exact only if this holds for every op: the source text
    can be spliced back out of the test text from the offsets alone.
    """
    source_text = "The Supplier shall respond within four hours and restore within two days."
    test_text = "The Supplier shall respond within two hours and restore within one day."
    source = tree(block("paragraph", source_text))
    test = tree(block("paragraph", test_text))
    changes = built(source, test)
    assert changes[0].inline
    for change_op in changes[0].inline:
        assert (
            source_text[change_op.source_start : change_op.source_end]
            == change_op.source_text
        )
        assert (
            test_text[change_op.test_start : change_op.test_end] == change_op.test_text
        )
    recovered = test_text
    for change_op in reversed(changes[0].inline):
        recovered = (
            recovered[: change_op.test_start]
            + change_op.source_text
            + recovered[change_op.test_end :]
        )
    assert recovered == source_text


def test_an_inline_insert_records_where_in_the_source_it_went_in() -> None:
    """A zero-width source range, which v1's `Redline` cannot express.

    ``Redline.source_position`` is ``None`` for an insert, so the change tree
    reads the opcodes for its own offsets rather than the token positions --
    and the insertion point is exactly what a renderer splicing by character
    needs.
    """
    source = tree(block("paragraph", "alpha omega"))
    test = tree(block("paragraph", "alpha beta omega"))
    inline = built(source, test)[0].inline
    assert len(inline) == 1
    assert str(inline[0].kind) == "insert"
    assert inline[0].source_start == inline[0].source_end == 6
    assert (inline[0].test_start, inline[0].test_end) == (6, 11)
    assert inline[0].test_text == "beta "


def test_the_ops_survive_a_processor_that_marks_paragraph_boundaries() -> None:
    """A block whose text has a hard break still gets offsets into its own text.

    The differ inserts a ``¶`` token that has no counterpart in the text at
    all. Locating tokens by scanning the text rather than by adding up their
    lengths is what keeps the offsets honest when that happens.
    """
    source_text = "First line.\nfour hours."
    test_text = "First line.\ntwo hours."
    source = tree(block("paragraph", source_text))
    test = tree(block("paragraph", test_text))
    inline = built(source, test)[0].inline
    assert inline
    for change_op in inline:
        assert (
            source_text[change_op.source_start : change_op.source_end]
            == change_op.source_text
        )
        assert (
            test_text[change_op.test_start : change_op.test_end] == change_op.test_text
        )


@pytest.mark.skipif(not NUPUNKT_AVAILABLE, reason="nupunkt is an optional extra")
def test_a_sentence_marking_processor_still_yields_slices() -> None:
    """The other marker, from the other processor, held to the same standard."""
    source_text = "One thing. The Supplier responds within four hours."
    test_text = "One thing. The Supplier responds within two hours."
    source = tree(block("paragraph", source_text))
    test = tree(block("paragraph", test_text))
    changes = build_change_tree(
        align(source, test), source, test, processor=NupunktProcessor()
    )
    assert changes[0].inline
    for change_op in changes[0].inline:
        assert (
            source_text[change_op.source_start : change_op.source_end]
            == change_op.source_text
        )


# --- the extraction --------------------------------------------------------


def test_the_v1_redline_list_is_the_extracted_function() -> None:
    """``Redlines.changes`` and the change tree read one differ through one function.

    ADR-0010's reuse rule made concrete: `redlines_from_opcodes` is
    ``Redlines.changes``'s own body, lifted out, and this asserts the facade
    still gets exactly what it used to.
    """
    facade = Redlines(
        "The quick brown fox jumps over the lazy dog.",
        "The quick brown fox walks past the lazy dog.",
    )
    processor = WholeDocumentProcessor(autojunk=False)
    diff_ops = processor.process(
        "The quick brown fox jumps over the lazy dog.",
        "The quick brown fox walks past the lazy dog.",
    )
    assert facade.changes == redlines_from_opcodes(diff_ops)
    assert [redline.operation for redline in facade.changes] == ["replace"]


def test_the_two_representations_report_the_same_edits() -> None:
    """One opcode filter, so the token frame and the character frame agree."""
    source_text = "acknowledge within four hours and restore within two Business Days."
    test_text = "acknowledge within two hours and restore within one Business Day."
    processor = WholeDocumentProcessor(autojunk=False)
    diff_ops = processor.process(source_text, test_text)
    as_redlines = redlines_from_opcodes(diff_ops)
    as_ops = inline_ops_from_opcodes(
        diff_ops, source_text=source_text, test_text=test_text
    )
    assert [redline.operation for redline in as_redlines] == [
        str(inline.kind) for inline in as_ops
    ]


# --- building from an alignment --------------------------------------------


def test_the_builder_reads_the_alignment_it_is_given() -> None:
    """`build_change_tree` classifies pairs; it does not re-align anything.

    An alignment that says two unrelated blocks correspond produces a
    `modify` between them, which is how the benchmark and the M3 facade get
    to hand in an alignment of their own.
    """
    source = tree(block("paragraph", "alpha"))
    test = tree(block("paragraph", "omega"))
    handmade = Alignment(
        pairs=(
            AlignedPair(
                source_path="/",
                test_path="/",
                matched_by="root",
                confidence=1.0,
            ),
            AlignedPair(
                source_path="/paragraph[1]",
                test_path="/paragraph[1]",
                matched_by="positional",
                confidence=0.25,
            ),
        ),
        inserted=(),
        deleted=(),
        config=AlignmentConfig(),
        backend="difflib",
        pass_counts={"root": 1, "positional": 1},
    )
    changes = build_change_tree(handmade, source, test)
    assert summary(changes) == [("modify", "/paragraph[1]", "/paragraph[1]")]
    assert changes[0].matched_by == "positional"
    assert changes[0].confidence == 0.25


def test_a_block_that_rode_along_inside_a_move_is_not_a_second_move() -> None:
    """Topmost wins for moves too, and the passenger keeps its own kind.

    An alignment that flagged a whole subtree as moved -- which 1.0's move
    pass does not do, since it excludes container kinds, but a later one
    might -- must still produce one node at the top. The child that also
    changed is reported as the `modify` it is, carrying both of its
    addresses, which is the same rule the benchmark scores moves under.
    """
    source = tree(
        block(
            "section",
            children=(block("heading", "Confidentiality"), block("paragraph", "three years")),
        ),
        block("section", children=(block("heading", "Termination"),)),
    )
    test = tree(
        block("section", children=(block("heading", "Termination"),)),
        block(
            "section",
            children=(block("heading", "Confidentiality"), block("paragraph", "five years")),
        ),
    )
    handmade = Alignment(
        pairs=(
            AlignedPair(source_path="/", test_path="/", matched_by="root", confidence=1.0),
            AlignedPair(
                source_path="/section[1]",
                test_path="/section[2]",
                matched_by="move",
                confidence=1.0,
                moved=True,
            ),
            AlignedPair(
                source_path="/section[1]/heading[1]",
                test_path="/section[2]/heading[1]",
                matched_by="move",
                confidence=1.0,
                moved=True,
            ),
            AlignedPair(
                source_path="/section[1]/paragraph[1]",
                test_path="/section[2]/paragraph[1]",
                matched_by="move",
                confidence=0.6,
                moved=True,
            ),
            AlignedPair(
                source_path="/section[2]",
                test_path="/section[1]",
                matched_by="exact",
                confidence=1.0,
            ),
            AlignedPair(
                source_path="/section[2]/heading[1]",
                test_path="/section[1]/heading[1]",
                matched_by="exact",
                confidence=1.0,
            ),
        ),
        inserted=(),
        deleted=(),
        config=AlignmentConfig(),
        backend="difflib",
        pass_counts={"root": 1, "move": 3, "exact": 2},
    )
    changes = build_change_tree(handmade, source, test)
    assert summary(changes) == [
        ("move", "/section[1]", "/section[2]"),
        ("modify", "/section[1]/paragraph[1]", "/section[2]/paragraph[1]"),
    ]
    assert changes[1].inline[0].source_text == "three "


def test_the_root_pair_is_never_a_change() -> None:
    """The root is given rather than found, and two documents always have one."""
    source = tree(block("paragraph", "alpha"))
    test = tree(block("paragraph", "alpha"))
    assert list(built(source, test)) == []


def test_a_change_node_carries_the_test_side_breadcrumb() -> None:
    """Precomputed, so a summary or a section rollup never re-walks the tree."""
    source = tree(
        block(
            "section",
            children=(block("heading", "Charges"), block("paragraph", "thirty days")),
        )
    )
    test = tree(
        block(
            "section",
            children=(block("heading", "Charges"), block("paragraph", "sixty days")),
        )
    )
    changes = built(source, test)
    assert changes[0].breadcrumb == ("Charges",)
    assert str(changes[0].block_kind) == "paragraph"


def test_a_deleted_block_reports_its_own_side() -> None:
    """Kind, role, label, text and breadcrumb all come from the source tree."""
    source = tree(
        block(
            "section",
            children=(
                block("heading", "Charges"),
                block("list_item", "the disputed part", label="(c)", role="sub_clause"),
            ),
        )
    )
    test = tree(block("section", children=(block("heading", "Charges"),)))
    changes = built(source, test)
    assert summary(changes) == [("delete", "/section[1]/list_item[1]", None)]
    assert changes[0].role == "sub_clause"
    assert changes[0].source_label == "(c)"
    assert changes[0].test_text == ""
    assert changes[0].breadcrumb == ("Charges",)
    assert changes[0].matched_by == UNMATCHED
