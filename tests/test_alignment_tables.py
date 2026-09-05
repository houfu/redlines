"""Tests for table alignment (#134, ADR-0032).

Once a `table` pair exists (the ``structural`` pass), the descent handles the
rest of it with the ordinary rules -- rows match by the same exact-then-
positional order as anything else, and cells are a total rule of their own:
sibling index, always, no column operations. What makes tables worth their
own file rather than a corner of `tests/test_alignment.py` is the one place
they behave *differently* from prose: rows of near-identical content are
exactly the case ADR-0008 warns a similarity threshold misfires on, so
``table_fuzzy`` defaults to ``False`` and these tests pin what that default
actually buys -- rows that would score above the fuzzy floor, and are *not*
each other, staying unmatched rather than being guessed at.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redlines.alignment import AlignedPair, Alignment, AlignmentConfig, align
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.similarity import RAPIDFUZZ_AVAILABLE, resolve_backend, similarity, tokens

EXPECTED_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"


# --- helpers ---------------------------------------------------------------


def block(
    kind: str, text: str = "", *, label: str | None = None, children: tuple[Block, ...] = ()
) -> Block:
    return Block(kind=BlockKind(kind), text=text, label=label, children=children)


def tree(*children: Block) -> BlockTree:
    return BlockTree.build(block("document", children=children))


def row(*cells: str) -> Block:
    return block("row", children=tuple(block("cell", text=cell) for cell in cells))


def table(*rows: Block) -> BlockTree:
    return tree(block("table", children=rows))


def pairs_by_source(alignment: Alignment) -> dict[str, AlignedPair]:
    return {pair.source_path: pair for pair in alignment.pairs}


def matched(alignment: Alignment, source_path: str) -> AlignedPair:
    found = pairs_by_source(alignment).get(source_path)
    assert found is not None, (
        f"{source_path} was not matched; deleted={alignment.deleted}"
    )
    return found


def load_sample(name: str) -> BlockTree:
    return BlockTree.from_dict(json.loads((EXPECTED_DIR / name).read_text()))


# --- rows: exact then positional, fuzzy off by default ----------------------


def test_table_fuzzy_defaults_to_false() -> None:
    assert AlignmentConfig().table_fuzzy is False


def test_rows_match_exactly_when_their_cell_texts_agree() -> None:
    source = table(row("Milestone", "Owner", "Date"), row("Sign-off", "Supplier", "1 April"))
    test = table(row("Milestone", "Owner", "Date"), row("Sign-off", "Supplier", "1 April"))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]/row[1]").matched_by == "exact"
    assert matched(alignment, "/table[1]/row[2]").matched_by == "exact"


def test_a_reordered_row_matches_positionally_once_the_others_anchor() -> None:
    """Not fuzzy: two identical row texts fall through to position, not score.

    The row itself carries no text (a `row`'s key is its cells joined), so
    when two rows are byte-identical the ``exact`` pass takes the first one in
    document order on each side and the surplus falls through to
    ``positional`` -- the same rule an ordinary sibling group gets, with
    nothing table-specific about it.
    """
    header = row("Milestone", "Date")
    source = table(header, row("A", "1 Jan"))
    test = table(row("A", "1 Jan"), header)
    alignment = align(source, test)
    first = matched(alignment, "/table[1]/row[1]")
    second = matched(alignment, "/table[1]/row[2]")
    assert {first.matched_by, second.matched_by} <= {"exact", "positional"}
    assert {first.test_path, second.test_path} == {
        "/table[1]/row[1]",
        "/table[1]/row[2]",
    }


def test_the_sample_pairs_inserted_row_is_one_row_insert_with_three_cells() -> None:
    """#134's stated bar, verified on the real sample pair (change 6).

    Source row 5 ("Go-live sign-off") is unchanged and slides to test row 6;
    the new "Training day" row at test row 5 is one row-level insert carrying
    three cell inserts underneath it -- never thirteen loose cell moves,
    which is the failure the move pass's own regression test in
    ``tests/test_alignment_moves.py`` guards from the other direction.
    """
    source = load_sample("source.markdown.json")
    test = load_sample("test.markdown.json")
    alignment = align(source, test)
    prefix = "/section[3]/list_item[3]/table[1]"
    assert matched(alignment, f"{prefix}/row[5]").test_path == f"{prefix}/row[6]"
    assert matched(alignment, f"{prefix}/row[5]").matched_by == "exact"
    inserted = [path for path in alignment.inserted if path.startswith(prefix)]
    assert inserted == [
        f"{prefix}/row[5]",
        f"{prefix}/row[5]/cell[1]",
        f"{prefix}/row[5]/cell[2]",
        f"{prefix}/row[5]/cell[3]",
    ]
    assert alignment.pass_counts["move"] == 1  # the clause move; no table moves


# --- cells: strictly by sibling index ---------------------------------------


def test_cells_pair_by_sibling_index_even_when_their_text_disagrees() -> None:
    source = table(row("Milestone", "Owner", "Date"))
    test = table(row("Milestone", "Owner", "Deadline"))
    alignment = align(source, test)
    third = matched(alignment, "/table[1]/row[1]/cell[3]")
    assert third.test_path == "/table[1]/row[1]/cell[3]"
    assert third.matched_by == "positional"


def test_a_ragged_row_pairs_cells_up_to_the_shorter_side_only() -> None:
    """A row never fails to match on cell count alone (the decisions record)."""
    source = table(row("Alpha", "Beta", "Gamma"))
    test = table(row("Alpha", "Beta"))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]/row[1]").test_path == "/table[1]/row[1]"
    assert matched(alignment, "/table[1]/row[1]/cell[1]").test_path == (
        "/table[1]/row[1]/cell[1]"
    )
    assert matched(alignment, "/table[1]/row[1]/cell[2]").test_path == (
        "/table[1]/row[1]/cell[2]"
    )
    assert alignment.deleted == ("/table[1]/row[1]/cell[3]",)
    assert alignment.inserted == ()


def test_a_ragged_row_with_a_surplus_test_cell_reports_a_cell_insert() -> None:
    source = table(row("Alpha", "Beta"))
    test = table(row("Alpha", "Beta", "Gamma"))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]/row[1]").test_path == "/table[1]/row[1]"
    assert alignment.inserted == ("/table[1]/row[1]/cell[3]",)
    assert alignment.deleted == ()


def test_ragged_rows_on_both_sides_still_pair_the_row_and_the_common_cells() -> None:
    """Both a shrunken and a grown row in one table: the row still matches."""
    source = table(row("Alpha", "Beta", "Gamma"), row("One", "Two"))
    test = table(row("Alpha", "Beta"), row("One", "Two", "Three"))
    alignment = align(source, test)
    assert matched(alignment, "/table[1]/row[1]").test_path == "/table[1]/row[1]"
    assert matched(alignment, "/table[1]/row[2]").test_path == "/table[1]/row[2]"
    assert "/table[1]/row[1]/cell[3]" in alignment.deleted
    assert "/table[1]/row[2]/cell[3]" in alignment.inserted


# --- near-identical rows must not fuzzy-match, off by default --------------


def test_near_identical_rows_are_never_matched_by_the_fuzzy_pass_by_default() -> None:
    """The case ADR-0008 warns about, made concrete.

    "Training day, 20 March 2026" and "Design sign-off, 10 March 2026" share a
    date-shaped cell and are similar enough to clear an ordinary fuzzy floor
    if compared as free text. With ``table_fuzzy`` off the fuzzy pass never
    runs inside the table at all, so whichever row ends up paired -- the
    ``positional`` fill-in still applies inside a table, exactly as it does
    everywhere else -- it is never because a similarity score picked it out
    from among near-identical candidates.
    """
    source = table(row("Design sign-off", "1 March 2026"))
    test = table(
        row("Training day", "20 March 2026"),
        row("Design sign-off", "10 March 2026"),
    )
    alignment = align(source, test)
    row_pairs = [
        pair
        for pair in alignment.pairs
        if "/row[" in pair.source_path and "/cell[" not in pair.source_path
    ]
    assert all(pair.matched_by != "fuzzy" for pair in row_pairs)


def test_turning_table_fuzzy_on_finds_the_semantically_right_row_instead() -> None:
    """What the default actually costs, and what the knob buys back.

    With ``table_fuzzy`` off, the positional fill-in pairs source row 1 with
    whichever test row comes first in the gap -- "Training day", the *wrong*
    row by content, at a low score. With it on, the fuzzy pass finds
    "Design sign-off" instead, on its merits, at a much higher score. The
    contrast is the whole argument for defaulting it off: the wrong answer
    the default risks is a low-confidence positional guess, never a
    confident-looking fuzzy one.
    """
    source = table(row("Design sign-off", "1 March 2026"))
    test = table(
        row("Training day", "20 March 2026"),
        row("Design sign-off", "10 March 2026"),
    )
    off = matched(align(source, test), "/table[1]/row[1]")
    assert off.matched_by == "positional"
    assert off.test_path == "/table[1]/row[1]"

    on_config = AlignmentConfig(table_fuzzy=True)
    on = matched(align(source, test, config=on_config), "/table[1]/row[1]")
    assert on.matched_by == "fuzzy"
    assert on.test_path == "/table[1]/row[2]"
    assert on.confidence > off.confidence


def test_rows_that_are_merely_similar_never_match_under_any_backend() -> None:
    """The near-identical-rows guarantee holds under both similarity backends."""
    source_row = "Design sign-off, 1 March 2026, Supplier"
    test_row = "Training day, 20 March 2026, Customer"
    backend = resolve_backend("auto")
    score = similarity(tokens(source_row), tokens(test_row), backend=backend)
    # These two rows are not each other -- a low score is the point of the
    # fixture -- so the default table behaviour of never comparing them at
    # all cannot be masked by a coincidentally high similarity.
    assert score < AlignmentConfig().fuzzy_min_similarity


@pytest.mark.parametrize(
    "backend",
    [
        "difflib",
        pytest.param(
            "rapidfuzz",
            marks=pytest.mark.skipif(
                not RAPIDFUZZ_AVAILABLE, reason="the [fuzzy] extra is not installed"
            ),
        ),
    ],
)
def test_table_fuzzy_off_holds_under_either_backend(backend: str) -> None:
    source = table(row("Design sign-off", "1 March 2026"))
    test = table(
        row("Training day", "20 March 2026"),
        row("Design sign-off", "10 March 2026"),
    )
    config = AlignmentConfig(similarity=backend)
    alignment = align(source, test, config=config)
    assert alignment.backend == backend
    row_pairs = [
        pair
        for pair in alignment.pairs
        if "/row[" in pair.source_path and "/cell[" not in pair.source_path
    ]
    assert all(pair.matched_by != "fuzzy" for pair in row_pairs)
