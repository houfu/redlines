"""Where a deleted block sits: `redlines.changes.Anchors` and the change-list order (D4).

A delete has no test address, so the flat change list needs a rule for where
it goes, and M3's renderers need the same rule to draw the deleted block and a
moved block's origin. ADR-0033's amendment states it: a block sits in its own
parent -- the test counterpart of its source parent -- right after its nearest
preceding sibling that *stayed in place*, meaning a sibling with a counterpart
under that same parent that is not the source of a move of its own. With no
such sibling it sits first in the parent: after the parent's own block and
before its first child, or, in the root, before the first block.

M2 sorted a delete after the last earlier block, in pre-order, that had a
counterpart anywhere. A block that had moved out of the section therefore
took the deletion with it.

Each constructed case is the smallest input that separates candidate rules
(decision D4's table): a moved predecessor; a deleted child of a moved clause;
a clause moved out of a moved clause; a trailing insert in the section before
a deleted one; a swap and its mirror; a deleted first child; and a deletion
before the first block. The last two pin what ``Anchor.after is None`` means.
``benchmark/corpus/hand/govinfo-hr7385-ih-to-eh`` is the one committed run
whose order the amendment changes, and its whole node list is pinned. Every
other committed run is checked against the rule as written, recomputed here
from the payload alone.

The constructed cases and the golden run under ``similarity="difflib"``, the
backend every golden is generated with (``tests/corpus/sample_pair/regenerate.py``),
so the expected values do not depend on which extras are installed; one test
checks that rapidfuzz agrees.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

import redlines.changes
from redlines.alignment import AlignedPair, Alignment, AlignmentConfig
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.changes import (
    CHANGE_KINDS,
    Anchor,
    Anchors,
    ChangeKind,
    build_change_tree,
)
from redlines.comparison import Comparison, compare
from redlines.similarity import RAPIDFUZZ_AVAILABLE

from tests.helpers.committed_runs import CommittedRun, committed_runs
from tests.helpers.hash_seed import assert_byte_identical_across_hash_seeds

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLDEN_BACKEND = "difflib"
HR7385 = REPO_ROOT / "benchmark" / "corpus" / "hand" / "govinfo-hr7385-ih-to-eh"

Node = tuple[str, "str | None", "str | None"]


# --- helpers ---------------------------------------------------------------


def compared(source: str, test: str, *, similarity: str = GOLDEN_BACKEND) -> Comparison:
    """Compare two markdown documents under one similarity backend."""
    return compare(
        source,
        test,
        format="markdown",
        alignment=AlignmentConfig(similarity=similarity),
    )


def nodes(comparison: Comparison) -> list[Node]:
    """Each node as (kind, source address, test address), in list order."""
    return [
        (change.kind.value, change.source_address, change.test_address)
        for change in comparison.changes
    ]


def anchors(comparison: Comparison) -> Anchors:
    """The placements for one comparison, built the way the renderers build them."""
    return Anchors(
        source=comparison.source, test=comparison.test, alignment=comparison.alignment
    )


def hr7385(*, similarity: str = GOLDEN_BACKEND) -> Comparison:
    """The committed run the amendment reorders."""
    return compare(
        (HR7385 / "source.txt").read_text(encoding="utf-8"),
        (HR7385 / "test.txt").read_text(encoding="utf-8"),
        format="text",
        alignment=AlignmentConfig(similarity=similarity),
    )


# --- the constructed cases -------------------------------------------------

# 7.3 moves to section 8; 7.4, right after it, is deleted (rd_example_probe.py).
MOVED_PREDECESSOR_SOURCE = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret.

7.2 Neither party shall make a public announcement about this Agreement without consent.

7.3 Each party shall return or destroy the other party's Confidential Information on request.

7.4 This clause survives termination for a period of three years.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' notice to the other.
"""
MOVED_PREDECESSOR_TEST = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret.

7.2 Neither party shall make a public announcement about this Agreement without consent.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' notice to the other.

8.2 Each party shall return or destroy the other party's Confidential Information on request.
"""

# 7.2 moves to section 8 with its (a); its (b) is deleted (rd_scope_probe.py).
MOVED_CHILD_SOURCE = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret.

7.2 Each party shall return or destroy the other party's Confidential Information on request.

(a) The receiving party shall certify the destruction in writing.

(b) The receiving party may keep one archival copy for legal purposes.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' notice to the other.
"""
MOVED_CHILD_TEST = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' notice to the other.

8.2 Each party shall return or destroy the other party's Confidential Information on request.

(a) The receiving party shall certify the destruction in writing.
"""

# 7.2 moves to section 8 with its (a); its (b) leaves it for section 9
# (synth/nested_move_probe.py).
NESTED_MOVE_SOURCE = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret and use it only for this Agreement.

7.2 Each party shall return or destroy the other party's Confidential Information on written request.

(a) The receiving party shall certify the destruction in writing within five Business Days.

(b) The receiving party may keep one archival copy of the information for legal purposes only.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' written notice to the other party.

## 9. Records

9.1 The Supplier shall keep complete records of the Services for six years after the end of the Term.
"""
NESTED_MOVE_TEST = """## 7. Confidentiality

7.1 Each party shall keep the other party's Confidential Information secret and use it only for this Agreement.

## 8. Termination

8.1 Either party may terminate this Agreement on ninety days' written notice to the other party.

8.2 Each party shall return or destroy the other party's Confidential Information on written request.

(a) The receiving party shall certify the destruction in writing within five Business Days.

## 9. Records

9.1 The Supplier shall keep complete records of the Services for six years after the end of the Term.

9.2 The receiving party may keep one archival copy of the information for legal purposes only.
"""

# Section 3 gains a trailing 3.3 and section 4 is deleted
# (synth/anchor_rules_probe2.py).
TRAILING_INSERT_SOURCE = (
    "## 3. Services\n\n3.1 The Supplier shall supply the Services.\n\n"
    "3.2 The Supplier shall meet the Service Levels.\n\n"
    "## 4. Fees\n\n4.1 The Client shall pay the Fees monthly.\n"
)
TRAILING_INSERT_TEST = (
    "## 3. Services\n\n3.1 The Supplier shall supply the Services.\n\n"
    "3.2 The Supplier shall meet the Service Levels.\n\n"
    "3.3 The Supplier may engage subcontractors with consent.\n"
)

# Four list items A M D Z; D is deleted and two of the others swap
# (synth/anchor_rules_probe2.py).
_A = "The Supplier shall deliver the goods to the warehouse nominated by the Buyer."
_M = "Risk in the goods passes to the Buyer when the goods are unloaded at the warehouse."
_D = (
    "Title to the goods passes to the Buyer when the Supplier receives payment in full."
)
_Z = (
    "The Buyer shall inspect the goods within five days of delivery and notify defects."
)
SWAP_SOURCE = f"## 1. Delivery\n\n- {_A}\n\n- {_M}\n\n- {_D}\n\n- {_Z}\n"
SWAP_TEST = f"## 1. Delivery\n\n- {_M}\n\n- {_A}\n\n- {_Z}\n"
MIRRORED_SWAP_TEST = f"## 1. Delivery\n\n- {_A}\n\n- {_Z}\n\n- {_M}\n"

# Clause 1.1's first limb is deleted, and the clause and its second limb edited.
FIRST_CHILD_SOURCE = """## 1. Delivery

1.1 The Supplier shall deliver the goods to the warehouse nominated by the Buyer.

(a) The Supplier shall give the Buyer two days' notice of each delivery.

(b) The Supplier shall deliver only on Business Days.
"""
FIRST_CHILD_TEST = """## 1. Delivery

1.1 The Supplier shall deliver the goods to the warehouse nominated by the Buyer in writing.

(b) The Supplier shall deliver only on Business Days between nine and five.
"""

# A banner before the first heading is deleted, and the heading edited.
FIRST_BLOCK_SOURCE = """DRAFT FOR DISCUSSION ONLY

## 1. Delivery

1.1 The Supplier shall deliver the goods to the warehouse nominated by the Buyer.
"""
FIRST_BLOCK_TEST = """## 1. Delivery and Risk

1.1 The Supplier shall deliver the goods to the warehouse nominated by the Buyer.
"""

CONSTRUCTED: dict[str, tuple[str, str]] = {
    "moved predecessor": (MOVED_PREDECESSOR_SOURCE, MOVED_PREDECESSOR_TEST),
    "deleted child of a moved clause": (MOVED_CHILD_SOURCE, MOVED_CHILD_TEST),
    "nested move": (NESTED_MOVE_SOURCE, NESTED_MOVE_TEST),
    "trailing insert": (TRAILING_INSERT_SOURCE, TRAILING_INSERT_TEST),
    "swap": (SWAP_SOURCE, SWAP_TEST),
    "mirrored swap": (SWAP_SOURCE, MIRRORED_SWAP_TEST),
    "first child": (FIRST_CHILD_SOURCE, FIRST_CHILD_TEST),
    "first block": (FIRST_BLOCK_SOURCE, FIRST_BLOCK_TEST),
}


def test_a_delete_after_a_clause_that_moved_away_stays_in_its_own_section() -> None:
    """7.3 moved to section 8 as 8.2, and 7.4, right after it, was deleted.

    M2 sorted 7.4 after the last earlier block that survived anywhere, which
    was 7.3 at its new address, and so listed the deletion of a
    confidentiality clause inside Termination, after the move. The moved
    clause is no longer there to sit after: 7.4 sits after 7.2. The moved
    clause's own origin is placed the same way, so a renderer draws its
    tombstone there too, ahead of the ghost, in source order.
    """
    comparison = compared(MOVED_PREDECESSOR_SOURCE, MOVED_PREDECESSOR_TEST)
    assert nodes(comparison) == [
        ("delete", "/section[1]/list_item[4]", None),
        ("move", "/section[1]/list_item[3]", "/section[2]/list_item[2]"),
    ]
    placed = anchors(comparison)
    after_7_2 = Anchor(test_parent="/section[1]", after="/section[1]/list_item[2]")
    assert placed.place("/section[1]/list_item[4]") == after_7_2
    assert placed.place("/section[1]/list_item[3]") == after_7_2


def test_a_deleted_child_of_a_moved_clause_sits_inside_the_destination() -> None:
    """7.2 moved to section 8 and took (a) with it; its (b) was deleted.

    (b)'s own parent is 7.2, and 7.2 is now 8.2, so the deletion sits inside
    8.2, after (a). The change list cannot tell this rule from M2's, since
    both list the delete after the move. The anchor is the difference: it is
    where a renderer draws the deleted limb.
    """
    comparison = compared(MOVED_CHILD_SOURCE, MOVED_CHILD_TEST)
    assert nodes(comparison) == [
        ("move", "/section[1]/list_item[2]", "/section[2]/list_item[2]"),
        ("delete", "/section[1]/list_item[2]/list_item[2]", None),
    ]
    assert anchors(comparison).place("/section[1]/list_item[2]/list_item[2]") == (
        Anchor(
            test_parent="/section[2]/list_item[2]",
            after="/section[2]/list_item[2]/list_item[1]",
        )
    )


def test_a_clause_moved_out_of_a_moved_clause_leaves_its_origin_in_the_destination() -> (
    None
):
    """7.2 moved to 8.2, and its (b) left it for 9.2.

    Each landed somewhere its source ancestors did not, so each is a move of
    its own and a ``move`` node. The inner origin is placed in its own
    parent's counterpart, inside 8.2 after (a), which is where the renderers
    draw its tombstone (D15, rule 3).
    """
    comparison = compared(NESTED_MOVE_SOURCE, NESTED_MOVE_TEST)
    assert nodes(comparison) == [
        ("move", "/section[1]/list_item[2]", "/section[2]/list_item[2]"),
        ("move", "/section[1]/list_item[2]/list_item[2]", "/section[3]/list_item[2]"),
    ]
    placed = anchors(comparison)
    assert placed.place("/section[1]/list_item[2]") == Anchor(
        test_parent="/section[1]", after="/section[1]/list_item[1]"
    )
    assert placed.place("/section[1]/list_item[2]/list_item[2]") == Anchor(
        test_parent="/section[2]/list_item[2]",
        after="/section[2]/list_item[2]/list_item[1]",
    )


def test_a_deleted_section_sits_after_the_whole_section_before_it() -> None:
    """Section 3 gained a trailing 3.3, and section 4 was deleted.

    The deletion sits after section 3's whole test subtree, the new 3.3
    included. M2 sorted it after 3.2, the last earlier source block that
    survived, and so listed the deleted section 4 inside section 3, ahead of
    the clause section 3 gained.
    """
    comparison = compared(TRAILING_INSERT_SOURCE, TRAILING_INSERT_TEST)
    assert nodes(comparison) == [
        ("insert", None, "/section[1]/list_item[3]"),
        ("delete", "/section[2]", None),
    ]
    placed = anchors(comparison)
    assert placed.place("/section[2]") == Anchor(test_parent="/", after="/section[1]")
    # Blocks inside a deleted subtree have no anchor of their own: they are
    # drawn with the section they belong to.
    assert placed.place("/section[2]/heading[1]") is None
    assert placed.place("/section[2]/list_item[1]") is None


def test_a_delete_after_a_swap_sits_after_the_sibling_that_stayed() -> None:
    """A M D Z became M A Z, and the alignment calls A the one that moved.

    M stayed, so D sits after M, which is now first, and ahead of A's new
    place. A sibling that moved is skipped as an anchor but still has an
    origin of its own: A's is after the heading's section.
    """
    comparison = compared(SWAP_SOURCE, SWAP_TEST)
    assert nodes(comparison) == [
        ("delete", "/list_item[3]", None),
        ("move", "/list_item[1]", "/list_item[2]"),
    ]
    placed = anchors(comparison)
    assert placed.place("/list_item[3]") == Anchor(
        test_parent="/", after="/list_item[1]"
    )
    assert placed.place("/list_item[1]") == Anchor(test_parent="/", after="/section[1]")


def test_a_delete_after_a_mirrored_swap_skips_the_sibling_that_moved() -> None:
    """A M D Z became A Z M, and the alignment calls M the one that moved.

    M is no longer before Z, so D sits after A, beside the spine that did not
    move, rather than after M's new place at the end. M2 listed the deletion
    after the move; so would a rule that anchored to the moved sibling.
    """
    comparison = compared(SWAP_SOURCE, MIRRORED_SWAP_TEST)
    assert nodes(comparison) == [
        ("delete", "/list_item[3]", None),
        ("move", "/list_item[2]", "/list_item[3]"),
    ]
    assert anchors(comparison).place("/list_item[3]") == Anchor(
        test_parent="/", after="/list_item[1]"
    )


def test_a_deleted_first_child_sits_after_its_parent_and_before_its_siblings() -> None:
    """Clause 1.1's first limb was deleted; 1.1 and its other limb were edited.

    With no earlier sibling, ``after`` is ``None``: the deletion sits after the
    parent's own block and before its first remaining child.
    """
    comparison = compared(FIRST_CHILD_SOURCE, FIRST_CHILD_TEST)
    assert nodes(comparison) == [
        ("modify", "/section[1]/list_item[1]", "/section[1]/list_item[1]"),
        ("delete", "/section[1]/list_item[1]/list_item[1]", None),
        (
            "modify",
            "/section[1]/list_item[1]/list_item[2]",
            "/section[1]/list_item[1]/list_item[1]",
        ),
    ]
    assert anchors(comparison).place("/section[1]/list_item[1]/list_item[1]") == (
        Anchor(test_parent="/section[1]/list_item[1]", after=None)
    )


def test_a_delete_with_nothing_before_it_sits_before_the_first_block() -> None:
    """A banner above the first heading was deleted, and the heading edited.

    First in the root means before the first block of the document, so the
    deletion is listed ahead of everything else.
    """
    comparison = compared(FIRST_BLOCK_SOURCE, FIRST_BLOCK_TEST)
    assert nodes(comparison) == [
        ("delete", "/paragraph[1]", None),
        ("modify", "/section[1]/heading[1]", "/section[1]/heading[1]"),
    ]
    assert anchors(comparison).place("/paragraph[1]") == Anchor(
        test_parent="/", after=None
    )


@pytest.mark.skipif(not RAPIDFUZZ_AVAILABLE, reason="needs rapidfuzz installed")
@pytest.mark.parametrize("case", sorted(CONSTRUCTED))
def test_both_backends_order_and_place_the_constructed_cases_alike(case: str) -> None:
    """The expected values above hold whichever similarity backend runs."""
    source, test = CONSTRUCTED[case]
    seen = []
    for similarity in ("difflib", "rapidfuzz"):
        comparison = compared(source, test, similarity=similarity)
        placed = anchors(comparison)
        seen.append(
            (
                nodes(comparison),
                [placed.place(block.path) for block in comparison.source.walk()],
            )
        )
    assert seen[0] == seen[1]


# --- the one committed run the amendment reorders ---------------------------

# Its 24 nodes in the amended order. Under M2 the delete of
# /section[9]/list_item[1] sat at index 6, straight after the move into
# section 7 of /section[9]/paragraph[2], the last earlier block that survived.
HR7385_NODES: list[Node] = [
    ("modify", "/section[3]/heading[1]", "/section[3]/heading[1]"),
    ("delete", "/section[6]/section[1]/paragraph[1]", None),
    ("delete", "/section[7]/heading[1]", None),
    ("insert", None, "/section[7]/heading[1]"),
    ("insert", None, "/section[7]/paragraph[1]"),
    ("move", "/section[9]/paragraph[2]", "/section[7]/paragraph[2]"),
    ("insert", None, "/section[7]/list_item[1]"),
    (
        "move",
        "/section[9]/list_item[1]/list_item[1]",
        "/section[7]/list_item[1]/list_item[1]",
    ),
    (
        "move",
        "/section[9]/list_item[1]/list_item[2]",
        "/section[7]/list_item[1]/list_item[2]",
    ),
    ("delete", "/section[9]/list_item[1]/list_item[2]/paragraph[1]", None),
    ("insert", None, "/section[7]/list_item[1]/list_item[2]/paragraph[1]"),
    ("insert", None, "/section[7]/list_item[1]/list_item[2]/paragraph[2]"),
    ("insert", None, "/section[7]/list_item[1]/list_item[2]/paragraph[3]"),
    ("delete", "/section[8]/heading[1]", None),
    ("delete", "/section[8]/paragraph[1]", None),
    ("delete", "/section[8]/paragraph[2]", None),
    ("delete", "/section[8]/paragraph[3]", None),
    ("insert", None, "/section[8]/heading[1]"),
    ("delete", "/section[9]/heading[1]", None),
    ("delete", "/section[9]/paragraph[1]", None),
    ("delete", "/section[9]/list_item[1]", None),
    ("insert", None, "/section[9]/heading[1]"),
    ("insert", None, "/section[9]/section[1]"),
    ("insert", None, "/section[10]"),
]


def test_govinfo_hr7385_lists_its_nodes_in_the_amended_order() -> None:
    """The whole node list of the one committed run whose order changed.

    Every earlier sibling of /section[9]/list_item[1] in the source was
    deleted or moved out, so the deleted item sits first in its own section,
    with the two deletions before it, instead of in section 7 where a
    sibling went.
    """
    assert nodes(hr7385()) == HR7385_NODES


def test_govinfo_hr7385_places_the_deleted_item_in_its_own_section() -> None:
    """The anchors behind that order, and the origins of the moves out of it."""
    placed = anchors(hr7385())
    assert placed.place("/section[9]/list_item[1]") == Anchor(
        test_parent="/section[9]", after=None
    )
    # Both sub-items moved out of the deleted item. Their parent has no
    # counterpart, so their origins have no anchor of their own: they are
    # drawn inside the deleted item's ghost.
    assert placed.place("/section[9]/list_item[1]/list_item[1]") is None
    assert placed.place("/section[9]/list_item[1]/list_item[2]") is None
    # A deletion inside a moved sub-item sits in that sub-item's destination.
    assert placed.place("/section[9]/list_item[1]/list_item[2]/paragraph[1]") == (
        Anchor(test_parent="/section[7]/list_item[1]/list_item[2]", after=None)
    )


@pytest.mark.skipif(not RAPIDFUZZ_AVAILABLE, reason="needs rapidfuzz installed")
def test_govinfo_hr7385_has_the_same_order_under_rapidfuzz() -> None:
    """The golden is not a property of the backend it was generated under."""
    assert nodes(hr7385(similarity="rapidfuzz")) == HR7385_NODES


# --- the rule as written, over every committed run --------------------------


def amended_order(comparison: Comparison) -> list[int]:
    """The order ADR-0033's amendment states, as indices into the change list.

    Written from the rule's wording rather than from `redlines.changes`: own
    moves are read off the change list's ``move`` nodes, siblings off the
    source tree and positions off a fresh walk, so a regression in the
    shipped code cannot hide in a helper it shares with this check.
    """
    test_order = {
        block.path: index for index, block in enumerate(comparison.test.walk())
    }
    source_order = {
        block.path: index for index, block in enumerate(comparison.source.walk())
    }
    subtree_end: dict[str, int] = {}

    def end(block: Block) -> int:
        last = test_order[block.path]
        for child in block.children:
            last = max(last, end(child))
        subtree_end[block.path] = last
        return last

    end(comparison.test.root)
    test_parent = {
        child.path: block.path
        for block in comparison.test.walk()
        for child in block.children
    }
    source_parent = {
        child.path: block.path
        for block in comparison.source.walk()
        for child in block.children
    }
    own_moves = {
        change.source_address
        for change in comparison.changes
        if change.kind is ChangeKind.MOVE
    }
    alignment = comparison.alignment

    def delete_rank(path: str) -> int:
        parent = source_parent[path]
        test_parent_of_delete = alignment.test_for(parent)
        assert test_parent_of_delete is not None, path
        anchor: str | None = None
        for sibling in comparison.source.block_at(parent).children:
            if sibling.path == path:
                break
            counterpart = alignment.test_for(sibling.path)
            if (
                counterpart is not None
                and sibling.path not in own_moves
                and test_parent.get(counterpart) == test_parent_of_delete
            ):
                anchor = counterpart
        if anchor is None:
            return test_order[test_parent_of_delete]
        return subtree_end[anchor]

    keyed: list[tuple[tuple[int, int, int, int], int]] = []
    for index, change in enumerate(comparison.changes):
        kind_rank = CHANGE_KINDS.index(change.kind.value)
        if change.kind is ChangeKind.DELETE:
            assert change.source_address is not None
            key = (
                delete_rank(change.source_address),
                1,
                source_order[change.source_address],
                kind_rank,
            )
        else:
            assert change.test_address is not None
            source_rank = (
                -1
                if change.source_address is None
                else source_order[change.source_address]
            )
            key = (test_order[change.test_address], 0, source_rank, kind_rank)
        keyed.append((key, index))
    return [index for _, index in sorted(keyed)]


RUNS: tuple[CommittedRun, ...] = committed_runs()


@pytest.mark.parametrize("run", RUNS, ids=[run.name for run in RUNS])
def test_every_committed_run_lists_its_changes_in_the_amended_order(
    run: CommittedRun,
) -> None:
    """On all 60 runs, the list is already in the order the amendment states."""
    source, test = run.texts()
    comparison = compare(source, test, format=run.format)
    assert amended_order(comparison) == list(range(len(comparison.changes)))


# --- the interface the renderers build on -----------------------------------


def test_an_anchor_is_a_frozen_pair_of_addresses() -> None:
    """Two fields, compared by value, and not mutable once placed."""
    anchor = Anchor(test_parent="/section[1]", after=None)
    assert anchor == Anchor("/section[1]", None)
    assert [field.name for field in dataclasses.fields(Anchor)] == [
        "test_parent",
        "after",
    ]
    with pytest.raises(dataclasses.FrozenInstanceError):
        anchor.after = "/section[1]/list_item[1]"  # type: ignore[misc]


def test_anchors_are_built_from_keyword_arguments_only() -> None:
    """``Anchors(*, source, test, alignment)``: the three inputs cannot be swapped."""
    comparison = compared(TRAILING_INSERT_SOURCE, TRAILING_INSERT_TEST)
    with pytest.raises(TypeError):
        Anchors(  # type: ignore[misc]
            comparison.source, comparison.test, comparison.alignment
        )


def test_the_root_has_no_anchor_and_an_unknown_address_is_an_error() -> None:
    """The root has no parent to sit in; an address from elsewhere is a bug."""
    placed = anchors(compared(TRAILING_INSERT_SOURCE, TRAILING_INSERT_TEST))
    assert placed.place("/") is None
    with pytest.raises(KeyError, match="not an address in the source tree"):
        placed.place("/section[9]")


def test_anchor_and_anchors_are_importable_but_not_yet_documented_surface() -> None:
    """Decision D4: out of `__all__`, which the API reference is built from."""
    assert redlines.changes.Anchor is Anchor
    assert redlines.changes.Anchors is Anchors
    assert "Anchor" not in redlines.changes.__all__
    assert "Anchors" not in redlines.changes.__all__


def test_a_delete_whose_parent_the_alignment_never_mentions_sorts_first() -> None:
    """A hand-built alignment can leave a block's parent unaccounted for.

    `redlines.alignment.align` never does: every source block is paired or
    deleted. A delete with no anchor to sort by is listed first, as if it were
    the first block of the document, rather than failing.
    """
    source = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            children=(
                Block(kind=BlockKind.PARAGRAPH, text="kept"),
                Block(
                    kind=BlockKind.SECTION,
                    children=(
                        Block(kind=BlockKind.HEADING, text="Terms"),
                        Block(kind=BlockKind.PARAGRAPH, text="gone"),
                    ),
                ),
            ),
        )
    )
    test = BlockTree.build(
        Block(
            kind=BlockKind.DOCUMENT,
            children=(Block(kind=BlockKind.PARAGRAPH, text="kept, and edited"),),
        )
    )
    handmade = Alignment(
        pairs=(
            AlignedPair(
                source_path="/", test_path="/", matched_by="root", confidence=1.0
            ),
            AlignedPair(
                source_path="/paragraph[1]",
                test_path="/paragraph[1]",
                matched_by="fuzzy",
                confidence=0.8,
            ),
        ),
        inserted=(),
        deleted=("/section[1]/paragraph[1]",),
        config=AlignmentConfig(similarity=GOLDEN_BACKEND),
        backend=GOLDEN_BACKEND,
        pass_counts={"root": 1, "fuzzy": 1},
    )
    placed = Anchors(source=source, test=test, alignment=handmade)
    assert placed.place("/section[1]/paragraph[1]") is None
    changes = build_change_tree(handmade, source, test)
    assert [(change.kind.value, change.source_address) for change in changes] == [
        ("delete", "/section[1]/paragraph[1]"),
        ("modify", "/paragraph[1]"),
    ]


# --- determinism -------------------------------------------------------------

_PLACE_HR7385 = """
import json
from pathlib import Path

from redlines.alignment import AlignmentConfig
from redlines.changes import Anchors
from redlines.comparison import compare

pair = Path({pair!r})
comparison = compare(
    (pair / "source.txt").read_text(encoding="utf-8"),
    (pair / "test.txt").read_text(encoding="utf-8"),
    format="text",
    alignment=AlignmentConfig(similarity="difflib"),
)
anchors = Anchors(
    source=comparison.source, test=comparison.test, alignment=comparison.alignment
)
placed = {{}}
for block in comparison.source.walk():
    anchor = anchors.place(block.path)
    placed[block.path] = None if anchor is None else [anchor.test_parent, anchor.after]
print(json.dumps({{
    "changes": [change.to_dict() for change in comparison.changes],
    "statistics": comparison.statistics().to_dict(),
    "anchors": placed,
}}))
""".format(pair=str(HR7385))


def test_two_builds_of_hr7385_give_identical_change_lists_and_anchors() -> None:
    """Within one process: the same input, the same list and the same placements."""
    first, second = hr7385(), hr7385()
    assert [c.to_dict() for c in first.changes] == [c.to_dict() for c in second.changes]
    first_anchors, second_anchors = anchors(first), anchors(second)
    for block in first.source.walk():
        assert first_anchors.place(block.path) == second_anchors.place(block.path)


def test_hr7385_is_byte_identical_across_hash_seeds() -> None:
    """Across processes: no placement depends on a string hash (D21, N1)."""
    output = assert_byte_identical_across_hash_seeds(_PLACE_HR7385, cwd=REPO_ROOT)
    result = json.loads(output)
    assert [
        (change["kind"], change["source_address"], change["test_address"])
        for change in result["changes"]
    ] == HR7385_NODES
    assert result["anchors"]["/section[9]/list_item[1]"] == ["/section[9]", None]
