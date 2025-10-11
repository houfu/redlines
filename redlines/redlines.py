from __future__ import annotations

import re
import typing as t

from rich.text import Text
from typing_extensions import Unpack

from .document import Document
from .enums import MarkdownStyle, OutputType
from .processor import DiffOperation, Redline, Stats, WholeDocumentProcessor

__all__: tuple[str, ...] = (
    "Redlines",
    "RedlinesOptions",
)

# Workaround for enum + literal support in type hints
# See: https://github.com/python/typing/issues/781
OutputTypeLike = OutputType | t.Literal["markdown", "rich"]


class RedlinesOptions(t.TypedDict, total=False):
    markdown_style: str | MarkdownStyle | None
    """The style to use for markdown output. See `Redlines.output_markdown` for more information."""
    ins_class: str
    """The CSS class to use for insertions when `markdown_style` is set to `custom_css`. Defaults to 'redline-inserted'."""
    del_class: str
    """The CSS class to use for deletions when `markdown_style` is set to `custom_css`. Defaults to 'redline-deleted'."""


class Redlines:
    _source: str | None = None
    _test: str | None = None
    _seq1: list[str] | None = None
    _seq2: list[str] | None = None
    _diff_operations: list[DiffOperation] | None = None

    @property
    def source(self) -> str:
        """
        Get the source text to be used as a basis for comparison.

        :return: The source text to be used as a basis for comparison.
        :rtype: str
        """
        if self._source is None:
            raise ValueError("No source string was provided.")
        return self._source

    @source.setter
    def source(self, value: str | Document) -> None:
        self._source = value.text if isinstance(value, Document) else value

        # If test is already set, process the new source against it
        if self._test is not None:
            self._diff_operations = self.processor.process(self._source, self._test)

    @property
    def test(self) -> str:
        """
        Get the text to be compared with the source.

        :return: The text to be compared with the source.
        :rtype: str
        """
        if self._test is None:
            raise ValueError("No test string was provided.")
        return self._test

    @test.setter
    def test(self, value: str | Document) -> None:
        self._test = value.text if isinstance(value, Document) else value

        # Process the text against the source
        if self._source is not None:
            self._diff_operations = self.processor.process(self._source, self._test)

    @property
    def _diff_ops(self) -> list[DiffOperation]:
        """
        Internal property: Return the list of DiffOperation objects (includes 'equal' operations).
        For internal rendering code.

        :return: List of DiffOperation objects
        """
        if self._diff_operations is None:
            raise ValueError(
                "No test string was provided when the function was called, or during initialisation."
            )
        return self._diff_operations

    @property
    def redlines(self) -> list[Redline]:
        """
        Return the list of Redline objects representing actual changes between source and test.

        This is an alias for the `changes` property and provides the same functionality.
        Only actual changes are returned (equal operations are excluded).

        :return: List of Redline objects
        :rtype: list[Redline]
        """
        return self.changes

    def __init__(
        self,
        source: str | Document,
        test: str | Document | None = None,
        **options: Unpack[RedlinesOptions],
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
        :type source: str | Document
        :param test: Optional test text to compare with the source.
        :type test: str | Document | None
        :param options: Additional options for comparison and output formatting.
        :type options: RedlinesOptions
        """
        self.processor = WholeDocumentProcessor()
        self.source = source.text if isinstance(source, Document) else source
        self.options = options
        self._diff_operations = None
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

        :return: List of 5-tuples describing how to turn `source` into `test`.
        :rtype: list[tuple[str, int, int, int, int]]
        """
        return [diff_op.opcodes for diff_op in self._diff_ops]

    @property
    def changes(self) -> list[Redline]:
        """
        Return list of Redline objects representing the differences between source and test.

        This provides a user-friendly interface for programmatically accessing changes,
        with direct access to the changed text and position information. Only actual
        changes are returned (equal operations are excluded).

        ```python
        from redlines import Redlines

        test = Redlines(
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog."
        )

        for redline in test.changes:
            print(f"{redline.operation}: {redline.source_text} -> {redline.test_text}")
        # Output: replace: jumps over  -> walks past
        ```

        :return: List of Redline objects (only actual changes, no 'equal' operations)
        """
        result = []
        for diff_op in self._diff_ops:
            tag, i1, i2, j1, j2 = diff_op.opcodes

            # Skip equal operations - only return actual changes
            if tag == "equal":
                continue

            source_tokens = diff_op.source_chunk.text
            test_tokens = diff_op.test_chunk.text

            # Extract text and positions based on operation type
            if tag == "delete":
                redline = Redline(
                    operation="delete",
                    source_text="".join(source_tokens[i1:i2]),
                    test_text=None,
                    source_position=(i1, i2),
                    test_position=None,
                )
            elif tag == "insert":
                redline = Redline(
                    operation="insert",
                    source_text=None,
                    test_text="".join(test_tokens[j1:j2]),
                    source_position=None,
                    test_position=(j1, j2),
                )
            elif tag == "replace":
                redline = Redline(
                    operation="replace",
                    source_text="".join(source_tokens[i1:i2]),
                    test_text="".join(test_tokens[j1:j2]),
                    source_position=(i1, i2),
                    test_position=(j1, j2),
                )
            else:
                continue

            result.append(redline)

        return result

    def get_changes(
        self, operation: str | None = None
    ) -> list[Redline]:
        """
        Get changes (redlines), optionally filtered by operation type.

        ```python
        from redlines import Redlines

        test = Redlines(
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog."
        )

        # Get all changes
        all_changes = test.get_changes()

        # Get only replacements
        replacements = test.get_changes(operation="replace")

        # Get deletions
        deletions = test.get_changes(operation="delete")

        # Get insertions
        insertions = test.get_changes(operation="insert")
        ```

        :param operation: Filter by operation type: "delete", "insert", or "replace". If None, returns all changes.
        :return: List of Redline objects matching the filter
        """
        changes = self.changes

        if operation is None:
            return changes

        if operation not in ("delete", "insert", "replace"):
            raise ValueError(
                f"Invalid operation '{operation}'. Must be 'delete', 'insert', or 'replace'."
            )

        return [r for r in changes if r.operation == operation]

    def stats(self) -> Stats:
        """
        Get statistics about the changes between source and test.

        ```python
        from redlines import Redlines

        test = Redlines(
            "The quick brown fox jumps over the lazy dog.",
            "The quick brown fox walks past the lazy dog."
        )

        stats = test.stats()
        print(f"Total changes: {stats.total_changes}")
        print(f"Deletions: {stats.deletions}")
        print(f"Insertions: {stats.insertions}")
        print(f"Replacements: {stats.replacements}")
        ```

        :return: Stats object with change counts
        """
        changes = self.changes

        deletions = sum(1 for c in changes if c.operation == "delete")
        insertions = sum(1 for c in changes if c.operation == "insert")
        replacements = sum(1 for c in changes if c.operation == "replace")

        return Stats(
            total_changes=len(changes),
            deletions=deletions,
            insertions=insertions,
            replacements=replacements,
        )

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

        :return: The delta in Markdown format.
        :rtype: str
        """
        result: list[str] = []

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

        for diff_op in self._diff_ops:
            tag, i1, i2, j1, j2 = diff_op.opcodes
            source_tokens = diff_op.source_chunk.text
            test_tokens = diff_op.test_chunk.text

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
        """
        Returns the delta in text with colors/style for the console.

        :return: The delta in text with colors/style for the console.
        :rtype: Text
        """
        console_text = Text()

        for diff_op in self._diff_ops:
            tag, i1, i2, j1, j2 = diff_op.opcodes
            source_tokens = diff_op.source_chunk.text
            test_tokens = diff_op.test_chunk.text

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

    def compare(
        self,
        test: str | None = None,
        output: OutputTypeLike = OutputType.MARKDOWN,
        **options: Unpack[RedlinesOptions],
    ) -> Text | str:
        """
        Compare `test` with `source`, and produce a delta in a format specified by `output`.

        :param test: Optional test string to compare. If None, uses the test string provided during initialisation.
        :type test: str | None
        :param output: The format which the delta should be produced. Currently, "markdown" and "rich" are supported. Defaults to "markdown".
        :type output: OutputTypeLike
        :param options: Additional options for comparison and output formatting.
        :type options: RedlinesOptions
        :return: The delta in the format specified by `output`.
        :rtype: Text | str
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

        if output == OutputType.MARKDOWN:
            return self.output_markdown
        elif output == OutputType.RICH:
            return self.output_rich
        return self.output_markdown
