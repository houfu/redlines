"""The runnable Python in a markdown file's fenced code blocks.

Two tests run the README's examples. ``tests/test_readme_strings.py`` checks that
they run and that the quickstart prints what 0.6.2 printed;
``tests/test_quick_path_is_silent.py`` runs them again and fails on a warning.
This module is the one place that decides what "the README's Python" is and how a
block is run, so the two cannot disagree about it.

Which fences count. A fence opens on a line that starts, after any indentation,
with three or more backticks or tildes, and closes on a line of the same
character, at least as long, with nothing else on it (CommonMark). It is Python
when the first word of its info string is ``python``. A fence of another language,
a fence with no language, and a fence inside a longer one are not. The body is
dedented as a whole (``textwrap.dedent``), so a fence inside a list item runs as
written.

Opting out. A fence whose info string has the word ``no-run`` after the language
is skipped::

    ```python no-run
    Redlines(old_text, new_text)  # placeholders: the prose defines them
    ```

Use it for an example that cannot run as printed, because it names files that
are not there or variables the prose defines. Nothing in the README uses it
today, so every example in it is run.
"""

from __future__ import annotations

import contextlib
import io
import textwrap
from typing import Final

from redlines.processor import NUPUNKT_AVAILABLE

NO_RUN: Final = "no-run"
"""The word that, after ``python`` in an info string, excludes a fence."""

BLOCK_FILENAME_PREFIX: Final = "<README.md python block "
"""A block is compiled under ``<README.md python block N>``, N counting from 1.
A warning that ``stacklevel`` aims at the block's caller carries that name."""


def _opening_run(stripped: str) -> str:
    """The run of backticks or tildes that opens a fence on this line, or ''."""
    for character in "`~":
        run = len(stripped) - len(stripped.lstrip(character))
        if run >= 3:
            # After backticks the info string cannot contain a backtick, which
            # keeps ```code``` at the start of a paragraph from opening a fence.
            if character == "`" and "`" in stripped[run:]:
                return ""
            return character * run
    return ""


def _closes(stripped: str, opening_run: str) -> bool:
    return len(stripped) >= len(opening_run) and set(stripped) == {opening_run[0]}


def python_blocks(markdown: str) -> list[str]:
    """The bodies of the runnable ``python`` fences of a markdown text, in order,
    each dedented and ending in a newline.

    A fence still open at the end of the text counts, as it does in CommonMark.
    """
    blocks: list[str] = []
    opening_run = ""  # the run that opened the fence we are inside; '' outside one
    keep = False  # whether that fence is a runnable python fence
    lines: list[str] = []
    for line in markdown.splitlines():
        stripped = line.strip()
        if not opening_run:
            opening_run = _opening_run(stripped)
            if opening_run:
                info = stripped[len(opening_run) :].split()
                keep = bool(info) and info[0] == "python" and NO_RUN not in info[1:]
                lines = []
        elif _closes(stripped, opening_run):
            if keep:
                blocks.append(textwrap.dedent("\n".join(lines)) + "\n")
            opening_run = ""
        elif keep:
            lines.append(line)
    if opening_run and keep:
        blocks.append(textwrap.dedent("\n".join(lines)) + "\n")
    return blocks


def skip_reason(code: str) -> str | None:
    """Why a block cannot run in this environment, or None when it can.

    The README's blocks need nothing beyond the core package, except the one that
    builds a ``NupunktProcessor``, which needs the ``nupunkt`` extra (Python 3.11
    and later). A block that needs another extra is added here.
    """
    if "nupunkt" in code.lower() and not NUPUNKT_AVAILABLE:
        return "this README block needs the nupunkt extra, which is not installed"
    return None


def run_block(index: int, code: str) -> None:
    """Run one block in a namespace of its own, with standard output captured.

    ``index`` counts from 0, as the blocks do in the list ``python_blocks``
    returns. Nothing carries over from one block to the next: an example has to
    work as written, not because an earlier one imported something for it. An
    error in the block propagates.
    """
    compiled = compile(code, f"{BLOCK_FILENAME_PREFIX}{index + 1}>", "exec")
    with contextlib.redirect_stdout(io.StringIO()):
        exec(compiled, {"__name__": "readme_block"})
