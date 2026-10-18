"""The README and course strings, pinned to what 0.6.2 printed.

The M3 exit requires the README and course example strings to stay byte-identical
to 0.6.2 (ROADMAP, M3): the example every user copies first, and the one the
DeepLearning.AI course (Lesson 6) teaches. The goldens cover those pairs only with
``markdown_style`` passed explicitly, and nothing executes ``README.md`` at all.
This module closes both gaps.

- Every ``python`` fenced block of ``README.md`` is run in a namespace of its
  own and must finish without an error. The blocks assert some output
  themselves, so this also keeps the README honest about what it shows. A fence
  marked ``python no-run`` is the one way out, for an example that cannot run as
  printed; ``tests/helpers/readme_fences.py`` has the rules for finding fences.
- The expected strings of the quickstart's fox example, in the default style and
  in ``markdown_style="none"``, are written out below. They are the bytes 0.6.2
  produced, not a copy of what the code under test prints: the same strings come
  out of the v0.6.2 package itself (``git archive v0.6.2 redlines``, imported from
  a scratch directory) on the same inputs.
- The course example (``tests/corpus/course_lesson6``, ``source.txt`` against
  ``test.txt``, default style) must equal ``golden/red_green.md`` read without
  newline translation, and equal the literal written out below. The golden is
  pinned by SHA-256 in ``tests/test_v062_contract_frozen.py``.

Nothing here may be "updated" to follow a change in the output: a difference is
a compatibility break (ADR-0003).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from redlines import Redlines
from tests.helpers import readme_fences
from tests.helpers.readme_fences import python_blocks, run_block, skip_reason

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
COURSE_DIR = Path(__file__).resolve().parent / "corpus" / "course_lesson6"


def read_exact(path: Path) -> str:
    """Read a file without any newline translation."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


BLOCKS = python_blocks(README.read_text(encoding="utf-8"))


def test_python_blocks_takes_python_fences_and_nothing_else() -> None:
    markdown = "\n".join(
        [
            "# A title",
            "```bash",
            "from redlines import Redlines  # looks like Python, is a shell block",
            "```",
            "Some prose.",
            "```python",
            "first = 1",
            "```",
            "  ```python title='attributes after the language are ignored'",
            "  second = 2",
            "  ```",
            "```",
            "no language, so not Python",
            "```",
            "```python",
            "third = 3  # the fence is never closed",
        ]
    )

    assert python_blocks(markdown) == [
        "first = 1\n",
        "second = 2\n",
        "third = 3  # the fence is never closed\n",
    ]


def test_python_blocks_dedents_a_fence_inside_a_list_item() -> None:
    markdown = "\n".join(
        [
            "1. A step:",
            "",
            "   ```python",
            "   if True:",
            "       nested = 1",
            "   ```",
        ]
    )

    assert python_blocks(markdown) == ["if True:\n    nested = 1\n"]


def test_python_blocks_follows_the_fence_rules_of_commonmark() -> None:
    markdown = "\n".join(
        [
            "~~~python",
            "tilde = 1",
            "~~~",
            "````markdown",
            "```python",
            "inside_a_longer_fence = 2",
            "```",
            "````",
            "```python",
            "after = 3",
            "```",
        ]
    )

    assert python_blocks(markdown) == ["tilde = 1\n", "after = 3\n"]


def test_a_no_run_fence_is_skipped() -> None:
    assert python_blocks("```python no-run\nundefined_name\n```\n") == []


def test_skip_reason_names_a_missing_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readme_fences, "NUPUNKT_AVAILABLE", False)

    assert skip_reason("processor = NupunktProcessor()") is not None
    assert skip_reason("Redlines('a', 'b')") is None


def test_readme_has_python_blocks() -> None:
    """If the README stops having runnable examples the tests below would
    parametrise over nothing and be skipped without a word."""
    assert BLOCKS, (
        "README.md has no runnable ```python fenced block. Its examples are what "
        "this module runs; if that is deliberate, change this module with it."
    )


@pytest.mark.parametrize(
    "index", range(len(BLOCKS)), ids=lambda index: f"block-{index + 1}"
)
def test_readme_python_block_runs(index: int) -> None:
    code = BLOCKS[index]
    reason = skip_reason(code)
    if reason is not None:
        pytest.skip(reason)

    run_block(index, code)


# The quickstart example (README.md, "Quick Start" and "Basic comparison"; also
# tests/corpus/readme_quickstart). The expected strings are what 0.6.2 printed.
FOX_SOURCE = "The quick brown fox jumps over the lazy dog."
FOX_TEST = "The quick brown fox walks past the lazy dog."
FOX_NONE = (
    "The quick brown fox <del>jumps over </del><ins>walks past </ins>the lazy dog."
)
FOX_DEFAULT = (
    "The quick brown fox "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>jumps over </span>"
    "<span style='color:green;font-weight:700;'>walks past </span>"
    "the lazy dog."
)


def test_quickstart_fox_in_the_default_style() -> None:
    assert Redlines(FOX_SOURCE, FOX_TEST).output_markdown == FOX_DEFAULT
    # "Multiple comparisons with one source" in the README, without a style.
    assert Redlines(FOX_SOURCE).compare(FOX_TEST) == FOX_DEFAULT


def test_quickstart_fox_with_markdown_style_none() -> None:
    redline = Redlines(FOX_SOURCE, FOX_TEST, markdown_style="none")

    assert redline.output_markdown == FOX_NONE


# Lesson 6 of the DeepLearning.AI course "ChatGPT Prompt Engineering for
# Developers", linked from the README: a proofreading example, default style.
# Written out as 0.6.2 printed it, one fragment per run of text and per span, so
# that the six edits can be read off. The sentence separators in the unchanged
# text are the double spaces of the source (they survive in `equal` runs).
COURSE_DEFAULT = (
    "Got this for my daughter for her birthday "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>cuz </span>"
    "<span style='color:green;font-weight:700;'>because </span>"
    "she keeps taking mine from my room.  Yes, adults also like "
    "pandas too.  She takes it everywhere with her, and it's super "
    "soft and cute.  "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>One </span>"
    "<span style='color:green;font-weight:700;'>However, one </span>"
    "of the ears is a bit lower than the other, and I don't think "
    "that was designed to be asymmetrical. "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>It's </span>"
    "<span style='color:green;font-weight:700;'>Additionally, it's </span>"
    "a bit small for what I paid for "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>it though. </span>"
    "<span style='color:green;font-weight:700;'>it. </span>"
    "I "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>think </span>"
    "<span style='color:green;font-weight:700;'>believe </span>"
    "there might be other options that are bigger for the same "
    "price.  "
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>It </span>"
    "<span style='color:green;font-weight:700;'>On the positive side, it </span>"
    "arrived a day earlier than expected, so I got to play with it "
    "myself before I gave it to my daughter."
)


def test_course_example_is_byte_identical_to_0_6_2() -> None:
    source = read_exact(COURSE_DIR / "source.txt")
    test = read_exact(COURSE_DIR / "test.txt")
    golden = read_exact(COURSE_DIR / "golden" / "red_green.md")

    # The two pins agree with each other before either is held against the code.
    assert COURSE_DEFAULT == golden

    # No markdown_style argument: the default is the style the course relies on.
    output = Redlines(source, test).output_markdown

    assert output == golden
    assert output == COURSE_DEFAULT
