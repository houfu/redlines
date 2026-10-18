"""PRD § 10's release gates, as tests that fail on the day they are met (#143, ADR-0034).

Every gate below is `pytest.mark.xfail(strict=True)`. That is not a way of
switching a failing test off: `strict=True` means the day the gate is actually
met the test **fails because it passed**, and somebody has to delete the mark
by hand. A gate that could be left quietly marked expected-to-fail once it went
green would not be a gate, and ADR-0009 asks for a forcing function rather than
a habit.

The bars, from PRD § 10 and ADR-0009:

- synthetic correspondence F1 ≥ 0.95;
- hand-labelled correspondence F1 ≥ 0.85;
- move recall ≥ 0.90 on the synthetic tier;
- on the hand-labelled set, no engine move a reviewer ruled ``wrong`` **and**
  none with no verdict at all -- unknown is not a pass.

**The hand-labelled F1 gate asserts the labels are confirmed as well.** Its
labels today are what `benchmark/label.py init` proposed out of this engine's
own alignment, every row still ``status: proposed``. Scoring the engine against
its own unreviewed proposals produces 1.0000 and means nothing, so a gate that
read only the ratio could be passed by a benchmark that had never been
labelled. ADR-0034 says a proposed row is not ground truth; this test says the
same thing where it can fail.

Everything here runs under the ``difflib`` backend -- the floor the
documentation site runs on (PRD § 12), and the backend the report quotes its
headline numbers under. Beside the gates sit the checks that keep the committed
artefacts honest: that ``REPORT.md`` and ``results/latest.json`` are what the
runner writes today, and that writing them twice produces the same bytes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

from redlines.similarity import RAPIDFUZZ_AVAILABLE

from benchmark.generate import repository_root
from benchmark.report import GATES, render_report
from benchmark.run import BACKENDS, results_text, run

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = pytest.mark.filterwarnings("error")


@pytest.fixture(scope="module")
def results() -> dict[str, Any]:
    """The whole committed corpus, scored once under `difflib`, for every gate."""
    return run(backends=("difflib",))


def _tier(results: Mapping[str, Any], tier: str) -> Mapping[str, Any]:
    """The 1.0 engine's row for one tier, under `difflib`."""
    for entry in results["tiers"]:
        if (
            entry["tier"] == tier
            and entry["engine"] == "1.0"
            and entry["backend"] == "difflib"
        ):
            found: Mapping[str, Any] = entry
            return found
    raise AssertionError(f"no 1.0/difflib results for the {tier} tier")


def _proposed_rows(results: Mapping[str, Any], tier: str) -> int:
    """How many of a tier's correspondence rows nobody has confirmed."""
    return sum(pair["proposed_rows"] for pair in _tier(results, tier)["pairs"])


# --- the gates --------------------------------------------------------------


def test_synthetic_correspondence_f1_meets_the_target(results: dict[str, Any]) -> None:
    """PRD § 10: correspondence F1 ≥ 0.95 on the synthetic tier.

    Met, and the ``xfail(strict=True)`` mark this test carried until the
    alignment tuning pass is gone rather than relaxed: the exact and label
    passes now break a tie between equally exact candidates on structural
    nearness rather than on document order alone, which is what the first
    report's 84 wrong exact matches were.
    """
    f1 = _tier(results, "synthetic")["links"]["f1"]
    assert f1 is not None
    assert f1 >= 0.95


@pytest.mark.xfail(
    strict=True,
    reason="the hand tier's labels are still engine-seeded drafts (#142): every row "
    "is status: proposed, so its F1 measures self-agreement and is not evidence",
)
def test_hand_correspondence_f1_meets_the_target(results: dict[str, Any]) -> None:
    """PRD § 10: correspondence F1 ≥ 0.85 on the hand-labelled tier.

    The confirmation check is part of the gate, not a separate courtesy: a
    ratio computed against rows this engine proposed and nobody reviewed is not
    a measurement of the engine.
    """
    assert _proposed_rows(results, "hand") == 0, (
        "the hand tier's labels are still drafts; run benchmark/label.py check "
        "and sign before quoting this number"
    )
    f1 = _tier(results, "hand")["links"]["f1"]
    assert f1 is not None
    assert f1 >= 0.85


@pytest.mark.xfail(
    strict=True,
    reason="move recall is short of ADR-0009's bar and cannot reach it on this "
    "corpus: 5 of the 23 labelled moves are byte-identical paragraphs among 30 "
    "byte-identical siblings in the repetitive-schedule pairs, where 30 candidates "
    "are equally good and reporting one would be a guess. 18/23 = 0.7826 is the "
    "ceiling that keeps move precision at 1.0000 (see benchmark/REPORT.md)",
)
def test_synthetic_move_recall_meets_the_target(results: dict[str, Any]) -> None:
    """ADR-0009: move recall ≥ 0.90 on synthetic mutations."""
    recall = _tier(results, "synthetic")["moves"]["recall"]
    assert recall is not None
    assert recall >= 0.90


@pytest.mark.xfail(
    strict=True,
    reason="the engine reports moves on the hand set that no reviewer has ruled on; "
    "the gate is fail-closed (ADR-0034), so unknown counts against it until #142's "
    "move worksheets are worked through",
)
def test_no_engine_move_on_the_hand_set_is_wrong_or_unreviewed(
    results: dict[str, Any],
) -> None:
    """ADR-0009's second bar, enforced by per-move verdicts, failing closed."""
    hand = _tier(results, "hand")
    assert hand["wrong_moves"] == 0
    assert hand["unreviewed_moves"] == 0


# --- checks that are expected to pass ---------------------------------------


def test_no_synthetic_move_is_ruled_wrong_or_left_unreviewed(
    results: dict[str, Any],
) -> None:
    """The synthetic tier's labels are what the generator did, so a reported move
    absent from them is a false positive by construction. ADR-0009 would rather miss
    a move than invent one, so this is the half of the bar that must stay green while
    recall is being worked on."""
    synthetic = _tier(results, "synthetic")
    assert synthetic["wrong_moves"] == 0
    assert synthetic["unreviewed_moves"] == 0


def test_move_precision_is_not_traded_away_for_recall(
    results: dict[str, Any],
) -> None:
    """Every move the engine reports on generated truth is one the generator made."""
    moves = _tier(results, "synthetic")["moves"]
    assert moves["reported"] > 0, "a corpus with no reported moves cannot test this"
    assert moves["precision"] == 1.0


def test_the_alignment_budget_is_never_exhausted(results: dict[str, Any]) -> None:
    """`max_comparisons` running out would make a number mean "we gave up", not
    "the engine decided". If this ever fires, the report's figures need a caveat
    before anything else is read into them."""
    for entry in results["tiers"]:
        for pair in entry["pairs"]:
            assert not pair["budget_exhausted"], pair["pair"]


def test_every_gate_the_report_prints_has_a_test_here(results: dict[str, Any]) -> None:
    """`benchmark/report.py`'s GATES table and this module must not drift apart."""
    assert set(GATES) == {
        ("synthetic", "correspondence F1", 0.95),
        ("hand", "correspondence F1", 0.85),
        ("synthetic", "move recall", 0.90),
    }


# --- the committed artefacts ------------------------------------------------


@pytest.mark.skipif(
    not RAPIDFUZZ_AVAILABLE,
    reason="the committed report is generated under both backends; install the "
    "[fuzzy] extra with `uv sync --all-extras --dev`",
)
def test_the_committed_results_and_report_are_what_the_runner_writes() -> None:
    """ADR-0034: both files are committed so a number changing is a reviewable diff.

    They are only that if they are current. A failure here means somebody changed
    the engine, the corpus or the labels without re-running
    `uv run python -m benchmark.run --tier all`.
    """
    fresh = run(backends=BACKENDS)
    base = repository_root() / "benchmark"
    assert (base / "results" / "latest.json").read_text(
        encoding="utf-8"
    ) == results_text(fresh)
    assert (base / "REPORT.md").read_text(encoding="utf-8") == render_report(fresh)


def test_the_results_file_carries_no_clock() -> None:
    """Nothing committed may carry a timestamp, a duration or a run id, or the file
    would differ on every run and its diff would stop being readable."""
    text = (
        repository_root() / "benchmark" / "results" / "latest.json"
    ).read_text(encoding="utf-8")
    for forbidden in ("timestamp", "generated_at", "elapsed", "duration", "run_id"):
        assert forbidden not in text


def test_scoring_the_same_corpus_twice_gives_the_same_bytes() -> None:
    """Determinism, end to end: sorted pair order, integer counts, ratios rounded
    once at the edge. Anything that iterated a set would show up here."""
    first = run(tiers=("hand",), backends=("difflib",))
    second = run(tiers=("hand",), backends=("difflib",))
    assert results_text(first) == results_text(second)
    assert render_report(first) == render_report(second)
