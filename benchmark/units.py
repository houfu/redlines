"""Flat line units, and the lift from a unit to a block address (#143, ADR-0034).

The 0.6 engine has no block model. It splits a document on runs of newlines
(`redlines.processor.split_paragraphs`) and diffs one flat token sequence
against another, with a ``¶`` token where a line boundary was. Its answer to
"which part of the old document is this part of the new one?" is therefore a
pairing of **lines**, and the benchmark's ground truth is a pairing of
**blocks**. Something has to carry one into the other, or the floor and the
engine are measured on different things and the comparison is worthless.

This module is that carrier, and it is deliberately the only place the
translation happens, because it is the one place the baseline can be
flattered or hobbled. Both of its rules are stated here, restated in
``benchmark/REPORT.md``, and nowhere else:

**The pairing rule.** Units and blocks are walked together, in document order,
with a monotone pointer: unit *i* is assigned to the first block at or after
the pointer whose normalised text contains it, and the pointer then rests on
that block rather than moving past it, because a hard-wrapped clause is
several units of one block. A unit that matches nothing within
`SEARCH_WINDOW` blocks of the pointer is assigned nothing and is reported in
`UnitLift.unassigned`, rather than being attached to whichever block happened
to be nearest.

**What "contains" means.** A unit is the document's own line, so it carries
the markup the reader stripped: ``"# Cloud Service Agreement"`` against a
heading whose text is ``"Cloud Service Agreement"``, ``"1.1 Access and Use."``
against a list item labelled ``1.1`` whose text starts ``"Access and Use."``.
Comparison is on `redlines.blocks`-free normalised text
(`benchmark.labels.normalise_text`) after leading markup -- heading hashes,
bullet and ordered-list markers, block-quote arrows, table pipes -- and a
leading copy of the candidate block's own label have been removed from the
unit. Containment is tested both ways round: the reader sometimes drops more
than the line does (inline HTML), and sometimes less.

Nothing here is fuzzy. A unit either lies inside a block's text or it does
not, and the units that lie inside nothing are counted and published rather
than guessed at -- an unassigned unit costs the baseline a vote, and hiding
that would be the exact thumb on the scale this module exists to keep off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from redlines.blocks import BlockKind
from redlines.processor import PARAGRAPH_MARKER, split_paragraphs

from .labels import LABELLED_KINDS, normalise_text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redlines.blocks import Block, BlockTree

__all__ = [
    "FLAT_ADDRESSABLE_KINDS",
    "SEARCH_WINDOW",
    "UnitLift",
    "flat_units",
    "token_unit_indices",
    "lift_units",
    "flat_addressable_addresses",
]

#: The labelled kinds the flat engine can address at all. `row` and `cell` are
#: excluded because 0.6 has no concept of a table: a markdown table is lines
#: like any other text, and crediting or blaming it for a row-level
#: correspondence would measure this module's cleverness rather than the
#: engine's. ADR-0034 asks for this column *beside* the all-blocks one, not
#: instead of it.
FLAT_ADDRESSABLE_KINDS: frozenset[BlockKind] = LABELLED_KINDS - {
    BlockKind.ROW,
    BlockKind.CELL,
}

#: How far ahead of the pointer a unit may look for its block. Large enough
#: that a table (whose rows the pointer walks past one line at a time) does not
#: strand the paragraph after it, small enough that a unit cannot be captured
#: by repetitive text on the far side of the document.
SEARCH_WINDOW: int = 40

# Leading markup a reader strips from a line but `split_paragraphs` does not:
# heading hashes, block-quote arrows, bullet markers, table pipes, and the
# ordered-list marker a markdown list item begins with.
_LEADING_MARKUP = re.compile(r"^(?:[#>|]+|[-*+](?=\s)|\(?[0-9]+[.)]|\(?[a-zA-Z][.)])\s*")


@dataclass(frozen=True, slots=True)
class UnitLift:
    """Which block each of a document's flat units belongs to.

    :param units: the flat units, in document order, exactly as
        `redlines.processor.split_paragraphs` produced them.
    :param addresses: one entry per unit -- the ADR-0029 address of the block
        it lifted to, or ``None`` for a unit that matched nothing.
    :param addressable: the addresses of every block the flat engine can
        address, in document order (`FLAT_ADDRESSABLE_KINDS`), whether or not
        a unit landed on it.
    """

    units: tuple[str, ...]
    addresses: tuple[str | None, ...]
    addressable: tuple[str, ...]

    @property
    def unassigned(self) -> int:
        """How many units lifted to no block at all."""
        return sum(1 for address in self.addresses if address is None)

    def address_for(self, unit: int) -> str | None:
        """Return the address unit ``unit`` lifted to, or ``None``.

        :param unit: an index into `units`. Out-of-range indices return
            ``None`` rather than raising: the token walk in
            `benchmark.baselines` can produce one at a document's edges.
        """
        if 0 <= unit < len(self.addresses):
            return self.addresses[unit]
        return None


def flat_units(text: str) -> tuple[str, ...]:
    """Return the 0.6 engine's own units for ``text``.

    A thin, named wrapper over `redlines.processor.split_paragraphs` so that
    every caller in the benchmark agrees about what a unit is and none of them
    re-splits the text with a rule of its own. The unit is a **line**, not a
    paragraph, despite the function's name: the pattern splits on any run of
    newlines, which is why the floor necessarily gets a whitespace-only rewrap
    wrong.

    :param text: the document.
    :return: its units, in order, each stripped of surrounding whitespace.
    """
    return tuple(split_paragraphs(text))


def token_unit_indices(tokens: Sequence[str]) -> tuple[int, ...]:
    """Map each normalised token to the index of the unit it sits in.

    `redlines.processor.WholeDocumentProcessor` diffs the token list of
    ``concatenate_paragraphs_and_add_chr_182(text)``, in which a lone
    `redlines.processor.PARAGRAPH_MARKER` token stands between two units. Unit
    indices are therefore the count of marker tokens strictly before a token.

    :param tokens: the whitespace-stripped tokens the processor compared.
    :return: one unit index per token; a marker token itself gets ``-1``,
        because it belongs to the boundary rather than to either side.
    """
    indices: list[int] = []
    unit = 0
    for token in tokens:
        if token == PARAGRAPH_MARKER:
            indices.append(-1)
            unit += 1
        else:
            indices.append(unit)
    return tuple(indices)


def flat_addressable_addresses(tree: BlockTree) -> tuple[str, ...]:
    """Return the addresses of the blocks the flat engine can address.

    :param tree: the tree to walk.
    :return: addresses in document order, of blocks in
        `FLAT_ADDRESSABLE_KINDS`.
    """
    return tuple(
        block.path for block in tree.walk() if block.kind in FLAT_ADDRESSABLE_KINDS
    )


def lift_units(text: str, tree: BlockTree) -> UnitLift:
    """Lift a document's flat units into its block addresses.

    :param text: the document exactly as the flat engine reads it.
    :param tree: the block tree the same document was read into.
    :return: the `UnitLift`, whose ``addresses`` is parallel to its ``units``.
    """
    units = flat_units(text)
    blocks: tuple[Block, ...] = tuple(
        block for block in tree.walk() if block.kind in FLAT_ADDRESSABLE_KINDS
    )
    texts = tuple(normalise_text(block.text) for block in blocks)
    labels = tuple(block.label or "" for block in blocks)

    addresses: list[str | None] = []
    pointer = 0
    for unit in units:
        found: int | None = None
        limit = min(len(blocks), pointer + SEARCH_WINDOW)
        for index in range(pointer, limit):
            if _contains(texts[index], unit, labels[index]):
                found = index
                break
        if found is None:
            addresses.append(None)
        else:
            addresses.append(blocks[found].path)
            pointer = found
    return UnitLift(
        units=units,
        addresses=tuple(addresses),
        addressable=tuple(block.path for block in blocks),
    )


def _contains(block_text: str, unit: str, label: str) -> bool:
    """Whether ``unit`` is this block's text, once the line's markup is off.

    :param block_text: the block's normalised text.
    :param unit: the raw unit.
    :param label: the block's label, stripped from the head of the unit when
        the line carries it and the block's text does not.
    :return: whether either string contains the other.
    """
    stripped = _strip_line_markup(unit, label)
    if not block_text:
        # A label-only block -- ``## Schedule 1``, whose whole line is its
        # label -- owns no text at all, so containment has nothing to test.
        # It is that block's unit exactly when the label is all the line was.
        return bool(label) and not stripped and normalise_text(unit) != ""
    if not stripped:
        return False
    return stripped in block_text or block_text in stripped


def _strip_line_markup(unit: str, label: str) -> str:
    """Return ``unit`` normalised, with leading markup and ``label`` removed."""
    text = normalise_text(unit)
    while True:
        if label and text.startswith(label):
            rest = text[len(label) :]
            if not rest or rest[0] in " .)":
                text = rest.lstrip(" .)")
                continue
        stripped = _LEADING_MARKUP.sub("", text, count=1)
        if stripped == text:
            return text
        text = stripped
