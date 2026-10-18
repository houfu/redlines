"""N2 for the renderers: 2,000 flat blocks, half of them deleted (ADR-0037, rule 6).

The view and the traversal are O(N), with path dictionaries built once and no
``BlockTree.block_at`` in a loop. The design measured 1.1 ms for the anchors
and 9 ms for the view and a render at this size. Each step is held to a
second, and doubling the document is held to less than three times the cost:
a slip to O(N^2) with a small constant (a ``list.index`` per ghost costs tens
of milliseconds here) would pass a one-second budget, but not the ratio.

The renderers that build on the traversal add their own renders to this file.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pytest

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.changes import Anchors, ChangeKind
from redlines.comparison import Comparison, compare
from redlines.renderers._inplace import render_inplace
from redlines.renderers._marks import CRITIC, LEGACY
from redlines.renderers._view import BlockStatus, build_view

BLOCKS = 2_000
FLOOR = 0.005
"""Seconds below which a step is too quick for its ratio to mean anything."""


def _flat(count: int, *, keep_every: int = 1) -> BlockTree:
    paragraphs = tuple(
        Block(
            kind=BlockKind.PARAGRAPH,
            text=f"Paragraph {number} says something that no other paragraph says.",
            role="clause",
        )
        for number in range(count)
        if number % keep_every == 0
    )
    return BlockTree.build(Block(kind=BlockKind.DOCUMENT, children=paragraphs))


def _half_deleted(count: int) -> Comparison:
    comparison = compare(_flat(count), _flat(count, keep_every=2))
    deletes = sum(
        1 for change in comparison.changes if change.kind is ChangeKind.DELETE
    )
    assert deletes == count // 2
    return comparison


@pytest.fixture(scope="module")
def half_deleted() -> Comparison:
    return _half_deleted(BLOCKS)


@pytest.fixture(scope="module")
def twice_as_long() -> Comparison:
    return _half_deleted(2 * BLOCKS)


def _best(call: Callable[[], object]) -> float:
    """The best of three timings, in seconds."""
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        call()
        timings.append(time.perf_counter() - started)
    return min(timings)


def _steps(comparison: Comparison) -> dict[str, Callable[[], object]]:
    return {
        "anchors": lambda: Anchors(
            source=comparison.source,
            test=comparison.test,
            alignment=comparison.alignment,
        ),
        "view": lambda: build_view(comparison),
        "none render": lambda: render_inplace(
            comparison, LEGACY["none"], syntax="markdown", roles=False
        ),
        "critic render": lambda: render_inplace(
            comparison, CRITIC, syntax="markdown", roles=True
        ),
        "annotated render": lambda: comparison.output_annotated(),
    }


@pytest.mark.slow
def test_each_step_takes_under_a_second_and_grows_linearly(
    half_deleted: Comparison, twice_as_long: Comparison
) -> None:
    short, long = _steps(half_deleted), _steps(twice_as_long)
    for name in short:
        once, twice = _best(short[name]), _best(long[name])
        assert once < 1.0 and twice < 1.0, (name, once, twice)
        assert twice / max(once, FLOOR) < 3.0, (name, once, twice)


def test_the_view_of_the_scale_pair_has_every_ghost_in_place(
    half_deleted: Comparison,
) -> None:
    view = build_view(half_deleted)
    statuses = [node.status for node in view.children]
    assert statuses.count(BlockStatus.DELETE) == BLOCKS // 2
    assert statuses[:4] == [
        BlockStatus.UNCHANGED,
        BlockStatus.DELETE,
        BlockStatus.UNCHANGED,
        BlockStatus.DELETE,
    ]
