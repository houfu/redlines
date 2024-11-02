"""
# Redlines

`Redlines` produces a text showing the differences between two strings/text. The changes are represented with
strike-throughs and underlines, which looks similar to Microsoft Word's track changes. This method of showing changes is
more familiar to lawyers and is more compact for long series of characters.

Redlines uses [SequenceMatcher](https://docs.python.org/3/library/difflib.html#difflib.SequenceMatcher)
to find differences between words used.
The output can be in HTML, Markdown, or `rich` format.

## Example

Given an original string:

    The quick brown fox jumps over the lazy dog.

And the string to be tested with:

    The quick brown fox walks past the lazy dog.

The library gives a result of:

    "The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog."


Which is rendered like this:

The quick brown fox <span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span><span style='color:green;font-weight:700;'>walks past </span>the lazy dog.

## Install

Use your regular package manager to install the library in your python environment.

```terminal
pip install redlines
```

## Quickstart

This is the most direct way to produce the example.

```python
# import the class
from redlines import Redlines

# Create a Redlines object using the two strings to compare
test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
)

# This produces an output in markdown format
test.output_markdown
```

## Common Issues

The documentation contains other information on common issues users have faced while using this library:

* [Styling](redlines/redlines.html#styling-markdown)
* [Ensuring styling appears in environments such as Jupyter Notebooks, Streamlit, CoLab etc](redlines/redlines.html#markdown-output-in-specific-environments)
* [Using plain text files and others as input](redlines/document.html)
* [Using the CLI](redlines/cli.html)

"""

from .document import *
from .redlines import Redlines

__all__ = ["redlines", "document", "processor", "cli"]
