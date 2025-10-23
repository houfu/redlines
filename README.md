# Redlines
![Repository banner image](repository-open-graph.png)
![PyPI - Version](https://img.shields.io/pypi/v/redlines)
![GitHub Release Date - Published_At](https://img.shields.io/github/release-date/houfu/redlines)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/houfu/redlines)
![PyPI - License](https://img.shields.io/pypi/l/redlines)

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

    The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

Which is rendered like this:

> The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

The library can also output the results in Markdown, HTML or `rich` format, and
for a variety of environments like Streamlit, Jupyter Notebooks, Google Colab and the terminal.

## Install

```shell
pip install redlines
```

### Supported Python Versions
This project supports the following Python versions:

- Python 3.10
- Python 3.11
- Python 3.12
- Python 3.13
- Python 3.14

Support for Python 3.8 and 3.9 has been dropped as they have reached their end-of-life.

### Optional: Install with NupunktProcessor support

For advanced sentence boundary detection (requires Python 3.11+):

```shell
pip install redlines[nupunkt]
```

The NupunktProcessor provides intelligent sentence tokenization that handles:
- Abbreviations (Dr., Mr., etc.)
- Decimals and numbers (3.14, $5.99)
- URLs and email addresses
- Legal citations and complex punctuation

See the [Usage](#advanced-custom-processors) section below for more details.

## For AI Agents & Automation

**🤖 Using redlines with Claude Code, Aider, Cursor, or other AI coding agents?**

Check out the **[Agent Integration Guide](AGENT_GUIDE.md)** for:
- Copy-paste ready code examples
- JSON schema documentation
- CLI automation patterns
- Error handling cookbook
- Performance guidelines
- Real-world integration examples

**Quick links:**
- [Agent Guide](AGENT_GUIDE.md) - Comprehensive guide for AI agents
- [Examples](examples/) - Runnable scripts for common tasks
- [CLI Reference](AGENT_GUIDE.md#output-formats) - Command-line usage

## Usage

The library contains one class: `Redlines`, which is used to compare text.

```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
  "The quick brown fox walks past the lazy dog.", markdown_style="none",
)
assert (
        test.output_markdown
        == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)
```

Alternatively, you can create Redline with the text to be tested, and compare several times to see the results.

```python
from redlines import Redlines

test = Redlines("The quick brown fox jumps over the lazy dog.", markdown_style="none")
assert (
        test.compare("The quick brown fox walks past the lazy dog.")
        == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)

assert (
        test.compare("The quick brown fox jumps over the dog.")
        == "The quick brown fox jumps over the <del>lazy </del>dog."
)
```

### Advanced: Custom Processors

Redlines supports custom processors for different tokenization strategies. By default, it uses `WholeDocumentProcessor` which tokenizes at the paragraph level.

#### Using NupunktProcessor

For sentence-level tokenization with intelligent boundary detection (requires `pip install redlines[nupunkt]`):

```python
from redlines import Redlines
from redlines.processor import NupunktProcessor

# Use NupunktProcessor for better handling of abbreviations and complex punctuation
processor = NupunktProcessor()
test = Redlines(
    "Dr. Smith said hello. Mr. Jones replied.",
    "Dr. Smith said hi. Mr. Jones replied.",
    processor=processor
)
```

**When to use NupunktProcessor:**
- Legal or technical documents with many abbreviations
- Text with URLs, emails, or complex citations
- When you need sentence-level granularity
- Documents with decimal numbers that shouldn't be treated as sentence boundaries

**When to use WholeDocumentProcessor (default):**
- Simple documents without complex sentence structures
- When speed is critical (5-6x faster than NupunktProcessor)
- When paragraph-level granularity is sufficient

See the [demo comparison](demo/README.md) for detailed performance and accuracy benchmarks.

### Command Line Tool

Redlines features a command line tool to visualize and analyze differences between texts.

#### Quick Start (Command-less)

For the simplest usage, just provide two strings or files - it outputs JSON by default:

```bash
# Compare two strings (outputs JSON)
redlines "The quick brown fox" "The slow brown fox"

# Compare two files
redlines old_version.txt new_version.txt

# Pretty-print JSON for readability
redlines --pretty file1.txt file2.txt
```

#### Specific Output Formats

For specific output formats, use the traditional commands:

```bash
# Rich terminal display with side-by-side comparison
redlines text "source text" "test text"

# Markdown output
redlines markdown file1.txt file2.txt --markdown-style ghfm

# Statistics only
redlines stats old.txt new.txt --quiet

# JSON with formatting
redlines json old.txt new.txt --pretty
```

**💡 Tip:** Run `redlines --help` to see all available commands, or `redlines guide` for the full [Agent Integration Guide](AGENT_GUIDE.md).

You may also want to check out the demo project [redlines-textual](https://github.com/houfu/redlines-textual).

## Documentation

[Read the available Documentation](https://houfu.github.io/redlines).

## Uses

* View and mark changes in legislation: [PLUS Explorer](https://houfu-plus-explorer.streamlit.app/)
* Visualise changes after ChatGPT transforms a
  text: [ChatGPT Prompt Engineering for Developers](https://www.deeplearning.ai/short-courses/chatgpt-prompt-engineering-for-developers/)
  Lesson 6

## License

MIT License

