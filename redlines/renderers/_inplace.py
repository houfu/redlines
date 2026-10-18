r"""The in-place traversal: the inline splice, the line syntax, and the walk every in-place output shares (ADR-0037).

`render_inplace` walks `redlines.renderers._view.build_view`'s view of the test
document once and writes it with a `redlines.renderers._marks.MarkSet`: the
six legacy styles and ``custom_css``, CriticMarkup, and whatever set a later
renderer brings. Placement, subtree emission, labels and tables therefore
cannot drift between renderers. The walk first lays the document out as
*chunks* -- one per block, a table counting as one block, plus the notes --
each a sequence of `Piece`\ s, and only then spells them with the set's
delimiters and escape (`serialize`), so a renderer that does not produce a
string, such as rich's, can spell the same chunks its own way.

**The walk.** Blocks come in view order, each text-bearing block (heading,
paragraph, list item) on a line of its own:

- an inserted or deleted block is one whole-block mark around its label and
  text, with the syntax head and the role prefix outside the mark; every
  text-bearing block of an inserted or deleted subtree is wrapped separately;
- any other block is its label part, then its text with its inline ops spliced
  in (`inline_segments`), on ``modify``, ``move`` and ``renumber`` alike;
- a note-bearing set ends a moved block's line with ``{>>moved from …<<}`` and
  writes a tombstone line at the origin; the whole-move sets (``whole_moves``)
  draw 0.6's picture instead: the moved block's whole source subtree struck at
  the origin, deleted and moved-out descendants included, and its whole test
  subtree inserted at the destination with no ghost or tombstone drawn inside
  it;
- a label that changed is a substitution as the label part, or a delete then
  an insert in a set without one; in the markdown variant a list-marker label
  stays in the syntax head and a note-bearing set says
  ``{>>renumbered from OLD<<}`` instead, because a mark inside the marker would
  break the list.

**Line syntax.** The text variant has none. The markdown variant takes it from
the blocks' ``attrs``: a heading is ``"#" * atx_level`` (or ``min(level + 1,
6)``) and a space; a list item with a ``list_marker`` is four spaces per
nesting level, the marker and a space; a quoted block has ``> `` before every
physical line; a fenced block is a fence with its marks *inside* it, opened
and closed by one backtick more than the longest run in its body, and at least
three.

**Labels** are written as the reader found them: ``attrs["label_raw"]``, else,
for a label that came from a list marker, the marker (text variant only; in the
markdown variant the marker is the syntax head and the label part is empty),
else ``label``. The whitespace between a label and its text is one space, and a
label-only block (``Schedule 1``, whose text is empty) ends at its label, with
no space after it.

**Tables** are one chunk: the header row, the alignment row (markdown variant
only), then the data rows, each ``| c1 | c2 |``, joined by ``\n``. A mark never
spans a ``|``: an inserted or deleted row marks each non-empty cell, an
all-empty one marks its first cell with an empty mark, and a modified cell is
spliced inside the cell. A deleted row anchored first goes after the header (and
the alignment row), so a deleted row never becomes the rendered header; a
wholly deleted table writes its first row as its header. A row that gained or
lost a cell is drawn as its test row inserted and its source row deleted, so
neither side reads back a cell the other side does not have. A ``|`` in cell
text is written ``\|`` in both variants.

**Separators.** Chunks are joined by ``\n\n``, with no trailing newline, and an
empty chunk is left out. The output is a normalised document, not the input
bytes: the readers have re-joined hard wraps, and a setext heading comes out
as ATX.

**CriticMarkup escaping** is ``_escape``'s backslash rule, applied to every
piece of document text and never to the renderer's own syntax. With role
prefixes on, a ``[`` that would read as a role prefix at the start of a line's
content is escaped too. A line's content can begin with different text on the
accept side and on the reject side -- an insertion at the very start of a block
-- and the escape is one string for both, so where only one of them can be
satisfied the accept side wins: accept-all reproduces the test rendering
exactly, and reject-all is a weaker claim in any case (ADR-0037).

Everything here is package-private; the `redlines.comparison.Comparison`
methods are the API.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Final, Literal

from ..blocks import Block, BlockKind
from ..changes import Change
from ._escape import (
    LINE_START_SITE,
    SYNTAX_HEAD,
    critic_escape,
    double_trailing_backslashes,
    encode_role,
    html_text,
)
from ._marks import MarkSet
from ._view import BlockStatus, ViewNode, build_view

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from ..comparison import Comparison

__all__: tuple[str, ...] = (
    "Segment",
    "inline_segments",
    "Piece",
    "Chunk",
    "Syntax",
    "label_text",
    "syntax_head",
    "layout",
    "serialize",
    "render_inplace",
)

Syntax = Literal["text", "markdown"]
"""The two syntax variants of an in-place rendering."""

SegmentKind = Literal["equal", "insert", "delete", "replace"]

PieceKind = Literal["syntax", "role", "text", "insert", "delete", "substitution", "note"]

# A cell is only ever drawn by its table; it is text-bearing here for a tree
# that puts one somewhere else, so its text is not lost.
_TEXT_BEARING: Final[frozenset[BlockKind]] = frozenset(
    {
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.CELL,
        BlockKind.UNKNOWN,
    }
)
_NO_ROLE: Final[frozenset[BlockKind]] = frozenset(
    {BlockKind.TABLE, BlockKind.ROW, BlockKind.CELL}
)
_ALIGNMENT_CELL: Final[dict[str, str]] = {
    "default": "---",
    "left": ":---",
    "right": "---:",
    "center": ":---:",
}

_Mark = Literal["insert", "delete"]


# --------------------------------------------------------------------------
# The inline splice.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Segment:
    """One run of a modified block's text: unchanged, or one inline op.

    :param kind: ``equal`` for a run between ops, or the op's kind.
    :param source_text: the run in the source block's text.
    :param test_text: the run in the test block's text. An ``equal`` run
        carries both sides, because they can differ in whitespace the differ
        does not compare.
    """

    kind: SegmentKind
    source_text: str
    test_text: str


def inline_segments(change: Change) -> tuple[Segment, ...]:
    """Split a change's two texts into equal runs and its inline ops, in order.

    Joining every segment's ``test_text`` gives ``change.test_text``, and
    joining every ``source_text`` gives ``change.source_text``. The runs are
    slices of the two texts at the ops' offsets; an op that starts before the
    previous one ended, or past the end of its text, is clamped, so the
    segments always tile both texts.

    :param change: a change node; one with no inline ops is one equal run.
    :return: the segments, with no empty equal run.
    """
    source, test = change.source_text, change.test_text
    segments: list[Segment] = []
    source_at = test_at = 0
    for op in change.inline:
        source_start = min(max(op.source_start, source_at), len(source))
        test_start = min(max(op.test_start, test_at), len(test))
        source_end = min(max(op.source_end, source_start), len(source))
        test_end = min(max(op.test_end, test_start), len(test))
        if source_start > source_at or test_start > test_at:
            segments.append(
                Segment("equal", source[source_at:source_start], test[test_at:test_start])
            )
        segments.append(
            Segment(
                op.kind.value,
                source[source_start:source_end],
                test[test_start:test_end],
            )
        )
        source_at, test_at = source_end, test_end
    if source_at < len(source) or test_at < len(test):
        segments.append(Segment("equal", source[source_at:], test[test_at:]))
    return tuple(segments)


# --------------------------------------------------------------------------
# The layout: chunks of pieces.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Piece:
    """One run of a chunk.

    :param kind: ``syntax`` for what the renderer writes of its own (syntax
        heads, table pipes, fences, newlines); ``role`` for a role prefix,
        already encoded and delimited; ``text`` for document text; ``insert``,
        ``delete`` and ``note`` for a mark around ``text``; ``substitution``
        for a replacement of ``text`` by ``new``.
    :param text: the run, the mark's body, or a substitution's old side.
    :param new: a substitution's new side; empty for every other kind.
    """

    kind: PieceKind
    text: str = ""
    new: str = ""


@dataclass(frozen=True, slots=True)
class Chunk:
    """One block of the output, or one note on a line of its own.

    :param pieces: the runs, in order.
    :param quote: whether every physical line of the chunk is quoted (``> ``).
    :param block: the block the chunk draws, ``None`` for a note line.
    :param status: that block's status in the view.
    """

    pieces: tuple[Piece, ...]
    quote: bool = False
    block: Block | None = None
    status: BlockStatus | None = None


def label_text(block: Block, syntax: Syntax) -> str:
    """The label as the document wrote it (ADR-0037, "Labels as written").

    ``attrs["label_raw"]``, else, for a label that came from a list marker, the
    marker in the text variant and nothing in the markdown variant (where the
    marker is the syntax head), else ``label``.

    :param block: the block.
    :param syntax: the variant being written.
    :return: the label text, ``""`` for a block with no label.
    """
    if block.label is None:
        return ""
    attrs = block.attrs
    raw = attrs.get("label_raw")
    if isinstance(raw, str) and raw:
        return raw
    if attrs.get("label_source") == "list_marker":
        if syntax == "markdown":
            return ""
        marker = attrs.get("list_marker")
        if isinstance(marker, str) and marker:
            return marker
    return block.label


def syntax_head(block: Block, syntax: Syntax) -> str:
    """The markdown syntax head of a block's first line, without any quote marker.

    :param block: the block.
    :param syntax: the variant being written; the text variant has none.
    :return: ``"## "`` for a heading, ``"    - "`` for a nested list item, and
        so on; ``""`` for everything else.
    """
    if syntax != "markdown":
        return ""
    attrs = block.attrs
    if block.kind is BlockKind.HEADING:
        return "#" * _integer(attrs.get("atx_level"), min(block.level + 1, 6)) + " "
    marker = attrs.get("list_marker")
    if block.kind is BlockKind.LIST_ITEM and isinstance(marker, str) and marker:
        depth = _integer(attrs.get("list_depth"), 1)
        return "    " * max(depth - 1, 0) + marker + " "
    return ""


def _integer(value: object, default: int) -> int:
    """An ``attrs`` value that should be an integer, or ``default``."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _is_fence(block: Block, syntax: Syntax) -> bool:
    return syntax == "markdown" and "fence" in block.attrs


def _is_quoted(block: Block, syntax: Syntax) -> bool:
    return syntax == "markdown" and bool(block.attrs.get("quote"))


def _pipes(text: str) -> str:
    return text.replace("|", "\\|")


def _longest_backtick_run(texts: Iterable[str]) -> int:
    longest = 0
    for text in texts:
        run = 0
        for character in text:
            run = run + 1 if character == "`" else 0
            longest = max(longest, run)
    return longest


@dataclass(frozen=True, slots=True)
class _RowLine:
    """One rendered table row, and whether it is a deleted one."""

    pieces: tuple[Piece, ...]
    deleted: bool
    cells: int


class _Layout:
    """Walks one view and lays it out as chunks for one mark set and variant."""

    def __init__(
        self, comparison: Comparison, marks: MarkSet, syntax: Syntax, roles: bool
    ) -> None:
        self.comparison = comparison
        self.marks = marks
        self.syntax = syntax
        self.roles = roles and marks.roles
        self.test_blocks: dict[str, Block] = {
            block.path: block for block in comparison.test.walk()
        }
        self.chunks: list[Chunk] = []

    # -- the walk ---------------------------------------------------------

    def run(self, view: ViewNode) -> tuple[Chunk, ...]:
        if self.marks.notes:
            self._header_notes()
        self._walk(view, inside_whole_move=False)
        return tuple(self.chunks)

    def _walk(self, node: ViewNode, *, inside_whole_move: bool) -> None:
        status = node.status
        block = node.block
        if status is BlockStatus.ORIGIN:
            if not inside_whole_move:  # else struck at the outer origin already
                self._origin(node)
            return
        if status is BlockStatus.DELETE and inside_whole_move:
            return  # struck at the origin with the moved block's source subtree
        whole_move = status is BlockStatus.MOVE and self.marks.whole_moves
        children_whole = inside_whole_move or whole_move
        if block.kind is BlockKind.TABLE:
            if inside_whole_move or whole_move or status is BlockStatus.INSERT:
                self._table(node, whole="insert")
            elif status is BlockStatus.DELETE:
                self._table(node, whole="delete")
            else:
                self._table(node, whole=None)
                self._move_note_line(node)
            return
        if block.kind in _TEXT_BEARING:
            if inside_whole_move or whole_move or status is BlockStatus.INSERT:
                self._whole_block(block, "insert", status)
            elif status is BlockStatus.DELETE:
                self._whole_block(block, "delete", status)
            else:
                self._line(node)
        else:
            # document, section, and a row or cell outside any table: nothing
            # of their own to write, but a moved one still says so.
            if not children_whole:
                self._move_note_line(node)
        for child in node.children:
            self._walk(child, inside_whole_move=children_whole)

    def _origin(self, node: ViewNode) -> None:
        """A move's origin: a tombstone line, or 0.6's struck source subtree."""
        if self.marks.whole_moves:
            self._strike(node.block)
            return
        change = node.change
        if change is None or change.test_address is None or not self.marks.notes:
            return
        source_label = label_text(node.block, self.syntax)
        destination = self.test_blocks.get(change.test_address)
        test_label = "" if destination is None else label_text(destination, self.syntax)
        note = (
            (source_label + " " if source_label else "")
            + "moved to "
            + (test_label + " " if test_label else "")
            + change.test_address
        )
        self._add((Piece("note", note),), quote=False, block=node.block, status=node.status)

    def _strike(self, block: Block) -> None:
        """Strike a whole source subtree, in pre-order, every descendant included."""
        if block.kind is BlockKind.TABLE:
            rows = [self._marked_row(row, "delete") for row in block.children]
            self._add_table(block, rows, quote=_is_quoted(block, self.syntax), status=BlockStatus.ORIGIN)
            return
        if block.kind in _TEXT_BEARING:
            self._whole_block(block, "delete", BlockStatus.ORIGIN)
        for child in block.children:
            self._strike(child)

    # -- one line ---------------------------------------------------------

    def _head(self, block: Block) -> list[Piece]:
        """The syntax head and the role prefix: what sits outside every mark."""
        pieces: list[Piece] = []
        head = syntax_head(block, self.syntax)
        if head:
            pieces.append(Piece("syntax", head))
        if (
            self.roles
            and block.role is not None
            and block.kind not in _NO_ROLE
            and not _is_fence(block, self.syntax)
        ):
            pieces.append(Piece("role", self._role_prefix(block.role)))
        return pieces

    def _role_prefix(self, role: str) -> str:
        assert self.marks.role is not None  # roles are on only for a set with roles
        opening, closing = self.marks.role
        if self.marks.escape == "html":
            return opening + html_text(role) + closing
        return opening + encode_role(role) + closing

    def _whole_block(self, block: Block, mark: _Mark, status: BlockStatus) -> None:
        """An inserted or deleted text-bearing block: one mark, head and role outside."""
        if _is_fence(block, self.syntax):
            self._fence(block, [Piece(mark, block.text)], status)
            return
        body = _labelled(label_text(block, self.syntax), block.text)
        pieces = self._head(block)
        pieces.append(Piece(mark, body))
        self._add(tuple(pieces), quote=_is_quoted(block, self.syntax), block=block, status=status)

    def _line(self, node: ViewNode) -> None:
        """A block that is in both documents, or unchanged, drawn in place."""
        block = node.block
        change = node.change
        if _is_fence(block, self.syntax):
            if change is not None and change.inline:
                body = self._splice(change, pipes=False)
            else:
                body = [Piece("text", block.text)] if block.text else []
            self._fence(block, body, node.status)
            self._move_note_line(node)
            return
        pieces = self._head(block)
        pieces.extend(self._label_part(node))
        if change is not None and change.inline:
            pieces.extend(self._splice(change, pipes=False))
        elif block.text:
            pieces.append(Piece("text", block.text))
        if node.status is BlockStatus.MOVE and self.marks.notes and change is not None:
            pieces.append(Piece("text", " "))
            pieces.append(Piece("note", self._moved_from(node, change)))
        self._add(tuple(pieces), quote=_is_quoted(block, self.syntax), block=block, status=node.status)

    def _label_part(self, node: ViewNode) -> list[Piece]:
        """The label part of a line: the label, its renumbering, or nothing.

        The space between a label and its text is written only when there is
        text: a label-only block, such as a ``Schedule 1`` heading, ends at its
        label. The one exception is the renumber note, whose space the reader
        removes together with the note.
        """
        block = node.block
        change = node.change
        new = label_text(block, self.syntax)
        space = " " if block.text else ""
        relabelled = change is not None and (change.source_label or None) != (
            change.test_label or None
        )
        if not relabelled:
            return [Piece("text", new + space)] if new else []
        source = node.counterpart
        if (
            self.marks.notes
            and self.syntax == "markdown"
            and block.attrs.get("label_source") == "list_marker"
        ):
            old = "" if source is None else label_text(source, "text")
            return [Piece("note", "renumbered from " + old), Piece("text", " ")]
        old = "" if source is None else label_text(source, self.syntax)
        if old == new:
            return [Piece("text", new + space)] if new else []
        if self.marks.substitution is not None:
            return [Piece("substitution", old, new), Piece("text", space)]
        pieces: list[Piece] = []
        if old:
            pieces.append(Piece("delete", old + space))
        if new:
            pieces.append(Piece("insert", new + space))
        return pieces

    def _moved_from(self, node: ViewNode, change: Change) -> str:
        source = node.counterpart
        label = "" if source is None else label_text(source, self.syntax)
        address = change.source_address or ""
        return "moved from " + (label + " " if label else "") + address

    def _move_note_line(self, node: ViewNode) -> None:
        """A moved block with no line of its own (a section, a table, a fence) says so on one."""
        change = node.change
        if node.status is not BlockStatus.MOVE or change is None or not self.marks.notes:
            return
        if self.marks.whole_moves:
            return
        self._add(
            (Piece("note", self._moved_from(node, change)),),
            quote=False,
            block=node.block,
            status=node.status,
        )

    def _splice(self, change: Change, *, pipes: bool) -> list[Piece]:
        """The block's text with its inline ops marked, equal runs from the test side."""
        escape = _pipes if pipes else _same
        pieces: list[Piece] = []
        for segment in inline_segments(change):
            if segment.kind == "equal":
                if segment.test_text:
                    pieces.append(Piece("text", escape(segment.test_text)))
            elif segment.kind == "insert":
                if segment.test_text:
                    pieces.append(Piece("insert", escape(segment.test_text)))
            elif segment.kind == "delete":
                if segment.source_text:
                    pieces.append(Piece("delete", escape(segment.source_text)))
            elif self.marks.substitution is not None:
                old, new = segment.source_text, segment.test_text
                tail = ""
                while old and new and old[-1].isspace() and old[-1] == new[-1]:
                    tail = old[-1] + tail
                    old, new = old[:-1], new[:-1]
                pieces.append(Piece("substitution", escape(old), escape(new)))
                if tail:
                    pieces.append(Piece("text", tail))
            else:
                if segment.source_text:
                    pieces.append(Piece("delete", escape(segment.source_text)))
                if segment.test_text:
                    pieces.append(Piece("insert", escape(segment.test_text)))
        return pieces

    def _fence(self, block: Block, body: list[Piece], status: BlockStatus) -> None:
        """A fenced block, its marks inside the fence."""
        texts = [piece.text for piece in body] + [piece.new for piece in body]
        ticks = "`" * max(3, _longest_backtick_run(texts) + 1)
        info = block.attrs.get("fence")
        pieces: list[Piece] = [Piece("syntax", ticks)]
        if isinstance(info, str) and info:
            pieces.append(Piece("text", info))
        pieces.append(Piece("syntax", "\n"))
        pieces.extend(body)
        pieces.append(Piece("syntax", "\n" + ticks))
        self._add(tuple(pieces), quote=_is_quoted(block, self.syntax), block=block, status=status)

    # -- tables -----------------------------------------------------------

    def _table(self, node: ViewNode, *, whole: _Mark | None) -> None:
        lines: list[_RowLine] = []
        for row in node.children:
            if row.status is BlockStatus.ORIGIN:
                continue  # cannot occur under the default move kinds (ADR-0037, rule 5)
            if row.status is BlockStatus.DELETE and whole == "insert":
                continue  # 0.6's picture draws no ghost inside a moved block
            lines.extend(self._row_lines(row, whole))
        if node.status is not BlockStatus.DELETE:
            first = next((index for index, line in enumerate(lines) if not line.deleted), None)
            if first is not None:
                lines = [lines[first], *lines[:first], *lines[first + 1 :]]
        self._add_table(node.block, lines, quote=_is_quoted(node.block, self.syntax), status=node.status)

    def _row_lines(self, row: ViewNode, whole: _Mark | None) -> list[_RowLine]:
        if whole is not None:
            return [self._marked_row(row.block, whole)]
        if row.status is BlockStatus.INSERT or (
            row.status is BlockStatus.MOVE and self.marks.whole_moves
        ):
            return [self._marked_row(row.block, "insert")]
        if row.status is BlockStatus.DELETE:
            return [self._marked_row(row.block, "delete")]
        restructured = any(
            cell.status in (BlockStatus.INSERT, BlockStatus.DELETE, BlockStatus.ORIGIN)
            for cell in row.children
        )
        if restructured:
            lines = [self._marked_row(row.block, "insert")]
            if row.counterpart is not None:
                lines.append(self._marked_row(row.counterpart, "delete"))
            return lines
        cells: list[list[Piece]] = []
        for cell in row.children:
            change = cell.change
            if change is not None and change.inline:
                cells.append(self._splice(change, pipes=True))
            elif cell.block.text:
                cells.append([Piece("text", _pipes(cell.block.text))])
            else:
                cells.append([])
        return [_RowLine(_assemble_row(cells), deleted=False, cells=len(cells))]

    def _marked_row(self, row: Block, mark: _Mark) -> _RowLine:
        """A row inserted or deleted whole: each non-empty cell marked on its own."""
        cells: list[list[Piece]] = [
            [Piece(mark, _pipes(cell.text))] if cell.text else [] for cell in row.children
        ]
        if cells and not any(cells):
            cells[0] = [Piece(mark, "")]  # an all-empty row stays visible
        return _RowLine(_assemble_row(cells), deleted=mark == "delete", cells=len(cells))

    def _add_table(
        self, table: Block, lines: Sequence[_RowLine], *, quote: bool, status: BlockStatus
    ) -> None:
        if not lines:
            return
        pieces: list[Piece] = []
        for index, line in enumerate(lines):
            if index:
                pieces.append(Piece("syntax", "\n"))
            pieces.extend(line.pieces)
            if index == 0 and self.syntax == "markdown":
                pieces.append(Piece("syntax", "\n" + _alignment_row(table, line.cells)))
        self._add(tuple(pieces), quote=quote, block=table, status=status)

    # -- notes ------------------------------------------------------------

    def _header_notes(self) -> None:
        """The notices before the first block, each only when it is true (ADR-0037)."""
        config = self.comparison.config
        if config.filter is not None:
            fields: list[str] = []
            for name, value in config.filter.to_dict().items():
                rendered = _filter_value(value)
                if rendered is not None:
                    fields.append(f"{name}={rendered}")
            if fields:
                self._add((Piece("note", "filtered: " + "; ".join(fields)),), quote=False)
        if config.budget_exhausted:
            self._add(
                (Piece("note", "alignment stopped early: the comparison budget ran out"),),
                quote=False,
            )
        for side, tree in (("source", self.comparison.source), ("test", self.comparison.test)):
            for dropped in tree.dropped:
                note = f"{side} dropped {dropped.count} {dropped.kind}: {dropped.reason}"
                self._add((Piece("note", note),), quote=False)

    def _add(
        self,
        pieces: tuple[Piece, ...],
        *,
        quote: bool,
        block: Block | None = None,
        status: BlockStatus | None = None,
    ) -> None:
        self.chunks.append(Chunk(_merge_text(pieces), quote, block, status))


def _same(text: str) -> str:
    return text


def _labelled(label: str, text: str) -> str:
    """A label and its text, one space between them, and none after a label-only block."""
    if label and text:
        return label + " " + text
    return label or text


def _filter_value(value: object) -> str | None:
    """A `redlines.filters.ChangeFilter` field as the filtered note writes it, or ``None`` if empty."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if value is None:
        return None
    if isinstance(value, int):
        return str(value) if value else None
    if isinstance(value, (list, tuple)):
        return ",".join(str(item) for item in value) if value else None
    return str(value) if value else None


def _assemble_row(cells: Sequence[Sequence[Piece]]) -> tuple[Piece, ...]:
    pieces: list[Piece] = [Piece("syntax", "| ")]
    for index, cell in enumerate(cells):
        if index:
            pieces.append(Piece("syntax", " | "))
        pieces.extend(cell)
    pieces.append(Piece("syntax", " |"))
    return tuple(pieces)


def _alignment_row(table: Block, cells: int) -> str:
    alignments = table.attrs.get("alignments")
    names = (
        [str(name) for name in alignments]
        if isinstance(alignments, (list, tuple)) and alignments
        else ["default"] * max(cells, 1)
    )
    return "| " + " | ".join(_ALIGNMENT_CELL.get(name, "---") for name in names) + " |"


def _merge_text(pieces: Iterable[Piece]) -> tuple[Piece, ...]:
    """Join adjacent text pieces and drop empty ones, so no backslash run spans two."""
    merged: list[Piece] = []
    for piece in pieces:
        if piece.kind == "text":
            if not piece.text:
                continue
            if merged and merged[-1].kind == "text":
                merged[-1] = Piece("text", merged[-1].text + piece.text)
                continue
        merged.append(piece)
    return tuple(merged)


def layout(
    comparison: Comparison,
    marks: MarkSet,
    *,
    syntax: Syntax,
    roles: bool,
    view: ViewNode | None = None,
) -> tuple[Chunk, ...]:
    """Lay a comparison's view out as chunks, before any delimiter is spelled.

    :param comparison: the comparison to draw.
    :param marks: the mark set; it decides replacements, notes, roles and moves.
    :param syntax: ``"text"`` or ``"markdown"``.
    :param roles: show role prefixes, for a set that has them.
    :param view: the view, if the caller has already built it.
    :return: the chunks, in output order.
    """
    tree = build_view(comparison) if view is None else view
    return _Layout(comparison, marks, syntax, roles).run(tree)


# --------------------------------------------------------------------------
# Spelling the chunks.
# --------------------------------------------------------------------------


_Side = Literal["accept", "reject"]
_Origin = tuple[int, int, int]  # (piece index, part: 0 text or old side / 1 new side, offset)


def _side_text(
    pieces: Sequence[Piece], side: _Side, quote: bool
) -> tuple[str, list[_Origin | None], list[int]]:
    """What a reader recovers of one chunk on one side, with where each character came from.

    Mirrors the reader: marks resolved, notes stripped with one adjacent space,
    a quote marker after every newline.

    :return: the text, each character's origin (``None`` for the renderer's
        own syntax), and the positions where a role prefix starts.
    """
    characters: list[str] = []
    origins: list[_Origin | None] = []
    role_starts: list[int] = []

    def put(text: str, origin: tuple[int, int] | None) -> None:
        for offset, character in enumerate(text):
            characters.append(character)
            origins.append(None if origin is None else (origin[0], origin[1], offset))
            if character == "\n" and quote:
                characters.extend("> ")
                origins.extend((None, None))

    if quote:
        put("> ", None)
    skip_space = False
    for index, piece in enumerate(pieces):
        if piece.kind == "note":
            following = pieces[index + 1] if index + 1 < len(pieces) else None
            if (
                following is not None
                and following.kind in ("text", "syntax")
                and following.text.startswith(" ")
            ):
                skip_space = True
            elif characters and characters[-1] == " ":
                characters.pop()
                origins.pop()
            continue
        if piece.kind in ("syntax", "role"):
            if piece.kind == "role":
                role_starts.append(len(characters))
            text = piece.text[1:] if skip_space and piece.text.startswith(" ") else piece.text
            put(text, None)
        elif piece.kind == "text":
            if skip_space and piece.text.startswith(" "):
                characters_before = len(characters)
                put(piece.text[1:], (index, 0))
                for position in range(characters_before, len(origins)):
                    origin = origins[position]
                    if origin is not None:
                        origins[position] = (origin[0], origin[1], origin[2] + 1)
            else:
                put(piece.text, (index, 0))
        elif piece.kind == "insert":
            if side == "accept":
                put(piece.text, (index, 0))
        elif piece.kind == "delete":
            if side == "reject":
                put(piece.text, (index, 0))
        elif side == "accept":
            put(piece.new, (index, 1))
        else:
            put(piece.text, (index, 0))
        skip_space = False
    return "".join(characters), origins, role_starts


def _line_start_sites(
    pieces: Sequence[Piece], side: _Side, quote: bool
) -> dict[tuple[int, int, int], int]:
    """Where one side's lines would read document text as a role prefix.

    :return: for each such ``[``, its origin and the backslash run before it.
    """
    text, origins, role_starts = _side_text(pieces, side, quote)
    sites: dict[tuple[int, int, int], int] = {}
    roles = dict.fromkeys(role_starts)
    start = 0
    while start <= len(text):
        end = text.find("\n", start)
        if end < 0:
            end = len(text)
        head = SYNTAX_HEAD.match(text, start, end)
        content = head.end() if head is not None else start
        if content in roles:
            prefix_end = text.find("] ", content, end)
            content = prefix_end + 2 if prefix_end >= 0 else content
        site = LINE_START_SITE.match(text, content, end)
        if site is not None:
            bracket = content + len(site.group(1))
            origin = origins[bracket]
            if origin is not None:
                sites[origin] = len(site.group(1))
        start = end + 1
    return sites


def _escape_line_starts(pieces: tuple[Piece, ...], quote: bool) -> tuple[Piece, ...]:
    """Escape every role-shaped ``[`` at a line's content start, on either side.

    One string serves both sides, so a ``[`` in shared text that starts a line
    on the reject side only is left alone: the accept side wins.
    """
    if not any(
        "[" in piece.text or "[" in piece.new
        for piece in pieces
        if piece.kind not in ("syntax", "role")
    ):
        return pieces
    accept = _line_start_sites(pieces, "accept", quote)
    reject = _line_start_sites(pieces, "reject", quote)
    escapes: dict[tuple[int, int], dict[int, int]] = {}
    for (index, part, offset), run in accept.items():
        escapes.setdefault((index, part), {})[offset] = run + 1
    for (index, part, offset), run in reject.items():
        if pieces[index].kind == "text":
            continue  # shared text: escaped only if the accept side needs it
        escapes.setdefault((index, part), {})[offset] = run + 1
    if not escapes:
        return pieces
    escaped = list(pieces)
    for (index, part), at in escapes.items():
        piece = escaped[index]
        text = piece.new if part else piece.text
        for offset in sorted(at, reverse=True):
            text = text[:offset] + "\\" * at[offset] + text[offset:]
        escaped[index] = replace(piece, new=text) if part else replace(piece, text=text)
    return tuple(escaped)


def _spell(chunk: Chunk, marks: MarkSet, roles: bool) -> str:
    """Write one chunk with a set's delimiters and escape."""
    pieces = chunk.pieces
    if marks.escape == "critic" and roles:
        pieces = _escape_line_starts(pieces, chunk.quote)
    if marks.escape == "critic":
        escape = critic_escape
    elif marks.escape == "html":
        escape = html_text
    else:
        escape = _same
    live = marks.escape == "critic"

    def quoted(text: str) -> str:
        return text.replace("\n", "\n> ") if chunk.quote else text

    out: list[str] = ["> "] if chunk.quote else []

    def delimiter(text: str) -> None:
        if live and out:
            out[-1] = double_trailing_backslashes(out[-1])
        out.append(text)

    def body(text: str) -> None:
        written = quoted(escape(text))
        out.append(double_trailing_backslashes(written) if live else written)

    for piece in pieces:
        if piece.kind in ("syntax", "role"):
            out.append(quoted(piece.text))
        elif piece.kind == "text":
            out.append(quoted(escape(piece.text)))
        elif piece.kind == "substitution":
            if marks.substitution is None:  # pragma: no cover - the layout never asks
                raise ValueError(f"the {marks.name} set has no substitution")
            opening, separator, closing = marks.substitution
            delimiter(opening)
            body(piece.text)
            out.append(separator)
            body(piece.new)
            out.append(closing)
        else:
            if piece.kind == "note":
                if marks.note is None:  # pragma: no cover - the layout never asks
                    raise ValueError(f"the {marks.name} set carries no notes")
                opening, closing = marks.note
            elif piece.kind == "insert":
                opening, closing = marks.insert
            else:
                opening, closing = marks.delete
            delimiter(opening)
            body(piece.text)
            out.append(closing)
    return "".join(out)


def serialize(chunks: Iterable[Chunk], marks: MarkSet, *, roles: bool) -> str:
    """Spell laid-out chunks with a mark set: chunks joined by a blank line.

    :param chunks: what `layout` returned for the same set.
    :param marks: the set to spell them with.
    :param roles: whether the layout was made with role prefixes on.
    :return: the rendering, with no trailing newline; an empty chunk is left out.
    """
    roles = roles and marks.roles
    spelled = (_spell(chunk, marks, roles) for chunk in chunks)
    return "\n\n".join(text for text in spelled if text)


def render_inplace(
    comparison: Comparison,
    marks: MarkSet,
    *,
    syntax: Syntax,
    roles: bool,
    view: ViewNode | None = None,
) -> str:
    """Render a comparison's test document with its changes marked in place.

    :param comparison: the comparison, filtered or not.
    :param marks: the mark set to write with.
    :param syntax: ``"text"`` for no line syntax, ``"markdown"`` for the
        markdown variant's heads, fences, quotes and alignment rows.
    :param roles: write role prefixes. Only a set that has them can show them.
    :param view: the comparison's view, if the caller has already built it.
    :return: the rendering, chunks joined by ``\\n\\n``, no trailing newline.
    :raises ValueError: if ``syntax`` is not one of the two variants, or roles
        are asked of a set that shows none.
    """
    if syntax not in ("text", "markdown"):
        raise ValueError(f"syntax must be 'text' or 'markdown', got {syntax!r}")
    if roles and not marks.roles:
        raise ValueError(f"the {marks.name} set shows no roles; pass roles=False")
    chunks = layout(comparison, marks, syntax=syntax, roles=roles, view=view)
    return serialize(chunks, marks, roles=roles)
