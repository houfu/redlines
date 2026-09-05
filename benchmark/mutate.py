"""Mutation operators over a real document, and the ground truth about what they did (#141).

ADR-0021 asks for a synthetic corpus built *before* alignment is tuned: take real text and
markdown documents, apply known mutations programmatically, and keep the ground truth. This
module is the "apply known mutations" half; :mod:`benchmark.generate` is the half that reads a
plan, seeds the generator and writes the pairs out.

**Why a line model and not a tree model.** The readers have no writer -- a `redlines.blocks.BlockTree`
cannot be rendered back to markdown or to plain text -- so a mutation that edited the tree would
have nothing to write. Everything here therefore mutates the *document's own text*, and uses the
tree only to say what that text means. `Document.from_text` reads the document through
`redlines.pipeline.read_document` and then walks the raw lines and the labelled blocks together,
in document order, cutting the text into `Unit`\\ s: one unit per labelled block (a table's cells
ride along on their row's unit), each holding the exact lines that produced it. Rendering a
`Document` back out is `Unit` lines and the blank lines between them, joined -- and
`Document.from_text` asserts that this round-trips the input byte for byte, so a document whose
shape this model cannot express fails loudly at build time rather than producing a corpus pair
whose labels quietly describe the wrong blocks.

**What a unit knows, and why.** A unit carries its label split out of its own first line
(``head`` + ``label_text`` + ``separator`` + body), which is what makes renumbering a textual
operation with no guessing: to relabel a clause you replace ``label_text``, not a regex match
somewhere in a paragraph. It carries the address and parent address of the block it produced, so
"the run of siblings this clause belongs to" is a lookup rather than an inference. And it carries
the values of that block's ``cross_reference`` spans, which is what makes
`insert_clause`'s cross-reference rewrite a lookup too: the semantic pass has already decided
which blocks cite which labels and normalised the cited value the same way `redlines.blocks.Block.label`
is normalised, so a renumbering knows exactly which units to rewrite and never has to guess from
a bare number in prose.

**Operators.** Each takes the mutation state and the seeded `random.Random`, applies itself where
it can, and records what it did:

- `move_block` -- lift a labelled block (and the units nested under it) into another section,
  relabel it to fit its new siblings, renumber both runs. One ``move`` correspondence at the
  topmost block; nested units are ``same`` at their new addresses (ADR-0034's subtree rule).
- `insert_clause` -- insert a clause from the boilerplate bank into a run, relabel the rest of
  the run, and rewrite every cross-reference whose cited label moved.
- `delete_block` -- the mirror of the above.
- `edit_text` -- an in-place inline edit in one of six styles.
- `whitespace_only` -- re-wrap a block at a different column, or widen the spaces inside its
  lines. **A negative control**: the block's normalised text, and therefore its ADR-0034 digest,
  is unchanged, so an engine that reports a change here has lost precision and the labels say so
  by not recording one.
- `relabel_run` -- renumber a whole run with no text change at all, which separates label matching
  from content matching.
- `split_block` / `merge_blocks` -- recorded into ``splits``/``merges`` and excluded from every
  1.0 denominator (#141: labelled now so the 1.1 metric has data).
- `table_edit` -- a row insert, a row delete or a cell edit, for #134.

**Every change is read back before it is kept.** An operator works on lines, while the ground
truth is addresses in the tree those lines read as, so a change that alters how a reader *groups*
the text -- a re-wrap the plain-text reader takes as a continuation paragraph -- would leave unit
*n* no longer producing block *n* and every label after it naming the wrong address. `_attempt`
therefore applies each change, re-reads the document, and rolls the change back if the reader
disagrees. The cost is one read per attempted change; the benefit is that a source document only
has to be *readable*, not to sit inside the intersection of what two readers happen to do, and a
document that resists an operator produces a quieter pair rather than a wrong one.

**Determinism.** Every draw goes through `random.Random.randrange` on a list -- never
`random.sample`, `random.shuffle` or `random.choice`, whose implementations have changed between
CPython releases, and never `set` iteration or `hash()`. The corpus is committed and byte-compared
in CI across five Python versions (`tests/test_benchmark_corpus.py`), so a draw that is stable only
on one of them is a broken build, not a flaky test.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from random import Random
from typing import Any

from redlines.blocks import Block, BlockKind, BlockTree
from redlines.pipeline import read_document

__all__ = [
    "MutationError",
    "OPERATORS",
    "EDIT_STYLES",
    "RELABEL_STYLES",
    "TABLE_STYLES",
    "Unit",
    "Document",
    "Split",
    "Merge",
    "Mutation",
    "Step",
    "normalise",
    "mutate",
]


class MutationError(ValueError):
    """A document (or a mutation of one) does not fit the line model this module needs.

    Raised at build time, not at score time: a corpus pair whose units cannot be lined up with
    the blocks they produced would carry labels that name the wrong addresses, and a wrong label
    is worse than a missing pair.
    """


def normalise(text: str) -> str:
    """Collapse whitespace runs to one space and strip the ends.

    The same normalisation `benchmark.labels.normalise_text` digests under, repeated here rather
    than imported so that the two stay legible independently; a change to one without the other
    is caught by ``tests/test_benchmark_corpus.py``'s digest checks.
    """
    return " ".join(text.split())


# --------------------------------------------------------------------------
# Label schemes
# --------------------------------------------------------------------------

_DOTTED_RE = re.compile(r"^(?P<prefix>(?:\d+\.)+)(?P<n>\d+)$")
_DECIMAL_RE = re.compile(r"^(?P<n>\d+)$")
_ALPHA_RE = re.compile(r"^\((?P<a>[a-z])\)$")


@dataclass(frozen=True, kw_only=True, slots=True)
class LabelScheme:
    """How one run of sibling labels counts, so a run can be renumbered as text.

    :param name: the scheme's name, recorded in the operation log.
    :param prefix: the fixed part of every label in the run (``"3."`` for ``3.1, 3.2``).
    :param separator: the punctuation and space that follow the label in the document's own
        text. Kept so that renumbering within a scheme preserves the document's typography,
        and replaced by the new scheme's own when `relabel_run` changes scheme.
    """

    name: str
    prefix: str = ""
    separator: str = " "

    def parse(self, label: str) -> int | None:
        """Return the ordinal `label` denotes under this scheme, or ``None`` if it is not one."""
        if self.name == "dotted":
            match = _DOTTED_RE.match(label)
            if match is None or match.group("prefix") != self.prefix:
                return None
            return int(match.group("n"))
        if self.name == "decimal":
            match = _DECIMAL_RE.match(label)
            return int(match.group("n")) if match else None
        if self.name == "alpha":
            match = _ALPHA_RE.match(label)
            return ord(match.group("a")) - ord("a") + 1 if match else None
        return None

    def format(self, ordinal: int) -> str:
        """Return the label text for `ordinal`, or raise if this scheme cannot express it."""
        if self.name == "dotted":
            return f"{self.prefix}{ordinal}"
        if self.name == "decimal":
            return str(ordinal)
        if self.name == "alpha":
            if not 1 <= ordinal <= 26:
                raise MutationError(f"the alpha scheme cannot express ordinal {ordinal}")
            return f"({chr(ord('a') + ordinal - 1)})"
        raise MutationError(f"unknown label scheme {self.name!r}")


def _scheme_for(label: str, separator: str) -> LabelScheme | None:
    """Infer the scheme of a run from the literal label its first member carries."""
    dotted = _DOTTED_RE.match(label)
    if dotted is not None:
        return LabelScheme(name="dotted", prefix=dotted.group("prefix"), separator=separator)
    if _DECIMAL_RE.match(label):
        return LabelScheme(name="decimal", separator=separator)
    if _ALPHA_RE.match(label):
        return LabelScheme(name="alpha", separator=separator)
    return None


# --------------------------------------------------------------------------
# The line model
# --------------------------------------------------------------------------

#: Container kinds, which own no text of their own and are never a unit (ADR-0034).
_CONTAINER_KINDS = frozenset({BlockKind.DOCUMENT, BlockKind.SECTION, BlockKind.TABLE})

#: Markers that sit before a label on a line and are not part of it.
_HEAD_RE = re.compile(r"^(?:#{1,6}\s+|[-*+]\s+|>\s+)?")

#: The punctuation and whitespace between a label and the text it labels.
_SEPARATOR_RE = re.compile(r"^[.):]?[ \t]*")

_TABLE_LINE_RE = re.compile(r"^\s*\|")


@dataclass(frozen=True, kw_only=True, slots=True)
class Unit:
    """One labelled block's own lines, cut out of the document's text.

    :param uid: a stable identity that survives every mutation. Source units are numbered in
        document order; units the generator creates carry their own prefix. The label rows are
        built by matching a test unit's `origin` against a source unit's `uid`, so this is what
        makes ground truth a lookup rather than a re-alignment.
    :param origin: the ``uid`` of the source unit this one descends from, or ``None`` for a unit
        the generator inserted.
    :param gap: the blank lines that preceded this unit in the document, kept verbatim so that
        rendering round-trips and so that a tight markdown list stays tight.
    :param head: whatever precedes the label on the first line -- indentation, an ATX heading's
        ``##``, a bullet.
    :param label_text: the label exactly as the document writes it, or ``""`` when the block has
        no label or when it could not be located in the text (in which case the unit is never
        renumbered; see `renumberable`).
    :param separator: the punctuation and space between `label_text` and the body.
    :param body: the rest of the unit's lines; ``body[0]`` is the remainder of the first line.
    :param kind: the `redlines.blocks.BlockKind` of the block this unit produced.
    :param address: the block's ADR-0029 address in the tree this unit was read from.
    :param parent: the address of that block's parent, which is what a sibling run is keyed on.
    :param label: the block's own normalised `redlines.blocks.Block.label`.
    :param references: the values of the block's ``cross_reference`` spans -- the labels this
        unit cites, which is what a renumbering rewrites.
    """

    uid: str
    origin: str | None
    gap: tuple[str, ...] = ()
    head: str = ""
    label_text: str = ""
    separator: str = ""
    body: tuple[str, ...] = ()
    kind: BlockKind = BlockKind.PARAGRAPH
    address: str = ""
    parent: str = ""
    label: str | None = None
    references: tuple[str, ...] = ()

    @property
    def lines(self) -> tuple[str, ...]:
        """The unit's lines as they appear in the document."""
        first = f"{self.head}{self.label_text}{self.separator}{self.body[0] if self.body else ''}"
        return (first, *self.body[1:])

    @property
    def text(self) -> str:
        """The unit's whole text, lines joined with newlines."""
        return "\n".join(self.lines)

    @property
    def body_text(self) -> str:
        """The unit's text with the label and its separator removed."""
        return "\n".join(self.body)

    @property
    def renumberable(self) -> bool:
        """True when this unit's label was found in its own text and so can be rewritten."""
        return bool(self.label_text)

    def with_body(self, body_text: str) -> Unit:
        """Return a copy whose body is `body_text`, split back into lines."""
        return replace(self, body=tuple(body_text.split("\n")))


@dataclass(frozen=True, kw_only=True, slots=True)
class Document:
    """A document as an ordered list of `Unit`\\ s, renderable back to its own exact text."""

    units: tuple[Unit, ...]
    epilogue: tuple[str, ...] = ()
    trailing_newline: bool = True
    format: str = "text"
    profile: str = "contract"
    parties: tuple[str, ...] = ()

    def render(self) -> str:
        """Return the document's text."""
        lines: list[str] = []
        for unit in self.units:
            lines.extend(unit.gap)
            lines.extend(unit.lines)
        lines.extend(self.epilogue)
        text = "\n".join(lines)
        return text + "\n" if self.trailing_newline else text

    @classmethod
    def from_text(cls, text: str, *, format: str, profile: str) -> Document:
        """Read `text` and cut it into units, one per labelled block.

        :raises MutationError: if the lines and the blocks cannot be walked together, or if the
            units do not render back to `text` exactly.
        """
        tree = read_document(text, format=format, profile=profile)
        units = tuple(
            _unit_from(block, index, gap, lines)
            for index, (block, gap, lines) in enumerate(_cut(text, tree))
        )
        document = cls(
            units=units,
            epilogue=_epilogue(text, units),
            trailing_newline=text.endswith("\n"),
            format=format,
            profile=profile,
            parties=_parties(tree),
        )
        if document.render() != text:
            raise MutationError(
                "the unit model does not round-trip this document; it has structure "
                "benchmark/mutate.py cannot express"
            )
        return document

    def tree(self) -> BlockTree:
        """Return the tree this document's text reads as."""
        return read_document(self.render(), format=self.format, profile=self.profile)


def _labelled(tree: BlockTree) -> list[Block]:
    """Every block that owns a unit: text-bearing blocks and table rows, never a cell."""
    return [
        block
        for block in tree.walk()
        if block.kind not in _CONTAINER_KINDS and block.kind is not BlockKind.CELL
    ]


def _is_delimiter(line: str) -> bool:
    """True for a markdown table's ``| --- | --- |`` line, which produces no block."""
    stripped = line.strip()
    if not stripped or not _TABLE_LINE_RE.match(line):
        return False
    return set(stripped.replace("|", "").replace(" ", "")) <= set("-:") and "-" in stripped


def _cut(text: str, tree: BlockTree) -> list[tuple[Block, tuple[str, ...], tuple[str, ...]]]:
    """Walk lines and blocks together, returning ``(block, gap lines, unit lines)`` per block.

    Blocks come out of `BlockTree.walk` in document order and a reader never reorders, so a
    single forward pass suffices: skip blank lines into the gap, then take lines until the
    block's normalised text is covered by what has been taken. A table row takes exactly one
    line (plus the delimiter that follows a header row), because a row's text lives in its cells.
    """
    lines = text.splitlines()
    cursor = 0
    cut: list[tuple[Block, tuple[str, ...], tuple[str, ...]]] = []
    for block in _labelled(tree):
        gap_start = cursor
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        gap = tuple(lines[gap_start:cursor])
        if cursor >= len(lines):
            raise MutationError(f"ran out of lines before block {block.path}")
        start = cursor
        if block.kind is BlockKind.ROW:
            cursor += 1
            if block.attrs.get("header") and cursor < len(lines) and _is_delimiter(lines[cursor]):
                cursor += 1
        else:
            target = normalise(block.text)
            accumulated = ""
            while cursor < len(lines):
                accumulated = f"{accumulated} {lines[cursor]}"
                cursor += 1
                if target in normalise(accumulated):
                    break
            else:
                raise MutationError(
                    f"block {block.path} ({target[:60]!r}) is not covered by any run of lines"
                )
        cut.append((block, gap, tuple(lines[start:cursor])))
    return cut


def _epilogue(text: str, units: Sequence[Unit]) -> tuple[str, ...]:
    """Return the lines after the last unit -- a trailing rule, a stray blank line."""
    lines = text.splitlines()
    consumed = sum(len(unit.gap) + len(unit.lines) for unit in units)
    return tuple(lines[consumed:])


def _unit_from(
    block: Block, index: int, gap: tuple[str, ...], lines: tuple[str, ...]
) -> Unit:
    """Split one block's lines into head, label, separator and body."""
    head, label_text, separator, body_first = _split_label(lines[0], block.label)
    return Unit(
        uid=f"s{index:04d}",
        origin=f"s{index:04d}",
        gap=gap,
        head=head,
        label_text=label_text,
        separator=separator,
        body=(body_first, *lines[1:]),
        kind=block.kind,
        address=block.path,
        parent=_parent_of(block.path),
        label=block.label,
        references=tuple(
            span.value for span in block.spans if span.type == "cross_reference" and span.value
        ),
    )


def _split_label(line: str, label: str | None) -> tuple[str, str, str, str]:
    """Return ``(head, label_text, separator, rest)`` for a unit's first line.

    The label is located by looking for `label` itself immediately after the line's markers, so
    the document's own spelling is what gets rewritten -- ``"3.3"`` where the reader normalised
    ``"3.3."``. A label the reader inferred but did not write (a heading numbered only by
    position, say) is simply not found, and the unit is then never renumbered.
    """
    marker = _HEAD_RE.match(line)
    head = marker.group(0) if marker else ""
    rest = line[len(head) :]
    if not label or not rest.startswith(label):
        return head, "", "", rest
    after = rest[len(label) :]
    separator_match = _SEPARATOR_RE.match(after)
    separator = separator_match.group(0) if separator_match else ""
    if not separator:
        # A label butted straight against its text is not a label the document wrote.
        return head, "", "", rest
    return head, label, separator, after[len(separator) :]


def _parent_of(address: str) -> str:
    """Return the parent address of an ADR-0029 address (``"/"`` for a top-level block)."""
    head, _, _ = address.rpartition("/")
    return head or "/"


def _parties(tree: BlockTree) -> tuple[str, ...]:
    """The two most-cited ``party`` span texts, for `edit_text`'s ``party_swap`` style."""
    counts: dict[str, int] = {}
    for block in tree.walk():
        for span in block.spans:
            if span.type == "party":
                name = block.text[span.start : span.end].strip()
                if name:
                    counts[name] = counts.get(name, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return tuple(name for name, _ in ranked[:2])


# --------------------------------------------------------------------------
# The mutation state and its result
# --------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class Split:
    """One source unit that became several test units (labelled, unscored in 1.0)."""

    source: str
    tests: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class Merge:
    """Several source units that became one test unit (labelled, unscored in 1.0)."""

    sources: tuple[str, ...]
    test: str


@dataclass(frozen=True, kw_only=True, slots=True)
class Mutation:
    """A mutated document and the ground truth about how it got that way."""

    document: Document
    moved: frozenset[str]
    inserted: frozenset[str]
    deleted: tuple[str, ...]
    splits: tuple[Split, ...]
    merges: tuple[Merge, ...]
    operations: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class Step:
    """One entry of a mutation plan: an operator and its arguments."""

    op: str
    count: int = 1
    style: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Step:
        unknown = sorted(set(data) - {"op", "count", "style"})
        if unknown:
            raise MutationError(f"unknown plan step keys: {', '.join(unknown)}")
        if "op" not in data:
            raise MutationError("a plan step needs an 'op'")
        op = str(data["op"])
        if op not in OPERATORS:
            raise MutationError(
                f"unknown operator {op!r}; known operators are {', '.join(sorted(OPERATORS))}"
            )
        return cls(op=op, count=int(data.get("count", 1)), style=data.get("style"))


@dataclass
class _State:
    """The working state of a mutation: the unit list plus what has happened to it."""

    units: list[Unit]
    document: Document
    moved: set[str] = field(default_factory=set)
    inserted: set[str] = field(default_factory=set)
    deleted: list[str] = field(default_factory=list)
    splits: list[Split] = field(default_factory=list)
    merges: list[Merge] = field(default_factory=list)
    operations: list[str] = field(default_factory=list)
    touched: set[str] = field(default_factory=set)
    counter: int = 0

    def fresh_uid(self, prefix: str) -> str:
        """Return a new, stable uid for a unit the generator created."""
        self.counter += 1
        return f"{prefix}{self.counter:04d}"

    def index_of(self, uid: str) -> int:
        for index, unit in enumerate(self.units):
            if unit.uid == uid:
                return index
        raise MutationError(f"no unit {uid!r} in the document")

    def note(self, message: str) -> None:
        self.operations.append(message)


# --------------------------------------------------------------------------
# Deterministic drawing
# --------------------------------------------------------------------------


def _draw(rng: Random, population: Sequence[Unit], count: int) -> list[Unit]:
    """Draw `count` distinct members of `population` using only `Random.randrange`.

    `random.sample`, `random.shuffle` and `random.choice` have all changed implementation
    between CPython releases; ``randrange`` on an explicit list has not, and the committed
    corpus is byte-compared across five Python versions in CI.
    """
    pool = list(population)
    drawn: list[Unit] = []
    for _ in range(min(count, len(pool))):
        drawn.append(pool.pop(rng.randrange(len(pool))))
    return drawn


def _pick(rng: Random, population: Sequence[str]) -> str:
    return population[rng.randrange(len(population))]


# --------------------------------------------------------------------------
# Runs and renumbering
# --------------------------------------------------------------------------


def _run_of(state: _State, unit: Unit) -> list[int]:
    """Return the indices of the sibling run `unit` belongs to, in document order.

    A run is every unit with the same parent address and the same block kind. That is the scope
    a label means something in -- clause 3.3 is the third child of section 3, and nothing about
    section 4 tells you what to call it.
    """
    return [
        index
        for index, other in enumerate(state.units)
        if other.parent == unit.parent and other.kind is unit.kind
    ]


def _scheme_of(state: _State, run: Sequence[int]) -> LabelScheme | None:
    """Return the label scheme a run counts under, or ``None`` if it does not count."""
    members = [state.units[index] for index in run]
    if not members or not all(member.renumberable for member in members):
        return None
    scheme = _scheme_for(members[0].label_text, members[0].separator)
    if scheme is None:
        return None
    if any(scheme.parse(member.label_text) is None for member in members):
        return None
    return scheme


def _renumber(
    state: _State, run: Sequence[int], scheme: LabelScheme, *, start: int | None = None
) -> dict[str, str]:
    """Relabel a run consecutively under `scheme`, returning ``{old label: new label}``.

    Only labels that actually changed are in the map, which is what
    `_rewrite_references` then rewrites.
    """
    members = [state.units[index] for index in run]
    first = start if start is not None else (scheme.parse(members[0].label_text) or 1)
    changes: dict[str, str] = {}
    for offset, index in enumerate(run):
        unit = state.units[index]
        new_label = scheme.format(first + offset)
        if new_label != unit.label_text:
            changes[unit.label_text] = new_label
        state.units[index] = replace(
            unit, label_text=new_label, separator=scheme.separator, label=new_label
        )
    return changes


def _sentinel(position: int) -> str:
    """A placeholder that no label pattern can match, so rewrites do not chain.

    Renumbering a run produces a map like ``{"3.3": "3.4", "3.4": "3.5"}``, and rewriting one
    citation at a time would turn a citation of 3.3 into 3.4 and then into 3.5. Every citation is
    therefore replaced by a letters-only placeholder first, and the placeholders resolved
    afterwards, which makes the substitution simultaneous.
    """
    return "\x00" + chr(ord("A") + position % 26) * (position // 26 + 1) + "\x00"


def _rewrite_references(state: _State, changes: dict[str, str]) -> None:
    """Rewrite every cross-reference whose cited label changed.

    The `Unit.references` the semantic pass gave us say which units cite which labels, so this
    never guesses that a bare number in prose is a citation: only a block whose own
    ``cross_reference`` span cited the old label is touched, and only where that label stands as
    its own token.

    **Bare decimal labels are deliberately left alone.** ``5`` means clause 5 in one run and
    schedule item 5 in another, and `Unit.references` records the cited value, not the run it
    belongs to; rewriting it would sometimes follow the wrong renumbering and write a ground
    truth that is confidently wrong. In practice nothing is lost: no operator renumbers a
    heading, so a document's section numbers never move, and the citations that do have to follow
    a renumbering -- ``3.3``, ``(a)``, ``Schedule 1`` -- are all unambiguous.
    """
    rewritable = {old: new for old, new in changes.items() if not _DECIMAL_RE.match(old)}
    if not rewritable:
        return
    for index, unit in enumerate(state.units):
        cited = sorted({label for label in unit.references if label in rewritable}, key=len)
        if not cited:
            continue
        body = unit.body_text
        placeholders: list[tuple[str, str]] = []
        for position, old in enumerate(reversed(cited)):
            token = _sentinel(position)
            placeholders.append((token, rewritable[old]))
            # Not followed by a further digit or word character, so ``3.3`` in ``3.30`` and in
            # ``3.3.1`` is left alone while ``3.3`` at the end of a sentence is not.
            body = re.sub(rf"(?<![\w.]){re.escape(old)}(?!\.?\d)(?!\w)", token, body)
        for token, new in placeholders:
            body = body.replace(token, new)
        state.units[index] = replace(
            unit,
            body=tuple(body.split("\n")),
            references=tuple(changes.get(label, label) for label in unit.references),
        )


def _renumber_run_of(state: _State, unit: Unit, *, start: int | None = None) -> dict[str, str]:
    """Renumber the run `unit` sits in, if it counts, and return the label changes.

    :param start: the ordinal the run begins at. Pass the ordinal the run had *before* the
        change when a member was removed from its head: a section that loses clause 7.1 renumbers
        7.2 down to 7.1, and reading the start off what is left would instead leave the run
        beginning at 7.2 -- a document nobody would draft.
    """
    run = _run_of(state, unit)
    scheme = _scheme_of(state, run)
    if scheme is None:
        return {}
    return _renumber(state, run, scheme, start=start)


def _run_start(state: _State, unit: Unit) -> int | None:
    """The ordinal the run `unit` belongs to begins at, or ``None`` if the run does not count."""
    run = _run_of(state, unit)
    scheme = _scheme_of(state, run)
    if scheme is None:
        return None
    return scheme.parse(state.units[run[0]].label_text)


# --------------------------------------------------------------------------
# Eligibility
# --------------------------------------------------------------------------

_EDITABLE_KINDS = frozenset({BlockKind.PARAGRAPH, BlockKind.LIST_ITEM})
_MIN_EDIT_WORDS = 8
_MIN_MOVE_WORDS = 8


def _eligible(state: _State, *, min_words: int, kinds: Iterable[BlockKind]) -> list[Unit]:
    """Units this plan has not touched yet, of a kind worth mutating and long enough to matter."""
    allowed = frozenset(kinds)
    return [
        unit
        for unit in state.units
        if unit.kind in allowed
        and unit.uid not in state.touched
        and len(normalise(unit.body_text).split()) >= min_words
    ]


def _has_descendants(state: _State, unit: Unit) -> bool:
    prefix = f"{unit.address}/"
    return any(other.address.startswith(prefix) for other in state.units)


def _subtree(state: _State, unit: Unit) -> list[int]:
    """The indices of `unit` and every unit nested under it, contiguous in document order."""
    prefix = f"{unit.address}/"
    return [
        index
        for index, other in enumerate(state.units)
        if other.uid == unit.uid or other.address.startswith(prefix)
    ]


# --------------------------------------------------------------------------
# Text banks
# --------------------------------------------------------------------------

#: Clauses `insert_clause` inserts. Generic contract prose: long enough to be a real block, and
#: deliberately not similar to anything in the corpus documents, so an inserted clause that the
#: engine pairs with an existing one is a genuine false positive rather than an ambiguity.
BOILERPLATE: tuple[str, ...] = (
    "Each party shall keep records of the steps it takes under this Agreement and shall make "
    "those records available to the other party on reasonable written request.",
    "Neither party shall engage the other party's personnel without written consent during the "
    "Term and for six months after it ends.",
    "The parties shall review the operation of this Agreement at least once in each year of the "
    "Term and shall record the outcome of that review in writing.",
    "A party that is prevented from performing an obligation by an event beyond its reasonable "
    "control shall tell the other party promptly and shall resume performance as soon as it can.",
    "Any dispute arising out of this Agreement shall first be referred to a senior representative "
    "of each party, who shall meet within ten Business Days of the referral.",
    "Each party warrants that it has the authority to enter into this Agreement and that doing so "
    "does not breach any obligation it owes to anyone else.",
    "The Supplier shall keep insurance appropriate to the Services in force throughout the Term "
    "and shall give evidence of it on request.",
    "Nothing in this Agreement creates a partnership or a relationship of employment between the "
    "parties or between one party and the other party's personnel.",
)

#: Sentences `edit_text`'s ``sentence_insert`` style appends.
APPENDED_SENTENCES: tuple[str, ...] = (
    "This obligation survives the end of the Term.",
    "The party relying on this provision shall bear the cost of doing so.",
    "A failure to enforce this provision is not a waiver of it.",
    "The parties shall record any agreed change to this provision in writing.",
)

#: Spelled-out numbers `edit_text`'s ``number_pair`` style swaps, with their digits.
NUMBER_WORDS: tuple[tuple[str, str, str, str], ...] = (
    ("thirty", "30", "sixty", "60"),
    ("ninety", "90", "sixty", "60"),
    ("sixty", "60", "thirty", "30"),
    ("twenty", "20", "thirty", "30"),
    ("fifteen", "15", "twenty", "20"),
    ("twelve", "12", "eighteen", "18"),
    ("ten", "10", "twenty", "20"),
    ("five", "5", "seven", "7"),
    ("four", "4", "six", "6"),
    ("three", "3", "four", "4"),
    ("two", "2", "three", "3"),
)

#: Duration units `edit_text`'s ``duration`` style swaps.
DURATIONS: tuple[tuple[str, str], ...] = (
    ("Business Days", "calendar days"),
    ("Business Day", "calendar day"),
    ("months", "weeks"),
    ("month", "week"),
    ("hours", "minutes"),
    ("hour", "minutes"),
    ("days", "Business Days"),
    ("years", "months"),
)

#: Word-for-word substitutions `edit_text`'s ``word_substitute`` style makes.
SUBSTITUTIONS: tuple[tuple[str, str], ...] = (
    ("shall", "must"),
    ("reasonable", "commercially reasonable"),
    ("promptly", "without undue delay"),
    ("written notice", "signed written notice"),
    ("in writing", "in a signed writing"),
    ("may", "is entitled to"),
    ("agreed", "expressly agreed"),
)

EDIT_STYLES: tuple[str, ...] = (
    "number_pair",
    "duration",
    "party_swap",
    "sentence_insert",
    "sentence_drop",
    "word_substitute",
)

RELABEL_STYLES: tuple[str, ...] = ("shift", "alpha")

TABLE_STYLES: tuple[str, ...] = ("cell_edit", "row_insert", "row_delete")

_SENTENCE_SPLIT = re.compile(r'(?<=[.;])\s+(?=[A-Z"(])')


def _sentences(text: str) -> list[str]:
    return [part for part in _SENTENCE_SPLIT.split(normalise(text)) if part]


#: Where a one-sentence clause can be cut in two. Legal drafting piles obligations into one
#: sentence far more often than into two, so a split operator that only ever cut at a full stop
#: would find almost nothing to do in a real contract -- the sample pair has one multi-sentence
#: clause in a hundred. These are the joins a drafter actually breaks a clause at.
_CLAUSE_JOINS: tuple[str, ...] = ("; ", ", and ", ", or ", " and shall ", ", provided that ")


def _split_pieces(text: str) -> list[str] | None:
    """Return the two or more blocks `text` splits into, or ``None`` if it does not split.

    Sentence boundaries first, because they need no rewriting at all. Failing that, the clause
    is cut at a join and the text on each side kept exactly as it was, punctuation included: the
    second block opening with ``and shall ...`` is what a half-finished split really looks like,
    and inventing a capital letter would make the two sides differ from the source by more than
    the split itself.
    """
    normalised = normalise(text)
    sentences = _sentences(normalised)
    if len(sentences) >= 2:
        return sentences
    for join in _CLAUSE_JOINS:
        at = normalised.find(join, len(normalised) // 4)
        if at < 0:
            continue
        head, tail = normalised[:at].strip(), normalised[at + len(join) :].strip()
        if len(head.split()) >= 4 and len(tail.split()) >= 4:
            return [head if head.endswith((".", ";")) else f"{head}.", tail]
    return None




# --------------------------------------------------------------------------
# Applying one change, and rolling it back when the reader disagrees
# --------------------------------------------------------------------------


@dataclass
class _Snapshot:
    """Everything a single change can touch, copied so it can be put back."""

    units: list[Unit]
    moved: set[str]
    inserted: set[str]
    deleted: list[str]
    splits: list[Split]
    merges: list[Merge]
    operations: list[str]
    touched: set[str]
    counter: int


def _snapshot(state: _State) -> _Snapshot:
    return _Snapshot(
        units=list(state.units),
        moved=set(state.moved),
        inserted=set(state.inserted),
        deleted=list(state.deleted),
        splits=list(state.splits),
        merges=list(state.merges),
        operations=list(state.operations),
        touched=set(state.touched),
        counter=state.counter,
    )


def _restore(state: _State, snapshot: _Snapshot) -> None:
    state.units = snapshot.units
    state.moved = snapshot.moved
    state.inserted = snapshot.inserted
    state.deleted = snapshot.deleted
    state.splits = snapshot.splits
    state.merges = snapshot.merges
    state.operations = snapshot.operations
    state.touched = snapshot.touched
    state.counter = snapshot.counter


def _reads_back(state: _State) -> bool:
    """True when the document still reads as exactly the units the state says it has.

    Every operator works on lines while the ground truth is addresses in the tree those lines
    read as, so a change that alters how the reader *groups* the text -- a re-wrap the plain-text
    reader takes as a continuation paragraph, a merge markdown reads back as two list items --
    breaks the correspondence between unit *n* and block *n* and would make every label after it
    name the wrong address. Rather than restrict every operator to the intersection of what two
    readers happen to do, each change is applied, read back, and rolled back if the reader
    disagrees. A rolled-back change leaves no trace in the ground truth: the corpus is quieter on
    that document, never wrong about it.
    """
    text = replace(state.document, units=tuple(state.units)).render()
    try:
        reread = Document.from_text(
            text, format=state.document.format, profile=state.document.profile
        )
    except MutationError:
        return False
    if len(reread.units) != len(state.units):
        return False
    return all(
        normalise(written.text) == normalise(read.text)
        for written, read in zip(state.units, reread.units)
    )


def _attempt(state: _State, change: Callable[[], str | None]) -> bool:
    """Apply one change atomically, keeping it only if the reader still agrees.

    :param change: makes the change and returns the line for the operation log, or ``None`` if
        it turned out not to apply after all.
    :return: whether the change was kept.
    """
    snapshot = _snapshot(state)
    note = change()
    if note is None or not _reads_back(state):
        _restore(state, snapshot)
        return False
    state.note(note)
    return True


# --------------------------------------------------------------------------
# Operators
# --------------------------------------------------------------------------


def _edit_body(unit: Unit, style: str, rng: Random, parties: Sequence[str]) -> str | None:
    """Return `unit`'s body with `style` applied, or ``None`` if the style does not apply."""
    body = unit.body_text
    if style == "number_pair":
        for word, digits, new_word, new_digits in NUMBER_WORDS:
            pattern = re.compile(rf"\b{word}\b(\s*\({digits}\))?")
            match = pattern.search(body)
            if match is None:
                continue
            replacement = new_word if match.group(1) is None else f"{new_word} ({new_digits})"
            return body[: match.start()] + replacement + body[match.end() :]
        return None
    if style == "duration":
        for old, new in DURATIONS:
            match = re.search(rf"\b{re.escape(old)}\b", body)
            if match is None:
                continue
            return body[: match.start()] + new + body[match.end() :]
        return None
    if style == "party_swap":
        if len(parties) < 2:
            return None
        first, second = parties[0], parties[1]
        if first not in body or second not in body:
            return None
        sentinel = "\x00"
        swapped = body.replace(first, sentinel).replace(second, first).replace(sentinel, second)
        return swapped if swapped != body else None
    if style == "sentence_insert":
        sentence = _pick(rng, APPENDED_SENTENCES)
        return f"{body.rstrip()} {sentence}"
    if style == "sentence_drop":
        sentences = _sentences(body)
        if len(sentences) < 2:
            return None
        return " ".join(sentences[:-1])
    if style == "word_substitute":
        for old, new in SUBSTITUTIONS:
            match = re.search(rf"\b{re.escape(old)}\b", body)
            if match is None:
                continue
            return body[: match.start()] + new + body[match.end() :]
        return None
    raise MutationError(f"unknown edit style {style!r}; known styles are {', '.join(EDIT_STYLES)}")


def edit_text(state: _State, rng: Random, step: Step) -> None:
    """Apply an in-place inline edit to up to `step.count` blocks.

    With no ``style``, the styles are cycled in `EDIT_STYLES` order so that one plan entry with a
    count of twelve exercises all six rather than twelve of whichever happens to apply first.
    """
    styles = (step.style,) if step.style else EDIT_STYLES
    applied = 0
    for unit in _draw(
        rng, _eligible(state, min_words=_MIN_EDIT_WORDS, kinds=_EDITABLE_KINDS), step.count * 3
    ):
        if applied >= step.count:
            break
        style = styles[applied % len(styles)]

        def change(unit: Unit = unit, style: str = style) -> str | None:
            edited = _edit_body(unit, style, rng, state.document.parties)
            if edited is None or edited == unit.body_text:
                return None
            state.units[state.index_of(unit.uid)] = unit.with_body(edited)
            state.touched.add(unit.uid)
            return f"edit_text({style}) at {unit.address}"

        if _attempt(state, change):
            applied += 1


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap, written out rather than taken from `textwrap`.

    `textwrap` has options that change how it treats hyphens, long words and sentence ends; a
    dozen lines that only ever split on spaces are easier to promise never change the normalised
    text, which is the whole point of the negative control.
    """
    words = normalise(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        if len(current) + 1 + len(word) <= width:
            current = f"{current} {word}"
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def _widen_gaps(text: str) -> str | None:
    """Double the space after each sentence end, or after the first comma if there is none.

    The re-wrap in `whitespace_only` is the change a lawyer would recognise, but a reader may
    legitimately take a re-wrapped block as two (a continuation paragraph), and `_attempt` then
    rolls it back. This is the fallback that always applies and can never regroup anything: the
    line structure is untouched, so only the amount of whitespace inside a line changes.
    """
    widened = re.sub(r"(?<=[.;:]) (?=[A-Z\"(])", "  ", text)
    if widened != text:
        return widened
    widened = re.sub(r"(?<=,) ", "  ", text, count=1)
    return widened if widened != text else None


def whitespace_only(state: _State, rng: Random, step: Step) -> None:
    """Change a block's whitespace and nothing else. The negative control.

    ADR-0034 digests a block's *normalised* text, so a block this operator touched keeps its
    digest and its label row says ``kind: same``. An engine that reports a change here has lost
    precision, and the labels are what says so.
    """
    applied = 0
    for unit in _draw(
        rng, _eligible(state, min_words=_MIN_EDIT_WORDS, kinds=_EDITABLE_KINDS), step.count * 3
    ):
        if applied >= step.count:
            break
        width = 48 + 8 * rng.randrange(4)

        def rewrap(unit: Unit = unit, width: int = width) -> str | None:
            wrapped = _wrap(unit.body_text, width)
            if wrapped == list(unit.body):
                return None
            state.units[state.index_of(unit.uid)] = replace(unit, body=tuple(wrapped))
            state.touched.add(unit.uid)
            return f"whitespace_only(rewrap {width}) at {unit.address}"

        def widen(unit: Unit = unit) -> str | None:
            widened = [_widen_gaps(line) or line for line in unit.body]
            if widened == list(unit.body):
                return None
            state.units[state.index_of(unit.uid)] = replace(unit, body=tuple(widened))
            state.touched.add(unit.uid)
            return f"whitespace_only(gaps) at {unit.address}"

        if _attempt(state, rewrap) or _attempt(state, widen):
            applied += 1


def insert_clause(state: _State, rng: Random, step: Step) -> None:
    """Insert a boilerplate clause into a run, renumber it, and follow the cross-references."""
    candidates = [
        unit
        for unit in state.units
        if unit.kind is BlockKind.LIST_ITEM and unit.renumberable and len(_run_of(state, unit)) >= 2
    ]
    applied = 0
    for anchor in _draw(rng, candidates, step.count * 3):
        if applied >= step.count:
            break
        body = _pick(rng, BOILERPLATE)

        def change(anchor: Unit = anchor, body: str = body) -> str | None:
            run = _run_of(state, anchor)
            if _scheme_of(state, run) is None or len(run) < 2:
                return None
            at = run[rng.randrange(1, len(run))]
            neighbour = state.units[at]
            uid = state.fresh_uid("n")
            # The new clause borrows its neighbour's typography and run membership: it is a
            # sibling of the clauses around it, and the renumbering below gives it its label.
            new_unit = replace(neighbour, uid=uid, origin=None, body=(body,), references=())
            state.units.insert(at, new_unit)
            state.inserted.add(uid)
            state.touched.add(uid)
            _rewrite_references(state, _renumber_run_of(state, new_unit))
            return f"insert_clause before {neighbour.address}"

        if _attempt(state, change):
            applied += 1


def delete_block(state: _State, rng: Random, step: Step) -> None:
    """Delete a leaf block, renumber its run, and follow the cross-references."""
    candidates = [
        unit
        for unit in state.units
        if unit.kind is BlockKind.LIST_ITEM
        and unit.origin is not None
        and unit.uid not in state.touched
        and unit.renumberable
        and not _has_descendants(state, unit)
        and len(_run_of(state, unit)) >= 3
    ]
    applied = 0
    for unit in _draw(rng, candidates, step.count * 3):
        if applied >= step.count:
            break

        def change(unit: Unit = unit) -> str | None:
            run = _run_of(state, unit)
            if len(run) < 3:
                return None
            index = state.index_of(unit.uid)
            neighbour = state.units[run[1] if run[0] == index else run[0]]
            start = _run_start(state, unit)
            state.units.pop(index)
            state.deleted.append(unit.uid)
            state.touched.add(unit.uid)
            _rewrite_references(state, _renumber_run_of(state, neighbour, start=start))
            return f"delete_block at {unit.address}"

        if _attempt(state, change):
            applied += 1


def relabel_run(state: _State, rng: Random, step: Step) -> None:
    """Renumber a whole run with no text change, separating label matching from content."""
    style = step.style or "shift"
    if style not in RELABEL_STYLES:
        raise MutationError(
            f"unknown relabel style {style!r}; known styles are {', '.join(RELABEL_STYLES)}"
        )
    seen: set[str] = set()
    candidates: list[Unit] = []
    for unit in state.units:
        if unit.kind is not BlockKind.LIST_ITEM or not unit.renumberable or unit.parent in seen:
            continue
        seen.add(unit.parent)
        run = _run_of(state, unit)
        if len(run) >= 2 and _scheme_of(state, run) is not None:
            candidates.append(unit)
    applied = 0
    for anchor in _draw(rng, candidates, step.count * 3):
        if applied >= step.count:
            break

        def change(anchor: Unit = anchor) -> str | None:
            run = _run_of(state, anchor)
            scheme = _scheme_of(state, run)
            if scheme is None:
                return None
            if style == "alpha":
                if len(run) > 26:
                    return None
                changes = _renumber(state, run, LabelScheme(name="alpha", separator=" "), start=1)
            else:
                first = scheme.parse(state.units[run[0]].label_text) or 1
                changes = _renumber(state, run, scheme, start=first + 1)
            if not changes:
                return None
            _rewrite_references(state, changes)
            return f"relabel_run({style}) at {anchor.parent}"

        if _attempt(state, change):
            applied += 1


def move_block(state: _State, rng: Random, step: Step) -> None:
    """Move a clause and everything nested under it into another section.

    Cross-scope where the document has scopes to cross, and otherwise a reordering within the one
    scope it has -- which is still a move, because ADR-0032's descent reports a pair that crosses
    another pair in its own sibling group as one. A flat document of identical paragraphs has no
    other kind of move to offer, and it is exactly the document ADR-0010's repetitive-schedule
    pathology is about.
    """
    applied = 0
    for _ in range(step.count * 2):
        if applied >= step.count:
            break
        movers = [
            unit
            for unit in state.units
            if unit.kind in _EDITABLE_KINDS
            and unit.origin is not None
            and unit.uid not in state.touched
            and len(normalise(unit.body_text).split()) >= _MIN_MOVE_WORDS
        ]
        if not movers:
            return
        mover = _draw(rng, movers, 1)[0]
        destinations = [
            unit
            for unit in state.units
            if unit.kind is mover.kind
            and unit.parent != mover.parent
            and unit.uid not in state.touched
            and len(_run_of(state, unit)) >= 2
        ] or _distant_siblings(state, mover)
        if not destinations:
            return
        target = _draw(rng, destinations, 1)[0]

        def change(mover: Unit = mover, target: Unit = target) -> str | None:
            indices = _subtree(state, mover)
            moving = [state.units[index] for index in indices]
            if any(unit.uid == target.uid for unit in moving):
                return None
            # The scheme of the run the clause is joining, read before it joins it, so the
            # incoming label does not have a vote on what the run counts as.
            destination_scheme = _scheme_of(state, _run_of(state, target))
            origin_start = _run_start(state, mover)
            original_label = moving[0].label_text
            for index in reversed(indices):
                state.units.pop(index)
            origin_run = [
                other
                for other in state.units
                if other.parent == mover.parent and other.kind is mover.kind
            ]
            insert_at = max(_subtree(state, target)) + 1
            # The moved clause takes on its new siblings' typography and numbering -- a clause
            # relocated into section 5 is called 5.something, not 7.1 -- but only when both
            # sides actually write a label: adopting a separator with no label to put it after
            # would leave a stray ". " at the head of the paragraph. Any label the destination
            # scheme can express will do, because the renumbering below immediately replaces it.
            first = replace(moving[0], gap=target.gap, parent=target.parent)
            if moving[0].renumberable and target.renumberable:
                first = replace(first, head=target.head, separator=target.separator)
                if destination_scheme is not None:
                    first = replace(
                        first,
                        label_text=destination_scheme.format(1),
                        separator=destination_scheme.separator,
                    )
            for offset, unit in enumerate([first, *moving[1:]]):
                state.units.insert(insert_at + offset, unit)
            state.moved.add(mover.uid)
            state.touched.update(unit.uid for unit in moving)
            changes = _renumber_run_of(state, first)
            # The clause's own label moved with it, and citations of it have to follow. The
            # renumbering above only knows the placeholder label it was given on arrival, so the
            # real journey -- 7.1 to 5.4 -- is recorded here.
            arrived = state.units[state.index_of(mover.uid)].label_text
            if original_label and arrived and arrived != original_label:
                changes[original_label] = arrived
            if origin_run:
                changes.update(_renumber_run_of(state, origin_run[0], start=origin_start))
            _rewrite_references(state, changes)
            return f"move_block {mover.address} into {target.parent}"

        if _attempt(state, change):
            applied += 1


def _distant_siblings(state: _State, mover: Unit) -> list[Unit]:
    """Siblings far enough from `mover` that moving to them is a genuine reordering.

    A document with one sibling group -- a flat run of paragraphs -- has no other scope to move
    into. Reordering within the group is still a move, and "far enough" keeps it from being a
    swap with a neighbour, which reads as an edit rather than a relocation.
    """
    run = _run_of(state, mover)
    if len(run) < 6:
        return []
    position = run.index(state.index_of(mover.uid))
    return [
        state.units[index]
        for offset, index in enumerate(run)
        if abs(offset - position) >= 3 and state.units[index].uid not in state.touched
    ]


def split_block(state: _State, rng: Random, step: Step) -> None:
    """Split a block into two, recorded into ``splits`` and scored by nothing in 1.0.

    ADR-0009 puts splits and merges after moves, and #141 asks for them to be labelled now so the
    1.1 metric has data. They land in ``splits``, which `benchmark.labels.check_totality` counts
    and every 1.0 denominator ignores.
    """
    candidates = [
        unit
        for unit in _eligible(state, min_words=_MIN_EDIT_WORDS, kinds={BlockKind.LIST_ITEM})
        if unit.renumberable
        and _split_pieces(unit.body_text) is not None
        and not _has_descendants(state, unit)
        and _scheme_of(state, _run_of(state, unit)) is not None
    ]
    applied = 0
    for unit in _draw(rng, candidates, step.count * 3):
        if applied >= step.count:
            break

        def change(unit: Unit = unit) -> str | None:
            pieces = _split_pieces(unit.body_text)
            if pieces is None:
                return None
            at = 1 + rng.randrange(len(pieces) - 1)
            index = state.index_of(unit.uid)
            head_uid, tail_uid = state.fresh_uid("a"), state.fresh_uid("b")
            first = replace(unit, uid=head_uid, origin=None, body=(" ".join(pieces[:at]),))
            second = replace(unit, uid=tail_uid, origin=None, body=(" ".join(pieces[at:]),))
            state.units[index : index + 1] = [first, second]
            state.splits.append(Split(source=unit.uid, tests=(head_uid, tail_uid)))
            state.touched.update({unit.uid, head_uid, tail_uid})
            _rewrite_references(state, _renumber_run_of(state, first))
            return f"split_block at {unit.address}"

        if _attempt(state, change):
            applied += 1


def merge_blocks(state: _State, rng: Random, step: Step) -> None:
    """Merge a block into the sibling before it, recorded into ``merges``."""
    applied = 0
    for _ in range(step.count * 2):
        if applied >= step.count:
            break
        candidates = _mergeable(state)
        if not candidates:
            return
        unit = _draw(rng, candidates, 1)[0]

        def change(unit: Unit = unit) -> str | None:
            index = state.index_of(unit.uid)
            previous = state.units[index - 1]
            merged_uid = state.fresh_uid("m")
            merged = replace(
                previous,
                uid=merged_uid,
                origin=None,
                body=(f"{normalise(previous.body_text)} {normalise(unit.body_text)}",),
                references=previous.references + unit.references,
            )
            state.units[index - 1 : index + 1] = [merged]
            state.merges.append(Merge(sources=(previous.uid, unit.uid), test=merged_uid))
            state.touched.update({previous.uid, unit.uid, merged_uid})
            _rewrite_references(state, _renumber_run_of(state, merged))
            return f"merge_blocks {previous.address} + {unit.address}"

        if _attempt(state, change):
            applied += 1


def _mergeable(state: _State) -> list[Unit]:
    """Units that immediately follow an untouched sibling they could be merged into."""
    candidates: list[Unit] = []
    for unit in state.units:
        if unit.kind is not BlockKind.LIST_ITEM or unit.uid in state.touched:
            continue
        if unit.origin is None or not unit.renumberable:
            continue
        run = _run_of(state, unit)
        if len(run) < 2 or _scheme_of(state, run) is None:
            continue
        index = state.index_of(unit.uid)
        position = run.index(index)
        if position == 0 or run[position - 1] != index - 1:
            continue
        previous = state.units[index - 1]
        if (
            previous.uid in state.touched
            or previous.origin is None
            or _has_descendants(state, previous)
            or _has_descendants(state, unit)
        ):
            continue
        candidates.append(unit)
    return candidates


def _row_cells(unit: Unit) -> list[str]:
    """Split a markdown table row's line into its cell texts."""
    return [cell.strip() for cell in unit.lines[0].strip().strip("|").split("|")]


def _row_line(cells: Sequence[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def table_edit(state: _State, rng: Random, step: Step) -> None:
    """Edit a cell, insert a row or delete a row, for #134's table alignment.

    Header rows are left alone: the delimiter line rides on the header's unit, and a table whose
    header moved is a different table rather than an edited one.
    """
    style = step.style or "cell_edit"
    if style not in TABLE_STYLES:
        raise MutationError(
            f"unknown table style {style!r}; known styles are {', '.join(TABLE_STYLES)}"
        )
    body_rows = [
        unit
        for unit in state.units
        if unit.kind is BlockKind.ROW
        and unit.uid not in state.touched
        and len(unit.lines) == 1
        and len(_row_cells(unit)) >= 2
    ]
    applied = 0
    for unit in _draw(rng, body_rows, step.count * 3):
        if applied >= step.count:
            break
        column = rng.randrange(len(_row_cells(unit)))

        def change(unit: Unit = unit, column: int = column) -> str | None:
            index = state.index_of(unit.uid)
            cells = _row_cells(unit)
            if style == "cell_edit":
                cells[column] = f"{cells[column]} (revised)"
                state.units[index] = replace(unit, body=(_row_line(cells),))
                state.touched.add(unit.uid)
                return f"table_edit(cell_edit) at {unit.address}"
            if style == "row_insert":
                uid = state.fresh_uid("r")
                new_cells = [f"New {position + 1}" for position in range(len(cells))]
                state.units.insert(
                    index, replace(unit, uid=uid, origin=None, body=(_row_line(new_cells),))
                )
                state.inserted.add(uid)
                state.touched.add(uid)
                return f"table_edit(row_insert) before {unit.address}"
            if len(_run_of(state, unit)) < 3:
                return None
            state.units.pop(index)
            state.deleted.append(unit.uid)
            state.touched.add(unit.uid)
            return f"table_edit(row_delete) at {unit.address}"

        if _attempt(state, change):
            applied += 1


OPERATORS: dict[str, Callable[[_State, Random, Step], None]] = {
    "edit_text": edit_text,
    "whitespace_only": whitespace_only,
    "insert_clause": insert_clause,
    "delete_block": delete_block,
    "relabel_run": relabel_run,
    "move_block": move_block,
    "split_block": split_block,
    "merge_blocks": merge_blocks,
    "table_edit": table_edit,
}


def mutate(document: Document, steps: Sequence[Step], seed: int) -> Mutation:
    """Apply `steps` to `document` under a `random.Random` seeded with `seed`.

    :param document: the source document, as `Document.from_text` built it.
    :param steps: the plan's steps, applied in order. A step that finds nothing to work on, or
        whose every candidate change the reader would regroup, is a no-op that leaves no trace in
        the ground truth -- which is why a plan naming an operator a document cannot support (a
        table edit where there is no table) still produces a valid, if quieter, pair.
    :param seed: the seed `benchmark.generate.seed_for` derived for this pair.
    :return: the mutated document and the ground truth about what changed.
    """
    state = _State(units=list(document.units), document=document)
    rng = Random(seed)
    for step in steps:
        OPERATORS[step.op](state, rng, step)
    return Mutation(
        document=replace(document, units=tuple(state.units)),
        moved=frozenset(state.moved),
        inserted=frozenset(state.inserted),
        deleted=tuple(state.deleted),
        splits=tuple(state.splits),
        merges=tuple(state.merges),
        operations=tuple(state.operations),
    )
