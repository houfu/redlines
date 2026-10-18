r"""The two HTML fragments: the change list and the document view (ADR-0038).

`render_change_list` is `redlines.comparison.Comparison.output_html` and
`render_document` is ``output_annotated(syntax="html")``. They are the only
producers of change HTML in the project: the MCP App shell (M5) and the
documentation site (M6) inject these strings and never render change data.

**The change list** is one row per change node, in change-list order (shown
wrapped here; a row has no whitespace inside it, and rows are joined by a
newline)::

    <section class="redlines" data-redlines-view="changes"
        data-redlines-fragment="1.0" data-redlines-schema="2.0">
    <style>STYLESHEET</style>
    <header class="redlines-header">…</header>
    <ol class="redlines-changes"><li class="redlines-change" ATTRS><details>
        <summary>SUMMARY</summary><div class="redlines-inline">BODY</div>
    </details></li>
    …</ol>
    </section>

A row's attributes are, in this order and each left out when its value is
``None`` or empty: ``data-index``, ``data-kind``, ``data-address`` (the test
address, the source address on a delete), ``data-source-address``,
``data-test-address``, ``data-source-label``, ``data-test-label``,
``data-block-kind``, ``data-role``, ``data-matched-by``, ``data-confidence``
(``repr(round(confidence, 4))``), ``data-chars`` (``max(chars_added,
chars_deleted)``), ``data-has-inline`` (``true`` or ``false``) and
``data-span-types`` (sorted, space-separated). Between them they carry every
`redlines.filters.ChangeFilter` field, so a shell can filter rows without
re-rendering. The summary is the kind, the label (``OLD → NEW`` for a move or
a renumber whose labels differ), an excerpt of at most 80 characters cut at a
space, the breadcrumb (``B1 › B2``), the role, the address (``SRC → TEST`` on
a move) and ``MATCHED_BY CONFIDENCE``. The body is the node's text with its
inline ops spliced in (`redlines.renderers._inplace.inline_segments`); an
insert or a delete shows its whole subtree under one ``<ins>`` or ``<del>``,
one line per text-bearing block, a row's cells joined by `` | ``, and a block
that moved into or out of it left out; a move or a renumber without inline ops
shows its text with the label change.

**The document view** has the same root (``data-redlines-view="document"``),
stylesheet and header, then ``<div class="redlines-document">`` with one
element per entry of the view (`redlines.renderers._view.build_view`), drawn
by the same in-place walk as every other annotated output
(`redlines.renderers._inplace.layout`, text variant, the
`redlines.renderers._marks.HTML` set). A block is a ``<p
class="redlines-block">`` holding its role span, its label span, its text and
any note, with ``data-test-address`` (not on a deleted block),
``data-source-address`` (on a changed block that has a source side, and on a
deleted one), ``data-level``, ``data-kind`` (on changed and deleted blocks) and
``data-role``. A heading adds ``role="heading" aria-level="L"`` and is never an
``<h1>``–``<h6>``, so a host page's table of contents is untouched. An inserted
or deleted block wraps its label and text in ``<ins>`` or ``<del>``; a changed
label is ``<span class="redlines-label"><del>OLD</del><ins>NEW</ins></span>``;
a move's destination ends with ``<span class="redlines-note">moved from …
</span>``, and its origin is a tombstone, ``<p class="redlines-note"
data-kind="move" data-source-address="SRC" data-test-address="TEST">``. A table
is a ``<table class="redlines-table">`` with its header row in ``<thead>``,
marks per cell, and deleted rows where the walk places them.

**The contract** both fragments meet (ADR-0038, items 1 to 9):

1. one root element, and no ``id``;
2. exactly one ``<style>``, the root's first child, holding `STYLESHEET`; only
   the elements ``section style header p span button ol li details summary div
   code ins del table thead tbody tr th td`` and only the attributes ``class``,
   ``data-*``, ``role``, ``aria-level``, ``hidden`` and ``type``; no
   ``@import`` and no ``url(`` in the stylesheet;
3. no ``on*`` and no ``style=`` attribute;
4. text through ``html.escape(s, quote=False)`` and attribute values through
   ``html.escape(s, quote=True)`` in double quotes, every document-, profile-
   and engine-derived string included (`redlines.renderers._escape`);
   newlines kept and shown with ``white-space: pre-wrap``;
5. the stylesheet only reads ``var(--redlines-NAME, FALLBACK)`` and declares no
   property, so a shell that sets ``--redlines-*`` on an ancestor wins by
   inheritance; each FALLBACK is the hosts' standard variable with a
   ``light-dark()`` fallback of its own (`THEME`), ``--redlines-bg`` falls back
   to ``transparent``, and the fragment declares no ``color-scheme``: it
   inherits the scheme its shell sets on ``<html>``;
6. every selector starts with the ``.redlines`` class, and none is or contains
   ``:root``, ``html`` or ``body``, because an injected ``<style>`` is
   document-global;
7. the blocks, the excerpt and the body are ``unicode-bidi: isolate``, so
   direction controls cannot reorder text outside their own element;
8. a hidden fullscreen button with no handler, which a shell un-hides and
   answers by setting ``data-redlines-display="fullscreen"`` on the root;
   native ``<details>`` to expand a row; a shell may append children to a row;
9. ``data-redlines-fragment="1.0"`` (`FRAGMENT_VERSION`): an added attribute
   or class bumps the minor, a rename or a removal the major.

``tests/helpers/fragment_checks.py`` holds the checks F1 to F9 that prove it.

**Determinism.** Rows in change-list order, attributes in the order above,
counts in `redlines.statistics.ChangeCounts` order, the stylesheet a constant,
floats as ``repr(round(x, 4))``, no iteration over a ``set``, no timestamps or
generated ids, no locale formatting, and an enum only through ``.value``.

Everything here is package-private except `STYLESHEET` and `FRAGMENT_VERSION`,
which `redlines.renderers` exports so a shell can carry the stylesheet itself.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from ..blocks import Block, BlockKind
from ..changes import Change, ChangeKind
from ._escape import html_attr, html_text
from ._inplace import (
    Chunk,
    Piece,
    _filter_value,
    inline_segments,
    label_text,
    layout,
    serialize,
)
from ._marks import HTML
from ._view import BlockStatus, ViewNode, build_view

if TYPE_CHECKING:  # pragma: no cover - imported for annotations only
    from ..comparison import Comparison

__all__: tuple[str, ...] = (
    "FRAGMENT_VERSION",
    "STYLESHEET",
    "THEME",
    "render_change_list",
    "render_document",
)

FRAGMENT_VERSION: Final[str] = "1.0"
"""The version of the fragment contract (ADR-0038, item 9), written on every
root as ``data-redlines-fragment``. An added attribute or class bumps the
minor; a rename or a removal bumps the major."""

# --------------------------------------------------------------------------
# The stylesheet.
# --------------------------------------------------------------------------

THEME: Final[tuple[tuple[str, str, str], ...]] = (
    ("font", "--font-sans", "system-ui,sans-serif"),
    ("mono", "--font-mono", "ui-monospace,monospace"),
    ("fg", "--color-text-primary", "light-dark(#141413,#FAF9F5)"),
    ("bg", "", "transparent"),
    ("muted", "--color-text-secondary", "light-dark(#3D3D3A,#C2C0B6)"),
    ("border", "--color-border-tertiary", "light-dark(#1F1E1D26,#DEDCD126)"),
    ("ins-fg", "--color-text-success", "light-dark(#265B19,#7AB948)"),
    ("ins-bg", "--color-background-success", "light-dark(#E9F1DC,#1B4614)"),
    ("del-fg", "--color-text-danger", "light-dark(#7F2C28,#EE8884)"),
    ("del-bg", "--color-background-danger", "light-dark(#F7ECEC,#602A28)"),
    ("move-fg", "--color-text-info", "light-dark(#3266AD,#80AADD)"),
    ("warn-fg", "--color-text-warning", "light-dark(#5A4815,#D1A041)"),
    ("radius", "--border-radius-sm", "4px"),
)
"""The thirteen theme properties (ADR-0038, item 5): ``--redlines-NAME``, the
hosts' standard variable it falls back to, and that variable's own fallback.

The colours are Claude's published light and dark values, which the ADR's
table gives for reference, the border at 15% opacity. ``bg`` has no standard
name: Claude asks an app not to paint a background, so it falls back to
``transparent``."""

_THEME: Final[dict[str, tuple[str, str]]] = {
    name: (standard, own) for name, standard, own in THEME
}


def _var(name: str) -> str:
    """``var(--redlines-NAME,var(--standard,OWN))``; ``bg`` goes straight to ``OWN``."""
    standard, own = _THEME[name]
    fallback = f"var({standard},{own})" if standard else own
    return f"var(--redlines-{name},{fallback})"


_FONT, _MONO = _var("font"), _var("mono")
_FG, _BG, _MUTED, _BORDER = _var("fg"), _var("bg"), _var("muted"), _var("border")
_INS_FG, _INS_BG = _var("ins-fg"), _var("ins-bg")
_DEL_FG, _DEL_BG = _var("del-fg"), _var("del-bg")
_MOVE_FG, _WARN_FG, _RADIUS = _var("move-fg"), _var("warn-fg"), _var("radius")

_RULES: Final[tuple[tuple[str, str], ...]] = (
    (
        ".redlines",
        f"font-family:{_FONT};color:{_FG};background:{_BG};"
        "line-height:1.5;max-inline-size:48rem",
    ),
    (
        '.redlines[data-redlines-display="fullscreen"]',
        "max-inline-size:none;padding:1rem 1.5rem",
    ),
    (".redlines [hidden]", "display:none"),
    (".redlines .redlines-header", "margin:0 0 .75em"),
    (".redlines .redlines-header p", "margin:0 0 .25em"),
    (
        ".redlines .redlines-counts",
        "display:flex;flex-wrap:wrap;gap:.25em 1em;font-weight:600",
    ),
    (
        ".redlines .redlines-config,.redlines .redlines-structure,"
        ".redlines .redlines-empty,.redlines .redlines-breadcrumb,"
        ".redlines .redlines-address,.redlines .redlines-match,"
        ".redlines .redlines-role",
        f"color:{_MUTED};font-size:.875em",
    ),
    (".redlines .redlines-notice", f"color:{_WARN_FG};font-size:.875em"),
    (".redlines .redlines-changes", "list-style:none;margin:0;padding:0"),
    (".redlines .redlines-change", "padding:.375em 0"),
    (
        ".redlines .redlines-change+.redlines-change",
        f"border-top:1px solid {_BORDER}",
    ),
    (".redlines summary", "cursor:pointer"),
    (".redlines summary>*", "margin-inline-end:.5em"),
    (
        ".redlines .redlines-kind",
        "font-size:.75em;font-weight:600;letter-spacing:.04em;text-transform:uppercase",
    ),
    ('.redlines [data-kind="insert"] .redlines-kind', f"color:{_INS_FG}"),
    ('.redlines [data-kind="delete"] .redlines-kind', f"color:{_DEL_FG}"),
    ('.redlines [data-kind="move"] .redlines-kind', f"color:{_MOVE_FG}"),
    (".redlines .redlines-label", "font-weight:600"),
    (
        ".redlines .redlines-role",
        f"border:1px solid {_BORDER};border-radius:{_RADIUS};padding:0 .3em",
    ),
    (".redlines code,.redlines .redlines-match", f"font-family:{_MONO}"),
    (".redlines .redlines-inline", "margin:.375em 0 .125em 1.25em"),
    (
        ".redlines .redlines-block,.redlines p.redlines-note,.redlines .redlines-table",
        "margin:0 0 .5em",
    ),
    (".redlines .redlines-block,.redlines .redlines-inline", "white-space:pre-wrap"),
    (
        ".redlines .redlines-block,.redlines .redlines-excerpt,"
        ".redlines .redlines-inline,.redlines .redlines-label,"
        ".redlines .redlines-breadcrumb,.redlines .redlines-role,"
        ".redlines .redlines-note",
        "unicode-bidi:isolate",
    ),
    ('.redlines [role="heading"]', "font-weight:600;margin-block-start:1em"),
    ('.redlines .redlines-document>[data-level="2"]', "margin-inline-start:1.5em"),
    ('.redlines .redlines-document>[data-level="3"]', "margin-inline-start:3em"),
    (
        '.redlines .redlines-document>[data-level="4"],'
        '.redlines .redlines-document>[data-level="5"],'
        '.redlines .redlines-document>[data-level="6"]',
        "margin-inline-start:4.5em",
    ),
    (
        ".redlines .redlines-document>[data-kind]",
        f"border-inline-start:2px solid {_BORDER};padding-inline-start:.5em",
    ),
    (
        '.redlines .redlines-document>[data-kind="move"]',
        f"border-inline-start-color:{_MOVE_FG}",
    ),
    (".redlines .redlines-note", f"color:{_MOVE_FG};font-style:italic"),
    (".redlines .redlines-table", "border-collapse:collapse"),
    (
        ".redlines th,.redlines td",
        f"border:1px solid {_BORDER};padding:.25em .5em;text-align:start;"
        "vertical-align:top",
    ),
    (
        ".redlines ins",
        f"color:{_INS_FG};background:{_INS_BG};text-decoration:underline;"
        f"border-radius:{_RADIUS}",
    ),
    (
        ".redlines del",
        f"color:{_DEL_FG};background:{_DEL_BG};text-decoration:line-through;"
        f"border-radius:{_RADIUS}",
    ),
)

STYLESHEET: Final[str] = "\n".join(f"{selector}{{{body}}}" for selector, body in _RULES)
"""The fragments' stylesheet, one rule per line: the content of each
fragment's one ``<style>`` (ADR-0038, items 5 to 8).

Every selector starts with the ``.redlines`` class; every colour, background,
border and font is read through ``var(--redlines-NAME, FALLBACK)`` (`THEME`);
nothing declares a custom property or ``color-scheme``; and there is no
``@import``, no ``url(`` and no at-rule. It is a constant, so a site with a
hash-based CSP can list ``sha256(STYLESHEET)`` among its style hashes."""

# --------------------------------------------------------------------------
# What both fragments share: the root, the header, attributes, spelling.
# --------------------------------------------------------------------------

_BUTTON: Final[str] = (
    '<button type="button" class="redlines-fullscreen" '
    'data-redlines-action="fullscreen" hidden>Full screen</button>'
)

_TEXT_BEARING: Final[frozenset[BlockKind]] = frozenset(
    {
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.LIST_ITEM,
        BlockKind.CELL,
        BlockKind.UNKNOWN,
    }
)
"""The kinds whose own text is a line of a whole-subtree body, as in the
in-place walk; a row is one line of its cells."""

_EXCERPT_LENGTH: Final[int] = 80
_ARROW: Final[str] = " → "
_BREADCRUMB_JOINER: Final[str] = " › "
_CELL_JOINER: Final[str] = " | "


def _attributes(pairs: Sequence[tuple[str, str | None]]) -> str:
    """`` name="value"`` for each pair, in order, but a ``None`` or empty value."""
    return "".join(f' {name}="{html_attr(value)}"' for name, value in pairs if value)


def _open(view: str, schema_version: str) -> str:
    return (
        f'<section class="redlines" data-redlines-view="{html_attr(view)}" '
        f'data-redlines-fragment="{FRAGMENT_VERSION}" '
        f'data-redlines-schema="{html_attr(schema_version)}">'
    )


def _confidence(change: Change) -> str:
    """The confidence as the JSON writes it: ``repr(round(confidence, 4))``."""
    return repr(round(change.confidence, 4))


def _header(comparison: Comparison) -> list[str]:
    """The header both fragments share, one element per line (ADR-0038, "Header")."""
    statistics = comparison.statistics()
    counts = statistics.counts
    config = comparison.config
    total = "1 change" if counts.total == 1 else f"{counts.total} changes"
    lines = [
        '<header class="redlines-header">',
        '<p class="redlines-counts">'
        f'<span data-count="total">{total}</span>'
        f'<span data-count="insert">{counts.inserted} inserted</span>'
        f'<span data-count="delete">{counts.deleted} deleted</span>'
        f'<span data-count="modify">{counts.modified} modified</span>'
        f'<span data-count="move">{counts.moved} moved</span>'
        f'<span data-count="renumber">{counts.renumbered} renumbered</span>'
        "</p>",
        '<p class="redlines-config">'
        f"{html_text(config.test_format)}"
        f" · profile {html_text(config.profile or 'none')}"
        f" · similarity {html_text(config.similarity)}</p>",
        '<p class="redlines-structure">'
        f"{comparison.source.fallback_count} of {statistics.source_blocks}"
        " source blocks and "
        f"{comparison.test.fallback_count} of {statistics.test_blocks}"
        " test blocks matched no rule</p>",
    ]
    lines.extend(_notices(comparison))
    lines.append(_BUTTON)
    lines.append("</header>")
    return lines


def _notices(comparison: Comparison) -> list[str]:
    """The notices, each only when true: filtered, budget, then each ``Dropped``."""
    notices: list[str] = []
    config = comparison.config
    if config.filter is not None:
        fields: list[str] = []
        for name, value in config.filter.to_dict().items():
            rendered = _filter_value(value)
            if rendered is not None:
                fields.append(f"{name}={rendered}")
        if fields:
            notices.append(
                '<p class="redlines-notice" data-notice="filtered">'
                f"Filtered: {html_text('; '.join(fields))}</p>"
            )
    if config.budget_exhausted:
        notices.append(
            '<p class="redlines-notice" data-notice="budget-exhausted">'
            "Alignment stopped early: the comparison budget ran out</p>"
        )
    for side, tree in (("source", comparison.source), ("test", comparison.test)):
        for dropped in tree.dropped:
            notices.append(
                f'<p class="redlines-notice" data-notice="dropped" data-side="{side}">'
                f"{dropped.count} {html_text(dropped.kind)} dropped from the {side}: "
                f"{html_text(dropped.reason)}</p>"
            )
    return notices


def _label_span(inner: str) -> str:
    return f'<span class="redlines-label">{inner}</span>'


def _relabel(old: str, new: str) -> str:
    """A changed label, ``<del>OLD</del><ins>NEW</ins>`` in a label span."""
    deleted = f"<del>{html_text(old)}</del>" if old else ""
    inserted = f"<ins>{html_text(new)}</ins>" if new else ""
    return _label_span(deleted + inserted)


def _spell(pieces: Sequence[Piece]) -> str:
    """Spell pieces with the `redlines.renderers._marks.HTML` escape and marks."""
    return serialize([Chunk(tuple(pieces))], HTML, roles=False)


# --------------------------------------------------------------------------
# Subtrees: what an insert or a delete shows.
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Line:
    """One line of a whole-subtree body: a block's label as written, and its text."""

    label: str
    text: str

    def html(self) -> str:
        """The line with its label in a label span."""
        if not self.label:
            return html_text(self.text)
        space = " " if self.text else ""
        return _label_span(html_text(self.label)) + space + html_text(self.text)

    def plain(self) -> str:
        """The line as text, one space between the label and the text."""
        if self.label and self.text:
            return f"{self.label} {self.text}"
        return self.label or self.text


def _keeps(change: Change) -> Callable[[ViewNode], bool]:
    """Which descendants a node's subtree lines include.

    An insert keeps its unmatched descendants, the ones the view marks
    ``INSERT``: a matched one moved in, whether or not a filter kept its move
    node, and is left out with its subtree. A delete keeps its deleted
    descendants, the ghost's ``DELETE`` children, and leaves out the
    tombstones of the blocks that moved out of it. Any other node keeps its
    test side: everything but ghosts and tombstones.
    """
    if change.kind is ChangeKind.INSERT:
        return lambda node: node.status is BlockStatus.INSERT
    if change.kind is ChangeKind.DELETE:
        return lambda node: node.status is BlockStatus.DELETE
    return lambda node: node.status not in (BlockStatus.DELETE, BlockStatus.ORIGIN)


def _subtree_lines(node: ViewNode, keep: Callable[[ViewNode], bool]) -> list[_Line]:
    """One line per text-bearing block of a subtree, in pre-order; a row, its cells."""
    lines: list[_Line] = []
    stack: list[ViewNode] = [node]
    while stack:
        current = stack.pop()
        block = current.block
        if block.kind is BlockKind.ROW:
            cells = [child.block.text for child in current.children if keep(child)]
            lines.append(_Line("", _CELL_JOINER.join(cells)))
            continue
        if block.kind in _TEXT_BEARING:
            line = _Line(label_text(block, "text"), block.text)
            if line.label or line.text:
                lines.append(line)
        stack.extend(child for child in reversed(current.children) if keep(child))
    return lines


def _excerpt(text: str) -> str:
    """Whitespace collapsed, and past 80 characters cut at a space, then ``…``.

    The cut is at the last space at or before the 80th character, or at the
    80th character when there is none.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= _EXCERPT_LENGTH:
        return collapsed
    cut = collapsed.rfind(" ", 0, _EXCERPT_LENGTH + 1)
    return (collapsed[:cut] if cut > 0 else collapsed[:_EXCERPT_LENGTH]) + "…"


# --------------------------------------------------------------------------
# The change list.
# --------------------------------------------------------------------------

_NodeKey = tuple[str | None, str | None]


def _change_nodes(view: ViewNode) -> dict[_NodeKey, ViewNode]:
    """The view node that owns each change, keyed by the change's two addresses.

    The key is unique: a test address is the test side of at most one node,
    and a source address the source side of at most one. A tombstone carries
    its move's change too and is left out, so a move maps to its destination.
    """
    nodes: dict[_NodeKey, ViewNode] = {}
    for node in view.walk():
        change = node.change
        if change is not None and node.status is not BlockStatus.ORIGIN:
            nodes[(change.source_address, change.test_address)] = node
    return nodes


def _row_attributes(index: int, change: Change) -> str:
    return _attributes(
        (
            ("data-index", str(index)),
            ("data-kind", change.kind.value),
            ("data-address", change.test_address or change.source_address),
            ("data-source-address", change.source_address),
            ("data-test-address", change.test_address),
            ("data-source-label", change.source_label),
            ("data-test-label", change.test_label),
            ("data-block-kind", change.block_kind.value),
            ("data-role", change.role),
            ("data-matched-by", change.matched_by),
            ("data-confidence", _confidence(change)),
            ("data-chars", str(max(change.chars_added, change.chars_deleted))),
            ("data-has-inline", "true" if change.has_inline else "false"),
            ("data-span-types", " ".join(sorted(change.span_types))),
        )
    )


def _summary_label(change: Change) -> str:
    """The summary's label: ``OLD → NEW``, or the one label the node has.

    ``OLD → NEW`` for a move or a renumber whose labels differ; otherwise the
    test label, or the source label on a delete.
    """
    source, test = change.source_label or "", change.test_label or ""
    if change.kind in (ChangeKind.MOVE, ChangeKind.RENUMBER) and source != test:
        return f"{source}{_ARROW}{test}".strip()
    return source if change.kind is ChangeKind.DELETE else test


def _summary(change: Change, node: ViewNode) -> str:
    parts = [f'<span class="redlines-kind">{html_text(change.kind.value)}</span>']
    label = _summary_label(change)
    if label:
        parts.append(_label_span(html_text(label)))
    text = change.source_text if change.kind is ChangeKind.DELETE else change.test_text
    if not text:
        lines = _subtree_lines(node, _keeps(change))
        text = _CELL_JOINER.join(line.plain() for line in lines)
    parts.append(f'<span class="redlines-excerpt">{html_text(_excerpt(text))}</span>')
    if change.breadcrumb:
        breadcrumb = _BREADCRUMB_JOINER.join(change.breadcrumb)
        parts.append(
            f'<span class="redlines-breadcrumb">{html_text(breadcrumb)}</span>'
        )
    if change.role:
        parts.append(f'<span class="redlines-role">{html_text(change.role)}</span>')
    if change.kind is ChangeKind.MOVE:
        address = f"{change.source_address}{_ARROW}{change.test_address}"
    else:
        address = change.test_address or change.source_address or ""
    parts.append(f'<code class="redlines-address">{html_text(address)}</code>')
    parts.append(
        f'<span class="redlines-match">{html_text(change.matched_by)} '
        f"{_confidence(change)}</span>"
    )
    return "".join(parts)


def _splice(change: Change) -> list[Piece]:
    """The node's text with its inline ops as marks.

    Equal runs come from the test side, and a replacement is a delete then an
    insert, since the ``html`` set has no substitution: what the in-place walk
    writes for the same node.
    """
    pieces: list[Piece] = []
    for segment in inline_segments(change):
        if segment.kind == "equal":
            if segment.test_text:
                pieces.append(Piece("text", segment.test_text))
            continue
        if segment.kind in ("delete", "replace") and segment.source_text:
            pieces.append(Piece("delete", segment.source_text))
        if segment.kind in ("insert", "replace") and segment.test_text:
            pieces.append(Piece("insert", segment.test_text))
    return pieces


def _body(change: Change, node: ViewNode) -> str:
    if change.kind in (ChangeKind.INSERT, ChangeKind.DELETE):
        tag = "ins" if change.kind is ChangeKind.INSERT else "del"
        lines = _subtree_lines(node, _keeps(change))
        return f"<{tag}>" + "\n".join(line.html() for line in lines) + f"</{tag}>"
    if change.inline:
        return _spell(_splice(change))
    text = html_text(change.test_text)
    if change.kind in (ChangeKind.MOVE, ChangeKind.RENUMBER):
        old = "" if node.counterpart is None else label_text(node.counterpart, "text")
        new = label_text(node.block, "text")
        if old != new:
            return _relabel(old, new) + (" " if text else "") + text
    return text


def render_change_list(comparison: Comparison, *, schema_version: str) -> str:
    """Render the change list fragment: one row per change node (ADR-0038).

    :param comparison: the comparison, filtered or not; a filtered one lists
        only its own nodes and says so in a notice.
    :param schema_version: the `redlines.comparison.SCHEMA_VERSION` the
        fragment is rendered from, written as ``data-redlines-schema``.
        Passed in, because a renderer may not import the comparison module at
        run time.
    :return: the fragment, one ``<section>`` with no trailing newline.
    """
    nodes = _change_nodes(build_view(comparison))
    rows: list[str] = []
    for index, change in enumerate(comparison.changes):
        node = nodes[(change.source_address, change.test_address)]
        rows.append(
            f'<li class="redlines-change"{_row_attributes(index, change)}>'
            f"<details><summary>{_summary(change, node)}</summary>"
            f'<div class="redlines-inline">{_body(change, node)}</div>'
            "</details></li>"
        )
    lines = [_open("changes", schema_version), f"<style>{STYLESHEET}</style>"]
    lines.extend(_header(comparison))
    if rows:
        lines.append('<ol class="redlines-changes">' + "\n".join(rows) + "</ol>")
    else:
        lines.append('<p class="redlines-empty">No changes.</p>')
    lines.append("</section>")
    return "\n".join(lines)


# --------------------------------------------------------------------------
# The document view.
# --------------------------------------------------------------------------

_CHANGED: Final[frozenset[BlockStatus]] = frozenset(
    {BlockStatus.MODIFY, BlockStatus.MOVE, BlockStatus.RENUMBER}
)
"""The statuses of a block in both documents that a change node names."""


class _Document:
    """One render of the document view: the in-place layout's chunks, as elements.

    The layout decides which blocks are drawn, where ghosts and tombstones go,
    what an inserted or deleted subtree writes and how a table's rows are
    ordered, exactly as it does for CriticMarkup and the legacy styles; this
    class only turns each chunk into an element. Two things a chunk keeps flat
    are taken apart again here, both exactly. The label is the start of the
    block's first text piece, or a delete and an insert when it changed. A
    table's rows and cells are separated by the syntax pieces ``"| "``,
    ``" | "``, ``" |"`` and ``"\\n"``, and every ``|`` in a cell is written
    ``\\|``.
    """

    def __init__(self, comparison: Comparison, view: ViewNode, roles: bool) -> None:
        self.comparison = comparison
        self.view = view
        self.roles = roles
        self.test_nodes: dict[str, ViewNode] = {
            node.block.path: node
            for node in view.walk()
            if node.status not in (BlockStatus.DELETE, BlockStatus.ORIGIN)
        }
        self.moves: dict[str, Change] = {
            change.source_address: change
            for change in comparison.changes
            if change.kind is ChangeKind.MOVE and change.source_address is not None
        }

    def elements(self) -> list[str]:
        """One element per chunk of the layout, in order, but the header notices."""
        elements: list[str] = []
        chunks = layout(
            self.comparison, HTML, syntax="text", roles=self.roles, view=self.view
        )
        for chunk in chunks:
            block, status = chunk.block, chunk.status
            if block is None or status is None:
                continue  # a header notice: the shared header carries it
            if status is BlockStatus.ORIGIN:
                elements.append(self._tombstone(chunk, block))
            elif chunk.pieces and chunk.pieces[0].kind == "note":
                elements.append(self._moved_container(chunk, block))
            elif block.kind is BlockKind.TABLE:
                elements.append(self._table(chunk, block, status))
            else:
                elements.append(self._block(chunk, block, status))
        return elements

    def _attributes(self, block: Block, status: BlockStatus) -> str:
        """A block's attributes, in order (ADR-0038, "Blocks")."""
        source_address: str | None = None
        if status is BlockStatus.DELETE:
            test_address, source_address = None, block.path
        else:
            test_address = block.path
            if status in _CHANGED:
                change = self.test_nodes[block.path].change
                source_address = None if change is None else change.source_address
        kind = None if status is BlockStatus.UNCHANGED else status.value
        return _attributes(
            (
                ("data-test-address", test_address),
                ("data-source-address", source_address),
                ("data-level", str(block.level)),
                ("data-kind", kind),
                ("data-role", block.role),
            )
        )

    def _tombstone(self, chunk: Chunk, block: Block) -> str:
        """A move's origin, with the layout's own note.

        The note reads ``SRC_LABEL moved to TEST_LABEL TEST_ADDRESS``.
        """
        change = self.moves[block.path]
        return _note(chunk, source_address=block.path, test_address=change.test_address)

    def _moved_container(self, chunk: Chunk, block: Block) -> str:
        """A moved block with no line of its own, such as a table: its note."""
        change = self.test_nodes[block.path].change
        source = None if change is None else change.source_address
        return _note(chunk, source_address=source, test_address=block.path)

    def _block(self, chunk: Chunk, block: Block, status: BlockStatus) -> str:
        pieces = list(chunk.pieces)
        role = pieces.pop(0).text if pieces and pieces[0].kind == "role" else ""
        if status in (BlockStatus.INSERT, BlockStatus.DELETE):
            content = _whole(pieces, block)
        else:
            content = self._line(pieces, block)
        heading = (
            f' role="heading" aria-level="{_heading_level(block)}"'
            if block.kind is BlockKind.HEADING
            else ""
        )
        return (
            f'<p class="redlines-block"{heading}{self._attributes(block, status)}>'
            f"{role}{content}</p>"
        )

    def _line(self, pieces: list[Piece], block: Block) -> str:
        """A block in both documents: its label part, then the layout's text and note.

        For a set with no substitution, in the text variant, the layout writes
        the label part as a delete of OLD and an insert of NEW, each with the
        separating space, when a node names the block and its labels as
        written differ; otherwise as NEW and the space at the start of the
        first text piece.
        """
        node = self.test_nodes[block.path]
        new = label_text(block, "text")
        space = " " if block.text else ""
        old = "" if node.counterpart is None else label_text(node.counterpart, "text")
        if node.change is not None and old != new:
            if old:
                _take(pieces, "delete", old + space)
            if new:
                _take(pieces, "insert", new + space)
            label = _relabel(old, new) + space
        elif new:
            _take(pieces, "text", new + space)
            label = _label_span(html_text(new)) + space
        else:
            label = ""
        return label + _spell(pieces)

    def _table(self, chunk: Chunk, block: Block, status: BlockStatus) -> str:
        rows = _table_rows(chunk.pieces)
        header, body = rows[0], rows[1:]
        parts = [
            f'<table class="redlines-table"{self._attributes(block, status)}>',
            "<thead><tr>"
            + "".join(f"<th>{_spell(cell)}</th>" for cell in header)
            + "</tr></thead>",
        ]
        if body:
            parts.append(
                "<tbody>"
                + "".join(
                    "<tr>"
                    + "".join(f"<td>{_spell(cell)}</td>" for cell in row)
                    + "</tr>"
                    for row in body
                )
                + "</tbody>"
            )
        parts.append("</table>")
        return "".join(parts)


def _note(chunk: Chunk, *, source_address: str | None, test_address: str | None) -> str:
    """A note on a line of its own, a ``<p class="redlines-note" data-kind="move">``."""
    if len(chunk.pieces) != 1 or chunk.pieces[0].kind != "note":
        raise AssertionError(  # pragma: no cover - a note line is one note
            f"a note line is one note, got {chunk.pieces!r}"
        )
    attributes = _attributes(
        (("data-source-address", source_address), ("data-test-address", test_address))
    )
    return (
        f'<p class="redlines-note" data-kind="move"{attributes}>'
        f"{html_text(chunk.pieces[0].text)}</p>"
    )


def _whole(pieces: Sequence[Piece], block: Block) -> str:
    """An inserted or deleted block: label and text in one ``<ins>`` or ``<del>``."""
    if len(pieces) != 1 or pieces[0].kind not in ("insert", "delete"):
        raise AssertionError(  # pragma: no cover - a whole block is one mark
            f"a whole block is one mark, got {pieces!r}"
        )
    mark = pieces[0]
    tag = "ins" if mark.kind == "insert" else "del"
    label = label_text(block, "text")
    if label and mark.text.startswith(label):
        body = _label_span(html_text(label)) + html_text(mark.text[len(label) :])
    else:
        body = html_text(mark.text)
    return f"<{tag}>{body}</{tag}>"


def _take(pieces: list[Piece], kind: str, prefix: str) -> None:
    """Take ``prefix``, written by the layout as a ``kind`` piece, off ``pieces``."""
    first = pieces[0] if pieces else None
    if first is None or first.kind != kind or not first.text.startswith(prefix):
        raise AssertionError(  # pragma: no cover - the label part, by construction
            f"expected the label part {prefix!r} as a {kind} piece, got {first!r}"
        )
    rest = first.text[len(prefix) :]
    if rest and kind != "text":
        raise AssertionError(  # pragma: no cover - a label mark holds the label alone
            f"a label mark holds only the label, got {first!r}"
        )
    if rest:
        pieces[0] = Piece("text", rest)
    else:
        del pieces[0]


def _table_rows(pieces: Sequence[Piece]) -> list[list[list[Piece]]]:
    """A table chunk's rows of cells of pieces, each ``\\|`` back to ``|``."""
    rows: list[list[list[Piece]]] = []
    for piece in pieces:
        if piece.kind != "syntax":
            rows[-1][-1].append(
                Piece(piece.kind, _unpipe(piece.text), _unpipe(piece.new))
            )
        elif piece.text == "| ":
            rows.append([[]])
        elif piece.text == " | ":
            rows[-1].append([])
        elif piece.text not in (" |", "\n"):
            raise AssertionError(  # pragma: no cover - no alignment row in text
                f"unexpected table syntax {piece.text!r}"
            )
    return rows


def _unpipe(text: str) -> str:
    """Undo the layout's pipe escape, which put one backslash before every ``|``."""
    return text.replace("\\|", "|")


def _heading_level(block: Block) -> int:
    """A heading's ``aria-level``, from 1 to 6.

    ``attrs["atx_level"]`` when it reads as an integer, else
    ``min(level + 1, 6)``, and clamped to 1 to 6 either way.
    """
    value = block.attrs.get("atx_level")
    level = min(block.level + 1, 6)
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        try:
            level = int(value)
        except ValueError:
            pass
    return min(max(level, 1), 6)


def render_document(
    comparison: Comparison, *, schema_version: str, roles: bool = True
) -> str:
    """Render the document view: the test document, its changes in place (ADR-0038).

    :param comparison: the comparison, filtered or not; a filtered one draws
        the same test document with only its own nodes marked.
    :param schema_version: the `redlines.comparison.SCHEMA_VERSION` the
        fragment is rendered from, written as ``data-redlines-schema``.
    :param roles: write each block's role span. ``data-role`` is written
        either way: it is what a shell filters on, and it shows nothing.
    :return: the fragment, one ``<section>`` with no trailing newline.
    """
    view = build_view(comparison)
    elements = _Document(comparison, view, roles).elements()
    lines = [_open("document", schema_version), f"<style>{STYLESHEET}</style>"]
    lines.extend(_header(comparison))
    lines.append('<div class="redlines-document">' + "\n".join(elements) + "</div>")
    lines.append("</section>")
    return "\n".join(lines)
