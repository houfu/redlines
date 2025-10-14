import enum

__all__: tuple[str, ...] = (
    "MarkdownStyle",
    "OutputType",
)


class MarkdownStyle(str, enum.Enum):
    """The markdown styles supported by redlines."""

    RED_GREEN = "red_green"
    """Red and green colors for deletions and additions respectively."""

    NONE = "none"
    """No colors."""

    RED = "red"
    """Only red color for changes."""

    GHFM = "ghfm"
    """GitHub Flavored Markdown style."""

    BBCODE = "bbcode"
    """BBCode style."""

    STREAMLIT = "streamlit"
    """Streamlit style."""


class OutputType(str, enum.Enum):
    """The output types supported by redlines."""

    MARKDOWN = "markdown"
    """Markdown format."""

    RICH = "rich"
    """Rich format for terminal output."""
