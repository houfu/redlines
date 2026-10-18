"""What each in-place output spells for an insert, a delete, a replacement and a note.

A `MarkSet` is plain data: delimiter strings plus the capabilities the
traversal branches on, so ``_inplace`` never switches on a set's name
(ADR-0037, "Marks").

- ``substitution``: a replacement is written as one construct
  (CriticMarkup's ``{~~old~>new~~}``) or, when ``None``, as a delete followed
  by an insert.
- ``note`` and ``role``: whether the set can carry notes (moves, renumbers,
  header notices) and role prefixes at all. The legacy styles carry neither.
- ``escape``: how document text is protected. The legacy styles copy it
  verbatim, as 0.6 does, so a caller who renders untrusted input as HTML must
  sanitise it; CriticMarkup uses the backslash rule of ``_escape``.
- ``whole_moves``: 0.6's picture of a move -- the moved block's whole source
  subtree struck at its origin and its whole test subtree inserted at its
  destination -- rather than the destination drawn in place with a note and a
  tombstone at the origin.

`LEGACY` holds the six `redlines.enums.MarkdownStyle` styles and
``custom_css`` with its default classes; `custom_css` builds the last one with
other classes. The strings are 0.6's, copied from
``Redlines.output_markdown`` rather than imported, because that table is a
local variable of a 0.6 method that stays untouched. The trailing spaces of
the ``streamlit`` delimiters are 0.6's too.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Literal

from ..enums import MarkdownStyle

__all__: tuple[str, ...] = (
    "MarkSet",
    "LEGACY",
    "CRITIC",
    "DEFAULT_INS_CLASS",
    "DEFAULT_DEL_CLASS",
    "custom_css",
    "HTML",
)

Escape = Literal["none", "critic", "html"]
"""How a set protects the document text it copies."""


@dataclass(frozen=True, slots=True)
class MarkSet:
    """The delimiters and capabilities of one in-place output.

    :param name: the set's name: a `redlines.enums.MarkdownStyle` value,
        ``"custom_css"`` or ``"critic"``.
    :param insert: the ``(open, close)`` pair written around inserted text.
    :param delete: the ``(open, close)`` pair written around deleted text.
    :param substitution: ``(open, separator, close)`` for a replacement written
        as one construct, or ``None`` to write a delete then an insert.
    :param note: ``(open, close)`` around a note, or ``None`` for a set that
        carries no notes.
    :param role: ``(open, close)`` around a role prefix, or ``None`` for a set
        that never shows roles.
    :param escape: how document text is protected: ``"none"`` copies it
        verbatim, ``"critic"`` applies the backslash rule of ``_escape``,
        ``"html"`` escapes it as HTML.
    :param whole_moves: draw a move as 0.6 does, the whole source subtree
        struck at the origin and the whole test subtree inserted at the
        destination, instead of in place with notes.
    """

    name: str
    insert: tuple[str, str]
    delete: tuple[str, str]
    substitution: tuple[str, str, str] | None = None
    note: tuple[str, str] | None = None
    role: tuple[str, str] | None = None
    escape: Escape = "none"
    whole_moves: bool = True

    @property
    def notes(self) -> bool:
        """Whether this set can carry notes: moves, renumbers, header notices."""
        return self.note is not None

    @property
    def roles(self) -> bool:
        """Whether this set can show role prefixes at all."""
        return self.role is not None


DEFAULT_INS_CLASS: Final[str] = "redline-inserted"
"""0.6's default class for an insertion under ``custom_css``."""

DEFAULT_DEL_CLASS: Final[str] = "redline-deleted"
"""0.6's default class for a deletion under ``custom_css``."""

_STRIKE_RED: Final[tuple[str, str]] = (
    "<span style='color:red;font-weight:700;text-decoration:line-through;'>",
    "</span>",
)


def custom_css(
    ins_class: str = DEFAULT_INS_CLASS, del_class: str = DEFAULT_DEL_CLASS
) -> MarkSet:
    """Return the ``custom_css`` set with the given classes.

    The classes are written into the delimiters as they are, single-quoted and
    unescaped, exactly as 0.6 writes them.

    :param ins_class: the class of an inserted run.
    :param del_class: the class of a deleted run.
    :return: the set, named ``"custom_css"``.
    """
    return MarkSet(
        name="custom_css",
        insert=(f"<span class='{ins_class}'>", "</span>"),
        delete=(f"<span class='{del_class}'>", "</span>"),
    )


LEGACY: Final[Mapping[str, MarkSet]] = MappingProxyType(
    {
        MarkdownStyle.RED_GREEN.value: MarkSet(
            name=MarkdownStyle.RED_GREEN.value,
            insert=("<span style='color:green;font-weight:700;'>", "</span>"),
            delete=_STRIKE_RED,
        ),
        MarkdownStyle.NONE.value: MarkSet(
            name=MarkdownStyle.NONE.value,
            insert=("<ins>", "</ins>"),
            delete=("<del>", "</del>"),
        ),
        MarkdownStyle.RED.value: MarkSet(
            name=MarkdownStyle.RED.value,
            insert=("<span style='color:red;font-weight:700;'>", "</span>"),
            delete=_STRIKE_RED,
        ),
        MarkdownStyle.GHFM.value: MarkSet(
            name=MarkdownStyle.GHFM.value,
            insert=("**", "**"),
            delete=("~~", "~~"),
        ),
        MarkdownStyle.BBCODE.value: MarkSet(
            name=MarkdownStyle.BBCODE.value,
            insert=("[b][color=green]", "[/color][/b]"),
            delete=("[s][color=red]", "[/color][/s]"),
        ),
        MarkdownStyle.STREAMLIT.value: MarkSet(
            name=MarkdownStyle.STREAMLIT.value,
            insert=("**:green[", "]** "),
            delete=("~~:red[", "]~~ "),
        ),
        "custom_css": custom_css(),
    }
)
"""The legacy sets by name: the six `redlines.enums.MarkdownStyle` values, then
``custom_css`` with 0.6's default classes.

Each writes a replacement as a delete then an insert, carries no notes and no
roles, copies document text verbatim and draws moves whole.
"""

CRITIC: Final[MarkSet] = MarkSet(
    name="critic",
    insert=("{++", "++}"),
    delete=("{--", "--}"),
    substitution=("{~~", "~>", "~~}"),
    note=("{>>", "<<}"),
    role=("[", "] "),
    escape="critic",
    whole_moves=False,
)
"""CriticMarkup as ADR-0037's grammar writes it: no spaces inside delimiters, a
replacement as one substitution, notes for moves and renumbers, role prefixes,
and the backslash escape of ``_escape``."""

HTML: Final[MarkSet] = MarkSet(
    name="html",
    insert=("<ins>", "</ins>"),
    delete=("<del>", "</del>"),
    note=('<span class="redlines-note">', "</span>"),
    role=('<span class="redlines-role">', "</span> "),
    escape="html",
    whole_moves=False,
)
"""The HTML document view's set (ADR-0037, ADR-0038): ``<ins>`` and ``<del>``,
a replacement as a delete then an insert, notes and role prefixes as elements,
moves drawn in place with notes, and every piece of document text through
``html.escape`` (`redlines.renderers._escape.html_text`).

The role prefix is the role span and then a space, as CriticMarkup's ``[ROLE]``
is followed by one, so a block's text reads ``clause 1.1 The Supplier …``
rather than running the role into the label. ``redlines.renderers._html``
spells the label part and the tables itself, because a fragment needs
elements where the layout has flat pieces."""
