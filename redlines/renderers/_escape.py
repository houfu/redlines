r"""Escaping for CriticMarkup and HTML, and encoding roles (ADR-0037, ADR-0038).

**CriticMarkup defines no escape**, so this is a redlines convention: a
backslash at *delimiter sites*, with a parity rule. It applies to every piece
of document-derived text a renderer copies -- block text, labels, op texts,
cell texts, and the document-derived parts of notes -- and never to the
delimiters or syntax the renderer emits.

There are three sites, each captured together with the run of backslashes
directly before its site character:

- an *opener*: ``{`` followed by ``++``, ``--``, ``~~``, ``==`` or ``>>``;
- a *closer*: ``}`` preceded by ``++``, ``--``, ``~~``, ``==`` or ``<<``, the
  run sitting between the operator and the brace;
- a *separator*: ``>`` preceded by ``~``.

`critic_escape` turns each site's run of *n* backslashes into 2\ *n*\ +1, so
the site is literal; `critic_unescape` turns an odd run 2\ *n*\ +1 back into
*n*. A reader treats a delimiter as live when its run is even, zero included.
The emitter keeps its own delimiters live by doubling the run of backslashes
that ends the text before each one (`double_trailing_backslashes`), and the
reader halves that run again.

A fourth site, the **line start**, exists only when role prefixes are on: a
line whose content begins ``[word] `` would otherwise read as a role prefix,
so `escape_line_start` writes its ``[`` with the same 2\ *n*\ +1 rule.
`SYNTAX_HEAD` is where a reader finds a line's content: after an optional
quote marker and then one ATX heading or list marker.

**Roles never need escaping**, because `encode_role` percent-encodes every
character outside ``A-Z a-z 0-9 _ . -``: an encoded role holds no site, no
``]``, no space and no newline, and the encoding is injective.
``urllib.parse.quote`` is not enough, because it always keeps ``~``.

**HTML** is ``html.escape``: `html_text` for element content and `html_attr`
for a value written inside double quotes.
"""

from __future__ import annotations

import html
import re
from typing import Final

__all__: tuple[str, ...] = (
    "CRITIC_SITE",
    "LINE_START_SITE",
    "SYNTAX_HEAD",
    "critic_escape",
    "critic_unescape",
    "double_trailing_backslashes",
    "escape_line_start",
    "encode_role",
    "html_text",
    "html_attr",
)

CRITIC_SITE: Final[re.Pattern[str]] = re.compile(
    r"(?P<opener>\\*)\{(?=\+\+|--|~~|==|>>)"
    r"|(?<=\+\+|--|~~|==|<<)(?P<closer>\\*)\}"
    r"|(?<=~)(?P<separator>\\*)>"
)
"""The three CriticMarkup delimiter sites, each with the backslash run before
its site character (ADR-0037, "Escaping")."""

_ROLE_CHARACTERS: Final[str] = "A-Za-z0-9_.%-"

LINE_START_SITE: Final[re.Pattern[str]] = re.compile(
    r"(\\*)\[(?=[" + _ROLE_CHARACTERS + r"]+\] )"
)
"""A ``[`` that, with its backslash run, would read as the start of a role
prefix. Matched at a line's content start only, with ``match(text, pos)``."""

SYNTAX_HEAD: Final[re.Pattern[str]] = re.compile(
    r"(?:> )?(?:#{1,6} |(?: {4})*(?:[-*+]|\d+[.)]) )?"
)
"""The syntax head a reader skips before it looks for a role prefix: an
optional quote marker, then one ATX heading or one (indented) list marker.

ADR-0037's reader names the three heads ``#{1,6} ``, ``( {4})*marker `` and
``> ``; a quoted heading or list item carries the quote marker and one of the
other two, so the quote marker may precede either."""

_ROLE_SAFE: Final[frozenset[str]] = frozenset(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_.-"
)


def _site_run(match: re.Match[str]) -> str:
    """The backslash run a `CRITIC_SITE` match captured, whichever site it is."""
    for name in ("opener", "closer", "separator"):
        run = match.group(name)
        if run is not None:
            return run
    raise AssertionError("a site match captures exactly one run")  # pragma: no cover


def critic_escape(text: str) -> str:
    r"""Make every CriticMarkup delimiter site in ``text`` literal.

    Each site's run of *n* backslashes becomes 2\ *n*\ +1, followed by the site
    character. Text with no site is returned unchanged, so ``if (a) { b++ }``
    passes through as it is.

    :param text: document-derived text.
    :return: the text with every site escaped.
    """
    return CRITIC_SITE.sub(
        lambda match: "\\" * (2 * len(_site_run(match)) + 1) + match.group(0)[-1],
        text,
    )


def critic_unescape(text: str) -> str:
    r"""Reverse `critic_escape`: each site's odd run 2\ *n*\ +1 becomes *n*.

    A site whose run is even is a live delimiter, not escaped text, and is left
    as it is; `critic_escape` never produces one.

    :param text: text that `critic_escape` produced.
    :return: the original text.
    """

    def unescape(match: re.Match[str]) -> str:
        run = len(_site_run(match))
        if run % 2 == 0:
            return match.group(0)
        return "\\" * (run // 2) + match.group(0)[-1]

    return CRITIC_SITE.sub(unescape, text)


def double_trailing_backslashes(text: str) -> str:
    r"""Double the run of backslashes that ends ``text``.

    What the emitter does to the text written so far before it writes one of
    its own delimiters, so that the delimiter stays live: a reader halves the
    run again (ADR-0037, the emitter rule).

    :param text: the escaped text written so far.
    :return: the text with its trailing run of *n* backslashes made 2\ *n*.
    """
    run = len(text) - len(text.rstrip("\\"))
    return text + "\\" * run


def escape_line_start(text: str) -> str:
    r"""Escape a role-shaped ``[`` at the very start of ``text``.

    Only meaningful at a line's content start with role prefixes on: the run
    of *n* backslashes before the ``[`` becomes 2\ *n*\ +1. Text that does not
    start like a role prefix is returned unchanged, so ``[link](u) here`` and
    ``[Party A] shall`` pass through.

    :param text: the content at the start of a line.
    :return: the content with its line-start site escaped.
    """
    match = LINE_START_SITE.match(text)
    if match is None:
        return text
    run = len(match.group(1))
    return "\\" * (2 * run + 1) + text[run:]


def encode_role(role: str) -> str:
    """Percent-encode a role for a role prefix (ADR-0037, "Role prefixes").

    Every character outside ``A-Z a-z 0-9 _ . -`` becomes ``%XX`` for each of
    its UTF-8 bytes, in uppercase hexadecimal: ``sub_clause`` stays as it is,
    ``a]b`` becomes ``a%5Db`` and ``r~s`` becomes ``r%7Es``. ``%`` itself is
    encoded, which is what makes the encoding injective;
    ``urllib.parse.unquote`` reverses it.

    :param role: the block's role, any string.
    :return: the encoded role, made only of ``A-Z a-z 0-9 _ . - %``.
    """
    return "".join(
        (
            character
            if character in _ROLE_SAFE
            else "".join(
                f"%{byte:02X}" for byte in character.encode("utf-8", "surrogatepass")
            )
        )
        for character in role
    )


def html_text(text: str) -> str:
    """Escape text for HTML element content: ``&``, ``<`` and ``>``.

    :param text: document-derived text.
    :return: ``html.escape(text, quote=False)``.
    """
    return html.escape(text, quote=False)


def html_attr(text: str) -> str:
    """Escape text for an HTML attribute value written inside double quotes.

    :param text: document-derived text.
    :return: ``html.escape(text, quote=True)``.
    """
    return html.escape(text, quote=True)
