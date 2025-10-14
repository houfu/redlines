from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Literal

from .document import Document

__all__: tuple[str, ...] = (
    "RedlinesProcessor",
    "WholeDocumentProcessor",
    "Redline",
    "Stats",
    "DiffOperation",
    "Chunk",
)

tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")
r"""
This regular expression matches a group of characters that can include any character except for parentheses
and whitespace characters (which include spaces, tabs, and line breaks) or any character
that is a parenthesis or punctuation mark (.?!-).
The group can also include any whitespace characters that follow these characters.

Breaking it down further:

* `(` and `)` indicate a capturing group
* `(?: )` is a non-capturing group, meaning it matches the pattern but doesn't capture the matched text
* `[^()\s]+` matches one or more characters that are not parentheses or whitespace characters
* `|` indicates an alternative pattern
* `[().?!-]` matches any character that is a parenthesis or punctuation mark `(.?!-)`
* `\s*` matches zero or more whitespace characters (spaces, tabs, or line breaks) that follow the previous pattern.
"""
# This pattern matches one or more newline characters `\n`, and any spaces between them.

paragraph_pattern = re.compile(r"((?:\n *)+)")
r"""
It is used to split the text into paragraphs.

* `(?:\\n *)` is a non-capturing group that must start with a `\\n`   and be followed by zero or more spaces.
* `((?:\\n *)+)` is the previous non-capturing group repeated one or more times.
"""

space_pattern = re.compile(r"(\s+)")
"""It is used to detect space."""


def tokenize_text(text: str) -> list[str]:
    """
    Tokenizes a string into a list of tokens. A token is defined as a group of characters that can include any character except for parentheses
    and whitespace characters (which include spaces, tabs, and line breaks) or any character that is a parenthesis or punctuation mark (.?!-).
    The group can also include any whitespace characters that follow these characters.
    For example, if the text is "Hello, world! This is a test.", the result will be:
    ['Hello, ', 'world! ', 'This ', 'is ', 'a ', 'test.']

    :param text: The text to tokenize.
    :type text: str
    :return: a list of tokens.
    :rtype: list[str]
    """
    # NOTE: Single capturing group hence findall returns list of strings
    matches: list[str] = re.findall(tokenizer, text)
    return matches


def split_paragraphs(text: str) -> list[str]:
    """
    Splits a string into a list of paragraphs. One or more `\n` splits the paragraphs.
    For example, if the text is "Hello\nWorld\nThis is a test", the result will be:
    ['Hello', 'World', 'This is a test']

    :param text: The text to split.
    :type text: str
    :return: a list of paragraphs.
    :rtype: list[str]
    """
    # NOTE: Single capturing group hence split returns list of strings
    split_text: list[str] = re.split(paragraph_pattern, text)
    result: list[str] = []
    for s in split_text:
        if s and not re.fullmatch(space_pattern, s):
            result.append(s.strip())

    return result


def concatenate_paragraphs_and_add_chr_182(text: str) -> str:
    """
    Split paragraphs and concatenate them. Then add a character '¶' between paragraphs.
    For example, if the text is "Hello\nWorld\nThis is a test", the result will be:
    "Hello¶World¶This is a test"

    :param text: The text to split.
    :type text: str
    :return: a list of paragraphs.
    :rtype: str
    """
    paragraphs = split_paragraphs(text)

    result: list[str] = []
    for p in paragraphs:
        result.append(p)
        result.append(" ¶ ")
        # Add a string ' ¶ ' between paragraphs.
    if len(paragraphs) > 0:
        result.pop()

    return "".join(result)


@dataclass
class Chunk:
    """A chunk of text that is being compared. In some cases, it may be the whole document"""

    text: list[str]
    """The tokens of the chunk"""
    chunk_location: str | None
    """An optional string describing the location of the chunk in the document. For example, a PDF page number"""


@dataclass
class DiffOperation:
    """Internal representation of a diff operation (includes 'equal' operations for rendering)"""

    source_chunk: Chunk
    test_chunk: Chunk
    """The chunk of text that is being compared"""
    opcodes: tuple[str, int, int, int, int]
    """The opcodes that describe the operation. See the difflib documentation for more information"""


@dataclass
class Redline:
    """
    A structured representation of a single change between source and test text.

    This class provides a user-friendly interface for accessing diff information,
    with direct access to the changed text and position information.
    """

    operation: Literal["delete", "insert", "replace"]
    """The type of change: 'delete', 'insert', or 'replace'"""

    source_text: str | None
    """The text from the source document. Present for 'delete' and 'replace' operations."""

    test_text: str | None
    """The text from the test document. Present for 'insert' and 'replace' operations."""

    source_position: tuple[int, int] | None
    """Position in source tokens as (start, end). None for 'insert' operations."""

    test_position: tuple[int, int] | None
    """Position in test tokens as (start, end). None for 'delete' operations."""


@dataclass
class Stats:
    """
    Statistics about the changes between source and test text.

    Provides a comprehensive summary of all changes including counts by operation type,
    change size metrics, character-level statistics, and optional Levenshtein distance.
    """

    total_changes: int
    """Total number of changes (deletions + insertions + replacements)"""

    deletions: int
    """Number of deletion operations"""

    insertions: int
    """Number of insertion operations"""

    replacements: int
    """Number of replacement operations"""

    # Advanced analytics fields
    longest_change_length: int
    """Length of the longest change in characters"""

    shortest_change_length: int | None
    """Length of the shortest change in characters (None if no changes)"""

    average_change_length: float
    """Average length of all changes in characters"""

    change_ratio: float
    """Ratio of changed characters to total characters (0.0 to 1.0)"""

    chars_added: int
    """Total number of characters added"""

    chars_deleted: int
    """Total number of characters deleted"""

    chars_net_change: int
    """Net change in characters (added - deleted)"""

    levenshtein_distance: int | None = None
    """Levenshtein distance between source and test text (None if library not available)"""


class RedlinesProcessor(ABC):
    """
    An abstract class that defines the interface for a redlines processor.
    A redlines processor is a class that takes two documents and generates diff operations from them.
    Use this class as a base class if you want to create a custom redlines processor.
    See `WholeDocumentProcessor` for an example of a redlines processor.
    """

    @abstractmethod
    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        pass


class WholeDocumentProcessor(RedlinesProcessor):
    """
    A redlines processor that compares two documents. It compares the entire documents as a single chunk.
    """

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        """
        Compare two documents as a single chunk.

        :param source: The source document to compare.
        :type source: Document | str
        :param test: The test document to compare.
        :type test: Document | str
        :return: A list of `DiffOperation` that describe the differences between the two documents.
        :rtype: list[DiffOperation]
        """
                # --- Input validation with actionable error messages ---
        if not isinstance(source, (Document, str)):
            raise ValueError(
                "Invalid input type for 'source'. "
                f"Expected a 'Document' or 'str', but got '{type(source).__name__}'. "
                "Why it went wrong: The comparison process requires readable text content. "
                "How to fix: Pass either a text string or a 'Document' object.\n\n"
                "Example:\n"
                "    processor.process('text1', 'text2')\n"
                "    or\n"
                "    processor.process(Document('file1.txt'), Document('file2.txt'))"
            )

        if not isinstance(test, (Document, str)):
            raise ValueError(
                "Invalid input type for 'test'. "
                f"Expected a 'Document' or 'str', but got '{type(test).__name__}'. "
                "Why it went wrong: The comparison target must be text-based. "
                "How to fix: Pass either a text string or a 'Document' object."
            )

        if isinstance(source, str) and source.strip() == "":
            raise ValueError(
                "Empty 'source' text detected. "
                "Why it went wrong: The source document has no content to compare. "
                "How to fix: Provide valid text content for comparison."
            )

        if isinstance(test, str) and test.strip() == "":
            raise ValueError(
                "Empty 'test' text detected. "
                "Why it went wrong: The test document has no content to compare. "
                "How to fix: Provide valid text content for comparison."
            )

        # Extract text from documents if needed
        source_text = source.text if isinstance(source, Document) else source
        test_text = test.text if isinstance(test, Document) else test

        # Tokenize the texts
        source_tokens = tokenize_text(
            concatenate_paragraphs_and_add_chr_182(source_text)
        )
        test_tokens = tokenize_text(concatenate_paragraphs_and_add_chr_182(test_text))

        # Normalize tokens by stripping whitespace for comparison
        # This allows the matcher to focus on content differences rather than whitespace variations
        # while still preserving the original tokens (including whitespace) for display in the output
        seq_source_normalized = [token.strip() for token in source_tokens]
        seq_test_normalized = [token.strip() for token in test_tokens]

        matcher = SequenceMatcher(None, seq_source_normalized, seq_test_normalized)

        return [
            DiffOperation(
                source_chunk=Chunk(text=source_tokens, chunk_location=None),
                test_chunk=Chunk(text=test_tokens, chunk_location=None),
                opcodes=opcode,
            )
            for opcode in matcher.get_opcodes()
        ]
