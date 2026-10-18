"""Tests for the multi-pass alignment (#131, ADR-0032).

Three kinds of test live here.

The first are unit tests, one per pass, over trees built by hand in this file.
A pass is a rule about *why* two blocks correspond, so each of these asserts
the ``matched_by`` as well as the pairing: an ``exact`` match that arrived by
accident through the fill-in is a different engine with the same output, and
the pass record is the thing users are asked to trust.

The second run the real thing over the PRD § 3a sample pair, under both
profiles, and pin every pair the design predicts -- the two renumbers, the
three edited clauses and their scores, the inserted table row, the deleted
sub-clause, and the clause that moved from section 7 to section 9. The move
pass itself is exercised in ``tests/test_alignment_moves.py`` (#132); what is
pinned here is the shape of the whole record with it running.

The third are the promises that are not about any one pass: that the same
input aligned twice gives the same record (#135), that what a *reader* wrote
in ``matched_by``/``confidence`` cannot change the answer (ADR-0030), and that
2,000 blocks align in well under five seconds (N2).
"""

from __future__ import annotations

import dataclasses
import json
import time
from pathlib import Path
from typing import Any

import pytest

from redlines.alignment import (
    DEFAULT_ALIGNMENT,
    MANDATORY_PASSES,
    PASS_NAMES,
    RESERVED_PASS_NAMES,
    AlignedPair,
    Alignment,
    AlignmentConfig,
    align,
)
from redlines.blocks import Block, BlockKind, BlockTree

EXPECTED_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"

# The sample pair's clause 3.3 before the amendment, and the brand new clause
# that took its number. They share a label and share almost no words: difflib
# scores them 0.20, which is the measurement ADR-0032's 0.35 label floor is
# set from.
OLD_3_3 = (
    "The Supplier shall meet each Service Level and shall report on its "
    "performance against the Service Levels for each month within five "
    "Business Days of the end of that month."
)
NEW_3_3 = (
    "The Supplier may engage a subcontractor to supply any part of the "
    "Services, and remains responsible for the acts and omissions of that "
    "subcontractor as if they were its own."
)


# --- helpers ---------------------------------------------------------------


def block(
    kind: str,
    text: str = "",
    *,
    label: str | None = None,
    role: str | None = None,
    children: tuple[Block, ...] = (),
) -> Block:
    """One block, with only the fields alignment is allowed to look at."""
    return Block(
        kind=BlockKind(kind), text=text, label=label, role=role, children=children
    )


def tree(*children: Block) -> BlockTree:
    """Wrap children in a ``document`` root and address the result."""
    return BlockTree.build(block("document", children=children))


def row(*cells: str) -> Block:
    """A table row of plain cells."""
    return block("row", children=tuple(block("cell", text=cell) for cell in cells))


def pairs_by_source(alignment: Alignment) -> dict[str, AlignedPair]:
    """The pairs keyed by source address, for readable assertions."""
    return {pair.source_path: pair for pair in alignment.pairs}


def matched(alignment: Alignment, source_path: str) -> AlignedPair:
    """The pair for ``source_path``, or a failure naming what was matched."""
    found = pairs_by_source(alignment).get(source_path)
    assert found is not None, (
        f"{source_path} was not matched; deleted={alignment.deleted}"
    )
    return found


def load_sample(name: str) -> BlockTree:
    """One of the four frozen M1 trees for the sample pair."""
    return BlockTree.from_dict(json.loads((EXPECTED_DIR / name).read_text()))


@pytest.fixture(params=["markdown", "contract"])
def sample(request: pytest.FixtureRequest) -> tuple[BlockTree, BlockTree]:
    """The sample pair as read under one of the two profiles."""
    twin = request.param
    return load_sample(f"source.{twin}.json"), load_sample(f"test.{twin}.json")


# --- the vocabulary --------------------------------------------------------


def test_the_pass_names_are_the_six_the_adr_names() -> None:
    """A closed vocabulary: a consumer switching on it switches exhaustively."""
    assert PASS_NAMES == (
        "exact",
        "label",
        "structural",
        "fuzzy",
        "move",
        "positional",
    )
    assert RESERVED_PASS_NAMES == ("root", "unmatched")
    assert set(MANDATORY_PASSES) <= set(PASS_NAMES)


def test_the_root_pair_is_given_rather_than_found() -> None:
    """No pass matched the root, because a document is not evidence of itself."""
    same = tree(block("paragraph", "Alpha."))
    alignment = align(same, tree(block("paragraph", "Alpha.")))
    root = alignment.pairs[0]
    assert (root.source_path, root.test_path) == ("/", "/")
    assert root.matched_by == "root"
    assert root.confidence == 1.0
    assert root.moved is False
    assert root.renumbered is False
    assert alignment.pass_counts["root"] == 1


def test_pass_counts_always_carry_every_name() -> None:
    """Fixed shape on the wire, so a pass that fired nothing is visible as 0."""
    alignment = align(
        tree(block("paragraph", "Alpha.")), tree(block("paragraph", "Alpha."))
    )
    assert list(alignment.pass_counts) == ["root", *PASS_NAMES]


# --- pass 1: exact ---------------------------------------------------------


def test_identical_text_matches_exactly() -> None:
    source = tree(block("paragraph", "Alpha."), block("paragraph", "Beta."))
    test = tree(block("paragraph", "Alpha."), block("paragraph", "Beta."))
    alignment = align(source, test)
    assert matched(alignment, "/paragraph[1]").matched_by == "exact"
    assert matched(alignment, "/paragraph[1]").confidence == 1.0
    assert alignment.pass_counts["exact"] == 2


def test_a_whitespace_only_difference_is_still_an_exact_match() -> None:
    """The sample pair's clause 11.5 reflowed, and reports nothing (change 7)."""
    source = tree(block("paragraph", "Alpha  beta.\n   Gamma."))
    test = tree(block("paragraph", "Alpha beta. Gamma."))
    assert matched(align(source, test), "/paragraph[1]").matched_by == "exact"


def test_case_is_not_folded() -> None:
    """A case change is a real change, so the match key must not hide it."""
    alignment = align(
        tree(block("paragraph", "Alpha.")), tree(block("paragraph", "ALPHA."))
    )
    assert alignment.pass_counts["exact"] == 0


def test_exact_matches_reorder_freely_within_a_sibling_group() -> None:
    """Content decides; position is only ever the fallback."""
    source = tree(block("paragraph", "Alpha."), block("paragraph", "Beta."))
    test = tree(block("paragraph", "Beta."), block("paragraph", "Alpha."))
    alignment = align(source, test)
    assert matched(alignment, "/paragraph[1]").test_path == "/paragraph[2]"
    assert matched(alignment, "/paragraph[2]").test_path == "/paragraph[1]"


def test_repeated_text_is_consumed_in_document_order() -> None:
    """Thirty identical "Intentionally omitted." blocks must pair predictably."""
    same = "Intentionally omitted."
    source = tree(*(block("paragraph", same) for _ in range(3)))
    test = tree(*(block("paragraph", same) for _ in range(3)))
    alignment = align(source, test)
    for index in (1, 2, 3):
        assert matched(alignment, f"/paragraph[{index}]").test_path == (
            f"/paragraph[{index}]"
        )


def test_a_paragraph_may_match_a_list_item() -> None:
    """A clause that lost its number is still the same clause (ADR-0032)."""
    source = tree(block("list_item", "Alpha.", label="1"))
    test = tree(block("paragraph", "Alpha."))
    assert matched(align(source, test), "/list_item[1]").test_path == "/paragraph[1]"


def test_a_cell_never_matches_a_paragraph() -> None:
    """Kind classes keep table content inside tables."""
    source = tree(block("table", children=(row("Alpha."),)))
    test = tree(block("paragraph", "Alpha."))
    alignment = align(source, test)
    assert "/table[1]/row[1]/cell[1]" in alignment.deleted
    assert "/paragraph[1]" in alignment.inserted


def test_a_section_matches_on_its_headings_label_and_text() -> None:
    """Section 7 pairs with section 7 in one step, before anything is scored."""
    source = tree(
        block("section", children=(block("heading", "Termination", label="7"),)),
        block("section", children=(block("heading", "Notices", label="8"),)),
    )
    test = tree(
        block("section", children=(block("heading", "Notices", label="8"),)),
        block("section", children=(block("heading", "Termination", label="7"),)),
    )
    alignment = align(source, test)
    assert matched(alignment, "/section[1]").matched_by == "exact"
    assert matched(alignment, "/section[1]").test_path == "/section[2]"


# --- pass 2: label ---------------------------------------------------------


def test_an_edited_clause_matches_on_its_label() -> None:
    source = tree(block("list_item", "The term is thirty days.", label="7.1"))
    test = tree(block("list_item", "The term is sixty days.", label="7.1"))
    pair = matched(align(source, test), "/list_item[1]")
    assert pair.matched_by == "label"
    assert 0.35 < pair.confidence < 1.0


def test_the_label_floor_rejects_a_renumbered_clause_against_a_new_one() -> None:
    """The measurement ADR-0032's 0.35 floor exists for.

    Source clause 3.3 was renumbered to 3.4 *and* edited, so ``exact`` cannot
    reach it, and the block now carrying label 3.3 in the test document is a
    brand new clause. They score 0.20 against each other. Matching them would
    report one confident piece of nonsense and cascade into a run of wrong
    renumbers; falling through to a delete and an insert is the honest answer.
    """
    source = tree(block("list_item", OLD_3_3 + " Reported monthly.", label="3.3"))
    test = tree(block("list_item", NEW_3_3, label="3.3"))
    alignment = align(source, test)
    assert alignment.deleted == ("/list_item[1]",)
    assert alignment.inserted == ("/list_item[1]",)
    assert alignment.pass_counts["label"] == 0


def test_the_label_floor_is_configurable_and_lowering_it_matches_them() -> None:
    """The knob is not provisional even though the number is."""
    source = tree(block("list_item", OLD_3_3, label="3.3"))
    test = tree(block("list_item", NEW_3_3, label="3.3"))
    config = AlignmentConfig(label_min_similarity=0.1)
    assert matched(align(source, test, config=config), "/list_item[1]").matched_by == (
        "label"
    )


def test_two_empty_blocks_under_one_label_bypass_the_floor() -> None:
    """A floor over no text is meaningless (ADR-0032).

    A reader that puts a heading's whole text into its label leaves the block
    with none, and a heading pair must not be blocked by a similarity nobody
    can measure.
    """
    source = tree(
        block("section", children=(block("heading", "", label="Schedule 1"),)),
        block("section", children=(block("heading", "", label="Schedule 2"),)),
    )
    test = tree(
        block("section", children=(block("heading", "", label="Schedule 2"),)),
        block("section", children=(block("heading", "", label="Schedule 1"),)),
    )
    alignment = align(source, test)
    assert matched(alignment, "/section[1]/heading[1]").matched_by == "label"
    assert matched(alignment, "/section[1]").test_path == "/section[2]"


def test_the_label_pass_can_be_dropped() -> None:
    """ADR-0008's review gate needs to be able to cut a pass and re-measure."""
    source = tree(block("list_item", "The term is thirty days.", label="7.1"))
    test = tree(block("list_item", "The term is sixty days.", label="7.1"))
    config = AlignmentConfig(passes=("exact", "structural", "positional"))
    alignment = align(source, test, config=config)
    assert alignment.pass_counts["label"] == 0
    assert matched(alignment, "/list_item[1]").matched_by == "positional"


def test_a_label_never_matches_across_kind_classes() -> None:
    source = tree(block("heading", "Termination", label="7"))
    test = tree(block("list_item", "Termination", label="7"))
    alignment = align(source, test)
    assert alignment.deleted == ("/heading[1]",)


# --- pass 3: structural ----------------------------------------------------


def test_a_headingless_section_pairs_so_the_descent_can_continue() -> None:
    source = tree(block("section", children=(block("paragraph", "Alpha."),)))
    test = tree(block("section", children=(block("paragraph", "Beta and gamma."),)))
    alignment = align(source, test)
    assert matched(alignment, "/section[1]").matched_by == "structural"
    assert matched(alignment, "/section[1]").confidence == 1.0


def test_a_table_is_paired_structurally_so_its_rows_are_compared() -> None:
    """Regression, from a prototype that skipped this pass (ADR-0032).

    Without it the sample pair's table never paired, its rows were never
    compared, and thirteen of its cells came out as moves.
    """
    source = tree(block("table", children=(row("Milestone", "Date"),)))
    test = tree(block("table", children=(row("Milestone", "Date"),)))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]").matched_by == "structural"
    assert matched(alignment, "/table[1]/row[1]").matched_by == "exact"


def test_structural_pairing_is_within_a_kind_class() -> None:
    source = tree(block("section", children=(block("paragraph", "Alpha."),)))
    test = tree(block("table", children=(row("Alpha."),)))
    alignment = align(source, test)
    assert "/section[1]" in alignment.deleted
    assert "/table[1]" in alignment.inserted


# --- pass 4: fuzzy ---------------------------------------------------------


def test_a_rewritten_unlabelled_paragraph_matches_fuzzily() -> None:
    source = tree(
        block("paragraph", "Alpha."),
        block("paragraph", "The Supplier shall provide the Services with care."),
        block("paragraph", "Omega."),
    )
    test = tree(
        block("paragraph", "Alpha."),
        block("paragraph", "The Supplier shall provide the Services with due care."),
        block("paragraph", "Omega."),
    )
    pair = matched(align(source, test), "/paragraph[2]")
    assert pair.matched_by == "fuzzy"
    assert pair.confidence >= DEFAULT_ALIGNMENT.fuzzy_min_similarity


def test_text_below_the_fuzzy_threshold_falls_through() -> None:
    source = tree(block("paragraph", "Alpha."), block("paragraph", OLD_3_3))
    test = tree(block("paragraph", "Alpha."), block("paragraph", NEW_3_3))
    alignment = align(
        source,
        test,
        # Without the fill-in the two would still pair positionally; this test
        # is about the fuzzy pass alone, so the fill-in's floor is raised out
        # of the way rather than the pass being dropped.
        config=AlignmentConfig(positional_min_similarity=0.9),
    )
    assert alignment.deleted == ("/paragraph[2]",)
    assert alignment.inserted == ("/paragraph[2]",)


def test_the_fuzzy_pass_does_not_look_across_an_anchor() -> None:
    """Gap scoping is a correctness rule before it is a performance one.

    The two rewritten paragraphs sit on opposite sides of an anchor. Matching
    them would claim a correspondence that crosses a block both documents
    agree about, which is a move, not an edit -- and moves are the move pass's
    to find, with its own much higher threshold. So the pair is asserted twice:
    with the move pass dropped there is no pair at all, which is what proves
    ``fuzzy`` never looked across the anchor, and with it running the pair
    exists and says ``move``.
    """
    source = tree(
        block("paragraph", "The Supplier shall provide the Services with care."),
        block("paragraph", "ANCHOR."),
        block("paragraph", "Unrelated."),
    )
    test = tree(
        block("paragraph", "Unrelated."),
        block("paragraph", "ANCHOR."),
        block("paragraph", "The Supplier shall provide the Services with due care."),
    )
    without_moves = AlignmentConfig(
        passes=("exact", "label", "structural", "fuzzy", "positional"),
        positional_min_similarity=0.9,
    )
    alignment = align(source, test, config=without_moves)
    assert "/paragraph[1]" in alignment.deleted
    assert "/paragraph[3]" in alignment.inserted
    found = matched(
        align(source, test, config=AlignmentConfig(positional_min_similarity=0.9)),
        "/paragraph[1]",
    )
    assert (found.matched_by, found.test_path) == ("move", "/paragraph[3]")


def test_the_fuzzy_window_bounds_how_far_the_pass_looks() -> None:
    """The cap that makes ADR-0008's permitted quadratic fit N2's budget.

    Thirty paragraphs on each side, none of which matches anything on the
    other -- so the whole sibling group is one unanchored gap, which is the
    only situation the window can bite in. The rewritten paragraph sits at
    rank 0 on the source side and rank 20 on the test side. At the default
    window it is a candidate; at a window of five it is never scored at all.
    That is a real recall cost, and it is stated here rather than left to be
    discovered -- though the move pass does pick the pair up afterwards, at
    its own much higher threshold, which is why the narrow leg drops it too.
    """
    original = "The Supplier shall provide the Services with care."
    edited = "The Supplier shall provide the Services with due care."

    def noise(side: str, index: int) -> Block:
        # Nothing shares a token with anything else, so the gap has no anchors
        # and no other fuzzy candidate to compete with.
        return block("paragraph", f"{side}zeta{index} {side}eta{index}.")

    source = tree(
        block("paragraph", original), *(noise("s", index) for index in range(29))
    )
    test = tree(
        *(noise("t", index) for index in range(20)),
        block("paragraph", edited),
        *(noise("t", index) for index in range(20, 29)),
    )
    narrow = AlignmentConfig(
        passes=("exact", "label", "structural", "fuzzy", "positional"),
        fuzzy_window=5,
        positional_min_similarity=0.9,
    )
    wide = AlignmentConfig(positional_min_similarity=0.9)
    assert "/paragraph[1]" in align(source, test, config=narrow).deleted
    widened = matched(align(source, test, config=wide), "/paragraph[1]")
    assert widened.matched_by == "fuzzy"
    assert widened.test_path == "/paragraph[21]"


def test_the_fuzzy_pass_can_be_dropped() -> None:
    source = tree(block("paragraph", "The Supplier shall provide the Services."))
    test = tree(block("paragraph", "The Supplier shall provide the Services well."))
    config = AlignmentConfig(passes=("exact", "structural", "positional"))
    alignment = align(source, test, config=config)
    assert alignment.pass_counts["fuzzy"] == 0
    assert matched(alignment, "/paragraph[1]").matched_by == "positional"


def test_an_exhausted_budget_stops_the_search_and_says_so() -> None:
    """Silence is the safe failure; silent silence is not (ADR-0032)."""
    source = tree(
        block("paragraph", "The Supplier shall provide the Services with care."),
        block("paragraph", "The Customer shall pay the Charges when they fall due."),
    )
    test = tree(
        block("paragraph", "The Supplier shall provide the Services with due care."),
        block("paragraph", "The Customer shall pay all Charges when they fall due."),
    )
    config = AlignmentConfig(max_comparisons=0, positional_min_similarity=0.9)
    alignment = align(source, test, config=config)
    assert alignment.budget_exhausted is True
    assert alignment.pass_counts["fuzzy"] == 0
    assert not align(source, test).budget_exhausted


# --- pass 5: positional ----------------------------------------------------


def test_leftovers_pair_positionally_and_record_what_they_score() -> None:
    """A positional pair decides on position but still reports the content."""
    source = tree(block("paragraph", "The Supplier shall provide the Services."))
    test = tree(block("paragraph", "The Supplier shall provide services."))
    config = AlignmentConfig(passes=("exact", "structural", "positional"))
    pair = matched(align(source, test, config=config), "/paragraph[1]")
    assert pair.matched_by == "positional"
    assert 0.35 <= pair.confidence < 1.0


def test_the_positional_floor_rejects_unrelated_leftovers() -> None:
    source = tree(block("paragraph", OLD_3_3))
    test = tree(block("paragraph", NEW_3_3))
    alignment = align(source, test)
    assert alignment.deleted == ("/paragraph[1]",)
    assert alignment.inserted == ("/paragraph[1]",)


def test_the_fill_in_reaches_the_children_of_the_pairs_it_makes() -> None:
    """A container paired by the fill-in still gets descended into.

    The fill-in runs last, so anything it pairs has no other chance to have
    its children compared. It repeats until it finds nothing for exactly this
    reason.
    """
    source = tree(
        block(
            "section",
            children=(
                block("heading", "Old title", label="9"),
                block("paragraph", "Alpha."),
            ),
        )
    )
    test = tree(
        block(
            "section",
            children=(
                block("heading", "A completely different title", label="10"),
                block("paragraph", "Alpha."),
            ),
        )
    )
    alignment = align(source, test)
    assert matched(alignment, "/section[1]/paragraph[1]").matched_by == "exact"


# --- pass 0 and #134: tables ----------------------------------------------


def test_cells_pair_strictly_by_sibling_index() -> None:
    """The reader pads ragged rows, so the index is the column (#134)."""
    source = tree(block("table", children=(row("Milestone", "Owner", "Date"),)))
    test = tree(block("table", children=(row("Milestone", "Owner", "Deadline"),)))
    alignment = align(source, test)
    third = matched(alignment, "/table[1]/row[1]/cell[3]")
    assert third.test_path == "/table[1]/row[1]/cell[3]"
    assert third.matched_by == "positional"


def test_a_row_never_fails_to_match_because_of_its_cell_count() -> None:
    """Ragged rows pair up to the shorter one; the surplus is reported alone."""
    source = tree(block("table", children=(row("Alpha", "Beta", "Gamma"),)))
    test = tree(block("table", children=(row("Alpha", "Beta"),)))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]/row[1]").test_path == "/table[1]/row[1]"
    assert matched(alignment, "/table[1]/row[1]/cell[1]").test_path == (
        "/table[1]/row[1]/cell[1]"
    )
    assert alignment.deleted == ("/table[1]/row[1]/cell[3]",)
    assert alignment.inserted == ()


def test_a_surplus_cell_on_the_test_side_is_an_insert() -> None:
    source = tree(block("table", children=(row("Alpha", "Beta"),)))
    test = tree(block("table", children=(row("Alpha", "Beta", "Gamma"),)))
    alignment = align(source, test)
    assert alignment.inserted == ("/table[1]/row[1]/cell[3]",)
    assert alignment.deleted == ()


def test_an_inserted_row_is_one_row_and_its_cells() -> None:
    """#134's stated bar; the change tree is what collapses the cells."""
    source = tree(
        block("table", children=(row("Alpha", "1"), row("Gamma", "3")))
    )
    test = tree(
        block(
            "table", children=(row("Alpha", "1"), row("Beta", "2"), row("Gamma", "3"))
        )
    )
    alignment = align(source, test)
    assert alignment.inserted == (
        "/table[1]/row[2]",
        "/table[1]/row[2]/cell[1]",
        "/table[1]/row[2]/cell[2]",
    )
    assert matched(alignment, "/table[1]/row[2]").test_path == "/table[1]/row[3]"


def test_rows_do_not_fuzzy_match_by_default() -> None:
    """ADR-0008 warns fuzzy thresholds misfire on near-identical rows (#134).

    A row has no text of its own, so what a fuzzy pass would compare is its
    cells' contents -- and rows of near-identical content are precisely the
    case the warning is about. ``table_fuzzy`` is the knob that turns it on,
    and it is off. Both halves are asserted: with the knob on the pass does
    fire, so the default is a decision rather than dead configuration.
    """
    source = tree(block("table", children=(row("Design sign-off", "1 March 2026"),)))
    test = tree(
        block(
            "table",
            children=(
                row("Training day", "20 March 2026"),
                row("Design sign-off", "10 March 2026"),
            ),
        )
    )

    def fuzzy_rows(config: AlignmentConfig) -> list[AlignedPair]:
        return [
            pair
            for pair in align(source, test, config=config).pairs
            if pair.matched_by == "fuzzy" and pair.source_path.endswith("]")
            and "/row[" in pair.source_path
            and "/cell[" not in pair.source_path
        ]

    assert fuzzy_rows(AlignmentConfig(table_fuzzy=True))
    assert not fuzzy_rows(DEFAULT_ALIGNMENT)


# --- renumbering (#133) ----------------------------------------------------


def test_a_matched_pair_with_a_different_label_is_a_renumber() -> None:
    """#133 reads this straight off the record, which is why exact runs first."""
    source = tree(block("list_item", "Alpha.", label="3.3"))
    test = tree(block("list_item", "Alpha.", label="3.4"))
    pair = matched(align(source, test), "/list_item[1]")
    assert pair.matched_by == "exact"
    assert pair.renumbered is True


def test_an_unchanged_label_is_not_a_renumber() -> None:
    source = tree(block("list_item", "Alpha.", label="3.3"))
    test = tree(block("list_item", "Alpha.", label="3.3"))
    assert matched(align(source, test), "/list_item[1]").renumbered is False


def test_an_absent_label_and_an_empty_one_are_the_same_thing() -> None:
    """A reader writing "" rather than None must not invent a renumber."""
    source = tree(block("paragraph", "Alpha.", label=None))
    test = tree(block("paragraph", "Alpha.", label=""))
    assert matched(align(source, test), "/paragraph[1]").renumbered is False


def test_a_renumber_survives_an_edit_to_the_same_clause() -> None:
    """Renumbering and editing are separable, because the label is not in text."""
    source = tree(block("list_item", "The term is thirty days.", label="7.1"))
    test = tree(block("list_item", "The term is sixty days.", label="7.2"))
    config = AlignmentConfig(passes=("exact", "structural", "positional"))
    pair = matched(align(source, test, config=config), "/list_item[1]")
    assert pair.renumbered is True
    assert pair.confidence < 1.0


# --- moves (#132) ----------------------------------------------------------
# The pass itself lives in tests/test_alignment_moves.py; these two pin its
# place in the order and what dropping it costs.


def test_a_block_that_changed_scope_is_matched_by_the_move_pass() -> None:
    """The one pass that can pair blocks whose parents do not correspond."""
    moved_text = (
        "Each party shall return or destroy all Confidential Information on "
        "termination of this agreement."
    )
    seven = block("heading", "Seven", label="7")
    nine = block("heading", "Nine", label="9")
    clause = block("paragraph", moved_text)
    source = tree(
        block("section", children=(seven, clause)),
        block("section", children=(nine,)),
    )
    test = tree(
        block("section", children=(seven,)),
        block("section", children=(nine, clause)),
    )
    alignment = align(source, test)
    assert alignment.pass_counts["move"] == 1
    pair = matched(alignment, "/section[1]/paragraph[1]")
    assert (pair.test_path, pair.matched_by, pair.moved) == (
        "/section[2]/paragraph[1]",
        "move",
        True,
    )
    assert alignment.deleted == ()
    assert alignment.inserted == ()


def test_dropping_the_move_pass_turns_a_move_back_into_two_changes() -> None:
    """What the pass costs when it is off: silence, not a wrong answer."""
    clause = block(
        "paragraph",
        "Each party shall return or destroy all Confidential Information on "
        "termination of this agreement.",
    )
    source = tree(
        block("section", children=(block("heading", "Seven", label="7"), clause)),
        block("section", children=(block("heading", "Nine", label="9"),)),
    )
    test = tree(
        block("section", children=(block("heading", "Seven", label="7"),)),
        block("section", children=(block("heading", "Nine", label="9"), clause)),
    )
    config = AlignmentConfig(
        passes=("exact", "label", "structural", "fuzzy", "positional")
    )
    alignment = align(source, test, config=config)
    assert alignment.pass_counts["move"] == 0
    assert not [pair for pair in alignment.pairs if pair.moved]
    assert alignment.deleted == ("/section[1]/paragraph[1]",)
    assert alignment.inserted == ("/section[2]/paragraph[1]",)


# --- AlignmentConfig -------------------------------------------------------


def test_the_defaults_are_the_ones_the_adr_tabulates() -> None:
    config = DEFAULT_ALIGNMENT
    assert config.passes == PASS_NAMES
    assert config.similarity == "auto"
    assert config.fuzzy_min_similarity == 0.60
    assert config.label_min_similarity == 0.35
    assert config.positional_min_similarity == 0.35
    assert config.move_min_similarity == 0.80
    assert config.move_tie_margin == 0.10
    assert config.move_min_tokens == 8
    assert config.move_kinds == ("paragraph", "list_item", "heading")
    assert config.fuzzy_window == 25
    assert config.table_fuzzy is False
    assert config.max_comparisons == 2_000_000


def test_an_unknown_pass_names_the_closed_set() -> None:
    with pytest.raises(ValueError, match="not an alignment pass"):
        AlignmentConfig(passes=("exact", "structural", "positional", "semantic"))


def test_a_reserved_name_is_not_a_pass() -> None:
    with pytest.raises(ValueError, match="reserved"):
        AlignmentConfig(passes=("exact", "structural", "positional", "root"))


@pytest.mark.parametrize("dropped", MANDATORY_PASSES)
def test_a_mandatory_pass_cannot_be_dropped(dropped: str) -> None:
    """They are the descent's anchors and its fill-in, not preferences."""
    keep = tuple(name for name in PASS_NAMES if name != dropped)
    with pytest.raises(ValueError, match="cannot be dropped"):
        AlignmentConfig(passes=keep)


def test_a_pass_listed_twice_is_a_mistake() -> None:
    with pytest.raises(ValueError, match="more than once"):
        AlignmentConfig(passes=("exact", "exact", "structural", "positional"))


def test_the_pass_order_is_fixed_whatever_order_is_written() -> None:
    """Inclusion only (ADR-0032): two orderings are load-bearing.

    Rather than honour an order that would make the record lie, the tuple is
    canonicalised, so ``to_dict()`` reports the order that actually ran.
    """
    written = AlignmentConfig(passes=("positional", "structural", "exact"))
    assert written.passes == ("exact", "structural", "positional")


@pytest.mark.parametrize(
    "field",
    [
        "fuzzy_min_similarity",
        "label_min_similarity",
        "positional_min_similarity",
        "move_min_similarity",
        "move_tie_margin",
    ],
)
def test_a_threshold_outside_zero_to_one_is_rejected(field: str) -> None:
    with pytest.raises(ValueError, match="between 0.0 and 1.0"):
        AlignmentConfig.from_dict({field: 1.5})


def test_a_negative_move_minimum_is_rejected() -> None:
    with pytest.raises(ValueError, match="move_min_tokens"):
        AlignmentConfig(move_min_tokens=-1)


def test_a_move_kind_outside_the_closed_set_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a block kind"):
        AlignmentConfig(move_kinds=("clause",))


def test_a_window_of_zero_is_rejected() -> None:
    with pytest.raises(ValueError, match="fuzzy_window"):
        AlignmentConfig(fuzzy_window=0)


def test_a_negative_budget_is_rejected() -> None:
    with pytest.raises(ValueError, match="max_comparisons"):
        AlignmentConfig(max_comparisons=-1)


def test_an_unknown_similarity_backend_is_rejected() -> None:
    with pytest.raises(ValueError, match="not a similarity backend"):
        AlignmentConfig(similarity="levenshtein")


def test_a_config_round_trips_through_its_dict() -> None:
    config = AlignmentConfig(fuzzy_min_similarity=0.7, table_fuzzy=True)
    assert AlignmentConfig.from_dict(config.to_dict()) == config


def test_the_config_dict_keeps_its_authored_key_order() -> None:
    assert list(DEFAULT_ALIGNMENT.to_dict()) == [
        "passes",
        "similarity",
        "fuzzy_min_similarity",
        "label_min_similarity",
        "positional_min_similarity",
        "move_min_similarity",
        "move_tie_margin",
        "move_min_tokens",
        "move_kinds",
        "fuzzy_window",
        "table_fuzzy",
        "max_comparisons",
    ]


def test_an_unknown_config_key_is_rejected() -> None:
    """The strictness `redlines.blocks` already applies everywhere else."""
    with pytest.raises(ValueError, match="alignment config"):
        AlignmentConfig.from_dict({"fuzzy_threshold": 0.6})


# --- Alignment and AlignedPair --------------------------------------------


def test_an_alignment_round_trips_through_its_dict() -> None:
    alignment = align(
        tree(block("paragraph", "Alpha."), block("paragraph", "Beta or gamma.")),
        tree(block("paragraph", "Alpha."), block("paragraph", "Beta and gamma.")),
    )
    assert Alignment.from_dict(alignment.to_dict()).to_dict() == alignment.to_dict()


def test_the_alignment_dict_keeps_its_authored_key_order() -> None:
    alignment = align(
        tree(block("paragraph", "Alpha.")), tree(block("paragraph", "Alpha."))
    )
    assert list(alignment.to_dict()) == [
        "pairs",
        "inserted",
        "deleted",
        "config",
        "backend",
        "pass_counts",
        "budget_exhausted",
    ]
    assert list(alignment.to_dict()["pairs"][0]) == [
        "source_path",
        "test_path",
        "matched_by",
        "confidence",
        "moved",
        "renumbered",
    ]


def test_confidence_is_rounded_once_at_serialisation() -> None:
    """Full precision for every comparison, four places on the wire (N1)."""
    source = tree(block("paragraph", "The Supplier shall provide the Services."))
    test = tree(block("paragraph", "The Supplier shall provide the Service."))
    alignment = align(source, test)
    pair = matched(alignment, "/paragraph[1]")
    assert pair.to_dict()["confidence"] == round(pair.confidence, 4)


def test_the_lookups_answer_both_ways_and_report_absence() -> None:
    source = tree(block("paragraph", "Alpha."), block("paragraph", "Gone."))
    test = tree(block("paragraph", "Alpha."), block("paragraph", "New and different."))
    alignment = align(source, test)
    assert alignment.test_for("/paragraph[1]") == "/paragraph[1]"
    assert alignment.source_for("/paragraph[1]") == "/paragraph[1]"
    assert alignment.test_for("/paragraph[2]") is None
    assert alignment.source_for("/paragraph[2]") is None


def test_a_pair_matched_by_something_that_is_not_a_pass_is_rejected() -> None:
    with pytest.raises(ValueError, match="not an alignment pass"):
        AlignedPair(
            source_path="/", test_path="/", matched_by="unmatched", confidence=1.0
        )


def test_a_pair_needs_both_addresses() -> None:
    with pytest.raises(ValueError, match="both addresses"):
        AlignedPair(source_path="/", test_path="", matched_by="root", confidence=1.0)


def test_pass_counts_reject_a_name_that_is_not_a_pass() -> None:
    with pytest.raises(ValueError, match="not an alignment pass"):
        Alignment(
            pairs=(),
            inserted=(),
            deleted=(),
            config=DEFAULT_ALIGNMENT,
            backend="difflib",
            pass_counts={"semantic": 1},
        )


def test_the_resolved_backend_is_reported_not_the_request() -> None:
    """"auto picked difflib" and "difflib was demanded" are different facts."""
    trees = (tree(block("paragraph", "Alpha.")), tree(block("paragraph", "Alpha.")))
    alignment = align(*trees, config=AlignmentConfig(similarity="difflib"))
    assert alignment.backend == "difflib"
    assert alignment.config.similarity == "difflib"
    assert align(*trees).backend in ("difflib", "rapidfuzz")


# --- the sample pair -------------------------------------------------------


def test_the_sample_pair_aligns_the_way_the_design_predicts(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Every pass accounted for, on both twins.

    The two documents differ by the eight changes ADR-0013 names. Six of them
    are visible in the alignment: the inserted clause, the deleted sub-clause,
    the two renumbers, the three edits, and (on the markdown twin) the
    inserted table row. The seventh -- the whitespace-only reflow -- is
    visible as an ``exact`` match, which is the point of it. The eighth is the
    move, which the move pass finds as one pair (#132).
    """
    source, test = sample
    alignment = align(source, test)
    counted = sum(alignment.pass_counts.values())
    assert counted == len(alignment.pairs)
    assert counted + len(alignment.deleted) == len(list(source.walk()))
    assert counted + len(alignment.inserted) == len(list(test.walk()))
    assert alignment.pass_counts["move"] == 1
    assert alignment.budget_exhausted is False


def test_the_sample_pairs_renumbering_falls_out_of_the_exact_pass(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Change 3: an inserted clause renumbers the two below it (#133).

    Both are matched by ``exact`` -- their text is byte-identical -- so the
    label difference is read straight off, which is the whole reason ``exact``
    runs before ``label``.
    """
    source, test = sample
    alignment = align(source, test)
    renumbered = [pair for pair in alignment.pairs if pair.renumbered]
    assert [
        (pair.source_path, pair.test_path, pair.matched_by) for pair in renumbered
    ] == [
        (
            "/section[1]/section[3]/list_item[3]",
            "/section[1]/section[3]/list_item[4]",
            "exact",
        ),
        (
            "/section[1]/section[3]/list_item[4]",
            "/section[1]/section[3]/list_item[5]",
            "exact",
        ),
    ]
    labels = [
        (
            source.block_at(pair.source_path).label,
            test.block_at(pair.test_path).label,
        )
        for pair in renumbered
    ]
    assert labels == [("3.3", "3.4"), ("3.4", "3.5")]


def test_the_sample_pairs_edited_clauses_match_on_their_labels(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Changes 1, 4 and 8, with the scores the design predicts.

    The definitions entry, the cross-reference that followed the renumbering,
    and the reworded schedule item. Each keeps its label and loses some words,
    so each is a ``label`` match well above the 0.35 floor.
    """
    source, test = sample
    alignment = align(source, test)
    edited = {
        pair.source_path: round(pair.confidence, 3)
        for pair in alignment.pairs
        if pair.matched_by == "label"
    }
    assert edited == {
        "/section[1]/section[2]/list_item[4]": 0.792,
        "/section[1]/section[9]/list_item[2]": 0.963,
        "/section[4]/list_item[3]": 0.850,
    }


def test_the_sample_pairs_inserted_clause_and_deleted_sub_clause(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Changes 2 and 5: one insert, one delete, and the move that is neither."""
    source, test = sample
    alignment = align(source, test)
    assert "/section[1]/section[3]/list_item[3]" in alignment.inserted
    assert "/section[1]/section[5]/list_item[4]/list_item[3]" in alignment.deleted
    # Change 2, the moved clause: one pair, not a delete and an insert.
    assert "/section[1]/section[7]/list_item[5]" not in alignment.deleted
    assert "/section[1]/section[9]/list_item[6]" not in alignment.inserted


def test_the_sample_pairs_markdown_twin_reports_one_inserted_table_row() -> None:
    """Change 6 on the markdown side: #134's stated bar.

    Source row 5 pairs with test row 6 -- the "Go-live sign-off" row slid down
    a place and its text is unchanged -- and the new "Training day" row is one
    row insert carrying three cell inserts.
    """
    source = load_sample("source.markdown.json")
    test = load_sample("test.markdown.json")
    alignment = align(source, test)
    table = "/section[3]/list_item[3]/table[1]"
    assert matched(alignment, f"{table}/row[5]").test_path == f"{table}/row[6]"
    assert [path for path in alignment.inserted if path.startswith(table)] == [
        f"{table}/row[5]",
        f"{table}/row[5]/cell[1]",
        f"{table}/row[5]/cell[2]",
        f"{table}/row[5]/cell[3]",
    ]


def test_the_sample_pairs_plain_text_twin_reports_the_added_paragraph() -> None:
    """The one documented place the twins diverge (CHANGES.md, change 6)."""
    source = load_sample("source.contract.json")
    test = load_sample("test.contract.json")
    alignment = align(source, test)
    assert "/section[3]/list_item[3]/paragraph[5]" in alignment.inserted


def test_the_sample_pairs_pass_counts_are_pinned() -> None:
    """The numbers behind ADR-0032's review gate, on both twins.

    Pinned rather than described: if a pass starts contributing a different
    share of the matches, that is a change in behaviour whether or not the
    output still looks right, and ADR-0008 says the counts are the evidence.
    """
    markdown = align(
        load_sample("source.markdown.json"), load_sample("test.markdown.json")
    )
    assert markdown.pass_counts == {
        "root": 1,
        "exact": 96,
        "label": 3,
        "structural": 1,
        "fuzzy": 1,
        "move": 1,
        "positional": 15,
    }
    contract = align(
        load_sample("source.contract.json"), load_sample("test.contract.json")
    )
    assert contract.pass_counts == {
        "root": 1,
        "exact": 95,
        "label": 3,
        "structural": 0,
        "fuzzy": 1,
        "move": 1,
        "positional": 0,
    }


# --- determinism and provenance -------------------------------------------


def test_aligning_the_same_pair_twice_gives_the_same_record(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """#135, in the same process. The hash-seed matrix is #135's own module."""
    source, test = sample
    first = align(source, test).to_dict()
    second = align(source, test).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_reader_provenance_does_not_influence_alignment(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """ADR-0030's prohibition, as a test rather than a promise.

    ``matched_by`` and ``confidence`` on a `Block` are the *reader's* answer
    to "how do you know?", and a reader's guess must not steer alignment. Both
    are rewritten on every block of both trees -- to a value no reader would
    produce, at a confidence that would dominate any weighting -- and the
    alignment must come out byte-identical.
    """
    source, test = sample
    expected = align(source, test).to_dict()

    def rewrite(node: Block) -> Block:
        return dataclasses.replace(
            node,
            matched_by="nonsense:invented",
            confidence=1.0,
            children=tuple(rewrite(child) for child in node.children),
        )

    scrambled = align(
        BlockTree(root=rewrite(source.root), dropped=source.dropped),
        BlockTree(root=rewrite(test.root), dropped=test.dropped),
    ).to_dict()
    assert scrambled == expected


def test_a_tie_is_broken_by_the_earliest_position() -> None:
    """Two candidates that score identically resolve the same way every time."""
    target = "The Supplier shall provide the Services with reasonable care."
    source = tree(
        block("paragraph", "The Supplier shall provide the Services with care."),
        block("paragraph", "The Supplier shall provide the Services with care."),
    )
    test = tree(block("paragraph", target))
    alignment = align(source, test)
    assert matched(alignment, "/paragraph[1]").matched_by == "fuzzy"
    assert alignment.deleted == ("/paragraph[2]",)


def test_a_role_orders_equal_candidates_and_never_creates_a_match() -> None:
    """R2's bounded use of ``role``: a tie-break, never evidence.

    The two source candidates are identical text, so they score identically
    against the test block; the one whose role matches wins. Role cannot make
    a match on its own -- the pairing here would happen either way, and only
    which of the two is chosen changes.
    """
    same = "The Supplier shall provide the Services with care."
    edited = "The Supplier shall provide the Services with due care."
    source = tree(
        block("paragraph", same, role="recital"),
        block("paragraph", same, role="clause"),
    )
    test = tree(block("paragraph", edited, role="clause"))
    alignment = align(source, test)
    assert matched(alignment, "/paragraph[2]").test_path == "/paragraph[1]"
    assert alignment.deleted == ("/paragraph[1]",)


# --- N2: the budget --------------------------------------------------------


def flat_pair(count: int) -> tuple[BlockTree, BlockTree]:
    """Two flat documents of ``count`` paragraphs, none of which matches.

    Every paragraph is reworded, and none carries a label or a heading, so the
    sibling group has no anchors at all and is one gap end to end -- the only
    shape in which the window cap does any work.
    """

    def clause(index: int, edited: bool) -> Block:
        text = (
            f"Clause {index}: the Supplier shall provide the Services "
            f"described in Schedule {index} with reasonable skill and care."
        )
        return block(
            "paragraph", text.replace("reasonable", "all due") if edited else text
        )

    return (
        tree(*(clause(index, False) for index in range(count))),
        tree(*(clause(index, True) for index in range(count))),
    )


def synthetic_pair(sections: int, per_section: int) -> tuple[BlockTree, BlockTree]:
    """Two documents of ``sections * (per_section + 2) + 1`` blocks.

    Every twentieth clause is reworded, so the fuzzy pass has real work rather
    than a document that falls entirely to ``exact``.
    """
    source_sections: list[Block] = []
    test_sections: list[Block] = []
    counter = 0
    for section in range(sections):
        source_items: list[Block] = [
            block("heading", f"Part {section}", label=str(section + 1))
        ]
        test_items: list[Block] = [
            block("heading", f"Part {section}", label=str(section + 1))
        ]
        for item in range(per_section):
            counter += 1
            label = f"{section + 1}.{item + 1}"
            text = (
                f"Clause {counter}: the Supplier shall provide the Services "
                f"described in Schedule {item} with reasonable skill and care."
            )
            source_items.append(block("list_item", text, label=label))
            test_items.append(
                block(
                    "list_item",
                    text if counter % 20 else text.replace("reasonable", "all due"),
                    label=label,
                )
            )
        source_sections.append(block("section", children=tuple(source_items)))
        test_sections.append(block("section", children=tuple(test_items)))
    return tree(*source_sections), tree(*test_sections)


@pytest.mark.slow
def test_two_thousand_blocks_of_an_ordinary_document_stay_inside_it() -> None:
    """N2's budget on a document shaped like a real one.

    Headings and labels anchor densely, so the gaps between anchors are a
    handful of blocks each and the fuzzy pass barely runs. This is the case
    ADR-0032 measures at 24 ms, and it is the one nearly every user has.
    """
    source, test = synthetic_pair(sections=200, per_section=8)
    assert len(list(source.walk())) >= 2000
    started = time.perf_counter()
    alignment = align(source, test)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"aligning 2,000 anchored blocks took {elapsed:.2f}s"
    assert alignment.budget_exhausted is False
    assert alignment.deleted == ()
    assert alignment.inserted == ()


@pytest.mark.slow
def test_two_thousand_unanchored_blocks_align_inside_the_budget() -> None:
    """N2's budget on the shape that actually costs something.

    One flat sibling group of 2,000 paragraphs, every one of them reworded, so
    nothing anchors, the whole group is a single gap and the fuzzy pass runs
    across the full window on every block. This is what the window cap exists
    for: unbounded, the same comparison is measured at about 39 seconds.

    Kept in the default suite on purpose -- a performance promise nobody runs
    is a performance promise nobody keeps -- and the margin is wide enough
    (tenths of a second against five) that a loaded CI runner cannot make it
    flaky.
    """
    source, test = flat_pair(2000)
    started = time.perf_counter()
    alignment = align(source, test)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"aligning 2,000 unanchored blocks took {elapsed:.2f}s"
    assert alignment.pass_counts["fuzzy"] == 2000
    assert alignment.budget_exhausted is False


def test_the_synthetic_pair_matches_every_block() -> None:
    """A smaller run of the same generator, so the timing test is not alone."""
    source, test = synthetic_pair(sections=5, per_section=4)
    alignment = align(source, test)
    assert alignment.deleted == ()
    assert alignment.inserted == ()
    assert alignment.pass_counts["label"] == 1


def test_config_is_carried_into_the_record() -> None:
    """#135: the configuration in force is part of the output."""
    config = AlignmentConfig(similarity="difflib", fuzzy_min_similarity=0.75)
    alignment = align(
        tree(block("paragraph", "Alpha.")),
        tree(block("paragraph", "Alpha.")),
        config=config,
    )
    assert alignment.config == config
    on_the_wire: dict[str, Any] = alignment.to_dict()["config"]
    assert on_the_wire["fuzzy_min_similarity"] == 0.75
