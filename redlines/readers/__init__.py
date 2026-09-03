"""Readers: anything that turns a source document into a `BlockTree` (R7).

A reader is not a base class to inherit from. It is a `Reader` -- a
`typing.Protocol` with a name, the formats it claims, and a ``read`` method --
so a third party can contribute a reader for HTML, DOCX, Akoma Ntoso or a
house format without importing anything from redlines except the block model
and this registry. ``examples/custom_reader.py`` is a worked one, run by the
test suite.

Registering and finding a reader::

    from redlines.readers import reader_for, readers, register_reader

    register_reader(MyReader())        # claims every format in MyReader.formats
    reader = reader_for("text")        # -> the reader registered for "text"
    sorted(readers())                  # -> every format name, in order

Which format a source *is* is a separate question, answered by
`redlines.readers.detect.detect_format`, which never guesses.

**Size cap (ADR-0028).** A profile is trusted input whose patterns are
regular expressions run against document text, and a valid pattern can take
time exponential in the length of that text. Readers cannot bound a match
once it starts, so they bound the text instead: every reader here takes a
``max_chars`` keyword defaulting to `DEFAULT_MAX_CHARS` and raises `ValueError`
above it. `check_size` is that check, shared so every reader words it the same
way.
"""

from __future__ import annotations

import re
from typing import Protocol, runtime_checkable

from ..blocks import (
    MATCHED_BY_DOCUMENT,
    MATCHED_BY_FALLBACK,
    Block,
    BlockKind,
    BlockTree,
)
from ..profiles import Profile

__all__ = [
    "DEFAULT_MAX_CHARS",
    "ParagraphReader",
    "Reader",
    "check_size",
    "decode_source",
    "reader_for",
    "readers",
    "register_reader",
    "unregister_reader",
]

DEFAULT_MAX_CHARS = 2_000_000
"""The default input size cap, in characters (ADR-0028).

Two million characters is roughly a thousand pages: comfortably above any
document 1.0 is meant for, and low enough that a pathological profile pattern
fails fast instead of hanging a process.
"""


@runtime_checkable
class Reader(Protocol):
    """The contract a reader satisfies (R7).

    Structural, not nominal: any object with these three members is a
    `Reader`, and `isinstance(obj, Reader)` says so at runtime. There is
    nothing to subclass and nothing to import into your class definition.

    ``name`` and ``formats`` are declared as read-only properties, which is
    how a protocol says "any attribute will do": a plain class attribute
    (``formats = ("text",)``) satisfies them, and does so without having to
    be annotated ``tuple[str, ...]`` to keep a type checker happy.
    """

    @property
    def name(self) -> str:
        """A short, stable name for the reader itself.

        Used in error messages, in the registry listing, and as the family in
        a ``matched_by`` value of the reader's own (ADR-0030).
        """
        ...

    @property
    def formats(self) -> tuple[str, ...]:
        """The format names this reader claims.

        `register_reader` registers the reader under each of them:
        ``("text",)``, ``("markdown",)``, or a name of your own.
        """
        ...

    def read(self, source: str | bytes, *, profile: Profile | None = None) -> BlockTree:
        """Read ``source`` into a `BlockTree`.

        An implementation may add further keyword arguments with defaults --
        every reader here takes ``max_chars`` -- but must work when called
        with these two alone.

        :param source: the document, as text or as UTF-8 bytes.
        :param profile: the structure profile driving detection (ADR-0006).
            ``None`` means the reader's own default behaviour, which for a
            reader that needs a profile to do anything is one block per
            paragraph.
        :return: the document as a tree, with every ``path`` assigned and
            everything the reader dropped reported on it.
        """
        ...


_READERS: dict[str, Reader] = {}


def register_reader(reader: Reader, *, replace: bool = False) -> None:
    """Register ``reader`` for every format it claims.

    :param reader: any object satisfying the `Reader` protocol.
    :param replace: when true, take over formats another reader already
        claims. Registering over an existing format is otherwise an error,
        because two readers silently fighting over ``"markdown"`` is a bug
        that only shows up in the output.
    :raises TypeError: if ``reader`` does not satisfy the protocol.
    :raises ValueError: if it claims no formats, or claims a format already
        registered and ``replace`` is false.
    """
    if not isinstance(reader, Reader):
        raise TypeError(
            f"{reader!r} is not a Reader: it needs a name, formats and read()"
        )
    if not reader.formats:
        raise ValueError(f"reader {reader.name!r} claims no formats")
    for fmt in reader.formats:
        existing = _READERS.get(fmt)
        if existing is not None and not replace:
            raise ValueError(
                f"format {fmt!r} is already read by {existing.name!r}; "
                "pass replace=True to take it over"
            )
    for fmt in reader.formats:
        _READERS[fmt] = reader


def unregister_reader(fmt: str) -> None:
    """Remove whatever reader is registered for ``fmt``, if any.

    Mostly for tests and for a plugin tidying up after itself; unregistering a
    format nobody claims is not an error.

    :param fmt: the format name to free.
    """
    _READERS.pop(fmt, None)


def reader_for(fmt: str) -> Reader:
    """Return the reader registered for ``fmt``.

    :param fmt: a format name, as `detect_format` reports it.
    :return: the registered `Reader`.
    :raises LookupError: if no reader claims that format. The message names
        the formats that are claimed, because the usual cause is a reader
        module that was never imported.
    """
    try:
        return _READERS[fmt]
    except KeyError:
        known = ", ".join(sorted(_READERS)) or "none"
        raise LookupError(
            f"no reader is registered for format {fmt!r}; registered: {known}"
        ) from None


def readers() -> dict[str, Reader]:
    """Return every registered reader, by format name.

    :return: a new dict, sorted by format name so iteration is deterministic
        (N1). Mutating it does not change the registry; use `register_reader`
        and `unregister_reader` for that.
    """
    return {fmt: _READERS[fmt] for fmt in sorted(_READERS)}


def decode_source(source: str | bytes, *, reader: str) -> str:
    """Return ``source`` as text, decoding UTF-8 bytes.

    :param source: the document, as text or as UTF-8 bytes.
    :param reader: the reader's name, for the error message.
    :return: the document as ``str``.
    :raises ValueError: if the bytes are not UTF-8, or ``source`` is neither
        ``str`` nor ``bytes``.
    """
    if isinstance(source, str):
        return source
    if isinstance(source, (bytes, bytearray)):
        try:
            return bytes(source).decode("utf-8")
        except UnicodeDecodeError as error:
            raise ValueError(
                f"{reader}: the source is not UTF-8 text ({error}). "
                "Decode it yourself if it is in another encoding."
            ) from error
    raise TypeError(f"{reader}: expected str or bytes, got {type(source).__name__}")


def check_size(text: str, *, max_chars: int, reader: str) -> None:
    """Raise if ``text`` is longer than ``max_chars`` (ADR-0028).

    The cap is the readers' half of the profile trust boundary: profile
    patterns cannot be proved to terminate, so the text they run against is
    bounded instead.

    :param text: the document text about to be read.
    :param max_chars: the cap, in characters.
    :param reader: the reader's name, for the error message.
    :raises ValueError: if the text is over the cap.
    """
    if len(text) > max_chars:
        raise ValueError(
            f"{reader}: the source is {len(text):,} characters, over the "
            f"{max_chars:,} character limit. Split it, or raise max_chars if "
            "you trust both the document and the profile."
        )


_PARAGRAPH_BREAK = re.compile(r"\n[ \t]*\n")


class ParagraphReader:
    """One block per blank-line-separated paragraph, and nothing else.

    This is ADR-0006's **degrade path**, made concrete and shipped early: when
    no rule matches, a reader falls back to one block per paragraph and
    alignment still works. Every block it produces says so -- ``matched_by``
    is `MATCHED_BY_FALLBACK` and ``confidence`` is ``0.0`` -- so a tree read
    this way is honest about having no structure rather than confidently flat.
    It drops nothing, and it ignores the ``profile`` argument entirely,
    because there is no rule here for a profile to drive.

    **It is a placeholder.** It is registered for the ``"text"`` format so the
    `Reader` protocol and the registry are testable and usable now, in wave A,
    before any real reader exists. The plain-text reader of #102
    (``redlines.readers.text.PlainTextReader``) will register for ``"text"``
    with ``replace=True`` and take its place; what survives is this reader's
    behaviour, as the floor every reader degrades to.
    """

    name = "paragraph"
    formats = ("text",)

    def read(
        self,
        source: str | bytes,
        *,
        profile: Profile | None = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> BlockTree:
        """Split ``source`` into paragraphs and return them as a flat tree.

        Line endings are normalised, the text is split on blank lines, and
        each surviving chunk becomes one ``paragraph`` block whose text has
        its outer whitespace stripped. Interior line breaks are kept as they
        were: re-joining hard-wrapped lines is a judgement call, and this
        reader makes none.

        :param source: the document, as text or as UTF-8 bytes.
        :param profile: accepted and ignored, so this reader is substitutable
            for one that uses it.
        :param max_chars: the input size cap (ADR-0028).
        :return: a ``document`` block of ``paragraph`` children, addressed.
        :raises ValueError: if the source is over ``max_chars`` or is not
            UTF-8.
        """
        text = decode_source(source, reader=self.name)
        check_size(text, max_chars=max_chars, reader=self.name)
        normalised = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [
            chunk.strip()
            for chunk in _PARAGRAPH_BREAK.split(normalised)
            if chunk.strip()
        ]
        root = Block(
            kind=BlockKind.DOCUMENT,
            matched_by=MATCHED_BY_DOCUMENT,
            confidence=1.0,
            attrs={"reader": self.name},
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
        return BlockTree.build(root)


register_reader(ParagraphReader())
