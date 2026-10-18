"""The view every in-place renderer walks: the test document, with deletions and move origins placed (ADR-0037).

The change tree is flat and document-ordered, and a deletion or a move origin
has no position in the test document. `build_view` gives every renderer the
same answer to "where does it stand": the *test* document in pre-order, with
two kinds of node added where ADR-0033's anchor puts them (`Anchors.place`):

- **ghosts**, the source blocks of ``delete`` nodes, with status ``DELETE``.
  A ghost keeps only the source children that were deleted too, recursively,
  plus a tombstone for each child that moved out of it; a matched child that
  did not move on its own rides with an ancestor's move and appears at its
  test position;
- **tombstones**, ``ORIGIN`` leaves for the origin of every ``move`` node.
  A move out of a deleted block is drawn inside that block's ghost, and a
  clause that moved out of a moved clause sits inside the outer clause's
  destination, at its source position among its siblings.

Ghosts and tombstones that share an anchor go in source order, after the test
children before them.

**Status comes from the change list only.** Unmatched descendants of an
``INSERT`` node take ``INSERT`` with no change of their own; a matched
descendant is a move into the inserted block and keeps its own node. So a
filtered comparison renders the same test document with only its own nodes
marked, which is what lets renderers have no filtered code path (ADR-0033). A
view that read ``alignment.inserted`` would still mark the inserts of a
modify-only filter.

The view reads only what survives ``to_dict(include_alignment=True)`` and
``from_dict``, costs O(N) with path dictionaries built once, and iterates no
``set``.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import Enum
from operator import itemgetter
from typing import TYPE_CHECKING, Final

from ..blocks import Block
from ..changes import Anchor, Anchors, Change, ChangeKind

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from ..comparison import Comparison

__all__: tuple[str, ...] = ("BlockStatus", "ViewNode", "build_view")


class BlockStatus(str, Enum):
    """What the view says happened to one block.

    The five change kinds, ``UNCHANGED`` for a block no node names, and
    ``ORIGIN`` for the tombstone at a moved block's origin.
    """

    UNCHANGED = "unchanged"
    INSERT = "insert"
    DELETE = "delete"
    MODIFY = "modify"
    MOVE = "move"
    RENUMBER = "renumber"
    ORIGIN = "origin"

    def __str__(self) -> str:
        """Return the status's name; 3.10 and 3.11+ format str enums differently."""
        return self.value


_STATUS: Final[dict[ChangeKind, BlockStatus]] = {
    ChangeKind.INSERT: BlockStatus.INSERT,
    ChangeKind.DELETE: BlockStatus.DELETE,
    ChangeKind.MODIFY: BlockStatus.MODIFY,
    ChangeKind.MOVE: BlockStatus.MOVE,
    ChangeKind.RENUMBER: BlockStatus.RENUMBER,
}


@dataclass(frozen=True, slots=True)
class ViewNode:
    """One block of the view, and the view of its children.

    :param status: what happened to the block.
    :param block: the test block; the source block for ``DELETE`` and
        ``ORIGIN``.
    :param counterpart: the source block of a matched test block, ``None`` for
        an inserted block, a ghost and a tombstone.
    :param change: the change node that owns the status; ``None`` for
        ``UNCHANGED`` and for every block inside an inserted or deleted subtree
        below its topmost block.
    :param children: the test children in order, with ghosts and tombstones
        placed among them.
    """

    status: BlockStatus
    block: Block
    counterpart: Block | None
    change: Change | None
    children: tuple[ViewNode, ...] = ()

    def walk(self) -> Iterator[ViewNode]:
        """Yield this node and every node below it, in pre-order.

        :return: an iterator over the view.
        """
        stack: list[ViewNode] = [self]
        while stack:
            node = stack.pop()
            yield node
            stack.extend(reversed(node.children))


def build_view(comparison: Comparison) -> ViewNode:
    """Build the view of a comparison's test document (ADR-0037, rules 1 to 7).

    :param comparison: the comparison to draw, filtered or not.
    :return: the view's root, the test document's root block.
    """
    return _ViewBuilder(comparison).build()


_Placed = tuple[int, ViewNode]
"""A ghost or tombstone and its source pre-order rank, for ordering at an anchor."""


class _ViewBuilder:
    """One pass over each tree, with the anchored nodes grouped by where they go."""

    def __init__(self, comparison: Comparison) -> None:
        self.comparison = comparison
        self.alignment = comparison.alignment
        self.source_blocks: dict[str, Block] = {
            block.path: block for block in comparison.source.walk()
        }
        self.source_rank: dict[str, int] = {
            path: rank for rank, path in enumerate(self.source_blocks)
        }
        self.deleted: dict[str, None] = dict.fromkeys(self.alignment.deleted)
        self.by_test: dict[str, Change] = {}
        self.moves: dict[str, Change] = {}
        self.deletes: list[Change] = []
        for change in comparison.changes:
            if change.kind is ChangeKind.DELETE:
                self.deletes.append(change)
                continue
            if change.test_address is not None:
                self.by_test[change.test_address] = change
            if change.kind is ChangeKind.MOVE and change.source_address is not None:
                self.moves[change.source_address] = change
        # test parent -> anchor's ``after`` (None: first) -> nodes placed there
        self.anchored: dict[str, dict[str | None, list[_Placed]]] = {}

    def build(self) -> ViewNode:
        """Place every ghost and tombstone, then build the test side around them."""
        anchors = Anchors(
            source=self.comparison.source,
            test=self.comparison.test,
            alignment=self.alignment,
        )
        for change in self.deletes:
            path = change.source_address
            if path is None:  # pragma: no cover - a delete always has one
                continue
            anchor = anchors.place(path)
            # A topmost delete's parent is always matched, so its anchor exists;
            # a delete node below another deleted block is drawn in that ghost.
            if anchor is not None:
                self._place(anchor, path, self._ghost(self.source_blocks[path], change))
        for path, change in self.moves.items():
            anchor = anchors.place(path)
            # None only inside a deleted ancestor, whose ghost draws this one.
            if anchor is not None:
                origin = ViewNode(BlockStatus.ORIGIN, self.source_blocks[path], None, change)
                self._place(anchor, path, origin)
        return self._test(self.comparison.test.root, inside_insert=False)

    def _place(self, anchor: Anchor, path: str, node: ViewNode) -> None:
        by_after = self.anchored.setdefault(anchor.test_parent, {})
        by_after.setdefault(anchor.after, []).append((self.source_rank[path], node))

    def _ghost(self, block: Block, change: Change | None) -> ViewNode:
        """A deleted source block, pruned to its deleted children and its moves out."""
        children: list[ViewNode] = []
        for child in block.children:
            if child.path in self.deleted:
                children.append(self._ghost(child, None))
            else:
                moved = self.moves.get(child.path)
                if moved is not None:
                    children.append(ViewNode(BlockStatus.ORIGIN, child, None, moved))
        return ViewNode(BlockStatus.DELETE, block, None, change, tuple(children))

    def _test(self, block: Block, *, inside_insert: bool) -> ViewNode:
        """One test block, its children, and whatever is anchored among them."""
        change = self.by_test.get(block.path)
        source_path = self.alignment.source_for(block.path)
        counterpart = None if source_path is None else self.source_blocks.get(source_path)
        if change is not None:
            status = _STATUS[change.kind]
        elif inside_insert and source_path is None:
            status = BlockStatus.INSERT
        else:
            status = BlockStatus.UNCHANGED
        children_inside_insert = status is BlockStatus.INSERT
        placed = self.anchored.get(block.path, {})
        children = [node for _, node in sorted(placed.get(None, ()), key=itemgetter(0))]
        for child in block.children:
            children.append(self._test(child, inside_insert=children_inside_insert))
            here = placed.get(child.path)
            if here:
                children.extend(node for _, node in sorted(here, key=itemgetter(0)))
        return ViewNode(status, block, counterpart, change, tuple(children))
