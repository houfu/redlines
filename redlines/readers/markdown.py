"""The markdown reader: the syntax replaces PRD § 6b's first three stages (#103, R5, D16).

`MarkdownReader` turns a markdown document into a `redlines.blocks.BlockTree`
whose shape is the one `redlines.readers.text.PlainTextReader` produces, because
the two have to be comparable: PRD § 6b ends with the promise that "a markdown
contract with ``## 7. Termination`` and ``1.`` list items therefore gets the same
roles and labels as its plain-text twin", and an aligner cannot keep that promise
if the two readers disagree about what a section is.

So the division of labour is:

- **the syntax** answers what plain text has to infer -- where a heading is
  (``#``), where a list item is and how deep it nests (the marker and its
  indentation), where a table is (pipes), where verbatim text is (a fence).
  Those decisions are stated, so they are recorded as ``markdown:<syntax>`` at
  confidence 1.0 (ADR-0030);
- **the profile** answers everything the syntax does not: whether the text of a
  heading, a list item or a paragraph carries a clause label, how deep that
  label sits in the document's own numbering, which headings restart numbering,
  and which unlabelled paragraphs continue the block above them. That is
  `redlines.readers.labels` -- the same module, the same
  `redlines.readers.labels.HierarchyStack`, the same continuation and
  heading-scoring rules the plain-text reader uses, applied to the text left
  once a marker has been stripped. Those decisions are recorded as
  ``label:<pattern>``, ``continuation`` or ``fallback``, with the stack's own
  confidence.

Reading a document::

    from redlines.profiles.builtin import builtin_profile
    from redlines.readers import reader_for

    tree = reader_for("markdown").read(text, profile=builtin_profile("markdown"))

**What is dropped** (R3): horizontal rules, HTML blocks, link reference
definitions and images. Each is counted and reported in
`redlines.blocks.BlockTree.dropped` with a reason. A pipe table's alignment row
is *not* reported: it carries no text, it is the table's own punctuation, and
its content survives as the table's ``alignments`` attribute.

**Known limits**, all deliberate for 1.0 and all documented rather than
half-implemented: indented (four-space) code blocks are read as ordinary
content, not as code -- a fence is how a markdown contract writes code, and
guessing at indentation would fight list nesting for the same signal; inline
emphasis is left in the text (ADR-0024), so ``**bold**`` is part of the block's
text and the semantic pass may add an ``emphasis`` span later; and a blockquote
is stripped one level at a time but never promoted to a heading or allowed to
reset numbering, because quoted material is evidence inside the document rather
than structure of it. That last rule is enforced for *every* quoted construct,
including an ATX or setext heading written inside the quotation: it keeps its
text, its label and its ``markdown:atx`` provenance but comes out as a
``paragraph`` carrying ``attrs["quoted_heading"]``, it opens no section, and its
label is previewed against the numbering stack rather than placed on it. Quoted
blocks nest among themselves and are attached where the blockquote sits; they
never close a real block, and the first unquoted block after a quotation drops
everything the quotation opened.

**One departure from the task text for #103**, recorded here because it is a
promise traded for another: an ATX heading's ``level`` follows the clause label
in its text where it carries one, *not* the hash count, which is kept in
``attrs["atx_level"]`` and used as a floor on where the heading nests. The task
text asks for "level from the hash count" and, in the same paragraph, for
``## 7. Termination`` to match its plain-text twin ``7. Termination``; those two
cannot both hold, because the twin's level comes from the numbering and is 1.
The twin promise is the one PRD § 6b makes to users, so it wins. The
coordinator should confirm that trade.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..blocks import (
    MATCHED_BY_CONTINUATION,
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
    Dropped,
    matched_by_heading,
    matched_by_label,
    matched_by_markdown,
)
from ..profiles import Profile
from . import DEFAULT_MAX_CHARS, check_size, decode_source, register_reader
from .labels import (
    CONFIDENCE_RESET_HEADING,
    HEADING_THRESHOLD,
    NEXT_DEEPER,
    NEXT_NONE,
    NEXT_PEER,
    HeadingScore,
    HierarchyStack,
    Placement,
    continuation_for,
    heading_reset_name,
    heading_score,
    label_candidates,
)

# The plain-text reader owns stage one (normalise, segment and the PRD's
# hard-wrap rule) and the two helpers that record what stages two to five
# decided. Both are imported rather than reimplemented: a markdown paragraph
# has to break into blocks exactly where its plain-text twin does, and the
# ``attrs`` keys have to be the same keys, or the two trees stop being
# comparable. `_label_attrs` and `_heading_attrs` are private to that module
# only because nothing outside this package should depend on the shape of
# ``attrs``; this reader is inside it.
from .text import _heading_attrs, _label_attrs, normalise, segment

__all__ = [
    "MARKDOWN_SYNTAX",
    "MarkdownReader",
]


MARKDOWN_SYNTAX: tuple[str, ...] = (
    "atx",
    "setext",
    "list",
    "fence",
    "pipe_table",
    "table_row",
    "table_cell",
)
"""Every ``markdown:<syntax>`` detail this reader records (ADR-0030).

Listed so a consumer can filter on "what did the syntax state, as opposed to
what did a profile pattern infer" without matching on prefixes it guessed. A
blockquote is not among them: quoting says nothing about what a block *is*, so
a quoted block is recognised like any other and carries ``attrs["quote"]``.
"""


# --- syntax ----------------------------------------------------------------
#
# Deliberately a small, readable subset of CommonMark: stdlib `re` only
# (ADR-0013), and only the constructs a contract written in markdown actually
# uses. Anything not recognised here ends up as a paragraph, which is the
# degrade path every reader shares.

_ATX = re.compile(r"^(?P<indent> {0,3})(?P<hashes>#{1,6})(?P<rest>(?:\s.*)?)$")
_ATX_CLOSING = re.compile(r"\s+#+\s*$")
_SETEXT = re.compile(r"^ {0,3}(?P<underline>=+|-+)\s*$")
_THEMATIC = re.compile(r"^ {0,3}(?:(?:\*\s*){3,}|(?:-\s*){3,}|(?:_\s*){3,})$")
_FENCE_OPEN = re.compile(r"^(?P<indent>\s*)(?P<fence>`{3,}|~{3,})(?P<info>[^`]*)$")
_BULLET = re.compile(r"^(?P<indent>\s*)(?P<marker>[-*+])(?P<space>\s+|$)(?P<text>.*)$")
_ORDERED = re.compile(
    r"^(?P<indent>\s*)(?P<value>\d{1,9})(?P<delim>[.)])(?P<space>\s+|$)(?P<text>.*)$"
)
_QUOTE = re.compile(r"^ {0,3}>(?P<space> ?)(?P<text>.*)$")
_LINK_DEFINITION = re.compile(r"^ {0,3}\[[^\]\n]+\]:\s*\S+.*$")
_HTML_BLOCK = re.compile(
    r"^ {0,3}<(?:[A-Za-z][A-Za-z0-9-]*|/[A-Za-z][A-Za-z0-9-]*|[!?])"
)
_ALIGNMENT_CELL = re.compile(r"^:?-+:?$")
_IMAGE = re.compile(r"!\[[^\]\n]*\](?:\([^)\n]*\)|\[[^\]\n]*\])?")
_TAB_WIDTH = 4


_DROP_REASONS: tuple[tuple[str, str], ...] = (
    (
        "control_character",
        "Control characters were removed during normalisation; they carry no "
        "text and would corrupt block offsets.",
    ),
    (
        "thematic_break",
        "A horizontal rule is a visual divider with no text of its own; the "
        "sections it separates are kept.",
    ),
    (
        "html_block",
        "Raw HTML blocks are not parsed: ADR-0013 keeps the 1.0 core on the "
        "standard library and an HTML reader is 1.1 work (R8).",
    ),
    (
        "link_reference_definition",
        "A link reference definition declares a target used elsewhere in the "
        "document and carries no text of its own.",
    ),
    (
        "image",
        "An image has no text to compare; its markup was removed from the "
        "block it appeared in and the surrounding text kept.",
    ),
)
"""Everything this reader can throw away, with the sentence it reports (R3).

Ordered, and reported in this order, so two reads of the same document produce
identical ``dropped`` tuples (N1).
"""


@dataclass(frozen=True, slots=True)
class _Event:
    """One markdown block, as the scanner read it, before any profile is applied.

    The scanner answers only what the syntax states; every field a profile would
    have to decide (label, level, role) is absent on purpose, and is filled in
    by `MarkdownReader._build`.
    """

    type: str
    text: str = ""
    indent: int = 0
    lines: int = 1
    rejoined: bool = False
    quote: bool = False
    atx_level: int = 0
    syntax: str = ""
    marker: str = ""
    ordered: bool = False
    marker_value: str = ""
    depth: int = 0
    info: str = ""
    rows: tuple[tuple[str, ...], ...] = ()
    alignments: tuple[str, ...] = ()


@dataclass(slots=True)
class _OpenItem:
    """One list item the scanner has open, for working out what nests in what.

    :param marker_indent: the column the marker starts in.
    :param content_indent: the column its text starts in, which is what a
        deeper item has to reach to be nested inside this one.
    """

    marker_indent: int
    content_indent: int


class _Scanner:
    """Turns markdown lines into `_Event` objects: the syntax half of the read.

    One scanner per read, so the drop counts and the list stack cannot leak from
    one document into the next (N1).
    """

    def __init__(self, *, profile: Profile | None) -> None:
        self.profile = profile
        self.counts: dict[str, int] = {}

    def dropped(self) -> tuple[Dropped, ...]:
        """Return what this read threw away, in `_DROP_REASONS` order (R3)."""
        return tuple(
            Dropped(kind=kind, count=self.counts[kind], reason=reason)
            for kind, reason in _DROP_REASONS
            if self.counts.get(kind)
        )

    def count(self, kind: str, number: int = 1) -> None:
        """Record ``number`` more dropped things of ``kind``."""
        if number:
            self.counts[kind] = self.counts.get(kind, 0) + number

    def scan(self, lines: list[str], *, quote: bool = False) -> list[_Event]:
        """Read ``lines`` into events, in document order.

        Called again on itself for a blockquote's contents, with ``quote`` set,
        which is what makes a list inside a quotation come out as list items
        that know they are quoted.

        :param lines: the document's lines, already normalised.
        :param quote: whether these lines came out of a blockquote.
        :return: the events, in document order.
        """
        events: list[_Event] = []
        open_items: list[_OpenItem] = []
        index = 0
        while index < len(lines):
            line = lines[index]
            if not line.strip():
                index += 1
                continue
            fence = _FENCE_OPEN.match(line)
            if fence is not None:
                index = self._read_fence(lines, index, fence, events, quote=quote)
                continue
            if _THEMATIC.match(line):
                self.count("thematic_break")
                index += 1
                continue
            atx = _ATX.match(line)
            if atx is not None:
                open_items.clear()
                events.append(self._atx_event(atx, quote=quote))
                index += 1
                continue
            if _QUOTE.match(line):
                index = self._read_quote(lines, index, events)
                open_items.clear()
                continue
            if _HTML_BLOCK.match(line):
                self.count("html_block")
                index = self._skip_to_blank(lines, index)
                continue
            if _LINK_DEFINITION.match(line):
                self.count("link_reference_definition")
                index += 1
                continue
            if self._starts_table(lines, index):
                index = self._read_table(lines, index, events, quote=quote)
                continue
            item = _BULLET.match(line) or _ORDERED.match(line)
            if item is not None:
                index = self._read_list_item(
                    lines, index, item, events, open_items, quote=quote
                )
                continue
            index = self._read_paragraph(lines, index, events, open_items, quote=quote)
        return events

    # --- one construct at a time -------------------------------------------

    def _atx_event(self, match: re.Match[str], *, quote: bool) -> _Event:
        """Build the event for an ATX heading; the hash count is its depth."""
        text = _ATX_CLOSING.sub("", match.group("rest").strip()).strip()
        return _Event(
            type="heading",
            text=self._strip_images(text),
            indent=_indent_of(match.group("indent")),
            quote=quote,
            atx_level=len(match.group("hashes")),
            syntax="atx",
        )

    def _read_fence(
        self,
        lines: list[str],
        index: int,
        match: re.Match[str],
        events: list[_Event],
        *,
        quote: bool,
    ) -> int:
        """Read a fenced block verbatim, up to a closing fence or the end.

        Nothing inside is scanned -- not for markers, not for labels, not for
        images. That is the whole point of a fence, and a clause label inside a
        code sample is a code sample.
        """
        opening = match.group("fence")
        closing = re.compile(rf"^\s*{re.escape(opening[0])}{{{len(opening)},}}\s*$")
        body: list[str] = []
        cursor = index + 1
        while cursor < len(lines) and not closing.match(lines[cursor]):
            body.append(lines[cursor])
            cursor += 1
        events.append(
            _Event(
                type="fence",
                text="\n".join(body),
                indent=_indent_of(match.group("indent")),
                lines=len(body),
                quote=quote,
                syntax="fence",
                info=match.group("info").strip(),
            )
        )
        return min(cursor + 1, len(lines))

    def _read_quote(self, lines: list[str], index: int, events: list[_Event]) -> int:
        """Strip one ``>`` level off a run of lines and scan what is left."""
        inner: list[str] = []
        cursor = index
        while cursor < len(lines):
            match = _QUOTE.match(lines[cursor])
            if match is None:
                break
            inner.append(match.group("text"))
            cursor += 1
        events.extend(self.scan(inner, quote=True))
        return cursor

    def _skip_to_blank(self, lines: list[str], index: int) -> int:
        """Consume lines up to the next blank one, for a construct being dropped."""
        cursor = index
        while cursor < len(lines) and lines[cursor].strip():
            cursor += 1
        return cursor

    def _starts_table(self, lines: list[str], index: int) -> bool:
        """Whether a pipe table's header row starts here.

        A pipe table is a header row *plus* an alignment row of the same width:
        one line with a pipe in it is a sentence with a pipe in it.
        """
        if index + 1 >= len(lines) or "|" not in lines[index]:
            return False
        if "|" not in lines[index + 1]:
            return False
        header = _split_row(lines[index])
        alignments = _alignment_row(_split_row(lines[index + 1]))
        return alignments is not None and len(alignments) == len(header)

    def _read_table(
        self, lines: list[str], index: int, events: list[_Event], *, quote: bool
    ) -> int:
        """Read a pipe table: header, alignment row, then body rows."""
        header = tuple(self._strip_images(cell) for cell in _split_row(lines[index]))
        alignments = _alignment_row(_split_row(lines[index + 1]))
        assert alignments is not None  # _starts_table checked it
        rows: list[tuple[str, ...]] = [header]
        cursor = index + 2
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip() or "|" not in line or _starts_block(line):
                break
            rows.append(tuple(self._strip_images(cell) for cell in _split_row(line)))
            cursor += 1
        events.append(
            _Event(
                type="table",
                indent=_indent_of(lines[index]),
                lines=cursor - index,
                quote=quote,
                syntax="pipe_table",
                rows=tuple(rows),
                alignments=alignments,
            )
        )
        return cursor

    def _read_list_item(
        self,
        lines: list[str],
        index: int,
        match: re.Match[str],
        events: list[_Event],
        open_items: list[_OpenItem],
        *,
        quote: bool,
    ) -> int:
        """Read one list item, its lazy continuation lines and its nesting depth.

        Nesting is indentation: an item nests inside the innermost open item
        whose *content* it reaches. Its own lines are then re-joined by the
        plain-text reader's wrap rule, so an item wrapped across two lines is
        one block here exactly as it is there, and a line that rule refuses to
        join becomes a paragraph under the item rather than being glued into it.
        """
        marker_indent = _indent_of(match.group("indent"))
        groups = match.groupdict()
        marker = groups.get("marker") or ""
        value = groups.get("value") or ""
        delimiter = groups.get("delim") or ""
        ordered = bool(value)
        marker_text = f"{value}{delimiter}" if ordered else marker
        content_indent = marker_indent + len(marker_text) + len(match.group("space"))
        while open_items and marker_indent < open_items[-1].content_indent:
            open_items.pop()
        depth = len(open_items) + 1
        open_items.append(_OpenItem(marker_indent, content_indent))

        body, cursor, _ = self._take_run(lines, index + 1)
        first = " " * content_indent + match.group("text").strip()
        paragraphs = segment("\n".join([first, *body]), profile=self.profile)
        if not paragraphs:
            return cursor
        head = paragraphs[0]
        events.append(
            _Event(
                type="list_item",
                text=head.text,
                indent=content_indent,
                lines=head.lines,
                rejoined=head.rejoined,
                quote=quote,
                syntax="list",
                marker=marker_text,
                ordered=ordered,
                marker_value=value,
                depth=depth,
            )
        )
        for paragraph in paragraphs[1:]:
            events.append(
                _Event(
                    type="paragraph",
                    text=paragraph.text,
                    indent=max(paragraph.indent, content_indent),
                    lines=paragraph.lines,
                    rejoined=paragraph.rejoined,
                    quote=quote,
                )
            )
        return cursor

    def _read_paragraph(
        self,
        lines: list[str],
        index: int,
        events: list[_Event],
        open_items: list[_OpenItem],
        *,
        quote: bool,
    ) -> int:
        """Read a paragraph run, or the setext heading it turns out to be."""
        indent = _indent_of(lines[index])
        while open_items and indent < open_items[-1].content_indent:
            open_items.pop()
        body, cursor, setext_level = self._take_run(lines, index + 1, setext=True)
        run = [lines[index], *body]
        if setext_level:
            events.append(
                _Event(
                    type="heading",
                    text=self._strip_images(" ".join(line.strip() for line in run)),
                    indent=indent,
                    lines=len(run),
                    quote=quote,
                    atx_level=setext_level,
                    syntax="setext",
                )
            )
            return cursor
        for paragraph in segment(
            self._strip_images("\n".join(run)), profile=self.profile
        ):
            events.append(
                _Event(
                    type="paragraph",
                    text=paragraph.text,
                    indent=paragraph.indent,
                    lines=paragraph.lines,
                    rejoined=paragraph.rejoined,
                    quote=quote,
                )
            )
        return cursor

    def _take_run(
        self, lines: list[str], index: int, *, setext: bool = False
    ) -> tuple[list[str], int, int]:
        """Collect the lines that continue the block starting before ``index``.

        A run ends at a blank line, at anything that starts a block of its own
        (which is what stops a list item from swallowing the item below it), at
        a pipe table, and -- for a paragraph -- at a setext underline, which is
        the one place ``---`` means "the line above was a heading" rather than
        "a horizontal rule". That underline is consumed here, so a caller can
        never mistake a rule after a blank line for one.

        :return: the continuation lines, the index to carry on from, and the
            setext heading level the run ended at, or 0 if it did not.
        """
        body: list[str] = []
        cursor = index
        while cursor < len(lines):
            line = lines[cursor]
            if not line.strip():
                break
            if setext:
                underline = _SETEXT.match(line)
                if underline is not None:
                    level = 1 if underline.group("underline")[0] == "=" else 2
                    return body, cursor + 1, level
            if _starts_block(line) or self._starts_table(lines, cursor):
                break
            body.append(line)
            cursor += 1
        return body, cursor, 0

    def _strip_images(self, text: str) -> str:
        """Remove image markup from ``text``, counting what it removed (R3)."""
        stripped, count = _IMAGE.subn("", text)
        self.count("image", count)
        if not count:
            return text
        return re.sub(r"[ \t]{2,}", " ", stripped).strip()


def _starts_block(line: str) -> bool:
    """Whether ``line`` opens a markdown block rather than continuing one."""
    return bool(
        _THEMATIC.match(line)
        or _ATX.match(line)
        or _FENCE_OPEN.match(line)
        or _QUOTE.match(line)
        or _HTML_BLOCK.match(line)
        or _LINK_DEFINITION.match(line)
        or _BULLET.match(line)
        or _ORDERED.match(line)
    )


def _indent_of(text: str) -> int:
    """Return the width of ``text``'s leading whitespace, tabs counted as four."""
    width = 0
    for char in text:
        if char == "\t":
            width += _TAB_WIDTH
        elif char == " ":
            width += 1
        else:
            break
    return width


def _split_row(line: str) -> list[str]:
    """Split one pipe-table row into its cells, honouring ``\\|`` escapes."""
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells: list[str] = []
    buffer: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            buffer.append(char if char == "|" else "\\" + char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "|":
            cells.append("".join(buffer))
            buffer = []
        else:
            buffer.append(char)
    if escaped:
        buffer.append("\\")
    cells.append("".join(buffer))
    return [cell.strip() for cell in cells]


def _alignment_row(cells: list[str]) -> tuple[str, ...] | None:
    """Read a pipe table's alignment row, or ``None`` if this is not one.

    The row itself never becomes a block: it is the table's punctuation, it
    carries no text, and reporting it as dropped would claim content was lost
    when none was. What it says survives as the table's ``alignments``.
    """
    alignments: list[str] = []
    if not cells:
        return None
    for cell in cells:
        body = cell.strip()
        if not _ALIGNMENT_CELL.match(body):
            return None
        left, right = body.startswith(":"), body.endswith(":")
        if left and right:
            alignments.append("center")
        elif right:
            alignments.append("right")
        elif left:
            alignments.append("left")
        else:
            alignments.append("default")
    return tuple(alignments)


@dataclass(slots=True)
class _Node:
    """A block under construction, frozen bottom-up by `finish` when it is done.

    The same device the plain-text reader uses, and for the same reason:
    `redlines.blocks.Block` is frozen (ADR-0023), so a tree with children added
    as they are read has to be assembled in something that is not.
    """

    kind: BlockKind
    text: str = ""
    label: str | None = None
    level: int = 0
    matched_by: str = MATCHED_BY_FALLBACK
    confidence: float = 0.0
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[_Node] = field(default_factory=list)
    indent: int = 0
    rank: int = 0

    def finish(self) -> Block:
        """Return this node and its descendants as frozen `Block` objects."""
        return Block(
            kind=self.kind,
            text=self.text,
            label=self.label,
            level=self.level,
            children=tuple(child.finish() for child in self.children),
            attrs=self.attrs,
            matched_by=self.matched_by,
            confidence=self.confidence,
        )


class MarkdownReader:
    """Markdown into the same block tree the plain-text reader builds (R5, D16).

    Registered for the ``"markdown"`` format, which is what
    `redlines.readers.detect.detect_format` returns for ``.md`` and
    ``.markdown``.

    The reader holds no state between reads: the scanner, the numbering stack
    and the open-block stack all live inside one `read` call, so the same input
    and profile always give the same tree (N1).
    """

    name = "markdown"
    formats = ("markdown",)

    def read(
        self,
        source: str | bytes,
        *,
        profile: Profile | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> BlockTree:
        """Read ``source`` into a tree of headings, list items, tables and text.

        :param source: the document, as text or as UTF-8 bytes.
        :param profile: the structure profile (ADR-0006). ``None`` keeps
            everything the *syntax* states -- headings, list nesting, tables,
            fences -- and claims nothing else: no clause labels, no numbering
            levels, no heading scoring, every unlabelled paragraph a
            ``fallback``. That is the same bargain the plain-text reader's
            degrade path makes, with the part markdown states for itself kept.
        :param max_chars: the input size cap (ADR-0028). This reader is the
            enforcement point, as the plain-text one is: profile patterns run
            against this text, and a pattern cannot be bounded once it starts.
        :return: the document as a `redlines.blocks.BlockTree`, addressed, with
            horizontal rules, HTML blocks, link reference definitions, images
            and control characters reported in ``dropped``.
        :raises ValueError: if the source is over ``max_chars``, or is bytes
            that are not UTF-8.
        """
        text = decode_source(source, reader=self.name)
        check_size(text, max_chars=max_chars, reader=self.name)
        normalised, controls = normalise(text)
        scanner = _Scanner(profile=profile)
        scanner.count("control_character", controls)
        lines = normalised.split("\n")
        if lines and lines[-1] == "":
            # The newline that ended the last line is not a line of its own, and
            # an unclosed fence would otherwise keep it as a blank final line of
            # code.
            lines.pop()
        events = scanner.scan(lines)
        return BlockTree.build(
            self._build(events, profile=profile), dropped=scanner.dropped()
        )

    # --- the tree ----------------------------------------------------------

    def _build(self, events: list[_Event], *, profile: Profile | None) -> Block:
        """Turn the scanner's events into the document block.

        The open-block stack and its ranks are the plain-text reader's, because
        the two trees have to nest the same way: a heading opens a ``section``
        that holds it and everything under it, a labelled block closes its peers
        and nests under its parent, and a numbering-resetting heading closes
        everything.
        """
        stack = HierarchyStack()
        root = _Node(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            confidence=1.0,
            rank=-1,
        )
        open_nodes: list[_Node] = [root]
        headings = 0
        labelled = 0
        # Where the open-block stack stood when the current run of quoted
        # events began, or 0 outside a quotation. Quoted blocks nest among
        # themselves above this mark and never pop below it, and the first
        # unquoted event drops everything the quotation opened: that is what
        # keeps a quoted excerpt beside the document rather than inside it.
        quote_floor = 0

        for position, event in enumerate(events):
            if event.quote:
                quote_floor = quote_floor or len(open_nodes)
            elif quote_floor:
                del open_nodes[quote_floor:]
                quote_floor = 0
            floor = quote_floor or 1
            if event.type == "fence":
                open_nodes[-1].children.append(self._fence_node(event, open_nodes[-1]))
                continue
            if event.type == "table":
                open_nodes[-1].children.append(self._table_node(event, open_nodes[-1]))
                continue
            if event.type == "heading":
                if event.quote:
                    open_nodes[-1].children.append(
                        self._quoted_heading_node(
                            event,
                            stack=stack,
                            profile=profile,
                            parent=open_nodes[-1],
                        )
                    )
                    continue
                node = self._heading_node(event, stack=stack, profile=profile)
                headings += 1
                if node.label is not None:
                    labelled += 1
                self._open_section(open_nodes, node, floor=floor)
                continue
            if event.type == "list_item":
                node = self._item_node(event, stack=stack, profile=profile)
                if node.label is not None and node.matched_by.startswith("label:"):
                    labelled += 1
                self._open_item(open_nodes, node, floor=floor)
                continue

            # A paragraph is the one event whose kind the syntax does not
            # settle: the profile decides whether it is a heading nobody marked
            # up, a labelled clause, a continuation of the block above, or
            # nothing anyone recognised.
            placement, score, reset = self._paragraph_decision(
                events, position, stack=stack, profile=profile
            )
            if placement is not None:
                labelled += 1
            if reset is not None and not event.quote:
                stack.reset()
                headings += 1
                self._open_section(
                    open_nodes,
                    self._scored_heading_node(
                        event, placement, score, reset=reset, level=0, rank=0
                    ),
                    floor=floor,
                )
            elif score.is_heading and not event.quote:
                headings += 1
                level = placement.level if placement else 0
                self._open_section(
                    open_nodes,
                    self._scored_heading_node(
                        event,
                        placement,
                        score,
                        reset=None,
                        level=level,
                        rank=level + 1 if placement else 1,
                    ),
                    floor=floor,
                )
            elif placement is not None:
                self._open_item(
                    open_nodes,
                    self._labelled_paragraph_node(event, placement, score),
                    floor=floor,
                )
            else:
                open_nodes[-1].children.append(
                    self._body_node(event, score, parent=open_nodes[-1])
                )

        root.attrs = {
            "reader": self.name,
            "profile": profile.name if profile is not None else None,
            "blocks": len(events),
            "labelled": labelled,
            "headings": headings,
            "numbering_resets": stack.resets,
        }
        return root.finish()

    def _paragraph_decision(
        self,
        events: list[_Event],
        position: int,
        *,
        stack: HierarchyStack,
        profile: Profile | None,
    ) -> tuple[Placement | None, HeadingScore, str | None]:
        """Apply stages two, three and five to one paragraph, as plain text does.

        A quoted paragraph is previewed rather than placed, for the same reason
        it never resets numbering: its label belongs to the document it was
        quoted from, and committing it would leave this document's numbering
        run answering to a foreign one.
        """
        event = events[position]
        reset = None if event.quote else heading_reset_name(event.text, profile=profile)
        candidates = label_candidates(event.text, profile=profile)
        placement: Placement | None = None
        if candidates:
            placement = (
                stack.preview(candidates, indent=event.indent)
                if reset or event.quote
                else stack.place(candidates, indent=event.indent)
            )
        body = placement.match.text if placement else event.text
        score = self._score(
            body,
            profile=profile,
            next_label=self._next_label(
                events, position, stack=stack, placement=placement, profile=profile
            ),
        )
        return placement, score, reset

    def _score(
        self, text: str, *, profile: Profile | None, next_label: str = NEXT_NONE
    ) -> HeadingScore:
        """Score a paragraph as an unmarked heading -- but only under a profile.

        With no profile there is nothing to score against and nothing to be
        right about: markdown states its headings with ``#``, and inventing one
        from the shape of a line is exactly the claim the degrade path exists
        not to make.
        """
        if profile is None:
            return HeadingScore(0.0, ("no_profile",), HEADING_THRESHOLD)
        return heading_score(text, rule=profile.heading_rule, next_label=next_label)

    def _next_label(
        self,
        events: list[_Event],
        position: int,
        *,
        stack: HierarchyStack,
        placement: Placement | None,
        profile: Profile | None,
    ) -> str:
        """Classify what follows this paragraph, for the heading score (stage 5).

        The lookahead is one text-bearing event and costs nothing: its label is
        placed against a *copy* of the stack, so asking the question does not
        answer it.
        """
        following = next(
            (
                event
                for event in events[position + 1 :]
                if event.type in ("paragraph", "list_item", "heading")
            ),
            None,
        )
        if following is None or following.type == "heading":
            return NEXT_NONE
        candidates = label_candidates(following.text, profile=profile)
        if not candidates:
            return NEXT_NONE
        preview = stack.preview(candidates, indent=following.indent)
        if placement is None:
            return NEXT_DEEPER
        return NEXT_DEEPER if preview.level > placement.level else NEXT_PEER

    # --- one node at a time ------------------------------------------------

    def _heading_node(
        self, event: _Event, *, stack: HierarchyStack, profile: Profile | None
    ) -> _Node:
        """Build the node for a heading the syntax stated (``#`` or an underline).

        ``matched_by`` is ``markdown:atx`` at confidence 1.0 whatever else is
        true, because the syntax states that this is a heading and the syntax
        cannot be wrong about it (ADR-0030). What the *profile* adds -- the
        clause label in the heading's text, its depth in the document's own
        numbering, whether it restarts numbering -- rides along in ``label``,
        ``level`` and ``attrs``.

        **``level`` follows the label, not the hash count**, where the heading
        carries one. That is the PRD § 6b promise: ``## 7. Termination`` and a
        plain-text ``7. TERMINATION`` are the same clause at the same depth of
        the same agreement, and a ``level`` that said 2 here and 1 there would
        make the twin documents incomparable for the sake of restating a number
        that ``attrs["atx_level"]`` already carries. The hash count is what it
        was always good for instead: it is a floor on where the heading *nests*,
        so an ``h2`` never escapes the ``h1`` above it.

        Only ever called for a heading of *this* document: a heading inside a
        blockquote goes to `MarkdownReader._quoted_heading_node` instead.
        """
        reset = heading_reset_name(event.text, profile=profile)
        candidates = label_candidates(event.text, profile=profile)
        placement: Placement | None = None
        if candidates:
            placement = (
                stack.preview(candidates, indent=event.indent)
                if reset
                else stack.place(candidates, indent=event.indent)
            )
        if reset is not None:
            stack.reset()
            level, rank = 0, 0
        elif placement is not None:
            level = placement.level
            rank = max(event.atx_level, level + 1)
        else:
            level, rank = 0, event.atx_level

        attrs: dict[str, Any] = {
            "indent": event.indent,
            "atx_level": event.atx_level,
            "markdown": event.syntax,
        }
        if placement is not None:
            attrs.update(_label_attrs(placement))
            attrs["label_confidence"] = placement.confidence
        if reset is not None:
            attrs["heading_reset"] = reset
        return _Node(
            kind=BlockKind.HEADING,
            text=placement.match.text if placement else event.text,
            label=placement.match.label if placement else None,
            level=level,
            matched_by=matched_by_markdown(event.syntax),
            confidence=1.0,
            attrs=attrs,
            indent=event.indent,
            rank=rank,
        )

    def _quoted_heading_node(
        self,
        event: _Event,
        *,
        stack: HierarchyStack,
        profile: Profile | None,
        parent: _Node,
    ) -> _Node:
        """Build the node for a heading inside a blockquote: evidence, not structure.

        ``## Schedule 9`` inside a quotation is a heading of the document being
        quoted, and that document's structure is not this one's. Promoting it
        would open a ``section`` that every clause after the quotation fell
        into, and letting it reset numbering would restart this agreement's
        clause run on somebody else's schedule -- so it does neither, which is
        what the module docstring promises about quoted material.

        What survives is everything that is true: the text, the label the
        profile reads in it (placed against a *copy* of the stack, so reading
        it does not commit it), the markdown provenance in ``matched_by``, and
        the hash count in ``attrs["atx_level"]``. The kind is ``paragraph``,
        because a quoted heading heads nothing here -- and a ``heading`` block
        would otherwise turn up in the breadcrumb of the clauses after it.
        """
        candidates = label_candidates(event.text, profile=profile)
        placement = (
            stack.preview(candidates, indent=event.indent) if candidates else None
        )
        attrs: dict[str, Any] = {
            "indent": event.indent,
            "atx_level": event.atx_level,
            "markdown": event.syntax,
            "quote": True,
            "quoted_heading": True,
        }
        if placement is not None:
            attrs.update(_label_attrs(placement))
            attrs["label_confidence"] = placement.confidence
        return _Node(
            kind=BlockKind.PARAGRAPH,
            text=placement.match.text if placement else event.text,
            label=placement.match.label if placement else None,
            level=parent.level,
            matched_by=matched_by_markdown(event.syntax),
            confidence=1.0,
            attrs=attrs,
            indent=event.indent,
        )

    def _item_node(
        self, event: _Event, *, stack: HierarchyStack, profile: Profile | None
    ) -> _Node:
        """Build the node for a list item, labelled by its text or by its marker.

        Two things can label a list item, and they are not the same claim:

        - the *text* carries a clause label the profile knows (``- 1.1 The
          Supplier shall…``). Then the label, the level and the confidence are
          the profile's and the stack's, exactly as in plain text, and
          ``matched_by`` is ``label:<pattern>``. The list's own nesting is kept
          in ``attrs["list_depth"]``, and that nesting is a *floor* on the
          label's level: the syntax states how deep this item sits and cannot
          be wrong about it (ADR-0030), while the stack only infers, and a
          markdown marker never reaches the stack for a nested alpha label to
          be measured against. So a correctly indented ``- (a) …`` under
          ``1. Introduction`` stays that item's child. Where the floor lifted
          the level, ``attrs["label_level"]`` keeps what the stack said;
        - nothing in the text does (``1. Definitions``, where ``1.`` is the
          marker markdown renumbers for you). Then the marker itself is the
          label -- it is what the document shows a reader, and it is what the
          plain-text twin would have carried -- the level is the list's nesting
          depth, and ``matched_by`` is ``markdown:list`` at confidence 1.0,
          because the syntax stated both. (The built-in ``markdown`` profile's
          comment describes this case as arriving "with no label"; the reader
          labels it, because the plain-text twin ``1. Definitions`` carries
          ``1`` and the two trees have to agree. Correcting that comment is
          #101's file, not this one's.)

        A quoted item is *previewed* against the numbering stack rather than
        placed on it: somebody else's clause number must not become part of
        this document's numbering run.
        """
        candidates = label_candidates(event.text, profile=profile)
        placement = None
        if candidates:
            place = stack.preview if event.quote else stack.place
            placement = place(candidates, indent=event.indent)
        attrs: dict[str, Any] = {
            "indent": event.indent,
            "markdown": event.syntax,
            "list_marker": event.marker,
            "list_ordered": event.ordered,
            "list_depth": event.depth,
        }
        if event.rejoined:
            attrs["rejoined_lines"] = event.lines
        if event.quote:
            attrs["quote"] = True
        if placement is not None:
            attrs.update(_label_attrs(placement))
            level = max(placement.level, event.depth)
            if level != placement.level:
                attrs["label_level"] = placement.level
                attrs["level_source"] = "list_depth"
            return _Node(
                kind=BlockKind.LIST_ITEM,
                text=placement.match.text,
                label=placement.match.label,
                level=level,
                matched_by=matched_by_label(placement.match.name),
                confidence=placement.confidence,
                attrs=attrs,
                indent=event.indent,
                rank=level + 1,
            )
        if event.ordered:
            attrs["label_source"] = "list_marker"
        return _Node(
            kind=BlockKind.LIST_ITEM,
            text=event.text,
            label=event.marker_value if event.ordered else None,
            level=event.depth,
            matched_by=matched_by_markdown(event.syntax),
            confidence=1.0,
            attrs=attrs,
            indent=event.indent,
            rank=event.depth + 1,
        )

    def _scored_heading_node(
        self,
        event: _Event,
        placement: Placement | None,
        score: HeadingScore,
        *,
        reset: str | None,
        level: int,
        rank: int,
    ) -> _Node:
        """Build the node for a heading nobody marked up, found by the profile.

        The leftover case the built-in ``markdown`` profile's ``heading_rule``
        exists for. Recognised by a profile rather than by the syntax, so it
        records ``heading:<signal>`` or ``label:<pattern>`` with the heuristic's
        own confidence, exactly as the plain-text reader does.
        """
        attrs: dict[str, Any] = {"indent": event.indent}
        if placement is not None:
            attrs.update(_label_attrs(placement))
        attrs.update(_heading_attrs(score, reset=reset))
        if event.quote:
            attrs["quote"] = True
        if reset is not None:
            matched_by, confidence = (
                matched_by_heading(reset),
                CONFIDENCE_RESET_HEADING,
            )
        elif placement is not None:
            matched_by, confidence = (
                matched_by_label(placement.match.name),
                placement.confidence,
            )
        else:
            matched_by, confidence = matched_by_heading("score"), score.confidence
        return _Node(
            kind=BlockKind.HEADING,
            text=placement.match.text if placement else event.text,
            label=placement.match.label if placement else None,
            level=level,
            matched_by=matched_by,
            confidence=confidence,
            attrs=attrs,
            indent=event.indent,
            rank=rank,
        )

    def _labelled_paragraph_node(
        self, event: _Event, placement: Placement, score: HeadingScore
    ) -> _Node:
        """Build the node for a paragraph whose text carries a clause label.

        A markdown contract writes ``7.2 The Supplier shall…`` as an ordinary
        paragraph at least as often as it writes it as a list item, and the
        plain-text reader calls that a ``list_item``. So does this one, or the
        twin trees would differ on kind for the same clause.
        """
        attrs: dict[str, Any] = {"indent": event.indent}
        attrs.update(_label_attrs(placement))
        attrs.update(_heading_attrs(score, reset=None))
        if event.rejoined:
            attrs["rejoined_lines"] = event.lines
        if event.quote:
            attrs["quote"] = True
        return _Node(
            kind=BlockKind.LIST_ITEM,
            text=placement.match.text,
            label=placement.match.label,
            level=placement.level,
            matched_by=matched_by_label(placement.match.name),
            confidence=placement.confidence,
            attrs=attrs,
            indent=event.indent,
            rank=placement.level + 1,
        )

    def _body_node(self, event: _Event, score: HeadingScore, *, parent: _Node) -> _Node:
        """Build the node for an unlabelled paragraph: a continuation or a fallback."""
        open_label = parent.level if parent.kind is BlockKind.LIST_ITEM else None
        decision = continuation_for(
            open_label_level=open_label,
            heading=score,
            indent=event.indent,
            label_indent=parent.indent,
        )
        attrs: dict[str, Any] = {
            "indent": event.indent,
            "continuation": decision.attaches,
            "continuation_reason": decision.reason,
        }
        attrs.update(_heading_attrs(score, reset=None))
        if event.rejoined:
            attrs["rejoined_lines"] = event.lines
        if event.quote:
            attrs["quote"] = True
        return _Node(
            kind=BlockKind.PARAGRAPH,
            text=event.text,
            level=parent.level if decision.attaches else 0,
            matched_by=(
                MATCHED_BY_CONTINUATION if decision.attaches else MATCHED_BY_FALLBACK
            ),
            confidence=decision.confidence,
            attrs=attrs,
            indent=event.indent,
        )

    def _fence_node(self, event: _Event, parent: _Node) -> _Node:
        """Build the node for a fenced block: text kept exactly as it was written.

        A ``paragraph``, not a kind of its own: `redlines.blocks.BlockKind` is
        closed (R1) and code is not in it. What it *is* goes in ``attrs`` --
        the info string the fence declared, or an empty string where it declared
        none -- and the semantic pass is what may later call it ``code``
        (ADR-0005's open role vocabulary), because that is a semantic question
        and this reader answers structural ones.
        """
        return _Node(
            kind=BlockKind.PARAGRAPH,
            text=event.text,
            level=parent.level,
            matched_by=matched_by_markdown(event.syntax),
            confidence=1.0,
            attrs={
                "indent": event.indent,
                "markdown": event.syntax,
                "fence": event.info,
                "fence_lines": event.lines,
                **({"quote": True} if event.quote else {}),
            },
            indent=event.indent,
        )

    def _table_node(self, event: _Event, parent: _Node) -> _Node:
        """Build a ``table`` of ``row`` of ``cell``, header row flagged (R1).

        The alignment row is not a row: it is the syntax that *makes* this a
        table, it has no text, and it is reported as the table's ``alignments``
        rather than as something dropped -- nothing was.
        """
        table = _Node(
            kind=BlockKind.TABLE,
            level=parent.level,
            matched_by=matched_by_markdown(event.syntax),
            confidence=1.0,
            attrs={
                "indent": event.indent,
                "markdown": event.syntax,
                "alignments": list(event.alignments),
                "columns": len(event.alignments),
                "rows": len(event.rows),
                **({"quote": True} if event.quote else {}),
            },
            indent=event.indent,
        )
        for number, row in enumerate(event.rows):
            header = number == 0
            row_node = _Node(
                kind=BlockKind.ROW,
                level=parent.level,
                matched_by=matched_by_markdown("table_row"),
                confidence=1.0,
                attrs={
                    "header": header,
                    "row": number,
                    **({"ragged": True} if len(row) != len(event.alignments) else {}),
                },
            )
            cells = list(row) + [""] * max(0, len(event.alignments) - len(row))
            for column, cell in enumerate(cells):
                row_node.children.append(
                    _Node(
                        kind=BlockKind.CELL,
                        text=cell,
                        level=parent.level,
                        matched_by=matched_by_markdown("table_cell"),
                        confidence=1.0,
                        attrs={
                            "header": header,
                            "column": column,
                            "alignment": (
                                event.alignments[column]
                                if column < len(event.alignments)
                                else "default"
                            ),
                        },
                    )
                )
            table.children.append(row_node)
        return table

    # --- the open-block stack ----------------------------------------------

    def _open_section(
        self, open_nodes: list[_Node], heading: _Node, *, floor: int = 1
    ) -> None:
        """Close what the heading outranks, then open a section around it."""
        self._close_to(open_nodes, heading.rank, floor=floor)
        section = _Node(
            kind=BlockKind.SECTION,
            level=heading.level,
            matched_by=heading.matched_by,
            confidence=heading.confidence,
            attrs={"opened_by": "heading"},
            indent=heading.indent,
            rank=heading.rank,
        )
        open_nodes[-1].children.append(section)
        section.children.append(heading)
        open_nodes.append(section)

    def _open_item(
        self, open_nodes: list[_Node], item: _Node, *, floor: int = 1
    ) -> None:
        """Close every open block at or below this item's level, then open it."""
        self._close_to(open_nodes, item.rank, floor=floor)
        open_nodes[-1].children.append(item)
        open_nodes.append(item)

    def _close_to(self, open_nodes: list[_Node], rank: int, *, floor: int = 1) -> None:
        """Pop every open block a new block of this rank ends.

        :param open_nodes: the open-block stack, root first.
        :param rank: the rank of the block about to open.
        :param floor: how many blocks are held open whatever their rank. 1 is
            the root alone; inside a quotation it is the whole stack the
            quotation found open, so nothing quoted can close a real block.
        """
        while len(open_nodes) > floor and open_nodes[-1].rank >= rank:
            open_nodes.pop()


register_reader(MarkdownReader())
