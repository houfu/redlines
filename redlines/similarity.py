"""How alike two blocks are, and which library measured it (#131, ADR-0032).

Alignment needs one number: how similar is this source block to that test
block. This module is the only place that number comes from, and the only
module in the package that touches the optional ``rapidfuzz`` extra::

    from redlines.similarity import resolve_backend, similarity, tokens

    backend = resolve_backend("auto")          # "rapidfuzz" if installed
    similarity(tokens(source_text), tokens(test_text), backend=backend)

Three decisions are baked in here, and each of them is a decision rather than
an implementation detail.

**Tokens, never characters.** `tokens` runs the *same* tokeniser the leaf
differ uses (`redlines.processor.tokenize_text`, then a ``strip()`` per token,
which is what `WholeDocumentProcessor` compares), so the ratio alignment
measures is the ratio the leaf diff will go on to report. It is also two
orders of magnitude cheaper: measured on ~45-token blocks, token-level
comparison runs at about 68,000 pairs per second against about 1,000 at
character level.

**The backend is selected, not detected.** ``"auto"`` resolves to
``"rapidfuzz"`` when the extra is installed and to ``"difflib"`` otherwise,
but an explicit name is honoured, and asking for a backend that is not there
raises rather than quietly falling back. Selection is what lets the benchmark
run both legs in one process and lets a user pin a backend to keep goldens
stable, and it is why the *resolved* name goes on the wire.

The two backends do not agree exactly. Measured across 20,000 random
token-pair comparisons against rapidfuzz 3.14: they agree on 19,914 pairs to
1e-12, and on the 86 that differ rapidfuzz is always higher, by +0.027 to
+0.333, concentrated on short sequences with several edits --
`difflib.SequenceMatcher.get_matching_blocks` is a greedy recursive
longest-block search while ``Indel`` is a true LCS. A backend can therefore
flip a near-threshold decision, which is why determinism is promised *per
configuration* (ADR-0032) and why the resolved name is part of the output.

**The backend must never change the search space.** `SequenceScorer` applies
`difflib`'s two cheap upper bounds -- ``real_quick_ratio()`` (a length bound)
and ``quick_ratio()`` (a multiset bound) -- before either backend computes
anything, under both backends alike. Both bounds are sound for both: a
common-subsequence length can never exceed the multiset intersection, so a
bound on difflib's ratio bounds ``Indel.normalized_similarity`` too. Same
candidates, same pruning, same tie-breaks either way -- otherwise the
benchmark's with-and-without-rapidfuzz comparison measures the wrong thing.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Final

from .processor import tokenize_text

if TYPE_CHECKING:
    from collections.abc import Sequence

try:
    from rapidfuzz.distance import Indel as _Indel

    RAPIDFUZZ_AVAILABLE = True
    """Whether the ``[fuzzy]`` extra is installed (ADR-0004, ADR-0032)."""
except ImportError:  # pragma: no cover - the plain wheel, and the Pyodide job
    _Indel = None  # type: ignore[assignment]
    RAPIDFUZZ_AVAILABLE = False


__all__: tuple[str, ...] = (
    "RAPIDFUZZ_AVAILABLE",
    "BACKEND_NAMES",
    "REQUESTABLE_BACKENDS",
    "SequenceScorer",
    "resolve_backend",
    "similarity",
    "tokens",
)


BACKEND_NAMES: Final[tuple[str, ...]] = ("difflib", "rapidfuzz")
"""The concrete backends, which is what a *resolved* name is one of."""

REQUESTABLE_BACKENDS: Final[tuple[str, ...]] = ("auto", *BACKEND_NAMES)
"""What `AlignmentConfig.similarity` may be asked for, ``"auto"`` included."""


def tokens(text: str) -> tuple[str, ...]:
    """Return ``text`` as the token sequence similarity is measured over.

    The tokens are the leaf differ's own (`redlines.processor.tokenize_text`)
    with each one stripped, which is the normalisation
    `redlines.processor.WholeDocumentProcessor` applies before comparing. So
    two blocks that differ only in whitespace produce identical sequences and
    score 1.0, exactly as the leaf diff would report no change.

    :param text: a block's own ``text``; a label is never part of it.
    :return: the tokens, in order. Empty for text that is empty or all
        whitespace -- container blocks included, which is why nothing scores
        them (ADR-0032).
    """
    return tuple(token.strip() for token in tokenize_text(text))


def resolve_backend(requested: str = "auto") -> str:
    """Turn a requested backend into the concrete one that will run.

    :param requested: ``"auto"``, ``"difflib"`` or ``"rapidfuzz"``.
    :return: ``"difflib"`` or ``"rapidfuzz"`` -- the name that belongs in the
        output, because "auto picked difflib" and "difflib was demanded" are
        different facts (ADR-0032).
    :raises ValueError: if ``requested`` is not one of the three, or if
        ``"rapidfuzz"`` is asked for and the extra is not installed. Asking is
        never silently downgraded: a benchmark leg that quietly ran the other
        backend would report a gap of zero.
    """
    if requested == "auto":
        return "rapidfuzz" if RAPIDFUZZ_AVAILABLE else "difflib"
    if requested == "difflib":
        return "difflib"
    if requested == "rapidfuzz":
        if not RAPIDFUZZ_AVAILABLE:
            raise ValueError(
                "the 'rapidfuzz' backend was requested but rapidfuzz is not "
                "installed; install redlines[fuzzy], or ask for 'auto'"
            )
        return "rapidfuzz"
    allowed = ", ".join(REQUESTABLE_BACKENDS)
    raise ValueError(
        f"{requested!r} is not a similarity backend; the set is: {allowed}"
    )


def similarity(a: Sequence[str], b: Sequence[str], *, backend: str) -> float:
    """Return how alike two token sequences are, from 0.0 to 1.0.

    Both backends compute 2M/T -- twice the matched token count over the total
    length -- so two empty sequences are 1.0 rather than a division by zero,
    and both are exactly reproducible over integers (N1).

    :param a: the source side's tokens.
    :param b: the test side's tokens. The argument order is fixed at every
        call site, because `difflib`'s ratio is not perfectly symmetric.
    :param backend: a *resolved* backend name from `resolve_backend`.
    :return: the similarity.
    :raises ValueError: if ``backend`` is not a resolved backend name.
    """
    if backend == "difflib":
        return SequenceMatcher(None, a, b, autojunk=False).ratio()
    if backend == "rapidfuzz":
        if not RAPIDFUZZ_AVAILABLE:  # pragma: no cover - resolve_backend guards
            raise ValueError("the 'rapidfuzz' backend is not installed")
        return float(_Indel.normalized_similarity(a, b))
    allowed = ", ".join(BACKEND_NAMES)
    raise ValueError(
        f"{backend!r} is not a resolved similarity backend; it is one of: "
        f"{allowed}. Call resolve_backend() first."
    )


class SequenceScorer:
    """Scores many source sequences against one held test sequence.

    The inner loop of the fuzzy and move passes compares one test block
    against a window of source blocks. Holding the test side as `difflib`'s
    ``seq2`` and replacing ``seq1`` per candidate keeps its ``b2j`` index --
    measured at roughly twice the throughput of the other way round, because
    ``set_seq2`` invalidates that cache.

    Both of `difflib`'s cheap upper bounds run first, under either backend, so
    the set of candidates that survive to a full comparison does not depend on
    which library is installed (ADR-0032).

    :param target: the test side's tokens, held for the scorer's lifetime.
    :param backend: a resolved backend name from `resolve_backend`.
    """

    __slots__ = ("_backend", "_matcher", "_target")

    def __init__(self, target: Sequence[str], *, backend: str) -> None:
        if backend not in BACKEND_NAMES:
            allowed = ", ".join(BACKEND_NAMES)
            raise ValueError(
                f"{backend!r} is not a resolved similarity backend; it is one "
                f"of: {allowed}. Call resolve_backend() first."
            )
        self._backend = backend
        self._target = target
        self._matcher = SequenceMatcher(None, (), target, autojunk=False)

    @property
    def target(self) -> Sequence[str]:
        """The test-side tokens this scorer compares against."""
        return self._target

    def score(self, candidate: Sequence[str], *, floor: float = 0.0) -> float:
        """Return the similarity of ``candidate`` to the held target.

        :param candidate: the source side's tokens.
        :param floor: the score the caller would accept. Anything the cheap
            bounds already put below it is rejected without a full comparison.
        :return: the exact similarity whenever the value returned is at or
            above ``floor``; below ``floor`` the value is only an upper bound
            on the true similarity, which is all a caller who is about to
            reject it can use. Callers that need an exact number for a pair
            they will keep regardless -- the positional pass recording its
            confidence -- pass ``floor=0.0``.
        """
        self._matcher.set_seq1(candidate)
        bound = self._matcher.real_quick_ratio()
        if bound < floor:
            return bound
        bound = self._matcher.quick_ratio()
        if bound < floor:
            return bound
        if self._backend == "difflib":
            return self._matcher.ratio()
        return float(_Indel.normalized_similarity(candidate, self._target))
