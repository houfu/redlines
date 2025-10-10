"""Tests for the programmatic diff access API (changes, get_changes, stats)."""

import pytest
from redlines import Redlines
from redlines.processor import Redline, Stats


def test_changes_property_replace():
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


def test_changes_property_insert():
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


def test_changes_property_delete():
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


def test_changes_excludes_equal():
    """Test that changes property excludes equal operations."""
    test_string_1 = "The quick brown fox"
    test_string_2 = "The quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    # No changes when strings are identical
    assert len(changes) == 0


def test_changes_multiple_operations():
    """Test changes with multiple different operations."""
    test_string_1 = "Hello world. This is a test."
    test_string_2 = "Hi world. This is an example."

    r = Redlines(test_string_1, test_string_2)
    changes = r.changes

    # Should have 2 changes (replace "Hello" -> "Hi" and "a test" -> "an example")
    assert len(changes) == 2
    assert changes[0].operation == "replace"
    assert changes[1].operation == "replace"


def test_get_changes_no_filter():
    """Test get_changes with no filter returns all changes."""
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."

    r = Redlines(test_string_1, test_string_2)

    all_changes = r.get_changes()
    changes_from_property = r.changes

    assert len(all_changes) == len(changes_from_property)
    assert all_changes == changes_from_property


def test_get_changes_filter_replace():
    """Test get_changes filtering for replace operations."""
    test_string_1 = "Hello world"
    test_string_2 = "Hi earth"

    r = Redlines(test_string_1, test_string_2)
    replacements = r.get_changes(operation="replace")

    assert len(replacements) >= 1
    assert all(c.operation == "replace" for c in replacements)


def test_get_changes_filter_insert():
    """Test get_changes filtering for insert operations."""
    test_string_1 = "The quick brown fox"
    test_string_2 = "The very quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    insertions = r.get_changes(operation="insert")

    assert len(insertions) == 1
    assert insertions[0].operation == "insert"
    assert insertions[0].test_text == "very "


def test_get_changes_filter_delete():
    """Test get_changes filtering for delete operations."""
    test_string_1 = "The very quick brown fox"
    test_string_2 = "The quick brown fox"

    r = Redlines(test_string_1, test_string_2)
    deletions = r.get_changes(operation="delete")

    assert len(deletions) == 1
    assert deletions[0].operation == "delete"
    assert deletions[0].source_text == "very "


def test_get_changes_invalid_operation():
    """Test get_changes raises error for invalid operation."""
    test_string_1 = "Hello world"
    test_string_2 = "Hi world"

    r = Redlines(test_string_1, test_string_2)

    with pytest.raises(ValueError, match="Invalid operation"):
        r.get_changes(operation="invalid")


def test_stats_basic():
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


def test_stats_multiple_operations():
    """Test stats with multiple types of operations."""
    # Create a scenario with insert, delete, and replace
    test_string_1 = "A B C D E"
    test_string_2 = "A X C E F"
    # B->X (replace), D deleted, F inserted

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    assert stats.total_changes >= 1  # At least one change
    assert stats.deletions + stats.insertions + stats.replacements == stats.total_changes


def test_stats_no_changes():
    """Test stats when there are no changes."""
    test_string_1 = "Hello world"
    test_string_2 = "Hello world"

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    assert stats.total_changes == 0
    assert stats.deletions == 0
    assert stats.insertions == 0
    assert stats.replacements == 0


def test_redline_dataclass_attributes():
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


def test_stats_dataclass_attributes():
    """Test that Stats dataclass has expected attributes."""
    test_string_1 = "Hello"
    test_string_2 = "Hi"

    r = Redlines(test_string_1, test_string_2)
    stats = r.stats()

    # Check all attributes are accessible
    assert hasattr(stats, "total_changes")
    assert hasattr(stats, "deletions")
    assert hasattr(stats, "insertions")
    assert hasattr(stats, "replacements")


def test_changes_with_paragraphs():
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


def test_api_integration():
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
    manual_replacements = sum(1 for redline in changes if redline.operation == "replace")
    manual_insertions = sum(1 for redline in changes if redline.operation == "insert")
    manual_deletions = sum(1 for redline in changes if redline.operation == "delete")

    assert stats.replacements == manual_replacements
    assert stats.insertions == manual_insertions
    assert stats.deletions == manual_deletions
