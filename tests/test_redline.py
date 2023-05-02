import pytest

from redlines import Redlines
from redlines.redlines import split_paragraphs_and_tokenize_text


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_md",
    [
        (
            "The quick brown fox jumps over the dog.",
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox jumps over the <ins>lazy </ins>dog.",
        )
    ],
)
def test_redline_add(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_md",
    [
        (
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox jumps over the dog.",
            "The quick brown fox jumps over the <del>lazy </del>dog.",
        )
    ],
)
def test_redline_delete(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_md",
    [
        (
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog.",
            "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.",
        )
    ],
)
def test_redline_replace(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


def test_compare():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = (
        "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style="none")
    assert test.compare(test_string_2) == expected_md

    # When compare is called twice on the same test string, the first result is given
    assert test.compare(test_string_2) == expected_md

    assert (
        test.compare("The quick brown fox jumps over the dog.")
        == "The quick brown fox jumps over the <del>lazy </del>dog."
    )

    # Not giving the Redline object anything to test with throws an error.
    test = Redlines(test_string_1)
    with pytest.raises(ValueError):
        test.compare()


def test_opcodes_error():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test = Redlines(test_string_1)
    with pytest.raises(ValueError):
        print(test.opcodes)


def test_source():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test = Redlines(test_string_1, markdown_style="none")
    assert test.source == test_string_1


def test_markdown_style():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = (
        "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style="none")
    assert test.compare(test_string_2) == expected_md

    expected_md = (
        'The quick brown fox <span style="color:red;font-weight:700;text-decoration:line-through;">jumps '
        'over </span><span style="color:red;font-weight:700;">walks past </span>the lazy dog.'
    )
    test = Redlines(test_string_1, markdown_style="red")
    assert test.compare(test_string_2) == expected_md


def test_newline_handling():
    test_string_1 = """
Happy Saturday,

Thank you for reaching out, have a good weekend

Sophia 
"""
    test_string_2 = """Happy Saturday,

Thank you for reaching out. Have a good weekend.

Sophia."""
    expected_md = 'Happy Saturday,\n\nThank you for reaching <del>out, have </del><ins>out. Have </ins>a good <del>weekend</del><ins>weekend.</ins>\n\n<del>Sophia </del><ins>Sophia.</ins>'
    test = Redlines(test_string_1, markdown_style="none")
    assert test.compare(test_string_2) == expected_md

    expected_md = 'Happy Saturday,\n\nThank you for reaching <span style="color:red;font-weight:700;text-decoration:line-through;">out, have </span><span style="color:red;font-weight:700;">out. Have </span>a good <span style="color:red;font-weight:700;text-decoration:line-through;">weekend</span><span style="color:red;font-weight:700;">weekend.</span>\n\n<span style="color:red;font-weight:700;text-decoration:line-through;">Sophia </span><span style="color:red;font-weight:700;">Sophia.</span>'
    test = Redlines(test_string_1, markdown_style="red")
    assert test.compare(test_string_2) == expected_md

@pytest.mark.parametrize(
    "test_string, expected_list",
    [
        (
            "Hello World\nThis is a test.\n This is another test.",
            [['Hello ', 'World'], ['This ', 'is ', 'a ', 'test.'], ['This ', 'is ', 'another ', 'test.']],
        ),

        (
            "Hello World\n\r\nThis is a test.\n\n This is another test.",
            [['Hello ', 'World'], ['This ', 'is ', 'a ', 'test.'], ['This ', 'is ', 'another ', 'test.']],
        ),

                (
            "\n Hello World\n\r\nThis is a test.\n    \r\t\n This is another test.\n",
            [['Hello ', 'World'], ['This ', 'is ', 'a ', 'test.'], ['This ', 'is ', 'another ', 'test.']],
        ),

    ],
)
def test_split_paragraphs_and_tokenize_text(test_string,expected_list):
    assert split_paragraphs_and_tokenize_text(test_string) == expected_list
