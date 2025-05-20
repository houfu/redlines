import pytest
from rich.text import Text

from redlines import Redlines


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
def test_redline_add_md(test_string_1, test_string_2, expected_md):
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
def test_redline_delete_md(test_string_1, test_string_2, expected_md):
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
def test_redline_replace_md(test_string_1, test_string_2, expected_md):
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_rich",
    [
        (
            "The quick brown fox jumps over the dog.",
            "The quick brown fox jumps over the lazy dog.",
            Text.from_markup(
                "The quick brown fox jumps over the [green]lazy [/green]dog."
            ),
        )
    ],
)
def test_redline_add_rich(test_string_1, test_string_2, expected_rich):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_rich == expected_rich


# @pytest.mark.skip("Not sure why [red strike] is not the same as [strike red]")
@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_rich",
    [
        (
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox jumps over the dog.",
            Text.from_markup(
                "The quick brown fox jumps over the [red strike]lazy [/red strike]dog."
            ),
        )
    ],
)
def test_redline_delete_rich(test_string_1, test_string_2, expected_rich):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_rich == expected_rich


@pytest.mark.parametrize(
    "test_string_1, test_string_2, expected_rich",
    [
        (
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog.",
            Text.from_markup(
                "The quick brown fox [red strike]jumps over [/red strike][green]walks past [/green]the lazy dog."
            ),
        )
    ],
)
def test_redline_replace_rich(test_string_1, test_string_2, expected_rich):
    test = Redlines(test_string_1, test_string_2)
    assert test.output_rich == expected_rich


def test_compare():
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = (
        "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    expected_rich = Text.from_markup(
        "The quick brown fox [red strike]jumps over [/red strike][green]walks past [/green]the lazy dog."
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

    test = Redlines(test_string_1)
    assert test.compare(test_string_2, output="rich") == expected_rich


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
    # Test default - "red green"
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog."
    test = Redlines(test_string_1)
    assert test.compare(test_string_2) == expected_md

    # Test None style
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = (
        "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style=None)
    assert test.compare(test_string_2) == expected_md

    # Test "none" style
    test_string_1 = "The quick brown fox jumps over the lazy dog."
    test_string_2 = "The quick brown fox walks past the lazy dog."
    expected_md = (
        "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style="none")
    assert test.compare(test_string_2) == expected_md

    # Test one of the provided markdown styles
    expected_md = (
        "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps "
        "over </span><span style='color:red;font-weight:700;'>walks past </span>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style="red")
    assert test.compare(test_string_2) == expected_md

    # Test default custom css styles
    expected_md = (
        "The quick brown fox <span class='redline-deleted'>jumps "
        "over </span><span class='redline-inserted'>walks past </span>the lazy dog."
    )
    test = Redlines(test_string_1, markdown_style="custom_css")
    assert test.compare(test_string_2) == expected_md

    # Test custom css styles with custom names
    expected_md = (
        "The quick brown fox <span class='deleted'>jumps "
        "over </span><span class='inserted'>walks past </span>the lazy dog."
    )
    test = Redlines(
        test_string_1,
        markdown_style="custom_css",
        ins_class="inserted",
        del_class="deleted",
    )
    assert test.compare(test_string_2) == expected_md

    # Test ghfm (GitHub Flavored Markdown) style
    expected_md = "The quick brown fox ~~jumps over ~~**walks past **the lazy dog."
    test = Redlines(test_string_1, markdown_style="ghfm")
    assert test.compare(test_string_2) == expected_md

    # Test bbcode (BBCode) style
    expected_md = "The quick brown fox [s][color=red]jumps over [/color][/s][b][color=green]walks past [/color][/b]the lazy dog."
    test = Redlines(test_string_1, markdown_style="bbcode")
    assert test.compare(test_string_2) == expected_md

    # Test streamlit style
    expected_md = "The quick brown fox ~~:red[jumps over ]~~ **:green[walks past ]** the lazy dog."
    test = Redlines(test_string_1, markdown_style="streamlit")
    assert test.compare(test_string_2) == expected_md


def test_paragraphs_handling():
    test_string_1 = """
Happy Saturday,

Thank you for reaching out, have a good weekend

Sophia 
"""
    test_string_2 = """Happy Saturday,

Thank you for reaching out. Have a good weekend.

Sophia."""
    expected_md = (
        "Happy Saturday, \n\nThank you for reaching <del>out, have </del><ins>out. Have </ins>a good "
        "<del>weekend </del><ins>weekend. </ins>\n\n<del>Sophia</del><ins>Sophia.</ins>"
    )
    test = Redlines(test_string_1, markdown_style="none")
    assert test.compare(test_string_2) == expected_md


def test_different_number_of_paragraphs():
    test_string_1 = """
Happy Saturday,

Thank you for reaching out, have a good weekend

Best,

Sophia 
"""
    test_string_2 = """Happy Saturday,

Thank you for reaching out. Have a good weekend.

Sophia."""

    expected_md = (
        "Happy Saturday, \n\nThank you for reaching <del>out, have </del><ins>out. Have </ins>a good <del>weekend "
        "</del><ins>weekend. </ins>\n\n<del>Best, ¶ Sophia</del><ins>Sophia.</ins>"
    )
    test = Redlines(test_string_1, test_string_2, markdown_style="none")
    assert test.output_markdown == expected_md


@pytest.mark.parametrize(
    "source, test, expected_md, expected_diffing_disabled",
    [
        # Test 1: Adding a single character (suffix)
        (
            "The dog ran quickly.",
            "The dogs ran quickly.",
            "The dog<ins>s</ins> ran quickly.",
            "The <del>dog</del><ins>dogs</ins> ran quickly.",
        ),
        # Test 2: Adding punctuation (suffix)
        (
            "The quick brown fox jumps over the lazy dog",
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox jumps over the lazy dog<ins>.</ins>",
            "The quick brown fox jumps over the lazy <del>dog</del><ins>dog.</ins>",
        ),
        # Test 3: Changing middle characters
        (
            "The quick brown fox recieved the award.",
            "The quick brown fox received the award.",
            "The quick brown fox rec<del>ie</del><ins>ei</ins>ved the award.",
            "The quick brown fox <del>recieved</del><ins>received</ins> the award.",
        ),
        # Test 4: Prefix changes
        (
            "The dog is unhappy.",
            "The dog is happy.",
            "The dog is <del>un</del>happy.",
            "The dog is <del>unhappy</del><ins>happy</ins>.",
        ),
        # Test 5: Suffix and prefix preserved, middle changed
        (
            "The implementation is fast.",
            "The implementation is slow.",
            "The implementation is <del>f</del><ins>sl</ins>a<del>st</del><ins>ow</ins>.",
            "The implementation is <del>fast</del><ins>slow</ins>.",
        ),
        # Test 6: Multiple word changes that should be kept separate
        (
            "The cats plays outside. They are happy.",
            "The cat plays outside. It is happy.",
            "The <del>cats</del><ins>cat</ins> plays outside. <del>They</del><ins>It</ins> <del>are</del><ins>is</ins> happy.",
            "The <del>cats</del><ins>cat</ins> plays outside. <del>They</del><ins>It</ins> <del>are</del><ins>is</ins> happy.",
        ),
        # Test 7: Capitalization changes
        (
            "The quick brown fox.",
            "The Quick brown fox.",
            "The <del>q</del><ins>Q</ins>uick brown fox.",
            "The <del>quick</del><ins>Quick</ins> brown fox.",
        ),
    ],
)
def test_character_level_diffing(source, test, expected_md, expected_diffing_disabled):
    """Test character-level diffing with various types of changes."""
    # Test with character-level diffing enabled (default)
    redlines_enabled = Redlines(source, test, markdown_style="none")
    assert redlines_enabled.output_markdown == expected_md

    # Test with character-level diffing disabled
    redlines_disabled = Redlines(
        source, test, character_level_diffing=False, markdown_style="none"
    )
    assert redlines_disabled.output_markdown == expected_diffing_disabled


def test_special_punctuation_handling():
    """Test special handling of trailing punctuation."""
    source = "Thank you"
    test = "Thank you."

    # With character diffing enabled
    redlines = Redlines(source, test, markdown_style="none")
    assert redlines.output_markdown == "Thank you<ins>.</ins>"

    # With character diffing disabled
    redlines_disabled = Redlines(
        source, test, character_level_diffing=False, markdown_style="none"
    )
    assert redlines_disabled.output_markdown == "Thank <del>you</del><ins>you.</ins>"

    # Test multiple punctuation characters
    source = "Wow"
    test = "Wow!!!"
    redlines = Redlines(source, test, markdown_style="none")
    assert redlines.output_markdown == "Wow<ins>!!!</ins>"
