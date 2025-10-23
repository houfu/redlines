# Redlines Examples

This directory contains practical, runnable examples demonstrating how to use redlines in various scenarios.

## Quick Start

All examples are standalone Python scripts that can be run directly:

```bash
# Make scripts executable (Unix/Mac)
chmod +x *.py

# Run any example
python compare_files.py file1.txt file2.txt
```

## Available Examples

### 1. `compare_files.py` - Basic File Comparison

Compare two text files and display statistics and diff output.

**Usage:**
```bash
python compare_files.py old_version.txt new_version.txt
```

**Features:**
- File validation and error handling
- Comprehensive statistics display
- Markdown diff output
- UTF-8 encoding support

**Example output:**
```
Comparing: old.txt vs new.txt
============================================================

Statistics:
  Total changes: 5
  Insertions: 2
  Deletions: 1
  Replacements: 2
  Change ratio: 15.3%
  Characters added: 45
  Characters deleted: 38
  Net change: +7 characters

Diff (markdown):
------------------------------------------------------------
The quick brown fox <del>jumps over</del><ins>walks past</ins> the lazy dog.
```

---

### 2. `batch_diff.py` - Batch Directory Comparison

Compare all matching files in two directories and generate a summary report.

**Usage:**
```bash
# Compare all .txt files
python batch_diff.py old_dir/ new_dir/

# Compare specific pattern
python batch_diff.py old_dir/ new_dir/ '*.md'
```

**Features:**
- Recursive directory comparison
- Pattern-based file filtering
- Summary statistics
- Handles missing files
- Error reporting

**Example output:**
```
Batch Comparison Results
================================================================================

Summary:
  Total files: 15
  Compared: 12
  With changes: 8
  Errors: 0
  Missing: 3

Files with changes:
--------------------------------------------------------------------------------
File                                     Changes    Ratio      Net Change
--------------------------------------------------------------------------------
docs/api.md                              23         8.5%       +127
docs/guide.md                            45         12.3%      -89
README.md                                7          3.2%       +45
```

---

### 3. `generate_report.py` - HTML Diff Report Generator

Generate a beautiful HTML report comparing two directories with visual diffs.

**Usage:**
```bash
# Generate HTML report
python generate_report.py old_dir/ new_dir/ report.html

# With custom pattern
python generate_report.py old_docs/ new_docs/ docs_report.html '*.md'
```

**Features:**
- Beautiful, responsive HTML output
- Color-coded diffs (red=deletions, green=insertions)
- Summary statistics
- File-by-file breakdown
- Timestamp and metadata
- Ready for sharing or archiving

**Output:**
- Professional HTML report with CSS styling
- Expandable file sections
- Summary dashboard
- Mobile-friendly layout

**Open the report:**
```bash
open report.html  # Mac
xdg-open report.html  # Linux
start report.html  # Windows
```

---

### 4. `pre_commit_hook.sh` - Git Pre-commit Hook

Validate file changes before committing using redlines.

**Installation:**
```bash
# Copy to git hooks
cp pre_commit_hook.sh .git/hooks/pre-commit

# Make executable
chmod +x .git/hooks/pre-commit
```

**Features:**
- Compares staged files with HEAD
- Validates changes before commit
- Colored terminal output
- Skips binary files
- Optional change threshold enforcement

**Example output:**
```
Running pre-commit checks with redlines...

Checking staged files...
----------------------------------------
△ src/main.py - 12 changes (8.5%)
✓ README.md - no changes
+ docs/new-feature.md - new file
----------------------------------------

Summary:
  Files checked: 3
  Files with changes: 1
  Total changes: 12

✓ Pre-commit checks passed
```

---

### 5. `ci_check.py` - CI/CD Integration

Check documentation changes between git branches for CI/CD pipelines.

**Usage:**
```bash
# Compare against main branch
python ci_check.py main

# Check only markdown files
python ci_check.py main "*.md"

# Check docs directory
python ci_check.py develop "docs/**/*.txt"
```

**Features:**
- Git integration
- GitHub Actions compatible
- Automatic summary generation
- Branch comparison
- Pattern-based filtering
- CI-friendly exit codes

**GitHub Actions Integration:**
```yaml
# .github/workflows/check-docs.yml
- name: Check Documentation Changes
  run: |
    pip install redlines
    python examples/ci_check.py main "*.md"
```

**Example output:**
```
======================================================================
DOCUMENTATION CHANGE REPORT
======================================================================

📊 Summary:
  Files analyzed: 8
  Files with changes: 5
  Total changes: 127

📝 Modified files with changes (5):
  △ README.md
      Changes: 23 (8.5%)
      +15 -8 ↻0
      Net: +7 characters

✨ New files (1):
  + docs/new-guide.md

✓ Unchanged files (2):
  ✓ LICENSE.md
  ✓ CONTRIBUTING.md
```

---

## Common Patterns

### Pattern 1: Check if Two Files Are Identical

```python
from redlines import Redlines

diff = Redlines(file1_content, file2_content)
if diff.stats().total_changes == 0:
    print("Files are identical")
else:
    print(f"Files differ: {diff.stats().total_changes} changes")
```

### Pattern 2: Filter Specific Change Types

```python
from redlines import Redlines

diff = Redlines(old, new)

# Get only insertions
insertions = diff.get_changes(operation="insert")
for change in insertions:
    print(f"Added: {change.test_text}")

# Get only deletions
deletions = diff.get_changes(operation="delete")
for change in deletions:
    print(f"Removed: {change.source_text}")
```

### Pattern 3: Generate JSON for Machine Processing

```python
import json
from redlines import Redlines

diff = Redlines(old, new)
data = json.loads(diff.output_json(pretty=True))

# Process changes programmatically
for change in data["changes"]:
    print(f"{change['type']}: {change.get('source_text')} → {change.get('test_text')}")
```

### Pattern 4: Calculate Change Metrics

```python
from redlines import Redlines

diff = Redlines(old, new)
stats = diff.stats()

print(f"Change ratio: {stats.change_ratio:.1%}")
print(f"Net change: {stats.chars_net_change:+d} characters")
print(f"Average change size: {stats.average_change_length:.1f} chars")
```

---

## Requirements

All examples require:
- Python 3.10+
- redlines (`pip install redlines`)

Optional dependencies:
- For Levenshtein distance: `pip install redlines[levenshtein]`
- For advanced tokenization: `pip install redlines[nupunkt]` (Python 3.11+)

---

## Creating Test Data

To test the examples, you can create sample files:

```bash
# Create test files
echo "The quick brown fox jumps over the lazy dog." > old.txt
echo "The quick brown fox walks past the lazy dog." > new.txt

# Run comparison
python compare_files.py old.txt new.txt
```

Or create test directories:

```bash
# Create test directories
mkdir -p test_old test_new

echo "Version 1 of document" > test_old/doc1.txt
echo "Version 2 of document" > test_new/doc1.txt

echo "Another document here" > test_old/doc2.txt
echo "Another document here with changes" > test_new/doc2.txt

# Run batch comparison
python batch_diff.py test_old/ test_new/
```

---

## Troubleshooting

### FileNotFoundError
```
Error: [Errno 2] No such file or directory: 'file.txt'
```
**Solution:** Check that file paths are correct and files exist.

### UnicodeDecodeError
```
Encoding error: 'utf-8' codec can't decode byte...
```
**Solution:** Convert files to UTF-8 encoding:
```bash
iconv -f ISO-8859-1 -t UTF-8 file.txt > file_utf8.txt
```

### Permission Denied
```
Error: Failed to read file: Permission denied
```
**Solution:** Check file permissions:
```bash
chmod +r file.txt
```

---

## Contributing

Have an example you'd like to add? Contributions are welcome!

1. Create a new Python script with clear documentation
2. Add usage examples and expected output
3. Test thoroughly
4. Update this README with your example
5. Submit a pull request

---

## License

These examples are part of the redlines project and are licensed under the MIT License.

See the main [LICENSE](../LICENSE.txt) file for details.
