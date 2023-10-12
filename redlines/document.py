from abc import ABC, abstractmethod


class Document(ABC):
    """
    An abstract base class used as a common data interchange with the redlines with formats other than python text strings.
    To see a basic implementation, you can look at the `PlainTextFile` class for text files

    |Supported File Formats | Class |
    |---| --- |
    |Plain Text files | `PlainTextFile` |
    """

    @property
    @abstractmethod
    def text(self) -> str:
        """
        This property is used by the redlines library to obtain the text to compare. Implement this method to return
        the text to be compared by redlines.
        """
        pass


class PlainTextFile(Document):
    """
    Use this class so that Redlines can read plain text files.

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

    """

    @property
    def text(self) -> str:
        """
        :return: The text of the file referred to when the Document was created.
        """
        return self._text

    def __init__(self, file_path):
        """
        Use this class so that Redlines can read plain text files.

        :param file_path: Path to the text file.
        """
        with open(file_path) as f:
            self._text = f.read()
