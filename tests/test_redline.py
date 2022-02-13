import pytest

from redlines import Redlines


@pytest.mark.parametrize("test_string_1, test_string_2, expected_md", [
    ("The quick brown fox jumps over the dog.",
     "The quick brown fox jumps over the lazy dog.",
     "The quick brown fox jumps over the <ins>lazy </ins>dog.")
])
def test_redline_add(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_markdown == expected_md


@pytest.mark.parametrize("test_string_1, test_string_2, expected_md", [
    ("The quick brown fox jumps over the lazy dog.",
     "The quick brown fox jumps over the dog.",
     "The quick brown fox jumps over the <del>lazy </del>dog.")
])
def test_redline_delete(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_markdown == expected_md


@pytest.mark.parametrize("test_string_1, test_string_2, expected_md", [
    ("The quick brown fox jumps over the lazy dog.",
     "The quick brown fox walks past the lazy dog.",
     "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.")
])
def test_redline_replace(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_markdown == expected_md


def test_compare():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    test = Redlines(test_string_1)
    assert test.compare(test_string_2) == expected_md

    # When compare is called twice on the same test string, the first result is given
    assert test.compare(test_string_2) == expected_md

    assert test.compare(
        "The quick brown fox jumps over the dog.") == "The quick brown fox jumps over the <del>lazy </del>dog."

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
    test = Redlines(test_string_1)
    assert test.source == test_string_1
