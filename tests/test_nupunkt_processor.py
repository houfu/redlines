"""Tests for NupunktProcessor."""
import pytest

from redlines import Redlines
from redlines.processor import NUPUNKT_AVAILABLE, NupunktProcessor


@pytest.mark.skipif(not NUPUNKT_AVAILABLE, reason="nupunkt not installed")
class TestNupunktProcessor:
    """Test NupunktProcessor functionality."""

    def test_basic_sentence_detection(self) -> None:
        """Test basic sentence boundary detection."""
        source = "Sentence one. Sentence two."
        test = "Sentence one. Modified two."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        assert len(changes) == 1
        assert changes[0].operation == "replace"

    def test_abbreviations(self) -> None:
        """Test handling of abbreviations (Dr., Mr., etc.)."""
        source = "Dr. Smith visited Mr. Jones yesterday."
        test = "Dr. Smith met Mr. Jones yesterday."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should correctly identify the change without splitting on abbreviations
        assert len(changes) == 1
        assert changes[0].source_text is not None and "visited" in changes[0].source_text
        assert changes[0].test_text is not None and "met" in changes[0].test_text

    def test_decimals(self) -> None:
        """Test handling of decimal numbers."""
        source = "The price is $3.50 today."
        test = "The price is $4.50 today."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should not split on decimal point
        assert len(changes) == 1
        assert changes[0].source_text is not None and "$3.50" in changes[0].source_text
        assert changes[0].test_text is not None and "$4.50" in changes[0].test_text

    def test_urls_and_emails(self) -> None:
        """Test handling of URLs and email addresses."""
        source = "Visit example.com for info."
        test = "Visit example.org for info."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should not split on dots in URLs
        assert len(changes) == 1
        assert changes[0].source_text is not None and "example.com" in changes[0].source_text
        assert changes[0].test_text is not None and "example.org" in changes[0].test_text

    def test_legal_citations(self) -> None:
        """Test handling of legal citations with abbreviations."""
        source = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2020)."
        test = "See Smith v. Jones, 123 F.3d 456 (9th Cir. 2021)."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should correctly handle legal abbreviations
        assert len(changes) == 1
        assert changes[0].source_text is not None and "2020" in changes[0].source_text
        assert changes[0].test_text is not None and "2021" in changes[0].test_text

    def test_initials_and_acronyms(self) -> None:
        """Test handling of initials and acronyms with periods."""
        source = "J.R.R. Tolkien and the U.S.A. are famous."
        test = "J.R.R. Tolkien and the U.K. are famous."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should not split on periods in initials/acronyms
        assert len(changes) == 1
        assert changes[0].source_text is not None and "U.S.A." in changes[0].source_text
        assert changes[0].test_text is not None and "U.K." in changes[0].test_text

    def test_multiple_sentences(self) -> None:
        """Test correct handling of multiple sentences."""
        source = "First sentence. Second sentence. Third sentence."
        test = "First sentence. Modified sentence. Third sentence."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should detect change in second sentence
        assert len(changes) == 1
        assert changes[0].source_text is not None and "Second" in changes[0].source_text
        assert changes[0].test_text is not None and "Modified" in changes[0].test_text

    def test_complex_punctuation(self) -> None:
        """Test handling of complex punctuation."""
        source = 'He asked, "Are you sure?" She replied, "Yes!"'
        test = 'He asked, "Are you certain?" She replied, "Yes!"'

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should handle quotes and punctuation correctly
        assert len(changes) == 1
        assert changes[0].source_text is not None and "sure" in changes[0].source_text
        assert changes[0].test_text is not None and "certain" in changes[0].test_text

    def test_ellipsis(self) -> None:
        """Test handling of ellipsis."""
        source = "She said... well... never mind."
        test = "She said... um... never mind."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should not split on ellipsis
        assert len(changes) == 1
        assert changes[0].source_text is not None and "well" in changes[0].source_text
        assert changes[0].test_text is not None and "um" in changes[0].test_text

    def test_paragraph_boundaries(self) -> None:
        """Test that paragraph boundaries are respected."""
        source = "First paragraph.\n\nSecond paragraph here."
        test = "First paragraph.\n\nSecond modified here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should detect change in second paragraph
        assert len(changes) == 1
        assert changes[0].source_text is not None and "paragraph" in changes[0].source_text
        assert changes[0].test_text is not None and "modified" in changes[0].test_text

    def test_no_changes(self) -> None:
        """Test when there are no changes."""
        source = "This is a test. Nothing changes."
        test = "This is a test. Nothing changes."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        # Should have no changes
        assert len(changes) == 0

    def test_compare_with_whole_document_processor(self) -> None:
        """Test that NupunktProcessor detects same changes as WholeDocumentProcessor."""
        from redlines.processor import WholeDocumentProcessor

        source = "The quick brown fox jumps over the lazy dog."
        test = "The quick red fox jumps over the lazy dog."

        # NupunktProcessor
        nupunkt_processor = NupunktProcessor()
        nupunkt_redlines = Redlines(source, test, processor=nupunkt_processor)
        nupunkt_changes = nupunkt_redlines.redlines

        # WholeDocumentProcessor
        whole_processor = WholeDocumentProcessor()
        whole_redlines = Redlines(source, test, processor=whole_processor)
        whole_changes = whole_redlines.redlines

        # Both should detect the same number of changes
        assert len(nupunkt_changes) == len(whole_changes)

        # Both should detect same change
        assert nupunkt_changes[0].operation == whole_changes[0].operation
        assert nupunkt_changes[0].source_text is not None and "brown" in nupunkt_changes[0].source_text
        assert nupunkt_changes[0].test_text is not None and "red" in nupunkt_changes[0].test_text


class TestNupunktProcessorWithoutImport:
    """Test that NupunktProcessor raises proper error when nupunkt not available."""

    @pytest.mark.skipif(NUPUNKT_AVAILABLE, reason="nupunkt is installed")
    def test_import_error_when_nupunkt_not_installed(self) -> None:
        """Test that importing NupunktProcessor fails gracefully when nupunkt not installed."""
        # This test only runs when nupunkt is NOT installed
        # The import at module level should succeed (NUPUNKT_AVAILABLE is defined in processor.py)
        # But using the processor should fail
        from redlines.processor import NupunktProcessor

        source = "Test sentence one. Test sentence two."
        test = "Test sentence one. Modified sentence two."

        processor = NupunktProcessor()

        # Should raise ImportError when trying to process
        with pytest.raises(ImportError, match="nupunkt is required"):
            Redlines(source, test, processor=processor)


def test_nupunkt_availability_flag() -> None:
    """Test that NUPUNKT_AVAILABLE flag is set correctly in processor module."""
    from redlines.processor import NUPUNKT_AVAILABLE as PROCESSOR_FLAG

    # Flag should match our local check
    assert PROCESSOR_FLAG == NUPUNKT_AVAILABLE
