from __future__ import annotations

import re

from rich.text import Text

from redlines.document import Document
from redlines.processor import WholeDocumentProcessor, Redline


class Redlines:
    _source: str = None
    _test: str = None
    _seq1: list[str] = None
    _seq2: list[str] = None

    @property
    def source(self) -> str:
        """
        :return: The source text to be used as a basis for comparison.
        """
        return self._source

    @source.setter
    def source(self, value):
        self._source = value.text if isinstance(value, Document) else value

        # If test is already set, process the new source against it
        if self._test is not None:
            self._redlines = self.processor.process(self._source, self._test)

    @property
    def test(self):
        """:return: The text to be compared with the source."""
        return self._test

    @test.setter
    def test(self, value):
        self._test = value.text if isinstance(value, Document) else value

        # Process the text against the source
        if self._source is not None and self._test is not None:
            self._redlines = self.processor.process(self._source, self._test)

    @property
    def redlines(self) -> list[Redline]:
        """
        Return the list of Redline objects representing the changes from source to test.

        :return: List of Redline objects
        """
        if self._redlines is None:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )
        return self._redlines

    def __init__(
        self, source: str | Document, test: str | Document | None = None, **options
    ):
        """
        Redline is a class used to compare text, and producing human-readable differences or deltas
        which look like track changes in Microsoft Word.

        ```python
        # import the class
        from redlines import Redlines

        # Create a Redlines object using the two strings to compare
        test = Redlines(
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog.",
        )

        # This produces an output in Markdown format
        test.output_markdown
        ```

        Besides strings, Redlines can also receive an input in another format if it is supported by the Document class

        ```python
        from redlines import PlainTextFile

        source = PlainTextFile("tests/documents/PlainTextFile/source.txt")
        test = PlainTextFile("tests/documents/PlainTextFile/test.txt")

        redline = Redlines(source, test)
        assert (
            redline.output_markdown
            == "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog."
        )

        ```

        :param source: The source text to be used as a basis for comparison.
        :param test: Optional test text to compare with the source.
        """
        self.processor = WholeDocumentProcessor()
        self.source = source.text if isinstance(source, Document) else source
        self.options = options
        self._redlines = None
        if test:
            self.test = test.text if isinstance(test, Document) else test
            # self.compare()

    @property
    def opcodes(self) -> list[tuple[str, int, int, int, int]]:
        """
        Return list of 5-tuples describing how to turn `source` into `test`.
        Similar to [`SequenceMatcher.get_opcodes`](https://docs.python.org/3/library/difflib.html#difflib.SequenceMatcher.get_opcodes).

        ```pycon
        >>> test_string_1 = 'The quick brown fox jumps over the lazy dog.'
        ... test_string_2 = 'The quick brown fox walks past the lazy dog.'
        ... s = Redlines(test_string_1, test_string_2)
        ... s.opcodes
        [('equal', 0, 4, 0, 4), ('replace', 4, 6, 4, 6), ('equal', 6, 9, 6, 9)]
        ```
        """
        return [redline.opcodes for redline in self.redlines]

    @property
    def output_markdown(self) -> str:
        """
        Returns the delta in Markdown format.

        ## Styling Markdown
        To output markdown in a particular manner, you must pass a `markdown_style` option when the `Redlines` object
        is created or when `Redlines.compare` is called.

        ```python
        from redlines import Redlines

        test = Redlines(
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog.",
            markdown_style="red"  # This option specifies the style as red
        )

        test.compare(markdown_style="none") # This option specifies the style as none
        ```

        ### Available styles

        | Style | Preview |
        |-------| -------|
        |red-green (**default**) | "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog."|
        |none | 'The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.'|
        |red | "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:red;font-weight:700;'>walks past </span>the lazy dog."|
        |ghfm (GitHub Flavored Markdown)| 'The quick brown fox ~~jumps over ~~**walks past **the lazy dog.' |
        |bbcode (BBCode) | 'The quick brown fox [s][color=red]jumps over [/color][/s][b][color=green]walks past [/color][/b]the lazy dog.' |
        |streamlit | 'The quick brown fox ~~:red[jumps over ]~~ **:green[walks past ]** the lazy dog.' |

        ### Custom styling

        You can also use css classes to provide custom styling by setting `markdown_style` as "custom_css".
        Insertions and deletions are now styled using the "redline-inserted" and "redline-deleted" CSS classes.
        You can also set your own CSS classes by specifying the name of the CSS class in the options `ins_class`
        and `del_class` respectively in the constructor or compare function.

        ## Markdown output in specific environments

        Users have reported that the output doesn't display correctly in their environments.
        This is because styling may not appear in markdown environments which disallow HTML.
        There is no consistent support for strikethroughs and colors in the markdown standard,
        and styling is largely accomplished through raw HTML. If you are using GitHub or Streamlit, you may not get
        the formatting you expect or see any change at all.

        If you are facing this kind of difficulty, here are some recommendations. If your experience doesn't match
        the hints or description below, or you continue to face problems, please raise an issue.

        ### Jupyter Notebooks
        This library was first written for the Jupyter notebook environment, so all the available styles, including
        the default (`red-green`), `red` and `none` work.

        ### Streamlit

        Try this:

        * If streamlit version is >= 1.16.0, consider the markdown style "streamlit"
        * If streamlit version is < 1.16.0, consider the markdown style `ghfm`
        * Enable parsing of HTML. In Streamlit, you need to set the `unsafe_allow_html` argument in `st.write` or
        `st.markdown` to `True`.

        ### Colab

        Try this:
        * Use the markdown style `none` or `ghfm`
        * `Redlines.output_rich` has been reported to work in Colab

        """
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
            elif style == "bbcode":
                md_styles = {
                    "ins": ("[b][color=green]", "[/color][/b]"),
                    "del": ("[s][color=red]", "[/color][/s]"),
                }
            elif style == "streamlit":
                md_styles = {"ins": ("**:green[", "]** "), "del": ("~~:red[", "]~~ ")}

        for redline in self.redlines:
            tag, i1, i2, j1, j2 = redline.opcodes
            source_tokens = redline.source_chunk.text
            test_tokens = redline.test_chunk.text

            if tag == "equal":
                temp_str = "".join(source_tokens[i1:i2])
                temp_str = re.sub("¶ ", "\n\n", temp_str)
                # here we use '¶ ' instead of ' ¶ ', because the leading space will be included in the previous token,
                # according to tokenizer = re.compile(r"((?:[^()\s]+|[().?!-])\s*)")
                result.append(temp_str)
            elif tag == "insert":
                temp_str = "".join(test_tokens[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    result.append(f"{md_styles['ins'][0]}{split}{md_styles['ins'][1]}")
                    result.append("\n\n")
                if len(splits) > 0:
                    result.pop()
            elif tag == "delete":
                result.append(
                    f"{md_styles['del'][0]}{''.join(source_tokens[i1:i2])}{md_styles['del'][1]}"
                )
                # for 'delete', we make no change, because otherwise there will be two times '\n\n' than the original
                # text.
            elif tag == "replace":
                result.append(
                    f"{md_styles['del'][0]}{''.join(source_tokens[i1:i2])}{md_styles['del'][1]}"
                )
                temp_str = "".join(test_tokens[j1:j2])
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

        for redline in self.redlines:
            tag, i1, i2, j1, j2 = redline.opcodes
            source_tokens = redline.source_chunk.text
            test_tokens = redline.test_chunk.text

            if tag == "equal":
                temp_str = "".join(source_tokens[i1:i2])
                temp_str = re.sub("¶ ", "\n\n", temp_str)
                console_text.append(temp_str)
            elif tag == "insert":
                temp_str = "".join(test_tokens[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    console_text.append(split, "green")
            elif tag == "delete":
                console_text.append("".join(source_tokens[i1:i2]), "strike red")
            elif tag == "replace":
                console_text.append("".join(source_tokens[i1:i2]), "strike red")
                temp_str = "".join(test_tokens[j1:j2])
                splits = re.split("¶ ", temp_str)
                for split in splits:
                    console_text.append(split, "green")

        return console_text

    def compare(self, test: str | None = None, output: str = "markdown", **options):
        """
        Compare `test` with `source`, and produce a delta in a format specified by `output`.

        :param test: Optional test string to compare. If None, uses the test string provided during initialisation.
        :param output: The format which the delta should be produced. Currently, "markdown" and "rich" are supported. Defaults to "markdown".
        :return: The delta in the format specified by `output`.
        """
        if options:
            self.options = options

        if test:
            if self._test and test == self._test:
                # If we've already processed this test string, no need to reprocess
                pass
            else:
                self.test = test
        elif self._test is None:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )

        if output == "markdown":
            return self.output_markdown
        elif output == "rich":
            return self.output_rich
        return self.output_markdown
