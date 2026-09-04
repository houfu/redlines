"""The plain-text reader: PRD § 6b's five mechanical stages (#102, R4, D17).

`PlainTextReader` turns a plain-text document into a `redlines.blocks.BlockTree`
by running the stages of PRD § 6b in order, driven by a
`redlines.profiles.Profile` (ADR-0006):

1. **normalise and segment** -- line endings, page breaks and exotic spaces are
   normalised, the text is split into paragraphs on blank lines, and
   hard-wrapped lines are re-joined (`normalise`, `segment`);
2. **detect labels** -- every paragraph is tested against the profile's label
   patterns (`redlines.readers.labels.label_candidates`);
3. **infer hierarchy** -- labels become levels through a
   `redlines.readers.labels.HierarchyStack`, which is what makes ``(i)`` after
   ``(h)`` alphabetic and ``(i)`` after ``7.2`` roman;
4. **attach continuations** -- an unlabelled paragraph becomes a child of the
   labelled block above it unless a heading claims it;
5. **recognise headings** -- short lines that look like headings are scored,
   and the score is kept in ``attrs`` rather than thrown away.

The semantic pass (roles, spans, definitions, cross-references) is *not* here:
it runs over the finished tree (#104).

Reading a document::

    from redlines.profiles import load_profile
    from redlines.readers import reader_for

    tree = reader_for("text").read(text, profile=load_profile("contract.yaml"))
    tree.fallback_count      # how much of it nothing recognised

**Every stage records what it decided**, in the block's ``attrs``, because a
mis-parse is otherwise invisible (PRD § 6b): which pattern matched and which
others also could have, how the level was reached, what the heading scored and
on which signals, why a paragraph was attached where it was. ``matched_by`` and
``confidence`` carry the summary of that per ADR-0030.

**Without a profile** the reader degrades to one block per paragraph -- exactly
what `redlines.readers.ParagraphReader` does, and for the same reason: nothing
was declared, so nothing is claimed. Every block is ``fallback`` at confidence
0.0 and alignment still works.
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
)
from ..profiles import Profile
from . import DEFAULT_MAX_CHARS, check_size, decode_source, register_reader
from .labels import (
    CONFIDENCE_RESET_HEADING,
    NEXT_DEEPER,
    NEXT_NONE,
    NEXT_PEER,
    HeadingScore,
    HierarchyStack,
    Placement,
    continuation_for,
    detect_label,
    heading_reset_name,
    heading_score,
    label_candidates,
)

__all__ = [
    "WRAP_MIN_CHARS",
    "Paragraph",
    "PlainTextReader",
    "normalise",
    "segment",
]


_PARAGRAPH_BREAK = re.compile(r"\n\s*\n+")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f]")
_BULLETS = ("-", "*", "•", "–", "—", "·")
_SENTENCE_ENDS = (".", "!", "?", ";", ":")
_TAB_WIDTH = 4

WRAP_MIN_CHARS = 45
"""How long a line must be before a capitalised next line may still wrap onto it.

Plain-text contracts are wrapped somewhere between 60 and 80 columns, so a line
that stopped well short of that stopped because its author ended it -- it is a
heading, a caption or a one-line clause -- not because a word would not fit.
45 is deliberately generous: it only has to separate a clause heading ("2.
Charges") from a wrapped sentence, and the second gate in `_is_plausible_wrap`
catches the long heading this one lets through. Lowering the bar costs a
paragraph break that was really a wrap; raising it swallows a heading, which is
the worse error, because the block below it disappears into the block above.
"""


def normalise(text: str) -> tuple[str, int]:
    """Normalise line endings, page breaks, spaces and trailing whitespace (stage 1).

    What it does, and why each one is here rather than left to the profile:

    - ``\\r\\n`` and ``\\r`` become ``\\n``, and so do the Unicode line and
      paragraph separators, so a Windows or pasted document segments the same
      way as a Unix one;
    - a form feed becomes a blank line, because a page break *is* a paragraph
      break in text extracted from a PDF;
    - non-breaking and narrow spaces become ordinary spaces, so a label pattern
      written with ``\\s`` still matches;
    - other C0 control characters are removed and counted, and the reader
      reports them as `redlines.blocks.Dropped` -- they are the one thing this
      reader throws away;
    - every line is right-stripped, so trailing whitespace cannot make a blank
      line look non-blank or change a paragraph boundary.

    Leading whitespace is deliberately kept: indentation is stage three's
    secondary signal.

    :param text: the document, as decoded text.
    :return: the normalised text and the number of control characters removed.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace("\u2028", "\n").replace("\u2029", "\n")
    text = text.replace("\f", "\n\n")
    for space in ("\u00a0", "\u2007", "\u202f", "\u2009"):
        text = text.replace(space, " ")
    text, controls = _CONTROL_CHARS.subn("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")), controls


@dataclass(frozen=True, slots=True)
class Paragraph:
    """One candidate paragraph: what stage 1 hands to stage 2.

    :param text: the paragraph's text, with any hard wraps already re-joined
        into single spaces and outer whitespace removed.
    :param indent: the leading whitespace of its first line, in characters,
        with tabs counted as four. Stage three's secondary signal.
    :param lines: how many source lines it was built from.
    :param rejoined: whether any of those lines were re-joined as a hard wrap,
        as opposed to the paragraph simply being one line.
    """

    text: str
    indent: int
    lines: int
    rejoined: bool


def segment(text: str, *, profile: Profile | None = None) -> tuple[Paragraph, ...]:
    """Split normalised text into candidate paragraphs, re-joining wraps (stage 1).

    Blank lines separate paragraphs, as they do in every plain-text convention.
    Inside a paragraph, two things can still start a new one:

    - a line that begins with one of the profile's labels. A document written
      with one clause per line and no blank lines between them is common, and
      joining ``7.1`` to ``7.2`` because no blank line separated them would lose
      the whole document's structure;
    - a line that is not a hard wrap of the one above it. PRD § 6b states that
      rule as "a line ends mid-sentence and the next begins lowercase", and both
      halves are required: ending mid-sentence alone would swallow the commonest
      shape in a plain-text contract, a one-line clause heading with its body on
      the next line ("2. Charges" / "The Client shall pay..."), which is a
      heading and a paragraph and not one sentence.

      A line beginning with a capital still joins where the line above it is a
      *plausible* hard wrap: at least `WRAP_MIN_CHARS` long, and not
      heading-shaped once its own label is stripped off the front. A label-led
      line is therefore not excluded as such -- "1. This agreement is made
      between Acme Analytics Ltd and" wraps like any other -- only one whose
      body reads as a heading. That is what keeps "…made
      between Acme Analytics Ltd and" / "Beta Retail plc." together, since a
      wrapped line routinely resumes on a party name or a defined term, without
      letting a short label-led heading claim the paragraph below it.

      A line that starts a bullet, or that changes case wholesale, never joins:
      that guard is what keeps an all-caps heading, or a page header extracted
      from a PDF, out of the sentence it interrupts.

    :param text: text that has been through `normalise`.
    :param profile: the active profile, whose label patterns decide where a
        line begins a new paragraph. ``None`` means no labels exist.
    :return: the candidate paragraphs, in document order.
    """
    paragraphs: list[Paragraph] = []
    for chunk in _PARAGRAPH_BREAK.split(text):
        lines = [line for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue
        buffer: list[str] = []
        indent = 0
        joins = 0
        for line in lines:
            starts_label = bool(label_candidates(line, profile=profile))
            if (
                buffer
                and not starts_label
                and _is_wrap(buffer[-1], line, profile=profile)
            ):
                buffer.append(line.strip())
                joins += 1
                continue
            if buffer:
                paragraphs.append(_paragraph(buffer, indent, joins))
            buffer = [line.strip()]
            indent = _indent_of(line)
            joins = 0
        if buffer:
            paragraphs.append(_paragraph(buffer, indent, joins))
    return tuple(paragraphs)


def _paragraph(lines: list[str], indent: int, joins: int) -> Paragraph:
    """Build a `Paragraph` from the lines gathered for it."""
    return Paragraph(
        text=" ".join(lines).strip(),
        indent=indent,
        lines=len(lines),
        rejoined=joins > 0,
    )


def _indent_of(line: str) -> int:
    """Return the width of ``line``'s leading whitespace, tabs counted as four."""
    width = 0
    for char in line:
        if char == "\t":
            width += _TAB_WIDTH
        elif char == " ":
            width += 1
        else:
            break
    return width


def _is_wrap(previous: str, line: str, *, profile: Profile | None = None) -> bool:
    """Whether ``line`` is a hard wrap of ``previous`` rather than a new paragraph.

    PRD § 6b's rule, with one documented widening: "a line ends mid-sentence and
    the next begins lowercase" joins outright, and a next line beginning with a
    capital joins only when `_is_plausible_wrap` says the line above it could
    have been wrapped at all. See `segment`.
    """
    before = previous.rstrip()
    after = line.strip()
    if not before or not after:
        return False
    if before.endswith(_SENTENCE_ENDS):
        return False
    if after.startswith(_BULLETS):
        return False
    if _is_shouting(before) != _is_shouting(after):
        return False
    if after[:1].islower():
        return True
    return _is_plausible_wrap(before, profile=profile)


def _is_plausible_wrap(before: str, *, profile: Profile | None) -> bool:
    """Whether ``before`` could be a wrapped line rather than a heading of its own.

    Two gates, both of which a one-line clause heading fails and a genuinely
    wrapped line passes: a wrapped line is close to the document's wrap width,
    and it does not look like a heading once its own label is off the front.
    """
    body = before.strip()
    if len(body) < WRAP_MIN_CHARS:
        return False
    match = detect_label(body, profile=profile)
    if match is not None:
        body = match.text
    rule = profile.heading_rule if profile is not None else None
    return not heading_score(body, rule=rule).is_heading


def _is_shouting(text: str) -> bool:
    """Whether ``text`` has letters and none of them are lower case."""
    return any(char.isalpha() for char in text) and text == text.upper()


@dataclass(slots=True)
class _Node:
    """A block under construction, before its children are known.

    `redlines.blocks.Block` is frozen, so the tree is assembled in these and
    frozen bottom-up by `finish` when the reader is done with it.
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


class PlainTextReader:
    """Plain text into a labelled block tree, under a structure profile (R4).

    Registered for the ``"text"`` format, replacing the `ParagraphReader`
    placeholder, whose behaviour survives as this reader's degrade path when it
    is given no profile.

    The reader holds no state between reads: the numbering stack, the container
    stack and the counters all live in one `read` call, so the same input and
    profile always give the same tree (N1).
    """

    name = "text"
    formats = ("text",)

    def read(
        self,
        source: str | bytes,
        *,
        profile: Profile | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> BlockTree:
        """Read ``source`` into a tree of labelled blocks.

        :param source: the document, as text or as UTF-8 bytes.
        :param profile: the structure profile (ADR-0006). ``None`` degrades to
            one ``paragraph`` block per blank-line-separated paragraph, every
            one of them ``fallback`` at confidence 0.0.
        :param max_chars: the input size cap (ADR-0028). This reader is the
            enforcement point: profile patterns run against this text, and a
            pattern cannot be bounded once it starts, so the text is bounded
            instead.
        :return: the document as a `redlines.blocks.BlockTree`, addressed, with
            any control characters removed reported in ``dropped``.
        :raises ValueError: if the source is over ``max_chars``, or is bytes
            that are not UTF-8.
        """
        text = decode_source(source, reader=self.name)
        check_size(text, max_chars=max_chars, reader=self.name)
        normalised, controls = normalise(text)
        dropped = (
            (
                Dropped(
                    kind="control_character",
                    count=controls,
                    reason=(
                        "Control characters were removed during normalisation; "
                        "they carry no text and would corrupt block offsets."
                    ),
                ),
            )
            if controls
            else ()
        )
        if profile is None:
            return BlockTree.build(self._degraded(normalised), dropped=dropped)
        paragraphs = segment(normalised, profile=profile)
        return BlockTree.build(
            self._structured(paragraphs, profile=profile), dropped=dropped
        )

    def _degraded(self, normalised: str) -> Block:
        """Return one ``paragraph`` block per paragraph, the ADR-0006 degrade path."""
        paragraphs = [
            chunk.strip()
            for chunk in _PARAGRAPH_BREAK.split(normalised)
            if chunk.strip()
        ]
        return Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            confidence=1.0,
            attrs={"reader": self.name, "profile": None, "paragraphs": len(paragraphs)},
            children=tuple(
                Block(
                    kind=BlockKind.PARAGRAPH,
                    text=paragraph,
                    matched_by=MATCHED_BY_FALLBACK,
                    confidence=0.0,
                )
                for paragraph in paragraphs
            ),
        )

    def _structured(
        self, paragraphs: tuple[Paragraph, ...], *, profile: Profile
    ) -> Block:
        """Run stages two to five over ``paragraphs`` and return the document block."""
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

        for position, paragraph in enumerate(paragraphs):
            reset = heading_reset_name(paragraph.text, profile=profile)
            candidates = label_candidates(paragraph.text, profile=profile)
            placement: Placement | None = None
            if candidates:
                # A resetting heading is a boundary, not a rung on the ladder:
                # its own label is read without disturbing the stack, which is
                # then cleared.
                placement = (
                    stack.preview(candidates, indent=paragraph.indent)
                    if reset
                    else stack.place(candidates, indent=paragraph.indent)
                )
            body = placement.match.text if placement else paragraph.text
            score = heading_score(
                body,
                rule=profile.heading_rule,
                next_label=self._next_label(
                    paragraphs,
                    position,
                    stack=stack,
                    placement=placement,
                    profile=profile,
                ),
            )

            if placement is not None:
                labelled += 1
            if reset is not None:
                stack.reset()
                headings += 1
                self._open_section(
                    open_nodes,
                    self._heading_node(
                        paragraph, placement, score, reset=reset, level=0, rank=0
                    ),
                )
            elif score.is_heading:
                headings += 1
                level = placement.level if placement else 0
                self._open_section(
                    open_nodes,
                    self._heading_node(
                        paragraph,
                        placement,
                        score,
                        reset=None,
                        level=level,
                        rank=level + 1 if placement else 1,
                    ),
                )
            elif placement is not None:
                self._open_item(
                    open_nodes, self._item_node(paragraph, placement, score)
                )
            else:
                open_nodes[-1].children.append(
                    self._body_node(paragraph, score, parent=open_nodes[-1])
                )

        root.attrs = {
            "reader": self.name,
            "profile": profile.name,
            "paragraphs": len(paragraphs),
            "labelled": labelled,
            "headings": headings,
            "numbering_resets": stack.resets,
        }
        return root.finish()

    def _next_label(
        self,
        paragraphs: tuple[Paragraph, ...],
        position: int,
        *,
        stack: HierarchyStack,
        placement: Placement | None,
        profile: Profile,
    ) -> str:
        """Classify what follows this paragraph, for the heading score (stage 5).

        The lookahead is one paragraph and costs nothing: the next paragraph's
        label is placed against a *copy* of the stack, so asking the question
        does not answer it.
        """
        if position + 1 >= len(paragraphs):
            return NEXT_NONE
        following = paragraphs[position + 1]
        candidates = label_candidates(following.text, profile=profile)
        if not candidates:
            return NEXT_NONE
        preview = stack.preview(candidates, indent=following.indent)
        if placement is None:
            return NEXT_DEEPER
        return NEXT_DEEPER if preview.level > placement.level else NEXT_PEER

    def _heading_node(
        self,
        paragraph: Paragraph,
        placement: Placement | None,
        score: HeadingScore,
        *,
        reset: str | None,
        level: int,
        rank: int,
    ) -> _Node:
        """Build the node for a heading, resetting or scored.

        A resetting heading is given level 0 whatever label it carries: it is
        the boundary the numbering starts again after, so it sits above the
        levels rather than at one of them. Its label is still kept, because
        "Schedule 2" is what a reader of the document would call it.
        """
        attrs: dict[str, Any] = {"indent": paragraph.indent}
        if placement is not None:
            attrs.update(_label_attrs(placement))
        attrs.update(_heading_attrs(score, reset=reset))
        if reset is not None:
            matched_by = matched_by_heading(reset)
            confidence = CONFIDENCE_RESET_HEADING
        elif placement is not None:
            matched_by = matched_by_label(placement.match.name)
            confidence = placement.confidence
        else:
            matched_by = matched_by_heading("score")
            confidence = score.confidence
        return _Node(
            kind=BlockKind.HEADING,
            text=placement.match.text if placement else paragraph.text,
            label=placement.match.label if placement else None,
            level=level,
            matched_by=matched_by,
            confidence=confidence,
            attrs=attrs,
            indent=paragraph.indent,
            rank=rank,
        )

    def _item_node(
        self, paragraph: Paragraph, placement: Placement, score: HeadingScore
    ) -> _Node:
        """Build the node for a labelled block that is not a heading."""
        attrs: dict[str, Any] = {"indent": paragraph.indent}
        attrs.update(_label_attrs(placement))
        attrs.update(_heading_attrs(score, reset=None))
        if paragraph.rejoined:
            attrs["rejoined_lines"] = paragraph.lines
        return _Node(
            kind=BlockKind.LIST_ITEM,
            text=placement.match.text,
            label=placement.match.label,
            level=placement.level,
            matched_by=matched_by_label(placement.match.name),
            confidence=placement.confidence,
            attrs=attrs,
            indent=paragraph.indent,
            rank=placement.level + 1,
        )

    def _body_node(
        self, paragraph: Paragraph, score: HeadingScore, *, parent: _Node
    ) -> _Node:
        """Build the node for an unlabelled paragraph: a continuation or a fallback."""
        open_label = parent.level if parent.kind is BlockKind.LIST_ITEM else None
        decision = continuation_for(
            open_label_level=open_label,
            heading=score,
            indent=paragraph.indent,
            label_indent=parent.indent,
        )
        attrs: dict[str, Any] = {
            "indent": paragraph.indent,
            "continuation": decision.attaches,
            "continuation_reason": decision.reason,
        }
        attrs.update(_heading_attrs(score, reset=None))
        if paragraph.rejoined:
            attrs["rejoined_lines"] = paragraph.lines
        return _Node(
            kind=BlockKind.PARAGRAPH,
            text=paragraph.text,
            level=parent.level if decision.attaches else 0,
            matched_by=(
                MATCHED_BY_CONTINUATION if decision.attaches else MATCHED_BY_FALLBACK
            ),
            confidence=decision.confidence,
            attrs=attrs,
            indent=paragraph.indent,
        )

    def _open_section(self, open_nodes: list[_Node], heading: _Node) -> None:
        """Close what the heading outranks, then open a section around it.

        A heading opens a ``section`` holding the heading itself and everything
        under it, so the tree carries the document's shape and
        `redlines.blocks.heading_breadcrumb` has something to walk.
        """
        self._close_to(open_nodes, heading.rank)
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

    def _open_item(self, open_nodes: list[_Node], item: _Node) -> None:
        """Close every open block at or below this label's level, then open it."""
        self._close_to(open_nodes, item.rank)
        open_nodes[-1].children.append(item)
        open_nodes.append(item)

    def _close_to(self, open_nodes: list[_Node], rank: int) -> None:
        """Pop every open block a new block of this rank ends. The root never pops.

        Rank orders containers on one scale, because headings and labels
        interleave: a numbering-resetting heading is rank 0 and contains
        everything until the next one; an unlabelled heading is rank 1, so it
        sits inside a schedule and still holds the level-1 clauses under it; and
        anything labelled at level *n* -- heading or clause -- is rank *n* + 1,
        so a clause closes its peers and nests under its parent.
        """
        while len(open_nodes) > 1 and open_nodes[-1].rank >= rank:
            open_nodes.pop()


def _label_attrs(placement: Placement) -> dict[str, Any]:
    """Record what stages two and three decided about a label (PRD § 6b)."""
    attrs: dict[str, Any] = {
        "label_pattern": placement.match.name,
        "label_style": placement.match.style,
        "label_depth_mode": placement.match.depth_mode,
        "level_reason": placement.level_reason,
        "style_reason": placement.style_reason,
        "numbering_run": placement.run_reason,
    }
    if placement.ambiguous:
        attrs["label_candidates"] = list(placement.considered)
    return attrs


def _heading_attrs(score: HeadingScore, *, reset: str | None) -> dict[str, Any]:
    """Record what stage five decided, score and all, whatever the verdict."""
    attrs: dict[str, Any] = {
        "heading_score": score.score,
        "heading_signals": list(score.signals),
        "heading_threshold": score.threshold,
    }
    if reset is not None:
        attrs["heading_reset"] = reset
    return attrs


register_reader(PlainTextReader(), replace=True)
