"""Tests for the move pass (#132, ADR-0009, ADR-0032).

A move is the only claim alignment makes that a user cannot check by reading
one place in one document, and it is the claim ADR-0009 says costs the most
trust when it is wrong. So these tests are written from both ends. Half of
them assert that a real move is found -- the sample pair's clause 7.5 moving
to 9.6 under both profiles, a whole subtree relocating, a clause crossing its
own siblings. The other half assert *silence*: an ambiguous text, a near-tie,
a block too short to identify, a container kind, an exhausted budget. Each of
those has a delete and an insert as its right answer, and the test says so.

Three of them are regressions rather than requirements. A prototype without
the structural table pairing, without the kind restriction and without the
token minimum reported thirteen of the sample pair's table cells as moves;
each failure was a confident wrong answer rather than a crash, which is
exactly the kind that needs a test rather than a review.

The similarity numbers quoted in the docstrings were measured under *both*
backends and agree to four places, so nothing here depends on whether the
``[fuzzy]`` extra is installed.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import sys
import time
from pathlib import Path

import pytest

from redlines.alignment import AlignedPair, Alignment, AlignmentConfig, align
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.similarity import RAPIDFUZZ_AVAILABLE

EXPECTED_DIR = Path(__file__).parent / "corpus" / "sample_pair" / "expected"

# Twelve tokens, and one substitution apart from each of its two rivals. Both
# backends score TARGET against NEAR_WINNER 0.9167 and against RUNNER_UP
# 0.8333: both clear the 0.80 threshold, and the 0.0834 between them is under
# the 0.10 tie margin.
TARGET = (
    "The Supplier shall deliver the Monthly Service Report within five Business Days."
)
NEAR_WINNER = (
    "The Supplier shall deliver the Monthly Service Report within seven Business Days."
)
RUNNER_UP = (
    "The Supplier shall deliver the Quarterly Service Report within seven "
    "Business Days."
)
UNRELATED = "The Customer may inspect the Supplier's records on reasonable notice."

# The clause that moves in most of the constructed cases: long enough to clear
# the eight-token minimum and distinctive enough to be unambiguous.
CLAUSE = (
    "Each party shall return or destroy all Confidential Information on "
    "termination of this agreement."
)


# --- helpers ---------------------------------------------------------------


def block(
    kind: str,
    text: str = "",
    *,
    label: str | None = None,
    role: str | None = None,
    children: tuple[Block, ...] = (),
) -> Block:
    """One block, with only the fields alignment is allowed to look at."""
    return Block(
        kind=BlockKind(kind), text=text, label=label, role=role, children=children
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


def two_sections(*, first: tuple[Block, ...], second: tuple[Block, ...]) -> BlockTree:
    """Two headed sections, which the exact pass pairs before anything moves."""
    return tree(section("7", *first), section("9", *second))


def moves(alignment: Alignment) -> list[tuple[str, str, str]]:
    """Every pair flagged ``moved``, as (source, test, pass), in source order."""
    return [
        (pair.source_path, pair.test_path, pair.matched_by)
        for pair in alignment.pairs
        if pair.moved
    ]


def matched(alignment: Alignment, source_path: str) -> AlignedPair:
    """The pair for ``source_path``, or a failure naming what was matched."""
    found = {pair.source_path: pair for pair in alignment.pairs}.get(source_path)
    assert found is not None, (
        f"{source_path} was not matched; deleted={alignment.deleted}"
    )
    return found


def load_sample(name: str) -> BlockTree:
    """One of the four frozen M1 trees for the sample pair."""
    return BlockTree.from_dict(json.loads((EXPECTED_DIR / name).read_text()))


@pytest.fixture(params=["markdown", "contract"])
def sample(request: pytest.FixtureRequest) -> tuple[BlockTree, BlockTree]:
    """The sample pair as read under one of the two profiles."""
    twin = request.param
    return load_sample(f"source.{twin}.json"), load_sample(f"test.{twin}.json")


# --- the sample pair -------------------------------------------------------


def test_the_sample_pairs_clause_moves_from_section_seven_to_section_nine(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """Change 2, the demo case #132 names, on both twins.

    One move, at confidence 1.0, because the clause's own text is unchanged
    and unique on both sides. Not a delete and an insert, and not two moves:
    the clause is one pair carrying both ADR-0029 addresses.
    """
    source, test = sample
    alignment = align(source, test)
    assert moves(alignment) == [
        (
            "/section[1]/section[7]/list_item[5]",
            "/section[1]/section[9]/list_item[6]",
            "move",
        )
    ]
    pair = matched(alignment, "/section[1]/section[7]/list_item[5]")
    assert pair.confidence == 1.0
    assert pair.renumbered is False  # a moved pair is not also a renumber


def test_the_sample_pairs_move_and_the_edit_inside_it_are_separable(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """CHANGES.md change 2: "the move and the edit are separable".

    The clause moved *and* its body was reworded. Because the move pass
    descends into the pair it just made, the body aligns inside the clause's
    new scope and comes out as an ordinary ``fuzzy`` match at 0.933 -- one
    move on the clause plus one edit on its child, rather than one
    indivisible event or a second move.
    """
    source, test = sample
    alignment = align(source, test)
    body = matched(alignment, "/section[1]/section[7]/list_item[5]/paragraph[1]")
    assert body.test_path == "/section[1]/section[9]/list_item[6]/paragraph[1]"
    assert body.matched_by == "fuzzy"
    assert body.moved is False  # its parents correspond: the parent is the move
    assert round(body.confidence, 3) == 0.933


def test_the_sample_pairs_move_leaves_the_other_changes_alone(
    sample: tuple[BlockTree, BlockTree],
) -> None:
    """The inserted clause and the deleted sub-clause are not moves.

    They are the two blocks most likely to be paired wrongly by a global
    search: both are leftovers, both are clauses, and both are in the same
    document. Measured, they score far below the 0.80 threshold, so the pass
    says nothing about either.
    """
    source, test = sample
    alignment = align(source, test)
    assert "/section[1]/section[5]/list_item[4]/list_item[3]" in alignment.deleted
    assert "/section[1]/section[3]/list_item[3]" in alignment.inserted


# --- the three prototype regressions ---------------------------------------


def test_a_table_is_paired_structurally_so_its_rows_never_become_moves() -> None:
    """Regression (a): the prototype that skipped structural pairing.

    With the table unpaired, its rows and cells are never compared, so every
    one of them is a leftover -- and thirteen of the sample pair's cells came
    out as moves. Here the table pairs, the shifted row pairs inside it, and
    the move pass has nothing to look at.
    """
    def row(*cells: str) -> Block:
        return block("row", children=tuple(block("cell", text=c) for c in cells))

    source = tree(
        block(
            "table",
            children=(
                row("Milestone", "Owner", "Date"),
                row("Go-live sign-off", "Supplier", "1 April"),
            ),
        )
    )
    test = tree(
        block(
            "table",
            children=(
                row("Milestone", "Owner", "Date"),
                row("Training day", "Customer", "20 March"),
                row("Go-live sign-off", "Supplier", "1 April"),
            ),
        )
    )
    alignment = align(source, test)
    assert matched(alignment, "/table[1]").matched_by == "structural"
    assert matched(alignment, "/table[1]/row[2]").test_path == "/table[1]/row[3]"
    assert alignment.pass_counts["move"] == 0
    assert moves(alignment) == []


def test_the_move_pass_never_reports_a_cell_a_row_or_a_section() -> None:
    """Regression (b): the kind restriction.

    Every leftover here is a container or part of one, and every one of them
    has an identical twin in the other document at a different address. Only
    the kinds ``move_kinds`` admits may be reported, so a relocated section
    surfaces as its *children* moving -- honest, and something the reader can
    check -- rather than as a claim about the section itself.
    """
    body = block("paragraph", CLAUSE)
    source = two_sections(
        first=(block("section", children=(body,)),),
        second=(),
    )
    test = two_sections(
        first=(),
        second=(block("section", children=(body,)),),
    )
    alignment = align(source, test)
    kinds = {
        source.block_at(path).kind.value for path, _, _ in moves(alignment)
    }
    assert kinds <= set(AlignmentConfig().move_kinds)
    assert kinds == {"paragraph"}
    assert "/section[1]/section[1]" in alignment.deleted  # the section itself
    assert "/section[2]/section[1]" in alignment.inserted


def test_a_block_shorter_than_the_token_minimum_is_never_a_move() -> None:
    """Regression (c): the token minimum.

    "Intentionally omitted." is unique in both documents and identical across
    them, so uniqueness alone would pair it. Three words is not enough text to
    identify a clause by, and Docxodus requires three for the same reason we
    require eight. Lowering the knob pairs it, which is what shows the
    minimum is what refused.
    """
    short = block("paragraph", "Intentionally omitted.")
    source = two_sections(first=(short,), second=())
    test = two_sections(first=(), second=(short,))
    assert moves(align(source, test)) == []
    assert align(source, test).deleted == ("/section[1]/paragraph[1]",)
    lenient = align(source, test, config=AlignmentConfig(move_min_tokens=2))
    assert moves(lenient) == [
        ("/section[1]/paragraph[1]", "/section[2]/paragraph[1]", "move")
    ]


# --- the exact stage: unique only ------------------------------------------


def test_a_text_unique_on_both_sides_moves_at_full_confidence() -> None:
    source = two_sections(first=(block("paragraph", CLAUSE),), second=())
    test = two_sections(first=(), second=(block("paragraph", CLAUSE),))
    alignment = align(source, test)
    pair = matched(alignment, "/section[1]/paragraph[1]")
    assert (pair.test_path, pair.matched_by, pair.confidence, pair.moved) == (
        "/section[2]/paragraph[1]",
        "move",
        1.0,
        True,
    )
    assert alignment.pass_counts["move"] == 1


def test_a_repeated_text_is_ambiguous_and_pairs_with_nothing() -> None:
    """The false-positive story in one test.

    Two leftovers on each side reading the same words. Any pairing is a
    guess, and three of the four ways of guessing are wrong, so the pass
    declines all four -- which is a delete and an insert per block.
    """
    boiler = block("paragraph", CLAUSE)
    source = two_sections(first=(boiler, boiler), second=())
    test = two_sections(first=(), second=(boiler, boiler))
    alignment = align(source, test)
    assert moves(alignment) == []
    assert alignment.deleted == (
        "/section[1]/paragraph[1]",
        "/section[1]/paragraph[2]",
    )
    assert alignment.inserted == (
        "/section[2]/paragraph[1]",
        "/section[2]/paragraph[2]",
    )


def test_a_text_that_is_unique_on_one_side_only_is_still_ambiguous() -> None:
    """One source block, two identical test blocks: which one did it become?

    Uniqueness is required on *both* sides, not on the side that happens to
    have one. Answering "the first" would be a coin toss dressed as a match.
    """
    boiler = block("paragraph", CLAUSE)
    source = two_sections(first=(boiler,), second=())
    test = two_sections(first=(), second=(boiler, boiler))
    assert moves(align(source, test)) == []


def test_a_move_never_crosses_a_kind_class() -> None:
    """A heading and a paragraph reading the same words are not the same block."""
    source = two_sections(first=(block("heading", CLAUSE),), second=())
    test = two_sections(first=(), second=(block("paragraph", CLAUSE),))
    assert moves(align(source, test)) == []


# --- the fuzzy stage: unique best only -------------------------------------


def test_an_edited_clause_that_changed_scope_moves_on_its_score() -> None:
    """A clause reworded on its way from section 7 to section 9.

    Its text changed, so the exact stage cannot see it; it scores 0.9167,
    which clears the 0.80 threshold, and it is the only candidate either way
    round. The confidence on the pair is that score, not 1.0 -- a move found
    by similarity says how similar, so a reviewer can argue with it.
    """
    source = two_sections(first=(block("paragraph", TARGET),), second=())
    test = two_sections(first=(), second=(block("paragraph", NEAR_WINNER),))
    alignment = align(source, test)
    pair = matched(alignment, "/section[1]/paragraph[1]")
    assert (pair.test_path, pair.matched_by, pair.moved) == (
        "/section[2]/paragraph[1]",
        "move",
        True,
    )
    assert round(pair.confidence, 4) == 0.9167


@pytest.mark.parametrize(
    "backend",
    [
        "difflib",
        pytest.param(
            "rapidfuzz",
            marks=pytest.mark.skipif(
                not RAPIDFUZZ_AVAILABLE, reason="the [fuzzy] extra is not installed"
            ),
        ),
    ],
)
def test_a_near_tie_is_not_a_move_however_high_both_candidates_score(
    backend: str,
) -> None:
    """Silence wins (#132's asymmetric gate), under either backend.

    Both candidates clear the 0.80 threshold -- 0.9167 and 0.8333, measured
    identically by difflib and by rapidfuzz -- and the 0.0834 between them is
    inside the 0.10 tie margin. A margin that narrow is not evidence about
    which clause moved, so nothing is reported: the two candidates are
    deletes and the block they might both be is an insert. Shrinking the
    margin to 0.05 pairs them, which is what shows the margin is what
    refused rather than the threshold.
    """
    config = AlignmentConfig(similarity=backend)
    source = two_sections(
        first=(block("paragraph", NEAR_WINNER), block("paragraph", RUNNER_UP)),
        second=(),
    )
    test = two_sections(first=(), second=(block("paragraph", TARGET),))
    alignment = align(source, test, config=config)
    assert alignment.backend == backend
    assert moves(alignment) == []
    assert alignment.inserted == ("/section[2]/paragraph[1]",)

    narrow = AlignmentConfig(similarity=backend, move_tie_margin=0.05)
    assert moves(align(source, test, config=narrow)) == [
        ("/section[1]/paragraph[1]", "/section[2]/paragraph[1]", "move")
    ]


def test_the_tie_margin_is_checked_from_both_ends() -> None:
    """The reading ADR-0032 leaves open, decided the quiet way (#132).

    The ADR states the rule over test blocks: best source candidate, by a
    margin. Read only that way, one source clause with two plausible
    destinations pairs confidently with whichever comes first, while two
    sources and one destination goes silent -- the same ambiguity answered
    two different ways depending on which document was called source. So the
    margin is checked from both ends, and this is the direction the literal
    reading would have got wrong.
    """
    source = two_sections(first=(block("paragraph", TARGET),), second=())
    test = two_sections(
        first=(),
        second=(block("paragraph", NEAR_WINNER), block("paragraph", RUNNER_UP)),
    )
    alignment = align(source, test)
    assert moves(alignment) == []
    assert alignment.deleted == ("/section[1]/paragraph[1]",)


def test_a_candidate_below_the_threshold_is_not_a_runner_up() -> None:
    """The margin is measured against the second-best *admissible* candidate.

    A block scoring 0.16 is not a rival for anything; if it counted as a
    runner-up it would still be 0.75 away, but the rule has to be stated or a
    corpus with one weak near-miss per clause would go silent everywhere.
    """
    source = two_sections(
        first=(block("paragraph", NEAR_WINNER), block("paragraph", UNRELATED)),
        second=(),
    )
    test = two_sections(first=(), second=(block("paragraph", TARGET),))
    assert moves(align(source, test)) == [
        ("/section[1]/paragraph[1]", "/section[2]/paragraph[1]", "move")
    ]
    assert "/section[1]/paragraph[2]" in align(source, test).deleted


def test_a_score_below_the_move_threshold_is_a_delete_and_an_insert() -> None:
    """0.60 is enough for an edit in place; a move has to clear 0.80."""
    source = two_sections(first=(block("paragraph", TARGET),), second=())
    test = two_sections(first=(), second=(block("paragraph", UNRELATED),))
    alignment = align(source, test)
    assert moves(alignment) == []
    assert alignment.deleted == ("/section[1]/paragraph[1]",)
    assert alignment.inserted == ("/section[2]/paragraph[1]",)


# --- a whole subtree -------------------------------------------------------


def test_a_moved_subtree_is_one_move_with_its_children_aligned_inside() -> None:
    """ADR-0032's reason for pushing move pairs back onto the descent queue.

    A clause with two sub-clauses moves from section 7 to section 9, and one
    sub-clause is edited on the way. The right answer is one move -- on the
    clause -- and two ordinary pairs inside it, because the sub-clauses did
    not move relative to their parent. Reporting three moves would be three
    times the noise for one event, and reporting the parent alone would lose
    the edit.
    """
    kept = block("list_item", CLAUSE, label="(a)")
    before = block("list_item", TARGET, label="(b)")
    after = block("list_item", NEAR_WINNER, label="(b)")
    head = "The Supplier shall comply with each of the following obligations."
    source = two_sections(
        first=(block("list_item", head, label="7.5", children=(kept, before)),),
        second=(),
    )
    test = two_sections(
        first=(),
        second=(block("list_item", head, label="9.6", children=(kept, after)),),
    )
    alignment = align(source, test)
    assert moves(alignment) == [
        ("/section[1]/list_item[1]", "/section[2]/list_item[1]", "move")
    ]
    assert alignment.pass_counts["move"] == 1
    inside = matched(alignment, "/section[1]/list_item[1]/list_item[1]")
    assert (inside.test_path, inside.matched_by) == (
        "/section[2]/list_item[1]/list_item[1]",
        "exact",
    )
    edited = matched(alignment, "/section[1]/list_item[1]/list_item[2]")
    assert edited.test_path == "/section[2]/list_item[1]/list_item[2]"
    assert edited.matched_by in {"label", "fuzzy"}
    assert round(edited.confidence, 4) == 0.9167
    assert alignment.deleted == () and alignment.inserted == ()


# --- crossings: the reordering the global search cannot see ----------------


def test_a_clause_that_crosses_its_own_siblings_is_a_move() -> None:
    """The intra-scope half of the rule (ADR-0032).

    Four clauses, all matched by ``exact`` in the right scope, with the first
    one now last. Three of them keep their order and are the longest
    increasing subsequence; the fourth crossed all three, and is the one
    reported. Classification, not a pass: ``pass_counts["move"]`` stays 0,
    because ``exact`` is what matched it and the record says so.
    """
    texts = [
        f"Clause {word} states an obligation that runs for the whole of the term."
        for word in ("alpha", "beta", "gamma", "delta")
    ]
    a, b, c, d = (block("paragraph", text) for text in texts)
    alignment = align(tree(a, b, c, d), tree(b, c, d, a))
    assert moves(alignment) == [("/paragraph[1]", "/paragraph[4]", "exact")]
    assert alignment.pass_counts["move"] == 0
    assert matched(alignment, "/paragraph[2]").moved is False


def test_siblings_that_keep_their_order_are_not_moves() -> None:
    """A block sliding down because something was inserted above it.

    The sample pair's "Go-live sign-off" row does exactly this. Its address
    changes and its order does not, and an address shift alone is never a
    change (ADR-0033).
    """
    a = block("paragraph", "Clause alpha states an obligation for the whole term.")
    b = block("paragraph", "Clause beta states another obligation for the term.")
    new = block("paragraph", "Clause gamma is entirely new to this agreement.")
    alignment = align(tree(a, b), tree(new, a, b))
    assert moves(alignment) == []
    assert matched(alignment, "/paragraph[1]").test_path == "/paragraph[2]"


def test_a_crossing_of_a_kind_move_kinds_excludes_is_not_reported() -> None:
    """``move_kinds`` says which kinds may be *reported*, not only searched.

    Two table rows swap. Reporting a row move would be a claim about a kind
    1.0 does not make claims about -- the same silence a relocated section
    gets -- so the rows pair and say nothing.
    """
    def row(*cells: str) -> Block:
        return block("row", children=tuple(block("cell", text=c) for c in cells))

    first, second = row("Alpha", "Supplier"), row("Beta", "Customer")
    alignment = align(
        tree(block("table", children=(first, second))),
        tree(block("table", children=(second, first))),
    )
    assert moves(alignment) == []
    assert matched(alignment, "/table[1]/row[1]").test_path == "/table[1]/row[2]"


def test_dropping_the_move_pass_drops_the_crossing_rule_too() -> None:
    """Both halves of "move" are the move pass; neither survives dropping it."""
    texts = [
        f"Clause {word} states an obligation that runs for the whole of the term."
        for word in ("alpha", "beta", "gamma", "delta")
    ]
    a, b, c, d = (block("paragraph", text) for text in texts)
    config = AlignmentConfig(
        passes=("exact", "label", "structural", "fuzzy", "positional")
    )
    alignment = align(tree(a, b, c, d), tree(b, c, d, a), config=config)
    assert moves(alignment) == []
    assert matched(alignment, "/paragraph[1]").test_path == "/paragraph[4]"


# --- the budget ------------------------------------------------------------


def test_an_exhausted_budget_reports_no_moves_and_says_that_it_stopped() -> None:
    """Degradation, and the flag that keeps it from being silent silence.

    With no budget at all the move pass cannot generate its first candidate,
    so the clause that moved falls through to a delete and an insert. That is
    the safe failure; what makes it honest is ``budget_exhausted``, which is
    the only thing telling a consumer "we stopped looking" apart from
    "nothing was there".
    """
    source = two_sections(first=(block("paragraph", CLAUSE),), second=())
    test = two_sections(first=(), second=(block("paragraph", CLAUSE),))
    spent = align(source, test, config=AlignmentConfig(max_comparisons=0))
    assert spent.budget_exhausted is True
    assert spent.pass_counts["move"] == 0
    assert moves(spent) == []
    assert spent.deleted == ("/section[1]/paragraph[1]",)

    afforded = align(source, test, config=AlignmentConfig(max_comparisons=1))
    assert afforded.budget_exhausted is False
    assert afforded.pass_counts["move"] == 1


def test_the_budget_is_one_counter_for_the_whole_run() -> None:
    """Not per pass: the fuzzy pass can spend what the move pass needed.

    ADR-0032 chose one run-wide counter over a per-site allowance because the
    guarantee people want is about the whole comparison. The consequence is
    visible here -- an unanchored gap early in the document exhausts the
    budget and the move later in it is never searched for -- and it is a
    consequence worth having a test for rather than discovering.
    """
    noise = tuple(
        block("paragraph", f"Filler paragraph number {index} of the schedule below.")
        for index in range(12)
    )
    rewritten = tuple(
        block("paragraph", f"Filler paragraph {index} of the schedule set out below.")
        for index in range(12)
    )
    source = tree(section("7", *noise, block("paragraph", CLAUSE)), section("9"))
    test = tree(section("7", *rewritten), section("9", block("paragraph", CLAUSE)))
    alignment = align(source, test, config=AlignmentConfig(max_comparisons=4))
    assert alignment.budget_exhausted is True
    assert moves(alignment) == []


# --- determinism (#135) ----------------------------------------------------


def _ambiguous_pair() -> tuple[BlockTree, BlockTree]:
    """Leftovers designed to make every stage of the move pass choose.

    Two exact candidates that are unique, two that are not, and a fuzzy field
    with one clear winner and one near-tie -- so a run that ordered its
    buckets or its proposals by anything seeded would not survive.
    """
    boiler = block("paragraph", CLAUSE)
    unique = block(
        "paragraph", "The Supplier shall maintain the Insurances at all times."
    )
    source = two_sections(
        first=(boiler, unique, boiler, block("paragraph", TARGET)),
        second=(),
    )
    test = two_sections(
        first=(),
        second=(
            block("paragraph", NEAR_WINNER),
            boiler,
            unique,
            boiler,
            block("paragraph", RUNNER_UP),
        ),
    )
    return source, test


def test_the_move_pass_gives_the_same_answer_twice() -> None:
    source, test = _ambiguous_pair()
    first = align(source, test).to_dict()
    second = align(source, test).to_dict()
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


_SCRIPT = """
import importlib.util, json, sys
spec = importlib.util.spec_from_file_location("_moves", {module!r})
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
from redlines.alignment import align
source, test = module._ambiguous_pair()
print(json.dumps(align(source, test).to_dict(), sort_keys=True))
"""


@pytest.mark.parametrize("seed", ["0", "1", "42", "12345", "random"])
def test_the_move_pass_does_not_depend_on_the_hash_seed(seed: str) -> None:
    """``str.__hash__`` is seeded, and the move pass buckets leftovers by text.

    Bucketing by text is exactly the shape that goes wrong quietly: a ``set``
    of texts iterates in an order that changes between processes, and the
    first candidate out of it wins. Dicts are insertion-ordered, so this
    passes -- but it passes for a reason a future edit can undo without
    failing any other test, which is why the seed matrix is here rather than
    only in #135's own module.
    """
    source, test = _ambiguous_pair()
    expected = json.dumps(align(source, test).to_dict(), sort_keys=True)
    completed = subprocess.run(
        [sys.executable, "-c", _SCRIPT.format(module=str(Path(__file__).resolve()))],
        env={**os.environ, "PYTHONHASHSEED": seed},
        capture_output=True,
        text=True,
        check=True,
        cwd=str(Path(__file__).resolve().parent.parent),
    )
    assert completed.stdout.strip() == expected


@pytest.mark.skipif(
    not RAPIDFUZZ_AVAILABLE, reason="the [fuzzy] extra is not installed"
)
def test_both_backends_report_the_same_moves_on_the_sample_pair() -> None:
    """The canary for the measured +0.027..+0.333 gap between the backends.

    Determinism is promised per configuration, so the two backends are
    allowed to differ -- but a move flipping between them on the sample pair
    would mean a near-threshold decision is sitting in the demo document, and
    that is worth knowing before the benchmark says so.
    """
    source = load_sample("source.markdown.json")
    test = load_sample("test.markdown.json")
    with_difflib = align(source, test, config=AlignmentConfig(similarity="difflib"))
    with_rapidfuzz = align(source, test, config=AlignmentConfig(similarity="rapidfuzz"))
    assert moves(with_difflib) == moves(with_rapidfuzz)


# --- cost (N2) -------------------------------------------------------------


@pytest.mark.slow
def test_the_move_pass_stays_inside_the_budget_on_a_field_of_leftovers() -> None:
    """The shape the move pass costs something on, which is not the ordinary one.

    The cross-scope search has no anchors to gap-scope against and no window
    to cap it -- there is no such thing as a rank position across two
    documents -- so ``max_comparisons`` is its only bound, and 1,500
    paragraphs that match nothing on the other side is what spends it. Two
    documents with nothing in common is a thing a user will do.

    It survives because `redlines.similarity.SequenceScorer` rejects almost
    every pair on `difflib`'s two cheap upper bounds before either backend
    computes anything: measured here at about 0.7 s for 562,500 pairs, which
    puts the full 2,000,000-comparison budget at roughly 2.5 s -- inside N2's
    five even on a slower machine than this one. The assertion is on the
    clock *and* on ``budget_exhausted``, because a run that got fast by
    giving up early would pass the first alone.
    """
    words = [f"w{index}" for index in range(4000)]

    def side(seed: int) -> BlockTree:
        rng = random.Random(seed)
        return tree(
            *(
                block("paragraph", " ".join(rng.sample(words, 12)) + ".")
                for _ in range(750)
            )
        )

    source, test = side(1), side(2)
    config = AlignmentConfig(positional_min_similarity=0.99)
    started = time.perf_counter()
    alignment = align(source, test, config=config)
    elapsed = time.perf_counter() - started
    assert elapsed < 5.0, f"the move pass took {elapsed:.2f}s over 750x750 leftovers"
    assert alignment.budget_exhausted is False
    assert moves(alignment) == []
