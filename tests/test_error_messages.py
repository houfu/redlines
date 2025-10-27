"""Test error messages for clarity and actionability."""

import pytest

from redlines import Redlines


class TestPropertyAccessErrors:
    """Test error messages when accessing properties before they are set."""

    def test_source_property_error_message(self) -> None:
        """Test that accessing source property after setting it to None raises a helpful error."""
        redlines_obj = Redlines(source="initial")
        # Simulate internal scenario where source is set to None
        redlines_obj._source = None

        with pytest.raises(ValueError) as exc_info:
            _ = redlines_obj.source

        error_message = str(exc_info.value)

        # Verify the error message contains key information
        assert "No source text available" in error_message
        assert "Cause:" in error_message
        assert "To fix:" in error_message
        assert "Initialize Redlines" in error_message
        assert "redlines_obj = Redlines(source='original', test='modified')" in error_message

    def test_test_property_error_message(self) -> None:
        """Test that accessing test property before setting it raises a helpful error."""
        redlines_obj = Redlines(source="source text")

        with pytest.raises(ValueError) as exc_info:
            _ = redlines_obj.test

        error_message = str(exc_info.value)

        # Verify the error message contains key information
        assert "No test text available" in error_message
        assert "Cause:" in error_message
        assert "To fix:" in error_message
        assert "Initialize Redlines" in error_message
        assert "redlines_obj = Redlines(source='original', test='modified')" in error_message

    def test_diff_operations_error_message(self) -> None:
        """Test that accessing diff operations before comparison raises a helpful error."""
        redlines_obj = Redlines(source="source text")

        with pytest.raises(ValueError) as exc_info:
            _ = redlines_obj._diff_ops

        error_message = str(exc_info.value)

        # Verify the error message contains key information
        assert "No diff operations available" in error_message
        assert "Cause:" in error_message
        assert "To fix:" in error_message
        assert "Set both source and test texts" in error_message
        # Check for multiple options
        assert "Option 1:" in error_message
        assert "Option 2:" in error_message
        assert "Option 3:" in error_message


class TestCompareMethodErrors:
    """Test error messages for compare method."""

    def test_compare_without_test_error_message(self) -> None:
        """Test that calling compare without test text raises a helpful error."""
        redlines_obj = Redlines(source="original text")

        with pytest.raises(ValueError) as exc_info:
            redlines_obj.compare()

        error_message = str(exc_info.value)

        # Verify the error message contains key information
        assert "No test text provided for comparison" in error_message
        assert "Cause:" in error_message
        assert "compare() method was called without a test parameter" in error_message
        assert "To fix:" in error_message
        # Check for multiple options
        assert "Option 1:" in error_message
        assert "Pass test text to compare()" in error_message
        assert "Option 2:" in error_message
        assert "Set test during initialization" in error_message
        assert "Option 3:" in error_message


class TestGetChangesErrors:
    """Test error messages for get_changes method."""

    def test_invalid_operation_type_error_message(self) -> None:
        """Test that passing invalid operation type raises a helpful error."""
        redlines_obj = Redlines(
            source="The quick brown fox",
            test="The quick red fox"
        )

        with pytest.raises(ValueError) as exc_info:
            redlines_obj.get_changes(operation="invalid")

        error_message = str(exc_info.value)

        # Verify the error message contains key information
        assert "Invalid operation type: 'invalid'" in error_message
        assert "Cause:" in error_message
        assert "must be one of the three valid diff operation types" in error_message
        assert "To fix:" in error_message
        # Check for examples of valid operations
        assert "operation='delete'" in error_message
        assert "operation='insert'" in error_message
        assert "operation='replace'" in error_message
        assert "Get all changes" in error_message


class TestErrorMessageStructure:
    """Test that all error messages follow the what/why/how structure."""

    @pytest.mark.parametrize("error_scenario", [
        "source_property",
        "test_property",
        "diff_operations",
        "compare_without_test",
        "invalid_operation",
    ])
    def test_error_messages_have_required_sections(self, error_scenario: str) -> None:
        """Test that all error messages contain What, Why (Cause), and How (To fix) sections."""
        error_message = None

        try:
            if error_scenario == "source_property":
                redlines_obj = Redlines(source="initial")
                redlines_obj._source = None
                _ = redlines_obj.source
            elif error_scenario == "test_property":
                redlines_obj = Redlines(source="source text")
                _ = redlines_obj.test
            elif error_scenario == "diff_operations":
                redlines_obj = Redlines(source="source text")
                _ = redlines_obj._diff_ops
            elif error_scenario == "compare_without_test":
                redlines_obj = Redlines(source="test")
                redlines_obj.compare()
            elif error_scenario == "invalid_operation":
                redlines_obj = Redlines("source", "test")
                redlines_obj.get_changes(operation="wrong")
        except ValueError as e:
            error_message = str(e)

        # All error messages should have these sections
        assert error_message is not None, f"Expected ValueError for {error_scenario}"
        assert "Cause:" in error_message, f"Missing 'Cause:' in {error_scenario}"
        assert "To fix:" in error_message, f"Missing 'To fix:' in {error_scenario}"
        # Check for code examples (indented with spaces)
        assert "  " in error_message, f"Missing code examples in {error_scenario}"
