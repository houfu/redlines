#!/usr/bin/env python3
"""
Example: Using Custom Tokenizers with Redlines

This example demonstrates how to use custom tokenizer functions with Redlines
for different text comparison needs.

Custom tokenizers allow you to control how text is split into tokens,
enabling specialized comparisons for:
- Word-level changes (whitespace tokenizer)
- Character-level changes (char tokenizer)
- Line-level changes (line tokenizer)
- Domain-specific tokenization (e.g., code, legal text)

For more information, see:
https://github.com/houfu/redlines
"""

from redlines import Redlines


def example_whitespace_tokenizer() -> None:
    """Example 1: Simple whitespace tokenizer for word-level comparison."""
    print("=" * 60)
    print("Example 1: Whitespace Tokenizer (Word-level)")
    print("=" * 60)

    def whitespace_tokenizer(text: str) -> list[str]:
        """Split text on whitespace for word-level comparison."""
        return text.split()

    source = "The quick brown fox jumps over the lazy dog"
    test = "The fast brown fox jumps over the lazy dog"

    redlines = Redlines(source, test, tokenizer=whitespace_tokenizer)

    print(f"Source: {source}")
    print(f"Test:   {test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    if redlines.changes:
        for i, change in enumerate(redlines.changes, 1):
            print(f"  {i}. {change.operation}: '{change.source_text}' → '{change.test_text}'")
    print()


def example_character_tokenizer() -> None:
    """Example 2: Character-level tokenizer for fine-grained comparison."""
    print("=" * 60)
    print("Example 2: Character Tokenizer (Character-level)")
    print("=" * 60)

    def char_tokenizer(text: str) -> list[str]:
        """Split text into individual characters."""
        return list(text)

    source = "color"
    test = "colour"

    redlines = Redlines(source, test, tokenizer=char_tokenizer)

    print(f"Source: {source}")
    print(f"Test:   {test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    if redlines.changes:
        for i, change in enumerate(redlines.changes, 1):
            print(f"  {i}. {change.operation}: '{change.source_text}' → '{change.test_text}'")
    print()


def example_line_tokenizer() -> None:
    """Example 3: Line-based tokenizer for diff-like comparison."""
    print("=" * 60)
    print("Example 3: Line Tokenizer (Line-level)")
    print("=" * 60)

    def line_tokenizer(text: str) -> list[str]:
        """Split text into lines, preserving line endings."""
        lines = text.split("\n")
        return [line + "\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])

    source = """Line 1: Introduction
Line 2: Body paragraph
Line 3: Conclusion"""

    test = """Line 1: Introduction
Line 2: Modified body paragraph
Line 3: Conclusion"""

    redlines = Redlines(source, test, tokenizer=line_tokenizer)

    print(f"Source:\n{source}")
    print(f"\nTest:\n{test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    if redlines.changes:
        for i, change in enumerate(redlines.changes, 1):
            src = repr(change.source_text) if change.source_text else "None"
            tst = repr(change.test_text) if change.test_text else "None"
            print(f"  {i}. {change.operation}: {src} → {tst}")
    print()


def example_code_tokenizer() -> None:
    """Example 4: Code-aware tokenizer for programming language comparison."""
    print("=" * 60)
    print("Example 4: Code Tokenizer (Code-aware)")
    print("=" * 60)

    import re

    def code_tokenizer(text: str) -> list[str]:
        """
        Tokenize code by splitting on whitespace and operators.
        Keeps operators and identifiers as separate tokens.
        """
        # Simple pattern that splits on whitespace and common operators
        # while preserving them
        pattern = r"(\s+|[+\-*/=<>!&|(){}\[\];,.])"
        tokens = re.split(pattern, text)
        return [t for t in tokens if t]  # Remove empty strings

    source = "x = foo(a, b)"
    test = "x = bar(a, b)"

    redlines = Redlines(source, test, tokenizer=code_tokenizer)

    print(f"Source: {source}")
    print(f"Test:   {test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    if redlines.changes:
        for i, change in enumerate(redlines.changes, 1):
            print(f"  {i}. {change.operation}: '{change.source_text}' → '{change.test_text}'")
    print()


def example_email_tokenizer() -> None:
    """Example 5: Email-aware tokenizer that preserves addresses."""
    print("=" * 60)
    print("Example 5: Email Tokenizer (Domain-specific)")
    print("=" * 60)

    import re

    def email_tokenizer(text: str) -> list[str]:
        """
        Tokenize text while keeping email addresses intact.
        """
        # Pattern to match email addresses
        email_pattern = r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
        parts = []
        last_end = 0

        for match in re.finditer(email_pattern, text):
            # Add text before email
            before = text[last_end : match.start()]
            if before:
                parts.extend(before.split())
            # Add email as single token
            parts.append(match.group())
            last_end = match.end()

        # Add remaining text
        remaining = text[last_end:]
        if remaining:
            parts.extend(remaining.split())

        return parts

    source = "Contact john@example.com for details"
    test = "Contact jane@example.com for details"

    redlines = Redlines(source, test, tokenizer=email_tokenizer)

    print(f"Source: {source}")
    print(f"Test:   {test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    if redlines.changes:
        for i, change in enumerate(redlines.changes, 1):
            print(f"  {i}. {change.operation}: '{change.source_text}' → '{change.test_text}'")
    print()


def example_with_processor() -> None:
    """Example 6: Using custom tokenizer with a processor."""
    print("=" * 60)
    print("Example 6: Custom Tokenizer with Processor")
    print("=" * 60)

    from redlines.processor import WholeDocumentProcessor

    def simple_tokenizer(text: str) -> list[str]:
        """Split on spaces."""
        return text.split(" ")

    # Create processor with custom tokenizer
    processor = WholeDocumentProcessor(tokenizer=simple_tokenizer)

    source = "alpha beta gamma"
    test = "alpha delta gamma"

    redlines = Redlines(source, test, processor=processor)

    print(f"Source: {source}")
    print(f"Test:   {test}")
    print(f"\nMarkdown output:")
    print(redlines.output_markdown)
    print(f"\nChanges detected: {len(redlines.changes)}")
    print()


def main() -> None:
    """Run all examples."""
    print("\n" + "=" * 60)
    print("CUSTOM TOKENIZER EXAMPLES")
    print("=" * 60 + "\n")

    example_whitespace_tokenizer()
    example_character_tokenizer()
    example_line_tokenizer()
    example_code_tokenizer()
    example_email_tokenizer()
    example_with_processor()

    print("=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    main()
