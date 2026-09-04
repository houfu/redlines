"""The block model: a document as an ordered tree of plain data (R1, R1a, R3).

A document read by any reader (:mod:`redlines.readers`) becomes a
`BlockTree`: a single `Block` of kind ``document`` holding an ordered tree of
children. Two layers live on every block, per ADR-0005:

- a **minimal structural core** with a closed ``kind`` vocabulary
  (`BlockKind`), the block's ``text``, its document ``label`` where it has
  one, a ``level``, a ``path`` derived from its position, and a free-form
  ``attrs`` mapping for reader-specific detail;
- an **open semantic layer** -- an optional ``role`` and a tuple of `Span`
  objects -- whose vocabularies are *recommended* (`RECOMMENDED_ROLES`,
  `RECOMMENDED_SPAN_TYPES`) and never enforced.

Every block also records how it was recognised (``matched_by``) and how sure
the reader is (``confidence``), and every tree reports what its reader threw
away (``dropped``) and how many blocks fell through to a plain paragraph
(``fallback_count``). See ADR-0030 for what those mean and
``docs/adr/0029-address-syntax.md`` for the address syntax ``path`` uses.

Blocks are frozen and their children are a tuple, so a tree is built bottom
up and then addressed in one pass::

    from redlines.blocks import Block, BlockKind, BlockTree

    root = Block(
        kind=BlockKind.DOCUMENT,
        matched_by="document",
        confidence=1.0,
        children=(
            Block(kind=BlockKind.HEADING, text="1. Term", matched_by="heading:atx"),
            Block(kind=BlockKind.PARAGRAPH, text="This agreement starts today."),
        ),
    )
    tree = BlockTree.build(root)
    tree.root.children[1].path  # '/paragraph[1]'

`BlockTree.build` is the normal way in: it calls `assign_paths`, which walks a
path-less tree and returns a copy with every ``path`` filled in. Nothing in
this module parses, matches or scores anything -- readers do that, and
alignment reads only ``text`` (R2).
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from typing import Any

__all__ = [
    "BLOCK_KINDS",
    "Block",
    "BlockKind",
    "BlockTree",
    "Dropped",
    "MATCHED_BY_CONTINUATION",
    "MATCHED_BY_DOCUMENT",
    "MATCHED_BY_FALLBACK",
    "MATCHED_BY_FAMILIES",
    "RECOMMENDED_ROLES",
    "RECOMMENDED_SPAN_TYPES",
    "ROOT_PATH",
    "Span",
    "assign_paths",
    "block_at",
    "child_path",
    "heading_breadcrumb",
    "iter_blocks",
    "matched_by_heading",
    "matched_by_label",
    "matched_by_markdown",
]


class BlockKind(str, Enum):
    """The closed structural vocabulary (R1, ADR-0005).

    A ``str`` enum, so ``block.kind == "paragraph"`` is true and a kind
    serialises as its own name. The set is closed on purpose: format-specific
    detail belongs in ``attrs`` and meaning belongs in ``role``, neither of
    which needs a new kind. ``unknown`` is the escape hatch for a reader that
    produced a block it cannot classify.
    """

    DOCUMENT = "document"
    SECTION = "section"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST_ITEM = "list_item"
    TABLE = "table"
    ROW = "row"
    CELL = "cell"
    UNKNOWN = "unknown"

    def __str__(self) -> str:
        """Return the kind's wire name, so f-strings and paths agree."""
        return self.value


BLOCK_KINDS: tuple[str, ...] = tuple(kind.value for kind in BlockKind)
"""Every `BlockKind` value, in declaration order."""


RECOMMENDED_ROLES: tuple[str, ...] = (
    "title",
    "recital",
    "definitions",
    "definition",
    "clause",
    "sub_clause",
    "schedule",
    "signature",
    "note",
    "quote",
    "code",
    "boilerplate",
)
"""The recommended ``role`` vocabulary from ADR-0005 -- documented, not enforced.

``role`` is an open string. These are the names the built-in profiles and
heuristics use, and the names a consumer can expect to see most often; a
profile is free to invent its own, which is the whole point of an open
semantic layer. Nothing in redlines rejects a role outside this tuple.
"""

RECOMMENDED_SPAN_TYPES: tuple[str, ...] = (
    "emphasis",
    "defined_term",
    "cross_reference",
    "party",
    "date",
    "amount",
    "citation",
)
"""The recommended `Span` ``type`` vocabulary from ADR-0005 -- documented, not enforced.

Same rule as `RECOMMENDED_ROLES`: these are the types the built-in span
extractors emit, and a profile may emit any other string.
"""


MATCHED_BY_FALLBACK = "fallback"
"""``matched_by`` for a block that matched no rule and became a plain paragraph.

Reserved and exact: `BlockTree.fallback_count` counts blocks whose
``matched_by`` is this string and no others (ADR-0030).
"""

MATCHED_BY_CONTINUATION = "continuation"
"""``matched_by`` for an unlabelled block attached to the labelled block above it."""

MATCHED_BY_DOCUMENT = "document"
"""``matched_by`` for the tree's root, which no rule recognises: it is the tree.

Reserved so the root does not have to claim it fell through, which would make
every `BlockTree.fallback_count` one too high. `Block` applies it for you: a
block of kind ``document`` that says nothing about how it was recognised gets
this value rather than `MATCHED_BY_FALLBACK`, so forgetting the keyword cannot
silently inflate the count.
"""

MATCHED_BY_FAMILIES: tuple[str, ...] = ("label", "heading", "markdown")
"""Recommended prefixes for a ``family:detail`` ``matched_by`` value.

``label:<label pattern name>``, ``heading:<signal>``, ``markdown:<syntax>``.
Like the role vocabulary, this is a recommendation: a third-party reader may
use a family of its own (see ``examples/custom_reader.py``). Only
`MATCHED_BY_FALLBACK`, `MATCHED_BY_CONTINUATION` and `MATCHED_BY_DOCUMENT`
carry fixed meaning.
"""


def matched_by_label(name: str) -> str:
    """Build the ``matched_by`` value for a profile label pattern.

    :param name: the ``name`` of the profile's `redlines.profiles.LabelPattern`.
    :return: ``"label:<name>"``.
    """
    return f"label:{name}"


def matched_by_heading(signal: str) -> str:
    """Build the ``matched_by`` value for a heading recognised by a signal.

    :param signal: the signal that decided it -- ``"all_caps"``, ``"reset"``,
        ``"atx"`` and so on.
    :return: ``"heading:<signal>"``.
    """
    return f"heading:{signal}"


def matched_by_markdown(syntax: str) -> str:
    """Build the ``matched_by`` value for a block recognised by markdown syntax.

    :param syntax: the syntax that carried it -- ``"atx"``, ``"fence"``,
        ``"pipe_table"``, ``"bullet"`` and so on.
    :return: ``"markdown:<syntax>"``.
    """
    return f"markdown:{syntax}"


ROOT_PATH = "/"
"""The document root's address (ADR-0029). Every other path hangs off it."""

_SEGMENT_RE = re.compile(r"(?P<kind>[a-z_]+)\[(?P<index>[1-9][0-9]*)\]")


def _coerce_kind(kind: BlockKind | str) -> BlockKind:
    """Return ``kind`` as a `BlockKind`, or raise a `ValueError` naming the set."""
    if isinstance(kind, BlockKind):
        return kind
    try:
        return BlockKind(kind)
    except ValueError:
        allowed = ", ".join(BLOCK_KINDS)
        raise ValueError(
            f"{kind!r} is not a block kind; the closed set is: {allowed}"
        ) from None


@dataclass(frozen=True, slots=True)
class Span:
    """A typed range of characters inside one block's ``text`` (R1a, ADR-0005).

    Offsets are into the owning block's ``text``, never into the document, so
    a span survives a block moving. Spans are output, not input: they never
    drive alignment or diffing (R2). A span on its own only knows that its
    ``end`` is not before its ``start``; that it lies *within* the text is
    `Block`'s to check, because only the block has the text.

    :param type: an open span type; see `RECOMMENDED_SPAN_TYPES`.
    :param start: the first character offset, counting from 0.
    :param end: the offset one past the last character, so ``text[start:end]``
        is the span.
    :param value: what the span *means* where that differs from what it says --
        the referenced label for a ``cross_reference``, the normalised term for
        a ``defined_term``. ``None`` when the text speaks for itself.
    """

    type: str
    start: int
    end: int
    value: str | None = None

    def __post_init__(self) -> None:
        """Reject offsets that cannot describe a range."""
        if not self.type:
            raise ValueError("a span needs a type")
        if self.start < 0:
            raise ValueError(f"span start must not be negative, got {self.start}")
        if self.end < self.start:
            raise ValueError(
                f"span end {self.end} is before its start {self.start}",
            )

    def to_dict(self) -> dict[str, Any]:
        """Return this span as a JSON-serialisable dict.

        :return: a dict with the keys ``type``, ``start``, ``end`` and ``value``,
            always in that order.
        """
        return {
            "type": self.type,
            "start": self.start,
            "end": self.end,
            "value": self.value,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Span:
        """Rebuild a span from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `Span`.
        :raises ValueError: if a key is missing or unrecognised.
        """
        _reject_unknown_keys(data, {"type", "start", "end", "value"}, "span")
        try:
            return cls(
                type=str(data["type"]),
                start=int(data["start"]),
                end=int(data["end"]),
                value=data.get("value"),
            )
        except KeyError as missing:
            raise ValueError(f"span is missing the key {missing.args[0]!r}") from None


@dataclass(frozen=True, slots=True)
class Dropped:
    """One kind of content a reader did not carry into the tree (R3).

    Readers disclose scope rather than pretending completeness: a reader that
    ignores footnotes says so, with a count, so a consumer can decide whether
    the comparison still answers its question.

    :param kind: what was dropped, in the reader's own words
        (``"footnote"``, ``"image"``, ``"unknown_tag"``).
    :param count: how many were dropped; must not be negative.
    :param reason: why, in one short sentence a user can act on.
    """

    kind: str
    count: int
    reason: str

    def __post_init__(self) -> None:
        """Reject a report that cannot be true."""
        if not self.kind:
            raise ValueError("a dropped report needs a kind")
        if self.count < 0:
            raise ValueError(f"dropped count must not be negative, got {self.count}")

    def to_dict(self) -> dict[str, Any]:
        """Return this report as a JSON-serialisable dict.

        :return: a dict with the keys ``kind``, ``count`` and ``reason``.
        """
        return {"kind": self.kind, "count": self.count, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Dropped:
        """Rebuild a dropped report from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `Dropped`.
        :raises ValueError: if a key is missing or unrecognised.
        """
        _reject_unknown_keys(data, {"kind", "count", "reason"}, "dropped report")
        try:
            return cls(
                kind=str(data["kind"]),
                count=int(data["count"]),
                reason=str(data["reason"]),
            )
        except KeyError as missing:
            raise ValueError(
                f"dropped report is missing the key {missing.args[0]!r}"
            ) from None


@dataclass(frozen=True, slots=True)
class Block:
    """One node of the document tree (R1, R1a).

    Frozen, so a tree cannot be mutated by accident during alignment
    (ADR-0023); ``children`` and ``spans`` are tuples for the same reason.
    Build a tree bottom up and hand the root to `BlockTree.build`, which
    assigns every ``path``.

    :param kind: the structural kind, from the closed `BlockKind` set. A plain
        string is accepted and converted; anything outside the set raises.
    :param text: the block's own text, and the only thing alignment compares
        (R2). Container blocks (``document``, ``section``, ``table``, ``row``)
        normally leave it empty and carry their text in their children.
    :param label: the document's own label for this block where it has one --
        ``"7.2"``, ``"(a)"``, ``"Schedule 2"`` -- stripped of surrounding
        punctuation and never encoded into ``path``.
    :param level: the block's depth in the *document's own* numbering, as the
        reader inferred it. Distinct from the depth of ``path``, which is
        purely positional; a continuation paragraph sits at its parent's level.
    :param path: the positional address (ADR-0029), assigned by `assign_paths`.
        Empty until then.
    :param children: the ordered children.
    :param attrs: reader-specific detail that has no place in the core model.
        Stored as a plain dict copied from what you pass, and to be treated as
        read-only; keep it JSON-serialisable, because `to_dict` puts it on the
        wire unchanged.
    :param role: the optional semantic role (R1a); open vocabulary, see
        `RECOMMENDED_ROLES`.
    :param spans: typed ranges inside ``text``; open vocabulary, see
        `RECOMMENDED_SPAN_TYPES`. Every span must lie within ``text``: one that
        ends past it raises, because it describes text this block does not
        have. `redlines.semantic` is what normally fills this in.
    :param matched_by: the rule that recognised this block (ADR-0030).
        Defaults to `MATCHED_BY_FALLBACK`, which is the honest answer for a
        block nothing recognised -- except on a ``document`` block, where the
        default becomes `MATCHED_BY_DOCUMENT`, because a document is the tree
        rather than something a rule did or did not recognise.
    :param confidence: how sure the reader is of that, from 0.0 to 1.0
        inclusive (ADR-0030). Defaults to 0.0.
    """

    kind: BlockKind
    text: str = ""
    label: str | None = None
    level: int = 0
    path: str = ""
    children: tuple[Block, ...] = ()
    attrs: Mapping[str, Any] = field(default_factory=dict)
    role: str | None = None
    spans: tuple[Span, ...] = ()
    matched_by: str = MATCHED_BY_FALLBACK
    confidence: float = 0.0

    def __post_init__(self) -> None:
        """Normalise the kind, copy ``attrs``, and reject impossible values."""
        object.__setattr__(self, "kind", _coerce_kind(self.kind))
        object.__setattr__(self, "children", tuple(self.children))
        object.__setattr__(self, "spans", tuple(self.spans))
        object.__setattr__(self, "attrs", dict(self.attrs))
        if self.level < 0:
            raise ValueError(f"level must not be negative, got {self.level}")
        for span in self.spans:
            # A span is offsets into *this* block's text (R1a), so a span that
            # runs past the end of it is not a range of anything. Caught here
            # rather than at the first attempt to render it, because by then
            # the block that produced it is long gone.
            if span.end > len(self.text):
                raise ValueError(
                    f"span {span.type!r} ends at {span.end}, past the end of "
                    f"{len(self.text)} characters of text"
                )
        if not self.matched_by:
            raise ValueError(
                "matched_by must name the rule that recognised the block; "
                f"use {MATCHED_BY_FALLBACK!r} when nothing did"
            )
        if self.kind is BlockKind.DOCUMENT and self.matched_by == MATCHED_BY_FALLBACK:
            # A document block is the tree; no rule recognises it and none
            # failed to, so it takes its reserved value rather than the field
            # default. Without this a reader that simply forgets the keyword
            # makes every fallback_count one too high (ADR-0030).
            object.__setattr__(self, "matched_by", MATCHED_BY_DOCUMENT)
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be between 0.0 and 1.0, got {self.confidence}"
            )

    def to_dict(self) -> dict[str, Any]:
        """Return this block and its descendants as a JSON-serialisable dict.

        Every key is always present and always in the same order, so two
        equal trees serialise to identical JSON (N1).

        :return: a dict with the keys ``kind``, ``text``, ``label``, ``level``,
            ``path``, ``role``, ``spans``, ``matched_by``, ``confidence``,
            ``attrs`` and ``children``.
        """
        return {
            "kind": self.kind.value,
            "text": self.text,
            "label": self.label,
            "level": self.level,
            "path": self.path,
            "role": self.role,
            "spans": [span.to_dict() for span in self.spans],
            "matched_by": self.matched_by,
            "confidence": self.confidence,
            "attrs": dict(self.attrs),
            "children": [child.to_dict() for child in self.children],
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Block:
        """Rebuild a block and its descendants from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces. Only ``kind``
            is required; every other key falls back to the field's default.
        :return: the reconstructed `Block`.
        :raises ValueError: if ``kind`` is missing or outside the closed set,
            or the mapping carries a key this model does not know.
        """
        _reject_unknown_keys(data, _BLOCK_KEYS, "block")
        if "kind" not in data:
            raise ValueError("block is missing the key 'kind'")
        return cls(
            kind=_coerce_kind(data["kind"]),
            text=str(data.get("text", "")),
            label=data.get("label"),
            level=int(data.get("level", 0)),
            path=str(data.get("path", "")),
            children=tuple(
                cls.from_dict(child) for child in data.get("children", ()) or ()
            ),
            attrs=dict(data.get("attrs", {}) or {}),
            role=data.get("role"),
            spans=tuple(Span.from_dict(span) for span in data.get("spans", ()) or ()),
            matched_by=str(data.get("matched_by", MATCHED_BY_FALLBACK)),
            confidence=float(data.get("confidence", 0.0)),
        )


_BLOCK_KEYS = {
    "kind",
    "text",
    "label",
    "level",
    "path",
    "children",
    "attrs",
    "role",
    "spans",
    "matched_by",
    "confidence",
}


def _reject_unknown_keys(data: Mapping[str, Any], known: set[str], what: str) -> None:
    """Raise if ``data`` carries a key outside ``known``.

    Being strict here turns a typo in a hand-written tree into an error at the
    point it was made, rather than a silently dropped field two passes later.
    """
    unknown = sorted(set(data) - known)
    if unknown:
        raise ValueError(f"{what} has unknown key(s): {', '.join(unknown)}")


def child_path(parent_path: str, kind: BlockKind | str, index: int) -> str:
    """Build one child's address from its parent's (ADR-0029).

    :param parent_path: the parent's ``path``; `ROOT_PATH` for the document.
    :param kind: the child's kind, which names the step.
    :param index: the child's 1-based position **among its same-kind
        siblings**, so a section's second paragraph is ``paragraph[2]`` however
        many headings sit between them.
    :return: the child's path, for example ``"/table[1]/row[2]/cell[3]"``.
    :raises ValueError: if ``parent_path`` is not an address or ``index`` is
        not positive.
    """
    if not parent_path.startswith(ROOT_PATH):
        raise ValueError(f"{parent_path!r} is not a block address")
    if index < 1:
        raise ValueError(f"sibling index is 1-based, got {index}")
    prefix = "" if parent_path == ROOT_PATH else parent_path
    return f"{prefix}/{_coerce_kind(kind).value}[{index}]"


def assign_paths(root: Block) -> Block:
    """Return a copy of ``root`` with ``path`` set on every block (ADR-0029).

    Blocks are frozen, so a reader builds its tree bottom up -- where a parent
    cannot know its own address yet -- and calls this once at the end. The
    walk rebuilds each block with `dataclasses.replace`, so the input tree is
    untouched and unchanged blocks keep every other field.

    :param root: the document root of a path-less tree.
    :return: an equal tree whose root has path `ROOT_PATH` and whose every
        descendant has an XPath-style address.
    """
    return _with_paths(root, ROOT_PATH)


def _with_paths(block: Block, path: str) -> Block:
    """Return ``block`` at ``path``, with its subtree addressed beneath it."""
    counts: dict[str, int] = {}
    children = []
    for child in block.children:
        name = child.kind.value
        counts[name] = counts.get(name, 0) + 1
        children.append(_with_paths(child, child_path(path, child.kind, counts[name])))
    return replace(block, path=path, children=tuple(children))


def iter_blocks(block: Block) -> Iterator[Block]:
    """Yield ``block`` and every descendant, depth-first in document order.

    :param block: the block to walk.
    :return: an iterator over the block and its descendants.
    """
    yield block
    for child in block.children:
        yield from iter_blocks(child)


def _parse_path(path: str) -> tuple[tuple[str, int], ...]:
    """Split an address into ``(kind, index)`` steps.

    :param path: an address, `ROOT_PATH` or ``/kind[n]`` repeated.
    :return: one ``(kind, index)`` pair per step; empty for the root.
    :raises ValueError: if the path is not an address.
    """
    if not path.startswith(ROOT_PATH):
        raise ValueError(f"{path!r} is not a block address")
    if path == ROOT_PATH:
        return ()
    steps: list[tuple[str, int]] = []
    for segment in path[1:].split("/"):
        match = _SEGMENT_RE.fullmatch(segment)
        if match is None:
            raise ValueError(f"{path!r} is not a block address: bad step {segment!r}")
        steps.append((match["kind"], int(match["index"])))
    return tuple(steps)


def _descend(root: Block, path: str) -> tuple[tuple[Block, int], ...]:
    """Return the chain from ``root`` down to the block at ``path``.

    :return: one ``(block, position)`` pair per step, root first, where
        ``position`` is the block's index among *all* its parent's children
        (``-1`` for the root, which has no parent).
    :raises KeyError: if no block sits at that address.
    """
    chain: list[tuple[Block, int]] = [(root, -1)]
    for kind, index in _parse_path(path):
        seen = 0
        for position, child in enumerate(chain[-1][0].children):
            if child.kind.value == kind:
                seen += 1
                if seen == index:
                    chain.append((child, position))
                    break
        else:
            raise KeyError(f"no block at {path!r}")
    return tuple(chain)


def block_at(root: Block, path: str) -> Block:
    """Return the block at ``path``, resolving it step by step from ``root``.

    Resolution counts same-kind siblings rather than reading each block's
    ``path`` field, so it works on a tree `assign_paths` has not seen yet.

    :param root: the document root.
    :param path: an address, `ROOT_PATH` or ``/kind[n]`` repeated.
    :return: the addressed `Block`.
    :raises ValueError: if ``path`` is not an address.
    :raises KeyError: if the tree has no block there.
    """
    return _descend(root, path)[-1][0]


def heading_breadcrumb(root: Block, path: str) -> tuple[str, ...]:
    """Return the headings that lead to the block at ``path`` (ADR-0029).

    The breadcrumb is carried *alongside* the address, never encoded into it:
    it is what makes ``/section[7]/list_item[2]`` mean something to a person.
    It is derived from position, so it costs a reader nothing.

    Walking down from the root, each step contributes at most two crumbs:

    - the ancestor's own text, when that ancestor is a ``heading`` block whose
      children the walk descends into;
    - the text of the nearest ``heading`` sibling preceding the step, which is
      what picks up the ``heading`` a ``section`` normally opens with, and
      what makes the crumb work for a flat tree whose headings are siblings
      rather than parents.

    The block at ``path`` never contributes its own text, so the breadcrumb of
    a heading is the headings *above* it.

    :param root: the document root.
    :param path: the address of the block to describe.
    :return: heading texts, outermost first; empty for the root and for a
        top-level block with no heading before it.
    :raises ValueError: if ``path`` is not an address.
    :raises KeyError: if the tree has no block there.
    """
    chain = _descend(root, path)
    crumbs: list[str] = []
    for (parent, _), (_, position) in zip(chain, chain[1:]):
        if parent.kind is BlockKind.HEADING and parent.text:
            crumbs.append(parent.text)
        nearest = [
            sibling.text
            for sibling in parent.children[:position]
            if sibling.kind is BlockKind.HEADING and sibling.text
        ]
        if nearest:
            crumbs.append(nearest[-1])
    return tuple(crumbs)


@dataclass(frozen=True, slots=True)
class BlockTree:
    """A document: one root `Block`, plus what its reader dropped (R3).

    A tree is plain data. It carries no reader, no profile and no behaviour
    beyond addressing and serialisation; anything a reader wants to record
    about itself goes in the root block's ``attrs``.

    :param root: the root block, conventionally of kind ``document``.
    :param dropped: what the reader did not carry across, one `Dropped` per
        kind. Empty when a reader dropped nothing -- which is a claim, not a
        default to leave unexamined.
    """

    root: Block
    dropped: tuple[Dropped, ...] = ()

    def __post_init__(self) -> None:
        """Freeze ``dropped`` into a tuple whatever sequence was passed."""
        object.__setattr__(self, "dropped", tuple(self.dropped))

    @classmethod
    def build(cls, root: Block, *, dropped: Sequence[Dropped] = ()) -> BlockTree:
        """Address a path-less tree and wrap it. This is how a reader returns.

        :param root: the root of a tree built bottom up, with no paths set.
        :param dropped: what the reader dropped, if anything.
        :return: a `BlockTree` whose every block has a ``path`` (ADR-0029).
        """
        return cls(root=assign_paths(root), dropped=tuple(dropped))

    def walk(self) -> Iterator[Block]:
        """Yield every block, root first, depth-first in document order.

        :return: an iterator over the tree's blocks.
        """
        return iter_blocks(self.root)

    @property
    def fallback_count(self) -> int:
        """How many blocks matched no rule at all (R1d, ADR-0030).

        Exactly the blocks whose ``matched_by`` is `MATCHED_BY_FALLBACK`. A
        high count against a document the profile was supposed to fit is the
        signal that the profile does not fit it.
        """
        return sum(
            1 for block in self.walk() if block.matched_by == MATCHED_BY_FALLBACK
        )

    def block_at(self, path: str) -> Block:
        """Return the block at ``path``.

        :param path: an address, `ROOT_PATH` or ``/kind[n]`` repeated.
        :return: the addressed `Block`.
        :raises KeyError: if the tree has no block there.
        """
        return block_at(self.root, path)

    def heading_breadcrumb(self, path: str) -> tuple[str, ...]:
        """Return the headings leading to the block at ``path``.

        :param path: an address, `ROOT_PATH` or ``/kind[n]`` repeated.
        :return: heading texts, outermost first.
        """
        return heading_breadcrumb(self.root, path)

    def to_dict(self) -> dict[str, Any]:
        """Return the whole tree as a JSON-serialisable dict.

        ``fallback_count`` is included because a consumer reading the JSON
        needs it as much as a caller holding the object does; it is derived,
        so `from_dict` recomputes rather than trusts it.

        :return: a dict with the keys ``root``, ``dropped`` and
            ``fallback_count``.
        """
        return {
            "root": self.root.to_dict(),
            "dropped": [dropped.to_dict() for dropped in self.dropped],
            "fallback_count": self.fallback_count,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> BlockTree:
        """Rebuild a tree from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces. Any
            ``fallback_count`` present is ignored, being derived from the
            blocks themselves.
        :return: the reconstructed `BlockTree`, equal to the one serialised.
        :raises ValueError: if ``root`` is missing or the mapping carries an
            unknown key.
        """
        _reject_unknown_keys(data, {"root", "dropped", "fallback_count"}, "block tree")
        if "root" not in data:
            raise ValueError("block tree is missing the key 'root'")
        return cls(
            root=Block.from_dict(data["root"]),
            dropped=tuple(
                Dropped.from_dict(item) for item in data.get("dropped", ()) or ()
            ),
        )
