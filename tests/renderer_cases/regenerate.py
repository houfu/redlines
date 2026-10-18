"""Regenerate the renderer cases' goldens (ADR-0037, "Fixtures").

Run this only when a change is intentional, then read the diff::

    uv run python tests/renderer_cases/regenerate.py

Each directory here holds one markdown pair, ``source.md`` and ``test.md``,
small enough to read whole, built around what the renderers must get right:
the four change kinds, a move beside a deletion, a nested move, an insert at
the end of a section, and hostile text. For every case, the pair is compared
as markdown under `GOLDEN_ALIGNMENT`, and each entry of `GOLDENS` writes one
rendering of it into the case's directory.

The inputs are read, and the goldens written, with ``newline=""``: the files
are compared byte for byte, and ``.gitattributes`` keeps git from translating
their line endings. The tests that check the goldens compare the pairs
themselves, through the public API, rather than calling this script, so a
drift between the two is a failure rather than a silently regenerated golden.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from redlines.alignment import AlignmentConfig
from redlines.comparison import Comparison, compare

CASES_DIR = Path(__file__).parent

GOLDEN_ALIGNMENT: AlignmentConfig = AlignmentConfig(similarity="difflib")
"""The backend every renderer golden is generated under, as in
``tests/corpus/sample_pair/regenerate.py``: named rather than ``"auto"``, so one
golden is correct on every CI leg."""

# <case>/<file> <- the rendering of the case's comparison written there
GOLDENS: tuple[tuple[str, Callable[[Comparison], str]], ...] = (
    ("annotated.markdown.md", lambda comparison: comparison.output_annotated(syntax="markdown")),
    ("annotated.text.txt", lambda comparison: comparison.output_annotated(syntax="text")),
)


def case_dirs() -> tuple[Path, ...]:
    """Every case directory: each one that holds a ``source.md``, sorted."""
    return tuple(
        sorted(path for path in CASES_DIR.iterdir() if (path / "source.md").is_file())
    )


def build_comparison(case: Path) -> Comparison:
    """Compare one case's pair as markdown, under `GOLDEN_ALIGNMENT`."""
    with open(case / "source.md", encoding="utf-8", newline="") as source:
        source_text = source.read()
    with open(case / "test.md", encoding="utf-8", newline="") as test:
        test_text = test.read()
    return compare(source_text, test_text, format="markdown", alignment=GOLDEN_ALIGNMENT)


def regenerate() -> None:
    for case in case_dirs():
        comparison = build_comparison(case)
        for name, render in GOLDENS:
            target = case / name
            with open(target, "w", encoding="utf-8", newline="") as handle:
                handle.write(render(comparison))
            print(f"wrote {target.relative_to(CASES_DIR.parent.parent)}")


if __name__ == "__main__":
    regenerate()
