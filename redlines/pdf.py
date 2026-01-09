"""
# PDF Document Support

This module provides PDF file support for the redlines library through the `PDFFile` class.

## Overview

The `PDFFile` class extends the `Document` abstract base class to enable text extraction
from PDF files for comparison. It uses the pdfplumber library for robust text extraction
with support for future page-level and position-aware comparison features.

## Installation

PDF support is an optional dependency:

```bash
pip install redlines[pdf]
```

This will install pdfplumber, which provides:
- High-quality text extraction from text-based PDFs
- Word and character-level bounding box information (for future features)
- Support for complex layouts (columns, tables)

## Usage

### Basic Comparison

```python
from redlines import Redlines
from redlines.pdf import PDFFile

# Load PDFs
source = PDFFile("contract_v1.pdf")
test = PDFFile("contract_v2.pdf")

# Compare
diff = Redlines(source, test)
print(diff.output_markdown)
```

### CLI Usage

PDF files are automatically detected by file extension:

```bash
redlines contract_v1.pdf contract_v2.pdf --pretty
```

### Page-Level Access

```python
pdf = PDFFile("document.pdf")

# Access all pages
for page in pdf.pages:
    print(f"Page {page.page_number}: {len(page.text)} characters")

# Get total page count
print(f"Total pages: {pdf.page_count}")
```

### Preserve Page Markers

```python
# Insert [Page N] markers in extracted text
pdf = PDFFile("document.pdf", preserve_pages=True)
print(pdf.text)  # Contains "[Page 1]\n...\n[Page 2]\n..."
```

## Limitations

This is a **text dump** implementation - it extracts plain text only:

- **Text-based PDFs only**: Scanned/image PDFs require OCR (not supported)
- **No layout preservation**: Multi-column layouts, tables, and formatting are flattened
- **No structure awareness**: Headers/footers, footnotes, signature blocks extracted in reading order
- **For complex legal documents**: Consider dedicated tools (Draftable, Workshare Compare, etc.)

## Future Enhancements

The module is designed to support future chunk-level comparison features:
- Page-level diff tracking using `Chunk.chunk_location`
- Paragraph and section-level granularity
- Bounding box information for visual diff rendering
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from .document import Document

__all__: tuple[str, ...] = ("PDFFile", "PDFPage", "PDF_AVAILABLE")

# Lazy import check pattern (following nupunkt pattern)
try:
    import pdfplumber

    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    pdfplumber = None  # type: ignore[assignment]


@dataclass
class PDFPage:
    """
    Represents a single page from a PDF document.

    Provides access to both the page number and extracted text content.
    This allows for page-level analysis and tracking of where changes occur
    within multi-page documents.

    Example:
        ```python
        pdf = PDFFile("document.pdf")
        for page in pdf.pages:
            if "important" in page.text.lower():
                print(f"Found on page {page.page_number}")
        ```
    """

    page_number: int
    """The 1-indexed page number (first page is 1, not 0)"""
    text: str
    """The extracted text content from this page"""


class PDFFile(Document):
    """
    Document class for reading and extracting text from PDF files.

    This class implements the Document interface to enable PDF comparison with redlines.
    It uses pdfplumber for high-quality text extraction and provides page-level access
    to the document structure.

    **Features:**
    - Automatic text extraction from all pages
    - Page-level access via the `pages` property
    - Optional page markers for multi-page awareness
    - Compatible with all redlines comparison features

    **Limitations:**
    - Text dump only - multi-column layouts, tables, headers/footers are flattened
    - No OCR support for scanned documents
    - Best suited for simple PDFs; complex legal contracts may need specialized tools

    **Example - Basic Comparison:**
        ```python
        from redlines import Redlines
        from redlines.pdf import PDFFile

        source = PDFFile("contract_v1.pdf")
        test = PDFFile("contract_v2.pdf")

        redline = Redlines(source, test)
        print(redline.output_markdown)
        ```

    **Example - Page-Level Analysis:**
        ```python
        pdf = PDFFile("document.pdf")
        print(f"Document has {pdf.page_count} pages")

        for page in pdf.pages:
            print(f"Page {page.page_number}: {len(page.text)} chars")
        ```

    **Example - With Page Markers:**
        ```python
        # Insert [Page N] markers to track page boundaries
        pdf = PDFFile("document.pdf", preserve_pages=True)
        print(pdf.text)  # Contains "[Page 1]\n...[Page 2]\n..."
        ```

    :param file_path: Path to the PDF file (string, bytes, or PathLike)
    :param preserve_pages: If True, inserts [Page N] markers in extracted text
    :raises ImportError: If pdfplumber is not installed
    :raises FileNotFoundError: If the PDF file does not exist
    :raises Exception: If the PDF cannot be read or parsed
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
        """
        Extract text from all pages of the PDF file.

        This method reads the PDF using pdfplumber and extracts text from each page.
        Pages are joined with double newlines to preserve paragraph structure.
        If preserve_pages is True, [Page N] markers are inserted.

        :param file_path: Path to the PDF file
        :type file_path: str | bytes | os.PathLike[str]
        :raises Exception: If PDF cannot be read or parsed
        """
        text_parts: list[str] = []

        with pdfplumber.open(str(file_path)) as pdf:
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
        Return the extracted text from all pages of the PDF.

        This property implements the Document interface's required `text` property.
        The text is extracted from all pages and joined with double newlines to
        preserve paragraph structure. If preserve_pages was True during initialization,
        the text will contain [Page N] markers.

        Example:
            ```python
            pdf = PDFFile("document.pdf")
            full_text = pdf.text
            word_count = len(full_text.split())
            ```

        :return: The complete text content of the PDF file as a single string
        :rtype: str
        """
        return self._text

    @property
    def pages(self) -> list[PDFPage]:
        """
        Return list of PDFPage objects for page-level access.

        Each PDFPage object contains the page number and extracted text for that page.
        This allows for page-level analysis, search, or filtering.

        Example:
            ```python
            pdf = PDFFile("document.pdf")

            # Find pages containing specific text
            matching_pages = [p for p in pdf.pages if "keyword" in p.text]

            # Get text from specific page
            first_page_text = pdf.pages[0].text
            ```

        :return: List of PDFPage objects, one per page in document order
        :rtype: list[PDFPage]
        """
        return self._pages

    @property
    def page_count(self) -> int:
        """
        Return the total number of pages in the PDF.

        This is a convenience property equivalent to `len(pdf.pages)`.

        Example:
            ```python
            pdf = PDFFile("document.pdf")
            if pdf.page_count > 10:
                print("Long document")
            ```

        :return: The total number of pages
        :rtype: int
        """
        return len(self._pages)
