r"""ADR-0038's checks F1 to F9 on an HTML fragment, with ``html.parser`` and ``re``.

`redlines.comparison.Comparison.output_html` and
``output_annotated(syntax="html")`` return fragments that the MCP App shell and
the documentation site inject as they are, so the contract they promise is
checked here, from the markup alone, by a reader written from the ADR rather
than from the renderer. Nothing here imports ``redlines.renderers``: the
stylesheet table below is the ADR's, copied, so a renderer that drifts from it
fails rather than taking its oracle along.

- **F1**, well formed: one root, every start tag closed in order, no stray
  end tag, no text outside the root, no comment; the root is
  ``<section class="redlines">`` with its three ``data-redlines-*``
  attributes.
- **F2**, contract items 2 and 3: the element and attribute allowlist; no
  ``on*``, ``style``, ``id`` or URL-bearing attribute; exactly one
  ``<style>``, the root's first child; no ``@import`` or ``url(``.
- **F3**, theming: every colour, background, border and font declaration
  reads one ``var(--redlines-NAME, var(--STANDARD, OWN))`` (``transparent``
  for ``bg``), with nothing beside it but lengths and border styles; the
  names used are the thirteen; no custom property and no ``color-scheme`` is
  declared; no colour appears outside such a ``var()``.
- **F4**, scoping: every selector starts with the ``.redlines`` class, and
  none names ``:root``, ``html`` or ``body``.
- **F5**, rows: one per change, in order, each with its attributes in the
  ADR's order and equal to its node's fields, in the ADR's shape.
- **F6**, filter parity: for every `redlines.filters.ChangeFilter` of a
  battery, the rows the attributes select are exactly the nodes
  `redlines.filters.filter_changes` keeps.
- **F7**, text: what a browser shows equals the documents' text, each row's
  body and each block of the document view, on its accept and reject sides;
  the hostile corpus runs through F1 to F4 as well.
- **F8**, header: the counts equal ``statistics().counts`` ("1 change",
  singular), then the configuration and structure lines, and each notice
  exactly when its condition holds, in order.
- **F9**, determinism: two renders are byte-equal, and a comparison rebuilt
  with ``from_dict(to_dict(include_alignment=True))`` renders the same bytes.

Two readings of the ADR are this module's, and the checks state them exactly.
F3 lists ``border*``; ``border-collapse`` and ``border-spacing`` lay a table out
and take no colour, so they are not theme declarations, and a border
shorthand's width and style may stand beside its colour's ``var()``
(``border-top: 1px solid var(--redlines-border, …)``), or no border could be
drawn at all. F4's "starts with ``.redlines``" means the root's own class,
compound or followed by a combinator: ``.redlines-change`` alone would be some
other class, and a host page could have one.

Each check raises `FragmentError`, an ``AssertionError``, with a message that
says what and where.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Final

from redlines.alignment import PASS_NAMES
from redlines.blocks import Block, BlockKind, BlockTree
from redlines.changes import CHANGE_KINDS, UNMATCHED, Change, ChangeKind
from redlines.comparison import SCHEMA_VERSION, Comparison
from redlines.filters import ChangeFilter, filter_changes

__all__: tuple[str, ...] = (
    "FragmentError",
    "Element",
    "parse",
    "check_well_formed",
    "check_self_contained",
    "check_theme",
    "check_scoped",
    "check_rows",
    "check_filter_parity",
    "check_row_texts",
    "check_block_texts",
    "check_header",
    "check_deterministic",
    "check_change_list",
    "check_document",
    "filter_battery",
    "row_elements",
    "rules",
)

FRAGMENT_VERSION: Final[str] = "1.0"


class FragmentError(AssertionError):
    """A fragment broke the contract of ADR-0038."""


# --------------------------------------------------------------------------
# Parsing: a small element tree from html.parser's events.
# --------------------------------------------------------------------------

VOID_ELEMENTS: Final[frozenset[str]] = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
"""The HTML void elements, which have no end tag (F1). The allowlist has none."""


@dataclass
class Element:
    """One element and its children, text as strings, attributes in source order."""

    tag: str
    attrs: list[tuple[str, str | None]]
    line: int
    children: list[Element | str] = field(default_factory=list)

    def get(self, name: str) -> str | None:
        """An attribute's value: ``None`` when absent, ``""`` for a bare one."""
        for key, value in self.attrs:
            if key == name:
                return "" if value is None else value
        return None

    def names(self) -> list[str]:
        """The attribute names, in source order."""
        return [key for key, _ in self.attrs]

    def classes(self) -> list[str]:
        return (self.get("class") or "").split()

    def walk(self) -> Iterator[Element]:
        """This element and every element below it, in document order."""
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def elements(self) -> list[Element]:
        """The child elements, text left out."""
        return [child for child in self.children if isinstance(child, Element)]

    def text(self) -> str:
        """All the text below this element, as a browser's ``textContent``."""
        return "".join(
            child if isinstance(child, str) else child.text() for child in self.children
        )

    def where(self) -> str:
        return f"<{self.tag}> on line {self.line}"


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.roots: list[Element] = []
        self.stack: list[Element] = []
        self.problems: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        element = Element(tag, list(attrs), self.getpos()[0])
        (self.stack[-1].children if self.stack else self.roots).append(element)
        if tag not in VOID_ELEMENTS:
            self.stack.append(element)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.problems.append(f"self-closing <{tag}/> on line {self.getpos()[0]}")
        element = Element(tag, list(attrs), self.getpos()[0])
        (self.stack[-1].children if self.stack else self.roots).append(element)

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1].tag != tag:
            open_tag = self.stack[-1].tag if self.stack else None
            self.problems.append(
                f"stray </{tag}> on line {self.getpos()[0]} (open: {open_tag!r})"
            )
            return
        self.stack.pop()

    def handle_data(self, data: str) -> None:
        if self.stack:
            self.stack[-1].children.append(data)
        elif data.strip():
            self.problems.append(
                f"text outside the root on line {self.getpos()[0]}: {data!r}"
            )

    def handle_comment(self, data: str) -> None:
        self.problems.append(f"a comment on line {self.getpos()[0]}")

    def handle_decl(self, decl: str) -> None:
        self.problems.append(f"a declaration on line {self.getpos()[0]}: {decl!r}")

    def handle_pi(self, data: str) -> None:
        self.problems.append(f"a processing instruction on line {self.getpos()[0]}")

    def unknown_decl(self, data: str) -> None:
        self.problems.append(f"an unknown declaration on line {self.getpos()[0]}")


def parse(fragment: str) -> Element:
    """Parse a fragment into its one root element, or raise `FragmentError` (F1)."""
    builder = _TreeBuilder()
    builder.feed(fragment)
    builder.close()
    problems = list(builder.problems)
    if builder.stack:
        problems.append(
            "unclosed: " + ", ".join(element.where() for element in builder.stack)
        )
    if len(builder.roots) != 1:
        problems.append(f"{len(builder.roots)} root elements, not one")
    if problems:
        raise FragmentError("the fragment is not well formed: " + "; ".join(problems))
    return builder.roots[0]


# --------------------------------------------------------------------------
# F1: well formed, one root with its three attributes.
# --------------------------------------------------------------------------

ROOT_ATTRIBUTES: Final[tuple[str, ...]] = (
    "class",
    "data-redlines-view",
    "data-redlines-fragment",
    "data-redlines-schema",
)


def check_well_formed(fragment: str, *, view: str | None = None) -> Element:
    """F1: the fragment parses to one ``<section class="redlines">`` root.

    :param fragment: the markup.
    :param view: ``"changes"`` or ``"document"``, if the caller knows which.
    :return: the root element.
    """
    root = parse(fragment)
    if root.tag != "section":
        raise FragmentError(f"the root is {root.where()}, not a <section>")
    if root.names() != list(ROOT_ATTRIBUTES):
        raise FragmentError(
            f"the root's attributes are {root.names()}, not {list(ROOT_ATTRIBUTES)}"
        )
    if root.get("class") != "redlines":
        raise FragmentError(
            f"the root's class is {root.get('class')!r}, not 'redlines'"
        )
    if root.get("data-redlines-view") not in ("changes", "document"):
        raise FragmentError(f"data-redlines-view is {root.get('data-redlines-view')!r}")
    if view is not None and root.get("data-redlines-view") != view:
        raise FragmentError(
            f"data-redlines-view is {root.get('data-redlines-view')!r}, not {view!r}"
        )
    if root.get("data-redlines-fragment") != FRAGMENT_VERSION:
        raise FragmentError(
            f"data-redlines-fragment is {root.get('data-redlines-fragment')!r}"
        )
    if root.get("data-redlines-schema") != SCHEMA_VERSION:
        raise FragmentError(
            f"data-redlines-schema is {root.get('data-redlines-schema')!r}"
        )
    if not fragment.startswith("<section ") or not fragment.endswith("</section>"):
        raise FragmentError("the fragment does not begin and end with its root")
    return root


# --------------------------------------------------------------------------
# F2: self-contained and CSP-safe (contract items 2 and 3).
# --------------------------------------------------------------------------

ALLOWED_ELEMENTS: Final[frozenset[str]] = frozenset(
    {
        "section",
        "style",
        "header",
        "p",
        "span",
        "button",
        "ol",
        "li",
        "details",
        "summary",
        "div",
        "code",
        "ins",
        "del",
        "table",
        "thead",
        "tbody",
        "tr",
        "th",
        "td",
    }
)
FORBIDDEN_ELEMENTS: Final[frozenset[str]] = frozenset(
    {
        "script",
        "link",
        "img",
        "iframe",
        "object",
        "embed",
        "base",
        "meta",
        "form",
        "svg",
        "math",
    }
)
ALLOWED_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"class", "role", "aria-level", "hidden", "type"}
)
URL_ATTRIBUTES: Final[frozenset[str]] = frozenset(
    {"src", "href", "srcset", "action", "formaction"}
)


def check_self_contained(root: Element) -> str:
    """F2: allowed elements and attributes, one leading ``<style>``, no reference out.

    :return: the stylesheet the one ``<style>`` holds.
    """
    for element in root.walk():
        if element.tag in FORBIDDEN_ELEMENTS:
            raise FragmentError(f"a forbidden element: {element.where()}")
        if element.tag not in ALLOWED_ELEMENTS:
            raise FragmentError(f"an element outside the allowlist: {element.where()}")
        names = element.names()
        if len(set(names)) != len(names):
            raise FragmentError(f"a repeated attribute on {element.where()}: {names}")
        for name in names:
            if name.startswith("on"):
                raise FragmentError(f"an inline handler {name!r} on {element.where()}")
            if name == "style":
                raise FragmentError(f"an inline style on {element.where()}")
            if name == "id":
                raise FragmentError(f"an id on {element.where()}")
            if name in URL_ATTRIBUTES:
                raise FragmentError(f"a URL-bearing {name!r} on {element.where()}")
            if name not in ALLOWED_ATTRIBUTES and not re.fullmatch(
                r"data-[a-z0-9-]+", name
            ):
                raise FragmentError(
                    f"an attribute outside the allowlist: {name!r} on {element.where()}"
                )
    styles = [element for element in root.walk() if element.tag == "style"]
    if len(styles) != 1:
        raise FragmentError(f"{len(styles)} <style> elements, not one")
    style = styles[0]
    first = root.children[0] if root.children else None
    leading_text = first if isinstance(first, str) else ""
    first_element = root.elements()[0] if root.elements() else None
    if first_element is not style or leading_text.strip():
        raise FragmentError("the <style> is not the root's first child")
    if style.attrs or not all(isinstance(child, str) for child in style.children):
        raise FragmentError("the <style> carries attributes or markup")
    css = style.text()
    lowered = css.lower()
    for banned in ("@import", "url("):
        if banned in lowered:
            raise FragmentError(f"the stylesheet contains {banned!r}")
    return css


def check_hooks(root: Element) -> None:
    """Contract item 8: one hidden fullscreen button, with no handler."""
    buttons = [element for element in root.walk() if element.tag == "button"]
    if len(buttons) != 1:
        raise FragmentError(f"{len(buttons)} buttons, not the one fullscreen hook")
    button = buttons[0]
    expected = [
        ("type", "button"),
        ("class", "redlines-fullscreen"),
        ("data-redlines-action", "fullscreen"),
        ("hidden", None),
    ]
    if button.attrs != expected:
        raise FragmentError(f"the fullscreen button is {button.attrs}, not {expected}")


# --------------------------------------------------------------------------
# F3 and F4: the stylesheet.
# --------------------------------------------------------------------------

STANDARD_VARIABLES: Final[dict[str, str | None]] = {
    "font": "--font-sans",
    "mono": "--font-mono",
    "fg": "--color-text-primary",
    "bg": None,
    "muted": "--color-text-secondary",
    "border": "--color-border-tertiary",
    "ins-fg": "--color-text-success",
    "ins-bg": "--color-background-success",
    "del-fg": "--color-text-danger",
    "del-bg": "--color-background-danger",
    "move-fg": "--color-text-info",
    "warn-fg": "--color-text-warning",
    "radius": "--border-radius-sm",
}
"""ADR-0038's table: each of the thirteen ``--redlines-*`` names and the
standard variable it falls back to (``bg`` falls back to ``transparent``)."""

COLOUR_NAMES: Final[frozenset[str]] = frozenset(
    name for name in STANDARD_VARIABLES if name not in ("font", "mono", "bg", "radius")
)
FONT_NAMES: Final[frozenset[str]] = frozenset({"font", "mono"})

THEMED_PROPERTIES: Final[frozenset[str]] = frozenset(
    {
        "color",
        "background",
        "background-color",
        "outline",
        "fill",
        "stroke",
        "box-shadow",
        "font-family",
    }
)
LAYOUT_BORDER_PROPERTIES: Final[frozenset[str]] = frozenset(
    {"border-collapse", "border-spacing"}
)

_LENGTH = r"(?:0|-?(?:\d+\.?\d*|\.\d+)(?:px|em|rem|%|ch|ex|vw|vh|pt))"
_BORDER_STYLE = r"(?:none|hidden|solid|dashed|dotted|double|groove|ridge|inset|outset)"
_EXTRA_TOKEN: Final[re.Pattern[str]] = re.compile(rf"{_LENGTH}|{_BORDER_STYLE}")
_COLOUR_LITERAL: Final[re.Pattern[str]] = re.compile(
    r"#[0-9a-fA-F]{3,8}(?![0-9a-zA-Z])"
    r"|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color|light-dark)\("
    r"|\b(?:black|white|red|green|blue|yellow|gray|grey|orange|purple|pink|brown)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Rule:
    """One rule of the stylesheet: its selector list and its declarations, in order."""

    selectors: tuple[str, ...]
    declarations: tuple[tuple[str, str], ...]


def _split_top_level(text: str, separator: str) -> list[str]:
    """Split at ``separator`` outside parentheses, brackets and quotes."""
    parts: list[str] = []
    depth = 0
    quote = ""
    start = 0
    for index, character in enumerate(text):
        if quote:
            if character == quote:
                quote = ""
        elif character in "\"'":
            quote = character
        elif character in "([":
            depth += 1
        elif character in ")]":
            depth -= 1
        elif character == separator and depth == 0:
            parts.append(text[start:index])
            start = index + 1
    parts.append(text[start:])
    return parts


def rules(css: str) -> list[Rule]:
    """Parse a flat stylesheet of ``selector{declarations}`` rules, with no at-rule."""
    if "@" in css:
        raise FragmentError("the stylesheet has an at-rule; it is meant to be flat")
    if "/*" in css:
        raise FragmentError("the stylesheet has a comment")
    parsed: list[Rule] = []
    position = 0
    for match in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if css[position : match.start()].strip():
            raise FragmentError(
                f"unparsed stylesheet text: {css[position:match.start()]!r}"
            )
        position = match.end()
        selectors = tuple(
            part.strip() for part in _split_top_level(match.group(1), ",")
        )
        declarations: list[tuple[str, str]] = []
        for declaration in match.group(2).split(";"):
            if not declaration.strip():
                continue
            name, colon, value = declaration.partition(":")
            if not colon:
                raise FragmentError(f"a declaration with no value: {declaration!r}")
            declarations.append((name.strip().lower(), value.strip()))
        parsed.append(Rule(selectors, tuple(declarations)))
    if css[position:].strip():
        raise FragmentError(f"unparsed stylesheet text: {css[position:]!r}")
    if not parsed:
        raise FragmentError("the stylesheet has no rule")
    return parsed


@dataclass(frozen=True)
class _Var:
    start: int
    end: int
    name: str
    fallback: str | None


def _vars(value: str) -> list[_Var]:
    """The top-level ``var(...)`` groups of a value, with their names and fallbacks."""
    found: list[_Var] = []
    index = 0
    while True:
        start = value.find("var(", index)
        if start < 0:
            return found
        depth = 0
        for end in range(start + 3, len(value)):
            if value[end] == "(":
                depth += 1
            elif value[end] == ")":
                depth -= 1
                if depth == 0:
                    break
        else:
            raise FragmentError(f"an unbalanced var() in {value!r}")
        inner = value[start + 4 : end]
        parts = _split_top_level(inner, ",")
        name = parts[0].strip()
        fallback = ",".join(parts[1:]).strip() if len(parts) > 1 else None
        found.append(_Var(start, end + 1, name, fallback))
        index = end + 1


def _themed(name: str) -> bool:
    if name in THEMED_PROPERTIES:
        return True
    return name.startswith("border") and name not in LAYOUT_BORDER_PROPERTIES


def _check_fallback(name: str, fallback: str | None, where: str) -> None:
    if name == "bg":
        if fallback != "transparent":
            raise FragmentError(
                f"--redlines-bg falls back to {fallback!r}, not transparent ({where})"
            )
        return
    standard = STANDARD_VARIABLES[name]
    inner = _vars(fallback or "")
    if len(inner) != 1 or inner[0].start != 0 or inner[0].end != len(fallback or ""):
        raise FragmentError(
            f"--redlines-{name}'s fallback {fallback!r} is not one var() ({where})"
        )
    if inner[0].name != standard:
        raise FragmentError(
            f"--redlines-{name} falls back to {inner[0].name}, not {standard} ({where})"
        )
    own = inner[0].fallback or ""
    if not own or "var(" in own:
        raise FragmentError(f"{standard} has no fallback of its own ({where})")
    if name in COLOUR_NAMES and not re.fullmatch(r"light-dark\([^()]+,[^()]+\)", own):
        raise FragmentError(
            f"{standard}'s own fallback {own!r} is not a light-dark() ({where})"
        )
    if name == "radius" and not re.fullmatch(_LENGTH, own):
        raise FragmentError(
            f"{standard}'s own fallback {own!r} is not a length ({where})"
        )


def check_theme(css: str) -> set[str]:
    """F3: every theme declaration reads one ``var(--redlines-NAME, …)`` (ADR-0038).

    :return: the names used, which equal the thirteen.
    """
    used: set[str] = set()
    for rule in rules(css):
        where = ",".join(rule.selectors)
        for name, value in rule.declarations:
            if name.startswith("--"):
                raise FragmentError(
                    f"the stylesheet declares the custom property {name} ({where})"
                )
            if name == "color-scheme" or "color-scheme" in value:
                raise FragmentError(f"the stylesheet declares color-scheme ({where})")
            groups = _vars(value)
            themed_groups = [
                group for group in groups if group.name.startswith("--redlines-")
            ]
            if len(groups) != len(themed_groups):
                raise FragmentError(
                    f"{name} reads a variable that is not --redlines-* ({where})"
                )
            outside = value
            for group in reversed(groups):
                outside = outside[: group.start] + " " + outside[group.end :]
            if _COLOUR_LITERAL.search(outside):
                raise FragmentError(
                    f"a colour outside var(--redlines-*): {name}:{value} ({where})"
                )
            if not _themed(name):
                if groups:
                    raise FragmentError(
                        f"{name} is not a theme property but reads one ({where})"
                    )
                continue
            if len(groups) != 1:
                raise FragmentError(
                    f"{name}:{value} does not read exactly one var() ({where})"
                )
            group = groups[0]
            theme_name = group.name.removeprefix("--redlines-")
            if theme_name not in STANDARD_VARIABLES:
                raise FragmentError(
                    f"--redlines-{theme_name} is not one of the thirteen ({where})"
                )
            _check_fallback(theme_name, group.fallback, where)
            if name == "font-family" and theme_name not in FONT_NAMES:
                raise FragmentError(
                    f"font-family reads --redlines-{theme_name} ({where})"
                )
            if name != "font-family" and theme_name in FONT_NAMES:
                raise FragmentError(
                    f"{name} reads the font --redlines-{theme_name} ({where})"
                )
            for token in outside.split():
                if not _EXTRA_TOKEN.fullmatch(token):
                    raise FragmentError(
                        f"{name}:{value} has {token!r} beside its var() ({where})"
                    )
            used.add(theme_name)
    if used != set(STANDARD_VARIABLES):
        missing = sorted(set(STANDARD_VARIABLES) - used)
        raise FragmentError(
            f"the stylesheet does not use all thirteen names; missing {missing}"
        )
    return used


_SCOPED: Final[re.Pattern[str]] = re.compile(r"\.redlines(?![\w-])")
_GLOBAL: Final[re.Pattern[str]] = re.compile(
    r":root|(?<![\w.#-])(?:html|body)(?![\w-])"
)


def check_scoped(css: str) -> None:
    """F4: every selector starts with the ``.redlines`` class.

    None names ``:root``, ``html`` or ``body``.
    """
    for rule in rules(css):
        for selector in rule.selectors:
            if not _SCOPED.match(selector):
                raise FragmentError(f"an unscoped selector: {selector!r}")
            bare = re.sub(r"\[[^\]]*\]", "[]", selector)
            if _GLOBAL.search(bare):
                raise FragmentError(f"a selector reaches the page: {selector!r}")


# --------------------------------------------------------------------------
# F5: the rows.
# --------------------------------------------------------------------------

ROW_ATTRIBUTES: Final[tuple[str, ...]] = (
    "class",
    "data-index",
    "data-kind",
    "data-address",
    "data-source-address",
    "data-test-address",
    "data-source-label",
    "data-test-label",
    "data-block-kind",
    "data-role",
    "data-matched-by",
    "data-confidence",
    "data-chars",
    "data-has-inline",
    "data-span-types",
)
"""A row's attributes in ADR-0038's order, ``class`` first."""


def row_elements(root: Element) -> list[Element]:
    """The change list's rows, in document order."""
    return [
        element
        for element in root.walk()
        if element.tag == "li" and "redlines-change" in element.classes()
    ]


def _expected_row_attributes(
    index: int, change: Change
) -> list[tuple[str, str | None]]:
    values: list[tuple[str, str | None]] = [
        ("class", "redlines-change"),
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
        ("data-confidence", repr(round(change.confidence, 4))),
        ("data-chars", str(max(change.chars_added, change.chars_deleted))),
        ("data-has-inline", "true" if change.has_inline else "false"),
        ("data-span-types", " ".join(sorted(change.span_types))),
    ]
    return [(name, value) for name, value in values if value]


def _summary_classes(change: Change) -> list[str]:
    classes = ["redlines-kind"]
    source, test = change.source_label or "", change.test_label or ""
    label = test
    if change.kind is ChangeKind.DELETE:
        label = source
    if change.kind in (ChangeKind.MOVE, ChangeKind.RENUMBER) and source != test:
        label = "x"
    if label:
        classes.append("redlines-label")
    classes.append("redlines-excerpt")
    if change.breadcrumb:
        classes.append("redlines-breadcrumb")
    if change.role:
        classes.append("redlines-role")
    classes.extend(["redlines-address", "redlines-match"])
    return classes


def _excerpt(text: str) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= 80:
        return collapsed
    cut = collapsed.rfind(" ", 0, 81)
    return (collapsed[:cut] if cut > 0 else collapsed[:80]) + "…"


def check_rows(root: Element, comparison: Comparison) -> list[Element]:
    """F5: one row per change, in order, its attributes in order and its node's.

    :return: the rows.
    """
    rows = row_elements(root)
    changes = list(comparison.changes)
    if len(rows) != len(changes):
        raise FragmentError(f"{len(rows)} rows for {len(changes)} changes")
    lists = [element for element in root.walk() if element.tag == "ol"]
    empty = [
        element for element in root.walk() if "redlines-empty" in element.classes()
    ]
    if changes and (len(lists) != 1 or empty):
        raise FragmentError(
            "a change list with changes has one <ol> and no 'No changes.'"
        )
    if not changes and (lists or len(empty) != 1 or empty[0].text() != "No changes."):
        raise FragmentError(
            "a change list with no changes says 'No changes.' instead of a list"
        )
    for index, (row, change) in enumerate(zip(rows, changes)):
        where = f"row {index}"
        names = row.names()
        if names != [name for name in ROW_ATTRIBUTES if name in names]:
            raise FragmentError(f"{where}: attributes out of order: {names}")
        expected = _expected_row_attributes(index, change)
        if row.attrs != expected:
            raise FragmentError(f"{where}: attributes {row.attrs}, not {expected}")
        if row.get("data-kind") not in CHANGE_KINDS:
            raise FragmentError(f"{where}: data-kind {row.get('data-kind')!r}")
        if not (row.get("data-address") or "").startswith("/"):
            raise FragmentError(f"{where}: data-address {row.get('data-address')!r}")
        kind = row.get("data-kind")
        if (row.get("data-source-address") is None) != (kind == "insert"):
            raise FragmentError(f"{where}: data-source-address against kind {kind}")
        if (row.get("data-test-address") is None) != (kind == "delete"):
            raise FragmentError(f"{where}: data-test-address against kind {kind}")
        if row.get("data-matched-by") not in (*PASS_NAMES, UNMATCHED):
            raise FragmentError(
                f"{where}: data-matched-by {row.get('data-matched-by')!r}"
            )
        if row.get("data-confidence") != repr(round(change.confidence, 4)):
            raise FragmentError(
                f"{where}: data-confidence {row.get('data-confidence')!r}"
            )
        if row.get("data-has-inline") not in ("true", "false"):
            raise FragmentError(
                f"{where}: data-has-inline {row.get('data-has-inline')!r}"
            )
        _check_row_shape(row, change, where)
    return rows


def _check_row_shape(row: Element, change: Change, where: str) -> None:
    if any(isinstance(child, str) for child in row.children):
        raise FragmentError(f"{where}: text directly inside the row")
    details = row.elements()
    if [element.tag for element in details] != ["details"] or details[0].attrs:
        raise FragmentError(f"{where}: the row is not one bare <details>")
    parts = details[0].children
    if [getattr(part, "tag", None) for part in parts] != ["summary", "div"]:
        raise FragmentError(f"{where}: <details> does not hold a <summary> and a <div>")
    summary, body = details[0].elements()
    if body.attrs != [("class", "redlines-inline")]:
        raise FragmentError(f"{where}: the body is {body.attrs}")
    if any(isinstance(child, str) for child in summary.children):
        raise FragmentError(f"{where}: whitespace or text between the summary's spans")
    classes = [
        element.classes()[0] if element.classes() else ""
        for element in summary.elements()
    ]
    if classes != _summary_classes(change):
        raise FragmentError(
            f"{where}: summary spans {classes}, not {_summary_classes(change)}"
        )
    spans = dict(zip(classes, summary.elements()))
    if spans["redlines-kind"].text() != change.kind.value:
        raise FragmentError(
            f"{where}: the kind reads {spans['redlines-kind'].text()!r}"
        )
    if spans["redlines-address"].tag != "code":
        raise FragmentError(f"{where}: the address is not a <code>")
    address = (
        f"{change.source_address} → {change.test_address}"
        if change.kind is ChangeKind.MOVE
        else change.test_address or change.source_address
    )
    if spans["redlines-address"].text() != address:
        raise FragmentError(
            f"{where}: the address reads {spans['redlines-address'].text()!r}"
        )
    match = f"{change.matched_by} {repr(round(change.confidence, 4))}"
    if spans["redlines-match"].text() != match:
        raise FragmentError(
            f"{where}: the match reads {spans['redlines-match'].text()!r}"
        )
    if change.breadcrumb and spans["redlines-breadcrumb"].text() != " › ".join(
        change.breadcrumb
    ):
        raise FragmentError(
            f"{where}: the breadcrumb reads {spans['redlines-breadcrumb'].text()!r}"
        )
    if change.role and spans["redlines-role"].text() != change.role:
        raise FragmentError(
            f"{where}: the role reads {spans['redlines-role'].text()!r}"
        )
    own = change.source_text if change.kind is ChangeKind.DELETE else change.test_text
    if own and spans["redlines-excerpt"].text() != _excerpt(own):
        raise FragmentError(
            f"{where}: the excerpt reads {spans['redlines-excerpt'].text()!r}"
        )


# --------------------------------------------------------------------------
# F6: filter parity.
# --------------------------------------------------------------------------


def _prefix_matches(address: str | None, prefix: str) -> bool:
    """Whether ``address`` is ``prefix`` or under it, segment-aligned (ADR-0033).

    ``/`` matches every address, and ``None`` none.
    """
    if address is None:
        return False
    if prefix == "/":
        return True
    return address == prefix or address.startswith(prefix.rstrip("/") + "/")


def select_rows(rows: Sequence[Element], spec: ChangeFilter) -> list[int]:
    """The ``data-index`` of every row a filter keeps, from the attributes alone."""
    kinds = {kind.value for kind in spec.kinds}
    selected: list[int] = []
    for row in rows:
        if kinds and row.get("data-kind") not in kinds:
            continue
        if spec.address_prefixes and not any(
            _prefix_matches(row.get(name), prefix)
            for prefix in spec.address_prefixes
            for name in ("data-source-address", "data-test-address")
        ):
            continue
        if spec.labels and not (
            row.get("data-source-label") in spec.labels
            or row.get("data-test-label") in spec.labels
        ):
            continue
        if spec.roles and row.get("data-role") not in spec.roles:
            continue
        if spec.min_chars and int(row.get("data-chars") or "0") < spec.min_chars:
            continue
        if spec.has_inline is not None and row.get("data-has-inline") != (
            "true" if spec.has_inline else "false"
        ):
            continue
        selected.append(int(row.get("data-index") or "-1"))
    return selected


def filter_battery(comparison: Comparison) -> list[ChangeFilter]:
    """Filters on every field and some combinations, from the comparison's values."""
    changes = list(comparison.changes)
    battery: list[ChangeFilter] = [ChangeFilter()]
    battery.extend(ChangeFilter(kinds=(ChangeKind(kind),)) for kind in CHANGE_KINDS)
    battery.append(ChangeFilter(kinds=(ChangeKind.INSERT, ChangeKind.DELETE)))
    roles = sorted({change.role for change in changes if change.role})
    battery.extend(ChangeFilter(roles=(role,)) for role in roles)
    battery.append(ChangeFilter(roles=("no-such-role",)))
    labels = sorted(
        {
            label
            for change in changes
            for label in (change.source_label, change.test_label)
            if label
        }
    )
    battery.extend(ChangeFilter(labels=(label,)) for label in labels[:8])
    prefixes: set[str] = {
        "/",
        "/section[1]",
        "/section[1]/",
        "/section[1",
        "/no-such[1]",
    }
    for change in changes:
        for address in (change.source_address, change.test_address):
            if address:
                segments = address.split("/")
                prefixes.add("/".join(segments[:2]))
                prefixes.add("/".join(segments[:-1]) or "/")
                prefixes.add(address)
    battery.extend(
        ChangeFilter(address_prefixes=(prefix,)) for prefix in sorted(prefixes)
    )
    battery.extend(
        ChangeFilter(min_chars=chars) for chars in (1, 2, 5, 10, 20, 50, 100, 10_000)
    )
    battery.extend(ChangeFilter(has_inline=value) for value in (True, False))
    battery.append(ChangeFilter(kinds=(ChangeKind.MODIFY,), min_chars=5))
    battery.append(ChangeFilter(address_prefixes=("/section[1]",), has_inline=False))
    battery.append(
        ChangeFilter(
            roles=tuple(roles[:2]), kinds=(ChangeKind.INSERT, ChangeKind.MODIFY)
        )
    )
    battery.append(ChangeFilter(labels=tuple(labels[:3]), has_inline=True))
    return battery


def check_filter_parity(
    root: Element, comparison: Comparison, specs: Iterable[ChangeFilter] | None = None
) -> int:
    """F6: per filter, the rows the attributes select are those filter_changes keeps.

    :return: how many filters were checked.
    """
    rows = row_elements(root)
    changes = list(comparison.changes)
    checked = 0
    for spec in filter_battery(comparison) if specs is None else specs:
        kept = list(filter_changes(comparison.changes, spec))
        expected = [
            index
            for index, change in enumerate(changes)
            if any(change is k for k in kept)
        ]
        actual = select_rows(rows, spec)
        if actual != expected:
            raise FragmentError(
                f"filter parity fails for {spec}: rows {actual}, nodes {expected}"
            )
        checked += 1
    return checked


# --------------------------------------------------------------------------
# F7: the text a reader sees is the documents' text.
# --------------------------------------------------------------------------


def _side_text(element: Element, side: str, *, skip: frozenset[str]) -> str:
    """The text one side of an element reads, ``textContent`` with marks resolved.

    ``side`` is ``"accept"`` (drop ``<del>``) or ``"reject"`` (drop ``<ins>``).
    An element with a class in ``skip`` is left out with one space next to it:
    the one after it if there is one, else the one before it.
    """
    dropped = "del" if side == "accept" else "ins"
    out: list[str] = []
    eat_space = False

    def visit(node: Element) -> None:
        nonlocal eat_space
        for child in node.children:
            if isinstance(child, str):
                text = child
                if eat_space and text.startswith(" "):
                    text = text[1:]
                eat_space = False
                out.append(text)
                continue
            if child.tag == dropped:
                continue
            if skip & set(child.classes()):
                eat_space = True
                if out and out[-1].endswith(" ") and _followed_by_nothing(node, child):
                    out[-1] = out[-1][:-1]
                    eat_space = False
                continue
            visit(child)

    visit(element)
    return "".join(out)


def _followed_by_nothing(parent: Element, child: Element) -> bool:
    """Whether ``child`` ends ``parent``, so the space before it is its own."""
    index = next(i for i, node in enumerate(parent.children) if node is child)
    return all(
        isinstance(node, str) and not node for node in parent.children[index + 1 :]
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


def _blocks(tree: BlockTree) -> dict[str, Block]:
    return {block.path: block for block in tree.walk()}


def subtree_lines(comparison: Comparison, change: Change) -> list[str]:
    """What an insert's or a delete's body reads, from the trees and the alignment.

    One line per text-bearing block with a label or text, a row as its
    cells' texts joined by `` | ``, and a block that is matched (it moved in
    or out) left out with its subtree. The labels are not part of a line:
    the check leaves out the label spans.
    """
    alignment = comparison.alignment
    if change.kind is ChangeKind.INSERT:
        start = _blocks(comparison.test)[change.test_address or ""]

        def keep(block: Block) -> bool:
            return alignment.source_for(block.path) is None

    else:
        start = _blocks(comparison.source)[change.source_address or ""]
        deleted = set(alignment.deleted)

        def keep(block: Block) -> bool:
            return block.path in deleted

    lines: list[str] = []

    def visit(block: Block) -> None:
        if block.kind is BlockKind.ROW:
            lines.append(" | ".join(cell.text for cell in block.children if keep(cell)))
            return
        if block.kind in _TEXT_BEARING and (block.text or block.label):
            lines.append(block.text)
        for child in block.children:
            if keep(child):
                visit(child)

    visit(start)
    return lines


def _loose(text: str) -> str:
    """The text with every whitespace character removed: ADR-0037's loose comparison."""
    return "".join(text.split())


def check_row_texts(root: Element, comparison: Comparison) -> None:
    """F7: each row's body, parsed, reads its node's text on both sides.

    A node with inline ops reads its test text exactly on the accept side,
    and its source text on the reject side up to whitespace: the splice
    writes each unchanged run from the test side, and the differ does not
    compare whitespace, so a run can carry the test's spacing at an edit
    (ADR-0037's loose comparison, the same claim reject-all makes). A node
    without ops reads its test text, after the label span of a move's or a
    renumber's label change. An insert or a delete reads its subtree, line by
    line, in one ``<ins>`` or ``<del>``.
    """
    labels = frozenset({"redlines-label"})
    for index, (row, change) in enumerate(zip(row_elements(root), comparison.changes)):
        where = f"row {index}"
        body = row.elements()[0].elements()[1]
        if change.kind in (ChangeKind.INSERT, ChangeKind.DELETE):
            tag = "ins" if change.kind is ChangeKind.INSERT else "del"
            marks = body.elements()
            if len(marks) != 1 or marks[0].tag != tag or len(body.children) != 1:
                raise FragmentError(f"{where}: the body is not one <{tag}>")
            side = "accept" if tag == "ins" else "reject"
            read = _side_text(marks[0], side, skip=labels).split("\n")
            if read != subtree_lines(comparison, change):
                raise FragmentError(
                    f"{where}: the body reads {read!r}, "
                    f"not {subtree_lines(comparison, change)!r}"
                )
            continue
        accepted = _side_text(body, "accept", skip=labels)
        if accepted != change.test_text:
            raise FragmentError(
                f"{where}: accept reads {accepted!r}, not {change.test_text!r}"
            )
        if change.inline:
            rejected = _side_text(body, "reject", skip=labels)
            if _loose(rejected) != _loose(change.source_text):
                raise FragmentError(
                    f"{where}: reject reads {rejected!r}, not {change.source_text!r}"
                )


def check_block_texts(root: Element, comparison: Comparison) -> None:
    """F7 for the document view: blocks read their blocks' texts, tables their cells.

    A block in the test document reads its test text on the accept side; a
    deleted one reads its source text on the reject side; role spans, label
    spans and notes are left out. A table's rows, on the accept side, are the
    test table's rows (rows of deleted cells dropped), and a deleted table's
    on the reject side are the source table's.
    """
    test, source = _blocks(comparison.test), _blocks(comparison.source)
    skip = frozenset({"redlines-role", "redlines-label", "redlines-note"})
    document = [
        element for element in root.walk() if "redlines-document" in element.classes()
    ]
    if len(document) != 1:
        raise FragmentError("the document view has no single redlines-document")
    for element in document[0].elements():
        where = element.where()
        if element.tag == "p" and "redlines-note" in element.classes():
            if element.get("data-kind") != "move" or element.elements():
                raise FragmentError(f"{where}: a note is a plain move note")
            continue
        test_address = element.get("data-test-address")
        source_address = element.get("data-source-address")
        if element.tag == "table":
            _check_table_text(
                element, test, source, test_address, source_address, where
            )
            continue
        if element.tag != "p" or "redlines-block" not in element.classes():
            raise FragmentError(f"{where}: not a block, a table or a note")
        if test_address is not None:
            block = test[test_address]
            read = _side_text(element, "accept", skip=skip)
        else:
            if element.get("data-kind") != "delete" or source_address is None:
                raise FragmentError(
                    f"{where}: a block with no test address is not a ghost"
                )
            block = source[source_address]
            read = _side_text(element, "reject", skip=skip)
        if read != block.text:
            raise FragmentError(f"{where}: reads {read!r}, not {block.text!r}")
        heading = element.get("role") == "heading"
        if heading != (block.kind is BlockKind.HEADING):
            raise FragmentError(f"{where}: role=heading on a {block.kind.value}")
        if heading and element.get("aria-level") not in {
            str(level) for level in range(1, 7)
        }:
            raise FragmentError(f"{where}: aria-level {element.get('aria-level')!r}")


def _cells(row: Element, side: str) -> list[str] | None:
    """A row's cell texts on one side, or ``None`` when the side drops every cell."""
    dropped = "del" if side == "accept" else "ins"
    cells = row.elements()
    if all(
        cell.elements()
        and all(mark.tag == dropped for mark in cell.elements())
        and not any(isinstance(child, str) and child for child in cell.children)
        for cell in cells
    ):
        return None
    return [_side_text(cell, side, skip=frozenset()) for cell in cells]


def _check_table_text(
    table: Element,
    test: dict[str, Block],
    source: dict[str, Block],
    test_address: str | None,
    source_address: str | None,
    where: str,
) -> None:
    rows = [row for part in table.elements() for row in part.elements()]
    if test_address is not None:
        block, side = test[test_address], "accept"
    elif source_address is not None:
        block, side = source[source_address], "reject"
    else:
        raise FragmentError(f"{where}: a table with no address")
    read = [cells for cells in (_cells(row, side) for row in rows) if cells is not None]
    expected = [[cell.text for cell in row.children] for row in block.children]
    if read != expected:
        raise FragmentError(f"{where}: rows read {read!r}, not {expected!r}")
    parts = [part.tag for part in table.elements()]
    if parts not in (["thead"], ["thead", "tbody"]):
        raise FragmentError(f"{where}: table parts {parts}")
    header_cells = {cell.tag for cell in table.elements()[0].elements()[0].elements()}
    if header_cells - {"th"}:
        raise FragmentError(f"{where}: the header row is not <th> cells")


# --------------------------------------------------------------------------
# F8: the header.
# --------------------------------------------------------------------------

_COUNT_KEYS: Final[tuple[tuple[str, str, str], ...]] = (
    ("insert", "inserted", "inserted"),
    ("delete", "deleted", "deleted"),
    ("modify", "modified", "modified"),
    ("move", "moved", "moved"),
    ("renumber", "renumbered", "renumbered"),
)


def _filter_fields(spec: ChangeFilter) -> list[str]:
    fields: list[str] = []
    for name, value in spec.to_dict().items():
        if isinstance(value, bool):
            fields.append(f"{name}={'true' if value else 'false'}")
        elif isinstance(value, int) and value:
            fields.append(f"{name}={value}")
        elif isinstance(value, list) and value:
            fields.append(f"{name}={','.join(str(item) for item in value)}")
    return fields


def check_header(root: Element, comparison: Comparison) -> None:
    """F8: the counts, configuration and structure lines, and notices, in order."""
    headers = [element for element in root.walk() if element.tag == "header"]
    if len(headers) != 1 or headers[0].attrs != [("class", "redlines-header")]:
        raise FragmentError('not one <header class="redlines-header">')
    header = headers[0]
    parts = header.elements()
    statistics = comparison.statistics()
    counts = statistics.counts
    paragraphs = [part for part in parts if part.tag == "p"]
    if [part.tag for part in parts] != ["p"] * len(paragraphs) + ["button"]:
        raise FragmentError("the header is paragraphs and then the fullscreen button")
    count_line, config_line, structure_line, *notices = paragraphs
    spans = count_line.elements()
    keys = [span.get("data-count") for span in spans]
    if count_line.attrs != [("class", "redlines-counts")] or keys != [
        "total",
        *(key for key, _, _ in _COUNT_KEYS),
    ]:
        raise FragmentError(f"the counts line has {keys}")
    total = "1 change" if counts.total == 1 else f"{counts.total} changes"
    expected = [total] + [
        f"{getattr(counts, attribute)} {word}" for _, attribute, word in _COUNT_KEYS
    ]
    if [span.text() for span in spans] != expected:
        raise FragmentError(
            f"the counts read {[span.text() for span in spans]}, not {expected}"
        )
    config = comparison.config
    configured = (
        f"{config.test_format} · profile {config.profile or 'none'}"
        f" · similarity {config.similarity}"
    )
    if (
        config_line.attrs != [("class", "redlines-config")]
        or config_line.text() != configured
    ):
        raise FragmentError(f"the configuration line reads {config_line.text()!r}")
    structure = (
        f"{comparison.source.fallback_count} of {statistics.source_blocks}"
        " source blocks and "
        f"{comparison.test.fallback_count} of {statistics.test_blocks}"
        " test blocks matched no rule"
    )
    if (
        structure_line.attrs != [("class", "redlines-structure")]
        or structure_line.text() != structure
    ):
        raise FragmentError(f"the structure line reads {structure_line.text()!r}")
    wanted: list[tuple[list[tuple[str, str | None]], str]] = []
    if config.filter is not None and _filter_fields(config.filter):
        wanted.append(
            (
                [("class", "redlines-notice"), ("data-notice", "filtered")],
                "Filtered: " + "; ".join(_filter_fields(config.filter)),
            )
        )
    if config.budget_exhausted:
        wanted.append(
            (
                [("class", "redlines-notice"), ("data-notice", "budget-exhausted")],
                "Alignment stopped early: the comparison budget ran out",
            )
        )
    for side, tree in (("source", comparison.source), ("test", comparison.test)):
        for dropped in tree.dropped:
            wanted.append(
                (
                    [
                        ("class", "redlines-notice"),
                        ("data-notice", "dropped"),
                        ("data-side", side),
                    ],
                    f"{dropped.count} {dropped.kind} dropped from the {side}: "
                    f"{dropped.reason}",
                )
            )
    found = [(notice.attrs, notice.text()) for notice in notices]
    if found != wanted:
        raise FragmentError(f"the notices are {found}, not {wanted}")


# --------------------------------------------------------------------------
# F9: determinism.
# --------------------------------------------------------------------------


def check_deterministic(
    render: Callable[[Comparison], str], comparison: Comparison
) -> str:
    """F9: two renders are byte-equal, and so is one of the comparison from its JSON.

    :return: the rendering.
    """
    first = render(comparison)
    if render(comparison) != first:
        raise FragmentError("two renders of one comparison differ")
    rebuilt = Comparison.from_dict(comparison.to_dict(include_alignment=True))
    if render(rebuilt) != first:
        raise FragmentError(
            "the comparison rebuilt with from_dict renders different bytes"
        )
    return first


# --------------------------------------------------------------------------
# Everything at once.
# --------------------------------------------------------------------------


def check_change_list(fragment: str, comparison: Comparison) -> Element:
    """F1 to F5, F7 and F8 on a change list fragment (F6 and F9 take more arguments).

    :return: the root element.
    """
    root = check_well_formed(fragment, view="changes")
    css = check_self_contained(root)
    check_hooks(root)
    check_theme(css)
    check_scoped(css)
    check_rows(root, comparison)
    check_row_texts(root, comparison)
    check_header(root, comparison)
    return root


def check_document(
    fragment: str, comparison: Comparison, *, roles: bool = True
) -> Element:
    """F1 to F4, F7 and F8 on a document view fragment, and its block rules.

    :return: the root element.
    """
    root = check_well_formed(fragment, view="document")
    css = check_self_contained(root)
    check_hooks(root)
    check_theme(css)
    check_scoped(css)
    check_header(root, comparison)
    check_block_texts(root, comparison)
    if not roles and any(
        "redlines-role" in element.classes() for element in root.walk()
    ):
        raise FragmentError("roles=False and a role span")
    return root
