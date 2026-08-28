from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence
    from typing import Callable

try:
    from nupunkt import sent_tokenize
    NUPUNKT_AVAILABLE = True
except ImportError:
    NUPUNKT_AVAILABLE = False
    sent_tokenize: Callable[[str], Any] = lambda x: []  # type: ignore[no-redef]

try:
    import Levenshtein
    LEVENSHTEIN_AVAILABLE = True
except ImportError:
    LEVENSHTEIN_AVAILABLE = False

from .document import Document

__all__: tuple[str, ...] = (
    "RedlinesProcessor",
    "WholeDocumentProcessor",
    "NupunktProcessor",
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

PARAGRAPH_MARKER = "¶"
"""
The character (U+00B6 PILCROW SIGN) used internally to mark a paragraph boundary.
Renderers convert '¶ ' into '\\n\\n'. Input text that literally contains '¶'
collides with this convention and may render incorrectly.
"""

SENTENCE_MARKER = "¦"
"""
The character (U+00A6 BROKEN BAR) used internally to mark a sentence boundary
within a paragraph in sentence-level tokenization (`NupunktProcessor`).

Because '¦' is neither whitespace nor a parenthesis, the tokenizer emits '¦ '
as a single token — exactly like '¶ ' — so it anchors `SequenceMatcher` at
sentence boundaries (a change cannot silently span sentences) without encoding
fake paragraph structure. Renderers strip it entirely, so it never appears in
output. As with '¶', input text that literally contains '¦ ' collides with this
convention and will be silently dropped from rendered output.
"""

punctuation_token_pattern = re.compile(r"[^\w\s]+")
r"""
It is used to detect a normalized token that consists entirely of punctuation.

* `[^\w\s]` matches any character that is neither a word character (`\w`) nor a
  whitespace character (`\s`), which covers parentheses, punctuation marks
  (.?!-) and other unicode punctuation such as em-dashes and quotes.
* `[^\w\s]+` is the previous character class repeated one or more times.
"""


def _is_punctuation_only(token: str) -> bool:
    """
    Returns True if a normalized (whitespace-stripped) token consists entirely of
    punctuation, or is empty.

    The paragraph boundary token '¶' is explicitly excluded: although it is a
    punctuation character, merging edits across it would pull paragraph breaks
    into deletions/insertions and break paragraph handling in the output.

    :param token: The normalized token to test.
    :type token: str
    :return: True if the token is empty or punctuation-only (and not '¶').
    :rtype: bool
    """
    if token == "¶":
        return False
    return token == "" or punctuation_token_pattern.fullmatch(token) is not None


def _merge_ops_split_by_punctuation(
    opcodes: Sequence[tuple[str, int, int, int, int]],
    source_normalized: list[str],
) -> list[tuple[str, int, int, int, int]]:
    """
    Cleanup pass over `SequenceMatcher` opcodes that merges adjacent non-equal
    operations separated only by an 'equal' run of punctuation-only tokens.

    Without this pass, a change such as "thirty (30)" -> "forty (40)" is reported
    as two separate changes because the '(' between "thirty"/"forty" and
    "30"/"40" matches as equal. Merging the two edits (and absorbing the
    punctuation-only equal run between them) reports the single, human-visible
    change instead.

    Because a merged operation is itself non-equal, chains of edits separated by
    punctuation collapse naturally into a single operation. Equal runs at the
    document boundaries are never absorbed, since they are not flanked by
    non-equal operations on both sides. Paragraph boundary tokens ('¶') are
    never merged across (see `_is_punctuation_only`).

    :param opcodes: The opcodes returned by `SequenceMatcher.get_opcodes`.
    :type opcodes: Sequence[tuple[str, int, int, int, int]]
    :param source_normalized: The normalized source tokens the matcher compared.
    :type source_normalized: list[str]
    :return: The opcodes with punctuation-separated edits merged.
    :rtype: list[tuple[str, int, int, int, int]]
    """
    result: list[tuple[str, int, int, int, int]] = []

    for op in opcodes:
        tag, i1, i2, j1, j2 = op
        if (
            tag != "equal"
            and len(result) >= 2
            and result[-1][0] == "equal"
            and result[-2][0] != "equal"
            and all(
                _is_punctuation_only(token)
                for token in source_normalized[result[-1][1] : result[-1][2]]
            )
        ):
            # Merge the previous non-equal op, the punctuation-only equal run,
            # and the current non-equal op into a single operation.
            result.pop()
            prev = result.pop()
            merged_i1, merged_i2 = prev[1], i2
            merged_j1, merged_j2 = prev[3], j2
            if merged_i1 == merged_i2:
                merged_tag = "insert"
            elif merged_j1 == merged_j2:
                merged_tag = "delete"
            else:
                merged_tag = "replace"
            result.append((merged_tag, merged_i1, merged_i2, merged_j1, merged_j2))
        else:
            result.append(op)

    return result


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


def concatenate_sentences_and_add_chr_182(text: str) -> str:
    """
    Split text into paragraphs and sentences, marking the boundaries.

    Paragraph boundaries (one or more newlines) are preserved and marked with
    '¶' (`PARAGRAPH_MARKER`), exactly as in paragraph-level tokenization.
    Within each paragraph, sentences are detected with nupunkt and their
    boundaries are marked with '¦' (`SENTENCE_MARKER`), which renderers strip
    so the input's real paragraph structure is not reflowed.

    Uses intelligent sentence boundary detection that handles:
    - Abbreviations (Dr., Mr., etc.)
    - Decimals and numbers (3.14, $5.99)
    - URLs and email addresses
    - Complex punctuation

    For example: "One. Two.\\n\\nThree."
    Returns: "One. ¦ Two. ¶ Three."

    Note: Requires nupunkt to be installed (Python 3.11+)

    :param text: The text to split into sentences.
    :type text: str
    :return: Text with sentences separated by ' ¦ ' markers within paragraphs,
        and paragraphs separated by ' ¶ ' markers.
    :rtype: str
    :raises ImportError: If nupunkt is not installed.
    """
    if not NUPUNKT_AVAILABLE:
        raise ImportError(
            "Missing required package: nupunkt.\n"
            "\n"
            "Cause: The nupunkt package is required for sentence-level tokenization but is not installed.\n"
            "\n"
            "To fix: Install nupunkt (requires Python 3.11+):\n"
            "  # Using pip\n"
            "  pip install nupunkt>=0.6.0\n"
            "\n"
            "  # Using uv\n"
            "  uv pip install nupunkt>=0.6.0\n"
            "\n"
            "  # Install redlines with nupunkt support\n"
            "  pip install redlines[nupunkt]\n"
        )

    paragraphs = split_paragraphs(text)

    paragraph_results: list[str] = []
    for paragraph in paragraphs:
        sentences = sent_tokenize(paragraph)

        sentence_results: list[str] = []
        for sentence in sentences:
            # sent_tokenize can return either strings or tuples (text, score)
            # We only care about the text
            if isinstance(sentence, tuple):
                text_part = sentence[0]
            else:
                text_part = sentence
            sentence_results.append(text_part.strip())
        paragraph_results.append(" ¦ ".join(sentence_results))

    return " ¶ ".join(paragraph_results)


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

    A cleanup pass merges adjacent edits separated only by punctuation, so a change
    such as "thirty (30)" -> "forty (40)" is reported as a single replace instead of
    two separate changes (see `_merge_ops_split_by_punctuation`).

    By default, ``difflib``'s ``autojunk`` heuristic is disabled. With autojunk on,
    any comparison of 200+ tokens treats tokens occurring in more than 1% of positions
    as unmatchable "popular junk", which silently degrades diffs of repetitive documents
    (schedules, price lists, "Intentionally omitted" runs) into whole-document replaces.
    """

    def __init__(self, *, autojunk: bool = False) -> None:
        """
        :param autojunk: Passed to difflib.SequenceMatcher. Defaults to False because the
            default heuristic silently degrades diffs of repetitive documents of 200+ tokens
            (see ADR-0010); set True to restore difflib's default popular-token heuristic,
            which can be faster on large repetitive documents.
        :type autojunk: bool
        """
        self.autojunk = autojunk

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

        matcher = SequenceMatcher(
            None, seq_source_normalized, seq_test_normalized, autojunk=self.autojunk
        )

        # Merge adjacent edits separated only by punctuation-only equal runs,
        # so e.g. "thirty (30)" -> "forty (40)" is reported as a single change.
        opcodes = _merge_ops_split_by_punctuation(
            matcher.get_opcodes(), seq_source_normalized
        )

        return [
            DiffOperation(
                source_chunk=Chunk(text=source_tokens, chunk_location=None),
                test_chunk=Chunk(text=test_tokens, chunk_location=None),
                opcodes=opcode,
            )
            for opcode in opcodes
        ]


class NupunktProcessor(RedlinesProcessor):
    """
    A redlines processor that uses nupunkt for intelligent sentence boundary detection.

    This processor splits documents into sentences using nupunkt's advanced tokenization,
    which better handles:
    - Abbreviations (Dr., Mr., etc.)
    - Decimals and numbers (3.14, $5.99)
    - URLs and email addresses
    - Complex punctuation

    The result is sentence-level granularity in diffs, providing more precise change detection
    compared to paragraph-level comparison. Paragraph boundaries in the input are preserved:
    sentences are anchored within their paragraph with an invisible marker, so rendered output
    keeps the document's real paragraph structure instead of reflowing one sentence per paragraph.

    A cleanup pass merges adjacent edits separated only by punctuation, so a change
    such as "thirty (30)" -> "forty (40)" is reported as a single replace instead of
    two separate changes (see `_merge_ops_split_by_punctuation`).

    Note: Requires nupunkt>=0.6.0 (Python 3.11+)

    Example:
        ```python
        from redlines import Redlines
        from redlines.processor import NupunktProcessor

        processor = NupunktProcessor()
        r = Redlines(source, test, processor=processor)
        ```
    """

    def __init__(self, *, autojunk: bool = False) -> None:
        """
        :param autojunk: Passed to difflib.SequenceMatcher. Defaults to False because the
            default heuristic silently degrades diffs of repetitive documents of 200+ tokens
            (see ADR-0010); set True to restore difflib's default popular-token heuristic,
            which can be faster on large repetitive documents.
        :type autojunk: bool
        """
        self.autojunk = autojunk

    def process(self, source: Document | str, test: Document | str) -> list[DiffOperation]:
        """
        Compare two documents using sentence-level tokenization.

        Paragraph boundaries are preserved ('¶' markers), and sentence boundaries
        within each paragraph are anchored with render-invisible '¦' markers.

        :param source: The source document to compare.
        :type source: Document | str
        :param test: The test document to compare.
        :type test: Document | str
        :return: A list of `DiffOperation` that describe the differences between the two documents.
        :rtype: list[DiffOperation]
        :raises ImportError: If nupunkt is not installed.
        """
        # Extract text from documents if needed
        source_text = source.text if isinstance(source, Document) else source
        test_text = test.text if isinstance(test, Document) else test

        # Tokenize the texts using nupunkt sentence boundaries
        source_tokens = tokenize_text(
            concatenate_sentences_and_add_chr_182(source_text)
        )
        test_tokens = tokenize_text(concatenate_sentences_and_add_chr_182(test_text))

        # Normalize tokens by stripping whitespace for comparison
        # This allows the matcher to focus on content differences rather than whitespace variations
        # while still preserving the original tokens (including whitespace) for display in the output
        seq_source_normalized = [token.strip() for token in source_tokens]
        seq_test_normalized = [token.strip() for token in test_tokens]

        matcher = SequenceMatcher(
            None, seq_source_normalized, seq_test_normalized, autojunk=self.autojunk
        )

        # Merge adjacent edits separated only by punctuation-only equal runs,
        # so e.g. "thirty (30)" -> "forty (40)" is reported as a single change.
        opcodes = _merge_ops_split_by_punctuation(
            matcher.get_opcodes(), seq_source_normalized
        )

        return [
            DiffOperation(
                source_chunk=Chunk(text=source_tokens, chunk_location=None),
                test_chunk=Chunk(text=test_tokens, chunk_location=None),
                opcodes=opcode,
            )
            for opcode in opcodes
        ]
