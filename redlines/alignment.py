"""Which source block corresponds to which test block, and how we know (#131).

`align` takes two `redlines.blocks.BlockTree` objects and returns an
`Alignment`: a flat, plain-data record of correspondence. Every pair carries
both ADR-0029 addresses, the name of the pass that found it, and the
similarity that pass measured::

    from redlines.alignment import align
    from redlines.pipeline import read_document

    alignment = align(read_document(old), read_document(new))
    for pair in alignment.pairs:
        print(pair.source_path, "->", pair.test_path, pair.matched_by)

It is plain data on purpose. It holds addresses rather than `Block`
references, so it serialises for debugging and for the benchmark harness
(ADR-0021); it returns *every* pair, unchanged ones included, because the
change tree, the filters, the statistics and the benchmark's correspondence
metric all need the ones that produced no change; and it lists every unmatched
block rather than only the root of an inserted subtree, because collapsing a
subtree to its root is presentation and belongs to the change tree.

Nothing here mutates a tree. Nothing here reads `Block.matched_by` or
`Block.confidence`: those are the *reader's* answer to "how do you know?", and
ADR-0030 forbids a reader's guess from steering alignment. Alignment is over
``text``, with ``role`` as a bounded tie-break between candidates that already
scored equal (R2). `AlignedPair.matched_by` is alignment's own answer to the
same question, on a different object, and the collision of names is deliberate.

The walk
--------

The passes ADR-0008 named run over an **anchored sibling-scoped descent**
(ADR-0032), not over a flattened tree. A FIFO queue starts with the root pair,
which is given rather than found; each entry aligns one sibling group and
pushes every new pair back onto the queue. Scope is what makes a label mean
something -- eight schedule items with pairwise similarity 0.70-0.80 are
near-ties across a document and trivially distinguished among their own
siblings -- and it is what keeps the cost down.

Within one sibling group the order is fixed (`PASS_NAMES` is the order):

===  ==============  ====================================================
 #   Pass            Decides on
===  ==============  ====================================================
 0   *cell rule*     sibling index, inside a ``row``. Total; recorded as
                     ``positional``
 1   ``exact``       the match key, within a kind class
 2   ``label``       ``Block.label`` equality, above ``label_min_similarity``
 3   ``structural``  nothing; unmatched containers pair positionally so the
                     descent can continue into them
 4   ``fuzzy``       token similarity, gap-scoped and window-capped
 5   ``positional``  nothing; leftovers in one gap, in order, above
                     ``positional_min_similarity``
===  ==============  ====================================================

``move`` is the sixth name and the only global work: it runs after the descent
and before the positional fill-in, over what is still unmatched on both sides.

**The order is load-bearing, twice.** ``exact`` must precede ``label``, or
renumbering detection inverts: in the sample pair source clause 3.3 and test
clause 3.4 are byte-identical, so ``exact`` pairs them and the label
difference is read straight off, while a ``label`` pass running first would
match source ``3.3`` to test ``3.3`` -- which in that document is the *newly
inserted* clause, scoring 0.20 against it. And ``move`` must precede
``positional``, or the fill-in eats a moved block into a wrong same-parent
slot whenever a section both loses and gains a clause. That is why
`AlignmentConfig.passes` controls inclusion only and never order.

Cost
----

Three deterministic bounds, because ADR-0008 permits a quadratic worst case
and N2 wants 2,000 blocks in under five seconds. After ``exact``, ``label``
and ``structural``, the matched siblings are **anchors** that partition the
group; ``fuzzy`` compares only source-gap against test-gap. Inside a large
gap a test block is compared only against source blocks within
``fuzzy_window`` rank positions of it. Behind both sits one run-wide
``max_comparisons`` counter: when it is spent, the site that spent it stops
generating candidates, its blocks fall through to the fill-in or to unmatched,
and `Alignment.budget_exhausted` says so on the wire. Silence is the safe
failure; silent silence is not.

Ties
----

Every maximum is taken under one stated, total order (N1, #135): highest
score, then the candidate whose ``role`` equals the other side's, then
earliest source document-order position, then earliest test position. Role
never *creates* a match, it only orders equals. No ``set`` is iterated
anywhere in this module, because ``str.__hash__`` is seeded.

Moves and renumbers
-------------------

Neither is a separate search. A pair is a **move** when its source and test
parents do not correspond (or, once the move pass lands, when it crosses its
own siblings); a pair is a **renumber** when its parents correspond and its
labels differ. Both are read off the record and recorded on `AlignedPair` as
``moved`` and ``renumbered``, so the change tree does not recompute them.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from .blocks import BLOCK_KINDS, ROOT_PATH, BlockKind, _reject_unknown_keys
from .similarity import (
    REQUESTABLE_BACKENDS,
    SequenceScorer,
    resolve_backend,
    similarity,
    tokens,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from .blocks import Block, BlockTree


__all__: tuple[str, ...] = (
    "PASS_NAMES",
    "RESERVED_PASS_NAMES",
    "MANDATORY_PASSES",
    "KIND_CLASSES",
    "AlignmentConfig",
    "DEFAULT_ALIGNMENT",
    "AlignedPair",
    "Alignment",
    "align",
)


PASS_NAMES: Final[tuple[str, ...]] = (
    "exact",
    "label",
    "structural",
    "fuzzy",
    "move",
    "positional",
)
"""The passes, in the order they run (ADR-0032). The order is not configurable.

A **closed** vocabulary, unlike ADR-0030's open reader vocabulary: these name
our own passes, no user-supplied rule sits behind them, and a consumer
switching on `AlignedPair.matched_by` should be able to switch exhaustively.
"""

RESERVED_PASS_NAMES: Final[tuple[str, ...]] = ("root", "unmatched")
"""Two values that are not passes.

``"root"`` is the root pair, which no pass found because it is given.
``"unmatched"`` is what an insert or delete change node carries in the same
field, having no pair at all; nothing in this module emits it.
"""

MANDATORY_PASSES: Final[tuple[str, ...]] = ("exact", "structural", "positional")
"""The passes `AlignmentConfig` will not let you drop.

``exact`` and ``structural`` are the descent's anchors -- without them a
container never pairs and the walk stops at it -- and ``positional`` is its
fill-in. ``label``, ``fuzzy`` and ``move`` are droppable, which is what
ADR-0008's review gate needs in order to be exercised.
"""

KIND_CLASSES: Final[Mapping[str, str]] = {
    "heading": "heading",
    "paragraph": "text",
    "list_item": "text",
    "section": "container",
    "document": "container",
    "table": "table",
    "row": "row",
    "cell": "cell",
    "unknown": "unknown",
}
"""Which `redlines.blocks.BlockKind` values may match each other.

Grouping ``paragraph`` with ``list_item`` is deliberate: a clause that lost
its number is still the same clause. Keeping ``cell`` and ``row`` apart from
``text`` is what stops a table cell matching a paragraph.
"""

_STRUCTURAL_CLASSES: Final[tuple[str, ...]] = ("container", "table")
_CONTAINER_SEPARATOR: Final[str] = "\x1f"
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")

_CONFIG_KEYS: Final[set[str]] = {
    "passes",
    "similarity",
    "fuzzy_min_similarity",
    "label_min_similarity",
    "positional_min_similarity",
    "move_min_similarity",
    "move_tie_margin",
    "move_min_tokens",
    "move_kinds",
    "fuzzy_window",
    "table_fuzzy",
    "max_comparisons",
}
_PAIR_KEYS: Final[set[str]] = {
    "source_path",
    "test_path",
    "matched_by",
    "confidence",
    "moved",
    "renumbered",
}
_ALIGNMENT_KEYS: Final[set[str]] = {
    "pairs",
    "inserted",
    "deleted",
    "config",
    "backend",
    "pass_counts",
    "budget_exhausted",
}


def _check_ratio(name: str, value: float) -> None:
    """Raise unless ``value`` is a similarity, which is 0.0 to 1.0 inclusive."""
    if not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0.0 and 1.0, got {value}")


@dataclass(frozen=True, slots=True)
class AlignmentConfig:
    """Every knob alignment has, and the only place they live (ADR-0032).

    Frozen and serialisable, because #135 requires the configuration in force
    to be part of the output: determinism is promised *per configuration*, so
    a reader of the output has to be able to see which one.

    **The numbers are provisional; the knobs are not.** Each default below is
    a measured justification rather than a tuned value, and ADR-0021's
    benchmark exists so they can be set from evidence. Every one of them
    defaults toward silence, because ADR-0009's gate is asymmetric: telling a
    lawyer a clause moved when it did not costs more trust than saying
    nothing.

    :param passes: which passes run. **Inclusion only** -- the order is fixed
        as `PASS_NAMES` and any tuple is re-ordered into it, because two
        orderings are load-bearing and a reordered run would report pass names
        that no longer mean what the record says they mean. `MANDATORY_PASSES`
        cannot be dropped, and an unknown name raises.
    :param similarity: the backend to *ask* for -- ``"auto"``, ``"difflib"``
        or ``"rapidfuzz"``. The resolved name lands on `Alignment.backend`;
        both are kept, because "auto picked difflib" and "difflib was
        demanded" are different facts.
    :param fuzzy_min_similarity: what the ``fuzzy`` pass will accept.
    :param label_min_similarity: how alike two blocks must be before an equal
        label is allowed to pair them. Measured: it is what rejects the sample
        pair's old clause 3.3 against the newly inserted 3.3, which score 0.20
        against each other. Two blocks that are both empty bypass it, since a
        floor over no text is meaningless.
    :param positional_min_similarity: the same number at the other end of the
        order, for the fill-in.
    :param move_min_similarity: what the move pass will accept. Distinct
        sibling clauses in the sample pair score 0.16-0.44 against each other,
        so it does not need to be low to work.
    :param move_tie_margin: how far a move candidate must beat the runner-up.
        Measured worst case in the sample pair: 0.85 against the true partner
        and 0.732 against the best wrong one, a margin of 0.118.
    :param move_min_tokens: how much text a block needs before it can be
        called moved. A one-word cell reading "Supplier" appearing in another
        row is not a move.
    :param move_kinds: which kinds may be reported as moved. Container moves
        are not reported in 1.0; they surface as their children moving, which
        is honest and cannot be wrong.
    :param fuzzy_window: how many rank positions either side of a test block,
        among the unmatched in its gap, the fuzzy pass will look. Ordinary
        documents never reach it, because a gap of 25 or fewer blocks makes
        the window the whole gap.
    :param table_fuzzy: whether the fuzzy pass runs inside a table. Off:
        rows of near-identical content are exactly what ADR-0008 warns fuzzy
        thresholds misfire on, so rows match by exact key and then by position
        (#134).
    :param max_comparisons: one run-wide budget, spent by the fuzzy pass and
        the move pass. Not per pass and not per gap: the guarantee people want
        is about the whole run.
    """

    passes: tuple[str, ...] = PASS_NAMES
    similarity: str = "auto"
    fuzzy_min_similarity: float = 0.60
    label_min_similarity: float = 0.35
    positional_min_similarity: float = 0.35
    move_min_similarity: float = 0.80
    move_tie_margin: float = 0.10
    move_min_tokens: int = 8
    move_kinds: tuple[str, ...] = ("paragraph", "list_item", "heading")
    fuzzy_window: int = 25
    table_fuzzy: bool = False
    max_comparisons: int = 2_000_000

    def __post_init__(self) -> None:
        """Canonicalise ``passes`` and reject a configuration that cannot run."""
        seen: dict[str, None] = {}
        for name in self.passes:
            if name not in PASS_NAMES:
                allowed = ", ".join(PASS_NAMES)
                reserved = ", ".join(RESERVED_PASS_NAMES)
                raise ValueError(
                    f"{name!r} is not an alignment pass; the closed set is: "
                    f"{allowed} ({reserved} are reserved and name no pass)"
                )
            if name in seen:
                raise ValueError(f"the pass {name!r} is listed more than once")
            seen[name] = None
        missing = [name for name in MANDATORY_PASSES if name not in seen]
        if missing:
            dropped = ", ".join(missing)
            keep = ", ".join(MANDATORY_PASSES)
            raise ValueError(
                f"the pass {dropped} cannot be dropped; {keep} are the "
                "descent's anchors and its fill-in"
            )
        # Inclusion only: whatever order was written, the run order is the one
        # PASS_NAMES states, and to_dict() reports that rather than the input.
        object.__setattr__(
            self, "passes", tuple(name for name in PASS_NAMES if name in seen)
        )
        if self.similarity not in REQUESTABLE_BACKENDS:
            allowed = ", ".join(REQUESTABLE_BACKENDS)
            raise ValueError(
                f"{self.similarity!r} is not a similarity backend; the set "
                f"is: {allowed}"
            )
        _check_ratio("fuzzy_min_similarity", self.fuzzy_min_similarity)
        _check_ratio("label_min_similarity", self.label_min_similarity)
        _check_ratio("positional_min_similarity", self.positional_min_similarity)
        _check_ratio("move_min_similarity", self.move_min_similarity)
        _check_ratio("move_tie_margin", self.move_tie_margin)
        if self.move_min_tokens < 0:
            raise ValueError(
                f"move_min_tokens must not be negative, got {self.move_min_tokens}"
            )
        object.__setattr__(self, "move_kinds", tuple(self.move_kinds))
        for kind in self.move_kinds:
            if kind not in BLOCK_KINDS:
                allowed = ", ".join(BLOCK_KINDS)
                raise ValueError(
                    f"{kind!r} is not a block kind; the closed set is: {allowed}"
                )
        if self.fuzzy_window < 1:
            raise ValueError(
                f"fuzzy_window must be at least 1, got {self.fuzzy_window}"
            )
        if self.max_comparisons < 0:
            raise ValueError(
                f"max_comparisons must not be negative, got {self.max_comparisons}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return the configuration as a JSON-serialisable dict.

        Every key is always present and always in the order the fields are
        declared, so two equal configurations serialise identically (N1).

        :return: a dict carrying every field.
        """
        return {
            "passes": list(self.passes),
            "similarity": self.similarity,
            "fuzzy_min_similarity": self.fuzzy_min_similarity,
            "label_min_similarity": self.label_min_similarity,
            "positional_min_similarity": self.positional_min_similarity,
            "move_min_similarity": self.move_min_similarity,
            "move_tie_margin": self.move_tie_margin,
            "move_min_tokens": self.move_min_tokens,
            "move_kinds": list(self.move_kinds),
            "fuzzy_window": self.fuzzy_window,
            "table_fuzzy": self.table_fuzzy,
            "max_comparisons": self.max_comparisons,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AlignmentConfig:
        """Rebuild a configuration from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces. Every key
            falls back to the field's default.
        :return: the reconstructed `AlignmentConfig`.
        :raises ValueError: if the mapping carries a key this model does not
            know, or a value `__post_init__` rejects.
        """
        _reject_unknown_keys(data, _CONFIG_KEYS, "alignment config")
        defaults = cls()
        return cls(
            passes=tuple(data.get("passes", defaults.passes)),
            similarity=str(data.get("similarity", defaults.similarity)),
            fuzzy_min_similarity=float(
                data.get("fuzzy_min_similarity", defaults.fuzzy_min_similarity)
            ),
            label_min_similarity=float(
                data.get("label_min_similarity", defaults.label_min_similarity)
            ),
            positional_min_similarity=float(
                data.get(
                    "positional_min_similarity", defaults.positional_min_similarity
                )
            ),
            move_min_similarity=float(
                data.get("move_min_similarity", defaults.move_min_similarity)
            ),
            move_tie_margin=float(
                data.get("move_tie_margin", defaults.move_tie_margin)
            ),
            move_min_tokens=int(data.get("move_min_tokens", defaults.move_min_tokens)),
            move_kinds=tuple(data.get("move_kinds", defaults.move_kinds)),
            fuzzy_window=int(data.get("fuzzy_window", defaults.fuzzy_window)),
            table_fuzzy=bool(data.get("table_fuzzy", defaults.table_fuzzy)),
            max_comparisons=int(
                data.get("max_comparisons", defaults.max_comparisons)
            ),
        )


DEFAULT_ALIGNMENT: Final[AlignmentConfig] = AlignmentConfig()
"""The configuration `align` uses when it is given none."""


@dataclass(frozen=True, slots=True)
class AlignedPair:
    """One correspondence: this source block is that test block.

    :param source_path: the block's address in the source tree (ADR-0029).
    :param test_path: its address in the test tree.
    :param matched_by: which pass found it -- one of `PASS_NAMES`, or
        ``"root"`` for the root pair, which is given rather than found. This
        is alignment's own answer to "how do you know?", and it is a different
        field on a different object from the reader's `Block.matched_by`
        (ADR-0030).
    :param confidence: the similarity the pass measured, 0.0 to 1.0. 1.0 for
        an exact or structural match. A pass that decides on position rather
        than content still records what the two blocks actually score, so a
        low-confidence positional pair is visible as such.
    :param moved: whether the two blocks' parents fail to correspond, or the
        pair crosses its own siblings.
    :param renumbered: whether the parents correspond and the labels differ.
    """

    source_path: str
    test_path: str
    matched_by: str
    confidence: float
    moved: bool = False
    renumbered: bool = False

    def __post_init__(self) -> None:
        """Reject a pair that could not have come from a pass."""
        if not self.source_path or not self.test_path:
            raise ValueError("an aligned pair needs both addresses")
        if self.matched_by not in PASS_NAMES and self.matched_by != "root":
            allowed = ", ".join((*PASS_NAMES, "root"))
            raise ValueError(
                f"{self.matched_by!r} is not an alignment pass; a pair is "
                f"matched by one of: {allowed}"
            )
        _check_ratio("confidence", self.confidence)

    def to_dict(self) -> dict[str, Any]:
        """Return the pair as a JSON-serialisable dict.

        ``confidence`` is rounded to four places here and nowhere else: full
        precision is kept for every comparison, and rounding happens once, at
        serialisation (N1).

        :return: a dict with the keys ``source_path``, ``test_path``,
            ``matched_by``, ``confidence``, ``moved`` and ``renumbered``.
        """
        return {
            "source_path": self.source_path,
            "test_path": self.test_path,
            "matched_by": self.matched_by,
            "confidence": round(self.confidence, 4),
            "moved": self.moved,
            "renumbered": self.renumbered,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> AlignedPair:
        """Rebuild a pair from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `AlignedPair`.
        :raises ValueError: if a key is unknown or a required one is missing.
        """
        _reject_unknown_keys(data, _PAIR_KEYS, "aligned pair")
        try:
            return cls(
                source_path=str(data["source_path"]),
                test_path=str(data["test_path"]),
                matched_by=str(data["matched_by"]),
                confidence=float(data["confidence"]),
                moved=bool(data.get("moved", False)),
                renumbered=bool(data.get("renumbered", False)),
            )
        except KeyError as missing:
            raise ValueError(
                f"aligned pair is missing the key {missing.args[0]!r}"
            ) from None


@dataclass(frozen=True, slots=True)
class Alignment:
    """What `align` found: every pair, everything left over, and how.

    :param pairs: every correspondence, in source document order with the root
        pair first. Unchanged pairs are included: the change tree decides
        which pairs become nodes, and the benchmark's correspondence metric
        needs the ones that produced no change.
    :param inserted: the addresses of test blocks nothing matched, in document
        order. Every one of them, not only the root of an inserted subtree --
        collapsing a subtree is presentation, and belongs to the change tree.
    :param deleted: the addresses of unmatched source blocks, likewise.
    :param config: the configuration that produced all of it (#135).
    :param backend: the **resolved** similarity backend that ran, so a reader
        can tell which of the two measured these numbers.
    :param pass_counts: how many pairs each pass contributed, ``"root"``
        included and zeros present. This is the evidence ADR-0008's review
        gate asks for: a pass that contributes little is a pass to cut.
    :param budget_exhausted: whether ``max_comparisons`` ran out. When it is
        true, "nothing more was found" and "we stopped looking" are different
        answers and this is the only thing that tells them apart.
    """

    pairs: tuple[AlignedPair, ...]
    inserted: tuple[str, ...]
    deleted: tuple[str, ...]
    config: AlignmentConfig
    backend: str
    pass_counts: Mapping[str, int]
    budget_exhausted: bool = False
    _by_source: dict[str, str] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )
    _by_test: dict[str, str] = field(
        init=False, repr=False, compare=False, default_factory=dict
    )

    def __post_init__(self) -> None:
        """Freeze the sequences, fix the shape of ``pass_counts``, index the pairs."""
        object.__setattr__(self, "pairs", tuple(self.pairs))
        object.__setattr__(self, "inserted", tuple(self.inserted))
        object.__setattr__(self, "deleted", tuple(self.deleted))
        for name in self.pass_counts:
            if name not in PASS_NAMES and name != "root":
                allowed = ", ".join(("root", *PASS_NAMES))
                raise ValueError(
                    f"{name!r} is not an alignment pass; pass_counts counts: "
                    f"{allowed}"
                )
        # Always the same keys in the same order, whatever was handed in, so
        # the wire shape does not depend on which passes happened to fire.
        object.__setattr__(
            self,
            "pass_counts",
            {
                name: int(self.pass_counts.get(name, 0))
                for name in ("root", *PASS_NAMES)
            },
        )
        object.__setattr__(
            self,
            "_by_source",
            {pair.source_path: pair.test_path for pair in self.pairs},
        )
        object.__setattr__(
            self, "_by_test", {pair.test_path: pair.source_path for pair in self.pairs}
        )

    def test_for(self, source_path: str) -> str | None:
        """Return the test address this source address corresponds to.

        :param source_path: an address in the source tree.
        :return: the test address, or ``None`` if the block was deleted.
        """
        return self._by_source.get(source_path)

    def source_for(self, test_path: str) -> str | None:
        """Return the source address this test address corresponds to.

        :param test_path: an address in the test tree.
        :return: the source address, or ``None`` if the block was inserted.
        """
        return self._by_test.get(test_path)

    def to_dict(self) -> dict[str, Any]:
        """Return the whole alignment as a JSON-serialisable dict.

        Keys are in the order the fields are declared, never sorted, so two
        equal alignments serialise to identical bytes (N1, #135).

        :return: a dict with the keys ``pairs``, ``inserted``, ``deleted``,
            ``config``, ``backend``, ``pass_counts`` and ``budget_exhausted``.
        """
        return {
            "pairs": [pair.to_dict() for pair in self.pairs],
            "inserted": list(self.inserted),
            "deleted": list(self.deleted),
            "config": self.config.to_dict(),
            "backend": self.backend,
            "pass_counts": dict(self.pass_counts),
            "budget_exhausted": self.budget_exhausted,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Alignment:
        """Rebuild an alignment from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `Alignment`, equal to the one serialised.
        :raises ValueError: if a key is unknown or ``backend`` is missing.
        """
        _reject_unknown_keys(data, _ALIGNMENT_KEYS, "alignment")
        if "backend" not in data:
            raise ValueError("alignment is missing the key 'backend'")
        return cls(
            pairs=tuple(
                AlignedPair.from_dict(pair) for pair in data.get("pairs", ()) or ()
            ),
            inserted=tuple(str(path) for path in data.get("inserted", ()) or ()),
            deleted=tuple(str(path) for path in data.get("deleted", ()) or ()),
            config=AlignmentConfig.from_dict(data.get("config", {}) or {}),
            backend=str(data["backend"]),
            pass_counts=dict(data.get("pass_counts", {}) or {}),
            budget_exhausted=bool(data.get("budget_exhausted", False)),
        )


def align(
    source: BlockTree,
    test: BlockTree,
    *,
    config: AlignmentConfig = DEFAULT_ALIGNMENT,
) -> Alignment:
    """Align two block trees and report every correspondence.

    Neither tree is read for anything but structure, ``text``, ``label``,
    ``kind`` and -- as a tie-break between equals only -- ``role``. Neither is
    mutated, and neither block's ``matched_by`` or ``confidence`` is consulted
    (ADR-0030).

    :param source: the earlier document.
    :param test: the later one.
    :param config: which passes run and on what terms; `DEFAULT_ALIGNMENT` if
        left out.
    :return: an `Alignment` carrying the pairs, the leftovers on both sides,
        the configuration, the resolved backend, the per-pass counts and
        whether the comparison budget ran out.
    :raises ValueError: if ``config.similarity`` names a backend that is not
        installed.
    """
    return _Aligner(source, test, config).run()


# --------------------------------------------------------------------------
# The engine. Everything below is private; the shapes above are the contract.
# --------------------------------------------------------------------------


def _normalise(text: str) -> str:
    """Collapse whitespace runs to one space and strip the ends.

    Case is deliberately not folded: a case change is a real change, and an
    ``exact`` match that ignored it would report no change at all.
    """
    return _WHITESPACE.sub(" ", text).strip()


def _longest_increasing_subsequence(
    anchors: Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return the longest run of anchors that is increasing on both sides.

    ``anchors`` are ``(source position, test position)`` pairs, sorted by
    source position with no repeats. Patience sorting, O(k log k). The
    subsequence is the monotone spine the gaps hang off; anchors outside it
    have genuinely crossed, which is what the move pass (#132) will report.

    :param anchors: the matched sibling positions.
    :return: the spine, in order.
    """
    if not anchors:
        return []
    tails: list[int] = []
    tail_index: list[int] = []
    previous: list[int] = [-1] * len(anchors)
    for position, (_, test_position) in enumerate(anchors):
        slot = bisect_left(tails, test_position)
        if slot == len(tails):
            tails.append(test_position)
            tail_index.append(position)
        else:
            tails[slot] = test_position
            tail_index[slot] = position
        previous[position] = tail_index[slot - 1] if slot else -1
    spine: list[tuple[int, int]] = []
    cursor = tail_index[-1]
    while cursor != -1:
        spine.append(anchors[cursor])
        cursor = previous[cursor]
    spine.reverse()
    return spine


class _Side:
    """One tree, flattened into document order with parents and caches.

    Node indices are assigned depth-first in document order, so ``sorted()``
    over them is document order and no ``set`` needs iterating to get there.
    """

    __slots__ = ("blocks", "children", "keys", "parents", "token_cache")

    def __init__(self, tree: BlockTree) -> None:
        self.blocks: list[Block] = []
        self.parents: list[int] = []
        self.children: list[tuple[int, ...]] = []
        self.token_cache: dict[int, tuple[str, ...]] = {}
        self.keys: dict[int, str | None] = {}
        self._add(tree.root, -1)

    def _add(self, block: Block, parent: int) -> int:
        index = len(self.blocks)
        self.blocks.append(block)
        self.parents.append(parent)
        self.children.append(())
        self.children[index] = tuple(
            self._add(child, index) for child in block.children
        )
        return index

    def __len__(self) -> int:
        return len(self.blocks)

    def path(self, index: int) -> str:
        """The block's ADR-0029 address, or `ROOT_PATH` for a path-less root."""
        return self.blocks[index].path or ROOT_PATH

    def klass(self, index: int) -> str:
        """The block's kind class; kinds only match within one (ADR-0032)."""
        return KIND_CLASSES.get(self.blocks[index].kind.value, "unknown")

    def tokens(self, index: int) -> tuple[str, ...]:
        """The block's own text as tokens, computed once per block.

        A ``row`` is the one exception, and it is the same exception the match
        key makes: a row carries no text of its own, so its content is its
        cells' texts. Without that, every row scores 1.0 against every other
        row -- two empty sequences are alike -- and neither the positional
        floor nor ``table_fuzzy`` could mean anything inside a table.
        """
        cached = self.token_cache.get(index)
        if cached is None:
            block = self.blocks[index]
            text = block.text
            if not text.strip() and block.kind is BlockKind.ROW:
                text = " ".join(child.text for child in block.children)
            cached = tokens(text)
            self.token_cache[index] = cached
        return cached

    def key(self, index: int) -> str | None:
        """The block's match key, or ``None`` when it has none (ADR-0032).

        A text-bearing block keys on its normalised text. A container keys on
        its ``heading`` child's label and text where it has one, and a ``row``
        on its cells' texts joined with a unit separator. Everything else --
        a headingless section, a table, a row of empty cells -- has no key and
        falls through to the ``structural`` pass, which is exactly why that
        pass exists.
        """
        if index in self.keys:
            return self.keys[index]
        block = self.blocks[index]
        computed: str | None = None
        text = _normalise(block.text)
        if text:
            computed = text
        else:
            for child in block.children:
                if child.kind is BlockKind.HEADING and (child.label or child.text):
                    label = child.label or ""
                    computed = f"{label}{_CONTAINER_SEPARATOR}{_normalise(child.text)}"
                    break
            else:
                if block.kind is BlockKind.ROW:
                    cells = [_normalise(child.text) for child in block.children]
                    if any(cells):
                        computed = _CONTAINER_SEPARATOR.join(cells)
        self.keys[index] = computed
        return computed


@dataclass(frozen=True, slots=True)
class _Match:
    """What the engine records for one source block while it works."""

    test: int
    matched_by: str
    confidence: float


class _Aligner:
    """One run of `align`. Holds the mutable state the passes share."""

    __slots__ = (
        "backend",
        "budget_exhausted",
        "comparisons",
        "config",
        "counts",
        "matched_test",
        "pairs",
        "queue",
        "source",
        "test",
    )

    def __init__(
        self, source: BlockTree, test: BlockTree, config: AlignmentConfig
    ) -> None:
        self.config = config
        self.backend = resolve_backend(config.similarity)
        self.source = _Side(source)
        self.test = _Side(test)
        self.pairs: dict[int, _Match] = {}
        self.matched_test: dict[int, int] = {}
        self.counts: dict[str, int] = {name: 0 for name in ("root", *PASS_NAMES)}
        self.comparisons = 0
        self.budget_exhausted = False
        self.queue: deque[tuple[int, int]] = deque()

    # -- bookkeeping -------------------------------------------------------

    def _record(self, source: int, test: int, matched_by: str, score: float) -> None:
        """Pair two blocks and queue them, so their children align next."""
        self.pairs[source] = _Match(test=test, matched_by=matched_by, confidence=score)
        self.matched_test[test] = source
        self.counts[matched_by] += 1
        self.queue.append((source, test))

    def _spend(self) -> bool:
        """Take one comparison from the run-wide budget, or report it spent.

        Checked at every candidate-generation site the ADR names -- the fuzzy
        gap-window and both stages of the move pass -- and nowhere else. The
        ``exact``, ``label``, ``structural`` and ``positional`` passes are
        linear in the sibling group and are not budgeted.
        """
        if self.comparisons >= self.config.max_comparisons:
            self.budget_exhausted = True
            return False
        self.comparisons += 1
        return True

    def _pair_score(self, source: int, test: int) -> float:
        """The exact similarity of two blocks' own text.

        Two blocks that are both empty score 1.0 rather than 0.0: a container
        carries its text in its children, and a floor over no text is
        meaningless.
        """
        source_tokens = self.source.tokens(source)
        test_tokens = self.test.tokens(test)
        if not source_tokens and not test_tokens:
            return 1.0
        return similarity(source_tokens, test_tokens, backend=self.backend)

    def _roles_differ(self, source: int, test: int) -> int:
        """0 when the two blocks share a role, 1 otherwise (the R2 tie-break).

        Sorted ascending, so equal roles come first. Role never creates a
        match; it only orders candidates that already scored the same.
        """
        source_role = self.source.blocks[source].role
        return 0 if source_role == self.test.blocks[test].role else 1

    # -- the run -----------------------------------------------------------

    def run(self) -> Alignment:
        """Align the two trees and build the record."""
        self._record(0, 0, "root", 1.0)
        self._descend()
        if "move" in self.config.passes:
            self._move_pass()
            self._descend()
        while self._positional_round():
            self._descend()
        return self._result()

    def _descend(self) -> None:
        """Drain the queue, aligning one sibling group per matched pair."""
        while self.queue:
            source_parent, test_parent = self.queue.popleft()
            self._align_children(source_parent, test_parent)

    def _align_children(self, source_parent: int, test_parent: int) -> None:
        """Run passes 0 to 4 over one sibling group."""
        source_kids = list(self.source.children[source_parent])
        test_kids = list(self.test.children[test_parent])
        if not source_kids or not test_kids:
            return
        if (
            self.source.blocks[source_parent].kind is BlockKind.ROW
            and self.test.blocks[test_parent].kind is BlockKind.ROW
        ):
            self._align_cells(source_kids, test_kids)
            return

        free_source = [index for index in source_kids if index not in self.pairs]
        free_test = [index for index in test_kids if index not in self.matched_test]
        self._exact(free_source, free_test)
        if "label" in self.config.passes:
            self._label(free_source, free_test)
        self._structural(free_source, free_test)
        if "fuzzy" in self.config.passes and self._fuzzy_applies(source_parent):
            gaps = self._gaps(source_kids, test_kids, free_source, free_test)
            self._fuzzy(gaps, free_source, free_test)

    def _fuzzy_applies(self, source_parent: int) -> bool:
        """Whether the fuzzy pass runs in this group (#134's table rule)."""
        if self.source.blocks[source_parent].kind is BlockKind.TABLE:
            return self.config.table_fuzzy
        return True

    # -- pass 0: cells -----------------------------------------------------

    def _align_cells(self, source_kids: list[int], test_kids: list[int]) -> None:
        """Pair the cells of one row strictly by sibling index (#134).

        Total, and it short-circuits every other pass. The markdown reader
        pads ragged rows to full width, so the index *is* the column, and
        keying on the index rather than on an ``attrs["column"]`` value keeps
        this module free of any reader's vocabulary.

        Where the two rows have different cell counts, cells pair up to the
        shorter row and the surplus on either side is reported as an
        individual cell insert or delete: **a row never fails to match
        because of its cell count alone.** No column operations, no merged
        cells (ROADMAP 5.8).
        """
        for source, test in zip(source_kids, test_kids):
            self._record(source, test, "positional", self._pair_score(source, test))

    # -- pass 1: exact -----------------------------------------------------

    def _exact(self, free_source: list[int], free_test: list[int]) -> None:
        """Pair blocks with the same match key, within a kind class.

        O(k) through buckets consumed in document order, which is both the
        early exit ADR-0008 asks for and what makes section 7 pair with
        section 7 explainably, before any similarity is computed.
        """
        buckets: dict[tuple[str, str], list[int]] = {}
        for source in free_source:
            key = self.source.key(source)
            if key is None:
                continue
            buckets.setdefault((self.source.klass(source), key), []).append(source)
        for test in list(free_test):
            key = self.test.key(test)
            if key is None:
                continue
            bucket = buckets.get((self.test.klass(test), key))
            if not bucket:
                continue
            self._take(bucket.pop(0), test, "exact", 1.0, free_source, free_test)

    # -- pass 2: label -----------------------------------------------------

    def _label(self, free_source: list[int], free_test: list[int]) -> None:
        """Pair blocks carrying the same label, if their text agrees enough.

        The floor is what stops a renumbered clause matching the *new* clause
        that took its number: measured on the sample pair, the old 3.3 and the
        inserted 3.3 score 0.20, so at 0.35 both fall through to a delete and
        an insert, which is the honest answer. Labels arrive already
        normalised from the reader, so nothing is normalised again here.
        """
        buckets: dict[tuple[str, str], list[int]] = {}
        for source in free_source:
            label = self.source.blocks[source].label
            if not label:
                continue
            buckets.setdefault((self.source.klass(source), label), []).append(source)
        for test in list(free_test):
            label = self.test.blocks[test].label
            if not label:
                continue
            bucket = buckets.get((self.test.klass(test), label))
            if not bucket:
                continue
            source = bucket[0]
            score = self._pair_score(source, test)
            if score < self.config.label_min_similarity:
                # Leave the candidate in its bucket: another test block with
                # the same label may still be the one that belongs to it.
                continue
            bucket.pop(0)
            self._take(source, test, "label", score, free_source, free_test)

    # -- pass 3: structural ------------------------------------------------

    def _structural(self, free_source: list[int], free_test: list[int]) -> None:
        """Pair leftover containers positionally, so the descent can go on.

        A ``table`` or a section whose heading changed matches nothing by key
        and nothing by label, and if it stays unmatched its rows and clauses
        are never compared at all -- the prototype that skipped this pass
        failed to pair the sample pair's table and reported thirteen of its
        cells as moves. Pairing is within a kind class and in order, which is
        as much as position can honestly claim.
        """
        by_class: dict[str, tuple[list[int], list[int]]] = {}
        for source in free_source:
            klass = self.source.klass(source)
            if klass in _STRUCTURAL_CLASSES:
                by_class.setdefault(klass, ([], []))[0].append(source)
        for test in free_test:
            klass = self.test.klass(test)
            if klass in _STRUCTURAL_CLASSES:
                by_class.setdefault(klass, ([], []))[1].append(test)
        for sources, tests in by_class.values():
            for source, test in zip(sources, tests):
                self._take(source, test, "structural", 1.0, free_source, free_test)

    # -- pass 4: fuzzy -----------------------------------------------------

    def _fuzzy(
        self,
        gaps: list[tuple[list[int], list[int]]],
        free_source: list[int],
        free_test: list[int],
    ) -> None:
        """Pair the rest of a gap by token similarity, within a window.

        Candidates are scored once, collected, and then taken greedily in one
        stated total order -- highest score, then equal roles, then earliest
        source position, then earliest test position -- rather than by
        repeatedly rescanning for the current best. Same answer, no ``set``
        iterated, and the tie-break is written down rather than emergent.
        """
        floor = self.config.fuzzy_min_similarity
        window = self.config.fuzzy_window
        for gap_source, gap_test in gaps:
            if not gap_source or not gap_test:
                continue
            candidates: list[tuple[float, int, int, int]] = []
            for rank, test in enumerate(gap_test):
                test_tokens = self.test.tokens(test)
                if not test_tokens:
                    continue
                scorer = SequenceScorer(test_tokens, backend=self.backend)
                first = max(0, rank - window)
                last = min(len(gap_source), rank + window + 1)
                for offset in range(first, last):
                    source = gap_source[offset]
                    if self.source.klass(source) != self.test.klass(test):
                        continue
                    source_tokens = self.source.tokens(source)
                    if not source_tokens:
                        continue
                    if not self._spend():
                        break
                    score = scorer.score(source_tokens, floor=floor)
                    if score >= floor:
                        candidates.append(
                            (-score, self._roles_differ(source, test), source, test)
                        )
                if self.budget_exhausted:
                    break
            candidates.sort()
            for negated, _, source, test in candidates:
                if source in self.pairs or test in self.matched_test:
                    continue
                self._take(source, test, "fuzzy", -negated, free_source, free_test)
            if self.budget_exhausted:
                return

    # -- pass 5: positional ------------------------------------------------

    def _positional_round(self) -> bool:
        """Run the fill-in over every aligned sibling group.

        It runs after the move pass, and it repeats until it finds nothing:
        pairing two leftover containers gives the descent somewhere new to go,
        and their children's leftovers are only visible on the next round.

        :return: whether anything was paired.
        """
        made = False
        for source_parent in sorted(self.pairs):
            test_parent = self.pairs[source_parent].test
            if (
                self.source.blocks[source_parent].kind is BlockKind.ROW
                and self.test.blocks[test_parent].kind is BlockKind.ROW
            ):
                continue  # the cell rule is total; there is nothing to fill in
            source_kids = list(self.source.children[source_parent])
            test_kids = list(self.test.children[test_parent])
            free_source = [index for index in source_kids if index not in self.pairs]
            free_test = [index for index in test_kids if index not in self.matched_test]
            if not free_source or not free_test:
                continue
            gaps = self._gaps(source_kids, test_kids, free_source, free_test)
            floor = self.config.positional_min_similarity
            for gap_source, gap_test in gaps:
                for source, test in zip(gap_source, gap_test):
                    if self.source.klass(source) != self.test.klass(test):
                        continue
                    score = self._pair_score(source, test)
                    if score < floor:
                        continue
                    self._take(
                        source, test, "positional", score, free_source, free_test
                    )
                    made = True
        return made

    # -- the move pass, which task A2 fills in ------------------------------

    def _move_pass(self) -> None:
        """The global move pass (#132). **A hook: it matches nothing yet.**

        ``move`` is already in `PASS_NAMES` and in `AlignmentConfig.passes`,
        already counted in `Alignment.pass_counts`, and already positioned
        here -- after the descent, before the positional fill-in, with every
        pair it makes pushed back onto the queue so a moved block's children
        align in their new scope. What it does not yet do is search. Until
        #132 lands, a block that moved is reported as a delete and an insert,
        which is honest rather than wrong.

        What goes here (ADR-0032): over the blocks still unmatched on both
        sides, restricted to ``move_kinds`` and to blocks of at least
        ``move_min_tokens`` tokens, pair first by normalised text that is
        unique among the leftovers on *both* sides, then by best fuzzy score
        where it clears ``move_min_similarity`` and beats the runner-up by
        ``move_tie_margin``. Both stages spend `_spend`, and stop generating
        candidates when it is spent. Separately, anchors outside the spine
        `_longest_increasing_subsequence` returns for a sibling group have
        crossed, and are moves too; `_gaps` already computes that spine.

        `_moved` is where the classification lands, and it needs no change:
        it reads parent correspondence off the finished record, so any pair
        this hook creates across scopes is a move without being told.
        """

    # -- gaps --------------------------------------------------------------

    def _gaps(
        self,
        source_kids: list[int],
        test_kids: list[int],
        free_source: list[int],
        free_test: list[int],
    ) -> list[tuple[list[int], list[int]]]:
        """Partition a sibling group's leftovers by the anchors between them.

        An **anchor** is a source child already paired with a child of this
        same test group. Anchors that cross each other cannot both bound a
        gap, so the monotone spine
        (`_longest_increasing_subsequence`) does the bounding and the rest are
        ignored here. Everything before the first spine anchor, between two of
        them, and after the last is one gap, and the fuzzy and positional
        passes never look across a boundary.

        :return: the gaps in order, each a pair of leftover lists.
        """
        source_position = {
            index: position for position, index in enumerate(source_kids)
        }
        test_position = {index: position for position, index in enumerate(test_kids)}
        anchors = [
            (source_position[index], test_position[self.pairs[index].test])
            for index in source_kids
            if index in self.pairs and self.pairs[index].test in test_position
        ]
        spine = _longest_increasing_subsequence(anchors)
        boundaries = [*spine, (len(source_kids), len(test_kids))]
        gaps: list[tuple[list[int], list[int]]] = []
        previous_source, previous_test = -1, -1
        for source_edge, test_edge in boundaries:
            gaps.append(
                (
                    [
                        index
                        for index in free_source
                        if previous_source < source_position[index] < source_edge
                    ],
                    [
                        index
                        for index in free_test
                        if previous_test < test_position[index] < test_edge
                    ],
                )
            )
            previous_source, previous_test = source_edge, test_edge
        return gaps

    # -- results -----------------------------------------------------------

    def _take(
        self,
        source: int,
        test: int,
        matched_by: str,
        score: float,
        free_source: list[int],
        free_test: list[int],
    ) -> None:
        """Record a pair and drop both blocks out of the group's leftovers."""
        self._record(source, test, matched_by, score)
        free_source.remove(source)
        free_test.remove(test)

    def _moved(self, source: int, test: int) -> bool:
        """Whether this pair's parents fail to correspond (ADR-0032).

        Read off the finished record rather than searched for, so the move
        pass does not have to announce what it did.
        """
        source_parent = self.source.parents[source]
        test_parent = self.test.parents[test]
        if source_parent < 0 or test_parent < 0:
            return False
        match = self.pairs.get(source_parent)
        return match is None or match.test != test_parent

    def _renumbered(self, source: int, test: int, moved: bool) -> bool:
        """Whether the parents correspond and the labels differ (#133).

        A block with no label and a block with an empty label are the same
        thing here, so a reader that writes one rather than the other never
        invents a renumber.
        """
        if moved:
            return False
        source_label = self.source.blocks[source].label or None
        test_label = self.test.blocks[test].label or None
        return source_label != test_label

    def _result(self) -> Alignment:
        """Build the `Alignment` from the finished record."""
        pairs: list[AlignedPair] = []
        for source in sorted(self.pairs):
            match = self.pairs[source]
            moved = self._moved(source, match.test)
            pairs.append(
                AlignedPair(
                    source_path=self.source.path(source),
                    test_path=self.test.path(match.test),
                    matched_by=match.matched_by,
                    confidence=match.confidence,
                    moved=moved,
                    renumbered=self._renumbered(source, match.test, moved),
                )
            )
        deleted = tuple(
            self.source.path(index)
            for index in range(len(self.source))
            if index not in self.pairs
        )
        inserted = tuple(
            self.test.path(index)
            for index in range(len(self.test))
            if index not in self.matched_test
        )
        return Alignment(
            pairs=tuple(pairs),
            inserted=inserted,
            deleted=deleted,
            config=self.config,
            backend=self.backend,
            pass_counts=dict(self.counts),
            budget_exhausted=self.budget_exhausted,
        )
