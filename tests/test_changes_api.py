"""Tests for the programmatic diff access API (changes, get_changes, stats)."""

import pytest
from redlines import Redlines
from redlines.processor import LEVENSHTEIN_AVAILABLE, Redline, Stats


def test_changes_property_replace() -> None:
    """Test changes property with replacement operation."""
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    assert len(changes) == 1
    assert changes[0].operation == "replace"
    assert changes[0].source_text == "jumps over "
    assert changes[0].test_text == "walks past "
    assert changes[0].source_position == (4, 6)
    assert changes[0].test_position == (4, 6)


def test_changes_property_insert() -> None:
    """Test changes property with insertion operation."""
    test_string_1 = "The quick brown fox jumps over the dog."
    test_string_2 = "The quick brown fox jumps over the lazy dog."

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    assert len(changes) == 1
    assert changes[0].operation == "insert"
    assert changes[0].source_text is None
    assert changes[0].test_text == "lazy "
    assert changes[0].source_position is None
    assert changes[0].test_position == (7, 8)


def test_changes_property_delete() -> None:
    """Test changes property with deletion operation."""
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox jumps over the dog."

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    assert len(changes) == 1
    assert changes[0].operation == "delete"
    assert changes[0].source_text == "lazy "
    assert changes[0].test_text is None
    assert changes[0].source_position == (7, 8)
    assert changes[0].test_position is None


def test_changes_excludes_equal() -> None:
    """Test that changes property excludes equal operations."""
    test_string_1 = "The quick brown fox"
    test_string_2 = "The quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    # No changes when strings are identical
    assert len(changes) == 0


def test_changes_multiple_operations() -> None:
    """Test changes with multiple different operations."""
    test_string_1 = "Hello world. This is a test."
    test_string_2 = "Hi world. This is an example."

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    # Should have 2 changes (replace "Hello" -> "Hi" and "a test" -> "an example")
    assert len(changes) == 2
    assert changes[0].operation == "replace"
    assert changes[1].operation == "replace"


def test_get_changes_no_filter() -> None:
    """Test get_changes with no filter returns all changes."""
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."

    r = Redlines(test_string_1, test_string_2)

    all_changes = r.get_changes()
    changes_from_property = r.changes

    assert len(all_changes) == len(changes_from_property)
    assert all_changes == changes_from_property


def test_get_changes_filter_replace() -> None:
    """Test get_changes filtering for replace operations."""
    test_string_1 = "Hello world"
    test_string_2 = "Hi earth"

    r = Redlines(test_string_1, test_string_2)
    replacements = r.get_changes(operation="replace")

    assert len(replacements) >= 1
    assert all(c.operation == "replace" for c in replacements)


def test_get_changes_filter_insert() -> None:
    """Test get_changes filtering for insert operations."""
    test_string_1 = "The quick brown fox"
    test_string_2 = "The very quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    insertions = r.get_changes(operation="insert")

    assert len(insertions) == 1
    assert insertions[0].operation == "insert"
    assert insertions[0].test_text == "very "


def test_get_changes_filter_delete() -> None:
    """Test get_changes filtering for delete operations."""
    test_string_1 = "The very quick brown fox"
    test_string_2 = "The quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    deletions = r.get_changes(operation="delete")

    assert len(deletions) == 1
    assert deletions[0].operation == "delete"
    assert deletions[0].source_text == "very "


def test_get_changes_invalid_operation() -> None:
    """Test get_changes raises error for invalid operation."""
    test_string_1 = "Hello world"
    test_string_2 = "Hi world"

    r = Redlines(test_string_1, test_string_2)

    with pytest.raises(ValueError, match="Invalid operation"):
        r.get_changes(operation="invalid")


def test_stats_basic() -> None:
    """Test stats method with basic changes."""
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    assert isinstance(stats, Stats)
    assert stats.total_changes == 1
    assert stats.replacements == 1
    assert stats.deletions == 0
    assert stats.insertions == 0


def test_stats_multiple_operations() -> None:
    """Test stats with multiple types of operations."""
    # Create a scenario with insert, delete, and replace
    test_string_1 = "A B C D E"
    test_string_2 = "A X C E F"
    # B->X (replace), D deleted, F inserted

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    assert stats.total_changes >= 1  # At least one change
    assert (
        stats.deletions + stats.insertions + stats.replacements == stats.total_changes
    )


def test_stats_no_changes() -> None:
    """Test stats when there are no changes."""
    test_string_1 = "Hello world"
    test_string_2 = "Hello world"

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    assert stats.total_changes == 0
    assert stats.deletions == 0
    assert stats.insertions == 0
    assert stats.replacements == 0


def test_redline_dataclass_attributes() -> None:
    """Test that Redline dataclass has expected attributes."""
    test_string_1 = "Hello"
    test_string_2 = "Hi"

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    assert len(changes) == 1
    redline = changes[0]

    # Check all attributes are accessible
    assert hasattr(redline, "operation")
    assert hasattr(redline, "source_text")
    assert hasattr(redline, "test_text")
    assert hasattr(redline, "source_position")
    assert hasattr(redline, "test_position")


def test_stats_dataclass_attributes() -> None:
    """Test that Stats dataclass has expected attributes."""
    test_string_1 = "Hello"
    test_string_2 = "Hi"

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    # Check all attributes are accessible (both old and new)
    expected_attrs = [
        "total_changes",
        "deletions",
        "insertions",
        "replacements",
        "longest_change_length",
        "shortest_change_length",
        "average_change_length",
        "change_ratio",
        "chars_added",
        "chars_deleted",
        "chars_net_change",
        "levenshtein_distance",
    ]

    for attr in expected_attrs:
        assert hasattr(stats, attr), f"Stats missing attribute: {attr}"


def test_changes_with_paragraphs() -> None:
    """Test changes API handles paragraphs correctly."""
    test_string_1 = """Hello world.

This is a test."""
    test_string_2 = """Hi world.

This is an example."""

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    # Should have changes for "Hello" -> "Hi" and "test" -> "example"
    assert len(changes) >= 1
    assert all(isinstance(r, Redline) for r in changes)


def test_api_integration() -> None:
    """Integration test for the complete programmatic API."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the sleepy cat."

    r = Redlines(source, test)

    # Test changes property
    changes = r.changes
    assert len(changes) >= 1
    assert all(isinstance(redline, Redline) for redline in changes)

    # Test get_changes with filter
    replacements = r.get_changes(operation="replace")
    assert all(redline.operation == "replace" for redline in replacements)

    # Test stats
    stats = r.stats()
    assert isinstance(stats, Stats)
    assert stats.total_changes == len(changes)

    # Verify stats match the actual changes
    manual_replacements = sum(
        1 for redline in changes if redline.operation == "replace"
    )
    manual_insertions = sum(1 for redline in changes if redline.operation == "insert")
    manual_deletions = sum(1 for redline in changes if redline.operation == "delete")

    assert stats.replacements == manual_replacements
    assert stats.insertions == manual_insertions
    assert stats.deletions == manual_deletions


def test_advanced_stats_basic_replace() -> None:
    """Test advanced stats with basic replacement operation."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."
    r = Redlines(source, test)
    stats = r.stats()

    # Basic operation counts
    assert stats.total_changes == 1
    assert stats.replacements == 1
    assert stats.deletions == 0
    assert stats.insertions == 0

    # Change length metrics
    assert stats.longest_change_length == 11  # "jumps over " (11 chars)
    assert stats.shortest_change_length == 11
    assert stats.average_change_length == 11.0

    # Change ratio (11 changed chars out of 44 total)
    assert abs(stats.change_ratio - 11 / 44) < 0.001

    # Character-level statistics
    assert stats.chars_added == 11  # "walks past " (11 chars)
    assert stats.chars_deleted == 11  # "jumps over " (11 chars)
    assert stats.chars_net_change == 0  # Same length

    # Levenshtein distance should be available if library installed
    if LEVENSHTEIN_AVAILABLE:
        assert stats.levenshtein_distance is not None
        assert stats.levenshtein_distance >= 1  # At least some distance
    else:
        assert stats.levenshtein_distance is None


def test_advanced_stats_insert() -> None:
    """Test advanced stats with insertion operation."""
    source = "Hello world"
    test = "Hello beautiful world"
    r = Redlines(source, test)
    stats = r.stats()

    assert stats.total_changes == 1
    assert stats.insertions == 1
    assert stats.replacements == 0
    assert stats.deletions == 0

    assert stats.longest_change_length == 10  # "beautiful "
    assert stats.shortest_change_length == 10
    assert stats.average_change_length == 10.0

    # Change ratio (10 changed chars out of 21 total - max of source/test lengths)
    assert abs(stats.change_ratio - 10 / 21) < 0.001

    assert stats.chars_added == 10
    assert stats.chars_deleted == 0
    assert stats.chars_net_change == 10


def test_advanced_stats_delete() -> None:
    """Test advanced stats with deletion operation."""
    source = "Hello beautiful world"
    test = "Hello world"
    r = Redlines(source, test)
    stats = r.stats()

    assert stats.total_changes == 1
    assert stats.deletions == 1
    assert stats.insertions == 0
    assert stats.replacements == 0

    assert stats.longest_change_length == 10  # "beautiful "
    assert stats.shortest_change_length == 10
    assert stats.average_change_length == 10.0

    # Change ratio (10 changed chars out of 21 total)
    assert abs(stats.change_ratio - 10 / 21) < 0.001

    assert stats.chars_added == 0
    assert stats.chars_deleted == 10
    assert stats.chars_net_change == -10


def test_advanced_stats_multiple_operations() -> None:
    """Test advanced stats with multiple different operations."""
    source = "A B C D E"
    test = "A X C E F"
    # B->X (replace), D deleted, F inserted

    r = Redlines(source, test)
    stats = r.stats()

    # Should have 3 changes: replace, delete, insert
    assert stats.total_changes == 3
    assert stats.replacements == 1  # B -> X
    assert stats.deletions == 1  # D deleted
    assert stats.insertions == 1  # F inserted

    # Change lengths: "X " (2), "D " (2), "F" (1)
    assert stats.longest_change_length == 2
    assert stats.shortest_change_length == 1
    assert stats.average_change_length == (2 + 2 + 1) / 3  # 1.666...

    # Character counts: added "X "+"F" (3), deleted "B "+"D " (4), net -1
    assert stats.chars_added == 3  # "X " + "F"
    assert stats.chars_deleted == 4  # "B " + "D "
    assert stats.chars_net_change == -1


def test_advanced_stats_no_changes() -> None:
    """Test advanced stats when there are no changes."""
    source = "Hello world"
    test = "Hello world"

    r = Redlines(source, test)
    stats = r.stats()

    assert stats.total_changes == 0
    assert stats.longest_change_length == 0
    assert stats.shortest_change_length == 0
    assert stats.average_change_length == 0.0
    assert stats.change_ratio == 0.0
    assert stats.chars_added == 0
    assert stats.chars_deleted == 0
    assert stats.chars_net_change == 0
    if LEVENSHTEIN_AVAILABLE:
        assert stats.levenshtein_distance == 0  # Identical strings
    else:
        assert stats.levenshtein_distance is None


def test_advanced_stats_empty_strings() -> None:
    """Test advanced stats with empty strings."""
    source = ""
    test = ""

    r = Redlines(source, test)
    stats = r.stats()

    # Empty identical strings
    assert stats.total_changes == 0
    assert stats.longest_change_length == 0
    assert stats.shortest_change_length == 0
    assert stats.average_change_length == 0.0
    assert stats.change_ratio == 0.0
    assert stats.chars_added == 0
    assert stats.chars_deleted == 0
    assert stats.chars_net_change == 0
    if LEVENSHTEIN_AVAILABLE:
        assert stats.levenshtein_distance == 0
    else:
        assert stats.levenshtein_distance is None


def test_advanced_stats_unicode() -> None:
    """Test advanced stats with unicode characters."""
    source = "Hello 世界"
    test = "Hi 世界🌍"

    r = Redlines(source, test)
    stats = r.stats()

    # Should handle unicode correctly
    assert stats.total_changes >= 1
    if LEVENSHTEIN_AVAILABLE:
        assert stats.levenshtein_distance is not None
    else:
        assert stats.levenshtein_distance is None
    assert isinstance(stats.change_ratio, float)
    assert 0.0 <= stats.change_ratio <= 1.0


def test_advanced_stats_levenshtein_fallback() -> None:
    """Test that Levenshtein distance gracefully handles missing library."""
    # We'll test this by temporarily mocking the import failure
    import sys
    from unittest.mock import patch

    source = "Hello world"
    test = "Hi world"

    # Mock import failure
    with patch.dict("sys.modules", {"Levenshtein": None}):
        with patch(
            "builtins.__import__",
            side_effect=ImportError("No module named 'Levenshtein'"),
        ):
            r = Redlines(source, test)
            stats = r.stats()

            # All other stats should still work
            assert stats.total_changes >= 1
            assert stats.change_ratio > 0
            # Levenshtein should be None when library unavailable
            assert stats.levenshtein_distance is None


def test_advanced_stats_dataclass_attributes() -> None:
    """Test that extended Stats dataclass has all expected attributes."""
    source = "Hello world"
    test = "Hi world"

    r = Redlines(source, test)
    stats = r.stats()

    # Check all new attributes are accessible
    required_attrs = [
        "total_changes",
        "deletions",
        "insertions",
        "replacements",
        "longest_change_length",
        "shortest_change_length",
        "average_change_length",
        "change_ratio",
        "chars_added",
        "chars_deleted",
        "chars_net_change",
        "levenshtein_distance",
    ]

    for attr in required_attrs:
        assert hasattr(stats, attr), f"Stats missing attribute: {attr}"


def test_advanced_stats_integration() -> None:
    """Integration test for complete advanced statistics functionality."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the sleepy cat."

    r = Redlines(source, test)
    stats = r.stats()

    # Verify all fields are present and reasonable
    assert isinstance(stats.total_changes, int)
    assert isinstance(stats.longest_change_length, int)
    assert isinstance(stats.average_change_length, float)
    assert isinstance(stats.change_ratio, float)
    assert isinstance(stats.chars_added, int)
    assert isinstance(stats.chars_deleted, int)
    assert isinstance(stats.chars_net_change, int)

    # Verify constraints
    assert stats.total_changes >= 0
    assert stats.longest_change_length >= 0
    assert stats.average_change_length >= 0.0
    assert 0.0 <= stats.change_ratio <= 1.0
    assert stats.chars_added >= 0
    assert stats.chars_deleted >= 0

    # Verify consistency: net change = added - deleted
    assert stats.chars_net_change == stats.chars_added - stats.chars_deleted

    # Levenshtein may or may not be available depending on installation
    if LEVENSHTEIN_AVAILABLE:
        assert stats.levenshtein_distance is not None
        assert isinstance(stats.levenshtein_distance, int)
        assert stats.levenshtein_distance >= 0
    else:
        assert stats.levenshtein_distance is None
