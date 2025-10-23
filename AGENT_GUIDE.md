# Agent Integration Guide

**Make AI coding agents productive with redlines in under 5 minutes.**

This guide is optimized for AI coding agents (Claude Code, Aider, Cursor, etc.) and automation tools. All examples are copy-paste ready and tested.

## Table of Contents

- [Quick Start](#quick-start)
- [Common Patterns](#common-patterns)
- [Output Formats](#output-formats)
- [JSON Schema Reference](#json-schema-reference)
- [Decision Matrix](#decision-matrix)
- [Programmatic API](#programmatic-api)
- [Error Handling](#error-handling)
- [Performance Guidelines](#performance-guidelines)
- [Integration Examples](#integration-examples)

---

## Quick Start

### 🤖 Agent-Friendly CLI (New!)

For maximum simplicity, you can now invoke redlines without specifying a command. It automatically outputs JSON (the most agent-friendly format):

```bash
# Simplest invocation - just provide two strings/files
redlines "source text" "test text"

# Pretty-print for readability
redlines --pretty "source text" "test text"

# Works with files too
redlines old_version.txt new_version.txt
```

**Why this is better for agents:**
- No need to choose between `text`, `json`, `markdown`, `stats` commands upfront
- JSON output is structured and parseable
- Consistent, predictable behavior
- Fewer tokens needed in prompts

**Traditional commands still work** if you need specific output formats (see [Output Formats](#output-formats)).

### Installation

```bash
# Basic installation
pip install redlines

# With advanced sentence tokenization (Python 3.11+)
pip install redlines[nupunkt]

# With Levenshtein distance metrics
pip install redlines[levenshtein]
```

### Your First Comparison (30 seconds)

```python
from redlines import Redlines

# Compare two strings
diff = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog."
)

# Get markdown output
print(diff.output_markdown)
# Output: The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.
```

### CLI Quick Start

```bash
# Compare strings (command-less, outputs JSON by default)
redlines "Hello world" "Hi world"

# Pretty-print JSON output
redlines --pretty "Hello world" "Hi world"

# Compare files (auto-detected, command-less)
redlines old_version.txt new_version.txt

# Or use explicit commands for specific output formats
redlines text "Hello world" "Hi world"
redlines json old_version.txt new_version.txt --pretty
redlines markdown file1.txt file2.txt --markdown-style ghfm

# Check if files differ (for CI/CD)
if redlines file1.txt file2.txt > /dev/null 2>&1; then
    echo "Files have changes"
else
    echo "Files are identical"
fi
```

---

## Common Patterns

### Pattern 1: Compare Two Files

```python
from pathlib import Path
from redlines import Redlines

# Read files
source = Path("old_version.txt").read_text()
test = Path("new_version.txt").read_text()

# Compare
diff = Redlines(source, test)

# Get results
print(f"Total changes: {diff.stats().total_changes}")
print(diff.output_markdown)
```

### Pattern 2: Get Machine-Readable JSON

```python
import json
from redlines import Redlines

diff = Redlines(source, test)

# Get JSON output
json_output = diff.output_json(pretty=True)
data = json.loads(json_output)

# Process changes
for change in data["changes"]:
    print(f"{change['type']}: {change.get('source_text', '')} → {change.get('test_text', '')}")
```

### Pattern 3: Filter Specific Operations

```python
from redlines import Redlines

diff = Redlines(source, test)

# Get only insertions
insertions = diff.get_changes(operation="insert")
for change in insertions:
    print(f"Added: {change.test_text}")

# Get only deletions
deletions = diff.get_changes(operation="delete")
for change in deletions:
    print(f"Removed: {change.source_text}")

# Get only replacements
replacements = diff.get_changes(operation="replace")
for change in replacements:
    print(f"Changed: {change.source_text} → {change.test_text}")
```

### Pattern 4: Collect Statistics

```python
from redlines import Redlines

diff = Redlines(source, test)
stats = diff.stats()

print(f"Total changes: {stats.total_changes}")
print(f"Insertions: {stats.insertions}")
print(f"Deletions: {stats.deletions}")
print(f"Replacements: {stats.replacements}")
print(f"Change ratio: {stats.change_ratio:.1%}")
print(f"Characters added: {stats.chars_added}")
print(f"Characters deleted: {stats.chars_deleted}")
print(f"Net change: {stats.chars_net_change}")
```

### Pattern 5: Batch Process Multiple Files

```python
from pathlib import Path
from redlines import Redlines

def compare_directory(dir1: Path, dir2: Path):
    """Compare all matching files in two directories."""
    results = []

    for file1 in dir1.glob("*.txt"):
        file2 = dir2 / file1.name
        if not file2.exists():
            continue

        diff = Redlines(
            file1.read_text(),
            file2.read_text()
        )

        stats = diff.stats()
        if stats.total_changes > 0:
            results.append({
                "file": file1.name,
                "changes": stats.total_changes,
                "change_ratio": stats.change_ratio
            })

    return results

# Usage
results = compare_directory(Path("old/"), Path("new/"))
for result in results:
    print(f"{result['file']}: {result['changes']} changes ({result['change_ratio']:.1%})")
```

### Pattern 6: Generate HTML Report

```python
from redlines import Redlines

diff = Redlines(source, test, markdown_style="none")

html_template = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        del {{ color: red; text-decoration: line-through; }}
        ins {{ color: green; text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Diff Report</h1>
    <div>{diff.output_markdown}</div>
</body>
</html>
"""

Path("report.html").write_text(html_template)
```

---

## Output Formats

### Markdown Styles

```python
from redlines import Redlines
from redlines.enums import MarkdownStyle

# Available styles:
styles = {
    "red_green": MarkdownStyle.RED_GREEN,    # Red strikethrough + green bold (default)
    "none": MarkdownStyle.NONE,              # Plain <del>/<ins> HTML tags
    "red": MarkdownStyle.RED,                # All changes in red
    "ghfm": MarkdownStyle.GHFM,             # GitHub Flavored Markdown
    "bbcode": MarkdownStyle.BBCODE,         # BBCode format
    "streamlit": MarkdownStyle.STREAMLIT,   # Streamlit-compatible
}

# Use a style
diff = Redlines(source, test, markdown_style=MarkdownStyle.GHFM)
print(diff.output_markdown)
```

### Rich Terminal Output

```python
from redlines import Redlines
from rich import print as rprint

diff = Redlines(source, test)

# Get Rich-formatted output for terminal
rprint(diff.output_rich)
```

### JSON Output

```python
import json
from redlines import Redlines

diff = Redlines(source, test)

# Pretty-printed JSON
json_str = diff.output_json(pretty=True)

# Compact JSON
json_str = diff.output_json(pretty=False)

# Parse and use
data = json.loads(json_str)
```

---

## JSON Schema Reference

### Complete JSON Structure

```json
{
  "source": "original text",
  "test": "modified text",
  "source_tokens": ["token1", "token2", " ¶ "],
  "test_tokens": ["token1", "token3", " ¶ "],
  "changes": [
    {
      "type": "replace",
      "source_text": "token2",
      "test_text": "token3",
      "source_position": [1, 2],
      "test_position": [1, 2],
      "source_char_position": [7, 13],
      "test_char_position": [7, 13]
    }
  ],
  "stats": {
    "total_changes": 1,
    "deletions": 0,
    "insertions": 0,
    "replacements": 1,
    "longest_change_length": 6,
    "shortest_change_length": 6,
    "average_change_length": 6.0,
    "change_ratio": 0.15,
    "chars_added": 6,
    "chars_deleted": 6,
    "chars_net_change": 0,
    "levenshtein_distance": 3
  }
}
```

### Field Descriptions

#### Root Fields
- **`source`** (string): Original text
- **`test`** (string): Modified text
- **`source_tokens`** (array of strings): Tokenized source text (` ¶ ` marks paragraph boundaries)
- **`test_tokens`** (array of strings): Tokenized test text

#### Change Object
- **`type`** (string): Operation type - `"insert"`, `"delete"`, or `"replace"`
- **`source_text`** (string | null): Original text (null for insertions)
- **`test_text`** (string | null): Modified text (null for deletions)
- **`source_position`** (array of 2 ints | null): Token position `[start, end]` in source (null for insertions)
- **`test_position`** (array of 2 ints | null): Token position `[start, end]` in test (null for deletions)
- **`source_char_position`** (array of 2 ints | null): Character position `[start, end]` in source
- **`test_char_position`** (array of 2 ints | null): Character position `[start, end]` in test

#### Stats Object
- **`total_changes`** (int): Total number of change operations
- **`deletions`** (int): Count of deletion operations
- **`insertions`** (int): Count of insertion operations
- **`replacements`** (int): Count of replacement operations
- **`longest_change_length`** (int): Length of longest change in characters
- **`shortest_change_length`** (int): Length of shortest change in characters
- **`average_change_length`** (float): Mean change length in characters
- **`change_ratio`** (float): Percentage of text modified (0.0 to 1.0)
- **`chars_added`** (int): Total characters added (insertions + replacement additions)
- **`chars_deleted`** (int): Total characters deleted (deletions + replacement deletions)
- **`chars_net_change`** (int): Net character change (added - deleted)
- **`levenshtein_distance`** (int | null): Edit distance (null if Levenshtein library not installed)

---

## Decision Matrix

| Use Case | Recommended Format | CLI Command | Reason |
|----------|-------------------|-------------|---------|
| **AI agents** | JSON | `redlines file1 file2` | Simplest invocation, structured output |
| **CI/CD check** | JSON | `redlines file1 file2` or `redlines json file1 file2 --quiet` | Parseable, scriptable, exit codes |
| **Human review** | Markdown (GHFM) | `redlines markdown file1 file2 --markdown-style ghfm` | GitHub-compatible rendering |
| **Terminal display** | Rich text | `redlines text file1 file2` | Colored, formatted output |
| **Metrics collection** | Stats | `redlines stats file1 file2 --quiet` | Log-friendly plain text |
| **Automation/scripts** | JSON + exit codes | `redlines file1 file2` | Exit code 0=changes, 1=no changes |
| **HTML report** | Markdown (none) | Programmatic API | Clean HTML tags for styling |
| **Documentation** | Markdown (streamlit) | Programmatic API | Streamlit-compatible markup |

### Exit Code Usage

```bash
# Check if files differ (useful in CI/CD) - command-less invocation
if redlines file1.txt file2.txt > /dev/null 2>&1; then
    echo "Exit code 0: Changes detected"
else
    exitcode=$?
    if [ $exitcode -eq 1 ]; then
        echo "Exit code 1: No changes (files identical)"
    else
        echo "Exit code 2: Error occurred"
    fi
fi

# Or use the stats command for more verbose output
if redlines stats file1.txt file2.txt --quiet; then
    echo "Exit code 0: Changes detected"
else
    echo "Exit code 1: No changes or error occurred"
fi
```

---

## Programmatic API

### Core Classes

#### `Redlines` Class

```python
from redlines import Redlines

# Create instance
diff = Redlines(
    source="original text",
    test="modified text",
    processor=None,  # Optional: Custom processor (default: WholeDocumentProcessor)
    markdown_style="red_green"  # Optional: Markdown style
)

# Or compare later
diff = Redlines("original text")
result = diff.compare("modified text")
```

#### Key Properties and Methods

```python
# Get changes (excludes "equal" operations)
changes: list[Redline] = diff.changes
redlines: list[Redline] = diff.redlines  # Alias for changes

# Filter changes by operation
insertions = diff.get_changes(operation="insert")
deletions = diff.get_changes(operation="delete")
replacements = diff.get_changes(operation="replace")
all_changes = diff.get_changes()  # Same as .changes

# Get statistics
stats: Stats = diff.stats()

# Get opcodes (like difflib)
opcodes: list[tuple] = diff.opcodes  # [(operation, i1, i2, j1, j2), ...]

# Output formats
markdown: str = diff.output_markdown
rich_text: Text = diff.output_rich
json_str: str = diff.output_json(pretty=False)
```

### `Redline` Dataclass

```python
from redlines.processor import Redline

# Structure of a Redline object
@dataclass
class Redline:
    operation: Literal["delete", "insert", "replace"]
    source_text: str | None
    test_text: str | None
    source_position: tuple[int, int] | None  # (start, end) token indices
    test_position: tuple[int, int] | None

# Example usage
for change in diff.changes:
    if change.operation == "replace":
        print(f"Line {change.source_position}: {change.source_text} → {change.test_text}")
```

### `Stats` Dataclass

```python
from redlines.processor import Stats

# Structure of a Stats object
@dataclass
class Stats:
    total_changes: int
    deletions: int
    insertions: int
    replacements: int
    longest_change_length: int
    shortest_change_length: int
    average_change_length: float
    change_ratio: float  # 0.0 to 1.0
    chars_added: int
    chars_deleted: int
    chars_net_change: int
    levenshtein_distance: int | None  # None if library not installed

# Example usage
stats = diff.stats()
print(f"Modified {stats.change_ratio:.1%} of the document")
print(f"Net change: {stats.chars_net_change:+d} characters")
```

---

## Error Handling

### Common Errors and Solutions

#### 1. File Not Found (CLI)

```bash
$ redlines json nonexistent.txt other.txt
# Error: Failed to read file 'nonexistent.txt': [Errno 2] No such file or directory

# Solution: Check file paths
if [ -f "file.txt" ]; then
    redlines json file.txt other.txt
else
    echo "File not found"
fi
```

#### 2. Encoding Errors (CLI)

```bash
# Error: Failed to read file 'file.txt': File encoding is not UTF-8

# Solution: Convert file to UTF-8
iconv -f ISO-8859-1 -t UTF-8 file.txt > file_utf8.txt
redlines json file_utf8.txt other.txt
```

#### 3. Invalid Operation Filter

```python
from redlines import Redlines

diff = Redlines(source, test)

try:
    changes = diff.get_changes(operation="invalid")
except ValueError as e:
    print(f"Error: {e}")  # Error: Invalid operation: invalid
    # Valid operations: "insert", "delete", "replace", or None
```

#### 4. Missing Optional Dependencies

```python
from redlines.processor import LEVENSHTEIN_AVAILABLE

if not LEVENSHTEIN_AVAILABLE:
    print("Levenshtein library not installed - distance will be None")
    # Install with: pip install redlines[levenshtein]

# Stats will still work, but levenshtein_distance will be None
stats = diff.stats()
if stats.levenshtein_distance is not None:
    print(f"Edit distance: {stats.levenshtein_distance}")
```

#### 5. Empty or Identical Files

```python
from redlines import Redlines

# Empty files
diff = Redlines("", "")
stats = diff.stats()
assert stats.total_changes == 0
assert stats.change_ratio == 0.0

# Identical files
diff = Redlines("Hello world", "Hello world")
stats = diff.stats()
assert stats.total_changes == 0
# CLI exit code will be 1 (no changes)
```

### Defensive Programming Pattern

```python
from pathlib import Path
from redlines import Redlines
import json

def safe_compare_files(file1: str, file2: str) -> dict:
    """Safely compare two files with comprehensive error handling."""
    try:
        # Validate files exist
        path1, path2 = Path(file1), Path(file2)
        if not path1.exists():
            return {"error": f"File not found: {file1}"}
        if not path2.exists():
            return {"error": f"File not found: {file2}"}

        # Read files
        try:
            source = path1.read_text(encoding="utf-8")
            test = path2.read_text(encoding="utf-8")
        except UnicodeDecodeError as e:
            return {"error": f"Encoding error: {e}"}

        # Compare
        diff = Redlines(source, test)
        stats = diff.stats()

        return {
            "success": True,
            "file1": file1,
            "file2": file2,
            "total_changes": stats.total_changes,
            "change_ratio": stats.change_ratio,
            "has_changes": stats.total_changes > 0
        }

    except Exception as e:
        return {"error": f"Unexpected error: {e}"}

# Usage
result = safe_compare_files("old.txt", "new.txt")
if "error" in result:
    print(f"Error: {result['error']}")
else:
    print(f"Changes: {result['total_changes']}")
```

---

## Performance Guidelines

### Processor Comparison

| Processor | Speed | Use Case | Python Version |
|-----------|-------|----------|----------------|
| **WholeDocumentProcessor** (default) | Fast (5-6x faster) | Simple documents, speed critical | 3.10+ |
| **NupunktProcessor** | Slower | Legal/technical docs, sentence-level accuracy | 3.11+ |

### Speed Benchmarks

| File Size | WholeDocument | Nupunkt | Difference |
|-----------|--------------|---------|------------|
| 400 chars | 0.19 ms | 0.40 ms | 2.1x |
| 4 KB | 0.39 ms | 2.34 ms | 6.0x |
| 40 KB | 3.85 ms | 25.14 ms | 6.5x |
| 400 KB | 37.92 ms | 241.68 ms | 6.4x |

**Throughput:**
- WholeDocumentProcessor: ~10 million chars/second
- NupunktProcessor: ~1.6 million chars/second

### When to Use Each Processor

#### Use WholeDocumentProcessor (Default) When:
- Processing large volumes of documents
- Speed is critical
- Documents are simple without complex punctuation
- Paragraph-level granularity is sufficient

#### Use NupunktProcessor When:
```python
from redlines import Redlines
from redlines.processor import NupunktProcessor

processor = NupunktProcessor()
diff = Redlines(source, test, processor=processor)
```

- Working with legal or technical documents
- Need sentence-level granularity
- Documents contain many abbreviations (Dr., Mr., etc.)
- URLs, email addresses, or decimal numbers in text
- Performance overhead (2-6x) is acceptable

### Performance Tips

1. **Reuse Redlines instance for multiple comparisons:**
```python
diff = Redlines(source)
result1 = diff.compare(test1)
result2 = diff.compare(test2)  # Faster than creating new instance
```

2. **Use CLI for one-off comparisons:**
```bash
# CLI is optimized for single comparisons
redlines json file1.txt file2.txt
```

3. **Batch processing pattern:**
```python
# Process multiple files efficiently
from concurrent.futures import ThreadPoolExecutor

def compare_file_pair(files):
    file1, file2 = files
    return Redlines(
        Path(file1).read_text(),
        Path(file2).read_text()
    ).stats()

with ThreadPoolExecutor(max_workers=4) as executor:
    results = executor.map(compare_file_pair, file_pairs)
```

---

## Integration Examples

### Example 1: Pre-commit Hook

```bash
#!/bin/bash
# .git/hooks/pre-commit

# Compare staged files with HEAD
for file in $(git diff --cached --name-only --diff-filter=M); do
    if [ -f "$file" ]; then
        # Get old version
        git show HEAD:"$file" > /tmp/old_version

        # Compare with new version
        if ! redlines stats /tmp/old_version "$file" --quiet > /dev/null; then
            echo "Error comparing $file"
            exit 1
        fi

        echo "✓ $file: Changes validated"
        rm /tmp/old_version
    fi
done

exit 0
```

### Example 2: CI/CD Check

```yaml
# .github/workflows/check-docs.yml
name: Check Documentation Changes

on: [pull_request]

jobs:
  check-docs:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Install redlines
        run: pip install redlines

      - name: Check README changes
        run: |
          git show main:README.md > old_readme.md
          if redlines stats old_readme.md README.md --quiet; then
            echo "README has changes"
            redlines markdown old_readme.md README.md --markdown-style ghfm >> $GITHUB_STEP_SUMMARY
          else
            echo "README unchanged"
          fi
```

### Example 3: Batch Report Generator

```python
#!/usr/bin/env python3
"""Generate HTML report comparing two directories."""

from pathlib import Path
from redlines import Redlines
import json

def generate_report(dir1: Path, dir2: Path, output: Path):
    """Generate HTML diff report for all files in two directories."""

    results = []
    for file1 in sorted(dir1.glob("**/*.txt")):
        file2 = dir2 / file1.relative_to(dir1)
        if not file2.exists():
            continue

        diff = Redlines(
            file1.read_text(),
            file2.read_text(),
            markdown_style="none"
        )
        stats = diff.stats()

        if stats.total_changes > 0:
            results.append({
                "file": str(file1.relative_to(dir1)),
                "stats": {
                    "changes": stats.total_changes,
                    "ratio": f"{stats.change_ratio:.1%}",
                    "added": stats.chars_added,
                    "deleted": stats.chars_deleted,
                },
                "diff": diff.output_markdown
            })

    # Generate HTML
    html = f"""<!DOCTYPE html>
<html>
<head>
    <title>Diff Report</title>
    <style>
        body {{ font-family: monospace; max-width: 1200px; margin: 0 auto; padding: 20px; }}
        .file {{ margin: 30px 0; border: 1px solid #ccc; padding: 20px; }}
        .stats {{ background: #f5f5f5; padding: 10px; margin-bottom: 20px; }}
        del {{ color: red; text-decoration: line-through; }}
        ins {{ color: green; text-decoration: underline; }}
    </style>
</head>
<body>
    <h1>Diff Report</h1>
    <p>Found {len(results)} files with changes</p>
"""

    for result in results:
        html += f"""
    <div class="file">
        <h2>{result['file']}</h2>
        <div class="stats">
            <strong>Changes:</strong> {result['stats']['changes']} |
            <strong>Ratio:</strong> {result['stats']['ratio']} |
            <strong>Added:</strong> {result['stats']['added']} chars |
            <strong>Deleted:</strong> {result['stats']['deleted']} chars
        </div>
        <div class="diff">{result['diff']}</div>
    </div>
"""

    html += """
</body>
</html>
"""

    output.write_text(html)
    print(f"Report generated: {output}")

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 4:
        print("Usage: generate_report.py <dir1> <dir2> <output.html>")
        sys.exit(1)

    generate_report(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
```

### Example 4: Test Suite Integration

```python
import pytest
from redlines import Redlines

def test_function_preserves_behavior():
    """Test that refactored code produces same output."""
    # Original implementation output
    original_output = "Hello World"

    # New implementation output
    new_output = my_refactored_function()

    # Compare
    diff = Redlines(original_output, new_output)
    stats = diff.stats()

    # Assert no changes
    assert stats.total_changes == 0, f"Output changed: {diff.output_markdown}"

def test_documentation_completeness():
    """Ensure all API changes are documented."""
    old_docs = Path("docs/api_v1.md").read_text()
    new_docs = Path("docs/api_v2.md").read_text()

    diff = Redlines(old_docs, new_docs)
    stats = diff.stats()

    # Ensure significant documentation updates
    assert stats.change_ratio > 0.05, "API changed but docs not updated enough"
```

### Example 5: Document Change Tracker

```python
#!/usr/bin/env python3
"""Track document changes over time."""

import json
from pathlib import Path
from datetime import datetime
from redlines import Redlines

class DocumentTracker:
    def __init__(self, storage_dir: Path):
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(exist_ok=True)
        self.history_file = storage_dir / "history.json"
        self.history = self._load_history()

    def _load_history(self):
        if self.history_file.exists():
            return json.loads(self.history_file.read_text())
        return {"documents": {}}

    def _save_history(self):
        self.history_file.write_text(json.dumps(self.history, indent=2))

    def track_change(self, doc_name: str, content: str):
        """Track a change to a document."""
        doc_history = self.history["documents"].setdefault(doc_name, {
            "versions": [],
            "total_changes": 0
        })

        # Get previous version
        versions = doc_history["versions"]
        if versions:
            prev_version = (self.storage_dir / versions[-1]["file"]).read_text()

            # Compare
            diff = Redlines(prev_version, content)
            stats = diff.stats()

            if stats.total_changes == 0:
                print(f"{doc_name}: No changes")
                return

            # Record change
            version_file = f"{doc_name}_{len(versions)}.txt"
            (self.storage_dir / version_file).write_text(content)

            versions.append({
                "file": version_file,
                "timestamp": datetime.now().isoformat(),
                "changes": stats.total_changes,
                "change_ratio": stats.change_ratio,
                "chars_net_change": stats.chars_net_change
            })

            doc_history["total_changes"] += stats.total_changes
            print(f"{doc_name}: {stats.total_changes} changes ({stats.change_ratio:.1%})")
        else:
            # First version
            version_file = f"{doc_name}_0.txt"
            (self.storage_dir / version_file).write_text(content)
            versions.append({
                "file": version_file,
                "timestamp": datetime.now().isoformat(),
                "changes": 0,
                "change_ratio": 0.0,
                "chars_net_change": 0
            })
            print(f"{doc_name}: Initial version tracked")

        self._save_history()

    def get_diff(self, doc_name: str, version1: int, version2: int) -> str:
        """Get diff between two versions."""
        versions = self.history["documents"][doc_name]["versions"]

        content1 = (self.storage_dir / versions[version1]["file"]).read_text()
        content2 = (self.storage_dir / versions[version2]["file"]).read_text()

        diff = Redlines(content1, content2)
        return diff.output_markdown

# Usage
tracker = DocumentTracker(Path(".document_history"))
tracker.track_change("README.md", Path("README.md").read_text())
```

---

## Additional Resources

- **Full Documentation:** [https://houfu.github.io/redlines](https://houfu.github.io/redlines)
- **GitHub Repository:** [https://github.com/houfu/redlines](https://github.com/houfu/redlines)
- **Example Scripts:** [examples/](examples/) directory
- **Demo Project:** [redlines-textual](https://github.com/houfu/redlines-textual)

---

## Quick Reference Card

```bash
# CLI - Command-less (recommended for agents)
redlines "source" "test"                    # JSON output
redlines --pretty "source" "test"           # Pretty JSON
redlines file1.txt file2.txt                # Works with files

# CLI - Traditional commands (for specific output formats)
redlines text SOURCE TEST                   # Rich terminal display
redlines json SOURCE TEST --pretty          # JSON with formatting
redlines markdown SOURCE TEST -m ghfm       # Markdown output
redlines stats SOURCE TEST --quiet          # Statistics only
```

```python
# Python API
from redlines import Redlines

# Compare
diff = Redlines(source, test)

# Get changes
all_changes = diff.changes
insertions = diff.get_changes(operation="insert")

# Get stats
stats = diff.stats()

# Output
markdown = diff.output_markdown
json_str = diff.output_json(pretty=True)
rich_text = diff.output_rich
```

---

**Last Updated:** 2025-10-22
**Version:** 0.6.0+
**Python:** 3.10+
