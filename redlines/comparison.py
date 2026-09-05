"""The whole comparison in one call: read, read, align, build (#136, PRD § 9).

`redlines.pipeline.read_document` turns one document into a block tree.
`redlines.alignment.align` says which block of one tree is which block of the
other. `redlines.changes.build_change_tree` says what happened to each of
them. `compare` is those four stages composed, and the `Comparison` it returns
is the object everything else in the library hangs off::

    from redlines import compare

    result = compare(source_markdown, test_markdown)
    for change in result.changes:
        print(change.kind, change.test_address or change.source_address)

**Where this lives, and why not in `redlines.pipeline`.** `read_document` is
deliberately *not* re-exported -- it is imported by its full path -- and
`compare` is the headline public API PRD § 9 describes, imported as
``from redlines import compare``. Putting a re-exported function inside a
deliberately-not-re-exported module would make that module half-public
(ADR-0033). M4's ``verify()`` (ADR-0015, R24) lands here beside `compare`.

**A bare `str` is always content, never a path.** The library does not stat
the filesystem behind the caller's back: a one-line contract that happens to
name a file on the server's disk must not turn into a file read. Reading files
is what `redlines.document.Document` and `redlines.document.PlainTextFile`
already exist for, so passing one of those covers the file case with no new
semantics. ``source_path`` and ``test_path`` are **name hints for format
detection only**, exactly as ``read_document(..., path=...)`` is.

**Format detection is per side.** With no ``format=``, each side is detected
from its own path hint and its own content; if the two disagree, `compare`
raises rather than silently picking one, and `ComparisonConfig` keeps the two
formats as separate fields so a comparison always records what each side was
actually read as.

**The alignment is public.** `Comparison.alignment` carries every pair,
including the unchanged ones -- which is the whole correspondence set, and is
not expressible in the change tree, because an unchanged pair produces no
change node (ADR-0033). On the wire it is optional: `Comparison.to_dict` emits
it only under ``include_alignment=True``.

The JSON this module emits is version ``2.0`` (`SCHEMA_VERSION`). ADR-0011's
policy: an additive change -- a new optional field, a new change kind, a new
statistic -- bumps the minor; a breaking change bumps the major, gets its own
ADR, and the previous major stays producible from its own schema file. The
schema file itself and `comparison_schema_text` arrive with #137.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from .alignment import DEFAULT_ALIGNMENT, Alignment, AlignmentConfig, align
from .blocks import BlockTree, _reject_unknown_keys
from .changes import ChangeTree, build_change_tree
from .document import Document
from .pipeline import _resolve_profile, read_document
from .processor import RedlinesProcessor, WholeDocumentProcessor
from .profiles import Profile
from .readers import DEFAULT_MAX_CHARS
from .readers.detect import detect_format

__all__: tuple[str, ...] = (
    "SCHEMA_VERSION",
    "BLOCKS_FORMAT",
    "ComparisonConfig",
    "Comparison",
    "compare",
)

SCHEMA_VERSION: Final[str] = "2.0"
"""The version of the JSON this module emits (ADR-0011, ADR-0033).

``major.minor`` as a string, because ADR-0011 defines exactly two kinds of
change and an integer ``2`` could not tell a 2.1 payload from a 2.0 one. Its
presence is also the v1/v2 discriminator: v1's
`redlines.redlines.Redlines.output_json` has no such key at all.
"""

BLOCKS_FORMAT: Final[str] = "blocks"
"""What `ComparisonConfig` records for a side that arrived already read.

A `redlines.blocks.BlockTree` handed to `compare` skips reading entirely, so
no reader and no format were involved and there is nothing to detect. Naming
that honestly beats guessing a format the caller never asked for.
"""

_CONFIG_KEYS: Final[set[str]] = {
    "source_format",
    "test_format",
    "profile",
    "alignment",
    "similarity",
    "processor",
    "budget_exhausted",
}

_COMPARISON_KEYS: Final[set[str]] = {
    "schema_version",
    "config",
    "source",
    "test",
    "changes",
    "alignment",
}


@dataclass(frozen=True, slots=True)
class ComparisonConfig:
    """Everything that decided what a comparison says (#135).

    On the wire in full, so a payload can be reproduced from itself: a reader
    who wants to know why two blocks were paired can see which passes ran, on
    what thresholds, under which similarity backend.

    :param source_format: the format the source side was read as, or
        `BLOCKS_FORMAT` if it arrived as a block tree.
    :param test_format: the same for the test side. Two fields rather than
        one, because per-side detection means the two can legitimately differ
        when one side was already read.
    :param profile: the name of the structure profile both sides were read
        under, or ``""`` when neither side was read.
    :param alignment: the `redlines.alignment.AlignmentConfig` in force,
        embedded whole rather than flattened out beside these fields -- one
        source of truth, so adding a threshold is one edit and the two halves
        cannot drift on a name (ADR-0033).
    :param similarity: the **resolved** similarity backend that actually ran,
        ``"difflib"`` or ``"rapidfuzz"``, while ``alignment.similarity`` is
        what was *asked* for (``"auto"`` by default). Both, because "auto
        picked difflib" and "difflib was demanded" are different facts.
    :param processor: the leaf differ's type name, ``type(processor).__name__``
        -- a name, not a serialised object. A custom
        `redlines.processor.RedlinesProcessor` is supported (R17), and this is
        how the payload says one was used.
    :param budget_exhausted: whether alignment's ``max_comparisons`` ran out.
        When it is true, "nothing more was found" and "we stopped looking" are
        different answers, and this is what tells them apart.
    """

    source_format: str
    test_format: str
    profile: str
    alignment: AlignmentConfig
    similarity: str
    processor: str
    budget_exhausted: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the configuration as a JSON-serialisable dict.

        Keys are in the order the fields are declared, never sorted, so two
        equal configurations serialise to identical bytes (N1, #135).

        :return: a dict with the keys ``source_format``, ``test_format``,
            ``profile``, ``alignment``, ``similarity``, ``processor`` and
            ``budget_exhausted``.
        """
        return {
            "source_format": self.source_format,
            "test_format": self.test_format,
            "profile": self.profile,
            "alignment": self.alignment.to_dict(),
            "similarity": self.similarity,
            "processor": self.processor,
            "budget_exhausted": self.budget_exhausted,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> ComparisonConfig:
        """Rebuild a configuration from `to_dict` output.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `ComparisonConfig`.
        :raises ValueError: if a key is unknown, or a required one is missing.
        """
        _reject_unknown_keys(data, _CONFIG_KEYS, "comparison config")
        for required in ("source_format", "test_format", "similarity", "processor"):
            if required not in data:
                raise ValueError(f"comparison config is missing the key {required!r}")
        return cls(
            source_format=str(data["source_format"]),
            test_format=str(data["test_format"]),
            profile=str(data.get("profile", "")),
            alignment=AlignmentConfig.from_dict(data.get("alignment", {}) or {}),
            similarity=str(data["similarity"]),
            processor=str(data["processor"]),
            budget_exhausted=bool(data.get("budget_exhausted", False)),
        )


@dataclass(frozen=True, slots=True)
class Comparison:
    """Two documents, what corresponds between them, and what changed.

    Everything M2 produces, in one value: both block trees exactly as
    `redlines.pipeline.read_document` built them, the alignment, the change
    tree and the configuration that produced all of it.

    The M3 renderers arrive as methods on this class -- ``output_markdown()``,
    ``output_rich()``, ``output_html()``, ``output_annotated()`` and
    ``output_summary()`` -- and are named here so M3 has no naming argument to
    have. ``statistics()`` (#139) and ``filter()`` (#138) land the same way,
    on the object rather than as loose functions.

    :param source: the earlier document's block tree.
    :param test: the later one's.
    :param alignment: every correspondence between them, unchanged pairs
        included. Public and first-class: the correspondence set is what the
        benchmark scores, and an unchanged pair produces no change node, so
        the change tree cannot express it (ADR-0033).
    :param changes: the change tree, flat and in document order.
    :param config: what was in force.
    """

    source: BlockTree
    test: BlockTree
    alignment: Alignment
    changes: ChangeTree
    config: ComparisonConfig

    def to_dict(self, *, include_alignment: bool = False) -> dict[str, Any]:
        """Return the whole comparison as a JSON-serialisable dict (v2).

        ``source`` and ``test`` are byte-for-byte
        `redlines.blocks.BlockTree.to_dict` output: M1's serialisation is not
        reshaped, so an existing expected tree stays valid as a slice of this
        document and every consumer gets ADR-0030's reporting fields with no
        adapter. The raw document strings are deliberately *not* carried --
        the trees already hold every character.

        :param include_alignment: also emit the ``alignment`` key. Off by
            default: the full pair list roughly doubles a large payload for
            data only the benchmark reads today, and the key is optional in
            the schema, so turning it on later is not even a minor bump.
        :return: a dict with the keys ``schema_version``, ``config``,
            ``source``, ``test``, ``changes``, and ``alignment`` when it was
            asked for.
        """
        document: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "config": self.config.to_dict(),
            "source": self.source.to_dict(),
            "test": self.test.to_dict(),
            "changes": [change.to_dict() for change in self.changes],
        }
        if include_alignment:
            document["alignment"] = self.alignment.to_dict()
        return document

    def to_json(self, *, pretty: bool = False, include_alignment: bool = False) -> str:
        """Return `to_dict` as JSON text.

        ``ensure_ascii`` is off and the keys are never sorted, so the bytes
        follow the authored key order and a document keeps the characters it
        was written with.

        :param pretty: indent by two spaces instead of emitting one line.
        :param include_alignment: passed through to `to_dict`.
        :return: the JSON text, without a trailing newline.
        """
        return json.dumps(
            self.to_dict(include_alignment=include_alignment),
            ensure_ascii=False,
            indent=2 if pretty else None,
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Comparison:
        """Rebuild a comparison from `to_dict` output.

        The payload must have been written with ``include_alignment=True``:
        the alignment is a field of this class, and rebuilding it as empty
        would be a lie about which blocks correspond.

        :param data: a mapping in the shape `to_dict` produces.
        :return: the reconstructed `Comparison`.
        :raises ValueError: if a key is unknown, ``schema_version`` is missing
            or unreadable, the payload's major version is not this one, its
            minor version is *higher* than this one -- a payload from a newer
            release, whose extra fields would be silently dropped -- or the
            ``alignment`` key is absent.
        """
        _reject_unknown_keys(data, _COMPARISON_KEYS, "comparison")
        _check_schema_version(data.get("schema_version"))
        if "alignment" not in data:
            raise ValueError(
                "this comparison was serialised without its alignment and "
                "cannot be rebuilt; write it with to_dict(include_alignment=True)"
            )
        return cls(
            source=BlockTree.from_dict(data.get("source", {}) or {}),
            test=BlockTree.from_dict(data.get("test", {}) or {}),
            alignment=Alignment.from_dict(data["alignment"]),
            changes=ChangeTree.from_dict({"changes": data.get("changes", []) or []}),
            config=ComparisonConfig.from_dict(data.get("config", {}) or {}),
        )


def compare(
    source: str | bytes | BlockTree | Document,
    test: str | bytes | BlockTree | Document,
    *,
    format: str | None = None,
    source_path: str | os.PathLike[str] | None = None,
    test_path: str | os.PathLike[str] | None = None,
    profile: str | Path | Profile | Mapping[str, Any] | None = None,
    alignment: AlignmentConfig = DEFAULT_ALIGNMENT,
    processor: RedlinesProcessor | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> Comparison:
    """Compare two documents and return everything M2 knows about the difference.

    Four stages: read the source, read the test, align the two trees, build
    the change tree. A side that arrives as a
    `redlines.blocks.BlockTree` skips the first two -- which is how the M3
    facade, the benchmark harness and the site hand in trees they built
    themselves.

    :param source: the earlier document, as text, as UTF-8 bytes, as a
        `redlines.document.Document` (which is how a *file* gets in), or as a
        `redlines.blocks.BlockTree` that has already been read. **A bare
        ``str`` is content, never a path.**
    :param test: the later document, in any of the same shapes.
    :param format: the format to read *both* sides as (``"text"``,
        ``"markdown"``, or any format a reader is registered for). When
        ``None``, each side is detected from its own path hint and content.
    :param source_path: the source document's path or file name, used only as
        a hint for detection -- the file is never opened.
    :param test_path: the same for the test document.
    :param profile: the structure profile both sides are read under, in any of
        the shapes `redlines.pipeline.read_document` accepts. ``None`` means
        the format's default.
    :param alignment: which alignment passes run and on what terms;
        `redlines.alignment.DEFAULT_ALIGNMENT` if left out.
    :param processor: the leaf differ run inside a matched pair.
        ``WholeDocumentProcessor(autojunk=False)`` when left out -- the
        ADR-0010 differ, the same object v1 uses.
    :param max_chars: the input size cap (ADR-0028), passed to each reader.
    :return: the `Comparison`.
    :raises ValueError: if ``format`` is ``None`` and a side's format cannot be
        detected, or the two sides detect as *different* formats -- comparing a
        markdown document against a plain-text one is almost always a mistake,
        and reading them under one format silently would hide it; or if a
        format has no default profile, or an input is over ``max_chars`` or is
        not UTF-8.
    :raises LookupError: if no reader is registered for a format.
    :raises redlines.profiles.ProfileError: if the profile does not load or
        does not validate.
    """
    source_format = _side_format(source, path=source_path, format=format, side="source")
    test_format = _side_format(test, path=test_path, format=format, side="test")
    _reject_mixed_formats(source, test, source_format, test_format, format)

    read_format = source_format if source_format != BLOCKS_FORMAT else test_format
    resolved_profile = (
        None
        if read_format == BLOCKS_FORMAT
        else _resolve_profile(profile, fmt=read_format)
    )
    source_tree = _tree(
        source, format=source_format, profile=resolved_profile, max_chars=max_chars
    )
    test_tree = _tree(
        test, format=test_format, profile=resolved_profile, max_chars=max_chars
    )

    result = align(source_tree, test_tree, config=alignment)
    leaf = processor if processor is not None else WholeDocumentProcessor(autojunk=False)
    changes = build_change_tree(result, source_tree, test_tree, processor=leaf)
    return Comparison(
        source=source_tree,
        test=test_tree,
        alignment=result,
        changes=changes,
        config=ComparisonConfig(
            source_format=source_format,
            test_format=test_format,
            profile="" if resolved_profile is None else resolved_profile.name,
            alignment=alignment,
            similarity=result.backend,
            processor=type(leaf).__name__,
            budget_exhausted=result.budget_exhausted,
        ),
    )


# --------------------------------------------------------------------------
# The stages. Everything below is private; the shapes above are the contract.
# --------------------------------------------------------------------------


def _side_format(
    value: str | bytes | BlockTree | Document,
    *,
    path: str | os.PathLike[str] | None,
    format: str | None,
    side: str,
) -> str:
    """Settle one side's format, without looking at the other.

    :param value: that side's input.
    :param path: its name hint, if the caller gave one.
    :param format: the format the caller named for both sides, if any.
    :param side: ``"source"`` or ``"test"``, for the error message.
    :return: the format name, or `BLOCKS_FORMAT` for a tree.
    :raises ValueError: if detection reached no conclusion. Its ``reason`` is
        quoted verbatim, because that sentence is written for a user to read
        and is the only place the "coming in 1.1" promise is made.
    """
    if isinstance(value, BlockTree):
        return BLOCKS_FORMAT
    if format is not None:
        return format
    text = value.text if isinstance(value, Document) else value
    detection = detect_format(path=None if path is None else os.fspath(path), text=text)
    if detection.format is None:
        raise ValueError(
            f"compare cannot tell what format the {side} document is: "
            f"{detection.reason}. Pass format= if you know it."
        )
    return detection.format


def _reject_mixed_formats(
    source: str | bytes | BlockTree | Document,
    test: str | bytes | BlockTree | Document,
    source_format: str,
    test_format: str,
    format: str | None,
) -> None:
    """Raise if the two sides were *detected* as different formats.

    Only detection can disagree: an explicit ``format=`` sets both sides, and
    a side that arrived as a block tree was not detected at all, so a tree
    compared against a markdown string is a legitimate mixture rather than a
    mistake.
    """
    if format is not None or source_format == test_format:
        return
    if isinstance(source, BlockTree) or isinstance(test, BlockTree):
        return
    raise ValueError(
        f"compare detected the source document as {source_format!r} and the "
        f"test document as {test_format!r}; two documents read under "
        "different formats cannot be aligned meaningfully. Pass format= to "
        "say what they both are."
    )


def _tree(
    value: str | bytes | BlockTree | Document,
    *,
    format: str,
    profile: Profile | None,
    max_chars: int,
) -> BlockTree:
    """Return one side as a block tree, reading it only if it is not one already.

    A `redlines.document.Document` is read for its text and nothing else: the
    file it came from was opened when the `Document` was built, not here.
    """
    if isinstance(value, BlockTree):
        return value
    text = value.text if isinstance(value, Document) else value
    return read_document(text, format=format, profile=profile, max_chars=max_chars)


def _check_schema_version(value: Any) -> None:
    """Accept a payload this release can read, and say why when it cannot.

    A different major is a different format (ADR-0011). A *higher* minor is
    rejected rather than silently narrowed: the extra fields a newer release
    added would be dropped without a word, and the strict key checking that
    would otherwise catch them reports an unknown key, which reads as a typo
    rather than as a version problem.
    """
    if value is None:
        raise ValueError(
            "comparison is missing the key 'schema_version'; a payload without "
            "one is v1 output, which redlines.redlines.Redlines reads"
        )
    text = str(value)
    parts = text.split(".")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(
            f"schema_version {text!r} is not a 'major.minor' version string"
        )
    major, minor = (int(part) for part in parts)
    expected_major, expected_minor = (int(part) for part in SCHEMA_VERSION.split("."))
    if major != expected_major:
        raise ValueError(
            f"this comparison is schema version {text}, and this release of "
            f"redlines reads {expected_major}.x only"
        )
    if minor > expected_minor:
        raise ValueError(
            f"this comparison is schema version {text}, which is newer than "
            f"the {SCHEMA_VERSION} this release writes; reading it would drop "
            "whatever that version added"
        )
