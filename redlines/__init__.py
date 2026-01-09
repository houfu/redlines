"""
# Redlines

`Redlines` compares two strings/text and shows their differences. The changes are represented with
strike-throughs and highlights, similar to Microsoft Word's track changes.

The output can be in JSON, Markdown, HTML, or `rich` format. JSON is the default for CLI and automation use.

## Quick Start

```python
from redlines import Redlines

# Create a Redlines object
test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
)

# Get markdown output with <del>/<ins> tags
print(test.compare(markdown_style="none"))
# Output: The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.

# Get JSON output (structured data)
print(test.output_json())

# Get rich output (terminal display)
print(test.output_rich)
```

## Installation

```bash
pip install redlines

# Optional: Advanced sentence detection (Python 3.11+)
pip install redlines[nupunkt]

# Optional: Levenshtein distance statistics
pip install redlines[levenshtein]
```

## For AI Agents & Automation

**🤖 Using with AI coding agents?**

See the [Agent Integration Guide](https://github.com/houfu/redlines/blob/main/AGENT_GUIDE.md) for:
- JSON schema documentation
- CLI automation patterns
- Error handling cookbook
- Performance guidelines
- [Runnable examples](https://github.com/houfu/redlines/tree/main/examples)

Quick CLI usage:
```bash
# Outputs JSON by default
redlines "old text" "new text"

# Pretty-print JSON
redlines file1.txt file2.txt --pretty

# Other formats
redlines text "source" "test"       # Rich terminal display
redlines markdown file1.txt file2.txt  # Markdown output
```

## API Documentation

* [Redlines](redlines/redlines.html) - Main comparison class
* [Document](redlines/document.html) - File input support
* [Processor](redlines/processor.html) - Custom tokenization
* [CLI](redlines/cli.html) - Command-line interface

"""

from .document import *
from .enums import *
from .pdf import *
from .processor import *
from .redlines import *
