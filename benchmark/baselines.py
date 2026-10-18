"""The flat 0.6 engine, as the floor every 1.0 number is read against (N-7, ADR-0034).

ADR-0021 asks for "flat redlines 0.6 as the floor", and the honest version of
that is harder than it sounds. 0.6 has no block model, no addresses and no
opinion about structure: it splits a document on runs of newlines, glues the
lines back together with a ``¶`` token between them, and runs one
`difflib.SequenceMatcher` over the whole thing. It never says "clause 3.3
became clause 3.4". Getting a correspondence set out of it at all means
deciding what its opcodes *imply* about which line went where -- and every one
of those decisions is a place the floor could be quietly flattered or hobbled.

So there are exactly two decisions, they are both written down, and they are
both restated in ``benchmark/REPORT.md``:

1. **Token opcodes to unit pairs.** Every ``equal`` opcode pairs its tokens
   one for one, and each paired token casts a vote for the pair of units its
   two tokens sit in. Every ``replace`` opcode pairs the units it spans by
   relative order -- the first source unit with the first test unit, and so on
   until one side runs out -- and each such pairing casts one vote. A source
   unit takes the test unit with the most votes; ties go to the **smallest
   test unit index**. ``insert`` and ``delete`` opcodes pair nothing, which is
   the whole of what 0.6 knows about insertion and deletion.
2. **Unit pairs to block pairs.** Units are lifted to addresses by
   `benchmark.units`, and a source block takes the **plurality** of its units'
   target blocks, ties broken by the **earliest test block in document order**.

Both rules are generous to the floor rather than mean to it. Voting lets one
strongly-matched line carry a block whose other lines drifted; relative-order
pairing inside a ``replace`` gives 0.6 credit for correspondences it never
states. What it still cannot do is say that a clause *moved* or that a label
*changed*, so its move recall and its renumber recall are ``0.0`` by
construction -- printed as ``0.0``, never as a blank, because that cell is the
argument for the whole milestone.

**This module must never import `redlines.redlines.Redlines`.**
[ADR-0003](../docs/adr/0003-compatibility-facade.md) has M3 reimplement that
class over the new core, so a baseline that went through the facade would stop
being the 0.6 baseline on the day the facade landed, and the report would be
comparing the new engine against itself. It calls
`redlines.processor.WholeDocumentProcessor` directly, which is the 0.6
algorithm and nothing else, and ``tests/test_benchmark_score.py`` asserts the
prohibition so the substitution cannot happen quietly.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

from redlines.processor import WholeDocumentProcessor

from .units import lift_units, token_unit_indices

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redlines.blocks import BlockTree

__all__ = [
    "baseline_unit_pairs",
    "baseline_pairs",
]


def baseline_unit_pairs(source_text: str, test_text: str) -> tuple[tuple[int, int], ...]:
    """Pair the two documents' flat units, the only way 0.6's opcodes allow.

    :param source_text: the earlier document, exactly as 0.6 would read it.
    :param test_text: the later one.
    :return: ``(source unit index, test unit index)`` pairs, one at most per
        source unit, in source unit order.
    """
    processor = WholeDocumentProcessor(autojunk=False)
    operations = processor.process(source_text, test_text)
    if not operations:
        return ()

    source_tokens = [token.strip() for token in operations[0].source_chunk.text]
    test_tokens = [token.strip() for token in operations[0].test_chunk.text]
    source_units = token_unit_indices(source_tokens)
    test_units = token_unit_indices(test_tokens)

    votes: dict[int, Counter[int]] = {}
    for operation in operations:
        tag, i1, i2, j1, j2 = operation.opcodes
        if tag == "equal":
            for offset in range(min(i2 - i1, j2 - j1)):
                left = source_units[i1 + offset]
                right = test_units[j1 + offset]
                if left >= 0 and right >= 0:
                    votes.setdefault(left, Counter())[right] += 1
        elif tag == "replace":
            left_span = _span_units(source_units, i1, i2)
            right_span = _span_units(test_units, j1, j2)
            for left, right in zip(left_span, right_span):
                votes.setdefault(left, Counter())[right] += 1

    pairs: list[tuple[int, int]] = []
    for unit in sorted(votes):
        counts = votes[unit]
        # Highest vote count, then the smallest test unit index. Both halves
        # stated, because `Counter.most_common` breaks ties by insertion order
        # and insertion order here is opcode order, which is not a rule anyone
        # could check.
        best = min(counts, key=lambda target: (-counts[target], target))
        pairs.append((unit, best))
    return tuple(pairs)


def baseline_pairs(
    source_text: str,
    test_text: str,
    *,
    source_tree: BlockTree,
    test_tree: BlockTree,
) -> tuple[tuple[str, str], ...]:
    """Lift `baseline_unit_pairs` into the label address space.

    :param source_text: the earlier document.
    :param test_text: the later one.
    :param source_tree: the same source document, read into blocks.
    :param test_tree: the same for the test document.
    :return: ``(source address, test address)`` pairs, one at most per source
        block, in source document order.
    """
    source_lift = lift_units(source_text, source_tree)
    test_lift = lift_units(test_text, test_tree)
    order = {address: index for index, address in enumerate(test_lift.addressable)}

    votes: dict[str, Counter[str]] = {}
    for source_unit, test_unit in baseline_unit_pairs(source_text, test_text):
        source_address = source_lift.address_for(source_unit)
        test_address = test_lift.address_for(test_unit)
        if source_address is None or test_address is None:
            # A unit the flat engine paired but that lifts to no block -- a
            # table line, most often. Dropped rather than guessed at.
            continue
        votes.setdefault(source_address, Counter())[test_address] += 1

    pairs: list[tuple[str, str]] = []
    for address in source_lift.addressable:
        counts = votes.get(address)
        if not counts:
            continue
        best = min(counts, key=lambda target: (-counts[target], order.get(target, 0)))
        pairs.append((address, best))
    return tuple(pairs)


def _span_units(units: Sequence[int], start: int, stop: int) -> tuple[int, ...]:
    """Return the distinct unit indices a token span covers, in order."""
    seen: list[int] = []
    for index in range(start, stop):
        unit = units[index]
        if unit >= 0 and (not seen or seen[-1] != unit):
            seen.append(unit)
    return tuple(seen)
