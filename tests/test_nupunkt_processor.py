"""Tests for NupunktProcessor."""
import json

import pytest

from redlines import Redlines
from redlines.processor import NUPUNKT_AVAILABLE, SENTENCE_MARKER, NupunktProcessor


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

    def test_output_markdown_preserves_paragraph_breaks(self) -> None:
        """Test that paragraph boundaries survive rendering instead of being reflowed."""
        source = "One sentence. Two sentence.\n\nThree sentence."
        test = "One sentence. Two sentence.\n\nThree modified."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        output = redlines.output_markdown

        # Only the input's real paragraph break renders as '\n\n'; sentences within
        # a paragraph stay on one line (the pre-fix behavior emitted '\n\n' between
        # every sentence).
        assert output.count("\n\n") == 1
        assert "One sentence. Two sentence." in output

    def test_output_contains_no_sentence_marker(self) -> None:
        """Test that the internal sentence marker never leaks into any output."""
        source = "First one. Second one.\n\nThird one."
        test = "First one. Second edited.\n\nThird one."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)

        assert SENTENCE_MARKER not in redlines.output_markdown
        assert SENTENCE_MARKER not in redlines.output_rich.plain
        assert SENTENCE_MARKER not in redlines.output_json()

    def test_paragraph_boundary_not_merged_across(self) -> None:
        """Test that a change in one paragraph does not pull in another paragraph."""
        source = "Alpha stays here.\n\nBravo gets changed now."
        test = "Alpha stays here.\n\nBravo gets modified now."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert changes[0].source_text is not None and "Alpha" not in changes[0].source_text
        assert changes[0].test_text is not None and "Alpha" not in changes[0].test_text

    def test_sentence_anchoring_within_paragraph(self) -> None:
        """Test that changes stay anchored to their sentence within a paragraph."""
        source = "Alpha starts here. Bravo gets changed. Charlie ends here."
        test = "Alpha starts here. Bravo gets modified. Charlie ends here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        changes = redlines.redlines

        assert len(changes) == 1
        assert changes[0].operation == "replace"
        assert changes[0].source_text is not None
        assert "changed" in changes[0].source_text
        assert "Alpha" not in changes[0].source_text
        assert "Charlie" not in changes[0].source_text

    def test_changes_api_has_no_markers(self) -> None:
        """Test that the public changes API contains no sentence markers."""
        source = "One here. Two here.\n\nThree here."
        test = "One here. Two changed.\n\nThree here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)

        for change in redlines.changes:
            if change.source_text is not None:
                assert SENTENCE_MARKER not in change.source_text
            if change.test_text is not None:
                assert SENTENCE_MARKER not in change.test_text

        # stats() is built on changes, so character counts reflect visible text only
        stats = redlines.stats()
        replace = redlines.get_changes(operation="replace")[0]
        assert replace.source_text is not None and replace.test_text is not None
        assert stats.chars_deleted == len(replace.source_text)
        assert stats.chars_added == len(replace.test_text)

    def test_json_roundtrip_paragraphs(self) -> None:
        """Test that JSON output has no markers and preserves paragraph breaks."""
        source = "One here. Two here.\n\nThree here."
        test = "One here. Two changed.\n\nThree here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        data = json.loads(redlines.output_json())

        for token in data["source_tokens"] + data["test_tokens"]:
            assert SENTENCE_MARKER not in token
        for change in data["changes"]:
            for key in ("text", "source_text", "test_text"):
                if change.get(key) is not None:
                    assert SENTENCE_MARKER not in change[key]

        # Reconstructing the test document from the changes keeps its paragraph break
        reconstructed = "".join(
            change.get("text") or change.get("test_text") or ""
            for change in data["changes"]
            if change["type"] in ("equal", "insert", "replace")
        )
        assert reconstructed.count("\n\n") == 1

    def test_whole_paragraph_insertion(self) -> None:
        """Test that an inserted paragraph renders separated by paragraph breaks."""
        source = "Para one here.\n\nPara two here."
        test = "Para one here.\n\nBrand new paragraph.\n\nPara two here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        output = redlines.output_markdown

        assert "Brand new paragraph." in output
        assert output.count("\n\n") == 2
        assert SENTENCE_MARKER not in output

    def test_whole_paragraph_deletion(self) -> None:
        """Test that a deleted paragraph's struck-through text has no sentence markers."""
        source = "Para one here.\n\nDoomed paragraph text.\n\nPara two here."
        test = "Para one here.\n\nPara two here."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        output = redlines.output_markdown

        assert "Doomed paragraph text." in output
        assert SENTENCE_MARKER not in output

    def test_single_paragraph_no_paragraph_breaks(self) -> None:
        """Test that a single-paragraph input renders without any paragraph breaks."""
        source = "First one. Second one. Third one."
        test = "First one. Second edited. Third one."

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)

        assert "\n\n" not in redlines.output_markdown

    def test_consecutive_and_surrounding_newlines(self) -> None:
        """Test that extra newlines still collapse to one break per boundary."""
        source = "\nFirst para here.\n\n\nSecond para here.\n"
        test = "\nFirst para here.\n\n\nSecond para changed.\n"

        processor = NupunktProcessor()
        redlines = Redlines(source, test, processor=processor)
        output = redlines.output_markdown

        assert output.count("\n\n") == 1

    def test_empty_and_identical_texts(self) -> None:
        """Test that empty and identical inputs produce no changes and no errors."""
        processor = NupunktProcessor()

        empty = Redlines("", "", processor=processor)
        assert len(empty.changes) == 0

        identical = Redlines(
            "Same text here.\n\nSame again.",
            "Same text here.\n\nSame again.",
            processor=processor,
        )
        assert len(identical.changes) == 0


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
        with pytest.raises(ImportError, match="Missing required package: nupunkt"):
            Redlines(source, test, processor=processor)


def test_nupunkt_availability_flag() -> None:
    """Test that NUPUNKT_AVAILABLE flag is set correctly in processor module."""
    from redlines.processor import NUPUNKT_AVAILABLE as PROCESSOR_FLAG

    # Flag should match our local check
    assert PROCESSOR_FLAG == NUPUNKT_AVAILABLE
