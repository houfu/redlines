"""The eight promises of the sample pair, read off its change tree (#144).

`tests/corpus/sample_pair/CHANGES.md` says the amended agreement carries
exactly eight changes, one of each thing the engine is meant to detect, and
nothing else. `tests/test_sample_pair.py` checks that both versions *parse*
into the trees M1 froze. This module checks what M2 makes of the difference
between them: one named test per row of that table, so a failure says which
promise broke rather than printing a hundred kilobytes of diff.

Each test composes the comparison itself, through the public `compare`, rather
than loading a golden. The goldens (`expected/change_tree.*.json`) arrive with
#144's second phase and pin the *whole* tree; these eight pin the parts the
pair exists to demonstrate, and they were written before `redlines.comparison`
existed, as the specification it was built against.

**What is asserted, and what deliberately is not.** Kind, both addresses, both
labels, `span_types` and the inline ops are asserted: they are what CHANGES.md
promises. `matched_by` is asserted only twice -- on the move, and on the
renumber run, where the pass *is* the point (the renumbers must come from
`exact`, which is what proves the pass order of ADR-0032 is doing its job).
Everywhere else the pass a block lands on is an emergent property of the
alignment, and a named test asserting a guessed pass name would be a false
failure.

Both twins are checked wherever the twins agree, which is everywhere except
change 6 -- the plain-text document has no table to put a row in, and that
divergence is a stated property of the pair.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redlines.changes import Change
    from redlines.comparison import Comparison

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair"

# (profile name, source file, test file, reader format), mirroring
# tests/test_sample_pair.py's PAIRINGS. The two twins say the same thing in
# two syntaxes, so every promise below is checked twice unless the pair
# documents a divergence.
PAIRINGS: tuple[tuple[str, str, str, str], ...] = (
    ("markdown", "source.md", "test.md", "markdown"),
    ("contract", "source.txt", "test.txt", "text"),
)
PROFILES: tuple[str, ...] = tuple(name for name, _, _, _ in PAIRINGS)

# The addresses CHANGES.md names, spelled as in tests/test_sample_pair.py so a
# failure here points at a row of that table.
CONFIDENTIAL_INFORMATION = "/section[1]/section[2]/list_item[4]"
MOVED_CLAUSE_SOURCE = "/section[1]/section[7]/list_item[5]"
MOVED_CLAUSE_TEST = "/section[1]/section[9]/list_item[6]"
MOVED_BODY_SOURCE = f"{MOVED_CLAUSE_SOURCE}/paragraph[1]"
MOVED_BODY_TEST = f"{MOVED_CLAUSE_TEST}/paragraph[1]"
RENUMBERED_SECTION = "/section[1]/section[3]"
INSERTED_CLAUSE = f"{RENUMBERED_SECTION}/list_item[3]"
CROSS_REFERENCE_CLAUSE = "/section[1]/section[9]/list_item[2]"
DELETED_SUB_CLAUSE = "/section[1]/section[5]/list_item[4]/list_item[3]"
INSERTED_TABLE_ROW = "/section[3]/list_item[3]/table[1]/row[5]"
INSERTED_SCHEDULE_PARAGRAPH = "/section[3]/list_item[3]/paragraph[5]"
NOTICES_CLAUSE = "/section[1]/section[11]/list_item[5]"
REPETITIVE_SCHEDULE_ITEM = "/section[4]/list_item[3]"

_CACHE: dict[str, Comparison] = {}


def comparison_for(profile_name: str) -> Comparison:
    """Compare the sample pair under one profile, through the public entry point.

    The import is inside the function on purpose: these tests were written
    before `redlines.comparison` existed, and a module-level import would have
    turned eight expected failures into one collection error.
    """
    if profile_name not in _CACHE:
        from redlines import compare

        for name, source_name, test_name, format_name in PAIRINGS:
            if name != profile_name:
                continue
            _CACHE[profile_name] = compare(
                (CASE_DIR / source_name).read_text(encoding="utf-8"),
                (CASE_DIR / test_name).read_text(encoding="utf-8"),
                format=format_name,
                profile=profile_name,
            )
            break
        else:  # pragma: no cover - a typo in a parametrisation
            raise AssertionError(f"{profile_name!r} is not one of the sample pair's")
    return _CACHE[profile_name]


def changes_at(
    comparison: Comparison,
    *,
    source: str | None = None,
    test: str | None = None,
) -> list[Change]:
    """Every change node touching these addresses, in document order."""
    return [
        change
        for change in comparison.changes
        if (source is None or change.source_address == source)
        and (test is None or change.test_address == test)
    ]


def only_change_at(
    comparison: Comparison,
    *,
    source: str | None = None,
    test: str | None = None,
) -> Change:
    """The single change node at these addresses, or an assertion failure."""
    found = changes_at(comparison, source=source, test=test)
    assert len(found) == 1, (
        f"expected exactly one change at source={source!r} test={test!r}, "
        f"got {[(c.kind, c.source_address, c.test_address) for c in found]}"
    )
    return found[0]


def inline_tuples(change: Change) -> list[tuple[Any, ...]]:
    """A change's inline ops as plain tuples, for a readable failure."""
    return [
        (
            str(op.kind),
            op.source_start,
            op.source_end,
            op.test_start,
            op.test_end,
            op.source_text,
            op.test_text,
        )
        for op in change.inline
    ]


# --- change 1: a definition whose text changed -----------------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_widened_definition_is_one_modify_with_one_inline_insert(
    profile_name: str,
) -> None:
    """CHANGES.md 1. Clause 2.4 keeps its role and gains a clause of text.

    The inserted run is reported as one inline `insert` at a character offset
    into the block's own text, and it touches no span: the `defined_term` span
    sits at the head of the definition, far from the edit, so `span_types` is
    empty and a summary can say "a definition was widened" without claiming
    the defined term changed.
    """
    comparison = comparison_for(profile_name)
    change = only_change_at(
        comparison, source=CONFIDENTIAL_INFORMATION, test=CONFIDENTIAL_INFORMATION
    )
    assert str(change.kind) == "modify"
    assert (change.source_label, change.test_label) == ("2.4", "2.4")
    assert change.role == "definition"
    assert change.span_types == ()
    assert inline_tuples(change) == [
        (
            "insert",
            133,
            133,
            133,
            204,
            "",
            "confidential, or that the receiving party ought reasonably to "
            "treat as ",
        )
    ]


# --- change 2: a clause moved, and edited on the way -----------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_moved_clause_is_one_move_and_its_body_a_separate_modify(
    profile_name: str,
) -> None:
    """CHANGES.md 2, and ADR-0009's demo case: the move and the edit separate.

    Clause 7.5 becomes 9.6 with byte-identical text, so it is one `move` node
    carrying both addresses and both labels and no inline ops at all. The edit
    rides in the unlabelled body paragraph, which is its own `modify` -- and
    that node carries *both* addresses too, which is why every node does.

    `matched_by` is asserted here because the pass is the point: nothing but
    the cross-scope move pass can find this pair.
    """
    comparison = comparison_for(profile_name)

    move = only_change_at(
        comparison, source=MOVED_CLAUSE_SOURCE, test=MOVED_CLAUSE_TEST
    )
    assert str(move.kind) == "move"
    assert (move.source_label, move.test_label) == ("7.5", "9.6")
    assert move.role == "clause"
    assert move.matched_by == "move"
    assert move.span_types == ()
    assert move.inline == ()
    assert move.source_text == move.test_text

    body = only_change_at(comparison, source=MOVED_BODY_SOURCE, test=MOVED_BODY_TEST)
    assert str(body.kind) == "modify"
    assert (body.source_label, body.test_label) == (None, None)
    assert inline_tuples(body) == [("replace", 44, 50, 44, 49, "three ", "five ")]


# --- change 3: an inserted clause and the renumbering it causes ------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_inserted_clause_renumbers_the_two_clauses_below_it(
    profile_name: str,
) -> None:
    """CHANGES.md 3. One insert, then a run of renumbers -- not three inserts.

    `matched_by` is asserted on the renumbers because the pass order is the
    point: the two surviving clauses are byte-identical, so `exact` must find
    them *before* `label` gets a chance to match old 3.3 to the newly inserted
    3.3. A renumber found by any other pass would mean the guard in ADR-0032
    had stopped working.
    """
    comparison = comparison_for(profile_name)

    inserted = only_change_at(comparison, test=INSERTED_CLAUSE)
    assert str(inserted.kind) == "insert"
    assert inserted.source_address is None
    assert (inserted.source_label, inserted.test_label) == (None, "3.3")
    assert inserted.role == "clause"
    assert inserted.matched_by == "unmatched"
    assert inserted.confidence == 0.0
    assert inserted.span_types == ("party",)
    assert inserted.inline == ()

    renumbered = [
        change
        for change in comparison.changes
        if str(change.kind) == "renumber"
        and change.test_address is not None
        and change.test_address.startswith(RENUMBERED_SECTION)
    ]
    assert [
        (c.source_address, c.test_address, c.source_label, c.test_label, c.matched_by)
        for c in renumbered
    ] == [
        (
            f"{RENUMBERED_SECTION}/list_item[3]",
            f"{RENUMBERED_SECTION}/list_item[4]",
            "3.3",
            "3.4",
            "exact",
        ),
        (
            f"{RENUMBERED_SECTION}/list_item[4]",
            f"{RENUMBERED_SECTION}/list_item[5]",
            "3.4",
            "3.5",
            "exact",
        ),
    ]
    assert all(change.inline == () for change in renumbered)


# --- change 4: a cross-reference following the renumbering -----------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_cross_reference_edit_touches_only_the_cross_reference_span(
    profile_name: str,
) -> None:
    """CHANGES.md 4, and the reason `span_types` means *touched*.

    Clause 9.2 carries two `party` spans and one `cross_reference` span, and
    the single inline op overlaps only the last of them. Reporting every span
    on the block would bury the one signal PRD § 3a promises here.
    """
    comparison = comparison_for(profile_name)
    change = only_change_at(
        comparison, source=CROSS_REFERENCE_CLAUSE, test=CROSS_REFERENCE_CLAUSE
    )
    assert str(change.kind) == "modify"
    assert (change.source_label, change.test_label) == ("9.2", "9.2")
    assert change.span_types == ("cross_reference",)
    assert inline_tuples(change) == [("replace", 164, 168, 164, 168, "3.3.", "3.4.")]


# --- change 5: a deleted sub-clause ----------------------------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_deleted_sub_clause_is_one_delete_that_keeps_its_label(
    profile_name: str,
) -> None:
    """CHANGES.md 5. Sub-clause (c) goes; (a) and (b) are not re-reported."""
    comparison = comparison_for(profile_name)
    change = only_change_at(comparison, source=DELETED_SUB_CLAUSE)
    assert str(change.kind) == "delete"
    assert change.test_address is None
    assert (change.source_label, change.test_label) == ("(c)", None)
    assert change.role == "sub_clause"
    assert change.matched_by == "unmatched"
    assert change.span_types == ("party",)
    assert change.test_text == ""
    assert change.source_text.startswith("The Client pays the undisputed part")

    siblings = [
        change
        for change in comparison.changes
        if (change.source_address or "").startswith("/section[1]/section[5]/list_item[4]")
        or (change.test_address or "").startswith("/section[1]/section[5]/list_item[4]")
    ]
    assert len(siblings) == 1


# --- change 6: an inserted table row (the one place the twins diverge) -----


def test_the_inserted_table_row_is_one_row_level_insert() -> None:
    """CHANGES.md 6, and #134's stated bar.

    In markdown the new row is one `insert` at the row, with its three cells
    suppressed by the topmost-wins rule; in the plain-text twin the same
    change is an inserted paragraph, because that document has no table. The
    "Go-live sign-off" row slides from `row[5]` to `row[6]` and is reported as
    nothing at all: an address shift alone is never a change.
    """
    markdown = comparison_for("markdown")
    row = only_change_at(markdown, test=INSERTED_TABLE_ROW)
    assert str(row.kind) == "insert"
    assert str(row.block_kind) == "row"
    assert row.role == "schedule"
    assert row.span_types == ()
    assert changes_at(markdown, test=f"{INSERTED_TABLE_ROW}/cell[1]") == []
    assert [
        change
        for change in markdown.changes
        if (change.test_address or "").startswith(f"{INSERTED_TABLE_ROW}/")
    ] == []
    assert [
        change
        for change in markdown.changes
        if (change.test_address or "").startswith("/section[3]/list_item[3]/table[1]/row[6]")
    ] == []

    contract = comparison_for("contract")
    paragraph = only_change_at(contract, test=INSERTED_SCHEDULE_PARAGRAPH)
    assert str(paragraph.kind) == "insert"
    assert str(paragraph.block_kind) == "paragraph"
    assert paragraph.span_types == ("party",)


# --- change 7: a whitespace-only change that is no change ------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_whitespace_only_change_produces_no_node(profile_name: str) -> None:
    """CHANGES.md 7. The pair's proof that the engine compares documents.

    Clause 11.5 is hard-wrapped at a different point in each version. Both
    readers re-join the wrap, so the two trees carry identical text and the
    change has disappeared before alignment ever sees it.
    """
    comparison = comparison_for(profile_name)
    assert changes_at(comparison, source=NOTICES_CLAUSE) == []
    assert changes_at(comparison, test=NOTICES_CLAUSE) == []


# --- change 8: an edit inside a repetitive schedule ------------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_edit_inside_the_repetitive_schedule_is_found(profile_name: str) -> None:
    """CHANGES.md 8, and ADR-0010's pathology.

    Eight near-identical service-level clauses, one of them edited. The flat
    engine loses this edit among the repetitions; here the block is aligned on
    its own label and the leaf differ runs over 127 characters. Three replaces
    rather than two, because the cleanup pass only merges across
    punctuation-only equal runs and "Business " sits between "two" and "Days."
    """
    comparison = comparison_for(profile_name)
    change = only_change_at(
        comparison, source=REPETITIVE_SCHEDULE_ITEM, test=REPETITIVE_SCHEDULE_ITEM
    )
    assert str(change.kind) == "modify"
    assert (change.source_label, change.test_label) == ("3", "3")
    assert change.role == "schedule"
    assert inline_tuples(change) == [
        ("replace", 60, 65, 60, 64, "four ", "two "),
        ("replace", 109, 113, 108, 112, "two ", "one "),
        ("replace", 122, 127, 121, 125, "Days.", "Day."),
    ]
    assert [
        c.source_address
        for c in comparison.changes
        if (c.source_address or "").startswith("/section[4]/")
    ] == [REPETITIVE_SCHEDULE_ITEM]
