"""R27a recoverability: proof, not an export (#140).

The constraint #140 exists to prove: every inline edit must be recoverable as
*(address, old text, new text, surrounding context)*, with enough context to
anchor a text search -- because the 1.1 applier export (R26) hands an
external tool a ``target_text`` to search for, and PRD § 12 names ambiguity
on repeated text as the risk a text-addressed applier runs.

**Not an export.** #140 says so in as many words: "Not an export. Proof that
one is possible." `_inline_recoveries` below is one small, readable,
throwaway function -- it lives in this test module and nowhere else, so
`redlines` gains no new public surface a milestone that has not shaped it yet
would then have to maintain. When 1.1's `redlines/apply.py` needs this shape
for real, it is lifted from here, not imported from here.

Every element of the recovered tuple already exists on `redlines.changes`:

======== ====================================================================
element  where it comes from
======== ====================================================================
address  ``change.source_address`` (``change.test_address`` too, which
         differs from it exactly when an ancestor moved)
old      ``op.source_text``
new      ``op.test_text``
context  ``change.source_text`` -- the whole source block's own text
offsets  ``op.source_start``, ``op.source_end``, into that same context
======== ====================================================================

The six things this module asserts, against the PRD § 3a sample pair under
both of its profiles:

1. every inline op yields a complete tuple -- no missing address, ``old`` and
   ``new`` not both empty;
2. the offsets are literally true -- slicing the context by them reproduces
   ``old`` (and the test-side offsets reproduce ``new`` out of the test
   block's own text), which is where an off-by-one between token indices and
   characters would actually show up;
3. the address resolves in the source tree and the block found there carries
   exactly the context the tuple claims;
4. the context is unique among the source tree's own blocks, so a
   text-addressed search for it lands on one block and not two;
5. the repetitive schedule's one genuinely different item
   (`/section[4]/list_item[3]`, ADR-0010's stress case for a flat differ) is
   named directly, and its context is shown to occur exactly once in the raw
   ``source.md``/``source.txt`` bytes -- not only in the tree, because that
   is the harder claim adeu's own ambiguity risk is about;
6. the reverse direction: replaying every tuple's ``(source_start,
   source_end) -> new`` splice against its own block's context reconstructs
   that block's test-side text exactly, which is the proof the ops are
   *complete*, not merely individually recoverable.

**Why assertion 4 is a tree search and assertion 5 is a named special case,
not a blanket rule over raw bytes.** A block's ``text`` has its label
stripped and hard wraps rejoined (PRD § 6b) before alignment ever sees it, so
a raw ``str.count`` over the source file agrees with the tree for an
un-wrapped, unlabelled clause like the repetitive schedule's items, but would
undercount a hard-wrapped clause (the sample pair's clause 11.5) whose
context spans a line break in the file. Assertion 4 is therefore always
checked against the tree; assertion 5 checks the raw bytes too, exactly
because the repetitive schedule is the one place in the pair where that
stronger claim happens to hold.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from redlines.blocks import BlockTree
from redlines.comparison import Comparison, compare

CASE_DIR = Path(__file__).parent / "corpus" / "sample_pair"
EXPECTED_DIR = CASE_DIR / "expected"

REPETITIVE_SCHEDULE_ITEM = "/section[4]/list_item[3]"

PROFILES: tuple[str, ...] = ("contract", "markdown")


@dataclass(frozen=True, slots=True)
class Recovery:
    """One inline edit, recoverable as (address, old, new, context) plus offsets.

    Carries both sides' context and offsets (not only the source side the
    R27a table names) because assertion 2 checks the test side too, and
    assertion 6 needs the test side's actual text to compare a reconstruction
    against.
    """

    source_address: str
    test_address: str | None
    old: str
    new: str
    context: str
    source_start: int
    source_end: int
    test_context: str
    test_start: int
    test_end: int


def _inline_recoveries(comparison: Comparison) -> tuple[Recovery, ...]:
    """Every inline op in a comparison's change tree, as a `Recovery`.

    The one small function #140 asks to be proven possible, not shipped. An
    insert or a delete never carries an inline op (ADR-0033: the whole block
    is the change), so nothing here ever needs a ``None`` address.
    """
    recoveries: list[Recovery] = []
    for change in comparison.changes:
        if not change.inline:
            continue
        assert change.source_address is not None  # only insert lacks one, and it has no inline
        for op in change.inline:
            recoveries.append(
                Recovery(
                    source_address=change.source_address,
                    test_address=change.test_address,
                    old=op.source_text,
                    new=op.test_text,
                    context=change.source_text,
                    source_start=op.source_start,
                    source_end=op.source_end,
                    test_context=change.test_text,
                    test_start=op.test_start,
                    test_end=op.test_end,
                )
            )
    return tuple(recoveries)


def _splice(context: str, ops: list[tuple[int, int, str]]) -> str:
    """Replay ``(start, end) -> new`` splices against ``context``, in order.

    ``ops`` must be sorted by ``start`` and non-overlapping, which is true of
    one block's own inline ops (the leaf differ never emits overlapping runs).
    """
    result: list[str] = []
    cursor = 0
    for start, end, new in ops:
        result.append(context[cursor:start])
        result.append(new)
        cursor = end
    result.append(context[cursor:])
    return "".join(result)


def _comparison_for(profile_name: str) -> Comparison:
    """The sample pair's already-parsed trees for one profile, compared once."""
    stem = "contract" if profile_name == "contract" else "markdown"
    source = BlockTree.from_dict(
        json.loads((EXPECTED_DIR / f"source.{stem}.json").read_text(encoding="utf-8"))
    )
    test = BlockTree.from_dict(
        json.loads((EXPECTED_DIR / f"test.{stem}.json").read_text(encoding="utf-8"))
    )
    return compare(source, test)


_CACHE: dict[str, Comparison] = {}


def comparison_for(profile_name: str) -> Comparison:
    if profile_name not in _CACHE:
        _CACHE[profile_name] = _comparison_for(profile_name)
    return _CACHE[profile_name]


# --- 1. every inline op yields a complete tuple ------------------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_every_recovery_has_an_address_and_is_not_a_no_op(profile_name: str) -> None:
    recoveries = _inline_recoveries(comparison_for(profile_name))

    assert recoveries, "the sample pair must produce at least one inline edit"
    for recovery in recoveries:
        assert recovery.source_address
        assert recovery.old or recovery.new  # never both empty


# --- 2. the offsets are true -------------------------------------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_offsets_slice_back_to_old_and_new(profile_name: str) -> None:
    recoveries = _inline_recoveries(comparison_for(profile_name))

    for recovery in recoveries:
        assert recovery.context[recovery.source_start : recovery.source_end] == recovery.old
        assert (
            recovery.test_context[recovery.test_start : recovery.test_end] == recovery.new
        )


# --- 3. the address resolves and agrees with the context ---------------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_source_address_resolves_to_a_block_with_that_context(
    profile_name: str,
) -> None:
    result = comparison_for(profile_name)
    recoveries = _inline_recoveries(result)

    for recovery in recoveries:
        assert result.source.block_at(recovery.source_address).text == recovery.context


# --- 4. the context is unique among the source tree's own blocks ------------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_context_is_unique_in_the_source_tree(profile_name: str) -> None:
    result = comparison_for(profile_name)
    recoveries = _inline_recoveries(result)
    all_texts = [block.text for block in result.source.walk()]

    for recovery in recoveries:
        assert all_texts.count(recovery.context) == 1


# --- 5. the repetitive schedule, named, and against the raw bytes -----------


@pytest.mark.parametrize("profile_name", PROFILES)
def test_the_repetitive_schedules_one_edited_item_is_recovered(
    profile_name: str,
) -> None:
    """Schedule 2 is eight near-identical service-level clauses (ADR-0010's
    stress case for a flat differ); exactly one, `/section[4]/list_item[3]`,
    was actually edited, and R27a must recover it by name."""
    recoveries = _inline_recoveries(comparison_for(profile_name))
    for_item = [r for r in recoveries if r.source_address == REPETITIVE_SCHEDULE_ITEM]

    assert for_item, f"no inline edit was recovered for {REPETITIVE_SCHEDULE_ITEM}"


@pytest.mark.parametrize("raw_name", ["source.md", "source.txt"])
def test_the_repetitive_schedule_items_context_is_unique_in_the_raw_file(
    raw_name: str,
) -> None:
    """The harder claim: not just unique in the tree, but findable by a plain
    text search over the file redlines read -- which is the shape adeu's own
    ambiguity risk (PRD § 12) is actually about."""
    profile_name = "markdown" if raw_name.endswith(".md") else "contract"
    recoveries = _inline_recoveries(comparison_for(profile_name))
    for_item = next(
        r for r in recoveries if r.source_address == REPETITIVE_SCHEDULE_ITEM
    )
    raw = (CASE_DIR / raw_name).read_text(encoding="utf-8")

    assert raw.count(for_item.context) == 1


# --- 6. the reverse direction: replaying the ops reconstructs the test text --


@pytest.mark.parametrize("profile_name", PROFILES)
def test_replaying_every_blocks_ops_reconstructs_its_test_text(
    profile_name: str,
) -> None:
    """Not just recoverable one op at a time -- complete: every op inside a
    block, replayed together in order, rebuilds that block's actual test
    text out of nothing but its source text and the ops."""
    result = comparison_for(profile_name)

    for change in result.changes:
        if not change.inline:
            continue
        ops = [(op.source_start, op.source_end, op.test_text) for op in change.inline]
        reconstructed = _splice(change.source_text, ops)
        assert reconstructed == change.test_text
