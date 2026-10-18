"""The rich renderer: the test document marked in place, in 0.6's two colours, with notes (ADR-0037).

`render_rich` lays out the view every in-place output walks
(`redlines.renderers._inplace.layout`) in the text variant, with the
`redlines.renderers._marks.RICH` set and no roles, and appends each run of it
to one `rich.text.Text` with its style:

- an insertion ``green`` and a deletion ``strike red``, 0.6's own two styles;
  a replacement is a deletion then an insertion, and a renumbered label is
  the old label deleted and the new one inserted;
- a note ``magenta``: ``moved from SRC_LABEL SRC_ADDRESS`` at the end of a
  moved block's line, and a line ``SRC_LABEL moved to TEST_LABEL
  TEST_ADDRESS`` where the block was. The tombstone stands for the moved
  block alone; its descendants are drawn at its destination;
- the document text of a heading ``bold``, combined with any mark on it
  (``bold green``, ``bold strike red``);
- everything else unstyled.

Above the document is a header line, ``T changes: N inserted, N deleted, N
modified, N moved, N renumbered``, with the counts of
`redlines.comparison.Comparison.statistics`, ``1 change`` in the singular, and
the total bold. The notices follow it in yellow, one per line and only when
true, in the order and the words of the HTML header: the filter, an exhausted
alignment budget, then each dropped item, the source's first. A blank line
separates the header from the document and each block from the next, and
nothing ends the text.

The text is built only with ``Text.append(segment, style)``, never from
markup, so document text such as ``[bold]`` stays literal, and with nothing
newer than `rich.text.Text`, its ``append``, ``plain`` and ``spans`` and plain
style strings, because the declared floor is ``rich>=13.3.5``. This is the
only renderer module that imports rich.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from rich.text import Text

from ..blocks import BlockKind
from ._inplace import Chunk, _filter_value, layout
from ._marks import RICH

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from ..comparison import Comparison

__all__: tuple[str, ...] = (
    "INSERT_STYLE",
    "DELETE_STYLE",
    "NOTE_STYLE",
    "HEADING_STYLE",
    "TOTAL_STYLE",
    "NOTICE_STYLE",
    "render_rich",
)

INSERT_STYLE: Final[str] = "green"
"""An inserted run, as 0.6's ``Redlines.output_rich`` styles one."""

DELETE_STYLE: Final[str] = "strike red"
"""A deleted run, as 0.6's ``Redlines.output_rich`` styles one."""

NOTE_STYLE: Final[str] = "magenta"
"""A note: a move's ``moved from`` and the tombstone at its origin."""

HEADING_STYLE: Final[str] = "bold"
"""A heading's document text, put before any mark's style on it."""

TOTAL_STYLE: Final[str] = "bold"
"""The header's total, ``T changes``."""

NOTICE_STYLE: Final[str] = "yellow"
"""A header notice: the filter, the budget, a dropped item."""

_MARK_STYLES: Final[dict[str, str]] = {
    "insert": INSERT_STYLE,
    "delete": DELETE_STYLE,
}

_Run = tuple[str, str | None]
"""One segment of the text and its style, ``None`` for an unstyled one."""


def render_rich(comparison: Comparison) -> Text:
    """Render a comparison's test document, changes marked in place, as a `rich.text.Text`.

    :param comparison: the comparison, filtered or not.
    :return: the header, its notices and the document; see the module
        docstring for the layout and the styles.
    """
    text = Text()
    for segment, style in _kept(_header(comparison)):
        text.append(segment, style)
    for chunk in layout(comparison, RICH, syntax="text", roles=False):
        if chunk.block is None:
            continue  # a header note, written above in the HTML header's words
        runs = _kept(_chunk_runs(chunk))
        if not runs:
            continue  # an empty chunk is left out, as in every in-place output
        text.append("\n\n")
        for segment, style in runs:
            text.append(segment, style)
    return text


def _kept(runs: list[_Run]) -> list[_Run]:
    """The runs as rich keeps them, without any that would come out empty.

    `rich.text.Text` drops a few control characters (bell, backspace,
    vertical tab, form feed, carriage return), and ``Text.append`` checks a
    run's length before it drops them, so a run made only of those would leave
    an empty span; rich versions also differ on whether an empty run makes one.
    ``Text(segment).plain`` is what this rich keeps of a segment.
    """
    kept: list[_Run] = []
    for segment, style in runs:
        remaining = Text(segment).plain
        if remaining:
            kept.append((remaining, style))
    return kept


def _header(comparison: Comparison) -> list[_Run]:
    """The counts line, then each notice on a line of its own."""
    counts = comparison.statistics().counts
    total = f"{counts.total} change" + ("" if counts.total == 1 else "s")
    runs: list[_Run] = [
        (total, TOTAL_STYLE),
        (
            f": {counts.inserted} inserted, {counts.deleted} deleted, "
            f"{counts.modified} modified, {counts.moved} moved, "
            f"{counts.renumbered} renumbered",
            None,
        ),
    ]
    for notice in _notices(comparison):
        runs.append(("\n", None))
        runs.append((notice, NOTICE_STYLE))
    return runs


def _notices(comparison: Comparison) -> list[str]:
    """The header notices that are true, in the HTML header's order and words (ADR-0038)."""
    notices: list[str] = []
    config = comparison.config
    if config.filter is not None:
        fields: list[str] = []
        for name, value in config.filter.to_dict().items():
            rendered = _filter_value(value)
            if rendered is not None:
                fields.append(f"{name}={rendered}")
        if fields:
            notices.append("Filtered: " + "; ".join(fields))
    if config.budget_exhausted:
        notices.append("Alignment stopped early: the comparison budget ran out")
    for side, tree in (("source", comparison.source), ("test", comparison.test)):
        for dropped in tree.dropped:
            notices.append(
                f"{dropped.count} {dropped.kind} dropped from the {side}: {dropped.reason}"
            )
    return notices


def _chunk_runs(chunk: Chunk) -> list[_Run]:
    """One laid-out block or note line, as styled runs.

    A tombstone holds only a note, so a heading's tombstone stays magenta.
    """
    heading = chunk.block is not None and chunk.block.kind is BlockKind.HEADING

    def styled(mark: str | None) -> str | None:
        if not heading:
            return mark
        return HEADING_STYLE if mark is None else f"{HEADING_STYLE} {mark}"

    runs: list[_Run] = []
    for piece in chunk.pieces:
        if piece.kind == "note":
            runs.append((piece.text, NOTE_STYLE))
        elif piece.kind in _MARK_STYLES:
            runs.append((piece.text, styled(_MARK_STYLES[piece.kind])))
        elif piece.kind == "text":
            runs.append((piece.text, styled(None)))
        else:
            # The renderer's own syntax: a table's pipes and the newlines
            # between its rows. RICH has no roles and no substitution, so the
            # layout writes no other kind of piece.
            runs.append((piece.text, None))
    return runs
