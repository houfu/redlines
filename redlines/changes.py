"""What changed between two aligned block trees, as plain data (#136).

`redlines.alignment` answers "which block is which". This module answers the
next question -- "and what happened to it" -- by turning an `Alignment` plus
the two trees it came from into a `ChangeTree`: a flat, document-ordered tuple
of `Change` nodes, each carrying the addresses it affects, the labels on both
sides, the semantic context and, where text was edited, the inline ops the
existing leaf differ found inside it (ADR-0033).

**Flat, not nested.** The "tree" in "change tree" is the ADR-0029 addresses,
which already encode the hierarchy exactly, plus the inline ops nested inside
a node -- the only nesting R18 asks for. A nested mirror of the block tree
would need pass-through nodes for unchanged ancestors, and every consumer
would then have to tell scaffolding from a real change. Filtering by section
is a segment-aligned prefix test on a flat list, which is what ADR-0029
settled a prefix match is enough for.

**Five kinds, and the precedence between them.** `insert`, `delete`,
`modify`, `move`, `renumber`; `split` and `merge` are reserved for 1.1
(ADR-0009) and are deliberately *not* members of `ChangeKind`, so a consumer
switching exhaustively today does not have to handle a value nothing emits.
When more than one is true the kind is `move > renumber > modify`. Nothing is
lost by that, because every node carries both addresses, both labels *and* its
inline ops whatever kind won -- a clause that was renumbered and edited is a
`renumber` node that still carries its edit.

**Granularity is topmost-wins** for `insert`, `delete` and `move`: one node
for the topmost affected block, with the subtree left to be read out of the
block trees in the same payload. That is what makes an inserted table row one
row-level `insert` by construction rather than by a table special case, and it
is the same rule the benchmark scores moves under, so the engine and its own
metric cannot disagree about what a move is. `modify` and `renumber` are
always per block.

**An address shift alone is never a change.** A block whose neighbours grew a
sibling above it has a new address and nothing else, and no node is emitted
for it. A renumbered clause shifts *and* changes its label, and the label is
what makes it a `renumber`.

**Inline ops carry character offsets into each block's own text**, the same
frame `redlines.blocks.Span` uses, so "which spans did this edit touch?" is an
interval overlap and nothing more, and M3's annotated renderer can splice by
character. v1's token positions stay in v1.

**The leaf differ is reused, not reimplemented** (ADR-0010). The ops come from
a `redlines.processor.RedlinesProcessor` -- `WholeDocumentProcessor` with
``autojunk`` off and the punctuation cleanup pass by default, the same object
`redlines.redlines.Redlines` runs -- and the conversion from its opcodes into
structured changes lives here, in `redlines_from_opcodes` (v1's `Redline`
list, which `Redlines.changes` now calls) and `inline_ops_from_opcodes` (this
module's `InlineOp` tuple). Both filter the opcodes through the same private
`_edit_opcodes`, so the two representations can never disagree about which
edits there were. They are two functions rather than one only because v1's
`Redline` reports ``source_position=None`` for an insert and so cannot carry
the source-side insertion point a character offset needs.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from .alignment import PASS_NAMES, Alignment
from .blocks import ROOT_PATH, Block, BlockKind, BlockTree, _reject_unknown_keys
from .processor import (
    PARAGRAPH_MARKER,
    SENTENCE_MARKER,
    DiffOperation,
    Redline,
    RedlinesProcessor,
    WholeDocumentProcessor,
    _strip_sentence_markers,
)
from .similarity import tokens

__all__: tuple[str, ...] = (
    "ChangeKind",
    "InlineKind",
    "CHANGE_KINDS",
    "RESERVED_CHANGE_KINDS",
    "UNMATCHED",
    "InlineOp",
    "Change",
    "ChangeTree",
    "build_change_tree",
    "redlines_from_opcodes",
    "inline_ops_from_opcodes",
)


class ChangeKind(str, Enum):
    """What happened to a block. A closed set in 1.0 (ADR-0033).

    A ``str`` enum like `redlines.blocks.BlockKind`, so ``change.kind ==
    "modify"`` is true and a kind serialises as its own name.
    """

    INSERT = "insert"
    DELETE = "delete"
    MODIFY = "modify"
    MOVE = "move"
    RENUMBER = "renumber"

    def __str__(self) -> str:
        """Return the kind's wire name."""
        return self.value


class InlineKind(str, Enum):
    """What one edit inside a block's text did.

    The three the leaf differ reports; ``equal`` runs are not changes and
    never become ops.
    """

    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"

    def __str__(self) -> str:
        """Return the kind's wire name."""
        return self.value


CHANGE_KINDS: Final[tuple[str, ...]] = tuple(kind.value for kind in ChangeKind)
"""Every kind a node can carry, in the order they sort in (ADR-0033)."""

RESERVED_CHANGE_KINDS: Final[tuple[str, ...]] = ("split", "merge")
"""Two names 1.0 does not emit and 1.1 will (ADR-0009).

They are recorded rather than enumerated: adding them to `ChangeKind` now
would make every consumer handle a value nothing produces, and adding them in
1.1 is an additive minor bump under ADR-0011.
"""

UNMATCHED: Final[str] = "unmatched"
"""`Change.matched_by` for an insert or a delete, which has no pair.

One of `redlines.alignment.RESERVED_PASS_NAMES`: it names the absence of a
pass, and no pass ever emits it.
"""

_KIND_ORDER: Final[Mapping[str, int]] = {
    kind: index for index, kind in enumerate(CHANGE_KINDS)
}

_MARKERS: Final[frozenset[str]] = frozenset({PARAGRAPH_MARKER, SENTENCE_MARKER})

_INLINE_KEYS: Final[set[str]] = {
    "kind",
    "source_start",
    "source_end",
    "test_start",
    "test_end",
    "source_text",
    "test_text",
}

_CHANGE_KEYS: Final[set[str]] = {
    "kind",
    "source_address",
    "test_address",
    "block_kind",
    "source_label",
    "test_label",
    "role",
    "span_types",
    "matched_by",
    "confidence",
    "source_text",
    "test_text",
    "inline",
    "breadcrumb",
}

_TREE_KEYS: Final[set[str]] = {"changes"}


@dataclass(frozen=True, slots=True)
class InlineOp:
    """One edit inside a block's text, in characters.

    Offsets are into the *owning block's own* ``text``, on each side
    separately -- never into the document -- which is the frame
    `redlines.blocks.Span` uses. An insert has ``source_start ==
    source_end`` (the point in the source text the new run went in at) and a
    delete has ``test_start == test_end``, so the two frames stay usable
    together.

    :param kind: ``insert``, ``delete`` or ``replace``.
    :param source_start: the first character of the run in the source block's
        text.
    :param source_end: one past its last character.
    :param test_start: the first character of the run in the test block's text.
    :param test_end: one past its last character.
    :param source_text: the source run, ``""`` for an insert. It is
        ``source_block.text[source_start:source_end]`` -- the op is a slice,
        not a paraphrase, which is what makes R27a's recovery exact.
    :param test_text: the test run, ``""`` for a delete.
    """

    kind: InlineKind
    source_start: int
    source_end: int
    test_start: int
    test_end: int
    source_text: str = ""
    test_text: str = ""

    def __post_init__(self) -> None:
        """Coerce the kind and reject an offset pair that cannot be a slice."""
        object.__setattr__(self, "kind", InlineKind(self.kind))
        for name, start, end in (
            ("source", self.source_start, self.source_end),
            ("test", self.test_start, self.test_end),
        ):
            if start < 0 or end < start:
                raise ValueError(
                    f"an inline op needs 0 <= {name}_start <= {name}_end, "
                    f"got {start} and {end}"
                )

    def to_dict(self) -> dict[str, Any]:
        """Return the op as a JSON-serialisable dict, in a fixed key order.

        :return: a dict with the keys ``kind``, ``source_start``,
            ``source_end``, ``test_start``, ``test_end``, ``source_text`` and
            ``test_text``.
        """
        return {
            "kind": self.kind.value,
            "source_start": self.source_start,
            "source_end": self.source_end,
            "test_start": self.test_start,
            "test_end": self.test_end,
            "source_text": self.source_text,
            "test_text": self.test_text,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InlineOp:
        """Rebuild an op from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `InlineOp`.
        :raises ValueError: if a key is unknown, ``kind`` is missing or
            outside the closed set, or the offsets cannot be a slice.
        """
        _reject_unknown_keys(data, _INLINE_KEYS, "inline op")
        if "kind" not in data:
            raise ValueError("inline op is missing the key 'kind'")
        return cls(
            kind=InlineKind(data["kind"]),
            source_start=int(data.get("source_start", 0)),
            source_end=int(data.get("source_end", 0)),
            test_start=int(data.get("test_start", 0)),
            test_end=int(data.get("test_end", 0)),
            source_text=str(data.get("source_text", "")),
            test_text=str(data.get("test_text", "")),
        )


@dataclass(frozen=True, slots=True)
class Change:
    """One thing that happened to one block.

    Every node carries **both** addresses, not only `move` and `renumber`: a
    `modify` inside a moved clause genuinely has two, and a shape where only
    some nodes carried both would force that node to lie about one of them.
    ``None`` marks the side that does not exist -- ``source_address`` on an
    insert, ``test_address`` on a delete.

    :param kind: what happened. When more than one thing did, ``move >
        renumber > modify`` (ADR-0033); the node keeps its inline ops either
        way, so nothing is lost by the precedence.
    :param source_address: the block's ADR-0029 address in the source tree,
        or ``None`` on an insert.
    :param test_address: its address in the test tree, or ``None`` on a delete.
    :param block_kind: the affected block's structural kind, from the test
        side, or the source side on a delete.
    :param source_label: its label in the source document, if it had one.
    :param test_label: its label in the test document.
    :param role: the semantic role (ADR-0005, ADR-0031), single-valued, from
        the test block or the source block on a delete. A role that *changed*
        is still visible -- both trees are in the same payload, at these two
        addresses.
    :param span_types: the types of the spans this change **touched**, sorted
        and deduplicated: for an edit, the spans on either side that overlap
        an inline op; for an insert or a delete, every span type on the block.
        The values are not copied here; they are on the blocks.
    :param matched_by: which alignment pass found the pair
        (`redlines.alignment.PASS_NAMES`), or `UNMATCHED` for an insert or a
        delete. This is alignment's own answer to "how do you know?", not the
        reader's `redlines.blocks.Block.matched_by` (ADR-0030).
    :param confidence: the alignment's confidence in the pair, 0.0 to 1.0, and
        0.0 for an insert or a delete. Rounded to four places on the wire and
        nowhere else.
    :param source_text: the affected block's own text on the source side,
        ``""`` where there is no source block.
    :param test_text: the same on the test side.
    :param inline: the edits inside the text, in order. Empty on an insert or
        a delete -- the whole block is the change, and its text is right here.
    :param breadcrumb: the ADR-0029 heading breadcrumb, test side (source side
        on a delete), precomputed so a summary never re-walks the tree.
    """

    kind: ChangeKind
    source_address: str | None
    test_address: str | None
    block_kind: BlockKind
    source_label: str | None = None
    test_label: str | None = None
    role: str | None = None
    span_types: tuple[str, ...] = ()
    matched_by: str = UNMATCHED
    confidence: float = 0.0
    source_text: str = ""
    test_text: str = ""
    inline: tuple[InlineOp, ...] = ()
    breadcrumb: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Coerce the enums, freeze the sequences, and check the shape."""
        object.__setattr__(self, "kind", ChangeKind(self.kind))
        object.__setattr__(self, "block_kind", BlockKind(self.block_kind))
        object.__setattr__(self, "span_types", tuple(self.span_types))
        object.__setattr__(self, "inline", tuple(self.inline))
        object.__setattr__(self, "breadcrumb", tuple(self.breadcrumb))
        has_source = self.source_address is not None
        has_test = self.test_address is not None
        if self.kind is ChangeKind.INSERT:
            if has_source:
                raise ValueError(
                    "an insert change has no source address: the block is not "
                    "in the source document"
                )
        elif not has_source:
            raise ValueError(
                f"a {self.kind} change needs a source address; only an insert "
                "goes without one"
            )
        if self.kind is ChangeKind.DELETE:
            if has_test:
                raise ValueError(
                    "a delete change has no test address: the block is not in "
                    "the test document"
                )
        elif not has_test:
            raise ValueError(
                f"a {self.kind} change needs a test address; only a delete "
                "goes without one"
            )
        if self.matched_by not in PASS_NAMES and self.matched_by != UNMATCHED:
            allowed = ", ".join((*PASS_NAMES, UNMATCHED))
            raise ValueError(
                f"{self.matched_by!r} is not an alignment pass; a change is "
                f"matched by one of: {allowed}"
            )
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence is a ratio from 0.0 to 1.0, got {self.confidence!r}"
            )

    @property
    def has_inline(self) -> bool:
        """Whether any text inside the block was edited.

        The predicate a consumer wants when kind precedence would hide an
        edit: a renumbered-and-edited clause is a ``renumber`` node, so
        filtering on ``kind == "modify"`` alone would miss it.
        """
        return bool(self.inline)

    @property
    def chars_added(self) -> int:
        """How many characters the inline ops put in (ADR-0033)."""
        return sum(len(op.test_text) for op in self.inline)

    @property
    def chars_deleted(self) -> int:
        """How many characters the inline ops took out (ADR-0033)."""
        return sum(len(op.source_text) for op in self.inline)

    @property
    def tokens_changed(self) -> int:
        """Tokens on both sides of every inline op, in the differ's own units.

        The same tokeniser the leaf differ compared with
        (`redlines.similarity.tokens`), so this number and the diff agree.
        """
        return sum(
            len(tokens(op.source_text)) + len(tokens(op.test_text))
            for op in self.inline
        )

    def to_dict(self) -> dict[str, Any]:
        """Return the node as a JSON-serialisable dict, in a fixed key order.

        ``confidence`` is rounded to four places here and nowhere else: full
        precision is kept for every comparison, and the rounding stops a
        golden churning on a 1e-9 difference between similarity backends.

        :return: a dict with the keys ``kind``, ``source_address``,
            ``test_address``, ``block_kind``, ``source_label``,
            ``test_label``, ``role``, ``span_types``, ``matched_by``,
            ``confidence``, ``source_text``, ``test_text``, ``inline`` and
            ``breadcrumb``.
        """
        return {
            "kind": self.kind.value,
            "source_address": self.source_address,
            "test_address": self.test_address,
            "block_kind": self.block_kind.value,
            "source_label": self.source_label,
            "test_label": self.test_label,
            "role": self.role,
            "span_types": list(self.span_types),
            "matched_by": self.matched_by,
            "confidence": round(self.confidence, 4),
            "source_text": self.source_text,
            "test_text": self.test_text,
            "inline": [op.to_dict() for op in self.inline],
            "breadcrumb": list(self.breadcrumb),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Change:
        """Rebuild a node from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `Change`.
        :raises ValueError: if a key is unknown, ``kind`` or ``block_kind`` is
            missing or outside its closed set, or the node's shape is not one
            `build_change_tree` could have produced.
        """
        _reject_unknown_keys(data, _CHANGE_KEYS, "change")
        for required in ("kind", "block_kind"):
            if required not in data:
                raise ValueError(f"change is missing the key {required!r}")
        source_address = data.get("source_address")
        test_address = data.get("test_address")
        return cls(
            kind=ChangeKind(data["kind"]),
            source_address=None if source_address is None else str(source_address),
            test_address=None if test_address is None else str(test_address),
            block_kind=BlockKind(data["block_kind"]),
            source_label=_optional_str(data.get("source_label")),
            test_label=_optional_str(data.get("test_label")),
            role=_optional_str(data.get("role")),
            span_types=tuple(str(name) for name in data.get("span_types", ()) or ()),
            matched_by=str(data.get("matched_by", UNMATCHED)),
            confidence=float(data.get("confidence", 0.0)),
            source_text=str(data.get("source_text", "")),
            test_text=str(data.get("test_text", "")),
            inline=tuple(
                InlineOp.from_dict(op) for op in data.get("inline", ()) or ()
            ),
            breadcrumb=tuple(str(part) for part in data.get("breadcrumb", ()) or ()),
        )


@dataclass(frozen=True, slots=True)
class ChangeTree:
    """Every change between two documents, flat and in document order.

    Iterable and indexable, so ``for change in comparison.changes`` and
    ``len(comparison.changes)`` read the way a caller expects a list of
    changes to.

    :param changes: the nodes, ordered by where they land in the test
        document, with a delete sitting after the last surviving block before
        it.
    """

    changes: tuple[Change, ...] = ()

    def __post_init__(self) -> None:
        """Freeze whatever sequence was handed in."""
        object.__setattr__(self, "changes", tuple(self.changes))

    def __iter__(self) -> Iterator[Change]:
        """Iterate the nodes in document order."""
        return iter(self.changes)

    def __len__(self) -> int:
        """Return how many nodes there are."""
        return len(self.changes)

    def __getitem__(self, index: int) -> Change:
        """Return one node by position."""
        return self.changes[index]

    def to_dict(self) -> dict[str, Any]:
        """Return the whole tree as a JSON-serialisable dict.

        :return: a dict with the single key ``changes``. The v2 document puts
            that list at its own top level rather than nesting it
            (`redlines.comparison.Comparison.to_dict`); this shape exists so a
            change tree can be serialised and rebuilt on its own.
        """
        return {"changes": [change.to_dict() for change in self.changes]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ChangeTree:
        """Rebuild a tree from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `ChangeTree`, equal to the one serialised.
        :raises ValueError: if a key is unknown or a node does not rebuild.
        """
        _reject_unknown_keys(data, _TREE_KEYS, "change tree")
        return cls(
            changes=tuple(
                Change.from_dict(change) for change in data.get("changes", ()) or ()
            )
        )


def build_change_tree(
    alignment: Alignment,
    source: BlockTree,
    test: BlockTree,
    *,
    processor: RedlinesProcessor | None = None,
) -> ChangeTree:
    """Turn an alignment and the two trees it came from into a change tree.

    Every matched pair is classified, every unmatched block on either side
    becomes an insert or a delete at the topmost address that is unmatched,
    and a pair whose two blocks say the same thing at the same place produces
    nothing at all.

    :param alignment: what `redlines.alignment.align` found for these two
        trees. Its addresses are resolved against the trees, so it must be the
        alignment of *these* two.
    :param source: the earlier document.
    :param test: the later one.
    :param processor: the leaf differ to run inside a matched pair --
        ``WholeDocumentProcessor(autojunk=False)`` when left out, which is the
        ADR-0010 differ v1 uses. A custom one is supported (R17); its opcodes
        are read the same way.
    :return: the `ChangeTree`, flat and in document order.
    :raises KeyError: if the alignment names an address that is not in the
        tree it belongs to -- the sign of an alignment paired with the wrong
        trees.
    """
    leaf = processor if processor is not None else WholeDocumentProcessor(autojunk=False)
    source_side = _Side(source)
    test_side = _Side(test)
    builder = _Builder(alignment, source_side, test_side, leaf)
    return builder.run()


def redlines_from_opcodes(diff_ops: Iterable[DiffOperation]) -> list[Redline]:
    """Turn a leaf differ's operations into v1's `redlines.processor.Redline` list.

    Extracted verbatim from ``Redlines.changes``, which now calls it, so the
    change tree and the v1 facade read one differ's output through one piece
    of code (ADR-0010: reuse, do not re-implement). Equal runs are dropped;
    only actual changes come back.

    Sentence markers (``'¦'``) are internal anchors with no counterpart in the
    input text and are stripped from every string, exactly as v1 does.

    :param diff_ops: the operations a `redlines.processor.RedlinesProcessor`
        produced, equal runs included.
    :return: one `redlines.processor.Redline` per change, in order, with
        **token** positions -- v1's frame. `inline_ops_from_opcodes` is the
        same list in characters.
    """
    result: list[Redline] = []
    for tag, i1, i2, j1, j2, source_tokens, test_tokens in _edit_opcodes(diff_ops):
        if tag == "delete":
            result.append(
                Redline(
                    operation="delete",
                    source_text=_strip_sentence_markers("".join(source_tokens[i1:i2])),
                    test_text=None,
                    source_position=(i1, i2),
                    test_position=None,
                )
            )
        elif tag == "insert":
            result.append(
                Redline(
                    operation="insert",
                    source_text=None,
                    test_text=_strip_sentence_markers("".join(test_tokens[j1:j2])),
                    source_position=None,
                    test_position=(j1, j2),
                )
            )
        else:
            result.append(
                Redline(
                    operation="replace",
                    source_text=_strip_sentence_markers("".join(source_tokens[i1:i2])),
                    test_text=_strip_sentence_markers("".join(test_tokens[j1:j2])),
                    source_position=(i1, i2),
                    test_position=(j1, j2),
                )
            )
    return result


def inline_ops_from_opcodes(
    diff_ops: Iterable[DiffOperation],
    *,
    source_text: str,
    test_text: str,
) -> tuple[InlineOp, ...]:
    """Turn a leaf differ's operations into `InlineOp`s, in characters.

    The same edits `redlines_from_opcodes` reports, in the frame
    `redlines.blocks.Span` uses. Each op's ``source_text`` is literally
    ``source_text[op.source_start:op.source_end]``, so a consumer can splice
    the source text back into the test text from the ops alone (R27a).

    :param diff_ops: the operations a `redlines.processor.RedlinesProcessor`
        produced for these two strings.
    :param source_text: the source side the differ was given.
    :param test_text: the test side.
    :return: the ops, in order.
    """
    ops: list[InlineOp] = []
    source_at: dict[int, tuple[int, ...]] = {}
    test_at: dict[int, tuple[int, ...]] = {}
    for tag, i1, i2, j1, j2, source_tokens, test_tokens in _edit_opcodes(diff_ops):
        source_offsets = _offsets_for(source_at, source_text, source_tokens)
        test_offsets = _offsets_for(test_at, test_text, test_tokens)
        source_start, source_end = source_offsets[i1], source_offsets[i2]
        test_start, test_end = test_offsets[j1], test_offsets[j2]
        ops.append(
            InlineOp(
                kind=InlineKind(tag),
                source_start=source_start,
                source_end=source_end,
                test_start=test_start,
                test_end=test_end,
                source_text=source_text[source_start:source_end],
                test_text=test_text[test_start:test_end],
            )
        )
    return tuple(ops)


# --------------------------------------------------------------------------
# The differ's opcodes, read once for both representations.
# --------------------------------------------------------------------------


def _edit_opcodes(
    diff_ops: Iterable[DiffOperation],
) -> Iterator[tuple[str, int, int, int, int, list[str], list[str]]]:
    """Yield every non-equal opcode with the token lists it indexes into.

    The one place either representation decides what counts as a change, so
    ``Redlines.changes`` and the change tree cannot drift apart. A tag neither
    difflib nor the cleanup pass produces is skipped rather than guessed at,
    which is what v1 did.
    """
    for diff_op in diff_ops:
        tag, i1, i2, j1, j2 = diff_op.opcodes
        if tag not in ("delete", "insert", "replace"):
            continue
        yield tag, i1, i2, j1, j2, diff_op.source_chunk.text, diff_op.test_chunk.text


def _offsets_for(
    cache: dict[int, tuple[int, ...]], text: str, chunk_tokens: list[str]
) -> tuple[int, ...]:
    """Return `_char_offsets` for one chunk's tokens, computed once."""
    key = id(chunk_tokens)
    if key not in cache:
        cache[key] = _char_offsets(text, chunk_tokens)
    return cache[key]


def _char_offsets(text: str, chunk_tokens: Sequence[str]) -> tuple[int, ...]:
    """Map token index to character offset in ``text``, with a sentinel at the end.

    The returned tuple has one more entry than there are tokens, so the
    half-open token range ``[i1, i2)`` becomes the half-open character range
    ``[offsets[i1], offsets[i2])`` with no special case at the end.

    The tokens are located by scanning ``text`` forward rather than by adding
    up their lengths, because the differ inserts paragraph and sentence
    markers that have no counterpart in the text at all: a marker token maps
    to the cursor it sits at, which is zero width, and the next real token
    picks up wherever it actually is. For the ordinary case -- a single block
    of text through `redlines.processor.WholeDocumentProcessor` -- the tokens
    tile the text exactly and this is the same answer their lengths would
    give.

    If a token cannot be found at all, which a processor that rewrites text
    rather than splitting it could manage, the offsets fall back to cumulative
    token lengths clamped to the text. The ops are then approximate rather
    than exact, and say so by not slicing back to their own text.
    """
    offsets: list[int] = []
    cursor = 0
    for token in chunk_tokens:
        content = token.strip()
        found = text.find(content, cursor) if content else cursor
        if found < 0:
            if content in _MARKERS:
                offsets.append(cursor)
                continue
            return _clamped_offsets(text, chunk_tokens)
        offsets.append(found)
        cursor = found + len(content)
    offsets.append(len(text))
    return tuple(offsets)


def _clamped_offsets(text: str, chunk_tokens: Sequence[str]) -> tuple[int, ...]:
    """Offsets from cumulative token lengths, never past the end of ``text``."""
    offsets: list[int] = []
    cursor = 0
    for token in chunk_tokens:
        offsets.append(min(cursor, len(text)))
        cursor += len(token)
    offsets.append(len(text))
    return tuple(offsets)


# --------------------------------------------------------------------------
# The builder. Everything below is private; the shapes above are the contract.
# --------------------------------------------------------------------------


class _Side:
    """One tree, indexed the three ways the builder reads it."""

    def __init__(self, tree: BlockTree) -> None:
        self.tree = tree
        self.block: dict[str, Block] = {}
        self.order: dict[str, int] = {}
        self.parent: dict[str, str | None] = {}
        stack: list[tuple[Block, str | None]] = [(tree.root, None)]
        # An explicit walk rather than BlockTree.walk(), because the parent of
        # each block is wanted and walk() reports blocks alone.
        index = 0
        while stack:
            block, parent_path = stack.pop()
            self.block[block.path] = block
            self.order[block.path] = index
            self.parent[block.path] = parent_path
            index += 1
            stack.extend(
                (child, block.path) for child in reversed(block.children)
            )

    def breadcrumb(self, path: str) -> tuple[str, ...]:
        """The ADR-0029 heading breadcrumb for one address."""
        return self.tree.heading_breadcrumb(path)


@dataclass(frozen=True, slots=True)
class _Sortable:
    """A node and the key it sorts by (ADR-0033).

    :param test_rank: where the node lands in the test document -- the test
        block's own position, or, for a delete, the position of the last
        surviving block before it.
    :param after: 0 for a node that is *at* ``test_rank``, 1 for a delete that
        sits just after it.
    :param source_rank: the source block's position, ``-1`` for an insert.
    :param kind_rank: the kind's index in `CHANGE_KINDS`, so two nodes that
        somehow shared everything else still have a stated order.
    """

    test_rank: int
    after: int
    source_rank: int
    kind_rank: int
    change: Change = field(compare=False)

    def key(self) -> tuple[int, int, int, int]:
        """The full sort key, which no two nodes may share."""
        return (self.test_rank, self.after, self.source_rank, self.kind_rank)


class _Builder:
    """Classifies one alignment into change nodes."""

    def __init__(
        self,
        alignment: Alignment,
        source: _Side,
        test: _Side,
        processor: RedlinesProcessor,
    ) -> None:
        self.alignment = alignment
        self.source = source
        self.test = test
        self.processor = processor
        self.inserted = {path: None for path in alignment.inserted}
        self.deleted = {path: None for path in alignment.deleted}
        self.moved = {
            pair.source_path: pair.test_path for pair in alignment.pairs if pair.moved
        }

    def run(self) -> ChangeTree:
        """Build every node, order them, and check the order is total."""
        nodes: list[_Sortable] = []
        nodes.extend(self._inserts())
        nodes.extend(self._deletes())
        nodes.extend(self._pairs())
        nodes.sort(key=_Sortable.key)
        seen: dict[tuple[int, int, int, int], None] = {}
        for node in nodes:
            if node.key() in seen:  # pragma: no cover - a bug, not an input
                raise AssertionError(
                    f"two changes share the sort key {node.key()}: "
                    f"{node.change.source_address} / {node.change.test_address}"
                )
            seen[node.key()] = None
        return ChangeTree(changes=tuple(node.change for node in nodes))

    # -- unmatched blocks ---------------------------------------------------

    def _inserts(self) -> Iterator[_Sortable]:
        """One node per topmost inserted block (ADR-0033).

        A block whose parent is inserted too is part of the same insertion and
        is not re-reported: the whole subtree is in the test tree, at this
        address.
        """
        for path in self.alignment.inserted:
            parent = self.test.parent[path]
            if parent is not None and parent in self.inserted:
                continue
            block = self.test.block[path]
            yield _Sortable(
                test_rank=self.test.order[path],
                after=0,
                source_rank=-1,
                kind_rank=_KIND_ORDER["insert"],
                change=Change(
                    kind=ChangeKind.INSERT,
                    source_address=None,
                    test_address=path,
                    block_kind=block.kind,
                    source_label=None,
                    test_label=block.label,
                    role=block.role,
                    span_types=_all_span_types(block),
                    matched_by=UNMATCHED,
                    confidence=0.0,
                    source_text="",
                    test_text=block.text,
                    inline=(),
                    breadcrumb=self.test.breadcrumb(path),
                ),
            )

    def _deletes(self) -> Iterator[_Sortable]:
        """One node per topmost deleted block, placed by its surviving neighbour.

        A delete has no test address, so it has no position of its own in the
        test document. It is sorted immediately after the last source block
        before it that survived -- which is where a reader looking at the test
        document would notice it missing.
        """
        surviving = -1
        by_source_order = sorted(self.deleted, key=lambda path: self.source.order[path])
        placement: dict[str, int] = {}
        for path in sorted(self.source.order, key=self.source.order.__getitem__):
            if path in self.deleted:
                placement[path] = surviving
                continue
            counterpart = self.alignment.test_for(path)
            if counterpart is not None:
                surviving = self.test.order[counterpart]
        for path in by_source_order:
            parent = self.source.parent[path]
            if parent is not None and parent in self.deleted:
                continue
            block = self.source.block[path]
            yield _Sortable(
                test_rank=placement[path],
                after=1,
                source_rank=self.source.order[path],
                kind_rank=_KIND_ORDER["delete"],
                change=Change(
                    kind=ChangeKind.DELETE,
                    source_address=path,
                    test_address=None,
                    block_kind=block.kind,
                    source_label=block.label,
                    test_label=None,
                    role=block.role,
                    span_types=_all_span_types(block),
                    matched_by=UNMATCHED,
                    confidence=0.0,
                    source_text=block.text,
                    test_text="",
                    inline=(),
                    breadcrumb=self.source.breadcrumb(path),
                ),
            )

    # -- matched pairs ------------------------------------------------------

    def _pairs(self) -> Iterator[_Sortable]:
        """One node per pair that is a move, a renumber or a real edit.

        A pair that is none of those is not a change, however far its address
        has shifted.
        """
        for pair in self.alignment.pairs:
            if pair.source_path == ROOT_PATH and pair.test_path == ROOT_PATH:
                continue
            source_block = self.source.block[pair.source_path]
            test_block = self.test.block[pair.test_path]
            inline = self._inline(source_block, test_block)
            moved = pair.moved and not self._under_a_move(
                pair.source_path, pair.test_path
            )
            kind = self._kind(moved, pair.renumbered, inline)
            if kind is None:
                continue
            yield _Sortable(
                test_rank=self.test.order[pair.test_path],
                after=0,
                source_rank=self.source.order[pair.source_path],
                kind_rank=_KIND_ORDER[kind.value],
                change=Change(
                    kind=kind,
                    source_address=pair.source_path,
                    test_address=pair.test_path,
                    block_kind=test_block.kind,
                    source_label=source_block.label,
                    test_label=test_block.label,
                    role=test_block.role,
                    span_types=_touched_span_types(source_block, test_block, inline),
                    matched_by=pair.matched_by,
                    confidence=pair.confidence,
                    source_text=source_block.text,
                    test_text=test_block.text,
                    inline=inline,
                    breadcrumb=self.test.breadcrumb(pair.test_path),
                ),
            )

    def _under_a_move(self, source_path: str, test_path: str) -> bool:
        """Whether this pair rode along inside an ancestor's move.

        Topmost wins: a block that went where its parent went is not a move of
        its own, and a descendant that *also* changed is reported as the
        `modify` or `renumber` it is, carrying both of its addresses.

        The test address has to be checked, not just the source ancestry: a
        block that left a moving clause for somewhere else moved on its own
        account, and suppressing that would lose a real move. So an ancestor
        only absorbs this pair when the pair landed inside where that ancestor
        landed.
        """
        ancestor = self.source.parent[source_path]
        while ancestor is not None:
            landed = self.moved.get(ancestor)
            if landed is not None and _is_under(test_path, landed):
                return True
            ancestor = self.source.parent[ancestor]
        return False

    def _kind(
        self, moved: bool, renumbered: bool, inline: tuple[InlineOp, ...]
    ) -> ChangeKind | None:
        """Apply ``move > renumber > modify``, or decide this is not a change.

        Nothing is lost to the precedence: the node keeps both addresses, both
        labels and its inline ops whichever kind won. What is decided here is
        only the one word a consumer switches on.
        """
        if moved:
            return ChangeKind.MOVE
        if renumbered:
            return ChangeKind.RENUMBER
        if inline:
            return ChangeKind.MODIFY
        return None

    def _inline(self, source_block: Block, test_block: Block) -> tuple[InlineOp, ...]:
        """Run the leaf differ inside one pair, or skip it when there is nothing to do.

        Identical text short-circuits, which is most of a document and every
        container block -- and it also states the rule that an edit the differ
        cannot see is not an edit: a block whose text differs only in
        whitespace the tokeniser normalises away produces no ops and so no
        node, exactly as the sample pair's hard-wrapped notices clause does.
        """
        if source_block.text == test_block.text:
            return ()
        diff_ops = self.processor.process(source_block.text, test_block.text)
        return inline_ops_from_opcodes(
            diff_ops, source_text=source_block.text, test_text=test_block.text
        )


def _all_span_types(block: Block) -> tuple[str, ...]:
    """Every span type on a block, sorted and deduplicated.

    What an insert or a delete reports: the whole block is the change, so
    every span on it was touched.
    """
    return tuple(sorted({span.type for span in block.spans}))


def _touched_span_types(
    source_block: Block, test_block: Block, inline: tuple[InlineOp, ...]
) -> tuple[str, ...]:
    """The types of the spans an edit actually overlapped (ADR-0005, ADR-0033).

    Read strictly: a span is touched when an op's character range on that
    span's own side overlaps it. Reporting every span on the block instead
    would bury the signal -- the sample pair's clause 9.2 carries two `party`
    spans nowhere near the one character range that changed.
    """
    found: dict[str, None] = {}
    for op in inline:
        for span in source_block.spans:
            if op.source_start < span.end and span.start < op.source_end:
                found[span.type] = None
        for span in test_block.spans:
            if op.test_start < span.end and span.start < op.test_end:
                found[span.type] = None
    return tuple(sorted(found))


def _is_under(path: str, prefix: str) -> bool:
    """Whether ``path`` is ``prefix`` or sits inside it, segment-aligned.

    A plain ``str.startswith`` would make ``/section[1]`` contain
    ``/section[11]``, and both exist in the sample pair. `ROOT_PATH` contains
    everything.
    """
    return path == prefix or path.startswith(prefix.rstrip("/") + "/")


def _optional_str(value: Any) -> str | None:
    """``None`` stays ``None``; anything else becomes its string."""
    return None if value is None else str(value)
