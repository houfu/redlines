# Redlines
![Repository banner image](repository-open-graph.png)
![PyPI - Version](https://img.shields.io/pypi/v/redlines)
![GitHub Release Date - Published_At](https://img.shields.io/github/release-date/houfu/redlines)
![GitHub last commit (by committer)](https://img.shields.io/github/last-commit/houfu/redlines)
![PyPI - License](https://img.shields.io/pypi/l/redlines)

`Redlines` compares two strings/text and produces structured output showing their differences. Changes are represented with strike-throughs and highlights, similar to Microsoft Word's track changes. The output includes detailed change information, positions, and statistics for programmatic use.

Supports multiple output formats: **JSON** (default, with structured change data and statistics), **Markdown**, **HTML**, and **rich** (terminal display).

## Quick Start

```bash
# Install
pip install redlines

# CLI: Compare two texts (outputs JSON by default)
redlines "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."

# Python: Compare and get markdown
from redlines import Redlines
test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
    markdown_style="none"
)
print(test.output_markdown)
# Output: The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.
```

**Supported:** Python 3.10 - 3.14 (Python 3.8 and 3.9 support dropped)

**Optional dependencies:**
- `pip install redlines[pdf]` for PDF file comparison
- `pip install redlines[nupunkt]` for advanced sentence boundary detection (Python 3.11+, handles abbreviations, citations, URLs)
- `pip install redlines[levenshtein]` for additional statistics

## Usage

### Python API

The library contains one class: `Redlines`, which is used to compare text.

**Basic comparison:**
```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
    markdown_style="none"
)
assert (
    test.output_markdown
    == "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)
```

**Multiple comparisons with one source:**
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

**JSON output with structured data:**
```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog."
)

# Get JSON with changes, positions, and statistics
print(test.output_json(pretty=True))
```

### CLI

**Basic usage (outputs JSON by default):**
```bash
redlines "old text" "new text"
redlines file1.txt file2.txt --pretty
```

**Output formats:**
```bash
redlines text "source" "test"              # Rich terminal display
redlines markdown file1.txt file2.txt      # Markdown output
redlines stats old.txt new.txt             # Statistics only
```

Run `redlines --help` or `redlines guide` for the [Agent Integration Guide](AGENT_GUIDE.md). See also: [redlines-textual](https://github.com/houfu/redlines-textual).

## Advanced Features

### Custom Processors

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

### For AI Agents & Automation

**🤖 Using with AI coding agents?** See the **[Agent Integration Guide](AGENT_GUIDE.md)** for JSON schemas, automation patterns, error handling, and [runnable examples](examples/).

## Documentation & Resources

**Full Documentation:** [https://houfu.github.io/redlines](https://houfu.github.io/redlines)

**Example Use Cases:**
* View and mark changes in legislation: [PLUS Explorer](https://houfu-plus-explorer.streamlit.app/)
* Visualise changes after ChatGPT transforms a text: [ChatGPT Prompt Engineering for Developers](https://www.deeplearning.ai/short-courses/chatgpt-prompt-engineering-for-developers/) Lesson 6

## License

MIT License
