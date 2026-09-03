"""Work out what format a document is, and say so plainly (R8b).

`detect_format` looks at the file extension first and at the content only
when the extension does not settle it. It never guesses: a type redlines does
not read comes back as ``format=None`` with a reason that names what it saw
and, for the formats that are coming, when they are coming.

    >>> from redlines.readers.detect import detect_format
    >>> detect_format(path="agreement.md").format
    'markdown'
    >>> detect_format(path="agreement.docx").format is None
    True
    >>> detect_format(path="agreement.docx").reason
    "the '.docx' extension is a DOCX file, which redlines 1.0 does not read; coming in 1.1"

The extension map is a registry, not a constant: a reader shipped later (or by
someone else) calls `register_extension` to claim its own suffixes, the same
way it calls `redlines.readers.register_reader` to claim its format name.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "FormatDetection",
    "detect_format",
    "known_extensions",
    "register_extension",
]

_EXTENSIONS: dict[str, str] = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
}

_COMING_IN_1_1: dict[str, str] = {
    ".docx": "DOCX",
    ".doc": "Word",
    ".pdf": "PDF",
    ".html": "HTML",
    ".htm": "HTML",
}

# Content signatures worth naming, so a binary file gets a useful answer
# rather than "not text".
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"%PDF-", "a PDF file, which redlines 1.0 does not read; coming in 1.1"),
    (
        b"PK\x03\x04",
        "a ZIP archive, which is what a DOCX file looks like; coming in 1.1",
    ),
    (b"\xd0\xcf\x11\xe0", "an old binary Office file, which redlines does not read"),
)

_MARKDOWN_SIGNALS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^#{1,6} \S", re.MULTILINE), "an ATX heading"),
    (re.compile(r"^```", re.MULTILINE), "a fenced code block"),
    (re.compile(r"^\s{0,3}[-*+] \S", re.MULTILINE), "a bullet list"),
    (re.compile(r"^\s{0,3}>\s", re.MULTILINE), "a block quote"),
    (re.compile(r"^\|.*\|\s*$", re.MULTILINE), "a pipe table row"),
    (re.compile(r"\[[^\]\n]+\]\([^)\s]+\)"), "an inline link"),
)


@dataclass(frozen=True, slots=True)
class FormatDetection:
    """What `detect_format` concluded, and why.

    :param format: the format name to hand to
        `redlines.readers.reader_for`, or ``None`` when nothing could be
        concluded. ``None`` is a real answer, not a failure -- it means the
        caller should tell the user what it saw rather than parse anyway.
    :param reason: one sentence naming the evidence, fit to show a user. Every
        result has one, including the successful ones.
    """

    format: str | None
    reason: str


def register_extension(extension: str, fmt: str, *, replace: bool = False) -> None:
    """Claim a file extension for a format.

    Claiming an extension another format already holds is an error, for the
    same reason `redlines.readers.register_reader` refuses an unflagged
    reclaim: two readers quietly fighting over ``.md`` is a bug that only
    shows up in the output. Re-claiming an extension for the format that
    already holds it is a no-op, so importing a reader module twice is safe.

    :param extension: the suffix, with its dot (``".rst"``). Case is ignored.
    :param fmt: the format name a reader is registered under.
    :param replace: when true, take over an extension another format already
        claims.
    :raises ValueError: if the extension does not start with a dot, or is
        already claimed by a different format and ``replace`` is false.
    """
    if not extension.startswith("."):
        raise ValueError(f"an extension starts with a dot, got {extension!r}")
    key = extension.lower()
    held_by = _EXTENSIONS.get(key)
    if held_by is not None and held_by != fmt and not replace:
        raise ValueError(
            f"extension {key!r} is already claimed by {held_by!r}; "
            "pass replace=True to take it over"
        )
    _EXTENSIONS[key] = fmt


def known_extensions() -> dict[str, str]:
    """Return every extension that maps to a format.

    :return: a new dict of extension to format name, sorted by extension so
        iteration is deterministic.
    """
    return {ext: _EXTENSIONS[ext] for ext in sorted(_EXTENSIONS)}


def detect_format(
    *, path: str | Path | None = None, text: str | bytes | None = None
) -> FormatDetection:
    """Decide which format a document is (R8b).

    Extension first: a suffix a reader has claimed settles the question, and
    a suffix belonging to a format that is coming later is reported as that
    format's absence. Content sniffing runs only when the extension does not
    settle it -- no extension at all, or one nobody claims -- so a ``.txt``
    file full of markdown is still text, which is what its name says it is.

    :param path: the document's path or file name. Only the suffix is read;
        the file is never opened.
    :param text: the document's content, as text or as bytes. Bytes that are
        not UTF-8, or text containing a NUL, are reported as binary.
    :return: a `FormatDetection`. ``format`` is ``None`` whenever the answer
        would be a guess.
    :raises ValueError: if neither ``path`` nor ``text`` is given -- there is
        nothing to detect from, and that is a caller error rather than an
        undetectable document.
    """
    if path is None and text is None:
        raise ValueError("detect_format needs a path, some text, or both")

    suffix = Path(path).suffix.lower() if path is not None else ""

    if suffix:
        claimed = _EXTENSIONS.get(suffix)
        if claimed is not None:
            return FormatDetection(claimed, f"the {suffix!r} extension names {claimed}")
        coming = _COMING_IN_1_1.get(suffix)
        if coming is not None:
            return FormatDetection(
                None,
                f"the {suffix!r} extension is a {coming} file, which redlines "
                "1.0 does not read; coming in 1.1",
            )

    if text is None:
        if suffix:
            return FormatDetection(
                None,
                f"no reader claims the {suffix!r} extension, and there is no "
                "content to look at",
            )
        return FormatDetection(
            None, "the name has no extension, and there is no content to look at"
        )

    return _sniff(text, suffix=suffix)


def _sniff(text: str | bytes, *, suffix: str) -> FormatDetection:
    """Detect from content alone. ``suffix`` only colours the reason."""
    preamble = (
        f"no reader claims the {suffix!r} extension, so the content decides: "
        if suffix
        else "the name has no usable extension, so the content decides: "
    )

    if isinstance(text, (bytes, bytearray)):
        raw = bytes(text)
        for magic, description in _MAGIC:
            if raw.startswith(magic):
                return FormatDetection(None, f"{preamble}the content is {description}")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError:
            return FormatDetection(
                None,
                f"{preamble}the content is not UTF-8 text, so it is binary of "
                "some kind redlines cannot read",
            )
    else:
        content = text

    if "\x00" in content:
        return FormatDetection(
            None,
            f"{preamble}the content contains a NUL byte, so it is binary of "
            "some kind redlines cannot read",
        )

    if not content.strip():
        return FormatDetection(
            None, f"{preamble}the content is empty, so there is nothing to detect"
        )

    for pattern, description in _MARKDOWN_SIGNALS:
        if pattern.search(content):
            return FormatDetection(
                "markdown", f"{preamble}the content has {description}"
            )

    return FormatDetection(
        "text", f"{preamble}the content is readable text with no markdown syntax"
    )
