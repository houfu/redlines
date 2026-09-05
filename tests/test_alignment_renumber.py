"""Tests for renumbering (#133, ADR-0009, ADR-0032).

Renumbering is not a search of its own: it falls straight out of the record
`align()` already produces, and only because ``exact`` runs before ``label``
(#131). A matched pair whose parents correspond and whose labels differ is a
renumber; `AlignedPair` says so on the ``renumbered`` field, and the old and
new labels are the ones already sitting on the two blocks the pair names --
``source.block_at(pair.source_path).label`` and
``test.block_at(pair.test_path).label`` -- so the pass record exposes them
without carrying a copy of its own that could drift from the tree.

Two things this file pins that #131's own tests do not: that a *cascade* of
renumbers -- several clauses shifting down together because one was inserted
above them -- comes out as one renumber per clause rather than one event, and
that the cross-reference block which follows the cascade is a ``modify`` in
the pass record's terms (matched, not renumbered itself, because its own
label is unchanged) even though the text it carries names the old label.
Resolving that reference is #136's job; what belongs here is that alignment
does not lose the pair the resolution needs.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from redlines.alignment import AlignedPair, Alignment, AlignmentConfig, align
from redlines.blocks import Block, BlockKind, BlockTree, Span

EXPECTED_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"


# --- helpers ---------------------------------------------------------------


def block(
    kind: str,
    text: str = "",
    *,
    label: str | None = None,
    role: str | None = None,
    spans: tuple[Span, ...] = (),
    children: tuple[Block, ...] = (),
) -> Block:
    """One block, with only the fields alignment is allowed to look at."""
    return Block(
        kind=BlockKind(kind),
        text=text,
        label=label,
        role=role,
        spans=spans,
        children=children,
    )


def tree(*children: Block) -> BlockTree:
    """Wrap children in a ``document`` root and address the result."""
    return BlockTree.build(block("document", children=children))


def section(label: str, *children: Block) -> Block:
    """A section with a heading, so ``exact`` pairs it and the descent goes in."""
    return block(
        "section",
        children=(block("heading", f"Section {label}", label=label), *children),
    )


def pairs_by_source(alignment: Alignment) -> dict[str, AlignedPair]:
    return {pair.source_path: pair for pair in alignment.pairs}


def matched(alignment: Alignment, source_path: str) -> AlignedPair:
    found = pairs_by_source(alignment).get(source_path)
    assert found is not None, (
        f"{source_path} was not matched; deleted={alignment.deleted}"
    )
    return found


def labels_of(
    source: BlockTree, test: BlockTree, pair: AlignedPair
) -> tuple[str | None, str | None]:
    """The old and new labels a renumbered pair carries, read off the trees."""
    return (
        source.block_at(pair.source_path).label,
        test.block_at(pair.test_path).label,
    )


def load_sample(name: str) -> BlockTree:
    return BlockTree.from_dict(json.loads((EXPECTED_DIR / name).read_text()))


@pytest.fixture(params=["markdown", "contract"])
def sample(request: pytest.FixtureRequest) -> tuple[BlockTree, BlockTree]:
    twin = request.param
    return load_sample(f"source.{twin}.json"), load_sample(f"test.{twin}.json")


# --- the sample pair: old and new labels, exposed -------------------------


def test_the_sample_pairs_renumbers_expose_their_old_and_new_labels(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Change 3 (PRD § 3a): the inserted clause renumbers the two below it.

    Both pairs are ``renumbered``, both are matched by ``exact`` -- their text
    is byte-identical, only the label moved -- and reading the label off each
    side of the pair gives exactly the old-to-new mapping the sample pair
    documents.
    """
    source, test = sample
    alignment = align(source, test)
    renumbered = [pair for pair in alignment.pairs if pair.renumbered]
    mapping = [labels_of(source, test, pair) for pair in renumbered]
    assert mapping == [("3.3", "3.4"), ("3.4", "3.5")]
    assert all(pair.matched_by == "exact" for pair in renumbered)
    assert all(pair.moved is False for pair in renumbered)


def test_the_sample_pairs_cross_reference_clause_is_a_modify_not_a_renumber(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Change 4: the cross-reference block keeps its own label.

    ``/section[1]/section[9]/list_item[2]`` is not itself renumbered -- its
    label is unchanged -- it is a ``label`` match on reworded text that
    happens to name the label ``3.3 -> 3.4`` shifted underneath it. Resolving
    the reference span is #136's job; what alignment owes it is that the pair
    survives with both addresses intact.
    """
    source, test = sample
    alignment = align(source, test)
    pair = matched(alignment, "/section[1]/section[9]/list_item[2]")
    assert pair.renumbered is False
    assert pair.matched_by == "label"
    old_label, new_label = labels_of(source, test, pair)
    assert old_label == new_label  # its own label never moved


# --- a renumber survives an edit to the same clause -------------------------


def test_a_renumbered_and_edited_clause_is_still_one_pair() -> None:
    """#133's central claim: renumbering and editing do not split a clause.

    With ``label`` and ``fuzzy`` both available the pair is found by
    ``label``; even with only the mandatory passes left, the shared label
    still carries it to one pair -- never a delete plus an insert -- because
    the label is not part of the diffed text (ADR-0032's ``Block.text``
    excludes the label).
    """
    source = tree(block("list_item", "The term is thirty days.", label="7.1"))
    test = tree(block("list_item", "The term is sixty days.", label="7.2"))

    default = matched(align(source, test), "/list_item[1]")
    assert default.renumbered is True
    assert default.test_path == "/list_item[1]"
    assert default.confidence < 1.0

    mandatory_only = AlignmentConfig(passes=("exact", "structural", "positional"))
    fallback = matched(align(source, test, config=mandatory_only), "/list_item[1]")
    assert fallback.renumbered is True
    assert fallback.test_path == "/list_item[1]"


# --- a synthetic cascade with a cross-reference -----------------------------


def _cascade_document() -> tuple[BlockTree, BlockTree]:
    """Three clauses in a section, one clause inserted at the top of them.

    Every clause below the insertion point shifts down by one label, and a
    fourth clause elsewhere carries a ``cross_reference`` span naming the
    clause that used to be ``3.2`` -- text that does not change, only what it
    is a cross-reference *to* changes underneath it. This is the shape #133
    calls out by name: "a cross-reference is updated to follow."
    """
    reference_text = "See the confidentiality obligations in clause 3.2."
    reference_start = reference_text.index("3.2")
    reference_end = reference_start + len("3.2")

    def cross_reference_clause(*, value: str) -> Block:
        return block(
            "list_item",
            reference_text,
            label="9.1",
            spans=(
                Span(
                    type="cross_reference",
                    start=reference_start,
                    end=reference_end,
                    value=value,
                ),
            ),
        )

    source = tree(
        section(
            "3",
            block("list_item", "Confidentiality obligations apply.", label="3.1"),
            block("list_item", "Return all materials on termination.", label="3.2"),
            block("list_item", "Survives expiry of the agreement.", label="3.3"),
        ),
        section("9", cross_reference_clause(value="3.2")),
    )
    test = tree(
        section(
            "3",
            block("list_item", "A new definitions clause.", label="3.1"),
            block("list_item", "Confidentiality obligations apply.", label="3.2"),
            block("list_item", "Return all materials on termination.", label="3.3"),
            block("list_item", "Survives expiry of the agreement.", label="3.4"),
        ),
        section("9", cross_reference_clause(value="3.3")),
    )
    return source, test


def test_a_cascade_of_renumbers_is_one_pair_per_clause() -> None:
    """Inserting one clause renumbers every clause below it, individually.

    Each of the two untouched clauses (byte-identical text) is matched by
    ``exact`` and reported as ``renumbered``; the newly inserted clause is an
    insert, never mistaken for a renumber of anything.
    """
    source, test = _cascade_document()
    alignment = align(source, test)

    obligations = matched(alignment, "/section[1]/list_item[1]")
    assert labels_of(source, test, obligations) == ("3.1", "3.2")
    assert obligations.renumbered is True
    assert obligations.matched_by == "exact"

    returns = matched(alignment, "/section[1]/list_item[2]")
    assert labels_of(source, test, returns) == ("3.2", "3.3")
    assert returns.renumbered is True
    assert returns.matched_by == "exact"

    survives = matched(alignment, "/section[1]/list_item[3]")
    assert labels_of(source, test, survives) == ("3.3", "3.4")
    assert survives.renumbered is True

    assert alignment.inserted == ("/section[1]/list_item[1]",)
    assert alignment.deleted == ()


def test_the_cross_reference_clause_that_follows_the_cascade_is_one_pair() -> None:
    """The clause naming the shifted label is matched, and not itself renumbered.

    Its own label (``9.1``) never moves, so ``renumbered`` is ``False``; its
    text is unchanged, so it is matched by ``exact`` too -- alignment's whole
    job here is to keep the pair alive so #136 can see that the span's
    *value* changed underneath unchanged surrounding text.
    """
    source, test = _cascade_document()
    alignment = align(source, test)
    pair = matched(alignment, "/section[2]/list_item[1]")
    assert pair.test_path == "/section[2]/list_item[1]"
    assert pair.renumbered is False
    assert pair.matched_by == "exact"

    old_value = source.block_at(pair.source_path).spans[0].value
    new_value = test.block_at(pair.test_path).spans[0].value
    assert (old_value, new_value) == ("3.2", "3.3")
