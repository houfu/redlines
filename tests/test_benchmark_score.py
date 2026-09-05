"""Toy labels with known answers, for every number the benchmark publishes (#143, ADR-0034).

A metric cannot be revised after publication, so it has to be tested against
answers worked out by hand rather than against whatever the engine happens to
say. Every test here builds its ground truth and its "engine output" itself:
the label file is constructed from `benchmark.labels`'s dataclasses, and the
`redlines.comparison.Comparison` is assembled from a hand-written
`redlines.alignment.Alignment` and `redlines.changes.ChangeTree` rather than
produced by `redlines.comparison.compare`. That is deliberate and is the whole
point of the module. If these tests ran the aligner, a change in alignment
would move both the answer and the expectation together and the metric could
drift without a single test failing.

The trees are real, though -- both sides of ``tests/corpus/benchmark_labels/
simple/`` read through `redlines.pipeline.read_document`, the same fixture the
label-format tests use, so addresses and block kinds are what a reader actually
produces. The pair is small enough to enumerate: nine labelled source blocks,
nine labelled test blocks, one insertion (``1.3``) and one deletion (``3.2``).

`benchmark.baselines` and `benchmark.units` are tested against the same
fixture, including the prohibition that keeps the 0.6 floor from quietly
becoming the M3 facade.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from redlines.alignment import PASS_NAMES, AlignedPair, Alignment, AlignmentConfig
from redlines.blocks import ROOT_PATH, BlockKind, BlockTree
from redlines.changes import Change, ChangeKind, ChangeTree
from redlines.comparison import Comparison, ComparisonConfig
from redlines.pipeline import read_document

from benchmark.baselines import baseline_pairs, baseline_unit_pairs
from benchmark.labels import (
    Correspondence,
    DeletedEntry,
    InsertedEntry,
    LabelFile,
    MergeEntry,
    MoveVerdict,
    Provenance,
    Review,
    Side,
    SplitEntry,
    UnscoredRegion,
)
from benchmark.report import render_report
from benchmark.score import (
    DROPPABLE_PASSES,
    LinkCounts,
    PairScore,
    PassCounts,
    RoleCounts,
    SetCounts,
    aggregate,
    pass_table,
    role_counts,
    score_baseline_pair,
    score_engine_pair,
    truth_for,
)
from benchmark.units import FLAT_ADDRESSABLE_KINDS, flat_units, lift_units

FIXTURE = Path(__file__).parent / "corpus" / "benchmark_labels" / "simple"

TITLE = "/section[1]/heading[1]"
DEFINITIONS = "/section[1]/section[1]/heading[1]"
CLAUSE_1_1 = "/section[1]/section[1]/list_item[1]"
CLAUSE_1_2 = "/section[1]/section[1]/list_item[2]"
INSERTED = "/section[1]/section[1]/list_item[3]"
TERM = "/section[1]/section[2]/heading[1]"
TERM_BODY = "/section[1]/section[2]/paragraph[1]"
CONFIDENTIALITY = "/section[1]/section[3]/heading[1]"
CLAUSE_3_1 = "/section[1]/section[3]/list_item[1]"
DELETED = "/section[1]/section[3]/list_item[2]"

#: The eight correspondences the fixture's committed labels state, as the
#: ``(source, test)`` pairs the metric consumes.
LINKS: tuple[tuple[str, str], ...] = (
    (TITLE, TITLE),
    (DEFINITIONS, DEFINITIONS),
    (CLAUSE_1_1, CLAUSE_1_1),
    (CLAUSE_1_2, CLAUSE_1_2),
    (TERM, TERM),
    (TERM_BODY, TERM_BODY),
    (CONFIDENTIALITY, CONFIDENTIALITY),
    (CLAUSE_3_1, CLAUSE_3_1),
)


@pytest.fixture(scope="module")
def trees() -> tuple[BlockTree, BlockTree]:
    """The fixture pair, read the way a real pair is read."""
    return (
        read_document(
            (FIXTURE / "source.txt").read_text(encoding="utf-8"),
            format="text",
            profile="contract",
        ),
        read_document(
            (FIXTURE / "test.txt").read_text(encoding="utf-8"),
            format="text",
            profile="contract",
        ),
    )


def _row(
    source: str,
    test: str,
    *,
    kind: str = "same",
    source_label: str | None = None,
    test_label: str | None = None,
    status: str = "confirmed",
) -> Correspondence:
    """One labelled correspondence. Digests are not verified by the metric."""
    return Correspondence(
        source=source,
        test=test,
        kind=kind,
        source_digest="0" * 16,
        test_digest="0" * 16,
        status=status,
        source_label=source_label,
        test_label=test_label,
    )


def _labels(
    *,
    correspondences: tuple[Correspondence, ...] | None = None,
    inserted: tuple[InsertedEntry, ...] = (
        InsertedEntry(test=INSERTED, test_digest="0" * 16, status="confirmed"),
    ),
    deleted: tuple[DeletedEntry, ...] = (
        DeletedEntry(source=DELETED, source_digest="0" * 16, status="confirmed"),
    ),
    splits: tuple[SplitEntry, ...] = (),
    merges: tuple[MergeEntry, ...] = (),
    unscored: tuple[UnscoredRegion, ...] = (),
    move_verdicts: tuple[MoveVerdict, ...] = (),
    review: Review | None = None,
) -> LabelFile:
    """A label file over the fixture pair, defaulting to its committed truth."""
    rows = (
        correspondences
        if correspondences is not None
        else tuple(_row(source, test) for source, test in LINKS)
    )
    side = Side(file="source.txt", format="text", profile="contract", sha256="0" * 64)
    return LabelFile(
        pair="toy",
        source=side,
        test=Side(
            file="test.txt", format="text", profile="contract", sha256="1" * 64
        ),
        provenance=Provenance(kind="hand", origin="tests/test_benchmark_score.py"),
        correspondences=rows,
        inserted=inserted,
        deleted=deleted,
        splits=splits,
        merges=merges,
        unscored=unscored,
        review=review,
        move_verdicts=move_verdicts,
    )


def _comparison(
    trees: tuple[BlockTree, BlockTree],
    *,
    pairs: tuple[AlignedPair, ...],
    changes: tuple[Change, ...] = (),
    pass_counts: dict[str, int] | None = None,
    config: AlignmentConfig | None = None,
) -> Comparison:
    """Assemble a `Comparison` by hand, so the metric is tested and not the engine."""
    source, test = trees
    alignment_config = config or AlignmentConfig(similarity="difflib")
    counts = pass_counts or {}
    return Comparison(
        source=source,
        test=test,
        alignment=Alignment(
            pairs=pairs,
            inserted=(),
            deleted=(),
            config=alignment_config,
            backend="difflib",
            pass_counts=counts,
        ),
        changes=ChangeTree(changes=changes),
        config=ComparisonConfig(
            source_format="text",
            test_format="text",
            profile="contract",
            alignment=alignment_config,
            similarity="difflib",
            processor="WholeDocumentProcessor",
        ),
    )


def _aligned(
    reported: tuple[tuple[str, str], ...], *, matched_by: str = "exact"
) -> tuple[AlignedPair, ...]:
    """Turn bare address pairs into `AlignedPair`s from one pass."""
    return tuple(
        AlignedPair(
            source_path=source,
            test_path=test,
            matched_by=matched_by,
            confidence=1.0,
        )
        for source, test in reported
    )


def _score(
    trees: tuple[BlockTree, BlockTree],
    reported: tuple[tuple[str, str], ...],
    *,
    labels: LabelFile | None = None,
    changes: tuple[Change, ...] = (),
    matched_by: str = "exact",
    pass_counts: dict[str, int] | None = None,
    passes: tuple[PassCounts, ...] = (),
) -> PairScore:
    """Score a hand-written engine answer against hand-written labels."""
    source, test = trees
    return score_engine_pair(
        pair="toy",
        tier="hand",
        labels=labels or _labels(),
        comparison=_comparison(
            trees,
            pairs=_aligned(reported, matched_by=matched_by),
            changes=changes,
            pass_counts=pass_counts,
        ),
        source_tree=source,
        test_tree=test,
        passes=passes,
    )


# --- the ground truth -------------------------------------------------------


def test_truth_for_reads_every_set_the_labels_state() -> None:
    """`truth_for` is the one place a label file becomes sets; it must lose nothing."""
    labels = _labels(
        correspondences=(
            _row(TITLE, TITLE),
            _row(CLAUSE_1_1, CLAUSE_1_2, kind="move", source_label="1.1", test_label="1.2"),
            _row(CLAUSE_3_1, CLAUSE_3_1, kind="renumber", source_label="3.1", test_label="2.1"),
        ),
        splits=(
            SplitEntry(
                source=TERM_BODY,
                tests=(TERM_BODY,),
                source_digest="0" * 16,
                test_digests=("0" * 16,),
                status="confirmed",
            ),
        ),
        merges=(
            MergeEntry(
                sources=(TERM,),
                test=TERM,
                source_digests=("0" * 16,),
                test_digest="0" * 16,
                status="confirmed",
            ),
        ),
        unscored=(
            UnscoredRegion(region=DEFINITIONS, side="both", reason="a toy region"),
        ),
    )
    truth = truth_for(labels)

    assert truth.links == {
        (TITLE, TITLE),
        (CLAUSE_1_1, CLAUSE_1_2),
        (CLAUSE_3_1, CLAUSE_3_1),
    }
    assert truth.moves == {(CLAUSE_1_1, CLAUSE_1_2)}
    assert truth.renumbers == {
        (CLAUSE_1_1, CLAUSE_1_2, "1.1", "1.2"),
        (CLAUSE_3_1, CLAUSE_3_1, "3.1", "2.1"),
    }
    assert truth.inserted == {INSERTED}
    assert truth.deleted == {DELETED}
    assert truth.excluded_source == {TERM_BODY, TERM, DEFINITIONS}
    assert truth.excluded_test == {TERM_BODY, TERM, DEFINITIONS}
    assert (truth.skipped_splits, truth.skipped_merges) == (1, 1)


def test_a_moved_and_relabelled_row_feeds_the_move_and_the_renumber_metric() -> None:
    """ADR-0034: one row of ground truth, two metrics -- `kind: move` plus two labels."""
    truth = truth_for(
        _labels(
            correspondences=(
                _row(
                    CLAUSE_1_1,
                    CLAUSE_1_2,
                    kind="move",
                    source_label="1.1",
                    test_label="1.2",
                ),
            )
        )
    )
    assert truth.moves == {(CLAUSE_1_1, CLAUSE_1_2)}
    assert truth.renumbers == {(CLAUSE_1_1, CLAUSE_1_2, "1.1", "1.2")}


# --- the correspondence metric ----------------------------------------------


def test_a_perfect_answer_scores_one(trees: tuple[BlockTree, BlockTree]) -> None:
    """Eight labelled links, eight reported, all right."""
    score = _score(trees, LINKS)
    assert score.links == LinkCounts(reported=8, truth=8, hits=8, spurious=0)
    assert (score.links.precision, score.links.recall, score.links.f1) == (1.0, 1.0, 1.0)


def test_precision_recall_and_f1_are_the_links_only_ratios(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Six right and two wrong out of eight labelled: 0.75 each way, so F1 is 0.75."""
    reported = (
        *LINKS[:6],
        (CONFIDENTIALITY, CLAUSE_1_1),  # wrong counterpart
        (CLAUSE_3_1, CLAUSE_1_2),  # wrong counterpart
    )
    score = _score(trees, reported)
    assert score.links == LinkCounts(reported=8, truth=8, hits=6, spurious=0)
    assert score.links.precision == 0.75
    assert score.links.recall == 0.75
    assert score.links.f1 == 0.75


def test_saying_less_costs_recall_and_not_precision(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Links-only scoring: four right answers and no wrong ones is P 1.0, R 0.5."""
    score = _score(trees, LINKS[:4])
    assert score.links.precision == 1.0
    assert score.links.recall == 0.5
    assert score.links.f1 == pytest.approx(2 / 3, abs=1e-4)


def test_the_root_pair_is_excluded(trees: tuple[BlockTree, BlockTree]) -> None:
    """`/` to `/` is free and must not be counted; ADR-0034 says so in as many words."""
    with_root = _score(trees, ((ROOT_PATH, ROOT_PATH), *LINKS))
    assert with_root.links == LinkCounts(reported=8, truth=8, hits=8, spurious=0)


def test_containers_are_in_neither_set(trees: tuple[BlockTree, BlockTree]) -> None:
    """A `section` pair is neither reported nor labelled: containers are not labelled."""
    with_container = _score(trees, (("/section[1]", "/section[1]"), *LINKS))
    assert with_container.links.reported == 8
    assert with_container.links.hits == 8


def test_the_spurious_match_rate_catches_an_invented_match(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """A pair touching an inserted or a deleted block is spurious, and links-only
    precision alone would never see it."""
    reported = (*LINKS, (DELETED, INSERTED))
    score = _score(trees, reported)
    assert score.links.reported == 9
    assert score.links.hits == 8
    assert score.links.spurious == 1
    assert score.links.spurious_rate == pytest.approx(1 / 9, abs=1e-4)


def test_splits_merges_and_unscored_regions_leave_every_denominator(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Excluded on both sides, from ``C`` and ``C*`` alike, and the count is published."""
    labels = _labels(
        correspondences=tuple(_row(source, test) for source, test in LINKS),
        splits=(
            SplitEntry(
                source=CLAUSE_1_1,
                tests=(CLAUSE_1_1,),
                source_digest="0" * 16,
                test_digests=("0" * 16,),
                status="confirmed",
            ),
        ),
        merges=(
            MergeEntry(
                sources=(CLAUSE_1_2,),
                test=CLAUSE_1_2,
                source_digests=("0" * 16,),
                test_digest="0" * 16,
                status="confirmed",
            ),
        ),
    )
    score = _score(trees, LINKS, labels=labels)
    assert score.links == LinkCounts(reported=6, truth=6, hits=6, spurious=0)
    assert (score.skipped_splits, score.skipped_merges) == (1, 1)


def test_an_unscored_region_drops_everything_beneath_it(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """A region is an address prefix, so the section and both its clauses go."""
    labels = _labels(
        unscored=(
            UnscoredRegion(
                region="/section[1]/section[1]", side="both", reason="a toy region"
            ),
        )
    )
    score = _score(trees, LINKS, labels=labels)
    assert score.links == LinkCounts(reported=5, truth=5, hits=5, spurious=0)


def test_a_zero_denominator_reads_none_and_not_zero(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """"Nothing to get right" and "everything got wrong" are different facts."""
    empty = LinkCounts()
    assert empty.precision is None
    assert empty.recall is None
    assert empty.f1 is None
    assert SetCounts().recall is None
    score = _score(trees, ())
    assert score.links.precision is None
    assert score.links.recall == 0.0


def test_the_flat_addressable_column_drops_table_rows() -> None:
    """The like-for-like column excludes what 0.6 has no concept of."""
    assert BlockKind.ROW not in FLAT_ADDRESSABLE_KINDS
    assert BlockKind.CELL not in FLAT_ADDRESSABLE_KINDS
    assert BlockKind.PARAGRAPH in FLAT_ADDRESSABLE_KINDS
    assert BlockKind.LIST_ITEM in FLAT_ADDRESSABLE_KINDS

    markdown = "# Title\n\n| a | b |\n| --- | --- |\n| 1 | 2 |\n"
    source = read_document(markdown, format="markdown", profile="markdown")
    test = read_document(markdown, format="markdown", profile="markdown")
    rows = [block.path for block in source.walk() if block.kind is BlockKind.ROW]
    assert rows, "the fixture must actually contain table rows"

    labels = _labels(
        correspondences=(_row(rows[0], rows[0]),),
        inserted=(),
        deleted=(),
    )
    score = score_engine_pair(
        pair="toy",
        tier="hand",
        labels=labels,
        comparison=_comparison((source, test), pairs=_aligned(((rows[0], rows[0]),))),
        source_tree=source,
        test_tree=test,
    )
    assert score.links == LinkCounts(reported=1, truth=1, hits=1, spurious=0)
    assert score.flat_links == LinkCounts(reported=0, truth=0, hits=0, spurious=0)


# --- moves and renumbers ----------------------------------------------------


def _move(source: str, test: str, *, source_label: str, test_label: str) -> Change:
    """A `move` change node, as `build_change_tree` would emit one."""
    return Change(
        kind=ChangeKind.MOVE,
        source_address=source,
        test_address=test,
        block_kind=BlockKind.LIST_ITEM,
        source_label=source_label,
        test_label=test_label,
    )


def _renumber(source: str, test: str, *, source_label: str, test_label: str) -> Change:
    """A `renumber` change node."""
    return Change(
        kind=ChangeKind.RENUMBER,
        source_address=source,
        test_address=test,
        block_kind=BlockKind.LIST_ITEM,
        source_label=source_label,
        test_label=test_label,
    )


def test_move_recall_and_precision_key_on_the_ordered_pair(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """One move labelled, one reported to the wrong destination: recall 0, precision 0."""
    labels = _labels(
        correspondences=(
            _row(CLAUSE_1_1, CLAUSE_1_1, kind="move", source_label="1.1", test_label="1.1"),
        ),
        inserted=(),
        deleted=(),
    )
    right = _score(
        trees,
        ((CLAUSE_1_1, CLAUSE_1_1),),
        labels=labels,
        changes=(_move(CLAUSE_1_1, CLAUSE_1_1, source_label="1.1", test_label="1.1"),),
    )
    assert right.moves == SetCounts(reported=1, truth=1, hits=1)
    assert right.moves.recall == 1.0

    wrong = _score(
        trees,
        ((CLAUSE_1_1, CLAUSE_1_2),),
        labels=labels,
        changes=(_move(CLAUSE_1_1, CLAUSE_1_2, source_label="1.1", test_label="1.2"),),
    )
    assert wrong.moves == SetCounts(reported=1, truth=1, hits=0)
    assert wrong.moves.recall == 0.0
    assert wrong.moves.precision == 0.0


def test_a_moved_subtree_counts_once(trees: tuple[BlockTree, BlockTree]) -> None:
    """ADR-0034: credited at the topmost moved block; descendants are ordinary links.

    Three blocks change place; one `move` node is emitted and one `move` row is
    labelled, so recall is 1.0 rather than 1/3.
    """
    labels = _labels(
        correspondences=(
            _row(DEFINITIONS, DEFINITIONS, kind="move"),
            _row(CLAUSE_1_1, CLAUSE_1_1),
            _row(CLAUSE_1_2, CLAUSE_1_2),
        ),
        inserted=(),
        deleted=(),
    )
    score = _score(
        trees,
        ((DEFINITIONS, DEFINITIONS), (CLAUSE_1_1, CLAUSE_1_1), (CLAUSE_1_2, CLAUSE_1_2)),
        labels=labels,
        changes=(_move(DEFINITIONS, DEFINITIONS, source_label="1", test_label="1"),),
    )
    assert score.moves == SetCounts(reported=1, truth=1, hits=1)
    assert score.links == LinkCounts(reported=3, truth=3, hits=3, spurious=0)


def test_renumber_recall_needs_the_right_new_label(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """A renumber reported with the wrong new label is not a hit."""
    labels = _labels(
        correspondences=(
            _row(CLAUSE_3_1, CLAUSE_3_1, kind="renumber", source_label="3.1", test_label="2.1"),
        ),
        inserted=(),
        deleted=(),
    )
    right = _score(
        trees,
        ((CLAUSE_3_1, CLAUSE_3_1),),
        labels=labels,
        changes=(_renumber(CLAUSE_3_1, CLAUSE_3_1, source_label="3.1", test_label="2.1"),),
    )
    assert right.renumbers == SetCounts(reported=1, truth=1, hits=1)

    wrong = _score(
        trees,
        ((CLAUSE_3_1, CLAUSE_3_1),),
        labels=labels,
        changes=(_renumber(CLAUSE_3_1, CLAUSE_3_1, source_label="3.1", test_label="4.9"),),
    )
    assert wrong.renumbers == SetCounts(reported=1, truth=1, hits=0)
    assert wrong.renumbers.recall == 0.0


def test_a_move_node_with_two_labels_is_also_a_renumber(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Kind precedence puts a moved-and-relabelled block on a `move` node, so the
    renumber metric has to read labels rather than kinds -- on both sides."""
    labels = _labels(
        correspondences=(
            _row(CLAUSE_1_1, CLAUSE_1_2, kind="move", source_label="1.1", test_label="1.2"),
        ),
        inserted=(),
        deleted=(),
    )
    score = _score(
        trees,
        ((CLAUSE_1_1, CLAUSE_1_2),),
        labels=labels,
        changes=(_move(CLAUSE_1_1, CLAUSE_1_2, source_label="1.1", test_label="1.2"),),
    )
    assert score.moves == SetCounts(reported=1, truth=1, hits=1)
    assert score.renumbers == SetCounts(reported=1, truth=1, hits=1)


# --- the move gate ----------------------------------------------------------


def test_an_unrecorded_engine_move_is_unreviewed_and_fails_closed(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """ADR-0034: unknown is not a pass."""
    score = _score(
        trees,
        LINKS,
        changes=(_move(CLAUSE_1_1, CLAUSE_1_2, source_label="1.1", test_label="1.2"),),
    )
    assert score.unreviewed_moves == ((CLAUSE_1_1, CLAUSE_1_2),)
    assert score.wrong_moves == ()


def test_a_verdict_moves_an_engine_move_out_of_unreviewed(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """`acceptable` clears it; `wrong` names it; either way it is no longer unknown."""
    verdict = MoveVerdict(
        source=CLAUSE_1_1,
        test=CLAUSE_1_2,
        engine="deadbeef",
        verdict="acceptable",
        reason="the same clause, renumbered by an insertion above it",
        reviewed_by="houfu",
        reviewed_at="2026-09-05",
    )
    change = _move(CLAUSE_1_1, CLAUSE_1_2, source_label="1.1", test_label="1.2")

    accepted = _score(
        trees, LINKS, labels=_labels(move_verdicts=(verdict,)), changes=(change,)
    )
    assert accepted.unreviewed_moves == ()
    assert accepted.wrong_moves == ()

    ruled_wrong = _score(
        trees,
        LINKS,
        labels=_labels(
            move_verdicts=(
                MoveVerdict(
                    source=CLAUSE_1_1,
                    test=CLAUSE_1_2,
                    engine="deadbeef",
                    verdict="wrong",
                    reason="two boilerplate clauses, not the same clause",
                    reviewed_by="houfu",
                    reviewed_at="2026-09-05",
                ),
            )
        ),
        changes=(change,),
    )
    assert ruled_wrong.unreviewed_moves == ()
    assert ruled_wrong.wrong_moves == ((CLAUSE_1_1, CLAUSE_1_2),)


def test_a_labelled_move_needs_no_verdict(trees: tuple[BlockTree, BlockTree]) -> None:
    """Verdicts rule on moves the labels do *not* carry; a hit is not a question."""
    labels = _labels(
        correspondences=(
            _row(CLAUSE_1_1, CLAUSE_1_1, kind="move"),
        ),
        inserted=(),
        deleted=(),
    )
    score = _score(
        trees,
        ((CLAUSE_1_1, CLAUSE_1_1),),
        labels=labels,
        changes=(_move(CLAUSE_1_1, CLAUSE_1_1, source_label="1.1", test_label="1.1"),),
    )
    assert score.unreviewed_moves == ()


# --- the per-pass table -----------------------------------------------------


def test_the_pass_table_reads_totals_from_alignment_pass_counts(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """`total` is the engine's own bookkeeping; `matches` is what the metric scores.

    The gap between them is real and is exactly what the report says it is: a
    container pair the pass found and the benchmark does not label.
    """
    source, test = trees
    reported = ((("/section[1]", "/section[1]")), *LINKS[:3])
    comparison = _comparison(
        trees,
        pairs=_aligned(reported),
        pass_counts={"exact": 4, "root": 1},
    )
    table = pass_table(
        comparison,
        labels=_labels(),
        source_tree=source,
        test_tree=test,
        config=AlignmentConfig(similarity="difflib"),
    )
    by_name = {counts.name: counts for counts in table}
    assert [counts.name for counts in table] == list(PASS_NAMES)
    assert by_name["exact"].total == 4
    assert by_name["exact"].matches == 3
    assert by_name["exact"].wrong == 0


def test_wrong_matches_are_attributed_to_the_pass_that_made_them(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Two passes, one of them wrong: the blame lands on the right row."""
    source, test = trees
    comparison = _comparison(
        trees,
        pairs=(
            *_aligned(LINKS[:4], matched_by="exact"),
            *_aligned(((CLAUSE_3_1, CLAUSE_1_2),), matched_by="positional"),
        ),
        pass_counts={"exact": 4, "positional": 1},
    )
    table = {
        counts.name: counts
        for counts in pass_table(
            comparison,
            labels=_labels(),
            source_tree=source,
            test_tree=test,
            config=AlignmentConfig(similarity="difflib"),
        )
    }
    assert (table["exact"].matches, table["exact"].wrong) == (4, 0)
    assert (table["positional"].matches, table["positional"].wrong) == (1, 1)
    assert table["positional"].to_dict()["wrong_rate"] == 1.0
    assert table["exact"].to_dict()["wrong_rate"] == 0.0


def test_only_a_droppable_pass_gets_a_unique_count(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """ADR-0032 fixes three passes as the descent's anchors and its fill-in, so their
    contribution cannot be measured by removing them; `n/a` says so, `0` would lie."""
    source, test = trees
    table = {
        counts.name: counts
        for counts in pass_table(
            _comparison(trees, pairs=_aligned(LINKS)),
            labels=_labels(),
            source_tree=source,
            test_tree=test,
            config=AlignmentConfig(similarity="difflib"),
        )
    }
    for name in ("exact", "structural", "positional"):
        assert name not in DROPPABLE_PASSES
        assert table[name].unique is None
    for name in DROPPABLE_PASSES:
        assert table[name].unique is not None


def test_a_pass_dropped_from_the_configuration_is_not_re_run(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """A pass that did not run has no unique contribution to measure."""
    source, test = trees
    config = AlignmentConfig(
        similarity="difflib",
        passes=tuple(name for name in PASS_NAMES if name != "move"),
    )
    table = {
        counts.name: counts
        for counts in pass_table(
            _comparison(trees, pairs=_aligned(LINKS), config=config),
            labels=_labels(),
            source_tree=source,
            test_tree=test,
            config=config,
        )
    }
    assert table["move"].unique is None
    assert table["fuzzy"].unique is not None


# --- aggregation ------------------------------------------------------------


def test_aggregate_micro_averages_rather_than_taking_a_mean_of_means() -> None:
    """A two-block pair must not weigh as much as a two-hundred-block one."""
    big = PairScore(
        pair="big",
        tier="synthetic",
        plan="heavy",
        links=LinkCounts(reported=100, truth=100, hits=50),
        flat_links=LinkCounts(),
        moves=SetCounts(),
        renumbers=SetCounts(),
    )
    small = PairScore(
        pair="small",
        tier="synthetic",
        plan="light",
        links=LinkCounts(reported=2, truth=2, hits=2),
        flat_links=LinkCounts(),
        moves=SetCounts(),
        renumbers=SetCounts(),
    )
    tier = aggregate([small, big], tier="synthetic", engine="1.0", backend="difflib")

    assert [score.pair for score in tier.pairs] == ["big", "small"]
    assert tier.links == LinkCounts(reported=102, truth=102, hits=52)
    assert tier.links.precision == pytest.approx(52 / 102, abs=1e-4)
    # The mean of the two pairs' precisions would be 0.75; micro-averaging is 0.5098.
    assert tier.links.precision != pytest.approx(0.75, abs=1e-4)


def test_aggregating_the_pass_table_keeps_a_measured_unique_count() -> None:
    """`None` is absorbing under addition, so the sum must not start from an empty row."""

    def pair(name: str, unique: int) -> PairScore:
        return PairScore(
            pair=name,
            tier="synthetic",
            plan=None,
            links=LinkCounts(),
            flat_links=LinkCounts(),
            moves=SetCounts(),
            renumbers=SetCounts(),
            passes=tuple(
                PassCounts(
                    name=pass_name,
                    total=1,
                    matches=1,
                    unique=unique if pass_name in DROPPABLE_PASSES else None,
                )
                for pass_name in PASS_NAMES
            ),
        )

    tier = aggregate(
        [pair("a", 2), pair("b", 3)], tier="synthetic", engine="1.0", backend="difflib"
    )
    table = {counts.name: counts for counts in tier.passes}
    assert table["fuzzy"].unique == 5
    assert table["fuzzy"].total == 2
    assert table["exact"].unique is None


def test_adding_two_different_passes_is_refused() -> None:
    """Summing `exact` into `fuzzy` would be a silent corruption of the table."""
    with pytest.raises(ValueError, match="cannot add pass"):
        PassCounts(name="exact") + PassCounts(name="fuzzy")


# --- the 0.6 floor ----------------------------------------------------------


def test_the_flat_unit_is_a_line() -> None:
    """`redlines.processor.split_paragraphs` splits on any run of newlines, which is
    why the floor necessarily gets a whitespace-only rewrap wrong."""
    assert flat_units("one\ntwo\n\nthree") == ("one", "two", "three")


def test_units_lift_to_the_blocks_that_contain_them(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Every line of the fixture finds its block; nothing is stranded."""
    source, _ = trees
    lift = lift_units((FIXTURE / "source.txt").read_text(encoding="utf-8"), source)
    assert lift.unassigned == 0
    assert lift.address_for(0) == TITLE
    assert lift.address_for(2) == CLAUSE_1_1
    assert lift.address_for(len(lift.units)) is None


def test_the_floor_pairs_the_fixtures_unchanged_lines(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """The 0.6 engine gets the blocks that did not move, which is what a floor is."""
    source, test = trees
    source_text = (FIXTURE / "source.txt").read_text(encoding="utf-8")
    test_text = (FIXTURE / "test.txt").read_text(encoding="utf-8")

    units = baseline_unit_pairs(source_text, test_text)
    assert units, "the flat engine must report something on an eight-of-nine match"

    pairs = baseline_pairs(
        source_text, test_text, source_tree=source, test_tree=test
    )
    reported = dict(pairs)
    assert reported[TITLE] == TITLE
    assert reported[CLAUSE_1_1] == CLAUSE_1_1
    assert reported[CLAUSE_3_1] == CLAUSE_3_1
    # 3.2 was deleted, so nothing in the test document is it. The floor may pair
    # its line with something -- that is what the spurious-match rate is for --
    # but it must not claim the address survived.
    assert reported.get(DELETED) != DELETED


def test_the_floor_scores_zero_move_and_renumber_recall_rather_than_blank(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """ADR-0034: that cell is the argument for the milestone, so it prints `0.0`."""
    source, test = trees
    labels = _labels(
        correspondences=(
            _row(CLAUSE_1_1, CLAUSE_1_2, kind="move", source_label="1.1", test_label="1.2"),
        ),
        inserted=(),
        deleted=(),
    )
    score = score_baseline_pair(
        pair="toy",
        tier="hand",
        labels=labels,
        reported=((CLAUSE_1_1, CLAUSE_1_2),),
        source_tree=source,
        test_tree=test,
    )
    assert score.moves == SetCounts(reported=0, truth=1, hits=0)
    assert score.moves.recall == 0.0
    assert score.renumbers.recall == 0.0
    assert score.passes == ()


def test_the_baseline_never_reaches_the_redlines_facade() -> None:
    """ADR-0003 has M3 reimplement `Redlines` over this same core, so a baseline that
    went through it would stop being the 0.6 baseline on the day the facade lands and
    the report would be comparing the new engine with itself.

    Asserted against the source rather than against a mock, because the failure this
    guards is somebody editing the module later.
    """
    for name in ("baselines.py", "units.py"):
        path = Path(__file__).parent.parent / "benchmark" / name
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "redlines.redlines", f"{name} imports the facade"
            elif isinstance(node, ast.ImportFrom):
                assert node.module != "redlines.redlines", f"{name} imports the facade"
                if node.module in {"redlines", "redlines.redlines"}:
                    imported = {alias.name for alias in node.names}
                    assert "Redlines" not in imported, f"{name} imports Redlines"
            elif isinstance(node, ast.Name):
                assert node.id != "Redlines", f"{name} names Redlines"
            elif isinstance(node, ast.Attribute):
                assert node.attr != "Redlines", f"{name} names Redlines"


# --- semantic roles ---------------------------------------------------------


def test_role_counts_report_coverage_by_role_and_by_match_kind(
    trees: tuple[BlockTree, BlockTree],
) -> None:
    """Coverage over labelled blocks only, containers excluded, both sides summed."""
    source, test = trees
    counts = role_counts(source, test)
    assert counts.blocks == 9 + 9
    assert 0 < counts.roled <= counts.blocks
    assert counts.coverage == round(counts.roled / counts.blocks, 4)
    assert sum(counts.by_role.values()) == counts.roled
    assert sum(counts.by_match.values()) == counts.roled
    assert list(counts.by_role) == sorted(counts.by_role)


def test_role_counts_add() -> None:
    """Summing two tiers merges both mappings and keeps them sorted."""
    left = RoleCounts(blocks=2, roled=1, by_role={"clause": 1}, by_match={"label": 1})
    right = RoleCounts(
        blocks=3, roled=2, by_role={"recital": 2}, by_match={"label": 2}
    )
    total = left + right
    assert total.blocks == 5
    assert total.roled == 3
    assert total.by_role == {"clause": 1, "recital": 2}
    assert total.by_match == {"label": 3}


# --- the report -------------------------------------------------------------


def _results() -> dict[str, object]:
    """A minimal results document, enough to render every section of the report."""
    tier = aggregate(
        [
            score_baseline_pair(
                pair="toy",
                tier="hand",
                labels=_labels(
                    correspondences=(
                        *(_row(source, test) for source, test in LINKS[:7]),
                        _row(
                            CLAUSE_3_1,
                            CLAUSE_3_1,
                            kind="move",
                            source_label="3.1",
                            test_label="2.1",
                        ),
                    ),
                    review=Review(labelled_by="houfu", labelled_at="2026-09-05"),
                ),
                reported=LINKS,
                source_tree=read_document(
                    (FIXTURE / "source.txt").read_text(encoding="utf-8"),
                    format="text",
                    profile="contract",
                ),
                test_tree=read_document(
                    (FIXTURE / "test.txt").read_text(encoding="utf-8"),
                    format="text",
                    profile="contract",
                ),
            )
        ],
        tier="hand",
        engine="0.6",
        backend="none",
    )
    return {
        "schema": "redlines/benchmark-results/1",
        "generator_version": 1,
        "backends": ["difflib"],
        "alignment_config": AlignmentConfig().to_dict(),
        "corpus": [
            {
                "tier": "hand",
                "pairs": 1,
                "formats": ["text"],
                "profiles": ["contract"],
                "plans": [],
                "documents": [],
            }
        ],
        "roles": {"hand": role_counts().to_dict()},
        "tiers": [tier.to_dict()],
    }


def test_the_report_states_the_two_baseline_lift_rules() -> None:
    """ADR-0034: the only places the floor can be flattered or hobbled, in the report."""
    report = render_report(_results())
    assert "plurality" in report
    assert "smallest test unit index" in report
    assert "earliest test block in document order" in report


def test_the_report_states_what_adr_0014_makes_impossible() -> None:
    """The 45.9 re-run is not achievable in 1.0 and the report must say so."""
    report = render_report(_results())
    assert "45.9" in report
    assert "ADR-0014" in report
    assert "cannot be one in 1.0" in report


def test_the_report_labels_external_numbers_not_reproducible() -> None:
    """The external tier is gitignored, so nothing from it is checkable by a stranger."""
    report = render_report(_results())
    assert "not reproducible from this repository" in report


def test_the_report_prints_zero_and_not_a_blank_for_the_floors_move_recall() -> None:
    """The 0.6 row's move and renumber cells are the thesis in two cells."""
    report = render_report(_results())
    row = next(
        line for line in report.splitlines() if line.startswith("| `hand` | 0.6 | none |")
    )
    assert row.endswith("| 0.0000 | 0.0000 |"), row


def test_the_report_says_a_single_backend_run_leaves_the_gap_unmeasured() -> None:
    """Better an explicit hole than a table that looks complete."""
    report = render_report(_results())
    assert "Unmeasured in this run" in report


def test_the_report_marks_a_draft_labelled_tier() -> None:
    """Scoring against still-`proposed` rows measures self-agreement; it is daggered."""
    results = _results()
    tiers = results["tiers"]
    assert isinstance(tiers, list)
    tiers[0]["pairs"][0]["proposed_rows"] = 7
    report = render_report(results)
    assert "drafts, not ground truth" in report
    assert "`hand` †" in report
