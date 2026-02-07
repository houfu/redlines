"""DOCX document support for redlines.

Provides format-aware comparison of ``.docx`` files.  Each word-level token
carries both its text and formatting properties (bold, italic, font, paragraph
style, etc.).  The diff algorithm treats tokens as different when *either* text
or formatting changes, so a word going from normal to bold shows up as a
replacement even though the text is identical.

Installation
------------

DOCX support requires ``lxml``::

    pip install lxml

    # or install redlines with the docx extra
    pip install redlines[docx]

Usage
-----

::

    from redlines import Redlines
    from redlines.docx import DocxFile

    source = DocxFile("contract_v1.docx")
    test = DocxFile("contract_v2.docx")

    diff = Redlines(source, test)
    print(diff.output_json(pretty=True))
"""

from __future__ import annotations

import os
import re
from difflib import SequenceMatcher
from typing import Any

from .document import Document
from .processor import Chunk, DiffOperation, RedlinesProcessor, RichToken

__all__: tuple[str, ...] = ("DocxFile", "DocxProcessor", "DOCX_AVAILABLE")

try:
    from lxml import etree as _etree  # type: ignore[attr-defined]  # noqa: F401

    from .docx_parser import parse_docx

    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    parse_docx = None  # type: ignore[assignment]

# Re-use the same word-level tokenizer as the plain-text processor.
_tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")


# ── Helpers ───────────────────────────────────────────────────────────

def _tokenize_run_text(text: str) -> list[str]:
    """Split run text into word-level tokens."""
    return re.findall(_tokenizer, text)


def _build_rich_tokens(
    paragraphs: list[dict[str, Any]],
) -> list[RichToken]:
    """Convert parsed paragraph data into a flat list of ``RichToken`` objects.

    Paragraph properties are merged into every word token so that each token
    carries a complete flat snapshot of both character and paragraph formatting.
    Paragraphs are separated by a ``¶`` marker token (matching the convention
    used by the plain-text processors).
    """
    tokens: list[RichToken] = []

    for para in paragraphs:
        para_props: dict[str, str] = para["properties"]
        runs: list[dict[str, Any]] = para["runs"]

        if not runs:
            continue

        # Paragraph separator
        if tokens:
            tokens.append(RichToken(text=" ¶ ", formatting=()))

        for run in runs:
            run_text: str = run["text"]
            run_props: dict[str, str] = run["properties"]

            # Merge paragraph + run props into a flat dict
            merged = {**para_props, **run_props}
            formatting = tuple(sorted(merged.items()))

            for word in _tokenize_run_text(run_text):
                tokens.append(RichToken(text=word, formatting=formatting))

    return tokens


# ── DocxFile ──────────────────────────────────────────────────────────

class DocxFile(Document):
    """Document class for ``.docx`` files with rich formatting metadata.

    Implements the ``Document`` interface so it can be passed directly to
    ``Redlines``.  When both source and test are ``DocxFile`` objects the
    ``Redlines`` constructor auto-selects ``DocxProcessor`` for format-aware
    comparison.

    :param file_path: Path to a ``.docx`` file.
    :raises ImportError: If ``lxml`` is not installed.
    """

    _text: str
    _rich_tokens: list[RichToken]
    _paragraphs: list[dict[str, Any]]

    def __init__(self, file_path: str | bytes | os.PathLike[str]) -> None:
        if not DOCX_AVAILABLE:
            raise ImportError(
                "Missing required package: lxml.\n"
                "\n"
                "Cause: The lxml package is required for DOCX support but is not installed.\n"
                "\n"
                "To fix: Install lxml:\n"
                "  pip install lxml\n"
                "\n"
                "  # Install redlines with DOCX support\n"
                "  pip install redlines[docx]\n"
            )

        self._paragraphs = parse_docx(file_path)
        self._rich_tokens = _build_rich_tokens(self._paragraphs)

        # Plain text for backward-compatible .text property
        text_parts: list[str] = []
        for para in self._paragraphs:
            para_text = "".join(run["text"] for run in para["runs"])
            if para_text:
                text_parts.append(para_text)
        self._text = "\n\n".join(text_parts)

    @property
    def text(self) -> str:
        """Plain text extracted from the document (no formatting)."""
        return self._text

    @property
    def rich_tokens(self) -> list[RichToken]:
        """Flat list of word-level tokens with formatting metadata."""
        return self._rich_tokens

    @property
    def paragraphs(self) -> list[dict[str, Any]]:
        """Raw paragraph structure as returned by the parser."""
        return self._paragraphs


# ── DocxProcessor ─────────────────────────────────────────────────────

class DocxProcessor(RedlinesProcessor):
    """Processor that compares two ``DocxFile`` documents at word level.

    Comparison uses ``RichToken`` objects so that both text *and* formatting
    are considered.  A word whose text is unchanged but whose formatting
    differs will appear as a ``replace`` operation.
    """

    def process(
        self, source: Document | str, test: Document | str
    ) -> list[DiffOperation]:
        if not isinstance(source, DocxFile) or not isinstance(test, DocxFile):
            raise TypeError(
                "DocxProcessor requires DocxFile inputs.\n"
                "\n"
                "Cause: Both source and test must be DocxFile instances.\n"
                "\n"
                "To fix:\n"
                "  source = DocxFile('old.docx')\n"
                "  test = DocxFile('new.docx')\n"
                "  diff = Redlines(source, test)\n"
            )

        source_tokens = source.rich_tokens
        test_tokens = test.rich_tokens

        # Normalize text whitespace for comparison, keeping formatting intact.
        source_norm = [rt.normalized() for rt in source_tokens]
        test_norm = [rt.normalized() for rt in test_tokens]

        matcher = SequenceMatcher(None, source_norm, test_norm)

        # Plain-text token lists for backward-compatible Chunk.text
        source_text_tokens = [rt.text for rt in source_tokens]
        test_text_tokens = [rt.text for rt in test_tokens]

        source_chunk = Chunk(
            text=source_text_tokens,
            chunk_location=None,
            rich_tokens=source_tokens,
        )
        test_chunk = Chunk(
            text=test_text_tokens,
            chunk_location=None,
            rich_tokens=test_tokens,
        )

        return [
            DiffOperation(
                source_chunk=source_chunk,
                test_chunk=test_chunk,
                opcodes=opcode,
            )
            for opcode in matcher.get_opcodes()
        ]
