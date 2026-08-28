"""Tests for the cleanup pass that merges adjacent edits separated only by punctuation."""
import json

import pytest

from redlines import Redlines
from redlines.processor import NUPUNKT_AVAILABLE, NupunktProcessor


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_md",
    [
        (
            "The fee is thirty (30) days.",
            "The fee is forty (40) days.",
            "The fee is <del>thirty (30</del><ins>forty (40</ins>) days.",
        ),
        (
            "thirty (30) days",
            "sixty (60) days",
            "<del>thirty (30</del><ins>sixty (60</ins>) days",
        ),
    ],
)
def test_merge_punctuation_split_replace_md(
    test_string_1: str, test_string_2: str, expected_md: str
) -> None:
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


def test_merge_punctuation_split_single_change() -> None:
    """The issue's headline case reports one change, not two."""
    test = Redlines(
        "The fee is thirty (30) days.",
        "The fee is forty (40) days.",
        markdown_style="none",
    )

    changes = test.changes
    assert len(changes) == 1
    assert changes[0].operation == "replace"
    assert changes[0].source_text == "thirty (30"
    assert changes[0].test_text == "forty (40"

    # The two replaces and the '(' equal run between them merge into one opcode
    assert ("replace", 3, 6, 3, 6) in test.opcodes

    stats = test.stats()
    assert stats.total_changes == 1
    assert stats.replacements == 1


def test_chained_merge_collapses_to_single_change() -> None:
    """Chains of edits separated by punctuation collapse into one operation."""
    test = Redlines("one (1) - two (2)", "uno (3) - dos (4)", markdown_style="none")

    assert len(test.changes) == 1
    assert test.opcodes == [("replace", 0, 8, 0, 8), ("equal", 8, 9, 8, 9)]
    # The trailing ')' is rendered outside the del/ins spans
    assert test.output_markdown == "<del>one (1) - two (2</del><ins>uno (3) - dos (4</ins>)"


def test_boundary_punctuation_not_swallowed() -> None:
    """Equal runs at the document boundaries are never absorbed."""
    test = Redlines("(thirty)", "(forty)", markdown_style="none")

    assert test.output_markdown == "(<del>thirty</del><ins>forty</ins>)"
    assert len(test.changes) == 1


def test_paragraph_boundary_never_merged() -> None:
    """The paragraph boundary token must not be merged across."""
    test = Redlines("thirty\n\nthirty", "forty\n\nforty", markdown_style="none")

    assert len(test.changes) == 2
    assert (
        test.output_markdown
        == "<del>thirty </del><ins>forty </ins>\n\n<del>thirty</del><ins>forty</ins>"
    )


def test_word_token_equal_run_not_merged() -> None:
    """Equal runs containing word tokens keep the edits separate."""
    test = Redlines(
        "thirty (30) days and thirty (30) nights",
        "forty (40) days and forty (40) nights",
        markdown_style="none",
    )

    assert len(test.changes) == 2


def test_delete_punct_delete_collapses_to_replace() -> None:
    """Deletions flanking a punctuation-only equal run merge into one replace."""
    test = Redlines("x - y", "-", markdown_style="none")

    changes = test.changes
    assert len(changes) == 1
    assert changes[0].operation == "replace"
    assert changes[0].source_text == "x - y"

    # The insert mirror also collapses to one change
    mirror = Redlines("-", "x - y", markdown_style="none")
    assert len(mirror.changes) == 1


def test_json_output_consistency() -> None:
    """The merged operation surfaces consistently through output_json."""
    test = Redlines(
        "The fee is thirty (30) days.",
        "The fee is forty (40) days.",
        markdown_style="none",
    )

    data = json.loads(test.output_json())
    non_equal = [c for c in data["changes"] if c["type"] != "equal"]
    assert len(non_equal) == 1
    assert non_equal[0]["type"] == "replace"
    assert non_equal[0]["source_token_position"] == [3, 6]
    assert non_equal[0]["test_token_position"] == [3, 6]
    assert data["stats"]["total_changes"] == 1

    # Character positions of consecutive changes remain contiguous
    changes = data["changes"]
    for prev, cur in zip(changes, changes[1:]):
        if prev["source_position"] is not None and cur["source_position"] is not None:
            assert prev["source_position"][1] == cur["source_position"][0]


def test_identical_texts_no_changes() -> None:
    """Identical texts still report no changes."""
    test = Redlines("thirty (30) days.", "thirty (30) days.", markdown_style="none")

    assert len(test.changes) == 0
    assert test.stats().total_changes == 0


def test_adjacent_edits_without_punctuation_unaffected() -> None:
    """Edits not separated by punctuation behave as before."""
    test = Redlines(
        "The quick brown fox jumps over the lazy dog.",
        "The quick brown fox walks past the lazy dog.",
        markdown_style="none",
    )

    assert (
        test.output_markdown
        == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    assert len(test.changes) == 1


@pytest.mark.skipif(not NUPUNKT_AVAILABLE, reason="nupunkt not installed")
class TestNupunktCleanup:
    """The cleanup pass applies to NupunktProcessor as well."""

    def test_merge_punctuation_split_single_change(self) -> None:
        test = Redlines(
            "The fee is thirty (30) days.",
            "The fee is forty (40) days.",
            processor=NupunktProcessor(),
            markdown_style="none",
        )

        changes = test.changes
        assert len(changes) == 1
        assert changes[0].operation == "replace"
