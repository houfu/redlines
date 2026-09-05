"""How much changed, and where (#139, ADR-0033).

`redlines.changes.build_change_tree` says *what* happened to each block.
This module counts it: how many inserts, deletes, modifies, moves and
renumbers; how many inline insertions, deletions and replacements; how many
tokens and characters moved; and how that load is distributed across the
document's own sections.

**Computed, not cached.** A `ComparisonStatistics` is built from a
`Comparison`'s change tree and two block trees on every call, in O(changes)
time. A frozen `slots` dataclass has nowhere good to cache a derived value,
and the input is already in memory -- there is nothing here worth memoising.

**What a "section" is.** #139 asks for "per top-level section" statistics.
Taken literally against a real contract that is the wrong unit: the PRD § 3a
sample pair's root has one child that is the *entire* body -- a `section`
block whose own children are eleven numbered sections and about a hundred
blocks below them -- so a single density number for it says nothing a
reviewer could use. The unit this module actually reports on is **every
block of kind ``section`` that has a ``heading`` child**, wherever it sits in
the tree, and every change is attributed to its **nearest enclosing** such
unit only -- never cumulatively to every ancestor section as well. Under this
reading the sample pair's outer wrapper reports only its own title and
parties paragraph, and ``/section[1]/section[3]`` reports the renumbering
inside it on its own six blocks -- the number #139's own next clause ("using
the heading breadcrumb from ADR-0029") was pointing at all along.

**Attribution side.** A change with a ``test_address`` (insert, modify, move,
renumber) is attributed by walking up the *test* tree from that address; a
``delete`` has no test address, so it is attributed by walking up the
*source* tree from its ``source_address`` instead -- the tree it still exists
in. Walking includes the change's own address, so a change *to* a section
block itself (an inserted or renumbered section, say) counts toward that
section, not its parent.

**The block denominator is test-side and change-independent.** ``blocks`` on
each `SectionStatistics` is how many blocks of the *test* tree have that
section as their nearest enclosing one -- every block, changed or not. A
section that was deleted whole (see below) has no blocks in the test tree at
all, so it reports ``0`` and a density of ``0.0``, however large the deletion
was. **Denominators always come from the unfiltered trees**: if
`redlines.comparison.Comparison.filter` produced this comparison, only the
numerators shrink, so a filtered density answers "how many of the changes I
asked to see, over how many blocks are actually there" rather than
overstating how much of the section changed.

**A section deleted whole gets its own row, by its source address.** A
``delete`` change whose own block was itself a section-with-heading unit
means the *entire* section vanished -- there is no test-side address to hang
a row off, so `SectionStatistics.address` falls back to the source one, and
``heading``/``breadcrumb`` come from the source tree. It is placed in
document order using the same surviving-neighbour rule
`redlines.changes.build_change_tree` places a topmost delete node by.

**No `by_block` array.** R22's per-block half of the ask is already on the
node: `redlines.changes.Change.inline`, `.tokens_changed`, `.chars_added` and
`.chars_deleted`. A second array keyed by address would just be the change
list again, at a cost M5's size guards and the site would both pay.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from .blocks import Block, BlockKind, BlockTree

if TYPE_CHECKING:  # pragma: no cover - typing only, avoids a circular import
    from .comparison import Comparison

from .changes import Change, ChangeKind, ChangeTree, InlineKind

__all__: tuple[str, ...] = (
    "ChangeCounts",
    "SectionStatistics",
    "ComparisonStatistics",
    "statistics",
)


@dataclass(frozen=True, slots=True)
class ChangeCounts:
    """How many changes there were, and what kind, over one list of nodes.

    Counts of **change nodes**, not blocks: a deleted forty-block schedule is
    one ``deleted``, not forty (ADR-0033's topmost-wins granularity). A
    consumer wanting the block count walks the subtree in the block tree.

    :param inserted: nodes of kind ``insert``.
    :param deleted: nodes of kind ``delete``.
    :param modified: nodes of kind ``modify``.
    :param moved: nodes of kind ``move``.
    :param renumbered: nodes of kind ``renumber``.
    :param total: every node, the sum of the five counts above.
    :param inline_insertions: `redlines.changes.InlineOp` s of kind
        ``insert``, across every node.
    :param inline_deletions: the same for ``delete`` ops.
    :param inline_replacements: the same for ``replace`` ops.
    :param tokens_changed: the sum of `redlines.changes.Change.tokens_changed`
        over every node -- #139's "inline tokens changed".
    :param chars_added: the sum of `redlines.changes.Change.chars_added`.
    :param chars_deleted: the sum of `redlines.changes.Change.chars_deleted`.
    """

    inserted: int = 0
    deleted: int = 0
    modified: int = 0
    moved: int = 0
    renumbered: int = 0
    total: int = 0
    inline_insertions: int = 0
    inline_deletions: int = 0
    inline_replacements: int = 0
    tokens_changed: int = 0
    chars_added: int = 0
    chars_deleted: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Return the counts as a JSON-serialisable dict, in a fixed key order."""
        return {
            "inserted": self.inserted,
            "deleted": self.deleted,
            "modified": self.modified,
            "moved": self.moved,
            "renumbered": self.renumbered,
            "total": self.total,
            "inline_insertions": self.inline_insertions,
            "inline_deletions": self.inline_deletions,
            "inline_replacements": self.inline_replacements,
            "tokens_changed": self.tokens_changed,
            "chars_added": self.chars_added,
            "chars_deleted": self.chars_deleted,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChangeCounts:
        """Rebuild counts from `to_dict` output."""
        return cls(
            inserted=int(data.get("inserted", 0)),
            deleted=int(data.get("deleted", 0)),
            modified=int(data.get("modified", 0)),
            moved=int(data.get("moved", 0)),
            renumbered=int(data.get("renumbered", 0)),
            total=int(data.get("total", 0)),
            inline_insertions=int(data.get("inline_insertions", 0)),
            inline_deletions=int(data.get("inline_deletions", 0)),
            inline_replacements=int(data.get("inline_replacements", 0)),
            tokens_changed=int(data.get("tokens_changed", 0)),
            chars_added=int(data.get("chars_added", 0)),
            chars_deleted=int(data.get("chars_deleted", 0)),
        )


def _count(changes: Sequence[Change]) -> ChangeCounts:
    """Tally one list of nodes into a `ChangeCounts`."""
    inserted = deleted = modified = moved = renumbered = 0
    inline_insertions = inline_deletions = inline_replacements = 0
    tokens_changed = chars_added = chars_deleted = 0
    for change in changes:
        if change.kind is ChangeKind.INSERT:
            inserted += 1
        elif change.kind is ChangeKind.DELETE:
            deleted += 1
        elif change.kind is ChangeKind.MODIFY:
            modified += 1
        elif change.kind is ChangeKind.MOVE:
            moved += 1
        elif change.kind is ChangeKind.RENUMBER:
            renumbered += 1
        tokens_changed += change.tokens_changed
        chars_added += change.chars_added
        chars_deleted += change.chars_deleted
        for op in change.inline:
            if op.kind is InlineKind.INSERT:
                inline_insertions += 1
            elif op.kind is InlineKind.DELETE:
                inline_deletions += 1
            elif op.kind is InlineKind.REPLACE:
                inline_replacements += 1
    return ChangeCounts(
        inserted=inserted,
        deleted=deleted,
        modified=modified,
        moved=moved,
        renumbered=renumbered,
        total=len(changes),
        inline_insertions=inline_insertions,
        inline_deletions=inline_deletions,
        inline_replacements=inline_replacements,
        tokens_changed=tokens_changed,
        chars_added=chars_added,
        chars_deleted=chars_deleted,
    )


@dataclass(frozen=True, slots=True)
class SectionStatistics:
    """Counts and density for one section-with-heading unit (#139, ADR-0033).

    :param address: the section block's test address, or its source address
        when the whole section was deleted (see the module docstring).
    :param heading: the section's ``heading`` child's text.
    :param breadcrumb: the ADR-0029 heading breadcrumb leading to the section
        itself, from whichever side ``address`` names.
    :param blocks: how many blocks of the *test* tree have this section as
        their nearest enclosing one. Change-independent and always from the
        unfiltered tree; ``0`` for a section deleted whole.
    :param counts: the changes attributed to this section.
    :param density: ``counts.total / blocks``, rounded to four places;
        ``0.0`` when ``blocks`` is ``0``.
    """

    address: str
    heading: str
    breadcrumb: tuple[str, ...]
    blocks: int
    counts: ChangeCounts
    density: float

    def to_dict(self) -> dict[str, Any]:
        """Return this row as a JSON-serialisable dict, in a fixed key order."""
        return {
            "address": self.address,
            "heading": self.heading,
            "breadcrumb": list(self.breadcrumb),
            "blocks": self.blocks,
            "counts": self.counts.to_dict(),
            "density": self.density,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SectionStatistics:
        """Rebuild a row from `to_dict` output."""
        return cls(
            address=str(data["address"]),
            heading=str(data.get("heading", "")),
            breadcrumb=tuple(str(part) for part in data.get("breadcrumb", ()) or ()),
            blocks=int(data.get("blocks", 0)),
            counts=ChangeCounts.from_dict(data.get("counts", {}) or {}),
            density=float(data.get("density", 0.0)),
        )


@dataclass(frozen=True, slots=True)
class ComparisonStatistics:
    """Every count #139 asks for, over one `redlines.comparison.Comparison`.

    :param counts: every change in the comparison, tallied.
    :param source_blocks: how many blocks the source tree has.
    :param test_blocks: how many blocks the test tree has.
    :param sections: one row per section-with-heading unit that exists on
        either side, in document order.
    """

    counts: ChangeCounts
    source_blocks: int
    test_blocks: int
    sections: tuple[SectionStatistics, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the statistics as a JSON-serialisable dict, in a fixed key order."""
        return {
            "counts": self.counts.to_dict(),
            "source_blocks": self.source_blocks,
            "test_blocks": self.test_blocks,
            "sections": [section.to_dict() for section in self.sections],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ComparisonStatistics:
        """Rebuild statistics from `to_dict` output."""
        return cls(
            counts=ChangeCounts.from_dict(data.get("counts", {}) or {}),
            source_blocks=int(data.get("source_blocks", 0)),
            test_blocks=int(data.get("test_blocks", 0)),
            sections=tuple(
                SectionStatistics.from_dict(section)
                for section in data.get("sections", ()) or ()
            ),
        )


def statistics(comparison: Comparison) -> ComparisonStatistics:
    """Compute `ComparisonStatistics` for a `redlines.comparison.Comparison`.

    Also available as ``comparison.statistics()``.

    :param comparison: the comparison to summarise. Its ``changes`` may be a
        `redlines.filters.filter_changes` result -- the counts then reflect
        the filtered list, while ``source_blocks``/``test_blocks`` and every
        section's ``blocks`` still come from the unfiltered trees.
    :return: the `ComparisonStatistics`.
    """
    source, test = comparison.source, comparison.test
    changes = tuple(comparison.changes)

    source_parents = _parent_map(source)
    test_parents = _parent_map(test)
    test_units = {
        block.path: block for block in test.walk() if _is_section_unit(block)
    }
    source_units = {
        block.path: block for block in source.walk() if _is_section_unit(block)
    }

    # blocks whose nearest enclosing (test-side) section is each unit.
    block_counts: dict[str, int] = dict.fromkeys(test_units, 0)
    for block in test.walk():
        nearest = _nearest_enclosing(block.path, test_parents, test_units)
        if nearest is not None:
            block_counts[nearest] += 1

    # a delete whose own block was itself a section unit: the whole section
    # vanished, and it needs a row of its own, addressed on the source side.
    deleted_units = [
        change.source_address
        for change in changes
        if change.kind is ChangeKind.DELETE
        and change.source_address is not None
        and change.source_address in source_units
    ]

    by_section: dict[str, list[Change]] = {addr: [] for addr in test_units}
    for addr in deleted_units:
        by_section.setdefault(addr, [])
    for change in changes:
        if change.kind is ChangeKind.DELETE:
            nearest = _nearest_enclosing(
                change.source_address, source_parents, source_units
            )
        else:
            nearest = _nearest_enclosing(change.test_address, test_parents, test_units)
        if nearest is not None:
            by_section[nearest].append(change)

    order = _section_order(test, source, comparison, test_units.keys(), deleted_units)
    sections = tuple(
        _row(addr, test, source, test_units, source_units, block_counts, by_section)
        for addr in order
    )

    return ComparisonStatistics(
        counts=_count(changes),
        source_blocks=sum(1 for _ in source.walk()),
        test_blocks=sum(1 for _ in test.walk()),
        sections=sections,
    )


# --------------------------------------------------------------------------
# Everything below is private; the shapes above are the contract.
# --------------------------------------------------------------------------


def _is_section_unit(block: Block) -> bool:
    """Whether ``block`` is a section that has a heading child (#139)."""
    return block.kind is BlockKind.SECTION and any(
        child.kind is BlockKind.HEADING for child in block.children
    )


def _parent_map(tree: BlockTree) -> dict[str, str | None]:
    """Map every address in ``tree`` to its parent's address, root to ``None``."""
    parents: dict[str, str | None] = {}

    def visit(block: Block, parent_path: str | None) -> None:
        parents[block.path] = parent_path
        for child in block.children:
            visit(child, block.path)

    visit(tree.root, None)
    return parents


def _nearest_enclosing(
    address: str | None, parents: dict[str, str | None], units: dict[str, Block]
) -> str | None:
    """The nearest section unit at or above ``address``, or ``None``.

    Inclusive of ``address`` itself, so a change *to* a section block is
    attributed to that section, not its parent.
    """
    if address is None:
        return None
    current: str | None = address
    while current is not None:
        if current in units:
            return current
        current = parents.get(current)
    return None


def _heading_text(unit: Block) -> str:
    """The text of a section unit's own ``heading`` child."""
    for child in unit.children:
        if child.kind is BlockKind.HEADING:
            return child.text
    return ""  # pragma: no cover - _is_section_unit already guarantees one


def _row(
    address: str,
    test: BlockTree,
    source: BlockTree,
    test_units: dict[str, Block],
    source_units: dict[str, Block],
    block_counts: dict[str, int],
    by_section: dict[str, list[Change]],
) -> SectionStatistics:
    """Build one `SectionStatistics` row, test-side unit or deleted-whole."""
    if address in test_units:
        unit = test_units[address]
        breadcrumb = test.heading_breadcrumb(address)
    else:
        unit = source_units[address]
        breadcrumb = source.heading_breadcrumb(address)
    blocks = block_counts.get(address, 0)
    counts = _count(by_section.get(address, ()))
    density = round(counts.total / blocks, 4) if blocks else 0.0
    return SectionStatistics(
        address=address,
        heading=_heading_text(unit),
        breadcrumb=breadcrumb,
        blocks=blocks,
        counts=counts,
        density=density,
    )


def _section_order(
    test: BlockTree,
    source: BlockTree,
    comparison: Comparison,
    test_addrs: Any,
    deleted_addrs: list[str],
) -> Iterator[str]:
    """Document order over both test-side units and whole-section deletes.

    A test-side unit is ordered by its own position in the test tree. A
    section deleted whole has no test position of its own, so it is placed
    the same way `redlines.changes.build_change_tree` places a topmost
    delete: immediately after the last surviving neighbour before it, using
    the comparison's own alignment.
    """
    test_order = {block.path: index for index, block in enumerate(test.walk())}
    source_order = {block.path: index for index, block in enumerate(source.walk())}
    alignment = comparison.alignment

    def placement(deleted_addr: str) -> tuple[int, int]:
        surviving = -1
        for path in sorted(source_order, key=source_order.__getitem__):
            if path == deleted_addr:
                break
            counterpart = alignment.test_for(path)
            if counterpart is not None:
                surviving = test_order.get(counterpart, surviving)
        return (surviving, source_order[deleted_addr])

    ranked: list[tuple[tuple[int, int], str]] = [
        ((test_order[addr], 0), addr) for addr in test_addrs
    ]
    ranked.extend((placement(addr), addr) for addr in deleted_addrs)
    ranked.sort(key=lambda item: item[0])
    return (addr for _, addr in ranked)
