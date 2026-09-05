"""The eight promises of the sample pair, read off its change tree (#144).

`tests/corpus/sample_pair/CHANGES.md` says the amended agreement carries
exactly eight changes, one of each thing the engine is meant to detect, and
nothing else. `tests/test_sample_pair.py` checks that both versions *parse*
into the trees M1 froze. This module checks what M2 makes of the difference
between them: one named test per row of that table, so a failure says which
promise broke rather than printing a hundred kilobytes of diff.

Each test composes the comparison itself, through the public `compare`, rather
than loading a golden. The eight pin the parts the pair exists to demonstrate,
and they were written before `redlines.comparison` existed, as the
specification it was built against.

Beneath them sit the whole-tree tests, which load the two goldens
`tests/corpus/sample_pair/expected/change_tree.{contract,markdown}.json` and
pin every byte: both block trees, all ten change nodes, the alignment and the
statistics, as JSON v2. They compose the comparison themselves too -- the
regeneration script is never imported -- so a drift between what `compare`
composes and what the script wrote is a failure rather than a silently
regenerated golden, exactly as `tests/test_sample_pair.py` treats the block
trees. When one fails, the eight above say which promise broke; when they all
pass and a whole-tree test still fails, something changed that CHANGES.md
never promised, and the diff is the review.

The goldens are generated under an explicitly named ``difflib`` backend
(`GOLDEN_BACKEND`), because ``auto`` resolves differently depending on whether
the ``[fuzzy]`` extra is installed and the resolved name goes on the wire. The
backend costs no coverage here: `test_the_similarity_backend_does_not_change_the_answer`
asserts the two agree on every node, every pair and every statistic of this
pair.

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

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from redlines.similarity import RAPIDFUZZ_AVAILABLE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from redlines.changes import Change
    from redlines.comparison import Comparison

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair"
EXPECTED_DIR = CASE_DIR / "expected"

GOLDEN_BACKEND = "difflib"
"""The similarity backend the goldens were generated under.

Spelled here rather than imported from
`tests/corpus/sample_pair/regenerate.py`, so that the script and the test have
to agree by review rather than by construction -- the same reason
`tests/test_sample_pair.py` writes the M1 pipeline out again instead of
calling the script's `build_tree`.
"""

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

_CACHE: dict[tuple[str, str | None], Comparison] = {}


def comparison_for(profile_name: str, *, backend: str | None = None) -> Comparison:
    """Compare the sample pair under one profile, through the public entry point.

    The import is inside the function on purpose: these tests were written
    before `redlines.comparison` existed, and a module-level import would have
    turned eight expected failures into one collection error.

    :param profile_name: which twin of the pair to compare.
    :param backend: the similarity backend to pin, or ``None`` -- the default
        -- to let `redlines.alignment.DEFAULT_ALIGNMENT` resolve ``"auto"``.
        The eight named tests below leave it alone, so they exercise whatever
        the installed extras actually give a user; the whole-tree tests pin
        `GOLDEN_BACKEND`, because the resolved name goes on the wire.
    :return: the `redlines.comparison.Comparison`, cached per (profile, backend).
    """
    key = (profile_name, backend)
    if key not in _CACHE:
        _CACHE[key] = fresh_comparison(profile_name, backend=backend)
    return _CACHE[key]


def fresh_comparison(profile_name: str, *, backend: str | None = None) -> Comparison:
    """Compare the pair again, bypassing the cache.

    Separate from `comparison_for` so that the determinism test can ask for
    two genuinely independent runs and get two, rather than the same object
    twice.

    :param profile_name: which twin of the pair to compare.
    :param backend: the similarity backend to pin, or ``None`` for the default.
    :return: a newly built `redlines.comparison.Comparison`.
    """
    from redlines import compare
    from redlines.alignment import DEFAULT_ALIGNMENT, AlignmentConfig

    config = (
        DEFAULT_ALIGNMENT if backend is None else AlignmentConfig(similarity=backend)
    )
    for name, source_name, test_name, format_name in PAIRINGS:
        if name != profile_name:
            continue
        return compare(
            (CASE_DIR / source_name).read_text(encoding="utf-8"),
            (CASE_DIR / test_name).read_text(encoding="utf-8"),
            format=format_name,
            profile=profile_name,
            alignment=config,
        )
    raise AssertionError(  # pragma: no cover - a typo in a parametrisation
        f"{profile_name!r} is not one of the sample pair's"
    )


def golden_path(profile_name: str) -> Path:
    """The change-tree golden for one twin."""
    return EXPECTED_DIR / f"change_tree.{profile_name}.json"


def golden_text(profile_name: str) -> str:
    """The golden exactly as it is stored, bytes and all."""
    return golden_path(profile_name).read_text(encoding="utf-8")


def golden_dict(profile_name: str) -> dict[str, Any]:
    """The golden parsed."""
    loaded: dict[str, Any] = json.loads(golden_text(profile_name))
    return loaded


def golden_form(document: dict[str, Any]) -> str:
    """Serialise a v2 document the way the goldens are stored.

    Sorted keys, two-space indent, trailing newline -- the same form
    `tests/corpus/sample_pair/regenerate.py` writes and the same form the four
    block-tree goldens use, spelled out here rather than imported so the two
    have to agree by review.
    """
    return json.dumps(document, indent=2, sort_keys=True) + "\n"


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


# --- the whole tree, against the two goldens -------------------------------
#
# Everything above says what CHANGES.md promises. Everything below says that
# nothing else happened -- and that what did happen is exactly the bytes under
# `expected/`, so a change anywhere in the engine, the readers or the profiles
# arrives as a reviewable diff instead of as silence.


DIVERGES = "<resolved per twin: CHANGES.md change 6>"
"""Placeholder for the one address the two twins do not share."""

# The ten nodes, as (kind, source address, test address), in the order the
# change tree emits them: flat, document-ordered on the test address, with a
# deleted block sorted by its predecessor (ADR-0033). Nine of the ten are the
# same in both twins; the tenth is CHANGES.md change 6, the one divergence.
TEN_NODES: tuple[tuple[str, str | None, str | None], ...] = (
    ("modify", CONFIDENTIAL_INFORMATION, CONFIDENTIAL_INFORMATION),
    ("insert", None, INSERTED_CLAUSE),
    (
        "renumber",
        f"{RENUMBERED_SECTION}/list_item[3]",
        f"{RENUMBERED_SECTION}/list_item[4]",
    ),
    (
        "renumber",
        f"{RENUMBERED_SECTION}/list_item[4]",
        f"{RENUMBERED_SECTION}/list_item[5]",
    ),
    ("delete", DELETED_SUB_CLAUSE, None),
    ("modify", CROSS_REFERENCE_CLAUSE, CROSS_REFERENCE_CLAUSE),
    ("move", MOVED_CLAUSE_SOURCE, MOVED_CLAUSE_TEST),
    ("modify", MOVED_BODY_SOURCE, MOVED_BODY_TEST),
    ("insert", None, DIVERGES),
    ("modify", REPETITIVE_SCHEDULE_ITEM, REPETITIVE_SCHEDULE_ITEM),
)

# Where change 6 lands in each twin: a table row in markdown, an ordinary
# paragraph in the plain text, which has no table to put a row in.
CHANGE_SIX: dict[str, str] = {
    "markdown": INSERTED_TABLE_ROW,
    "contract": INSERTED_SCHEDULE_PARAGRAPH,
}


def expected_nodes(profile_name: str) -> list[tuple[str, str | None, str | None]]:
    """`TEN_NODES` with change 6's address resolved for one twin."""
    resolved: list[tuple[str, str | None, str | None]] = []
    for kind, source, test in TEN_NODES:
        if test == DIVERGES:
            test = CHANGE_SIX[profile_name]
        resolved.append((kind, source, test))
    return resolved


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_pair_produces_exactly_ten_change_nodes(profile_name: str) -> None:
    """Eight promises, ten nodes, and nothing else in the document.

    CHANGES.md says the amended version carries "exactly eight changes, one of
    each thing the engine is meant to detect ... Nothing else differs". Ten
    nodes rather than eight because change 3 is an insert plus the two
    renumbers it causes, and change 2 is a move plus the edit that rode along
    in its body -- both of which are the point of those rows -- while changes 7
    and 8's absences are already asserted above. This is the readable half of
    the whole-tree golden: when it fails, it names the node that appeared or
    vanished instead of printing three hundred kilobytes.
    """
    comparison = comparison_for(profile_name, backend=GOLDEN_BACKEND)
    assert [
        (str(change.kind), change.source_address, change.test_address)
        for change in comparison.changes
    ] == expected_nodes(profile_name)


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_whole_comparison_matches_the_golden(profile_name: str) -> None:
    """The golden, byte for byte: both trees, the changes, the alignment, the stats.

    Compared a section at a time before the whole document, so a failure names
    the part that moved -- a change node, a correspondence, a statistic, a
    configuration field -- rather than dumping the lot. The final assertion is
    on the stored *text*, which is what catches a golden that was reformatted
    or hand-edited rather than regenerated.
    """
    comparison = comparison_for(profile_name, backend=GOLDEN_BACKEND)
    built = comparison.to_dict(include_alignment=True)
    golden = golden_dict(profile_name)

    assert built["schema_version"] == golden["schema_version"]
    assert built["config"] == golden["config"]
    assert built["changes"] == golden["changes"]
    assert built["statistics"] == golden["statistics"]
    assert built["alignment"] == golden["alignment"]
    assert built["source"] == golden["source"]
    assert built["test"] == golden["test"]
    assert golden_form(built) == golden_text(profile_name)


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_golden_is_the_same_block_trees_the_m1_goldens_froze(
    profile_name: str,
) -> None:
    """ADR-0033: ``source`` and ``test`` are byte-for-byte `BlockTree.to_dict`.

    The clause is a conformance requirement, not a convenience, and this is
    where it is checked: the two sections of the change-tree golden are the
    four trees `tests/test_sample_pair.py` already froze, unreshaped. If they
    ever diverge, every consumer that reads a block tree out of a v2 payload
    is reading something M1 did not promise.
    """
    golden = golden_dict(profile_name)
    for side in ("source", "test"):
        frozen = json.loads(
            (EXPECTED_DIR / f"{side}.{profile_name}.json").read_text(encoding="utf-8")
        )
        assert golden[side] == frozen


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_golden_round_trips_through_from_dict(profile_name: str) -> None:
    """A golden is a *complete* comparison: it can be read back and re-emitted.

    This is why the goldens carry their alignment --
    `redlines.comparison.Comparison.from_dict` refuses a payload without one,
    on the grounds that rebuilding it as empty would be a lie about which
    blocks correspond. Round-tripping is the strongest form of the freeze: it
    says the format can express everything the engine produced, with nothing
    lost on the way out and nothing invented on the way back in.
    """
    from redlines.comparison import Comparison

    golden = golden_dict(profile_name)
    rebuilt = Comparison.from_dict(golden)
    assert rebuilt.to_dict(include_alignment=True) == golden


@pytest.mark.parametrize("profile_name", PROFILES)
def test_comparing_the_pair_twice_gives_the_same_bytes(profile_name: str) -> None:
    """Determinism, within one process, over the whole document.

    `tests/test_determinism.py` runs the alignment across ``PYTHONHASHSEED``
    values; this is the cheaper end of the same property, and it is the one
    that would catch a set iterated somewhere in the change tree, the
    statistics or the serialisation.
    """
    runs = [
        golden_form(
            fresh_comparison(profile_name, backend=GOLDEN_BACKEND).to_dict(
                include_alignment=True
            )
        )
        for _ in range(2)
    ]
    assert runs[0] == runs[1]


@pytest.mark.skipif(
    not RAPIDFUZZ_AVAILABLE,
    reason="the claim is about the two backends agreeing, so both must be "
    "installed; run `uv sync --all-extras --dev`",
)
@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_similarity_backend_does_not_change_the_answer(profile_name: str) -> None:
    """Why one golden, generated under one named backend, is honest.

    ADR-0008 notes that results differ subtly with and without rapidfuzz, and
    ADR-0032 requires the two to search the same space; on this pair they
    agree on every change node, every correspondence and every statistic, and
    differ only in the two places that *record* which backend ran. So pinning
    ``difflib`` in the golden costs no coverage -- and if that ever stops being
    true, this test says so rather than the goldens quietly failing on one CI
    leg.
    """
    floor = comparison_for(profile_name, backend="difflib").to_dict(
        include_alignment=True
    )
    fast = comparison_for(profile_name, backend="rapidfuzz").to_dict(
        include_alignment=True
    )

    assert floor["changes"] == fast["changes"]
    assert floor["statistics"] == fast["statistics"]
    assert floor["alignment"]["pairs"] == fast["alignment"]["pairs"]
    assert floor["alignment"]["inserted"] == fast["alignment"]["inserted"]
    assert floor["alignment"]["deleted"] == fast["alignment"]["deleted"]
    assert floor["alignment"]["pass_counts"] == fast["alignment"]["pass_counts"]

    assert (floor["config"]["similarity"], fast["config"]["similarity"]) == (
        "difflib",
        "rapidfuzz",
    )
    assert (floor["alignment"]["backend"], fast["alignment"]["backend"]) == (
        "difflib",
        "rapidfuzz",
    )
