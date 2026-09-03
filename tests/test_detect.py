"""Tests for format detection: extension first, content second, never a guess (#107)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from pathlib import Path

import pytest

from redlines.readers import detect
from redlines.readers.detect import (
    FormatDetection,
    detect_format,
    known_extensions,
    register_extension,
)

MARKDOWN = """\
# Master Services Agreement

## 1. Interpretation

- "Services" means the services described in Schedule 1.
"""

PLAIN = """\
MASTER SERVICES AGREEMENT

1. Interpretation

In this agreement, "Services" means the services described in Schedule 1.
"""


@pytest.fixture
def clean_extensions() -> Iterator[None]:
    """Restore the extension map after a test claims a new extension.

    The map is a module-level registry with no public way to give an
    extension back, which is deliberate -- a reader claims its extensions for
    the life of the process. Tests are the exception.
    """
    before = dict(detect._EXTENSIONS)
    yield
    detect._EXTENSIONS.clear()
    detect._EXTENSIONS.update(before)


# --- the extension decides first -------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("agreement.txt", "text"),
        ("agreement.md", "markdown"),
        ("agreement.markdown", "markdown"),
        ("AGREEMENT.TXT", "text"),
        ("AGREEMENT.MD", "markdown"),
    ],
)
def test_a_claimed_extension_names_the_format(name: str, expected: str) -> None:
    detected = detect_format(path=name)
    assert detected.format == expected
    assert Path(name).suffix.lower() in detected.reason


def test_a_path_object_works_as_well_as_a_string() -> None:
    assert detect_format(path=Path("/tmp/deal/agreement.md")).format == "markdown"


def test_the_extension_wins_over_the_content() -> None:
    # A .txt file full of markdown is still text: that is what its name says.
    assert detect_format(path="agreement.txt", text=MARKDOWN).format == "text"


@pytest.mark.parametrize(
    ("name", "named"),
    [
        ("agreement.docx", "DOCX"),
        ("agreement.pdf", "PDF"),
        ("agreement.html", "HTML"),
        ("agreement.htm", "HTML"),
    ],
)
def test_a_format_that_is_coming_is_reported_as_coming(name: str, named: str) -> None:
    detected = detect_format(path=name)
    assert detected.format is None
    assert named in detected.reason
    assert "coming in 1.1" in detected.reason
    assert Path(name).suffix in detected.reason


def test_an_unreadable_extension_is_not_overridden_by_its_content() -> None:
    # Markdown-looking text inside a .docx name is still not a guess worth
    # making; the extension is the stronger signal and it says DOCX.
    detected = detect_format(path="agreement.docx", text=MARKDOWN)
    assert detected.format is None
    assert "coming in 1.1" in detected.reason


# --- content sniffing, only when the extension does not settle it ----------


def test_no_extension_with_markdown_content_is_markdown() -> None:
    detected = detect_format(path="agreement", text=MARKDOWN)
    assert detected.format == "markdown"
    assert "ATX heading" in detected.reason


def test_no_extension_with_plain_content_is_text() -> None:
    detected = detect_format(path="agreement", text=PLAIN)
    assert detected.format == "text"
    assert "no markdown syntax" in detected.reason


def test_content_alone_is_enough() -> None:
    assert detect_format(text=MARKDOWN).format == "markdown"
    assert detect_format(text=PLAIN).format == "text"


@pytest.mark.parametrize(
    ("content", "signal"),
    [
        ("# A heading\n\nAnd a paragraph.", "ATX heading"),
        ("Some code:\n\n```python\nprint()\n```\n", "fenced code block"),
        ("A list:\n\n- one\n- two\n", "bullet list"),
        ("> Quoted from the deed.\n", "block quote"),
        ("| Service | Fee |\n| --- | --- |\n", "pipe table row"),
        ("See the [schedule](schedule.md) for detail.", "inline link"),
    ],
)
def test_each_markdown_signal_is_named_in_the_reason(content: str, signal: str) -> None:
    detected = detect_format(text=content)
    assert detected.format == "markdown"
    assert signal in detected.reason


def test_an_unclaimed_extension_falls_through_to_the_content() -> None:
    detected = detect_format(path="agreement.rst", text=PLAIN)
    assert detected.format == "text"
    assert ".rst" in detected.reason


def test_an_unclaimed_extension_with_no_content_is_reported() -> None:
    detected = detect_format(path="agreement.rst")
    assert detected.format is None
    assert ".rst" in detected.reason
    assert "no content" in detected.reason


def test_a_name_with_no_extension_and_no_content_is_reported() -> None:
    detected = detect_format(path="agreement")
    assert detected.format is None
    assert "no extension" in detected.reason


def test_utf_8_bytes_are_sniffed_like_text() -> None:
    assert detect_format(text=MARKDOWN.encode("utf-8")).format == "markdown"
    assert detect_format(text="Fee: €1,000.".encode("utf-8")).format == "text"


# --- binary content is reported, never guessed at --------------------------


@pytest.mark.parametrize(
    ("content", "named"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "PDF"),
        (b"PK\x03\x04\x14\x00\x06\x00", "ZIP archive"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "Office"),
    ],
)
def test_a_recognisable_binary_signature_is_named(content: bytes, named: str) -> None:
    detected = detect_format(text=content)
    assert detected.format is None
    assert named in detected.reason


def test_a_recognisable_binary_signature_is_named_even_as_decoded_text() -> None:
    # A caller may have already decoded the bytes before calling in; a PDF's
    # magic bytes are plain ASCII, so a str still carrying them is caught the
    # same way raw bytes would be.
    detected = detect_format(text="%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    assert detected.format is None
    assert "PDF" in detected.reason


@pytest.mark.parametrize(
    ("content", "named"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "PDF"),
        (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "Office"),
    ],
)
def test_a_recognisable_binary_signature_names_1_0_and_1_1(
    content: bytes, named: str
) -> None:
    detected = detect_format(text=content)
    assert detected.format is None
    assert named in detected.reason
    assert "coming in 1.1" in detected.reason


def test_undecodable_bytes_are_reported_as_binary() -> None:
    detected = detect_format(text=b"\xff\xfe\x00\x01\x02\x03")
    assert detected.format is None
    assert "binary" in detected.reason


def test_a_nul_byte_in_text_is_reported_as_binary() -> None:
    detected = detect_format(text="A document\x00with a NUL")
    assert detected.format is None
    assert "NUL" in detected.reason


def test_empty_content_is_reported_rather_than_assumed_to_be_text() -> None:
    detected = detect_format(text="   \n\n")
    assert detected.format is None
    assert "empty" in detected.reason


def test_an_empty_file_with_a_claimed_extension_is_still_its_extension() -> None:
    assert detect_format(path="agreement.txt", text="").format == "text"


# --- the shape of the answer -----------------------------------------------


def test_every_answer_carries_a_reason() -> None:
    for detected in (
        detect_format(path="a.txt"),
        detect_format(path="a.pdf"),
        detect_format(text=PLAIN),
        detect_format(text=b"\x00\x01"),
    ):
        assert detected.reason


def test_the_result_is_frozen() -> None:
    detected = detect_format(path="a.md")
    assert isinstance(detected, FormatDetection)
    with pytest.raises(dataclasses.FrozenInstanceError):
        detected.format = "text"  # type: ignore[misc]


def test_detecting_from_nothing_at_all_is_a_caller_error() -> None:
    with pytest.raises(ValueError, match="needs a path, some text, or both"):
        detect_format()


# --- the extension map is a registry ---------------------------------------


def test_the_extension_map_starts_with_the_1_0_formats() -> None:
    assert known_extensions() == {
        ".markdown": "markdown",
        ".md": "markdown",
        ".txt": "text",
    }


def test_a_later_reader_can_claim_its_own_extension(clean_extensions: None) -> None:
    register_extension(".CLF", "clause-file")
    assert known_extensions()[".clf"] == "clause-file"
    assert detect_format(path="deal.clf").format == "clause-file"


def test_known_extensions_is_a_sorted_copy() -> None:
    listing = known_extensions()
    assert list(listing) == sorted(listing)
    listing[".invented"] = "nothing"
    assert ".invented" not in known_extensions()


def test_an_extension_needs_its_dot() -> None:
    with pytest.raises(ValueError, match="starts with a dot"):
        register_extension("clf", "clause-file")


def test_claiming_an_extension_another_format_holds_is_refused(
    clean_extensions: None,
) -> None:
    """The mirror of `register_reader`'s refusal: two formats quietly fighting
    over one suffix is a bug that only shows up in the output."""
    register_extension(".clf", "clause-file")

    with pytest.raises(ValueError, match="already claimed by 'clause-file'"):
        register_extension(".CLF", "other-format")

    assert detect_format(path="deal.clf").format == "clause-file"


def test_a_refused_claim_leaves_the_1_0_extensions_alone(
    clean_extensions: None,
) -> None:
    with pytest.raises(ValueError, match="already claimed by 'markdown'"):
        register_extension(".md", "not-markdown")

    assert detect_format(path="agreement.md").format == "markdown"


def test_replace_takes_an_extension_over(clean_extensions: None) -> None:
    register_extension(".clf", "clause-file")

    register_extension(".clf", "other-format", replace=True)

    assert detect_format(path="deal.clf").format == "other-format"


def test_reclaiming_an_extension_for_the_same_format_is_a_no_op(
    clean_extensions: None,
) -> None:
    """Importing a reader module twice must not raise."""
    register_extension(".clf", "clause-file")
    register_extension(".clf", "clause-file")

    assert known_extensions()[".clf"] == "clause-file"
