"""Tests for PDF document support."""

import pytest

from redlines import Redlines
from redlines.pdf import PDF_AVAILABLE


@pytest.mark.skipif(not PDF_AVAILABLE, reason="pdfplumber not installed")
class TestPDFFile:
    """Tests for PDFFile functionality."""

    def test_basic_pdf_text_extraction(self) -> None:
        """Test basic text extraction from PDF."""
        from redlines.pdf import PDFFile

        pdf = PDFFile("tests/documents/PDFFile/source.pdf")
        assert len(pdf.text) > 0
        assert "quick brown fox" in pdf.text.lower()

    def test_pdf_text_content(self) -> None:
        """Test that PDF text extraction returns expected content."""
        from redlines.pdf import PDFFile

        source = PDFFile("tests/documents/PDFFile/source.pdf")
        assert source.text == "The quick brown fox jumps over the lazy dog."

        test = PDFFile("tests/documents/PDFFile/test.pdf")
        assert test.text == "The quick brown fox walks past the lazy dog."

    def test_pdf_comparison(self) -> None:
        """Test comparing two PDF files."""
        from redlines.pdf import PDFFile

        source = PDFFile("tests/documents/PDFFile/source.pdf")
        test = PDFFile("tests/documents/PDFFile/test.pdf")

        redline = Redlines(source, test)
        assert redline.stats().total_changes > 0

    def test_pdf_with_redlines_output(self) -> None:
        """Test PDF comparison produces valid markdown output."""
        from redlines.pdf import PDFFile

        source = PDFFile("tests/documents/PDFFile/source.pdf")
        test = PDFFile("tests/documents/PDFFile/test.pdf")

        redline = Redlines(source, test)
        output = redline.output_markdown

        # Should contain expected markup for changes
        assert "jumps over" in output
        assert "walks past" in output

    def test_pdf_comparison_matches_plaintext(self) -> None:
        """Test that PDF comparison produces same result as PlainTextFile."""
        from redlines.pdf import PDFFile

        source = PDFFile("tests/documents/PDFFile/source.pdf")
        test = PDFFile("tests/documents/PDFFile/test.pdf")

        redline = Redlines(source, test)
        assert (
            redline.output_markdown
            == "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog."
        )

    def test_pdf_page_count(self) -> None:
        """Test page count property."""
        from redlines.pdf import PDFFile

        pdf = PDFFile("tests/documents/PDFFile/source.pdf")
        assert pdf.page_count >= 1

    def test_pdf_pages_property(self) -> None:
        """Test pages property returns PDFPage objects."""
        from redlines.pdf import PDFFile

        pdf = PDFFile("tests/documents/PDFFile/source.pdf")
        assert len(pdf.pages) == pdf.page_count
        assert all(hasattr(p, "page_number") and hasattr(p, "text") for p in pdf.pages)

    def test_pdf_preserve_pages_option(self) -> None:
        """Test preserve_pages option adds page markers."""
        from redlines.pdf import PDFFile

        pdf = PDFFile("tests/documents/PDFFile/source.pdf", preserve_pages=True)
        if pdf.page_count > 0:
            assert "[Page 1]" in pdf.text


def test_pdf_availability_flag() -> None:
    """Test that PDF_AVAILABLE flag is set correctly."""
    from redlines.pdf import PDF_AVAILABLE as PDF_FLAG

    # Flag should be True since we have pdfplumber installed for tests
    # This test verifies the import mechanism works
    assert isinstance(PDF_FLAG, bool)
