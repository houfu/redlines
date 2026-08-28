"""Golden-file regression tests for the corpus in tests/corpus/.

Each case directory holds a ``source.txt``/``test.txt`` input pair and one
frozen rendered output per markdown style under ``golden/``. The comparison
is byte-for-byte: these files are the M0 regression corpus (ROADMAP § M0,
PRD section 12) and are reused by M4 to prove the tree-based renderer is
byte-identical to the flat engine.

If an output change is intentional, regenerate the goldens with

    uv run python tests/corpus/regenerate_goldens.py

and review the resulting diff.
"""

from pathlib import Path

import pytest

from redlines import Redlines
from redlines.enums import MarkdownStyle

CORPUS_DIR = Path(__file__).parent / "corpus"

CASES = sorted(p.name for p in CORPUS_DIR.iterdir() if p.is_dir())

STYLES = [style.value for style in MarkdownStyle]


def read_exact(path: Path) -> str:
    """Read a corpus file without any newline translation."""
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


@pytest.mark.parametrize("style", STYLES)
@pytest.mark.parametrize("case", CASES)
def test_output_matches_golden(case: str, style: str) -> None:
    case_dir = CORPUS_DIR / case
    source = read_exact(case_dir / "source.txt")
    test = read_exact(case_dir / "test.txt")
    golden = read_exact(case_dir / "golden" / f"{style}.md")

    output = Redlines(source, test, markdown_style=style).output_markdown

    assert output == golden, (
        f"Output for corpus case {case!r} with style {style!r} no longer matches "
        f"its golden file. If this change is intentional, regenerate the goldens "
        f"with: uv run python tests/corpus/regenerate_goldens.py"
    )


@pytest.mark.parametrize("case", CASES)
def test_case_directory_is_complete(case: str) -> None:
    """A half-added case (missing inputs or goldens) must fail loudly."""
    case_dir = CORPUS_DIR / case
    missing = [
        name
        for name in ["source.txt", "test.txt"]
        + [f"golden/{style}.md" for style in STYLES]
        if not (case_dir / name).is_file()
    ]
    assert not missing, (
        f"Corpus case {case!r} is missing {missing}. Add the input files and run "
        f"uv run python tests/corpus/regenerate_goldens.py to create the goldens."
    )


def test_repetitive_schedule_reports_two_token_change() -> None:
    """The M0 exit criterion: the ~1,050-token repetitive schedule reports a
    two-token change, not a mangled wholesale replacement (needs autojunk off,
    see ADR-0010)."""
    case_dir = CORPUS_DIR / "repetitive_schedule"
    source = read_exact(case_dir / "source.txt")
    test = read_exact(case_dir / "test.txt")

    redline = Redlines(source, test)
    changes = [op for op in redline.opcodes if op[0] != "equal"]

    assert len(changes) == 1
    tag, i1, i2, j1, j2 = changes[0]
    assert tag == "replace"
    # The single change is "five thousand" -> "seven hundred": two tokens wide
    # on both sides.
    assert i2 - i1 == 2
    assert j2 - j1 == 2
