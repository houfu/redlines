from __future__ import annotations

import re

from rich.text import Text

# This regular expression matches a group of characters that can include any character except for parentheses
# and whitespace characters (which include spaces, tabs, and line breaks) or any character
# that is a parenthesis or punctuation mark (.?!-).
# The group can also include any whitespace characters that follow these characters.
# Breaking it down further:

#    ( and ) indicate a capturing group
#    (?: ) is a non-capturing group, meaning it matches the pattern but doesn't capture the matched text
#    [^()\s]+ matches one or more characters that are not parentheses or whitespace characters
#    | indicates an alternative pattern
#    [().?!-] matches any character that is a parenthesis or punctuation mark (.?!-)
#    \s* matches zero or more whitespace characters (spaces, tabs, or line breaks) that follow the previous pattern.
tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")

# This pattern matches one or more newline characters `\n`, and any spaces between them.
# It is used to split the text into paragraphs.
# (?:\n *) is a non-capturing group that must start with a \n   and be followed by zero or more spaces.
# ((?:\n *)+) is the previous non-capturing group repeated one or more times.
paragraph_pattern = re.compile(r"((?:\n *)+)")

space_pattern = re.compile(r"(\s+)")


def tokenize_text(text: str) -> list[str]:
    return re.findall(tokenizer, text)


def split_paragraphs(text: str) -> list[str]:
    """
    Splits a string into a list of paragraphs. One or more `\n` splits the paragraphs.
    For example, if the text is "Hello\nWorld\nThis is a test", the result will be:
    ['Hello', 'World', 'This is a test']

    :param text: The text to split.
    :return: a list of paragraphs.
    """

    split_text = re.split(paragraph_pattern, text)
    result = []
    for s in split_text:
        if s and not re.fullmatch(space_pattern, s):
            result.append(s.strip())

    return result


def concatenate_paragraphs_and_add_chr_182(text: str) -> str:
    """
    Split paragraphs and concatenate them. Then add a character '¶' between paragraphs.
    For example, if the text is "Hello\nWorld\nThis is a test", the result will be:
    "Hello¶World¶This is a test"

    :param text: The text to split.
    :return: a list of paragraphs.
    """
    paragraphs = split_paragraphs(text)

    result = []
    for p in paragraphs:
        result.append(p)
        result.append(" ¶ ")
        # Add a string ' ¶ ' between paragraphs.
    if len(paragraphs) > 0:
        result.pop()

    return "".join(result)


class Redlines:
    _source: str = None
    _test: str = None
    _seq1: list[str] = None
    _seq2: list[str] = None

    @property
    def source(self):
        """
        The source text to be used as a basis for comparison.
        :return:
        """
        return self._source

    @source.setter
    def source(self, value):
        self._source = value
        self._seq1 = tokenize_text(concatenate_paragraphs_and_add_chr_182(value))

    @property
    def test(self):
        """The text to be compared with the source."""
        return self._test

    @test.setter
    def test(self, value):
        self._test = value
        self._seq2 = tokenize_text(concatenate_paragraphs_and_add_chr_182(value))

    def __init__(self, source: str, test: str | None = None, **options):
        """
        Redline is a class used to compare text, and producing human-readable differences or deltas
        which look like track changes in Microsoft Word.

        :param source: The source text to be used as a basis for comparison.
        :param test: Optional test text to compare with the source.
        """
        self.source = source
        self.options = options
        if test:
            self.test = test
            # self.compare()

    @property
    def opcodes(self) -> list[tuple[str, int, int, int, int]]:
        """
        Return list of 5-tuples describing how to turn `source` into `test`.
        Similar to `SequenceMatcher.get_opcodes`
        """
        if self._seq2 is None:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )

        from difflib import SequenceMatcher

        matcher = SequenceMatcher(None, self._seq1, self._seq2)
        return matcher.get_opcodes()

    @property
    def output_markdown(self) -> str:
        """Returns the delta in Markdown format."""
        result = []

        # default_style = "red_green"

        md_styles = {
            "ins": (
                f"<span style='color:green;font-weight:700;'>",
                "</span>",
            ),
            "del": (
                f"<span style='color:red;font-weight:700;text-decoration:line-through;'>",
                "</span>",
            ),
        }

        if "markdown_style" in self.options:
            style = self.options["markdown_style"]

            if style == "none" or style is None:
                md_styles = {"ins": ("<ins>", "</ins>"), "del": ("<del>", "</del>")}
            elif style == "red":
                md_styles = {
                    "ins": (
                        f"<span style='color:red;font-weight:700;'>",
                        "</span>",
                    ),
                    "del": (
                        f"<span style='color:red;font-weight:700;text-decoration:line-through;'>",
                        "</span>",
                    ),
                }
            elif style == "custom_css":
                ins_class = (
                    self.options["ins_class"]
                    if "ins_class" in self.options
                    else "redline-inserted"
                )
                del_class = (
                    self.options["del_class"]
                    if "del_class" in self.options
                    else "redline-deleted"
                )

                elem_attributes = {
                    "ins": f"class='{ins_class}'",
                    "del": f"class='{del_class}'",
                }

                md_styles = {
                    "ins": (
                        f"<span {elem_attributes['ins']}>",
                        "</span>",
                    ),
                    "del": (
                        f"<span {elem_attributes['del']}>",
                        "</span>",
                    ),
                }
            elif style == "ghfm":
                md_styles = {"ins": ("**", "**"), "del": ("~~", "~~")}

        for tag, i1, i2, j1, j2 in self.opcodes:
            if tag == "equal":
                temp_str = "".join(self._seq1[i1:i2])
                temp_str = re.sub("¶ ", "\n\n", temp_str)
                # here we use '¶ ' instead of ' ¶ ', because the leading space will be included in the previous token,
                # according to tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")
                result.append(temp_str)
            elif tag == "insert":
                temp_str = "".join(self._seq2[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    result.append(f"{md_styles['ins'][0]}{split}{md_styles['ins'][1]}")
                    result.append("\n\n")
                if len(splits) > 0:
                    result.pop()
            elif tag == "delete":
                result.append(
                    f"{md_styles['del'][0]}{''.join(self._seq1[i1:i2])}{md_styles['del'][1]}"
                )
                # for 'delete', we make no change, because otherwise there will be two times '\n\n' than the original
                # text.
            elif tag == "replace":
                result.append(
                    f"{md_styles['del'][0]}{''.join(self._seq1[i1:i2])}{md_styles['del'][1]}"
                )
                temp_str = "".join(self._seq2[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    result.append(f"{md_styles['ins'][0]}{split}{md_styles['ins'][1]}")
                    result.append("\n\n")
                if len(splits) > 0:
                    result.pop()

        return "".join(result)

    @property
    def output_rich(self) -> Text:
        """Returns the delta in text with colors/style for the console."""
        console_text = Text()

        for tag, i1, i2, j1, j2 in self.opcodes:
            if tag == "equal":
                temp_str = "".join(self._seq1[i1:i2])
                temp_str = re.sub("¶ ", "\n\n", temp_str)
                console_text.append(temp_str)
            elif tag == "insert":
                temp_str = "".join(self._seq2[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    console_text.append(split, "green")
            elif tag == "delete":
                console_text.append("".join(self._seq1[i1:i2]), "strike red")
            elif tag == "replace":
                console_text.append("".join(self._seq1[i1:i2]), "strike red")
                temp_str = "".join(self._seq2[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    console_text.append(split, "green")

        return console_text

    def compare(self, test: str | None = None, output: str = "markdown", **options):
        """
        Compare `test` with `source`, and produce a delta in a format specified by `output`.

        :param test: Optional test string to compare. If None, uses the test string provided during initialisation.
        :param output: The format which the delta should be produced. Currently, only "markdown" is supported
        :return: The delta in the format specified by `output`.
        """
        if test:
            if self.test and test == self.test:
                return self.output_markdown
            else:
                self.test = test
        elif self.test is None:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )

        if options:
            self.options = options

        if output == "markdown":
            return self.output_markdown
