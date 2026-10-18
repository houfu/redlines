"""Regenerate the renderer cases' goldens (ADR-0037; #179 to #182).

Run this only for a change that is intended, then read the diff::

    uv run python tests/renderer_cases/regenerate.py

Each directory here holds a small markdown pair, ``source.md`` and
``test.md``, that pins one thing the in-place renderers must get right
(#178): ``four_kinds`` has one change of each common kind, ``moved_neighbour``
a move beside a block that stayed, ``nested_move`` a clause that moved out of
a moved clause, ``trailing_insert`` changes at the end of a document, and
``hostile`` document text that looks like markup. The goldens sit beside the
inputs, one file per output, named as the issues name them.

Every golden is generated under ``similarity="difflib"``, the
``GOLDEN_BACKEND`` of ``tests/corpus/sample_pair/regenerate.py``, so one
golden holds on every CI leg, and is written with ``newline=""``, so the bytes
on disk are the bytes the renderer returned. Each renderer appends its own
rows to `GOLDENS` (every case) or `CASE_GOLDENS` (one case) and reorders
none, because the renderers are developed in parallel. What freezes a golden
is houfu's reading of it against its inputs, once, not this script; the tests
render each case themselves rather than calling it.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from types import MappingProxyType

from redlines.alignment import AlignmentConfig
from redlines.comparison import Comparison, compare
from redlines.enums import MarkdownStyle

CASES_DIR: Path = Path(__file__).parent

GOLDEN_ALIGNMENT: AlignmentConfig = AlignmentConfig(similarity="difflib")
"""`redlines.alignment.DEFAULT_ALIGNMENT` with the backend pinned, as the sample pair's goldens are."""

MARKDOWN_STYLES: tuple[str, ...] = (
    *(style.value for style in MarkdownStyle),
    "custom_css",
)
"""Every style `redlines.comparison.Comparison.output_markdown` draws, in
`redlines.enums.MarkdownStyle` order, then ``custom_css`` with its default
classes."""

Golden = tuple[str, Callable[[Comparison], str]]
"""A golden's file name in its case directory, and what draws it."""


def _markdown(style: str) -> Callable[[Comparison], str]:
    """The ``output_markdown`` rendering in one style, as a golden's callable."""

    def render(comparison: Comparison) -> str:
        return comparison.output_markdown(style)

    return render


def dump_rich(comparison: Comparison) -> str:
    """The ``output_rich`` golden: ``{"plain": …, "spans": [[start, end, style], …]}``.

    ``(plain, spans)`` rather than ``Text.markup``, which churns on rich
    upgrades (ADR-0037). JSON with one span to a line, so a diff shows which
    run changed, and a trailing newline; the same form as the sample pair's.

    :param comparison: the comparison to render.
    :return: the JSON text.
    """
    text = comparison.output_rich()
    spans = [[span.start, span.end, str(span.style)] for span in text.spans]
    rows = "".join(
        f"    {json.dumps(span, ensure_ascii=False)}{',' if index < len(spans) - 1 else ''}\n"
        for index, span in enumerate(spans)
    )
    plain = json.dumps(text.plain, ensure_ascii=False)
    return f'{{\n  "plain": {plain},\n  "spans": [\n{rows}  ]\n}}\n'


GOLDENS: tuple[Golden, ...] = (
    # Comparison.output_markdown (#179): the none style on every case. Four of
    # them pin placement, the legacy picture of a nested move and the absence
    # of escaping, not styling.
    ("markdown.none.md", _markdown("none")),
    # Comparison.output_annotated (#181): both CriticMarkup syntaxes on every case.
    (
        "annotated.markdown.md",
        lambda comparison: comparison.output_annotated(syntax="markdown"),
    ),
    (
        "annotated.text.txt",
        lambda comparison: comparison.output_annotated(syntax="text"),
    ),
)
"""The goldens every case has."""

CASE_GOLDENS: Mapping[str, tuple[Golden, ...]] = MappingProxyType(
    {
        "four_kinds": (
            # Comparison.output_markdown (#179): the other six styles, on the
            # case that is small enough to read by eye.
            *(
                (f"markdown.{style}.md", _markdown(style))
                for style in MARKDOWN_STYLES
                if style != "none"
            ),
            # Comparison.output_rich (#180).
            ("rich.json", dump_rich),
        ),
    }
)
"""The goldens only one case has, by case name."""


def case_dirs() -> list[Path]:
    """Every case directory: each subdirectory holding a ``source.md``, sorted."""
    return sorted(
        directory
        for directory in CASES_DIR.iterdir()
        if (directory / "source.md").is_file()
    )


def build_comparison(case: Path) -> Comparison:
    """Compare one case as markdown, under `GOLDEN_ALIGNMENT`, reading both sides exactly as committed.

    :param case: one of `case_dirs`.
    :return: the comparison every golden of the case is drawn from.
    """
    with open(case / "source.md", encoding="utf-8", newline="") as source:
        with open(case / "test.md", encoding="utf-8", newline="") as test:
            return compare(
                source.read(),
                test.read(),
                format="markdown",
                alignment=GOLDEN_ALIGNMENT,
            )


def regenerate() -> None:
    """Write every case's goldens into its directory, byte for byte."""
    for case in case_dirs():
        comparison = build_comparison(case)
        for name, render in (*GOLDENS, *CASE_GOLDENS.get(case.name, ())):
            target = case / name
            target.write_text(render(comparison), encoding="utf-8", newline="")
            print(f"wrote {target.relative_to(CASES_DIR.parent.parent)}")


if __name__ == "__main__":
    regenerate()
