"""The view of the test document (ADR-0037, "One walk over the test document").

``redlines/renderers/_view.py`` places every deletion and every move origin
with ADR-0033's anchor, so the renderers and the change list agree on where
each one sits. These tests pin its rules on the small renderer cases, and the
invariants the design sweep checked on the 60 committed runs:

- **V1** ``#INSERT == len(alignment.inserted)``, ``#DELETE ==
  len(alignment.deleted)``, and the matched statuses count
  ``len(alignment.pairs)``; tombstones are not counted;
- **V2** a change node's test address is unique among non-delete nodes, and
  its source address among deletes;
- **V4** every change with inline ops splits into segments that join back to
  both of its texts (355 ops on the 60 runs);
- the view's ``MOVE`` nodes are exactly the own moves of the alignment, and
  the change list's ``move`` nodes (24 on the 60 runs).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from redlines.alignment import AlignmentConfig
from redlines.changes import Change, ChangeKind, _under_a_move
from redlines.comparison import Comparison, compare
from redlines.renderers._inplace import inline_segments, render_inplace
from redlines.renderers._marks import CRITIC, LEGACY
from redlines.renderers._view import BlockStatus, ViewNode, build_view
from tests.helpers.committed_runs import COMMITTED_RUN_COUNT, committed_runs

CASES = Path(__file__).parent / "renderer_cases"
DIFFLIB = AlignmentConfig(similarity="difflib")

U, I, D, M, V, R, O = (
    BlockStatus.UNCHANGED,
    BlockStatus.INSERT,
    BlockStatus.DELETE,
    BlockStatus.MODIFY,
    BlockStatus.MOVE,
    BlockStatus.RENUMBER,
    BlockStatus.ORIGIN,
)


def case(name: str) -> Comparison:
    """One renderer case, compared as markdown under the golden backend."""
    directory = CASES / name
    return compare(
        (directory / "source.md").read_text(encoding="utf-8"),
        (directory / "test.md").read_text(encoding="utf-8"),
        format="markdown",
        alignment=DIFFLIB,
    )


def shape(view: ViewNode) -> list[tuple[BlockStatus, str]]:
    """The view flattened to (status, block path), in pre-order."""
    return [(node.status, node.block.path) for node in view.walk()]


# --- the status enum --------------------------------------------------------


def test_block_status_formats_as_its_value_on_every_python() -> None:
    assert [status.value for status in BlockStatus] == [
        "unchanged",
        "insert",
        "delete",
        "modify",
        "move",
        "renumber",
        "origin",
    ]
    assert str(BlockStatus.MOVE) == "move"
    assert f"{BlockStatus.ORIGIN}" == "origin"
    assert isinstance(BlockStatus.INSERT, str)
    assert BlockStatus("insert") is BlockStatus.INSERT


# --- the small cases ----------------------------------------------------------


def test_four_kinds_places_the_delete_after_2_1_and_the_origin_after_1_1() -> None:
    assert shape(build_view(case("four_kinds"))) == [
        (U, "/"),
        (U, "/section[1]"),
        (U, "/section[1]/heading[1]"),
        (M, "/section[1]/list_item[1]"),
        (O, "/section[1]/list_item[2]"),
        (I, "/section[1]/list_item[2]"),
        (U, "/section[2]"),
        (U, "/section[2]/heading[1]"),
        (U, "/section[2]/list_item[1]"),
        (D, "/section[2]/list_item[2]"),
        (V, "/section[2]/list_item[2]"),
    ]


def test_each_node_carries_the_block_and_change_its_status_names() -> None:
    comparison = case("four_kinds")
    nodes = list(build_view(comparison).walk())
    by_status = {node.status: node for node in nodes}
    modify = by_status[M]
    assert modify.block is comparison.test.root.children[0].children[1]
    assert modify.counterpart is comparison.source.root.children[0].children[1]
    assert modify.change is not None and modify.change.kind is ChangeKind.MODIFY
    ghost = by_status[D]
    assert ghost.block is comparison.source.root.children[1].children[2]
    assert ghost.counterpart is None
    assert ghost.change is not None and ghost.change.kind is ChangeKind.DELETE
    origin = by_status[O]
    assert origin.block is comparison.source.root.children[0].children[2]
    assert origin.change is by_status[V].change
    assert by_status[I].counterpart is None
    unchanged = [node for node in nodes if node.status is U]
    assert all(
        node.change is None and node.counterpart is not None for node in unchanged
    )


def test_a_moved_neighbour_does_not_carry_the_delete_after_it_into_another_section() -> (
    None
):
    assert shape(build_view(case("moved_neighbour"))) == [
        (U, "/"),
        (U, "/section[1]"),
        (U, "/section[1]/heading[1]"),
        (U, "/section[1]/list_item[1]"),
        (U, "/section[1]/list_item[2]"),
        (O, "/section[1]/list_item[3]"),
        (D, "/section[1]/list_item[4]"),
        (U, "/section[2]"),
        (U, "/section[2]/heading[1]"),
        (U, "/section[2]/list_item[1]"),
        (V, "/section[2]/list_item[2]"),
    ]


def test_a_clause_moved_out_of_a_moved_clause_has_its_tombstone_inside_the_destination() -> (
    None
):
    """ADR-0037's nested move: 7.2 moves to 8.2, and its child (b) moves on to 9.2."""
    assert shape(build_view(case("nested_move"))) == [
        (U, "/"),
        (U, "/section[1]"),
        (U, "/section[1]/heading[1]"),
        (U, "/section[1]/list_item[1]"),
        (O, "/section[1]/list_item[2]"),
        (U, "/section[2]"),
        (U, "/section[2]/heading[1]"),
        (U, "/section[2]/list_item[1]"),
        (V, "/section[2]/list_item[2]"),
        (U, "/section[2]/list_item[2]/list_item[1]"),
        (O, "/section[1]/list_item[2]/list_item[2]"),
        (U, "/section[3]"),
        (U, "/section[3]/heading[1]"),
        (U, "/section[3]/list_item[1]"),
        (V, "/section[3]/list_item[2]"),
    ]


def test_a_tombstone_stands_for_the_moved_block_alone() -> None:
    origins = [
        node for node in build_view(case("nested_move")).walk() if node.status is O
    ]
    assert [node.children for node in origins] == [(), ()]


def test_a_deleted_section_after_a_trailing_insert_sits_after_the_section_before_it() -> (
    None
):
    assert shape(build_view(case("trailing_insert"))) == [
        (U, "/"),
        (U, "/section[1]"),
        (U, "/section[1]/heading[1]"),
        (U, "/section[1]/list_item[1]"),
        (U, "/section[1]/list_item[2]"),
        (I, "/section[1]/list_item[3]"),
        (D, "/section[2]"),
        (D, "/section[2]/heading[1]"),
        (D, "/section[2]/list_item[1]"),
    ]
    ghost = [
        node for node in build_view(case("trailing_insert")).walk() if node.status is D
    ]
    assert ghost[0].change is not None
    assert [node.change for node in ghost[1:]] == [None, None]


def test_a_move_out_of_a_deleted_block_into_an_inserted_one_keeps_both_nodes() -> None:
    """Rules 1 and 2: the tombstone is drawn in the ghost, the destination keeps its node."""
    view = build_view(case("hostile"))
    ghost = next(
        node for node in view.walk() if node.status is D and node.change is not None
    )
    inserted = next(
        node for node in view.walk() if node.status is I and node.change is not None
    )
    assert [child.status for child in ghost.children] == [O]
    assert [child.status for child in inserted.children] == [V]
    assert ghost.children[0].change is inserted.children[0].change


def test_a_ghost_keeps_only_its_deleted_children_and_its_moves_out() -> None:
    comparison = compare(
        "## 1. Alpha\n\n1.1 The first clause stays where it is.\n\n## 2. Beta\n\n"
        "2.1 The second clause is deleted with its section.\n\n"
        "2.2 The third clause leaves its section for the first one.\n",
        "## 1. Alpha\n\n1.1 The first clause stays where it is.\n\n"
        "1.2 The third clause leaves its section for the first one.\n",
        format="markdown",
        alignment=DIFFLIB,
    )
    view = build_view(comparison)
    ghost = next(
        node for node in view.walk() if node.status is D and node.change is not None
    )
    assert ghost.block.path == "/section[2]"
    assert [(child.status, child.block.path) for child in ghost.children] == [
        (D, "/section[2]/heading[1]"),
        (D, "/section[2]/list_item[1]"),
        (O, "/section[2]/list_item[2]"),
    ]
    assert [node.status for node in view.walk()].count(V) == 1


# --- rule 1: status from the change list only -------------------------------------


def test_a_filtered_comparison_marks_only_its_own_nodes() -> None:
    filtered = case("four_kinds").filter(kinds=("modify",))
    view = build_view(filtered)
    assert Counter(node.status for node in view.walk()) == Counter({U: 8, M: 1})
    assert len(list(view.walk())) == len(list(filtered.test.walk()))


def test_an_inserted_subtree_marks_its_unmatched_descendants_without_a_change() -> None:
    comparison = compare(
        "## 1. Scope\n\n1.1 This Agreement covers the Services.\n",
        "## 1. Scope\n\n1.1 This Agreement covers the Services.\n\n## 2. Terms\n\n"
        "2.1 The Term is two years from the start date.\n\n"
        "2.2 Either party may renew it for one more year.\n",
        format="markdown",
        alignment=DIFFLIB,
    )
    view = build_view(comparison)
    inserted = [node for node in view.walk() if node.status is I]
    assert [node.block.path for node in inserted] == [
        "/section[2]",
        "/section[2]/heading[1]",
        "/section[2]/list_item[1]",
        "/section[2]/list_item[2]",
    ]
    assert inserted[0].change is not None
    assert [node.change for node in inserted[1:]] == [None, None, None]
    assert len(inserted) == len(comparison.alignment.inserted)


FILTERS: list[tuple[str, ...]] = [
    ("delete",),
    ("move",),
    ("insert",),
    ("modify",),
    ("renumber",),
    ("insert", "delete"),
    ("move", "delete"),
]

_Entry = tuple[str, str, str, tuple[str, str | None, str | None] | None]


def _key(change: Change | None) -> tuple[str, str | None, str | None] | None:
    if change is None:
        return None
    return (change.kind.value, change.source_address, change.test_address)


def _entries(node: ViewNode) -> list[_Entry]:
    """A view flattened to (status, tree, path, change), in pre-order."""
    side = "source" if node.status in (D, O) else "test"
    out: list[_Entry] = [(node.status.value, side, node.block.path, _key(node.change))]
    for child in node.children:
        out.extend(_entries(child))
    return out


def _filtered(
    node: ViewNode,
    kept: set[tuple[str, str | None, str | None]],
    owner: Change | None = None,
) -> list[_Entry]:
    """What filtering should do to an unfiltered view: the same placements, fewer marks.

    A ghost or a tombstone whose node is filtered away disappears with
    everything inside it; a test block whose node, or whose inserted
    ancestor's node, is filtered away is drawn unchanged.
    """
    own = node.change if node.change is not None else owner
    if node.status in (D, O):
        if own is None or _key(own) not in kept:
            return []
        out: list[_Entry] = [
            (node.status.value, "source", node.block.path, _key(node.change))
        ]
        for child in node.children:
            out.extend(_filtered(child, kept, own if node.status is D else None))
        return out
    if node.status is U or own is None or _key(own) not in kept:
        entry: _Entry = ("unchanged", "test", node.block.path, None)
        inherited = None
    else:
        entry = (node.status.value, "test", node.block.path, _key(node.change))
        inherited = own if node.status is I else None
    out = [entry]
    for child in node.children:
        out.extend(_filtered(child, kept, inherited))
    return out


def test_a_filtered_view_places_every_ghost_and_tombstone_as_the_unfiltered_one() -> (
    None
):
    """Rule 1 on the 60 runs: a filter removes marks, never moves a block."""
    checked = moved_marks = 0
    for run in committed_runs():
        source, test = run.texts()
        comparison = compare(source, test, format=run.format)
        unfiltered = build_view(comparison)
        for kinds in FILTERS:
            filtered = comparison.filter(kinds=kinds)
            kept = {
                key for change in filtered.changes if (key := _key(change)) is not None
            }
            expected = _filtered(unfiltered, kept)
            assert _entries(build_view(filtered)) == expected, (run.name, kinds)
            checked += 1
            moved_marks += expected != _entries(unfiltered)
    assert checked == 60 * len(FILTERS) == 420
    assert moved_marks > 300  # the filters do change what is marked


# --- rule 7: only what survives the wire ----------------------------------------


def _project(
    view: ViewNode,
) -> list[tuple[str, str, str | None, str | None, str | None]]:
    return [
        (
            node.status.value,
            node.block.path,
            None if node.counterpart is None else node.counterpart.path,
            None if node.change is None else node.change.kind.value,
            (
                None
                if node.change is None
                else (node.change.source_address or node.change.test_address)
            ),
        )
        for node in view.walk()
    ]


@pytest.mark.parametrize(
    "name",
    ["four_kinds", "moved_neighbour", "nested_move", "trailing_insert", "hostile"],
)
def test_a_round_tripped_comparison_has_the_same_view_and_renders_the_same(
    name: str,
) -> None:
    comparison = case(name)
    rebuilt = Comparison.from_dict(comparison.to_dict(include_alignment=True))
    assert _project(build_view(rebuilt)) == _project(build_view(comparison))
    for marks, roles in ((CRITIC, True), (LEGACY["none"], False)):
        assert render_inplace(
            rebuilt, marks, syntax="markdown", roles=roles
        ) == render_inplace(comparison, marks, syntax="markdown", roles=roles)


# --- the 60 committed runs ------------------------------------------------------


def _source_parents(comparison: Comparison) -> dict[str, str | None]:
    parents: dict[str, str | None] = {comparison.source.root.path: None}
    for block in comparison.source.walk():
        for child in block.children:
            parents[child.path] = block.path
    return parents


def test_the_committed_runs_are_sixty() -> None:
    assert len(committed_runs()) == COMMITTED_RUN_COUNT == 60


def test_v1_v2_v4_and_the_moves_hold_on_every_committed_run() -> None:
    inline_ops = 0
    moves = 0
    for run in committed_runs():
        source, test = run.texts()
        comparison = compare(source, test, format=run.format)
        alignment = comparison.alignment
        view = build_view(comparison)
        statuses = Counter(node.status for node in view.walk())
        # V1
        assert statuses[I] == len(alignment.inserted), run.name
        assert statuses[D] == len(alignment.deleted), run.name
        assert statuses[U] + statuses[M] + statuses[V] + statuses[R] == len(
            alignment.pairs
        ), run.name
        # V2
        test_addresses = [
            c.test_address
            for c in comparison.changes
            if c.kind is not ChangeKind.DELETE
        ]
        source_addresses = [
            c.source_address for c in comparison.changes if c.kind is ChangeKind.DELETE
        ]
        assert len(set(test_addresses)) == len(test_addresses), run.name
        assert len(set(source_addresses)) == len(source_addresses), run.name
        # V4
        for change in comparison.changes:
            if change.inline:
                segments = inline_segments(change)
                assert (
                    "".join(s.test_text for s in segments) == change.test_text
                ), run.name
                assert (
                    "".join(s.source_text for s in segments) == change.source_text
                ), run.name
                assert sum(s.kind != "equal" for s in segments) == len(
                    change.inline
                ), run.name
                inline_ops += len(change.inline)
        # own moves == MOVE nodes == move change nodes, each with one tombstone
        moved = {p.source_path: p.test_path for p in alignment.pairs if p.moved}
        parents = _source_parents(comparison)
        own = [
            path
            for path, landed in moved.items()
            if not _under_a_move(path, landed, source_parent=parents, moved=moved)
        ]
        move_nodes = [
            c.source_address or ""
            for c in comparison.changes
            if c.kind is ChangeKind.MOVE
        ]
        view_moves = [
            node.counterpart.path
            for node in view.walk()
            if node.status is V and node.counterpart is not None
        ]
        origins = [node.block.path for node in view.walk() if node.status is O]
        assert (
            sorted(own) == sorted(move_nodes) == sorted(view_moves) == sorted(origins)
        ), run.name
        # every delete node is drawn once, as the topmost block of its ghost
        ghosts = [
            node.block.path
            for node in view.walk()
            if node.status is D and node.change is not None
        ]
        assert sorted(ghosts) == sorted(
            path or "" for path in source_addresses
        ), run.name
        moves += len(move_nodes)
    assert inline_ops == 355
    assert moves == 24
