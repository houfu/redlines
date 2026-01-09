"""
PDF document support for redlines.

This module provides the PDFFile class for comparing text-based PDFs.
Requires the optional 'pdf' dependency group: pip install redlines[pdf]
"""

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .document import Document

__all__: tuple[str, ...] = ("PDFFile", "PDFPage", "PDF_AVAILABLE")

# Lazy import check pattern (following nupunkt pattern)
try:
    import pdfplumber

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    pdfplumber = None  # type: ignore[assignment]

if TYPE_CHECKING:
    import pdfplumber


@dataclass
class PDFPage:
    """Represents a single page from a PDF document."""

    page_number: int
    """The 1-indexed page number"""
    text: str
    """The extracted text content from this page"""


class PDFFile(Document):
    """
    Document class for reading text-based PDF files.

    This class extracts text from PDF files for comparison with redlines.
    Note: Only text-based PDFs are supported. Scanned/image PDFs require OCR
    which is not currently supported.

    Example:
        ```python
        from redlines import Redlines
        from redlines.pdf import PDFFile

        source = PDFFile("contract_v1.pdf")
        test = PDFFile("contract_v2.pdf")

        redline = Redlines(source, test)
        print(redline.output_markdown)
        ```

    :param file_path: Path to the PDF file
    :param preserve_pages: If True, inserts page markers in extracted text
    """

    _text: str
    _pages: list[PDFPage]
    _preserve_pages: bool

    def __init__(
        self,
        file_path: str | bytes | os.PathLike[str],
        preserve_pages: bool = False,
    ) -> None:
        """
        Use this class so that Redlines can read PDF files.

        :param file_path: Path to the PDF file.
        :type file_path: str | bytes | os.PathLike[str]
        :param preserve_pages: If True, inserts [Page N] markers in the extracted text.
        :type preserve_pages: bool
        """
        if not PDF_AVAILABLE:
            raise ImportError(
                "Missing required package: pdfplumber.\n"
                "\n"
                "Cause: The pdfplumber package is required for PDF support but is not installed.\n"
                "\n"
                "To fix: Install pdfplumber:\n"
                "  # Using pip\n"
                "  pip install pdfplumber\n"
                "\n"
                "  # Using uv\n"
                "  uv pip install pdfplumber\n"
                "\n"
                "  # Install redlines with PDF support\n"
                "  pip install redlines[pdf]\n"
            )

        self._pages = []
        self._preserve_pages = preserve_pages
        self._extract_text(file_path)

    def _extract_text(self, file_path: str | bytes | os.PathLike[str]) -> None:
        """Extract text from PDF file."""
        text_parts: list[str] = []

        with pdfplumber.open(file_path) as pdf:  # type: ignore[arg-type]
            for i, page in enumerate(pdf.pages, start=1):
                page_text = page.extract_text() or ""
                self._pages.append(PDFPage(page_number=i, text=page_text))

                if self._preserve_pages and page_text.strip():
                    text_parts.append(f"[Page {i}]\n{page_text}")
                else:
                    text_parts.append(page_text)

        # Join with double newlines to preserve paragraph structure
        self._text = "\n\n".join(text_parts)

    @property
    def text(self) -> str:
        """
        Return the extracted text from the PDF.

        :return: The text content of the PDF file.
        """
        return self._text

    @property
    def pages(self) -> list[PDFPage]:
        """
        Return list of PDFPage objects for page-level access.

        :return: List of PDFPage objects containing page number and text.
        """
        return self._pages

    @property
    def page_count(self) -> int:
        """
        Return the number of pages in the PDF.

        :return: The number of pages.
        """
        return len(self._pages)
