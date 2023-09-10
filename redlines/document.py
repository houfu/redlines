from abc import ABC, abstractmethod


class Document(ABC):
    """An abstract base class used as a common data interchange with the redlines with formats other than plain text"""

    @property
    @abstractmethod
    def text(self) -> str:
        """
        This property is used by the redlines library to obtain the text to compare. Implement this method to return
        the text to be compared by redlines.
        """
        pass


class PlainTextFile(Document):
    """For plain text files"""

    @property
    def text(self) -> str:
        return self._text

    def __init__(self, file_path):
        with open(file_path) as f:
            self._text = f.read()
