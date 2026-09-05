"""The whole read pipeline in one call: detect, pick a profile, read, interpret.

PRD § 6b describes reading as stages -- work out what the document is, choose
the profile to read it under, run the reader, then run the semantic pass over
the tree that comes out. Each of those is its own function elsewhere in the
package, and composing them by hand is four imports and five lines that every
caller writes the same way. `read_document` is that composition, written once::

    from redlines.pipeline import read_document

    tree = read_document(source, path="agreement.md")   # markdown, `markdown`
    tree = read_document(source, format="text")         # text, `contract`
    tree = read_document(source, format="text", profile="my_profile.yaml")

**Where this lives and why.** Not in `redlines.readers`: a `Reader` produces
structure and never runs semantics, and that contract is worth keeping true --
a reader that quietly assigned roles would make "the tree a reader returned"
mean two different things. Not in `redlines.semantic` either: that module runs
on a tree and knows nothing about readers, and importing them there would
invert the dependency. This module sits above both and is imported by neither.

Nothing here is re-exported from ``redlines/__init__.py``; import it by its
full path, as the examples above do. That is also why M2's compare pipeline --
read both sides, align, build a change tree -- lives in `redlines.comparison`
rather than here. `redlines.comparison.compare` is the headline public API
PRD § 9 describes, imported as ``from redlines import compare``, and a
re-exported function inside a deliberately-not-re-exported module would make
this module half-public (ADR-0033). It calls `read_document` once per side,
which is the composition this module exists to provide.
"""

from __future__ import annotations

import inspect
import os
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol, cast

from .blocks import BlockTree
from .profiles import (
    BUILTIN_PROFILE_NAMES,
    Profile,
    builtin_profile,
    load_profile,
    profile_from_mapping,
)
from .readers import DEFAULT_MAX_CHARS, Reader, check_size, decode_source, reader_for
from .readers.detect import detect_format
from .semantic import apply_semantics

__all__ = [
    "DEFAULT_PROFILES",
    "read_document",
]

DEFAULT_PROFILES: Mapping[str, str] = MappingProxyType(
    {
        "text": "contract",
        "markdown": "markdown",
    }
)
"""Which built-in profile each format is read under when none is named.

A recorded decision, not a convenience: 1.0 ships no profile auto-selection,
so plain text defaults to ``contract`` and markdown to ``markdown``, with an
explicit profile to override (PRD § 6b, "Profiles (D30)"; ROADMAP § 5.2,
accepted 30 August 2026). Auto-selection is 1.1, and when it arrives this
mapping is what it replaces.

A format that is not a key here -- a third party's reader -- has no recorded
default, and `read_document` says so rather than guessing one.
"""


class _ReadWithCap(Protocol):
    """The ``read`` of a reader that accepts the ADR-0028 size cap.

    Every reader in the package takes ``max_chars``, but the `Reader` protocol
    only promises ``source`` and ``profile``, so `read_document` checks for the
    keyword before passing it and enforces the cap itself otherwise.
    """

    def __call__(
        self,
        source: str | bytes,
        *,
        profile: Profile | None = ...,
        max_chars: int = ...,
    ) -> BlockTree: ...


def read_document(
    source: str | bytes,
    *,
    format: str | None = None,
    path: str | os.PathLike[str] | None = None,
    profile: str | Path | Profile | Mapping[str, Any] | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> BlockTree:
    """Read ``source`` into a tree that carries roles and spans (PRD § 6b).

    The four stages, in order: settle the format, settle the profile, run the
    reader registered for that format, and run
    `redlines.semantic.apply_semantics` over what it produced.

    **It always applies semantics.** That is the point of it -- the tree that
    comes back is the one M2 aligns, with roles and spans on it. A caller who
    wants structure alone, with no semantic pass, should skip this function and
    call ``reader_for(fmt).read(source, profile=profile)`` directly; that is
    one line, and it keeps the reader's own contract visible.

    :param source: the document, as text or as UTF-8 bytes.
    :param format: the format name to read it as (``"text"``, ``"markdown"``,
        or any format a reader is registered for). Used as given; when
        ``None``, `redlines.readers.detect.detect_format` decides from ``path``
        and ``source``.
    :param path: the document's path or file name, used only for detection --
        the file is never opened, and passing it alongside an explicit
        ``format`` changes nothing.
    :param profile: the structure profile, in any of the four shapes a caller
        holds one in: a `redlines.profiles.Profile` is used as is; a mapping is
        validated by `redlines.profiles.profile_from_mapping`; a string naming
        a built-in (`redlines.profiles.BUILTIN_PROFILE_NAMES`) is loaded by
        `redlines.profiles.builtin_profile`; anything else -- a path, or YAML
        text -- goes to `redlines.profiles.load_profile`. The built-in names
        are checked *before* the path dispatch, so a file called
        ``contract`` in the working directory can never take over the
        built-in ``contract`` profile. ``None`` means `DEFAULT_PROFILES`.
    :param max_chars: the input size cap (ADR-0028), passed to the reader.
    :return: the document as a `redlines.blocks.BlockTree`, addressed, with
        roles and spans assigned.
    :raises ValueError: if ``format`` is ``None`` and the format cannot be
        detected -- the detection's own reason is quoted, so a ``.docx`` says
        "coming in 1.1" rather than "unsupported"; if ``profile`` is ``None``
        and the format has no recorded default; or if the source is over
        ``max_chars`` or is not UTF-8.
    :raises LookupError: if no reader is registered for the format.
    :raises redlines.profiles.ProfileError: if the profile is named but does
        not load, or does not validate.
    """
    resolved_format = format if format is not None else _detect(source, path=path)
    resolved_profile = _resolve_profile(profile, fmt=resolved_format)
    tree = _read(
        source,
        fmt=resolved_format,
        profile=resolved_profile,
        max_chars=max_chars,
    )
    return apply_semantics(tree, resolved_profile)


def _detect(source: str | bytes, *, path: str | os.PathLike[str] | None) -> str:
    """Return the detected format name, or raise quoting why there is none.

    :param source: the document, handed to detection as content to sniff.
    :param path: the document's path or file name, if the caller has one.
    :return: the format name `detect_format` concluded.
    :raises ValueError: if detection reached no conclusion. Its ``reason`` is
        quoted verbatim, because that sentence is written for a user to read
        and is the only place the "coming in 1.1" promise is made.
    """
    detection = detect_format(
        path=None if path is None else os.fspath(path), text=source
    )
    if detection.format is None:
        raise ValueError(
            f"read_document cannot tell what format this document is: "
            f"{detection.reason}. Pass format= if you know it."
        )
    return detection.format


def _resolve_profile(
    profile: str | Path | Profile | Mapping[str, Any] | None, *, fmt: str
) -> Profile:
    """Turn whatever the caller passed as ``profile`` into a `Profile`.

    :param profile: the ``profile`` argument of `read_document`.
    :param fmt: the format already settled on, which picks the default.
    :return: a validated profile.
    :raises ValueError: if ``profile`` is ``None`` and ``fmt`` has no entry in
        `DEFAULT_PROFILES`.
    :raises redlines.profiles.ProfileError: if the profile does not load or
        does not validate.
    """
    if profile is None:
        try:
            name = DEFAULT_PROFILES[fmt]
        except KeyError:
            known = ", ".join(sorted(DEFAULT_PROFILES))
            raise ValueError(
                f"no default profile is recorded for format {fmt!r} "
                f"(there are defaults for: {known}); pass profile= to say "
                "which profile this format should be read under"
            ) from None
        return builtin_profile(name)
    if isinstance(profile, Profile):
        return profile
    if isinstance(profile, Mapping):
        return profile_from_mapping(profile)
    if isinstance(profile, str) and profile in BUILTIN_PROFILE_NAMES:
        return builtin_profile(profile)
    return load_profile(profile)


def _read(
    source: str | bytes, *, fmt: str, profile: Profile, max_chars: int
) -> BlockTree:
    """Run the reader registered for ``fmt``, with the size cap enforced.

    The `Reader` protocol promises only ``source`` and ``profile``; every
    reader shipped here also takes ``max_chars``, and a third party's may not.
    So the keyword is passed when the reader accepts it and the cap is applied
    here otherwise, which keeps ``max_chars`` meaning the same thing whichever
    reader answers.

    :param source: the document, as text or as UTF-8 bytes.
    :param fmt: the format name to look the reader up by.
    :param profile: the profile to read under.
    :param max_chars: the input size cap (ADR-0028).
    :return: the reader's tree, before any semantic pass.
    :raises LookupError: if no reader is registered for ``fmt``.
    :raises ValueError: if the source is over ``max_chars`` or is not UTF-8.
    """
    reader = reader_for(fmt)
    if _takes_max_chars(reader):
        read_with_cap = cast(_ReadWithCap, reader.read)
        return read_with_cap(source, profile=profile, max_chars=max_chars)
    check_size(
        decode_source(source, reader=reader.name),
        max_chars=max_chars,
        reader=reader.name,
    )
    return reader.read(source, profile=profile)


def _takes_max_chars(reader: Reader) -> bool:
    """Say whether ``reader.read`` accepts a ``max_chars`` keyword.

    :param reader: the reader about to be called.
    :return: true if the keyword can be passed. A ``read`` whose signature
        cannot be inspected at all (a C callable, say) is treated as not
        taking it, so the cap is applied here instead of being dropped.
    """
    try:
        parameters = inspect.signature(reader.read).parameters
    except (TypeError, ValueError):
        return False
    return "max_chars" in parameters
