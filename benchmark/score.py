"""The alignment metric: every number the benchmark publishes (#143, D-8, ADR-0034).

A metric definition cannot be revised after publication, so this module is
written to be read as the definition rather than as an implementation of one.
Nothing here is tuned, nothing is averaged over an unstated set, and every
denominator is named.

The engine's answer is `redlines.comparison.Comparison`: `alignment` for the
correspondence set, because an unchanged matched pair produces no change node
and the change tree therefore cannot express the set at all, and `changes` for
the moves and renumbers, because their granularity rules live there
(ADR-0033) and scoring them off anything else would let the engine and its own
metric disagree about what a move is.

What is measured
----------------

Let ``C*`` be the labelled correspondence set as ``(source address, test
address)`` pairs and ``C`` the engine's reported pairs. Then:

- **precision** ``|C ∩ C*| / |C|``, **recall** ``|C ∩ C*| / |C*|``, **F1**
  their harmonic mean. **Links only**: an `inserted` or `deleted` block is not
  in either denominator. Counting correctly-unmatched blocks would let a long
  document with three edits inflate F1 by saying nothing about most of itself,
  and would make the score a function of document length.
- **spurious-match rate** ``|{p ∈ C : one side of p is labelled inserted or
  deleted}| / |C|``. This is the counterweight links-only scoring needs: a
  fill-in pass that invents matches is invisible to links-only precision and
  loud here.
- **move recall** ``|M ∩ M*| / |M*|`` over ordered pairs, with move precision
  beside it. A **moved subtree counts once**, at the highest block whose whole
  subtree moved -- which is not enforced here but inherited, because ``M``
  is read off the change tree's `move` nodes and that is the rule they are
  emitted under.
- **renumber recall** keys on ``(source, test, source label, test label)``: a
  renumber reported with the wrong new label is not a hit. Both sides derive
  the set the same way, from **labels that differ**, so a block that moved
  *and* was relabelled is one row of ground truth feeding two metrics.
- **per pass**, its match count, its wrong-match count, and how many of its
  pairs no other configuration would have found. The last is measured, not
  guessed: the alignment is re-run with that pass switched off and the
  difference is the pass's unique contribution. Only `label`, `fuzzy` and
  `move` can be switched off (ADR-0032 fixes the other three as the descent's
  anchors and its fill-in), so the other three report ``null`` rather than a
  number that would mean "we could not check".

What is excluded, and why
-------------------------

- **The root pair.** ``/`` corresponds to ``/`` in every comparison ever made;
  scoring an engine for knowing that a document is itself flatters every
  number in the table.
- **Containers.** Only the kinds ADR-0034 labels -- text-bearing blocks plus
  table `row` blocks -- are in either set, on either side.
- **Splits and merges**, and any `unscored` region: every address named by one
  is dropped from ``C`` and from ``C*`` alike, and the count of what was
  dropped is published, so the day 1.1 scores them the delta is measurable
  rather than a guess.

Exactness
---------

Counts are integers and ratios are computed once, at the end, from summed
counts -- a micro-average, never a mean of means, and never a float
accumulated across a corpus in a set-derived order. Ratios are rounded to four
places at the boundary where they leave this module, which is what keeps
``benchmark/results/latest.json`` byte-stable for identical inputs and its
diff readable.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from redlines.alignment import PASS_NAMES, AlignmentConfig, align
from redlines.blocks import ROOT_PATH, BlockKind
from redlines.changes import ChangeKind

from .labels import LABELLED_KINDS, override_rate
from .units import FLAT_ADDRESSABLE_KINDS

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from redlines.blocks import BlockTree
    from redlines.comparison import Comparison

    from .labels import LabelFile

__all__ = [
    "DROPPABLE_PASSES",
    "Truth",
    "LinkCounts",
    "SetCounts",
    "PassCounts",
    "RoleCounts",
    "PairScore",
    "TierScore",
    "truth_for",
    "engine_pairs",
    "score_engine_pair",
    "score_baseline_pair",
    "pass_table",
    "role_counts",
    "aggregate",
]

#: The passes `AlignmentConfig.passes` will let you drop (decision 7 of the M2
#: decisions record). ``exact``, ``structural`` and ``positional`` are the
#: descent's anchors and its fill-in and cannot be removed, so their unique
#: contribution is unmeasurable rather than zero.
DROPPABLE_PASSES: tuple[str, ...] = ("label", "fuzzy", "move")


def _ratio(numerator: int, denominator: int) -> float | None:
    """Return ``numerator / denominator`` to four places, or ``None`` at 0/0.

    ``None`` rather than ``0.0``, because "there was nothing to get right" and
    "everything was got wrong" are different facts and a report that prints
    them the same way is lying about one of them.
    """
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _harmonic(left: float | None, right: float | None) -> float | None:
    """Return the harmonic mean of two ratios, or ``None`` if either is absent."""
    if left is None or right is None or left + right == 0:
        return None
    return round(2 * left * right / (left + right), 4)


@dataclass(frozen=True, slots=True)
class Truth:
    """One pair's ground truth, in the shapes the metric consumes.

    :param links: ``(source, test)`` for every correspondence row.
    :param moves: the subset whose row said ``kind: move``.
    :param renumbers: ``(source, test, source label, test label)`` for every
        row whose two labels differ, whatever its ``kind`` -- which is how a
        moved-and-relabelled block feeds the renumber metric from the same row
        that feeds the move metric.
    :param inserted: labelled test addresses nothing corresponds to.
    :param deleted: labelled source addresses nothing corresponds to.
    :param excluded_source: source addresses no metric may count, because a
        split, a merge or an `unscored` region named them.
    :param excluded_test: the same on the test side.
    :param skipped_splits: how many split rows were dropped.
    :param skipped_merges: how many merge rows were dropped.
    """

    links: frozenset[tuple[str, str]]
    moves: frozenset[tuple[str, str]]
    renumbers: frozenset[tuple[str, str, str | None, str | None]]
    inserted: frozenset[str]
    deleted: frozenset[str]
    excluded_source: frozenset[str]
    excluded_test: frozenset[str]
    skipped_splits: int
    skipped_merges: int


@dataclass(frozen=True, slots=True)
class LinkCounts:
    """Correspondence counts, from which precision, recall and F1 derive.

    :param reported: ``|C|``.
    :param truth: ``|C*|``.
    :param hits: ``|C ∩ C*|``.
    :param spurious: reported pairs with one side labelled inserted or deleted.
    """

    reported: int = 0
    truth: int = 0
    hits: int = 0
    spurious: int = 0

    def __add__(self, other: LinkCounts) -> LinkCounts:
        """Sum two pairs' counts, which is what micro-averaging is."""
        return LinkCounts(
            reported=self.reported + other.reported,
            truth=self.truth + other.truth,
            hits=self.hits + other.hits,
            spurious=self.spurious + other.spurious,
        )

    @property
    def precision(self) -> float | None:
        """``|C ∩ C*| / |C|``."""
        return _ratio(self.hits, self.reported)

    @property
    def recall(self) -> float | None:
        """``|C ∩ C*| / |C*|``."""
        return _ratio(self.hits, self.truth)

    @property
    def f1(self) -> float | None:
        """The harmonic mean of `precision` and `recall`."""
        return _harmonic(self.precision, self.recall)

    @property
    def spurious_rate(self) -> float | None:
        """The fraction of reported pairs touching an inserted or deleted block."""
        return _ratio(self.spurious, self.reported)

    def to_dict(self) -> dict[str, Any]:
        """Return the counts and their derived ratios, ratios rounded."""
        return {
            "reported": self.reported,
            "truth": self.truth,
            "hits": self.hits,
            "spurious": self.spurious,
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "spurious_rate": self.spurious_rate,
        }


@dataclass(frozen=True, slots=True)
class SetCounts:
    """Move or renumber counts.

    :param reported: how many the engine reported.
    :param truth: how many the labels hold.
    :param hits: how many of the engine's are in the labels.
    """

    reported: int = 0
    truth: int = 0
    hits: int = 0

    def __add__(self, other: SetCounts) -> SetCounts:
        """Sum two pairs' counts."""
        return SetCounts(
            reported=self.reported + other.reported,
            truth=self.truth + other.truth,
            hits=self.hits + other.hits,
        )

    @property
    def precision(self) -> float | None:
        """``|X ∩ X*| / |X|``."""
        return _ratio(self.hits, self.reported)

    @property
    def recall(self) -> float | None:
        """``|X ∩ X*| / |X*|``."""
        return _ratio(self.hits, self.truth)

    def to_dict(self) -> dict[str, Any]:
        """Return the counts and their derived ratios."""
        return {
            "reported": self.reported,
            "truth": self.truth,
            "hits": self.hits,
            "precision": self.precision,
            "recall": self.recall,
        }


@dataclass(frozen=True, slots=True)
class PassCounts:
    """What one alignment pass contributed, and how much of it was wrong.

    Two match counts, because they answer two different questions and
    conflating them would hide the gap. ``total`` is the engine's own
    bookkeeping, `redlines.alignment.Alignment.pass_counts`, over every pair
    the pass produced -- containers included, `unscored` regions included.
    ``matches`` is the subset the metric may count: labelled kinds, root
    excluded, splits and merges excluded. ``wrong`` is measured against
    ``matches``, so ``total - matches`` is exactly the part of a pass's work
    the benchmark says nothing about.

    :param name: the pass, from `redlines.alignment.PASS_NAMES`.
    :param total: pairs the pass produced, straight off ``pass_counts``.
    :param matches: how many of them are in ``C``, the scored set.
    :param wrong: how many of *those* are not in ``C*``.
    :param unique: how many of them no run without this pass produced, or
        ``None`` for a pass that cannot be switched off.
    """

    name: str
    total: int = 0
    matches: int = 0
    wrong: int = 0
    unique: int | None = None

    def __add__(self, other: PassCounts) -> PassCounts:
        """Sum two pairs' counts for the same pass."""
        if self.name != other.name:
            raise ValueError(f"cannot add pass {self.name!r} to pass {other.name!r}")
        unique = (
            None
            if self.unique is None or other.unique is None
            else self.unique + other.unique
        )
        return PassCounts(
            name=self.name,
            total=self.total + other.total,
            matches=self.matches + other.matches,
            wrong=self.wrong + other.wrong,
            unique=unique,
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the counts, with the wrong-match rate derived."""
        return {
            "pass": self.name,
            "total": self.total,
            "matches": self.matches,
            "wrong": self.wrong,
            "unique": self.unique,
            "wrong_rate": _ratio(self.wrong, self.matches),
        }


@dataclass(frozen=True, slots=True)
class RoleCounts:
    """How much of a corpus the ADR-0031 semantic pass put a role on.

    ADR-0021 asks for semantic role precision on a hand-labelled sample,
    reported and not gated. The only hand-labelled role sample this repository
    owns is the sample pair, and its roles are *asserted* in
    ``tests/test_sample_pair.py`` -- so a precision number computed against it
    would be 1.0 by construction and would be evidence of nothing. What is
    published instead is coverage: how many labelled blocks carry a role at
    all, and which `role_match` kind put it there. That is a real measurement
    of the semantic pass over fifty real pairs, and the report says in as many
    words that it is coverage rather than precision.

    :param blocks: labelled blocks seen, on both sides of every pair.
    :param roled: how many carry a non-``None`` role.
    :param by_role: how many carry each role.
    :param by_match: how many were roled by each `role_match` kind.
    """

    blocks: int = 0
    roled: int = 0
    by_role: Mapping[str, int] = field(default_factory=dict)
    by_match: Mapping[str, int] = field(default_factory=dict)

    def __add__(self, other: RoleCounts) -> RoleCounts:
        """Sum two corpora's counts."""
        return RoleCounts(
            blocks=self.blocks + other.blocks,
            roled=self.roled + other.roled,
            by_role=_merge(self.by_role, other.by_role),
            by_match=_merge(self.by_match, other.by_match),
        )

    @property
    def coverage(self) -> float | None:
        """The fraction of labelled blocks carrying a role."""
        return _ratio(self.roled, self.blocks)

    def to_dict(self) -> dict[str, Any]:
        """Return the counts, each mapping in sorted key order."""
        return {
            "blocks": self.blocks,
            "roled": self.roled,
            "coverage": self.coverage,
            "by_role": {key: self.by_role[key] for key in sorted(self.by_role)},
            "by_match": {key: self.by_match[key] for key in sorted(self.by_match)},
        }


def _merge(left: Mapping[str, int], right: Mapping[str, int]) -> dict[str, int]:
    """Sum two count mappings, in sorted key order."""
    return {
        key: left.get(key, 0) + right.get(key, 0)
        for key in sorted(set(left) | set(right))
    }


def role_counts(*trees: BlockTree) -> RoleCounts:
    """Count the roles the semantic pass put on some trees' labelled blocks.

    :param trees: the trees to walk; both sides of a pair, normally.
    :return: the `RoleCounts`.
    """
    blocks = 0
    roled = 0
    by_role: dict[str, int] = {}
    by_match: dict[str, int] = {}
    for tree in trees:
        for block in tree.walk():
            if block.kind not in LABELLED_KINDS:
                continue
            blocks += 1
            if block.role is None:
                continue
            roled += 1
            by_role[block.role] = by_role.get(block.role, 0) + 1
            semantic = block.attrs.get("semantic")
            match = "unrecorded"
            if isinstance(semantic, Mapping):
                match = str(semantic.get("role_match", "unrecorded"))
            by_match[match] = by_match.get(match, 0) + 1
    return RoleCounts(
        blocks=blocks,
        roled=roled,
        by_role={key: by_role[key] for key in sorted(by_role)},
        by_match={key: by_match[key] for key in sorted(by_match)},
    )


@dataclass(frozen=True, slots=True)
class PairScore:
    """Everything measured about one pair under one engine and one backend.

    :param pair: the pair id, which is its directory name.
    :param tier: ``synthetic`` or ``hand``.
    :param plan: the mutation plan, for a synthetic pair; ``None`` otherwise.
    :param links: correspondence counts over every labelled block.
    :param flat_links: the same restricted to the blocks the flat engine can
        address, which is the only like-for-like comparison with the floor.
    :param moves: move counts.
    :param renumbers: renumber counts.
    :param passes: the per-pass table, empty for the baseline, which has none.
    :param unreviewed_moves: engine moves that are neither in the labels nor in
        ``move_verdicts``. Unknown is not a pass (ADR-0034).
    :param wrong_moves: engine moves a reviewer ruled ``wrong``.
    :param skipped_splits: split rows excluded from every denominator.
    :param skipped_merges: merge rows likewise.
    :param override_rate: the labeller's correction rate, or ``None`` when the
        file records no statuses to compute one from.
    :param labels_signed: whether the label file carries a `review` block --
        the difference between ground truth and an engine-seeded draft.
    :param proposed_rows: how many correspondence rows are still ``proposed``.
    :param budget_exhausted: whether alignment ran out of ``max_comparisons``.
    """

    pair: str
    tier: str
    plan: str | None
    links: LinkCounts
    flat_links: LinkCounts
    moves: SetCounts
    renumbers: SetCounts
    passes: tuple[PassCounts, ...] = ()
    unreviewed_moves: tuple[tuple[str, str], ...] = ()
    wrong_moves: tuple[tuple[str, str], ...] = ()
    skipped_splits: int = 0
    skipped_merges: int = 0
    override_rate: float | None = None
    labels_signed: bool = False
    proposed_rows: int = 0
    budget_exhausted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the pair's row of the results file."""
        return {
            "pair": self.pair,
            "tier": self.tier,
            "plan": self.plan,
            "links": self.links.to_dict(),
            "flat_links": self.flat_links.to_dict(),
            "moves": self.moves.to_dict(),
            "renumbers": self.renumbers.to_dict(),
            "passes": [counts.to_dict() for counts in self.passes],
            "unreviewed_moves": [list(move) for move in self.unreviewed_moves],
            "wrong_moves": [list(move) for move in self.wrong_moves],
            "skipped_splits": self.skipped_splits,
            "skipped_merges": self.skipped_merges,
            "override_rate": self.override_rate,
            "labels_signed": self.labels_signed,
            "proposed_rows": self.proposed_rows,
            "budget_exhausted": self.budget_exhausted,
        }


@dataclass(frozen=True, slots=True)
class TierScore:
    """One tier, under one engine and one backend, summed over its pairs.

    :param tier: ``synthetic`` or ``hand``.
    :param engine: ``"1.0"`` or ``"0.6"``.
    :param backend: the resolved similarity backend the run used.
    :param pairs: every `PairScore`, in sorted pair order.
    :param links: the summed correspondence counts.
    :param flat_links: the same over flat-addressable blocks only.
    :param moves: summed move counts.
    :param renumbers: summed renumber counts.
    :param passes: the summed per-pass table, in `PASS_NAMES` order.
    """

    tier: str
    engine: str
    backend: str
    pairs: tuple[PairScore, ...]
    links: LinkCounts
    flat_links: LinkCounts
    moves: SetCounts
    renumbers: SetCounts
    passes: tuple[PassCounts, ...]

    @property
    def unreviewed_moves(self) -> int:
        """How many engine moves across the tier have no verdict and no label."""
        return sum(len(pair.unreviewed_moves) for pair in self.pairs)

    @property
    def wrong_moves(self) -> int:
        """How many engine moves across the tier a reviewer ruled ``wrong``."""
        return sum(len(pair.wrong_moves) for pair in self.pairs)

    def to_dict(self) -> dict[str, Any]:
        """Return the tier's section of the results file."""
        return {
            "tier": self.tier,
            "engine": self.engine,
            "backend": self.backend,
            "links": self.links.to_dict(),
            "flat_links": self.flat_links.to_dict(),
            "moves": self.moves.to_dict(),
            "renumbers": self.renumbers.to_dict(),
            "passes": [counts.to_dict() for counts in self.passes],
            "unreviewed_moves": self.unreviewed_moves,
            "wrong_moves": self.wrong_moves,
            "skipped_splits": sum(pair.skipped_splits for pair in self.pairs),
            "skipped_merges": sum(pair.skipped_merges for pair in self.pairs),
            "pairs": [pair.to_dict() for pair in self.pairs],
        }


def truth_for(labels: LabelFile) -> Truth:
    """Build the ground-truth sets one pair's label file states.

    :param labels: the loaded label file.
    :return: the `Truth`, with split, merge and unscored addresses already
        collected into the excluded sets.
    """
    excluded_source: set[str] = set()
    excluded_test: set[str] = set()
    for split in labels.splits:
        excluded_source.add(split.source)
        excluded_test.update(split.tests)
    for merge in labels.merges:
        excluded_source.update(merge.sources)
        excluded_test.add(merge.test)
    for region in labels.unscored:
        if region.side in ("source", "both"):
            excluded_source.add(region.region)
        if region.side in ("test", "both"):
            excluded_test.add(region.region)

    links = {(row.source, row.test) for row in labels.correspondences}
    moves = {(row.source, row.test) for row in labels.correspondences if row.kind == "move"}
    renumbers = {
        (row.source, row.test, row.source_label, row.test_label)
        for row in labels.correspondences
        if row.source_label != row.test_label
    }
    return Truth(
        links=frozenset(links),
        moves=frozenset(moves),
        renumbers=frozenset(renumbers),
        inserted=frozenset(row.test for row in labels.inserted),
        deleted=frozenset(row.source for row in labels.deleted),
        excluded_source=frozenset(excluded_source),
        excluded_test=frozenset(excluded_test),
        skipped_splits=len(labels.splits),
        skipped_merges=len(labels.merges),
    )


def _kinds(tree: BlockTree) -> dict[str, BlockKind]:
    """Return every block's kind, by address."""
    return {block.path: block.kind for block in tree.walk()}


def _under(address: str, prefix: str) -> bool:
    """Whether ``address`` is ``prefix`` or lies inside it (ADR-0029 prefixes)."""
    return address == prefix or address.startswith(
        prefix if prefix.endswith("/") else prefix + "/"
    )


class _Scope:
    """Which addresses a metric may count, for one pair."""

    def __init__(
        self,
        truth: Truth,
        *,
        source_kinds: Mapping[str, BlockKind],
        test_kinds: Mapping[str, BlockKind],
        kinds: frozenset[BlockKind],
    ) -> None:
        self._truth = truth
        self._source_kinds = source_kinds
        self._test_kinds = test_kinds
        self._kinds = kinds

    def allows(self, source: str, test: str) -> bool:
        """Whether a ``(source, test)`` pair is inside the scored set."""
        if source == ROOT_PATH or test == ROOT_PATH:
            return False
        if self._source_kinds.get(source) not in self._kinds:
            return False
        if self._test_kinds.get(test) not in self._kinds:
            return False
        if any(_under(source, prefix) for prefix in self._truth.excluded_source):
            return False
        return not any(_under(test, prefix) for prefix in self._truth.excluded_test)


def engine_pairs(comparison: Comparison) -> tuple[tuple[str, str], ...]:
    """Return the engine's whole correspondence set, root pair included.

    Scoping happens in `score_engine_pair`; this is the raw record, in the
    order `redlines.alignment.Alignment` reports it.

    :param comparison: the comparison to read.
    :return: ``(source address, test address)`` pairs.
    """
    return tuple(
        (pair.source_path, pair.test_path) for pair in comparison.alignment.pairs
    )


def _link_counts(
    reported: Iterable[tuple[str, str]],
    truth: Truth,
    scope: _Scope,
) -> LinkCounts:
    """Count reported pairs against ground truth inside one scope."""
    scored = [pair for pair in reported if scope.allows(*pair)]
    wanted = [pair for pair in sorted(truth.links) if scope.allows(*pair)]
    hits = sum(1 for pair in scored if pair in truth.links)
    spurious = sum(
        1
        for source, test in scored
        if source in truth.deleted or test in truth.inserted
    )
    return LinkCounts(
        reported=len(scored), truth=len(wanted), hits=hits, spurious=spurious
    )


def score_engine_pair(
    *,
    pair: str,
    tier: str,
    labels: LabelFile,
    comparison: Comparison,
    source_tree: BlockTree,
    test_tree: BlockTree,
    passes: Sequence[PassCounts] = (),
) -> PairScore:
    """Score one pair's `redlines.comparison.Comparison` against its labels.

    :param pair: the pair id.
    :param tier: ``synthetic`` or ``hand``.
    :param labels: the loaded label file.
    :param comparison: what `redlines.comparison.compare` returned for it.
    :param source_tree: the source tree the comparison used.
    :param test_tree: the test tree.
    :param passes: the per-pass table, from `pass_table`; empty to skip it.
    :return: the `PairScore`.
    """
    truth = truth_for(labels)
    source_kinds = _kinds(source_tree)
    test_kinds = _kinds(test_tree)
    everything = _Scope(
        truth,
        source_kinds=source_kinds,
        test_kinds=test_kinds,
        kinds=LABELLED_KINDS,
    )
    flat = _Scope(
        truth,
        source_kinds=source_kinds,
        test_kinds=test_kinds,
        kinds=FLAT_ADDRESSABLE_KINDS,
    )
    reported = engine_pairs(comparison)

    moves = tuple(
        (change.source_address, change.test_address)
        for change in comparison.changes
        if change.kind is ChangeKind.MOVE
        and change.source_address is not None
        and change.test_address is not None
    )
    renumbers = tuple(
        (
            change.source_address,
            change.test_address,
            change.source_label,
            change.test_label,
        )
        for change in comparison.changes
        if change.source_address is not None
        and change.test_address is not None
        and change.source_label != change.test_label
    )
    verdicts = {
        (verdict.source, verdict.test): verdict.verdict
        for verdict in labels.move_verdicts
    }
    unreviewed = tuple(
        move for move in moves if move not in truth.moves and move not in verdicts
    )
    wrong = tuple(
        move
        for move in moves
        if move not in truth.moves and verdicts.get(move) == "wrong"
    )

    return PairScore(
        pair=pair,
        tier=tier,
        plan=labels.provenance.plan,
        links=_link_counts(reported, truth, everything),
        flat_links=_link_counts(reported, truth, flat),
        moves=SetCounts(
            reported=len(moves),
            truth=len(truth.moves),
            hits=sum(1 for move in moves if move in truth.moves),
        ),
        renumbers=SetCounts(
            reported=len(renumbers),
            truth=len(truth.renumbers),
            hits=sum(1 for row in renumbers if row in truth.renumbers),
        ),
        passes=tuple(passes),
        unreviewed_moves=unreviewed,
        wrong_moves=wrong,
        skipped_splits=truth.skipped_splits,
        skipped_merges=truth.skipped_merges,
        override_rate=override_rate(labels),
        labels_signed=labels.review is not None,
        proposed_rows=sum(
            1 for row in labels.correspondences if row.status == "proposed"
        ),
        budget_exhausted=comparison.alignment.budget_exhausted,
    )


def score_baseline_pair(
    *,
    pair: str,
    tier: str,
    labels: LabelFile,
    reported: Sequence[tuple[str, str]],
    source_tree: BlockTree,
    test_tree: BlockTree,
) -> PairScore:
    """Score the flat 0.6 floor's lifted pairs against the same labels.

    Move and renumber counts are ``reported=0`` with the labelled truth intact,
    so the recall cell reads ``0.0`` rather than blank: 0.6 cannot express
    either, and that is the point of printing it.

    :param pair: the pair id.
    :param tier: ``synthetic`` or ``hand``.
    :param labels: the loaded label file.
    :param reported: what `benchmark.baselines.baseline_pairs` returned.
    :param source_tree: the source tree the lift used.
    :param test_tree: the test tree.
    :return: the `PairScore`.
    """
    truth = truth_for(labels)
    source_kinds = _kinds(source_tree)
    test_kinds = _kinds(test_tree)
    everything = _Scope(
        truth,
        source_kinds=source_kinds,
        test_kinds=test_kinds,
        kinds=LABELLED_KINDS,
    )
    flat = _Scope(
        truth,
        source_kinds=source_kinds,
        test_kinds=test_kinds,
        kinds=FLAT_ADDRESSABLE_KINDS,
    )
    return PairScore(
        pair=pair,
        tier=tier,
        plan=labels.provenance.plan,
        links=_link_counts(reported, truth, everything),
        flat_links=_link_counts(reported, truth, flat),
        moves=SetCounts(reported=0, truth=len(truth.moves), hits=0),
        renumbers=SetCounts(reported=0, truth=len(truth.renumbers), hits=0),
        skipped_splits=truth.skipped_splits,
        skipped_merges=truth.skipped_merges,
        override_rate=override_rate(labels),
        labels_signed=labels.review is not None,
        proposed_rows=sum(
            1 for row in labels.correspondences if row.status == "proposed"
        ),
    )


def pass_table(
    comparison: Comparison,
    *,
    labels: LabelFile,
    source_tree: BlockTree,
    test_tree: BlockTree,
    config: AlignmentConfig,
) -> tuple[PassCounts, ...]:
    """Measure what each alignment pass contributed to one pair.

    ``matches`` and ``wrong`` are read straight off the finished alignment.
    ``unique`` is **measured**, by re-running `redlines.alignment.align` once
    per droppable pass with that pass removed and counting the pairs it found
    that the reduced run did not. That is the evidence ADR-0008's review gate
    asks for; a pass with a low unique count and a high wrong count is the one
    to cut.

    :param comparison: the full-configuration comparison.
    :param labels: the pair's labels, for the wrong-match count.
    :param source_tree: the source tree.
    :param test_tree: the test tree.
    :param config: the alignment configuration the comparison ran under.
    :return: one `PassCounts` per name in `redlines.alignment.PASS_NAMES`.
    """
    truth = truth_for(labels)
    source_kinds = _kinds(source_tree)
    test_kinds = _kinds(test_tree)
    scope = _Scope(
        truth,
        source_kinds=source_kinds,
        test_kinds=test_kinds,
        kinds=LABELLED_KINDS,
    )
    by_pass: dict[str, list[tuple[str, str]]] = {name: [] for name in PASS_NAMES}
    for aligned in comparison.alignment.pairs:
        key = (aligned.source_path, aligned.test_path)
        if aligned.matched_by in by_pass and scope.allows(*key):
            by_pass[aligned.matched_by].append(key)

    without: dict[str, frozenset[tuple[str, str]]] = {}
    for name in DROPPABLE_PASSES:
        if name not in config.passes:
            continue
        reduced = AlignmentConfig(
            **{
                **config.to_dict(),
                "passes": tuple(p for p in config.passes if p != name),
            }
        )
        result = align(source_tree, test_tree, config=reduced)
        without[name] = frozenset(
            (pair.source_path, pair.test_path) for pair in result.pairs
        )

    counts = comparison.alignment.pass_counts
    table: list[PassCounts] = []
    for name in PASS_NAMES:
        found = by_pass[name]
        unique: int | None = None
        if name in without:
            unique = sum(1 for key in found if key not in without[name])
        table.append(
            PassCounts(
                name=name,
                total=counts.get(name, 0),
                matches=len(found),
                wrong=sum(1 for key in found if key not in truth.links),
                unique=unique,
            )
        )
    return tuple(table)


def aggregate(
    pairs: Sequence[PairScore], *, tier: str, engine: str, backend: str
) -> TierScore:
    """Sum a tier's pair scores into one row of the report.

    Micro-averaged: counts are summed and the ratios are computed once from
    the sums, so a two-block pair does not weigh as much as a two-hundred-block
    one and no float is accumulated across the corpus.

    :param pairs: the scored pairs, in any order; they are sorted here.
    :param tier: the tier name.
    :param engine: ``"1.0"`` or ``"0.6"``.
    :param backend: the resolved similarity backend.
    :return: the `TierScore`.
    """
    ordered = tuple(sorted(pairs, key=lambda score: score.pair))
    links = LinkCounts()
    flat_links = LinkCounts()
    moves = SetCounts()
    renumbers = SetCounts()
    for score in ordered:
        links = links + score.links
        flat_links = flat_links + score.flat_links
        moves = moves + score.moves
        renumbers = renumbers + score.renumbers

    table: list[PassCounts] = []
    for index, name in enumerate(PASS_NAMES):
        contributions = [
            score.passes[index] for score in ordered if index < len(score.passes)
        ]
        if not contributions:
            continue
        # Seeded from the first pair rather than from ``PassCounts(name=name)``:
        # a fresh one has ``unique=None``, and ``None`` is absorbing under
        # addition -- rightly, since "unmeasurable" plus a number is not a
        # number -- so starting from the empty row would erase every unique
        # count in the corpus.
        total = contributions[0]
        for counts in contributions[1:]:
            total = total + counts
        table.append(total)
    return TierScore(
        tier=tier,
        engine=engine,
        backend=backend,
        pairs=ordered,
        links=links,
        flat_links=flat_links,
        moves=moves,
        renumbers=renumbers,
        passes=tuple(table),
    )
