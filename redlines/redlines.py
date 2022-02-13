import re

tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")


def tokenize_text(text: str) -> list[str]:
    return re.findall(tokenizer, text)


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
        self._seq1 = tokenize_text(value)

    @property
    def test(self):
        """The text to be compared with the source."""
        return self._test

    @test.setter
    def test(self, value):
        self._test = value
        self._seq2 = tokenize_text(value)

    def __init__(self, source: str, test: str | None = None):
        """
        Redline is a class used to compare text, and producing human-readable differences or deltas
        which look like track changes in Microsoft Word.

        :param source: The source text to be used as a basis for comparison.
        :param test: Optional test text to compare with the source.
        """
        self.source = source
        if test:
            self.test = test
            self.compare()

    @property
    def opcodes(self) -> list[tuple[str, int, int, int, int]]:
        """
        Return list of 5-tuples describing how to turn `source` into `test`.
        Similar to `SequenceMatcher.get_opcodes`
        """
        if self._seq2 is None:
            raise ValueError('No test string was provided when the function was called, or during initialisation.')

        from difflib import SequenceMatcher
        matcher = SequenceMatcher(None, self._seq1, self._seq2)
        return matcher.get_opcodes()

    @property
    def output_markdown(self) -> str:
        """Returns the delta in markdown format."""
        result = []
        for tag, i1, i2, j1, j2 in self.opcodes:
            match tag:
                case 'equal':
                    result.append("".join(self._seq1[i1:i2]))
                case 'insert':
                    result.append(f"<ins>{''.join(self._seq2[j1:j2])}</ins>")
                case 'delete':
                    result.append(f"<del>{''.join(self._seq1[i1:i2])}</del>")
                case 'replace':
                    result.append(f"<del>{''.join(self._seq1[i1:i2])}</del><ins>{''.join(self._seq2[j1:j2])}</ins>")

        return "".join(result)

    def compare(self, test: str | None = None, output: str = "markdown"):
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
            raise ValueError('No test string was provided when the function was called, or during initialisation.')

        match output:
            case 'markdown': return self.output_markdown
