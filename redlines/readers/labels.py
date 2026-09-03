"""Label detection, hierarchy inference, continuations and heading scoring.

These are stages two to five of PRD § 6b, factored out of the plain-text
reader so the markdown reader (#103) can reuse them. Everything here works on
**one line or paragraph of text at a time**, plus a `redlines.profiles.Profile`
and, for hierarchy, a `HierarchyStack` the caller carries across the document.
Nothing here reads a whole document, splits paragraphs, or builds a tree: that
is the reader's job, and it is what differs between plain text and markdown.

The four entry points, in the order a reader uses them::

    from redlines.readers.labels import (
        HierarchyStack, detect_label, heading_score, label_candidates,
    )

    stack = HierarchyStack()
    for line in lines:                                   # the reader's own loop
        candidates = label_candidates(line, profile=profile)
        if candidates:
            placement = stack.place(candidates)           # label, style, level
        heading = heading_score(line, rule=profile.heading_rule)

`detect_label` is the single-line convenience the markdown reader wants for a
list item or a paragraph whose syntax it has already stripped; `label_candidates`
is the same match reported in full, because a label can be genuinely ambiguous
and only the stack can settle it.

**Why a stack.** A decimal label carries its own depth (``7.2`` is depth two,
whatever came before it), but ``(a)`` and ``(i)`` do not: ``(i)`` after ``(h)``
is the ninth letter, and ``(i)`` after ``7.2`` is the first roman numeral one
level deeper (PRD § 6b, ADR-0006). `HierarchyStack` holds the styles currently
open, in order, with the last value seen for each, which is exactly the context
that disambiguates both questions -- and `HierarchyStack.reset` is what a
numbering-resetting heading (Schedule, Annex, Part) calls to make the labels
after the boundary unambiguous again.

**Confidence** follows ADR-0030's bands, and the constants below name every
value this module can produce: an arithmetic depth is a near-certainty unless
its value contradicts the numbering run it sits in (ADR-0028's ``2019 saw…``,
which is the reader's to catch and no profile's), a depth resolved from the
stack is a heuristic and stays under 0.7, and a heading keeps
its *score* -- `heading_confidence` maps it into the heuristic band rather than
thresholding it away, so a reader can put the score in ``attrs`` and let a
reviewer see how close a call it was.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from functools import lru_cache

from ..profiles import HeadingRule, Profile

__all__ = [
    "CONFIDENCE_ARITHMETIC",
    "CONFIDENCE_ARITHMETIC_AMBIGUOUS",
    "CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE",
    "CONFIDENCE_CONTINUATION_INDENT",
    "CONFIDENCE_CONTINUATION_POSITION",
    "CONFIDENCE_RESET_HEADING",
    "CONFIDENCE_STACK",
    "CONFIDENCE_STACK_FIRST_VALUE",
    "CONFIDENCE_STACK_ORDER",
    "CONFIDENCE_STACK_SEQUENCE",
    "HEADING_THRESHOLD",
    "NEXT_DEEPER",
    "NEXT_NONE",
    "NEXT_PEER",
    "RUN_FIRST_VALUE",
    "RUN_OUT_OF_SEQUENCE",
    "RUN_SEQUENCE",
    "RUN_UNVERIFIED",
    "Continuation",
    "HeadingScore",
    "HierarchyStack",
    "LabelMatch",
    "Placement",
    "continuation_for",
    "detect_label",
    "heading_confidence",
    "heading_reset_name",
    "heading_score",
    "label_candidates",
    "sequence_index",
]


HEADING_THRESHOLD = 0.5
"""The heading score at or above which a reader treats a line as a heading.

A default, not a law: the score is kept whatever the reader decides (PRD § 6b),
and a profile's `redlines.profiles.HeadingRule` tightens the gates that feed
it. A reader may pass its own ``threshold`` to `heading_score`.
"""

CONFIDENCE_ARITHMETIC = 0.9
"""A decimal label whose depth it counted from the label itself (ADR-0030, 0.7-0.99)."""

CONFIDENCE_ARITHMETIC_AMBIGUOUS = 0.7
"""A decimal label that another pattern also claimed; the depth is still its own."""

CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE = 0.45
"""A decimal label whose value contradicts the numbering run it sits in.

ADR-0028 hands this case to the reader, because a profile cannot express it:
"a paragraph opening '2019 saw…' will be mis-labelled by a bare-number pattern.
That belongs to the reader (#102), which sees the whole document and can score a
candidate against the numbering run, and it is exactly what ``matched_by`` and
per-block confidence (R1d, R3) exist to report." The label is still recorded --
it is what the document says -- but at a heuristic confidence (0.3-0.69) rather
than the `CONFIDENCE_ARITHMETIC` a value continuing its run earns, and
`Placement.run_reason` says which it was.
"""

CONFIDENCE_STACK = 0.65
"""One pattern matched, but the depth came from the style stack (0.3-0.69)."""

CONFIDENCE_STACK_SEQUENCE = 0.6
"""Several patterns matched; the label continues a style already open."""

CONFIDENCE_STACK_FIRST_VALUE = 0.5
"""Several patterns matched; the label is the first value of a style not yet open."""

CONFIDENCE_STACK_ORDER = 0.4
"""Several patterns matched and only the profile's own order broke the tie."""

CONFIDENCE_RESET_HEADING = 0.75
"""A heading a profile's ``heading_resets`` pattern matched outright (0.7-0.99)."""

CONFIDENCE_CONTINUATION_INDENT = 0.6
"""An unlabelled paragraph indented under the labelled block above it."""

CONFIDENCE_CONTINUATION_POSITION = 0.5
"""An unlabelled paragraph attached to the labelled block above it by position alone."""

NEXT_NONE = "none"
"""`heading_score` ``next_label``: nothing labelled follows this line."""

NEXT_DEEPER = "deeper"
"""`heading_score` ``next_label``: labelled content one or more levels deeper follows."""

NEXT_PEER = "peer"
"""`heading_score` ``next_label``: a label at this line's own level or shallower follows."""

RUN_SEQUENCE = "sequence"
"""`Placement.run_reason`: the value is the next one in the run at this level."""

RUN_FIRST_VALUE = "first_value"
"""`Placement.run_reason`: the value opens a run at this level, at its first value."""

RUN_OUT_OF_SEQUENCE = "out_of_sequence"
"""`Placement.run_reason`: a run is open at this level and the value does not continue it."""

RUN_UNVERIFIED = "unverified"
"""`Placement.run_reason`: there was no run to check the value against.

An empty stack, a level this style has not been seen at, or a value that is not
a readable sequence position at all. Nothing is wrong; nothing was confirmed
either, which is why it is reported rather than silently read as agreement.
"""


_WEIGHT_ALL_CAPS = 0.45
# Title case has to be able to carry a heading on its own, because plenty of
# contracts title their sections "Governing Law" rather than "GOVERNING LAW".
# At 0.28 it could not: with no terminal punctuation (+0.10) and short (+0.10)
# it reached 0.48 against a 0.5 threshold, so a Title Case heading was only
# ever recognised when labelled content happened to follow it, and no profile
# field could make up the difference. See `heading_score`.
_WEIGHT_TITLE_CASE = 0.40
_WEIGHT_NO_TERMINAL_PUNCTUATION = 0.10
_WEIGHT_SHORT = 0.10
_WEIGHT_FOLLOWED_BY_DEEPER = 0.28
_PENALTY_FOLLOWED_BY_PEER = -0.25

_TERMINAL_PUNCTUATION = (".", ";", ":", ",")

_TITLE_CASE_SMALL_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "as",
        "at",
        "but",
        "by",
        "for",
        "from",
        "in",
        "nor",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)

_ROMAN_VALUES = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}


@lru_cache(maxsize=256)
def _compiled(pattern: str) -> re.Pattern[str]:
    """Return ``pattern`` compiled, cached so a read does not recompile per line."""
    return re.compile(pattern)


@dataclass(frozen=True, slots=True)
class LabelMatch:
    """One profile label pattern's claim on the start of a line (PRD § 6b, stage 2).

    A *claim*, not a verdict: several patterns can match the same text -- that
    is what makes ``(i)`` hard -- so a reader collects `label_candidates` and
    lets `HierarchyStack.place` choose between them.

    :param name: the profile pattern's ``name``, which becomes the block's
        ``matched_by`` detail (``label:<name>``, ADR-0030).
    :param style: the pattern's ``style``: ``decimal``, ``alpha``, ``roman`` or
        ``word``.
    :param depth_mode: the pattern's ``depth_mode``: ``arithmetic`` (the label
        counts its own depth) or ``stack`` (the stack resolves it).
    :param label: the label as the document wrote it, stripped of surrounding
        whitespace and of one trailing full stop -- ``"7.2"``, ``"(a)"``,
        ``"Schedule 2"``. This is what goes in `redlines.blocks.Block.label`.
    :param value: the numbering token the pattern captured (group 1 where it has
        one, else the whole label): ``"7.2"``, ``"a"``, ``"i"``, ``"2"``.
    :param text: what is left of the line once the label and the space after it
        are removed. This is the block's text.
    :param end: how many characters of the (left-stripped) line the label
        occupied, for a caller that needs to map offsets back.
    """

    name: str
    style: str
    depth_mode: str
    label: str
    value: str
    text: str
    end: int

    @property
    def index(self) -> int | None:
        """Where ``value`` falls in its style's sequence, counting from 1.

        ``"c"`` is 3 as an alpha label and 100 as a roman one, which is exactly
        the ambiguity `HierarchyStack` resolves. ``None`` when the value is not
        a sequence position this module can read (a multi-letter alpha label, a
        word label with no number in it).
        """
        return sequence_index(self.style, self.value)


def sequence_index(style: str, value: str) -> int | None:
    """Return the 1-based position of ``value`` within ``style``'s sequence.

    :param style: a profile label style -- ``decimal``, ``alpha``, ``roman`` or
        ``word``. A ``word`` value is read as a number, then a roman numeral,
        then a letter, taking its last whitespace-separated token.
    :param value: the numbering token, for example ``"7.2"``, ``"h"`` or ``"iv"``.
    :return: the position (``"h"`` in ``alpha`` is 8, ``"iv"`` in ``roman`` is
        4, ``"7.2"`` in ``decimal`` is 2 -- the last group), or ``None`` when
        the value is not a position in that sequence.
    """
    if style == "decimal":
        return _decimal_index(value)
    if style == "alpha":
        return _alpha_index(value)
    if style == "roman":
        return _roman_index(value)
    token = value.split()[-1] if value.split() else value
    for reader in (_decimal_index, _roman_index, _alpha_index):
        index = reader(token)
        if index is not None:
            return index
    return None


def _decimal_index(value: str) -> int | None:
    """Return the last dot-separated group of ``value`` as an integer."""
    tail = value.rstrip(".").split(".")[-1]
    return int(tail) if tail.isdigit() else None


def _alpha_index(value: str) -> int | None:
    """Return the position of a single ASCII letter in the alphabet."""
    if len(value) == 1 and value.isascii() and value.isalpha():
        return ord(value.lower()) - ord("a") + 1
    return None


def _roman_index(value: str) -> int | None:
    """Return the value of a roman numeral, or ``None`` if it is not one."""
    text = value.lower()
    if not text or any(char not in _ROMAN_VALUES for char in text):
        return None
    total = 0
    highest = 0
    for char in reversed(text):
        current = _ROMAN_VALUES[char]
        if current < highest:
            total -= current
        else:
            total += current
            highest = current
    return total or None


def _decimal_depth(value: str) -> int:
    """Return how many dot-separated groups ``value`` has, at least one."""
    return max(1, len([group for group in value.rstrip(".").split(".") if group]))


def label_candidates(text: str, *, profile: Profile | None) -> tuple[LabelMatch, ...]:
    """Return every profile label pattern that matches the start of ``text``.

    Stage two of PRD § 6b, reported in full rather than resolved: patterns are
    returned **in profile order**, which is the profile's own precedence, and a
    reader that wants one answer either takes the first (`detect_label`) or
    hands the whole tuple to `HierarchyStack.place`, which weighs them against
    the numbering context.

    Leading whitespace is ignored, so a caller can pass an indented line as it
    stands; a pattern that matches without consuming anything is discarded,
    because a zero-width label would strip nothing and mean nothing.

    :param text: one line or paragraph, label and all.
    :param profile: the active profile. ``None`` -- or a profile with no
        ``label_patterns``, such as the built-in ``generic`` -- returns no
        candidates, which is how the degrade path (ADR-0006) starts.
    :return: the matching patterns as `LabelMatch` objects, in profile order.
    """
    if profile is None or not profile.label_patterns:
        return ()
    stripped = text.lstrip()
    matches: list[LabelMatch] = []
    for pattern in profile.label_patterns:
        match = _compiled(pattern.pattern).match(stripped)
        if match is None or match.end() == 0:
            continue
        value = (
            match.group(1)
            if match.re.groups >= 1 and match.group(1) is not None
            else match.group(0).strip()
        )
        label = match.group(0).strip()
        if label.endswith(".") and not value.endswith("."):
            label = label[:-1]
        matches.append(
            LabelMatch(
                name=pattern.name,
                style=pattern.style,
                depth_mode=pattern.depth_mode,
                label=label,
                value=value,
                text=stripped[match.end() :].strip(),
                end=match.end(),
            )
        )
    return tuple(matches)


def detect_label(text: str, *, profile: Profile | None) -> LabelMatch | None:
    """Return the label at the start of ``text``, by profile precedence alone.

    The one-line convenience the markdown reader wants when it has stripped
    ``- `` or ``## `` and needs to know whether what is left starts with a
    label. It answers "is there a label, and what style is it" without any
    document context, so where two patterns both match it reports the first the
    profile lists -- use `label_candidates` and `HierarchyStack.place` when the
    answer has to be right about ``(i)``.

    :param text: one line or paragraph, label and all.
    :param profile: the active profile; ``None`` means no labels exist.
    :return: the first matching `LabelMatch`, or ``None`` if none matched.
    """
    candidates = label_candidates(text, profile=profile)
    return candidates[0] if candidates else None


def heading_reset_name(text: str, *, profile: Profile | None) -> str | None:
    """Return the name of the ``heading_resets`` rule ``text`` matches, if any.

    A reset is the boundary that makes numbering unambiguous again (PRD § 6b):
    the reader turns the line into a heading, opens a new section and calls
    `HierarchyStack.reset`. Patterns carry their own anchoring, so they are
    searched rather than matched.

    :param text: the candidate heading line, as written.
    :param profile: the active profile; ``None`` means nothing resets.
    :return: the matching reset's ``name`` -- the ``heading:<signal>`` detail a
        reader records -- or ``None``.
    """
    if profile is None:
        return None
    stripped = text.strip()
    for reset in profile.heading_resets:
        if _compiled(reset.pattern).search(stripped) is not None:
            return reset.name
    return None


@dataclass(frozen=True, slots=True)
class Placement:
    """What `HierarchyStack.place` decided about one labelled line (stage 3).

    :param match: the candidate the stack chose, which may not be the first the
        profile lists -- that is the point of the exercise at ``(i)``.
    :param level: the label's depth in the document's own numbering, counting
        from 1. Goes straight into `redlines.blocks.Block.level`.
    :param confidence: ADR-0030 confidence for that depth: `CONFIDENCE_ARITHMETIC`
        when the label counted its own, one of the `CONFIDENCE_STACK` family
        when the stack resolved it.
    :param level_reason: how the depth was reached -- ``arithmetic`` (counted
        from the label), ``reopen`` (the style was already open at that level),
        ``push`` (a style new to the stack, one deeper), ``dedent_push`` (the
        same, after indentation popped the stack back first).
    :param style_reason: why this candidate rather than another -- ``only``
        (nothing competed), ``sequence`` (it continues an open style),
        ``first_value`` (it opens a style at its first value), ``open_style``,
        ``known_index`` or ``profile_order``.
    :param run_reason: how the value sits in the numbering run already open at
        its level -- `RUN_SEQUENCE`, `RUN_FIRST_VALUE`, `RUN_OUT_OF_SEQUENCE` or
        `RUN_UNVERIFIED`. This is the check a profile cannot make (ADR-0028) and
        the reason a stray ``2019`` does not read as a clause number: it is what
        separates a plausible label from an implausible one where
        ``style_reason`` cannot, because only one pattern matched either way.
    :param ambiguous: whether more than one pattern matched.
    :param considered: the names of every pattern that matched, in profile
        order, so a reader can record the road not taken in ``attrs``.
    """

    match: LabelMatch
    level: int
    confidence: float
    level_reason: str
    style_reason: str
    run_reason: str
    ambiguous: bool
    considered: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    """One open numbering style: its depth, its last value, its indentation.

    ``index`` is the last value that *continued* the run and ``seen`` the last
    value written at this level, whether or not it did. They differ only after
    an out-of-sequence value, which is exactly when the difference matters: a
    run of ``1.``, ``2019``, ``2.`` keeps ``index`` at 1 so ``2.`` reads as the
    sequel to ``1.``, while a run of ``1.``, ``2.``, ``5.``, ``6.`` keeps
    ``seen`` at 5 so ``6.`` reads as the sequel to ``5.``. A value that
    continues either one is in sequence; the reader loses the run only when a
    value continues neither.
    """

    style: str
    level: int
    index: int | None
    indent: int
    seen: int | None = None


class HierarchyStack:
    """The label-style stack that turns labels into levels (PRD § 6b, stage 3).

    A reader creates one per document and feeds it every label it detects, in
    document order; the stack answers with a `Placement`. It holds the styles
    currently open, outermost first, each with the level it sits at and the last
    value seen for it, which is what makes ``(i)`` after ``(h)`` alphabetic and
    ``(i)`` after ``7.2`` roman.

    Three rules, and nothing else:

    - **arithmetic** (``decimal``): the level *is* the number of dot-separated
      groups, and the stack is truncated to sit below it, so ``(a)`` after
      ``7.2`` lands at level 3 and ``(a)`` after ``7`` at level 2.
    - **stack** (``alpha``, ``roman``, ``word``): a style already open pops the
      stack back to its level and reuses it; a style new to the stack pushes one
      level deeper than whatever is open.
    - **reset**: a numbering-resetting heading clears the stack entirely, so the
      next label starts again at level 1.

    Indentation is a secondary signal, used only where the stack has nothing to
    say: a label in a style new to the stack, written *less* indented than the
    open styles, pops back past them before pushing. Where indentation has not
    survived (it usually has not) every indent is 0 and the rule never fires.

    Separately from the level, the stack scores every value against the run
    already open at that level and reports the answer as `Placement.run_reason`.
    This is the check ADR-0028 says a profile cannot make and the reader must:
    a bare-number pattern matches ``2019 saw a change.`` exactly as well as it
    matches a clause number, and only the numbering run knows the difference.
    It never changes the level -- the label is placed where it says it belongs
    either way -- but an arithmetic label that contradicts its run is reported
    at `CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE` rather than as a near-certainty.
    """

    __slots__ = ("_entries", "_resets")

    def __init__(self) -> None:
        """Start empty: no style is open and the next label is level 1."""
        self._entries: list[_Entry] = []
        self._resets = 0

    @property
    def depth(self) -> int:
        """How many styles are open."""
        return len(self._entries)

    @property
    def styles(self) -> tuple[str, ...]:
        """The open styles, outermost first."""
        return tuple(entry.style for entry in self._entries)

    @property
    def resets(self) -> int:
        """How many times `reset` has been called, for a reader's own report."""
        return self._resets

    def snapshot(self) -> tuple[tuple[str, int], ...]:
        """Return the open styles with their levels, for recording in ``attrs``.

        :return: ``(style, level)`` pairs, outermost first -- ``(("decimal", 1),
            ("decimal", 2), ("alpha", 3))`` part-way through a sub-clause list.
        """
        return tuple((entry.style, entry.level) for entry in self._entries)

    def reset(self) -> None:
        """Clear every open style, as a numbering-resetting heading does.

        This is what makes labels unambiguous again after a Schedule or Annex
        boundary (PRD § 6b): the ``1.`` that follows is level 1 again rather
        than a continuation of the body's numbering.
        """
        self._entries.clear()
        self._resets += 1

    def place(self, candidates: Sequence[LabelMatch], *, indent: int = 0) -> Placement:
        """Choose between ``candidates`` and give the winner a level.

        Mutates the stack: this is the call that says the label *happened*.

        :param candidates: what `label_candidates` returned, in profile order.
            Must not be empty.
        :param indent: the line's leading whitespace, in characters, or 0 where
            the format has none to offer.
        :return: the `Placement` for the chosen candidate.
        :raises ValueError: if ``candidates`` is empty.
        """
        return self._place(candidates, indent=indent, commit=True)

    def preview(
        self, candidates: Sequence[LabelMatch], *, indent: int = 0
    ) -> Placement:
        """Answer what `place` would answer, without changing the stack.

        The lookahead a heading score needs: "if the next line's label were
        placed now, would it be deeper than this line?" is what separates a
        heading from a one-line clause (PRD § 6b, stage 5).

        :param candidates: what `label_candidates` returned, in profile order.
        :param indent: the line's leading whitespace, in characters.
        :return: the `Placement` the same call to `place` would return.
        :raises ValueError: if ``candidates`` is empty.
        """
        return self._place(candidates, indent=indent, commit=False)

    def _place(
        self, candidates: Sequence[LabelMatch], *, indent: int, commit: bool
    ) -> Placement:
        """Do the work of `place`, against a copy of the stack when previewing."""
        if not candidates:
            raise ValueError("place() needs at least one label candidate")
        entries = self._entries if commit else [replace(e) for e in self._entries]
        match, style_reason = self._choose(candidates)
        ambiguous = len(candidates) > 1
        considered = tuple(candidate.name for candidate in candidates)

        if match.depth_mode == "arithmetic":
            level = _decimal_depth(match.value)
            # The run this value has to answer to is the one already open at
            # its own level and style, read before the stack is truncated.
            prior = next(
                (
                    entry
                    for entry in reversed(entries)
                    if entry.level == level and entry.style == match.style
                ),
                None,
            )
            run_reason = _run_reason(match.index, prior)
            while entries and entries[-1].level >= level:
                entries.pop()
            # An out-of-sequence value does not become the run: keeping the last
            # confirmed value is what lets the label after a stray "2019" read
            # as the sequel to the label before it.
            confirmed = (
                prior.index
                if run_reason == RUN_OUT_OF_SEQUENCE and prior is not None
                else match.index
            )
            entries.append(
                _Entry(match.style, level, confirmed, indent, seen=match.index)
            )
            confidence = _arithmetic_confidence(ambiguous, run_reason)
            level_reason = "arithmetic"
        else:
            open_entry = next(
                (entry for entry in entries if entry.style == match.style), None
            )
            run_reason = _run_reason(match.index, open_entry)
            if open_entry is not None:
                level = open_entry.level
                while entries and entries[-1].level > level:
                    entries.pop()
                entries[-1] = _Entry(
                    match.style, level, match.index, indent, seen=match.index
                )
                level_reason = "reopen"
            else:
                level_reason = "push"
                while entries and indent < entries[-1].indent:
                    entries.pop()
                    level_reason = "dedent_push"
                level = (entries[-1].level if entries else 0) + 1
                entries.append(
                    _Entry(match.style, level, match.index, indent, seen=match.index)
                )
            confidence = _stack_confidence(ambiguous, style_reason)
        return Placement(
            match=match,
            level=level,
            confidence=confidence,
            level_reason=level_reason,
            style_reason=style_reason,
            run_reason=run_reason,
            ambiguous=ambiguous,
            considered=considered,
        )

    def _choose(self, candidates: Sequence[LabelMatch]) -> tuple[LabelMatch, str]:
        """Pick the candidate the numbering context supports best.

        Ranked, highest first: a label that continues a style already open at
        its next value; a label that is the first value of a style not yet open;
        a label whose style is open at some other value; a label whose value is
        a readable position at all; anything else. Profile order breaks a tie,
        which is what makes it precedence.

        Two candidates whose styles are *both* open tie on rank alone, and
        profile order is the wrong answer there: after ``(a) (b) (i) … (v)``
        the label ``(x)`` continues neither run exactly, yet it is a jump of
        five in the open roman run against a jump of twenty-two in the open
        alpha one, and reading it as ``(x)`` the twenty-fourth letter would pop
        the roman sub-clauses shut. So within that rank the smaller forward
        jump wins, and a value that runs *backwards* in its style loses to one
        that runs forwards. The result is still a heuristic --
        `CONFIDENCE_STACK_ORDER`, with every candidate recorded in
        `Placement.considered` (ADR-0030) -- it is simply the better guess.
        """
        best_key = (-1, _NO_TIE_BREAK)
        best = candidates[0]
        best_reason = "only" if len(candidates) == 1 else "profile_order"
        for candidate in candidates:
            rank, closeness, reason = self._rank(candidate)
            if (rank, closeness) > best_key:
                best_key, best, best_reason = (rank, closeness), candidate, reason
        if len(candidates) == 1:
            return best, "only"
        return best, best_reason

    def _rank(self, candidate: LabelMatch) -> tuple[int, tuple[int, int], str]:
        """Score one candidate against the open styles; see `_choose`.

        :return: the rank, a within-rank tie-break (higher is better,
            `_NO_TIE_BREAK` where the rank has nothing more to say) and the
            `Placement.style_reason`.
        """
        entry = next(
            (entry for entry in self._entries if entry.style == candidate.style), None
        )
        index = candidate.index
        if (
            entry is not None
            and index is not None
            and entry.index is not None
            and index == entry.index + 1
        ):
            return 4, _NO_TIE_BREAK, "sequence"
        if entry is None and index == 1:
            return 3, _NO_TIE_BREAK, "first_value"
        if entry is not None:
            return 2, _jump_closeness(index, entry.index), "open_style"
        if index is not None:
            return 1, _NO_TIE_BREAK, "known_index"
        return 0, _NO_TIE_BREAK, "profile_order"


_JUMP_FORWARD = 2
_JUMP_UNKNOWN = 1
_JUMP_BACKWARDS = 0
_NO_TIE_BREAK = (0, 0)
"""`HierarchyStack._rank`'s tie-break where the rank itself settles the order."""


def _jump_closeness(index: int | None, last: int | None) -> tuple[int, int]:
    """Rate how well ``index`` follows ``last`` in the same open run; higher is better.

    The tie-break between two candidates whose styles are both open and neither
    of which continues its run exactly (`HierarchyStack._choose`). A value that
    runs forwards beats one that runs backwards or stands still, and the shorter
    forward jump beats the longer one -- ``(x)`` after a roman run at ``(v)`` is
    a jump of five, against twenty-two for the alpha run it would otherwise be
    read into.

    :param index: the candidate's `LabelMatch.index`.
    :param last: the last value of the open run in that style.
    :return: a sort key, comparable only against another `_jump_closeness`.
    """
    if index is None or last is None:
        return (_JUMP_UNKNOWN, 0)
    jump = index - last
    if jump > 0:
        return (_JUMP_FORWARD, -jump)
    return (_JUMP_BACKWARDS, jump)


def _run_reason(index: int | None, prior: _Entry | None) -> str:
    """Say how ``index`` sits in the run ``prior`` holds; see `Placement.run_reason`.

    :param index: the candidate's `LabelMatch.index`, or ``None`` where the
        value is not a readable sequence position.
    :param prior: the open entry the value has to answer to, or ``None`` where
        no run is open for it.
    :return: one of `RUN_SEQUENCE`, `RUN_FIRST_VALUE`, `RUN_OUT_OF_SEQUENCE`,
        `RUN_UNVERIFIED`.
    """
    if index is None:
        return RUN_UNVERIFIED
    if prior is None:
        return RUN_FIRST_VALUE if index == 1 else RUN_UNVERIFIED
    last = [value for value in (prior.index, prior.seen) if value is not None]
    if not last:
        return RUN_UNVERIFIED
    if any(index == value + 1 for value in last):
        return RUN_SEQUENCE
    return RUN_OUT_OF_SEQUENCE


def _arithmetic_confidence(ambiguous: bool, run_reason: str) -> float:
    """Map an arithmetic depth onto ADR-0030's bands, run plausibility included."""
    if run_reason == RUN_OUT_OF_SEQUENCE:
        return CONFIDENCE_ARITHMETIC_OUT_OF_SEQUENCE
    return CONFIDENCE_ARITHMETIC_AMBIGUOUS if ambiguous else CONFIDENCE_ARITHMETIC


def _stack_confidence(ambiguous: bool, style_reason: str) -> float:
    """Map a stack-resolved depth onto ADR-0030's heuristic band."""
    if not ambiguous:
        return CONFIDENCE_STACK
    if style_reason == "sequence":
        return CONFIDENCE_STACK_SEQUENCE
    if style_reason == "first_value":
        return CONFIDENCE_STACK_FIRST_VALUE
    return CONFIDENCE_STACK_ORDER


@dataclass(frozen=True, slots=True)
class HeadingScore:
    """How much one line looks like a heading, and which signals said so (stage 5).

    The score is kept, not thresholded away (PRD § 6b): a reader puts it in the
    block's ``attrs`` so a reviewer can see that a heading scored 0.53 and a
    paragraph scored 0.48, which is the difference between a mis-parse you can
    find and one you cannot.

    :param score: 0.0 to 1.0. Zero means a gate closed -- the line is too long,
        it ends in terminal punctuation the profile forbids, or it is not one
        line at all.
    :param signals: the signals that fired, in a fixed order, including the gate
        that closed (``too_many_words``, ``terminal_punctuation``, ``multiline``,
        ``empty``) and any negative one (``followed_by_peer_label``).
    :param threshold: the threshold this score was judged against.
    """

    score: float
    signals: tuple[str, ...]
    threshold: float = HEADING_THRESHOLD

    @property
    def is_heading(self) -> bool:
        """Whether the score reaches the threshold."""
        return self.score >= self.threshold

    @property
    def confidence(self) -> float:
        """The score as an ADR-0030 confidence; see `heading_confidence`."""
        return heading_confidence(self.score)


def heading_confidence(score: float) -> float:
    """Map a heading score onto ADR-0030's heuristic confidence band.

    A heading is inferred, never stated, in plain text, so even a perfect score
    stays under 0.7: the band is 0.3 to 0.69 and the score orders blocks within
    it.

    :param score: a `HeadingScore` score, 0.0 to 1.0.
    :return: ``0.3 + 0.39 * score``, rounded to three decimals.
    """
    bounded = min(1.0, max(0.0, score))
    return round(0.3 + 0.39 * bounded, 3)


def heading_score(
    text: str,
    *,
    rule: HeadingRule | None = None,
    next_label: str = NEXT_NONE,
    threshold: float = HEADING_THRESHOLD,
) -> HeadingScore:
    """Score one line as a heading (PRD § 6b, stage 5).

    "Short lines in all caps or title case without terminal punctuation,
    followed by labelled content, score as headings." The gates come from the
    profile's `redlines.profiles.HeadingRule` -- that is how a profile tightens
    or loosens the rule -- and the weights are fixed and documented:

    ============================  ======  =========================================
    signal                        weight  when it fires
    ============================  ======  =========================================
    ``all_caps``                   +0.45  every cased letter is upper case
    ``title_case``                 +0.40  every significant word is capitalised
    ``no_terminal_punctuation``    +0.10  the line does not end in ``. ; : ,``
    ``short``                      +0.10  at most half the rule's ``max_words``
    ``followed_by_deeper_label``   +0.28  ``next_label`` is `NEXT_DEEPER`
    ``followed_by_peer_label``     -0.25  ``next_label`` is `NEXT_PEER`
    ============================  ======  =========================================

    Both case signals are weighted to clear `HEADING_THRESHOLD` once the
    unpunctuated line is also short, and neither clears it alone: "Governing
    Law" standing over prose is a heading (0.60), and so is "GOVERNING LAW"
    (0.65), which is the point -- Title Case section titles are as ordinary a
    contract convention as capitals, and a profile has no weight or threshold
    field to make up a shortfall with (`redlines.profiles.HeadingRule` narrows
    the candidates, it does not score them).

    The negative signal is what separates the two halves of PRD § 6b's
    "one-line clauses that look like headings": a short title-case line with
    sub-clauses under it heads them (0.88), and the same line followed by its
    own numbered neighbour heads nothing and is a clause (0.35).

    :param text: the line, with any label already stripped -- a label does not
        count against ``max_words`` and does not decide the case.
    :param rule: the profile's heading rule; the defaults when ``None``.
    :param next_label: what follows, as `NEXT_NONE`, `NEXT_DEEPER` or
        `NEXT_PEER`. A reader gets this from `HierarchyStack.preview`.
    :param threshold: the score at or above which this is a heading.
    :return: the `HeadingScore`.
    """
    rule = rule or HeadingRule()
    body = text.strip()
    if not body:
        return HeadingScore(0.0, ("empty",), threshold)
    if "\n" in body:
        return HeadingScore(0.0, ("multiline",), threshold)
    words = body.split()
    if len(words) > rule.max_words:
        return HeadingScore(0.0, ("too_many_words",), threshold)
    terminal = body.endswith(_TERMINAL_PUNCTUATION)
    if terminal and rule.forbid_terminal_punctuation:
        return HeadingScore(0.0, ("terminal_punctuation",), threshold)

    signals: list[str] = []
    score = 0.0
    if _is_all_caps(body):
        # An all-caps line is trivially title case too, so a profile that
        # refuses all-caps headings must not have them let back in that way.
        if rule.allow_all_caps:
            score += _WEIGHT_ALL_CAPS
            signals.append("all_caps")
    elif _is_title_case(words) and rule.allow_title_case:
        score += _WEIGHT_TITLE_CASE
        signals.append("title_case")
    if not terminal:
        score += _WEIGHT_NO_TERMINAL_PUNCTUATION
        signals.append("no_terminal_punctuation")
    if len(words) <= max(2, rule.max_words // 2):
        score += _WEIGHT_SHORT
        signals.append("short")
    if next_label == NEXT_DEEPER:
        score += _WEIGHT_FOLLOWED_BY_DEEPER
        signals.append("followed_by_deeper_label")
    elif next_label == NEXT_PEER:
        score += _PENALTY_FOLLOWED_BY_PEER
        signals.append("followed_by_peer_label")
    return HeadingScore(round(min(1.0, max(0.0, score)), 3), tuple(signals), threshold)


def _is_all_caps(text: str) -> bool:
    """Whether ``text`` has letters and none of them are lower case."""
    return any(char.isalpha() for char in text) and text == text.upper()


def _is_title_case(words: Sequence[str]) -> bool:
    """Whether every significant word starts with a capital.

    Short function words (``of``, ``the``, ``and``) are allowed to stay lower
    case anywhere but the first word, which is how title case is actually
    written in a contract heading ("Limitation of Liability").
    """
    significant = False
    for position, word in enumerate(words):
        letters = word.lstrip("\"'“‘([")
        if not letters or not letters[0].isalpha():
            continue
        significant = True
        if letters[0].isupper():
            continue
        if (
            position > 0
            and letters.strip(".,;:)\"'”’").lower() in _TITLE_CASE_SMALL_WORDS
        ):
            continue
        return False
    return significant


@dataclass(frozen=True, slots=True)
class Continuation:
    """Whether an unlabelled paragraph belongs to the labelled block above it.

    :param attaches: whether it does.
    :param reason: why -- ``indented_under_label``, ``follows_label``,
        ``heading_claims_it`` or ``no_open_label``.
    :param confidence: ADR-0030 confidence for the attachment, 0.0 when it does
        not attach.
    """

    attaches: bool
    reason: str
    confidence: float


def continuation_for(
    *,
    open_label_level: int | None,
    heading: HeadingScore | None = None,
    indent: int = 0,
    label_indent: int = 0,
) -> Continuation:
    """Decide whether an unlabelled paragraph continues the block above (stage 4).

    "Unlabelled paragraphs following a labelled block become its body children
    unless a heading rule claims them" (PRD § 6b). Both halves are here: the
    heading claim wins, and an unlabelled paragraph with no labelled block open
    above it attaches to nothing and is a plain paragraph -- ``fallback`` in
    ADR-0030's terms, because nothing recognised it.

    :param open_label_level: the level of the innermost labelled block still
        open, or ``None`` when there is none.
    :param heading: this paragraph's own `HeadingScore`, if the reader scored
        it. A heading is not a continuation.
    :param indent: this paragraph's leading whitespace, in characters.
    :param label_indent: the leading whitespace of the labelled block above.
    :return: the `Continuation` decision.
    """
    if heading is not None and heading.is_heading:
        return Continuation(False, "heading_claims_it", 0.0)
    if open_label_level is None:
        return Continuation(False, "no_open_label", 0.0)
    if indent > label_indent:
        return Continuation(
            True, "indented_under_label", CONFIDENCE_CONTINUATION_INDENT
        )
    return Continuation(True, "follows_label", CONFIDENCE_CONTINUATION_POSITION)
