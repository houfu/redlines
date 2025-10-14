from __future__ import annotations

import re
from rich.text import Text
from redlines.document import Document
from redlines.processor import WholeDocumentProcessor, Redline

__all__ = ["Redlines"]


class Redlines:
    """
    Compare two pieces of text and produce human-readable differences (redlines),
    similar to Microsoft Word’s "Track Changes" feature.
    """

    _source: str | None = None
    _test: str | None = None
    _redlines: list[Redline] | None = None
    _seq1: list[str] | None = None
    _seq2: list[str] | None = None

    def __init__(
        self, source: str | Document, test: str | Document | None = None, **options
    ):
        """
        Initialize a Redlines object with a source and optional test text.

        :param source: The source text to compare from.
        :param test: The test text to compare to.
        :param options: Optional display or formatting options.
        """
        self.processor = WholeDocumentProcessor()
        self.source = source.text if isinstance(source, Document) else source
        self.options = options
        self._redlines = None

        if test:
            self.test = test.text if isinstance(test, Document) else test

    # --------------------------------------------------
    # Source / Test Properties
    # --------------------------------------------------

    @property
    def source(self) -> str:
        """The source text used as the comparison baseline."""
        return self._source

    @source.setter
    def source(self, value):
        self._source = value.text if isinstance(value, Document) else value
        if self._test is not None:
            self._redlines = self.processor.process(self._source, self._test)

    @property
    def test(self) -> str:
        """The text to be compared against the source."""
        return self._test

    @test.setter
    def test(self, value):
        self._test = value.text if isinstance(value, Document) else value
        if self._source is not None and self._test is not None:
            self._redlines = self.processor.process(self._source, self._test)

    @property
    def redlines(self) -> list[Redline]:
        """List of Redline objects describing differences between source and test."""
        if self._redlines is None:
    raise ValueError(
        "Comparison failed: No test string was provided when the function was called or during initialization.\n"
        "Why it went wrong: The Redlines object has no test text to compare against.\n"
        "How to fix: Provide both a source and a test string when creating or comparing.\n\n"
        "Example:\n"
        "    redlines = Redlines('source text', 'test text')\n"
        "    result = redlines.output_markdown"
    )

        return self._redlines

    # --------------------------------------------------
    # Opcodes
    # --------------------------------------------------

    @property
    def opcodes(self) -> list[tuple[str, int, int, int, int]]:
        """List of 5-tuples describing how to turn `source` into `test`."""
        return [redline.opcodes for redline in self.redlines]

    # --------------------------------------------------
    # Markdown Output
    # --------------------------------------------------

    @property
    def output_markdown(self) -> str:
        """Return the differences in Markdown (HTML-styled) format."""
        result = []

        md_styles = {
            "ins": (
                "<span style='color:green;font-weight:700;'>",
                "</span>",
            ),
            "del": (
                "<span style='color:red;font-weight:700;text-decoration:line-through;'>",
                "</span>",
            ),
        }

        # Apply optional markdown style
        style = self.options.get("markdown_style") if hasattr(self, "options") else None

        if style == "none" or style is None:
            md_styles = {"ins": ("<ins>", "</ins>"), "del": ("<del>", "</del>")}
        elif style == "red":
            md_styles = {
                "ins": (
                    "<span style='color:red;font-weight:700;'>",
                    "</span>",
                ),
                "del": (
                    "<span style='color:red;font-weight:700;text-decoration:line-through;'>",
                    "</span>",
                ),
            }
        elif style == "custom_css":
            ins_class = self.options.get("ins_class", "redline-inserted")
            del_class = self.options.get("del_class", "redline-deleted")
            md_styles = {
                "ins": (f"<span class='{ins_class}'>", "</span>"),
                "del": (f"<span class='{del_class}'>", "</span>"),
            }
        elif style == "ghfm":
            md_styles = {"ins": ("**", "**"), "del": ("~~", "~~")}
        elif style == "bbcode":
            md_styles = {
                "ins": ("[b][color=green]", "[/color][/b]"),
                "del": ("[s][color=red]", "[/color][/s]"),
            }
        elif style == "streamlit":
            md_styles = {"ins": ("**:green[", "]** "), "del": ("~~:red[", "]~~ ")}

        # Build formatted markdown
        for redline in self.redlines:
            tag, i1, i2, j1, j2 = redline.opcodes
            source_tokens = redline.source_chunk.text
            test_tokens = redline.test_chunk.text

            if tag == "equal":
                temp = "".join(source_tokens[i1:i2])
                result.append(re.sub("¶ ", "\n\n", temp))
            elif tag == "insert":
                temp = "".join(test_tokens[j1:j2])
                for part in re.split("¶ ", temp):
                    result.append(f"{md_styles['ins'][0]}{part}{md_styles['ins'][1]}\n\n")
                if len(result) > 0:
                    result.pop()  # remove trailing newlines
            elif tag == "delete":
                result.append(
                    f"{md_styles['del'][0]}{''.join(source_tokens[i1:i2])}{md_styles['del'][1]}"
                )
            elif tag == "replace":
                result.append(
                    f"{md_styles['del'][0]}{''.join(source_tokens[i1:i2])}{md_styles['del'][1]}"
                )
                temp = "".join(test_tokens[j1:j2])
                for part in re.split("¶ ", temp):
                    result.append(f"{md_styles['ins'][0]}{part}{md_styles['ins'][1]}\n\n")
                if len(result) > 0:
                    result.pop()

        return "".join(result)

    # --------------------------------------------------
    # Console Output
    # --------------------------------------------------

    @property
    def output_rich(self) -> Text:
        """Return the differences as colored text for console output."""
        console_text = Text()

        for redline in self.redlines:
            tag, i1, i2, j1, j2 = redline.opcodes
            source_tokens = redline.source_chunk.text
            test_tokens = redline.test_chunk.text

            if tag == "equal":
                console_text.append(re.sub("¶ ", "\n\n", "".join(source_tokens[i1:i2])))
            elif tag == "insert":
                for part in re.split("¶ ", "".join(test_tokens[j1:j2])):
                    console_text.append(part, "green")
            elif tag == "delete":
                console_text.append("".join(source_tokens[i1:i2]), "strike red")
            elif tag == "replace":
                console_text.append("".join(source_tokens[i1:i2]), "strike red")
                for part in re.split("¶ ", "".join(test_tokens[j1:j2])):
                    console_text.append(part, "green")

        return console_text

    # --------------------------------------------------
    # Compare Function
    # --------------------------------------------------

    def compare(self, test: str | None = None, output: str = "markdown", **options):
        """
        Compare `test` with `source` and return the delta in the specified format.

        :param test: Optional test string to compare with.
        :param output: Format of output ("markdown" or "rich").
        :param options: Extra formatting options.
        :return: The formatted diff result.
        """
        if options:
            self.options = options

        if test:
            if not (self._test and test == self._test):
                self.test = test
       elif self._test is None:
    raise ValueError(
        "Cannot perform comparison: No test string was provided.\n"
        "Why it went wrong: The Redlines object is missing the test text.\n"
        "How to fix: Add a test string either during initialization or when calling compare().\n\n"
        "Example:\n"
        "    redlines = Redlines('source', 'test')\n"
        "    print(redlines.compare())"
    )

        if output == "markdown":
            return self.output_markdown
        elif output == "rich":
            return self.output_rich

        return self.output_markdown
