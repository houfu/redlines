---
title: Quickstart
description: Install redlines and compare two texts from the CLI or from Python.
sidebar:
  order: 1
---

`redlines` compares two strings and produces structured output showing their
differences. Changes are represented with strike-throughs and highlights, in the
manner of Microsoft Word's track changes, and the output carries change
information, positions and statistics for programmatic use.

## Install

```bash
pip install redlines
```

Python 3.10 to 3.14 are supported.

### Optional extras

| Extra | Install | What it adds |
|---|---|---|
| `pdf` | `pip install redlines[pdf]` | Comparing PDF files |
| `nupunkt` | `pip install redlines[nupunkt]` | Sentence boundary detection that handles abbreviations, citations and URLs (Python 3.11+) |
| `levenshtein` | `pip install redlines[levenshtein]` | Levenshtein distance in the statistics |

## Compare from the command line

JSON is the default output, so a bare invocation is enough:

```bash
redlines "The quick brown fox jumps over the lazy dog." "The quick brown fox walks past the lazy dog."
```

Files work the same way, and `--pretty` makes the JSON readable:

```bash
redlines --pretty old_version.txt new_version.txt
```

## Compare from Python

```python
from redlines import Redlines

test = Redlines(
    "The quick brown fox jumps over the lazy dog.",
    "The quick brown fox walks past the lazy dog.",
    markdown_style="none",
)
print(test.output_markdown)
# The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog.
```

Other output formats are available on the same object: `output_json` for
structured changes and statistics, `output_rich` for terminal display, and
`compare(markdown_style=...)` for the six markdown styles.

## Where to go next

- The [agent integration guide](/redlines/guides/agent-guide/) covers invocation
  from agents and automation, the JSON structure, error handling and integration
  patterns.
- The [API reference](/redlines/api/) is generated from the
  docstrings and documents every class and method.
- The [decision records](/redlines/project/adr/) explain why the library is
  shaped the way it is, and where it is going.

## Reading this site as an agent

Every page is available as plain markdown by appending `.md` to its path —
[`/guides/agent-guide.md`](/redlines/guides/agent-guide.md), for instance.
[`/llms.txt`](/redlines/llms.txt) indexes the site,
[`/llms-small.txt`](/redlines/llms-small.txt) is the usage documentation in one
file, and [`/llms-full.txt`](/redlines/llms-full.txt) adds the planning
documents and decision records.
