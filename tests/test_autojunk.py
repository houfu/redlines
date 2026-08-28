"""Tests for the autojunk option on processors (ADR-0010).

difflib.SequenceMatcher's default autojunk heuristic kicks in for sequences of
200+ tokens and treats tokens occurring in more than 1% of positions as
unmatchable "popular junk". On repetitive documents this silently reports the
entire document as replaced, so redlines disables it by default and exposes it
as an option on the processors.
"""

import pytest

from redlines import Redlines
from redlines.processor import (
    NUPUNKT_AVAILABLE,
    NupunktProcessor,
    WholeDocumentProcessor,
)

# One clause of ~36 tokens; repeated 30 times it exceeds 1,000 tokens, well past
# the 200-token threshold where difflib's autojunk heuristic activates.
CLAUSE = (
    "The tenant shall pay the monthly rent of five hundred dollars to the "
    "landlord on or before the first business day of each calendar month "
    "without any deduction set off or counterclaim whatsoever under this "
    "agreement. "
)


def _repetitive_texts() -> tuple[str, str]:
    """Build the ADR-0010 repetitive case: the clause repeated 30 times, with a
    single two-word change ("five hundred" -> "six thousand") in one middle
    occurrence."""
    source = CLAUSE * 30
    repetitions = [CLAUSE] * 30
    repetitions[15] = CLAUSE.replace("five hundred", "six thousand")
    test = "".join(repetitions)
    return source, test


def test_autojunk_default_false_repetitive_case() -> None:
    """With the default processor (autojunk=False), a two-word edit in a
    repetitive 1,000+ token document is reported as a small localized change,
    not a whole-document replace. (M0 exit criterion for the repetitive
    schedule case.)"""
    source, test = _repetitive_texts()
    redline = Redlines(source, test)
    changes = redline.redlines

    assert len(changes) == 1
    change = changes[0]
    assert change.operation == "replace"
    assert change.source_position is not None
    start, end = change.source_position
    # The edit is two adjacent tokens; allow a little slack for how the
    # matcher anchors within repeated text, but it must stay localized.
    assert end - start <= 4
    assert change.source_text is not None and "five hundred" in change.source_text
    assert change.test_text is not None and "six thousand" in change.test_text


def test_autojunk_true_reproduces_old_behavior() -> None:
    """With autojunk=True the popular-token heuristic degrades the same diff
    into a change spanning most of the document, proving the option is plumbed
    through to SequenceMatcher."""
    source, test = _repetitive_texts()
    redline = Redlines(
        source, test, processor=WholeDocumentProcessor(autojunk=True)
    )
    changes = redline.redlines

    max_span = max(
        change.source_position[1] - change.source_position[0]
        for change in changes
        if change.source_position is not None
    )
    assert max_span > 500


def test_autojunk_no_effect_on_varied_prose() -> None:
    """On ordinary varied prose the option makes no difference."""
    source = (
        "The quick brown fox jumps over the lazy dog. "
        "A wizard's job is to vex chumps quickly in fog. "
        "Pack my box with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump!"
    )
    test = (
        "The quick brown fox leaps over the lazy dog. "
        "A wizard's job is to vex chumps quickly in fog. "
        "Pack my crate with five dozen liquor jugs. "
        "How vexingly quick daft zebras jump!"
    )

    with_autojunk = Redlines(
        source, test, processor=WholeDocumentProcessor(autojunk=True)
    )
    without_autojunk = Redlines(
        source, test, processor=WholeDocumentProcessor(autojunk=False)
    )

    assert with_autojunk.output_markdown == without_autojunk.output_markdown


def test_default_processor_is_autojunk_false() -> None:
    """Redlines' default processor must have autojunk disabled."""
    redline = Redlines("a", "b")
    assert isinstance(redline.processor, WholeDocumentProcessor)
    assert redline.processor.autojunk is False


@pytest.mark.skipif(not NUPUNKT_AVAILABLE, reason="nupunkt not installed")
def test_nupunkt_processor_accepts_autojunk() -> None:
    """NupunktProcessor accepts and stores the autojunk option too."""
    assert NupunktProcessor().autojunk is False
    processor = NupunktProcessor(autojunk=True)
    assert processor.autojunk is True

    redline = Redlines(
        "Sentence one. Sentence two.",
        "Sentence one. Modified two.",
        processor=processor,
    )
    changes = redline.redlines
    assert len(changes) == 1
    assert changes[0].operation == "replace"
