"""Regenerate the renderer goldens of the five small renderer cases (#178 to #182).

Run this only when a change is intentional, then read the diff::

    uv run python tests/renderer_cases/regenerate.py

Each case directory holds a ``source.md`` and a ``test.md``. The goldens of
each renderer go under the case's ``expected/`` directory, one file per
output; every renderer PR of M3 appends its own outputs here rather than
reordering, because the four of them are developed side by side.

Every comparison is made the way the sample pair's are
(``tests/corpus/sample_pair/regenerate.py``): the format and the profile are
named, ``markdown`` for both, and the similarity backend is pinned to
`GOLDEN_BACKEND`, because ``"auto"`` resolves differently on CI legs with and
without the ``[fuzzy]`` extra, and the backend is written into the
configuration line of the HTML header. Goldens are written with
``newline=""``, as the tests read them.

**The HTML fragments** (#182, ADR-0038): ``expected/changes.html`` is
`redlines.comparison.Comparison.output_html` and ``expected/annotated.html``
is ``output_annotated(syntax="html")``.
"""

from __future__ import annotations

from pathlib import Path

from redlines.alignment import AlignmentConfig
from redlines.comparison import Comparison, compare

CASES_DIR = Path(__file__).parent

CASES: tuple[str, ...] = (
    "four_kinds",
    "moved_neighbour",
    "nested_move",
    "trailing_insert",
    "hostile",
)

GOLDEN_BACKEND: str = "difflib"
"""The similarity backend every renderer golden is generated under."""

GOLDEN_ALIGNMENT: AlignmentConfig = AlignmentConfig(similarity=GOLDEN_BACKEND)


def read_case(name: str) -> tuple[str, str]:
    """Return a case's two documents, with their bytes' line endings kept."""
    directory = CASES_DIR / name
    with open(directory / "source.md", encoding="utf-8", newline="") as source:
        with open(directory / "test.md", encoding="utf-8", newline="") as test:
            return source.read(), test.read()


def build_comparison(name: str) -> Comparison:
    """Compare one case as its goldens are generated: markdown, named, under difflib."""
    source, test = read_case(name)
    return compare(
        source, test, format="markdown", profile="markdown", alignment=GOLDEN_ALIGNMENT
    )


def html_golden_paths(name: str) -> tuple[Path, Path]:
    """Return the change-list and document-view golden paths for one case (#182)."""
    expected = CASES_DIR / name / "expected"
    return expected / "changes.html", expected / "annotated.html"


def regenerate_html() -> None:
    """Write both HTML fragments of every case, with ``newline=""`` (#182)."""
    for name in CASES:
        comparison = build_comparison(name)
        changes, annotated = html_golden_paths(name)
        changes.parent.mkdir(exist_ok=True)
        for target, text in (
            (changes, comparison.output_html()),
            (annotated, comparison.output_annotated(syntax="html")),
        ):
            target.write_text(text, encoding="utf-8", newline="")
            print(f"wrote {target.relative_to(CASES_DIR.parent.parent)}")


def regenerate() -> None:
    regenerate_html()


if __name__ == "__main__":
    regenerate()
