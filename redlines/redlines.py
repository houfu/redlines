from __future__ import annotations

import re
from difflib import SequenceMatcher

tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")

# This pattern matches one or more newline characters `\n`, and any spaces between them.
# It is used to split the text into paragraphs.
# (?:\n *) is a non-capturing group that must start with a \n or \r and be followed by zero or more spaces.
# ((?:\n *)+) is the previous non-capturing group repeated one or more times.
paragraph_pattern = re.compile(r"((?:\n *)+)")

space_pattern = re.compile(r"(\s+)")


def tokenize_text(text: str) -> list[str]:
    return re.findall(tokenizer, text)


def split_paragraphs(text: str) -> list[str]:
    """
    Splits a string into a list of paragraphs.
    For example, if the text is "Hello\nWorld\nThis is a test", the result will be:
    ['Hello', 'World', 'This is a test']

    :param text: The text to split.
    :return: a list of paragraphs.
    """

    splitted_text=re.split(paragraph_pattern, text)
    result = []
    for s in splitted_text:
        if s and not re.fullmatch(space_pattern, s):
            result.append(s)
    
    return result
    
def split_paragraphs_and_tokenize_text(text: str) -> list[list[str]]:
    """
    Splits a string into a list of paragraphs. Then, each paragraph is tokenized.
    For example, if the text is "Hello World\nThis is a test. \n This is another test.", the result will be:
    [['Hello ', 'World'], ['This ', 'is ', 'a ', 'test.'], ['This ', 'is ', 'another ', 'test.']]

    :param text: The text to split.
    :return: a list of lists of tokens.
    """
    paragraphs = split_paragraphs(text)
    return [tokenize_text(p) for p in paragraphs]

class Redlines:
    _source: str = None
    _test: str = None
    _seqlist1: list[list[str]] = [] # This is a list of list. Each sub-list is a sequence of tokens in a paragraph in the source.
    _seqlist2: list[list[str]] = [] # This is a list of list. Each sub-list is a sequence of tokens in a paragraph in the test.

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
        self._seqlist1 = split_paragraphs_and_tokenize_text(value)

    @property
    def test(self):
        """The text to be compared with the source."""
        return self._test

    @test.setter
    def test(self, value):
        self._test = value
        self._seqlist2 = split_paragraphs_and_tokenize_text(value)

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

    @property
    def opcodes(self) -> list[list[tuple[str, int, int, int, int]]]:
        """
        Return a list of list. 
        Each sub-list represent a paragraph, and is a list of 5-tuples describing how to turn a `source` paragraph into a `test` paragraph
        Each 5-tuple represents a single change in the source and test text.
        The 5-tuple has the following format:
        (tag, i1, i2, j1, j2)
        where:
        - tag is a string describing the type of change, and could be 'equal', 'replace', 'insert', 'delete'
        - i1, i2, j1, j2 are integers, where i1 and j1 are the starting and ending indices of the change
        """

        if not self._seqlist2:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )
        
        # If the number of pararagraphs in the source is greater than the number of paragraphs in the test,
        # we add empty lists to the end of the list of lists, and vice versa. 
        
        len_seqlist1 = len(self._seqlist1)
        len_seqlist2 = len(self._seqlist2)
        if len_seqlist1>len_seqlist2:
            for i in range(len_seqlist1-len_seqlist2):
                self._seqlist2.append([])
        elif len_seqlist2>len_seqlist1:
            for i in range(len_seqlist2-len_seqlist1):
                self._seqlist1.append([])
        assert len(self._seqlist1) == len(self._seqlist2)

        result=[]
        for seq1, seq2 in zip(self._seqlist1, self._seqlist2):
            matcher = SequenceMatcher(None, seq1, seq2)
            result.append(matcher.get_opcodes())

        return result

    @property
    def output_markdown(self) -> str:
        """Returns the delta in markdown format."""
        result = []
        style = "red"

        if self.options.get("markdown_style"):
            style = self.options["markdown_style"]

        if style == "none":
            md_styles = {"ins": ("ins", "ins"), "del": ("del", "del")}
        elif "red":
            md_styles = {
                "ins": ('span style="color:red;font-weight:700;"', "span"),
                "del": (
                    'span style="color:red;font-weight:700;text-decoration:line-through;"',
                    "span",
                ),
            }
        for opcode, seq1, seq2 in zip(self.opcodes, self._seqlist1, self._seqlist2):
            for tag, i1, i2, j1, j2 in opcode:
                if tag == 'equal':
                    result.append("".join(seq1[i1:i2]))
                elif tag == 'insert':
                    result.append(f"<{md_styles['ins'][0]}>{''.join(seq2[j1:j2])}</{md_styles['ins'][1]}>")
                elif tag == 'delete':
                    result.append(f"<{md_styles['del'][0]}>{''.join(seq1[i1:i2])}</{md_styles['del'][1]}>")
                elif tag == 'replace':
                    result.append(
                        f"<{md_styles['del'][0]}>{''.join(seq1[i1:i2])}</{md_styles['del'][1]}>"
                        f"<{md_styles['ins'][0]}>{''.join(seq2[j1:j2])}</{md_styles['ins'][1]}>")

            result.append("\n\n")
        # pop the last '\n\n'
        result.pop()

        return "".join(result)

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
