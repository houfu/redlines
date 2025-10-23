# Redlines
![Repository banner image](repository-open-graph.png)
![PyPI - Version](https://img.shields.io/pypi/v/redlines)
![GitHub Release Date - Published_At](https://img.shields.io/github/release-date/houfu/redlines)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/houfu/redlines)
![PyPI - License](https://img.shields.io/pypi/l/redlines)

`Redlines` compares two strings/text and shows their differences. The changes are represented with
strike-throughs and highlights, similar to Microsoft Word's track changes.

The output can be in JSON, Markdown, HTML, or `rich` format. JSON is the default for CLI and automation use.

## Example

```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog."
)

# Markdown output (with simple <del>/<ins> tags)
print(test.output_markdown)  # requires markdown_style="none"
# Output: The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

# JSON output (default for CLI)
print(test.output_json())
# Returns structured JSON with changes, positions, and statistics
```

Supports multiple output formats for different environments: JSON (default for automation), Markdown, HTML, and `rich` (terminal).

## Install

```shell
pip install redlines
```

**Supported:** Python 3.10 - 3.14 (Python 3.8 and 3.9 support dropped)

**Optional:** `pip install redlines[nupunkt]` for advanced sentence boundary detection (Python 3.11+, handles abbreviations, citations, URLs)

## For AI Agents & Automation

**🤖 Using with AI coding agents?** See the **[Agent Integration Guide](AGENT_GUIDE.md)** for JSON schemas, automation patterns, error handling, and [runnable examples](examples/).

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

Use `NupunktProcessor` for sentence-level tokenization with intelligent boundary detection:

```python
from redlines import Redlines
from redlines.processor import NupunktProcessor

processor = NupunktProcessor()
test = Redlines("Dr. Smith said hello.", "Dr. Smith said hi.", processor=processor)
```

**Use NupunktProcessor for:** Legal/technical documents with abbreviations, URLs, citations, decimals
**Use WholeDocumentProcessor (default) for:** Simple documents, speed-critical tasks (5-6x faster), paragraph-level granularity

See [demo comparison](demo/README.md) for benchmarks.

### Command Line Tool

**Quick Start (outputs JSON by default):**
```bash
redlines "old text" "new text"
redlines file1.txt file2.txt --pretty
```

**Specific formats:**
```bash
redlines text "source" "test"              # Rich terminal display
redlines markdown file1.txt file2.txt      # Markdown output
redlines stats old.txt new.txt             # Statistics only
```

Run `redlines --help` or `redlines guide` for the [Agent Integration Guide](AGENT_GUIDE.md). See also: [redlines-textual](https://github.com/houfu/redlines-textual).

## Documentation

[Read the available Documentation](https://houfu.github.io/redlines).

## Uses

* View and mark changes in legislation: [PLUS Explorer](https://houfu-plus-explorer.streamlit.app/)
* Visualise changes after ChatGPT transforms a
  text: [ChatGPT Prompt Engineering for Developers](https://www.deeplearning.ai/short-courses/chatgpt-prompt-engineering-for-developers/)
  Lesson 6

## License

MIT License

