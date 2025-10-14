"""Tests for the JSON output functionality."""

import json

import pytest
from redlines import Redlines


def test_json_output_basic_replace() -> None:
    """Test JSON output with a basic replacement operation."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()

    # Verify it's valid JSON
    data = json.loads(json_output)

    # Verify top-level structure
    assert "source" in data
    assert "test" in data
    assert "source_tokens" in data
    assert "test_tokens" in data
    assert "changes" in data
    assert "stats" in data

    # Verify source and test
    assert data["source"] == source
    assert data["test"] == test

    # Verify tokens are lists
    assert isinstance(data["source_tokens"], list)
    assert isinstance(data["test_tokens"], list)
    assert len(data["source_tokens"]) > 0
    assert len(data["test_tokens"]) > 0

    # Verify changes
    assert isinstance(data["changes"], list)
    assert len(data["changes"]) == 3  # equal, replace, equal

    # Verify the replace operation
    replace_change = data["changes"][1]
    assert replace_change["type"] == "replace"
    assert replace_change["source_text"] == "jumps over "
    assert replace_change["test_text"] == "walks past "
    assert replace_change["source_position"] == [20, 31]
    assert replace_change["test_position"] == [20, 31]
    assert replace_change["source_token_position"] == [4, 6]
    assert replace_change["test_token_position"] == [4, 6]

    # Verify stats
    assert data["stats"]["replacements"] == 1
    assert data["stats"]["deletions"] == 0
    assert data["stats"]["insertions"] == 0
    assert data["stats"]["unchanged"] == 2
    assert data["stats"]["total_changes"] == 1


def test_json_output_insert() -> None:
    """Test JSON output with insertion operation."""
    source = "The quick brown fox jumps over the dog."
    test = "The quick brown fox jumps over the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Find the insert operation
    insert_changes = [c for c in data["changes"] if c["type"] == "insert"]
    assert len(insert_changes) == 1

    insert = insert_changes[0]
    assert insert["text"] == "lazy "
    assert insert["source_position"] is None
    assert insert["test_position"] is not None
    assert insert["source_token_position"] is None
    assert insert["test_token_position"] is not None

    # Verify stats
    assert data["stats"]["insertions"] == 1
    assert data["stats"]["deletions"] == 0
    assert data["stats"]["replacements"] == 0


def test_json_output_delete() -> None:
    """Test JSON output with deletion operation."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox jumps over the dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Find the delete operation
    delete_changes = [c for c in data["changes"] if c["type"] == "delete"]
    assert len(delete_changes) == 1

    delete = delete_changes[0]
    assert delete["text"] == "lazy "
    assert delete["source_position"] is not None
    assert delete["test_position"] is None
    assert delete["source_token_position"] is not None
    assert delete["test_token_position"] is None

    # Verify stats
    assert data["stats"]["deletions"] == 1
    assert data["stats"]["insertions"] == 0
    assert data["stats"]["replacements"] == 0


def test_json_output_equal() -> None:
    """Test JSON output includes equal operations."""
    source = "Hello world"
    test = "Hello world"

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Should have only one equal operation
    assert len(data["changes"]) == 1
    assert data["changes"][0]["type"] == "equal"
    assert data["changes"][0]["text"] == "Hello world"

    # Verify stats show no changes
    assert data["stats"]["total_changes"] == 0
    assert data["stats"]["unchanged"] == 1


def test_json_output_character_positions() -> None:
    """Test that character positions are accurate."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify character positions by extracting text
    for change in data["changes"]:
        if change["type"] == "equal":
            start, end = change["source_position"]
            assert source[start:end] == change["text"]
            start, end = change["test_position"]
            assert test[start:end] == change["text"]
        elif change["type"] == "delete":
            start, end = change["source_position"]
            assert source[start:end] == change["text"]
        elif change["type"] == "insert":
            start, end = change["test_position"]
            assert test[start:end] == change["text"]
        elif change["type"] == "replace":
            start, end = change["source_position"]
            assert source[start:end] == change["source_text"]
            start, end = change["test_position"]
            assert test[start:end] == change["test_text"]


def test_json_output_token_positions() -> None:
    """Test that token positions match the token arrays."""
    source = "The quick brown fox"
    test = "The quick brown cat"

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify token positions by extracting tokens
    source_tokens = data["source_tokens"]
    test_tokens = data["test_tokens"]

    for change in data["changes"]:
        if change["type"] == "equal":
            si1, si2 = change["source_token_position"]
            ti1, ti2 = change["test_token_position"]
            assert "".join(source_tokens[si1:si2]) == change["text"]
            assert "".join(test_tokens[ti1:ti2]) == change["text"]
        elif change["type"] == "delete":
            si1, si2 = change["source_token_position"]
            assert "".join(source_tokens[si1:si2]) == change["text"]
        elif change["type"] == "insert":
            ti1, ti2 = change["test_token_position"]
            assert "".join(test_tokens[ti1:ti2]) == change["text"]
        elif change["type"] == "replace":
            si1, si2 = change["source_token_position"]
            ti1, ti2 = change["test_token_position"]
            assert "".join(source_tokens[si1:si2]) == change["source_text"]
            assert "".join(test_tokens[ti1:ti2]) == change["test_text"]


def test_json_output_pretty_print() -> None:
    """Test pretty-printed JSON output."""
    source = "Hello world"
    test = "Hello there"

    r = Redlines(source, test)
    compact_json = r.output_json(pretty=False)
    pretty_json = r.output_json(pretty=True)

    # Both should be valid JSON
    compact_data = json.loads(compact_json)
    pretty_data = json.loads(pretty_json)

    # Should have same content
    assert compact_data == pretty_data

    # Pretty version should have more characters (whitespace)
    assert len(pretty_json) > len(compact_json)

    # Pretty version should have newlines
    assert "\n" in pretty_json
    assert "\n" not in compact_json or compact_json.count("\n") < pretty_json.count(
        "\n"
    )


def test_json_output_unicode() -> None:
    """Test JSON output handles unicode correctly."""
    source = "Hello 世界"
    test = "Hello 🌍"

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify unicode is preserved
    assert "世界" in data["source"]
    assert "🌍" in data["test"]

    # Verify character positions work with unicode
    for change in data["changes"]:
        if change["type"] == "replace":
            start, end = change["source_position"]
            assert source[start:end] == change["source_text"]
            start, end = change["test_position"]
            assert test[start:end] == change["test_text"]


def test_json_output_special_characters() -> None:
    """Test JSON output handles special characters."""
    source = 'Hello "world"'
    test = "Hello 'world'"

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify special characters are preserved
    assert '"' in data["source"]
    assert "'" in data["test"]


def test_json_output_newlines() -> None:
    """Test JSON output handles newlines/paragraphs."""
    source = "Hello\n\nWorld"
    test = "Hello\n\nEarth"

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify newlines are preserved in source and test
    assert "\n\n" in data["source"]
    assert "\n\n" in data["test"]

    # Verify we have changes with newlines
    has_newlines = any("\n\n" in change.get("text", "") for change in data["changes"])
    assert has_newlines, "Changes should contain newline markers"

    # Note: Perfect reconstruction isn't possible due to how paragraphs are tokenized
    # The tokenizer adds spaces around paragraph markers, which matches output_markdown behavior
    # This is a known limitation of the tokenization approach


def test_json_output_multiple_changes() -> None:
    """Test JSON output with multiple different types of changes."""
    source = "A B C D E"
    test = "A X C E F"
    # B->X (replace), D deleted, F inserted

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Count operation types
    operation_counts: dict[str, int] = {}
    for change in data["changes"]:
        op_type = change["type"]
        operation_counts[op_type] = operation_counts.get(op_type, 0) + 1

    # Should have multiple types
    assert "equal" in operation_counts
    assert (
        operation_counts.get("replace", 0)
        + operation_counts.get("delete", 0)
        + operation_counts.get("insert", 0)
        > 1
    )


def test_json_output_empty_strings() -> None:
    """Test JSON output with empty-ish strings."""
    source = "   "
    test = "   "

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Should still produce valid JSON
    assert isinstance(data, dict)
    assert data["source"] == source
    assert data["test"] == test


def test_json_output_tokens_can_reconstruct_text() -> None:
    """Test that joining tokens reconstructs the original text."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Reconstruct source from tokens
    reconstructed_source = "".join(data["source_tokens"])
    assert reconstructed_source == source

    # Reconstruct test from tokens
    reconstructed_test = "".join(data["test_tokens"])
    assert reconstructed_test == test


def test_json_output_all_changes_covered() -> None:
    """Test that changes array covers all text without gaps or overlaps."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Reconstruct source from changes
    source_parts = []
    for change in data["changes"]:
        if change["type"] in ["equal", "delete"]:
            source_parts.append(change.get("text") or change.get("source_text", ""))
        elif change["type"] == "replace":
            source_parts.append(change["source_text"])

    reconstructed_source = "".join(source_parts)
    assert reconstructed_source == source

    # Reconstruct test from changes
    test_parts = []
    for change in data["changes"]:
        if change["type"] in ["equal", "insert"]:
            test_parts.append(change.get("text") or change.get("test_text", ""))
        elif change["type"] == "replace":
            test_parts.append(change["test_text"])

    reconstructed_test = "".join(test_parts)
    assert reconstructed_test == test


def test_json_output_consistency_with_changes_api() -> None:
    """Test that JSON output stats match the changes API."""
    source = "The quick brown fox jumps over the lazy dog."
    test = "The quick brown fox walks past the lazy dog."

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Compare with stats() method
    stats = r.stats()
    assert data["stats"]["deletions"] == stats.deletions
    assert data["stats"]["insertions"] == stats.insertions
    assert data["stats"]["replacements"] == stats.replacements
    assert data["stats"]["total_changes"] == stats.total_changes


def test_json_output_long_text() -> None:
    """Test JSON output with longer text."""
    source = """The quick brown fox jumps over the lazy dog.

    This is a longer text with multiple paragraphs.
    It should handle all the newlines and spaces correctly.

    The end."""

    test = """The quick brown fox walks past the lazy dog.

    This is a longer text with several paragraphs.
    It should handle all the newlines and spaces properly.

    The end."""

    r = Redlines(source, test)
    json_output = r.output_json()
    data = json.loads(json_output)

    # Verify structure is valid
    assert "changes" in data
    assert "stats" in data
    assert len(data["changes"]) > 1

    # Verify we have multiple paragraphs represented
    has_newlines = any(
        "\n\n" in str(change.get("text", "") or change.get("source_text", ""))
        for change in data["changes"]
    )
    assert has_newlines, "Should preserve paragraph breaks"

    # Verify stats show actual changes
    assert data["stats"]["total_changes"] > 0
