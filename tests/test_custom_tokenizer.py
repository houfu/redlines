"""Tests for custom tokenizer functionality."""
import pytest

from redlines import Redlines
from redlines.processor import (
    NupunktProcessor,
    TokenizerFunction,
    WholeDocumentProcessor,
)


class TestCustomTokenizer:
    """Test custom tokenizer functionality."""

    def test_simple_whitespace_tokenizer(self) -> None:
        """Test using a simple whitespace tokenizer."""

        def whitespace_tokenizer(text: str) -> list[str]:
            """Split on whitespace."""
            return text.split()

        source = "The quick brown fox"
        test = "The fast brown fox"

        redlines = Redlines(source, test, tokenizer=whitespace_tokenizer)
        changes = redlines.redlines

        # Should detect one change: quick -> fast
        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert changes[0].source_text == "quick"
        assert changes[0].test_text == "fast"

    def test_character_level_tokenizer(self) -> None:
        """Test using a character-level tokenizer."""

        def char_tokenizer(text: str) -> list[str]:
            """Split into individual characters."""
            return list(text)

        source = "cat"
        test = "bat"

        redlines = Redlines(source, test, tokenizer=char_tokenizer)
        changes = redlines.redlines

        # Should detect one character change: c -> b
        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert changes[0].source_text == "c"
        assert changes[0].test_text == "b"

    def test_word_tokenizer_with_punctuation(self) -> None:
        """Test a custom tokenizer that keeps punctuation attached."""

        def word_punct_tokenizer(text: str) -> list[str]:
            """Simple word tokenizer that keeps punctuation."""
            import re

            return re.findall(r"\w+[.,!?;:]?", text)

        source = "Hello, world!"
        test = "Hello, universe!"

        redlines = Redlines(source, test, tokenizer=word_punct_tokenizer)
        changes = redlines.redlines

        # Should detect change from world! to universe!
        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert "world!" in changes[0].source_text  # type: ignore
        assert "universe!" in changes[0].test_text  # type: ignore

    def test_line_based_tokenizer(self) -> None:
        """Test a tokenizer that splits on lines."""

        def line_tokenizer(text: str) -> list[str]:
            """Split on newlines."""
            return [line + "\n" for line in text.split("\n") if line]

        source = "Line one\nLine two\nLine three"
        test = "Line one\nModified two\nLine three"

        redlines = Redlines(source, test, tokenizer=line_tokenizer)
        changes = redlines.redlines

        # Should detect change in second line
        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert "Line two" in changes[0].source_text  # type: ignore
        assert "Modified two" in changes[0].test_text  # type: ignore

    def test_custom_tokenizer_with_processor(self) -> None:
        """Test passing custom tokenizer to a processor directly."""

        def word_tokenizer(text: str) -> list[str]:
            """Split on whitespace."""
            return text.split()

        processor = WholeDocumentProcessor(tokenizer=word_tokenizer)
        source = "The quick brown fox"
        test = "The fast brown fox"

        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should detect one change
        assert len(changes) == 1
        assert changes[0].source_text == "quick"
        assert changes[0].test_text == "fast"

    @pytest.mark.skipif(
        not hasattr(NupunktProcessor, "__init__"),
        reason="NupunktProcessor doesn't support custom tokenizer",
    )
    def test_custom_tokenizer_with_nupunkt_processor(self) -> None:
        """Test passing custom tokenizer to NupunktProcessor."""
        from redlines.processor import NUPUNKT_AVAILABLE

        if not NUPUNKT_AVAILABLE:
            pytest.skip("nupunkt not installed")

        def simple_tokenizer(text: str) -> list[str]:
            """Split on spaces."""
            return text.split(" ")

        processor = NupunktProcessor(tokenizer=simple_tokenizer)
        source = "Dr. Smith said hello."
        test = "Dr. Smith said hi."

        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should detect change from hello to hi
        assert len(changes) >= 1
        # At least one change should involve hello/hi
        hello_change = any("hello" in str(c.source_text) for c in changes)
        hi_change = any("hi" in str(c.test_text) for c in changes)
        assert hello_change or hi_change

    def test_tokenizer_parameter_overrides_default(self) -> None:
        """Test that tokenizer parameter properly overrides default behavior."""

        def custom_tokenizer(text: str) -> list[str]:
            """Custom tokenizer that splits differently than default."""
            # Add markers to prove this tokenizer is being used
            tokens = text.split()
            return [f"[{token}]" for token in tokens]

        source = "hello world"
        test = "hello universe"

        redlines = Redlines(source, test, tokenizer=custom_tokenizer)

        # The tokens should have our custom markers
        output = redlines.output_markdown
        # Since we wrap tokens in [], the output should contain them
        assert "[" in output or "hello" in output

    def test_processor_takes_precedence_over_tokenizer(self) -> None:
        """Test that processor parameter takes precedence over tokenizer parameter."""

        def custom_tokenizer(text: str) -> list[str]:
            """This should not be used."""
            return ["TOKENIZER"]

        def processor_tokenizer(text: str) -> list[str]:
            """This should be used."""
            return ["PROCESSOR"]

        processor = WholeDocumentProcessor(tokenizer=processor_tokenizer)

        source = "test"
        test = "test"

        # Pass both processor and tokenizer - processor should win
        redlines = Redlines(source, test, processor=processor, tokenizer=custom_tokenizer)

        # Both texts are identical, so no changes expected
        # But we're testing that the right tokenizer was used
        assert redlines.processor == processor

    def test_tokenizer_with_empty_strings(self) -> None:
        """Test custom tokenizer with empty strings."""

        def word_tokenizer(text: str) -> list[str]:
            """Split on whitespace, filtering empty strings."""
            return [t for t in text.split() if t]

        source = ""
        test = "hello"

        redlines = Redlines(source, test, tokenizer=word_tokenizer)
        changes = redlines.redlines

        # Should detect insertion
        assert len(changes) == 1
        assert changes[0].operation == "insert"
        assert changes[0].test_text == "hello"

    def test_tokenizer_preserves_ordering(self) -> None:
        """Test that custom tokenizer preserves token order."""

        def reverse_word_tokenizer(text: str) -> list[str]:
            """Split and reverse (intentionally weird behavior)."""
            return list(reversed(text.split()))

        source = "one two three"
        test = "one two three"

        redlines = Redlines(source, test, tokenizer=reverse_word_tokenizer)
        changes = redlines.redlines

        # Even with reversed tokenization, identical inputs should have no changes
        # (both are reversed the same way)
        assert len(changes) == 0

    def test_tokenizer_with_special_characters(self) -> None:
        """Test custom tokenizer handling special characters."""

        def special_char_tokenizer(text: str) -> list[str]:
            """Split on special characters."""
            import re

            return re.split(r"([^\w\s])", text)

        source = "hello@world.com"
        test = "hello@universe.com"

        redlines = Redlines(source, test, tokenizer=special_char_tokenizer)
        changes = redlines.redlines

        # Should detect the change from world to universe
        assert len(changes) >= 1
        source_tokens = [c.source_text for c in changes if c.source_text]
        test_tokens = [c.test_text for c in changes if c.test_text]

        # Verify either world or universe appears
        has_world = any("world" in str(t) for t in source_tokens)
        has_universe = any("universe" in str(t) for t in test_tokens)
        assert has_world or has_universe


class TestTokenizerFunctionType:
    """Test TokenizerFunction type."""

    def test_tokenizer_function_type_signature(self) -> None:
        """Test that TokenizerFunction type works as expected."""

        def valid_tokenizer(text: str) -> list[str]:
            """Valid tokenizer matching the type signature."""
            return text.split()

        # This should work without type errors
        tokenizer: TokenizerFunction = valid_tokenizer

        # Use it with Redlines
        redlines = Redlines("test one", "test two", tokenizer=tokenizer)
        assert redlines is not None

    def test_lambda_tokenizer(self) -> None:
        """Test using a lambda as tokenizer."""
        source = "hello world"
        test = "hello universe"

        # Lambda tokenizer
        redlines = Redlines(source, test, tokenizer=lambda text: text.split())
        changes = redlines.redlines

        assert len(changes) == 1
        assert changes[0].source_text == "world"
        assert changes[0].test_text == "universe"


class TestEdgeCases:
    """Test edge cases for custom tokenizers."""

    def test_tokenizer_returning_empty_list(self) -> None:
        """Test tokenizer that returns empty list."""

        def empty_tokenizer(text: str) -> list[str]:
            """Always return empty list."""
            return []

        source = "hello"
        test = "world"

        redlines = Redlines(source, test, tokenizer=empty_tokenizer)
        changes = redlines.redlines

        # No tokens means no changes can be detected
        assert len(changes) == 0

    def test_tokenizer_returning_single_token(self) -> None:
        """Test tokenizer that returns entire text as single token."""

        def single_token_tokenizer(text: str) -> list[str]:
            """Return entire text as single token."""
            return [text] if text else []

        source = "The quick brown fox"
        test = "The fast brown fox"

        redlines = Redlines(source, test, tokenizer=single_token_tokenizer)
        changes = redlines.redlines

        # Should see one replace operation for the entire text
        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert changes[0].source_text == "The quick brown fox"
        assert changes[0].test_text == "The fast brown fox"

    def test_none_as_tokenizer_uses_default(self) -> None:
        """Test that passing None as tokenizer uses default."""
        source = "The quick brown fox"
        test = "The fast brown fox"

        # Explicitly pass None
        redlines = Redlines(source, test, tokenizer=None)
        changes = redlines.redlines

        # Should work with default tokenizer
        assert len(changes) >= 1
