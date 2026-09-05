"""The one number alignment runs on, and the two libraries that produce it.

`redlines.similarity` is small, and every one of its decisions is load-bearing
somewhere else: the tokeniser has to be the leaf differ's or the ratio
alignment measures is not the ratio the diff reports; the backend has to be
selectable or #143 cannot measure the gap between the two; and the prefilter
has to prune identically under both or the two legs of that measurement are
not comparable.
"""

from __future__ import annotations

import pytest

from redlines.processor import concatenate_paragraphs_and_add_chr_182, tokenize_text
from redlines.similarity import (
    BACKEND_NAMES,
    RAPIDFUZZ_AVAILABLE,
    REQUESTABLE_BACKENDS,
    SequenceScorer,
    resolve_backend,
    similarity,
    tokens,
)

# Every test that measures runs under whichever backends this install has, so
# that a machine with the [fuzzy] extra checks both and one without still
# checks the core. Anything a backend must *not* change is asserted across
# this list rather than on one of them.
BACKENDS: tuple[str, ...] = (
    BACKEND_NAMES if RAPIDFUZZ_AVAILABLE else ("difflib",)
)

CLAUSE = (
    "The Supplier shall meet each Service Level and shall report on its "
    "performance against the Service Levels for each month within five "
    "Business Days of the end of that month."
)
OTHER_CLAUSE = (
    "The Supplier may engage a subcontractor to supply any part of the "
    "Services, and remains responsible for the acts and omissions of that "
    "subcontractor as if they were its own."
)


def test_tokens_are_the_leaf_differs_own() -> None:
    """The sequences compared here are the sequences the leaf diff compares.

    `WholeDocumentProcessor` strips each token before comparing it, so
    `tokens` does the same. Any drift between the two would make a block score
    0.98 in alignment and come out with a visible edit in the diff, or the
    other way round.
    """
    # Exactly the two lines `WholeDocumentProcessor.process` runs before it
    # hands the sequences to `SequenceMatcher`. A single block carries no
    # paragraph break, so the pilcrow marker never appears and the tokens are
    # the block's own.
    prepared = concatenate_paragraphs_and_add_chr_182(CLAUSE)
    assert "\u00b6" not in prepared
    assert tokens(CLAUSE) == tuple(
        token.strip() for token in tokenize_text(prepared)
    )


def test_tokens_ignore_whitespace_runs() -> None:
    """A whitespace-only change is not a change (sample pair, clause 11.5)."""
    assert tokens("a  b\n\tc") == tokens("a b c") == ("a", "b", "c")


def test_tokens_of_empty_text_are_empty() -> None:
    """Container blocks carry no text, so nothing scores them."""
    assert tokens("") == ()
    assert tokens("   \n ") == ()


@pytest.mark.parametrize("backend", BACKENDS)
def test_identical_sequences_score_one(backend: str) -> None:
    assert similarity(tokens(CLAUSE), tokens(CLAUSE), backend=backend) == 1.0


@pytest.mark.parametrize("backend", BACKENDS)
def test_two_empty_sequences_score_one(backend: str) -> None:
    """2M/T over nothing is 1.0, not a division by zero.

    Two container blocks are alike, and the passes that compare them rely on
    this rather than special-casing emptiness at every call site.
    """
    assert similarity((), (), backend=backend) == 1.0


@pytest.mark.parametrize("backend", BACKENDS)
def test_unrelated_clauses_score_low(backend: str) -> None:
    """The measured number the label floor is set from (ADR-0032).

    The sample pair's old clause 3.3 and the newly inserted clause that took
    its number are unrelated text under one label. difflib puts them at 0.20;
    rapidfuzz is never lower.
    """
    score = similarity(tokens(CLAUSE), tokens(OTHER_CLAUSE), backend=backend)
    assert 0.15 <= score < 0.35


def test_difflib_scores_the_sample_clauses_at_exactly_zero_point_two() -> None:
    """Pinned, because ADR-0032 quotes it as the evidence for the 0.35 floor."""
    assert similarity(tokens(CLAUSE), tokens(OTHER_CLAUSE), backend="difflib") == 0.2


def test_auto_resolves_to_what_is_installed() -> None:
    assert resolve_backend("auto") == (
        "rapidfuzz" if RAPIDFUZZ_AVAILABLE else "difflib"
    )


def test_an_explicit_backend_is_honoured() -> None:
    assert resolve_backend("difflib") == "difflib"


def test_resolve_backend_defaults_to_auto() -> None:
    assert resolve_backend() == resolve_backend("auto")


def test_an_unknown_backend_names_the_set() -> None:
    with pytest.raises(ValueError, match="not a similarity backend"):
        resolve_backend("levenshtein")


@pytest.mark.skipif(RAPIDFUZZ_AVAILABLE, reason="the [fuzzy] extra is installed")
def test_asking_for_a_missing_backend_raises_rather_than_falling_back() -> None:
    """A silent downgrade would make the benchmark report a gap of zero."""
    with pytest.raises(ValueError, match="redlines\\[fuzzy\\]"):
        resolve_backend("rapidfuzz")


def test_similarity_rejects_an_unresolved_name() -> None:
    """``"auto"`` is a request, not a backend; it never reaches a comparison."""
    with pytest.raises(ValueError, match="resolve_backend"):
        similarity(("a",), ("a",), backend="auto")


def test_requestable_backends_are_the_concrete_ones_plus_auto() -> None:
    assert REQUESTABLE_BACKENDS == ("auto", *BACKEND_NAMES)


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_scorer_agrees_with_the_bare_function(backend: str) -> None:
    """`SequenceScorer` is an optimisation, so it must not be a difference."""
    scorer = SequenceScorer(tokens(OTHER_CLAUSE), backend=backend)
    assert scorer.score(tokens(CLAUSE)) == pytest.approx(
        similarity(tokens(CLAUSE), tokens(OTHER_CLAUSE), backend=backend)
    )


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_scorer_prunes_below_the_floor(backend: str) -> None:
    """A pruned candidate reports something below the floor, and nothing more.

    The contract is deliberately weak: below the floor the value is only an
    upper bound, because that is all a caller who is about to reject it can
    use. Above the floor it is exact, which the test above pins.
    """
    scorer = SequenceScorer(tokens(OTHER_CLAUSE), backend=backend)
    assert scorer.score(tokens("Not this at all."), floor=0.6) < 0.6


@pytest.mark.parametrize("backend", BACKENDS)
def test_the_prefilter_never_prunes_a_candidate_above_the_floor(
    backend: str,
) -> None:
    """The bounds are upper bounds for *both* backends (ADR-0032).

    A common subsequence can never be longer than the multiset intersection,
    so `difflib`'s ``quick_ratio`` bounds ``Indel.normalized_similarity`` too.
    If that ever stopped holding, the two backends would search different
    candidate sets and the benchmark's with-and-without comparison would
    measure the wrong thing.
    """
    words = CLAUSE.split()
    for cut in range(1, len(words)):
        candidate = tokens(" ".join(words[cut:]))
        target = tokens(CLAUSE)
        exact = similarity(candidate, target, backend=backend)
        pruned = SequenceScorer(target, backend=backend).score(candidate, floor=exact)
        assert pruned == pytest.approx(exact)


def test_the_scorer_rejects_an_unresolved_backend() -> None:
    with pytest.raises(ValueError, match="resolve_backend"):
        SequenceScorer(("a",), backend="auto")


def test_the_scorer_keeps_its_target() -> None:
    target = tokens(CLAUSE)
    assert SequenceScorer(target, backend="difflib").target == target


@pytest.mark.skipif(not RAPIDFUZZ_AVAILABLE, reason="needs the [fuzzy] extra")
def test_the_backends_agree_on_most_pairs_and_rapidfuzz_is_never_lower() -> None:
    """The canary for the measured +0.027..+0.333 divergence (ADR-0032).

    rapidfuzz's ``Indel`` is a true LCS and difflib's is a greedy
    longest-block search, so the two differ on short sequences with several
    edits and rapidfuzz is always the higher of the two. That direction is
    what makes the prefilter sound; if it ever inverted, pruning under
    rapidfuzz would start dropping candidates it should keep.
    """
    words = CLAUSE.split()
    for cut in range(1, len(words)):
        left = tokens(" ".join(words[:cut]))
        right = tokens(" ".join(words[cut:] + words[:2]))
        assert similarity(left, right, backend="rapidfuzz") >= similarity(
            left, right, backend="difflib"
        ) - 1e-12
