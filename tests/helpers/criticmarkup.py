r"""The reference reader for ADR-0037's CriticMarkup: accept-all, reject-all, and the residue rule.

CriticMarkup defines no escape, so a third-party stripper ignores redlines'
backslashes: it opens a mark at ``\{++`` and mis-pairs ``use \{++ here
{++new++}``. This module is the reader ADR-0037 names. It is written from the
ADR's text, independently of ``redlines.renderers``, so that the renderer
tests have an oracle that is not the code under test. `accept_all` and
`reject_all` are exactly the ADR's seven steps:

1. **Parse** (`parse`): a strict tokenising scan, not a regular expression.
   A live opener (``{++``, ``{--``, ``{~~``, ``{>>``) has an even run of
   backslashes before it; an odd run makes the whole opener literal, its
   ``{`` included. A mark ends at the first live closer (``++}``, ``--}``,
   ``~~}``, ``<<}``), one with an even run between the operator and the
   ``}``, and a substitution's old side at the first live ``~>``. The run that
   ends the text before a delimiter, and a mark body before its closer, is
   halved; then `critic_unescape` is applied to every text piece and body.
2. **Resolve** (`resolve`): accept keeps insert bodies and the new side of
   substitutions and drops deletions; reject does the reverse.
3. **Strip notes**, inside `resolve`: every note goes, with one adjacent space
   -- the space after it if the next text starts with one, otherwise the space
   before it.
4. **Lines**: split on ``\n``.
5. **Strip roles** (`split_role`): after the syntax head, remove one
   ``[ENCODED-ROLE] `` whose ``[`` no backslash precedes.
6. **Line-start unescape** (`unescape_line_start`): at the content start, an
   odd run of backslashes before a role-shaped ``[`` is halved.
7. **Residue** (`residue`), applied to both sides of every comparison: strip
   each line; drop a line that is empty or holds only a syntax head, a table
   row whose cells are all empty, an alignment row with no table row next to
   it, and a fence whose body is empty.

The comparisons are `exact` (list equality), `multiset` (`collections.Counter`
equality) and `loose_multiset` (a multiset after `loose` also removes all
whitespace and a leading syntax head or list marker from each line).

`tag_lines` reads the legacy ``none`` style's ``<ins>`` and ``<del>`` the same
way, for ADR-0037's invariant of that style. Never imported by ``redlines``.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final, Literal
from urllib.parse import unquote

Side = Literal["accept", "reject"]
"""Which document a reader recovers: ``accept`` the test, ``reject`` the source."""

TokenKind = Literal["text", "insert", "delete", "substitution", "note"]


class CriticMarkupError(ValueError):
    """The text is not well-formed under ADR-0037's grammar: a mark never closes."""


@dataclass(frozen=True, slots=True)
class Token:
    """One piece of a parsed annotated text, already unescaped.

    :param kind: ``text``, ``insert``, ``delete``, ``substitution`` or ``note``.
    :param text: the text, the mark's body, or a substitution's old side.
    :param new: a substitution's new side; empty for every other kind.
    """

    kind: TokenKind
    text: str
    new: str = ""


_OPENERS: Final[dict[str, TokenKind]] = {
    "{++": "insert",
    "{--": "delete",
    "{~~": "substitution",
    "{>>": "note",
}
_CLOSERS: Final[dict[TokenKind, str]] = {
    "insert": "++}",
    "delete": "--}",
    "substitution": "~~}",
    "note": "<<}",
}

# The three sites of ADR-0037's escape, written out again here rather than
# imported, so that the oracle and the renderer are two readings of the ADR.
_SITE: Final[re.Pattern[str]] = re.compile(
    r"(?P<o>\\*)\{(?=\+\+|--|~~|==|>>)|(?<=\+\+|--|~~|==|<<)(?P<c>\\*)\}|(?<=~)(?P<s>\\*)>"
)
_ROLE: Final[str] = r"[A-Za-z0-9_.%-]+"
_ROLE_PREFIX: Final[re.Pattern[str]] = re.compile(r"\[(" + _ROLE + r")\] ")
_LINE_START: Final[re.Pattern[str]] = re.compile(r"(\\*)\[(?=" + _ROLE + r"\] )")
_HEAD: Final[re.Pattern[str]] = re.compile(
    r"(?:> )?(?:#{1,6} |(?: {4})*(?:[-*+]|\d+[.)]) )?"
)
_HEAD_ONLY: Final[re.Pattern[str]] = re.compile(r"(?:>\s*)?(?:#{1,6}|[-*+]|\d+[.)])?")
_EMPTY_ROW: Final[re.Pattern[str]] = re.compile(r"\|(?:\s*\|)+")
_ALIGNMENT_ROW: Final[re.Pattern[str]] = re.compile(r"\|(?:\s*:?-{3,}:?\s*\|)+")
_TABLE_ROW: Final[re.Pattern[str]] = re.compile(r"\|.*\|")
_FENCE_OPEN: Final[re.Pattern[str]] = re.compile(r"((?:>\s*)?`{3,})(?!`)")
_LOOSE_HEAD: Final[re.Pattern[str]] = re.compile(
    r"^(?:> )?(?:#{1,6} |(?: {4})*(?:[-*+]|\d+[.)]) )?(?:\d+[.)]\s+)?"
)
_WHITESPACE: Final[re.Pattern[str]] = re.compile(r"\s+")


def critic_unescape(text: str) -> str:
    r"""Turn each delimiter site's odd backslash run 2\ *n*\ +1 into *n*.

    An even run is a live delimiter rather than escaped text and stays as it is.

    :param text: a text piece or a mark body, as written.
    :return: the document text it stands for.
    """

    def unescape(match: re.Match[str]) -> str:
        run = next(group for group in match.groups() if group is not None)
        if len(run) % 2 == 0:
            return match.group(0)
        return "\\" * (len(run) // 2) + match.group(0)[-1]

    return _SITE.sub(unescape, text)


def _halve_trailing_run(text: str) -> str:
    """Halve the run of backslashes that ends ``text`` (the emitter doubled it)."""
    run = len(text) - len(text.rstrip("\\"))
    return text[: len(text) - run] + "\\" * (run // 2)


def _scan_body(annotated: str, start: int, closer: str) -> tuple[str, int]:
    """Read a mark body from ``start`` up to its first live ``closer``.

    :return: the unescaped body and the index just past the closer.
    :raises CriticMarkupError: if no live closer follows.
    """
    operator, final = closer[:-1], closer[-1]
    index = start
    while index < len(annotated):
        if annotated.startswith(operator, index):
            after = index + len(operator)
            cursor = after
            while cursor < len(annotated) and annotated[cursor] == "\\":
                cursor += 1
            if (
                cursor < len(annotated)
                and annotated[cursor] == final
                and (cursor - after) % 2 == 0
            ):
                body = _halve_trailing_run(annotated[start:index])
                return critic_unescape(body), cursor + 1
        index += 1
    raise CriticMarkupError(
        f"a mark opened before index {start} never closes: wanted {closer!r}"
    )


def parse(annotated: str) -> tuple[Token, ...]:
    """Tokenise annotated text: step 1 of `accept_all` and `reject_all`.

    :param annotated: text a CriticMarkup renderer produced.
    :return: the tokens in order, each already unescaped. Text tokens are never
        empty.
    :raises CriticMarkupError: if a mark never closes.
    """
    tokens: list[Token] = []
    text: list[str] = []
    index = 0
    length = len(annotated)

    def flush(before_delimiter: bool) -> None:
        piece = "".join(text)
        text.clear()
        if before_delimiter:
            piece = _halve_trailing_run(piece)
        if piece:
            tokens.append(Token("text", critic_unescape(piece)))

    while index < length:
        cursor = index
        while cursor < length and annotated[cursor] == "\\":
            cursor += 1
        run = cursor - index
        opener = annotated[cursor : cursor + 3]
        if opener in _OPENERS and run % 2 == 0:
            text.append(annotated[index:cursor])
            flush(before_delimiter=True)
            kind = _OPENERS[opener]
            body_start = cursor + 3
            if kind == "substitution":
                old, after_old = _scan_body(annotated, body_start, "~>")
                new, index = _scan_body(annotated, after_old, _CLOSERS[kind])
                tokens.append(Token(kind, old, new))
            else:
                body, index = _scan_body(annotated, body_start, _CLOSERS[kind])
                tokens.append(Token(kind, body))
            continue
        if run:
            if opener in _OPENERS:
                # An odd run: the whole opener is literal, its "{" included.
                text.append(annotated[index : cursor + 1])
                index = cursor + 1
            else:
                text.append(annotated[index:cursor])
                index = cursor
            continue
        text.append(annotated[index])
        index += 1
    flush(before_delimiter=False)
    return tuple(tokens)


def resolve(tokens: Sequence[Token], side: Side) -> str:
    """Resolve every mark for one side and strip every note: steps 2 and 3.

    :param tokens: what `parse` returned.
    :param side: ``accept`` keeps insertions and new sides; ``reject`` keeps
        deletions and old sides.
    :return: the resolved text, notes removed with one adjacent space each.
    """
    out = ""
    skip_space = False
    for position, token in enumerate(tokens):
        if token.kind == "note":
            following = tokens[position + 1] if position + 1 < len(tokens) else None
            if (
                following is not None
                and following.kind == "text"
                and following.text.startswith(" ")
            ):
                skip_space = True
            elif out.endswith(" "):
                out = out[:-1]
            continue
        if token.kind == "text":
            piece = token.text[1:] if skip_space else token.text
            skip_space = False
            out += piece
        elif token.kind == "insert":
            out += token.text if side == "accept" else ""
        elif token.kind == "delete":
            out += token.text if side == "reject" else ""
        else:
            out += token.new if side == "accept" else token.text
    return out


def split_role(line: str) -> tuple[str, str | None, int]:
    """Remove a line's role prefix: step 5.

    :param line: one resolved line.
    :return: the line with one ``[ENCODED-ROLE] `` removed from after its
        syntax head, the role decoded with ``urllib.parse.unquote`` (``None``
        when the line carries no role prefix), and the index in the returned
        line where its content starts: after the syntax head, and after the
        role prefix when there was one.
    """
    head = _HEAD.match(line)
    start = head.end() if head is not None else 0
    prefix = _ROLE_PREFIX.match(line, start)
    if prefix is None:
        return line, None, start
    return line[:start] + line[prefix.end() :], unquote(prefix.group(1)), start


def strip_roles(line: str) -> str:
    """Return the line without its role prefix, if it has one (step 5)."""
    return split_role(line)[0]


def unescape_line_start(line: str, start: int) -> str:
    """Halve an odd backslash run before a role-shaped ``[`` at ``start``: step 6.

    :param line: a line that `split_role` has already been applied to.
    :param start: where its content starts, as `split_role` reported it.
    :return: the line with its line-start site unescaped.
    """
    site = _LINE_START.match(line, start)
    if site is None or len(site.group(1)) % 2 == 0:
        return line
    run = len(site.group(1))
    return line[:start] + "\\" * (run // 2) + line[start + run :]


def read_line(line: str) -> str:
    """Steps 5 and 6 on one resolved line: strip its role, unescape its start."""
    stripped, _, start = split_role(line)
    return unescape_line_start(stripped, start)


def lines(annotated: str, side: Side, *, roles: bool = True) -> list[str]:
    """Steps 1 to 6: the resolved lines of one side, before the residue rule.

    :param annotated: the renderer's output.
    :param side: ``accept`` or ``reject``.
    :param roles: whether the text was rendered with role prefixes on; without
        them a reader neither strips roles nor unescapes line starts.
    :return: one string per ``\\n``-separated line.
    """
    resolved = resolve(parse(annotated), side).split("\n")
    if not roles:
        return resolved
    return [read_line(line) for line in resolved]


def _drop_empty_fences(kept: list[str]) -> list[str]:
    """Drop every fence whose opening line is directly followed by its closing one."""
    out: list[str] = []
    index = 0
    while index < len(kept):
        line = kept[index]
        opening = _FENCE_OPEN.match(line)
        if opening is None:
            out.append(line)
            index += 1
            continue
        ticks = opening.group(1)
        if index + 1 < len(kept) and kept[index + 1] == ticks:
            index += 2
            continue
        # A fence with a body: keep it whole, so no line inside it is read as
        # the opening line of another fence.
        out.append(line)
        index += 1
        while index < len(kept):
            out.append(kept[index])
            index += 1
            if out[-1] == ticks:
                break
    return out


def residue(resolved: Sequence[str]) -> list[str]:
    """Step 7, the residue rule, applied to both sides of every comparison.

    :param resolved: lines from `lines`.
    :return: the lines stripped of outer whitespace, without the lines a
        removed mark leaves behind: empty lines and lines holding only a syntax
        head, table rows whose cells are all empty, alignment rows with no
        table row next to them, and fences whose body is empty.
    """
    stripped = [line.strip() for line in resolved]
    kept = [
        line
        for line in stripped
        if not _HEAD_ONLY.fullmatch(line) and not _EMPTY_ROW.fullmatch(line)
    ]

    def is_row(position: int) -> bool:
        return (
            0 <= position < len(kept)
            and _TABLE_ROW.fullmatch(kept[position]) is not None
            and _ALIGNMENT_ROW.fullmatch(kept[position]) is None
        )

    aligned = [
        line
        for position, line in enumerate(kept)
        if _ALIGNMENT_ROW.fullmatch(line) is None
        or is_row(position - 1)
        or is_row(position + 1)
    ]
    return _drop_empty_fences(aligned)


def accept_all(annotated: str, *, roles: bool = True) -> list[str]:
    """Accept every mark: ADR-0037's seven steps, residue rule included.

    :param annotated: the renderer's output.
    :param roles: whether it was rendered with role prefixes on.
    :return: the lines of the test rendering this text claims to annotate.
    """
    return residue(lines(annotated, "accept", roles=roles))


def reject_all(annotated: str, *, roles: bool = True) -> list[str]:
    """Reject every mark: ADR-0037's seven steps, residue rule included.

    :param annotated: the renderer's output.
    :param roles: whether it was rendered with role prefixes on.
    :return: the lines of the source as this text reconstructs it.
    """
    return residue(lines(annotated, "reject", roles=roles))


def exact(left: Sequence[str], right: Sequence[str]) -> bool:
    """List equality: the same lines in the same order."""
    return list(left) == list(right)


def multiset(left: Sequence[str], right: Sequence[str]) -> bool:
    """`collections.Counter` equality: the same lines, in any order."""
    return Counter(left) == Counter(right)


def loose(resolved: Sequence[str]) -> list[str]:
    """Each line without its leading syntax head or list marker, and without whitespace."""
    return [_WHITESPACE.sub("", _LOOSE_HEAD.sub("", line, count=1)) for line in resolved]


def loose_multiset(left: Sequence[str], right: Sequence[str]) -> bool:
    """`multiset` after `loose` on both sides."""
    return multiset(loose(left), loose(right))


_TAG: Final[dict[Side, tuple[re.Pattern[str], re.Pattern[str]]]] = {
    "accept": (re.compile(r"<del>.*?</del>", re.S), re.compile(r"<ins>(.*?)</ins>", re.S)),
    "reject": (re.compile(r"<ins>.*?</ins>", re.S), re.compile(r"<del>(.*?)</del>", re.S)),
}


def tag_lines(rendered: str, side: Side) -> list[str]:
    """Resolve the legacy ``none`` style's ``<ins>`` and ``<del>`` and apply the residue rule.

    The legacy styles copy document text verbatim, so this is only a reader
    for documents that contain no ``<ins>`` or ``<del>`` of their own -- which
    is every committed run.

    :param rendered: output of the ``none`` legacy set.
    :param side: ``accept`` or ``reject``.
    :return: the residue-ruled lines of that side.
    """
    drop, keep = _TAG[side]
    return residue(keep.sub(r"\1", drop.sub("", rendered)).split("\n"))
