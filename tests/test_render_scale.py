"""N2 for the renderers: 2,000 flat blocks, half of them deleted (ADR-0037, rule 6).

The view and the traversal are O(N), with path dictionaries built once and no
``BlockTree.block_at`` in a loop. The design measured 1.1 ms for the anchors
and 9 ms for the view and a render at this size; each is held to a second
here, so a quadratic slip fails long before a slow runner could.

The renderers that build on the traversal add their own renders to this file.
"""

from __future__ import annotations

import time

import pytest

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.changes import Anchors, ChangeKind
from redlines.comparison import Comparison, compare
from redlines.renderers._inplace import render_inplace
from redlines.renderers._marks import CRITIC, LEGACY
from redlines.renderers._view import BlockStatus, build_view

BLOCKS = 2_000


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


@pytest.fixture(scope="module")
def half_deleted() -> Comparison:
    comparison = compare(_flat(BLOCKS), _flat(BLOCKS, keep_every=2))
    deletes = sum(1 for change in comparison.changes if change.kind is ChangeKind.DELETE)
    assert deletes == BLOCKS // 2
    return comparison


def _timed(seconds: list[float], call: object) -> object:
    assert callable(call)
    started = time.perf_counter()
    result = call()
    seconds.append(time.perf_counter() - started)
    return result


@pytest.mark.slow
def test_the_anchors_the_view_and_a_render_each_take_under_a_second(
    half_deleted: Comparison,
) -> None:
    comparison = half_deleted
    seconds: list[float] = []
    _timed(
        seconds,
        lambda: Anchors(
            source=comparison.source, test=comparison.test, alignment=comparison.alignment
        ),
    )
    view = _timed(seconds, lambda: build_view(comparison))
    _timed(
        seconds,
        lambda: render_inplace(comparison, LEGACY["none"], syntax="markdown", roles=False),
    )
    _timed(seconds, lambda: render_inplace(comparison, CRITIC, syntax="markdown", roles=True))
    assert all(elapsed < 1.0 for elapsed in seconds), seconds
    assert hasattr(view, "walk")


def test_the_view_of_the_scale_pair_has_every_ghost_in_place(half_deleted: Comparison) -> None:
    view = build_view(half_deleted)
    statuses = [node.status for node in view.children]
    assert statuses.count(BlockStatus.DELETE) == BLOCKS // 2
    assert statuses[:4] == [
        BlockStatus.UNCHANGED,
        BlockStatus.DELETE,
        BlockStatus.UNCHANGED,
        BlockStatus.DELETE,
    ]


@pytest.mark.slow
def test_the_markdown_and_rich_renders_each_take_under_a_second(
    half_deleted: Comparison,
) -> None:
    """``Comparison.output_markdown`` and ``Comparison.output_rich`` at N2's size (#179, #180)."""
    seconds: list[float] = []
    markdown = _timed(seconds, lambda: half_deleted.output_markdown("none"))
    rich = _timed(seconds, half_deleted.output_rich)
    assert all(elapsed < 1.0 for elapsed in seconds), seconds
    assert isinstance(markdown, str) and markdown.count("<del>") == BLOCKS // 2
    assert str(rich).startswith(f"{BLOCKS // 2} changes: 0 inserted, {BLOCKS // 2} deleted")
