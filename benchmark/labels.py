"""The benchmark label file: dataclasses, schema validation, digests, totality (D-7, ADR-0034).

One YAML file per pair, ``benchmark/corpus/<tier>/<pair>/labels.yaml``, is the shared ground truth
both the synthetic generator (#141) and a human labeller (#142) write and the metric (#143) reads.
This module is the one place that knows its shape:

- **`LabelFile` and its nested dataclasses** mirror the mapping ``labels/schema.json`` validates
  (`Correspondence`, `InsertedEntry`, `DeletedEntry`, `SplitEntry`, `MergeEntry`, `UnscoredRegion`,
  `Review`, `MoveVerdict`). Frozen and ``slots=True``, like `redlines.blocks.Block`: a label file is
  data, not something a scorer mutates in place.
- **`load_labels`/`labels_from_mapping`** validate against the published schema with `jsonschema`
  (a dev-only dependency -- this whole package is unpackaged, see `benchmark/__init__.py`) and build
  the dataclass tree. **`dump_labels`** is the inverse: a canonical dumper that always emits keys in
  the schema's own order, so two label files with the same content are byte-identical and a PR diff
  shows only what a labeller actually changed.
- **`digest_for`** computes the anchor ADR-0034 calls "sha256 of the block's normalised text
  (whitespace collapsed, label re-prefixed) truncated to 16 hex characters". A `row` block owns no
  text of its own (`redlines.blocks.Block`'s container convention), so its content is its cells'
  texts, joined the same way `redlines/alignment.py`'s match key will join them -- this is the one
  place that decision is duplicated, deliberately, because this module must not import
  ``redlines.alignment`` (a different track; see the module docstring's dependency note).
- **`verify_digests`** re-derives every recorded digest against the trees given and fails loudly,
  naming every stale address in one exception, rather than scoring whatever the addresses happen to
  point at today.
- **`check_totality`** asserts that every labelled block on each side -- every text-bearing block,
  plus `row` blocks; `document`, `section` and `table` excluded, per `LABELLED_KINDS` -- appears
  exactly once across ``correspondences``, ``inserted``, ``deleted``, ``splits``, ``merges`` and
  ``unscored``. Without this, recall is meaningless: a half-labelled file scores 1.0.
- **`override_rate`** computes the anti-self-marking symptom ADR-0034 asks the report to print:
  the fraction of rows a labeller marked ``corrected`` rather than ``confirmed``.

**Dependency direction.** This module imports only `redlines.blocks` (the `Block`/`BlockTree` model
and its addresses) and, in its doctest-style usage, `redlines.pipeline.read_document` to build the
trees a label file is checked against. It does not import `redlines.alignment`,
`redlines.comparison` or anything else from the alignment or change-tree tracks -- those are separate
work landing on other branches, and this module's job is the label *format*, usable before or after
they exist.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from redlines.blocks import Block, BlockKind, BlockTree

__all__ = [
    "SCHEMA_ID",
    "LABELLED_KINDS",
    "STATUSES",
    "CORRESPONDENCE_KINDS",
    "LabelError",
    "StaleDigestError",
    "TotalityError",
    "Side",
    "Provenance",
    "Correspondence",
    "InsertedEntry",
    "DeletedEntry",
    "SplitEntry",
    "MergeEntry",
    "UnscoredRegion",
    "Review",
    "MoveVerdict",
    "LabelFile",
    "label_schema_text",
    "normalise_text",
    "digest_for",
    "labelled_blocks",
    "labelled_addresses",
    "load_labels",
    "labels_from_mapping",
    "labels_from_yaml",
    "to_mapping",
    "dump_labels",
    "save_labels",
    "verify_digests",
    "check_totality",
    "override_rate",
]

SCHEMA_ID = "redlines/alignment-labels/1"
"""The label format's own version -- the ``schema`` key every labels.yaml carries."""

#: Only blocks that own text, plus `row` blocks for tables (ADR-0034's totality rule).
#: `document`, `section` and `table` are containers and are never labelled.
LABELLED_KINDS: frozenset[BlockKind] = frozenset(BlockKind) - {
    BlockKind.DOCUMENT,
    BlockKind.SECTION,
    BlockKind.TABLE,
}

STATUSES: tuple[str, ...] = ("proposed", "confirmed", "corrected")
CORRESPONDENCE_KINDS: tuple[str, ...] = ("same", "move", "renumber")


class LabelError(ValueError):
    """A label file failed schema validation.

    Carries every problem found, like `redlines.profiles.ProfileError`, so a
    labeller fixing a hand-edited file can address them all in one pass.
    """

    def __init__(self, errors: Sequence[str]):
        self.errors = list(errors)
        detail = "\n".join(f"  - {message}" for message in self.errors)
        super().__init__(f"Invalid label file:\n{detail}")


class StaleDigestError(ValueError):
    """A recorded digest no longer matches the block at its address.

    Raised by `verify_digests` rather than letting the metric silently score
    whatever the address happens to point at today (ADR-0034).
    """

    def __init__(self, mismatches: Sequence[str]):
        self.mismatches = list(mismatches)
        detail = "\n".join(f"  - {message}" for message in self.mismatches)
        super().__init__(
            "Labels are stale -- digests no longer match the current tree; "
            f"run benchmark/reanchor.py:\n{detail}"
        )


class TotalityError(ValueError):
    """A label file does not account for every labelled block exactly once.

    Raised by `check_totality`. Without this check, recall is meaningless: a
    half-labelled file scores a perfect 1.0 by never being asked about the
    blocks it left out.
    """

    def __init__(self, problems: Sequence[str]):
        self.problems = list(problems)
        detail = "\n".join(f"  - {message}" for message in self.problems)
        super().__init__(f"Label file is not total:\n{detail}")


def label_schema_text() -> str:
    """Return the published JSON Schema for the label format, as text.

    Read from the installed location the same way `redlines.profiles.profile_schema_text`
    reads its schema, for the same reason: a consumer that only wants the schema
    text should not need to know this package's directory layout.
    """
    return (files(__package__) / "labels" / "schema.json").read_text(encoding="utf-8")


def normalise_text(text: str) -> str:
    """Collapse whitespace runs to one space and strip the ends.

    The normalisation ADR-0034 names for the digest: case is *not* folded (a
    case-only change is a real change), only whitespace shape is discarded.
    """
    return " ".join(text.split())


_ROW_CELL_SEPARATOR = "\x1f"
_LABEL_SEPARATOR = "\x1f"


def digest_for(block: Block) -> str:
    """Return the 16-hex-character sha256 digest ADR-0034 anchors a label row to.

    The content hashed is the block's normalised text (`normalise_text`),
    prefixed with its label where it has one; a `row` block, which owns no
    text of its own, is hashed over its cells' normalised texts joined with
    the same separator `redlines/alignment.py`'s match key will use for a
    row's exact-match key, so a table's rows keep meaningful digests without
    this module importing that one.

    :param block: the block to digest. Any kind is accepted; callers normally
        restrict themselves to `LABELLED_KINDS` via `labelled_blocks`.
    :return: 16 lowercase hex characters.
    """
    if block.kind is BlockKind.ROW:
        content = _ROW_CELL_SEPARATOR.join(
            normalise_text(cell.text) for cell in block.children
        )
    else:
        content = normalise_text(block.text)
    if block.label:
        content = f"{block.label}{_LABEL_SEPARATOR}{content}"
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]


def labelled_blocks(tree: BlockTree) -> tuple[Block, ...]:
    """Return every block in `tree` that ADR-0034 says must be labelled, in document order.

    :param tree: the tree to walk (`BlockTree.walk` is depth-first, root
        first, document order).
    :return: blocks whose kind is in `LABELLED_KINDS`.
    """
    return tuple(block for block in tree.walk() if block.kind in LABELLED_KINDS)


def labelled_addresses(tree: BlockTree) -> tuple[str, ...]:
    """Return the addresses of every block `labelled_blocks` would return.

    Convenience for the totality check and for building a digest index; see
    `labelled_blocks` for which blocks these are.
    """
    return tuple(block.path for block in labelled_blocks(tree))


# --------------------------------------------------------------------------
# Dataclasses mirroring benchmark/labels/schema.json
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Side:
    """One side (``source`` or ``test``) of a pair: which document, read how."""

    file: str
    format: str
    profile: str
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "file": self.file,
            "format": self.format,
            "profile": self.profile,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Side:
        return cls(
            file=str(data["file"]),
            format=str(data["format"]),
            profile=str(data["profile"]),
            sha256=str(data["sha256"]),
        )


@dataclass(frozen=True, slots=True)
class Provenance:
    """Where a pair came from, and what was done to it before it was committed."""

    kind: str  # "hand" | "synthetic"
    origin: str
    licence: str | None = None
    attribution: str | None = None
    prepared_by: str | None = None
    normalisations: tuple[str, ...] = ()
    generator: str | None = None
    generator_version: int | None = None
    seed: int | None = None
    plan: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {"kind": self.kind, "origin": self.origin}
        if self.licence is not None:
            data["licence"] = self.licence
        if self.attribution is not None:
            data["attribution"] = self.attribution
        if self.prepared_by is not None:
            data["prepared_by"] = self.prepared_by
        if self.normalisations:
            data["normalisations"] = list(self.normalisations)
        if self.generator is not None:
            data["generator"] = self.generator
        if self.generator_version is not None:
            data["generator_version"] = self.generator_version
        if self.seed is not None:
            data["seed"] = self.seed
        if self.plan is not None:
            data["plan"] = self.plan
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Provenance:
        return cls(
            kind=str(data["kind"]),
            origin=str(data["origin"]),
            licence=data.get("licence"),
            attribution=data.get("attribution"),
            prepared_by=data.get("prepared_by"),
            normalisations=tuple(data.get("normalisations", ()) or ()),
            generator=data.get("generator"),
            generator_version=data.get("generator_version"),
            seed=data.get("seed"),
            plan=data.get("plan"),
        )


@dataclass(frozen=True, slots=True)
class Correspondence:
    """One matched pair -- unchanged, moved or renumbered (ADR-0034's ``kind``)."""

    source: str
    test: str
    kind: str  # "same" | "move" | "renumber"
    source_digest: str
    test_digest: str
    status: str
    source_label: str | None = None
    test_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "test": self.test,
            "kind": self.kind,
            "source_label": self.source_label,
            "test_label": self.test_label,
            "source_digest": self.source_digest,
            "test_digest": self.test_digest,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Correspondence:
        return cls(
            source=str(data["source"]),
            test=str(data["test"]),
            kind=str(data["kind"]),
            source_label=data.get("source_label"),
            test_label=data.get("test_label"),
            source_digest=str(data["source_digest"]),
            test_digest=str(data["test_digest"]),
            status=str(data["status"]),
        )


@dataclass(frozen=True, slots=True)
class InsertedEntry:
    test: str
    test_digest: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {"test": self.test, "test_digest": self.test_digest, "status": self.status}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> InsertedEntry:
        return cls(
            test=str(data["test"]),
            test_digest=str(data["test_digest"]),
            status=str(data["status"]),
        )


@dataclass(frozen=True, slots=True)
class DeletedEntry:
    source: str
    source_digest: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "source_digest": self.source_digest,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> DeletedEntry:
        return cls(
            source=str(data["source"]),
            source_digest=str(data["source_digest"]),
            status=str(data["status"]),
        )


@dataclass(frozen=True, slots=True)
class SplitEntry:
    """One source block that became several test blocks (labelled, unscored in 1.0)."""

    source: str
    tests: tuple[str, ...]
    source_digest: str
    test_digests: tuple[str, ...]
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "tests": list(self.tests),
            "source_digest": self.source_digest,
            "test_digests": list(self.test_digests),
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> SplitEntry:
        return cls(
            source=str(data["source"]),
            tests=tuple(data["tests"]),
            source_digest=str(data["source_digest"]),
            test_digests=tuple(data["test_digests"]),
            status=str(data["status"]),
        )


@dataclass(frozen=True, slots=True)
class MergeEntry:
    """Several source blocks that became one test block (labelled, unscored in 1.0)."""

    sources: tuple[str, ...]
    test: str
    source_digests: tuple[str, ...]
    test_digest: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "sources": list(self.sources),
            "test": self.test,
            "source_digests": list(self.source_digests),
            "test_digest": self.test_digest,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MergeEntry:
        return cls(
            sources=tuple(data["sources"]),
            test=str(data["test"]),
            source_digests=tuple(data["source_digests"]),
            test_digest=str(data["test_digest"]),
            status=str(data["status"]),
        )


@dataclass(frozen=True, slots=True)
class UnscoredRegion:
    region: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"region": self.region, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> UnscoredRegion:
        return cls(region=str(data["region"]), reason=str(data["reason"]))


@dataclass(frozen=True, slots=True)
class Review:
    """Who labelled and reviewed this pair, and the anti-self-marking symptom (ADR-0034)."""

    labelled_by: str
    labelled_at: str
    reviewed_by: str | None = None
    reviewed_at: str | None = None
    decision: str | None = None
    override_rate: float | None = None
    signature: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "labelled_by": self.labelled_by,
            "labelled_at": self.labelled_at,
        }
        if self.reviewed_by is not None:
            data["reviewed_by"] = self.reviewed_by
        if self.reviewed_at is not None:
            data["reviewed_at"] = self.reviewed_at
        if self.decision is not None:
            data["decision"] = self.decision
        if self.override_rate is not None:
            data["override_rate"] = self.override_rate
        if self.signature is not None:
            data["signature"] = self.signature
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Review:
        return cls(
            labelled_by=str(data["labelled_by"]),
            labelled_at=str(data["labelled_at"]),
            reviewed_by=data.get("reviewed_by"),
            reviewed_at=data.get("reviewed_at"),
            decision=data.get("decision"),
            override_rate=data.get("override_rate"),
            signature=data.get("signature"),
        )


@dataclass(frozen=True, slots=True)
class MoveVerdict:
    """A reviewer's ruling on an engine-reported move absent from `correspondences` (ADR-0009)."""

    source: str
    test: str
    engine: str
    verdict: str  # "wrong" | "acceptable"
    reason: str
    reviewed_by: str
    reviewed_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "test": self.test,
            "engine": self.engine,
            "verdict": self.verdict,
            "reason": self.reason,
            "reviewed_by": self.reviewed_by,
            "reviewed_at": self.reviewed_at,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> MoveVerdict:
        return cls(
            source=str(data["source"]),
            test=str(data["test"]),
            engine=str(data["engine"]),
            verdict=str(data["verdict"]),
            reason=str(data["reason"]),
            reviewed_by=str(data["reviewed_by"]),
            reviewed_at=str(data["reviewed_at"]),
        )


@dataclass(frozen=True, slots=True)
class LabelFile:
    """One pair's whole label file -- the parsed, validated shape of ``labels.yaml``."""

    pair: str
    source: Side
    test: Side
    provenance: Provenance
    correspondences: tuple[Correspondence, ...] = ()
    inserted: tuple[InsertedEntry, ...] = ()
    deleted: tuple[DeletedEntry, ...] = ()
    splits: tuple[SplitEntry, ...] = ()
    merges: tuple[MergeEntry, ...] = ()
    unscored: tuple[UnscoredRegion, ...] = ()
    review: Review | None = None
    move_verdicts: tuple[MoveVerdict, ...] = ()
    schema: str = SCHEMA_ID

    def to_dict(self) -> dict[str, Any]:
        """Return this label file as a dict, keys in the schema's own order (`to_mapping`)."""
        return to_mapping(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> LabelFile:
        """Build a `LabelFile` from an already-parsed mapping, without schema validation.

        Use `labels_from_mapping` (or `load_labels`) for a mapping you have
        not already validated -- a hand-edited or generator-written file.
        """
        return cls(
            schema=str(data.get("schema", SCHEMA_ID)),
            pair=str(data["pair"]),
            source=Side.from_dict(data["source"]),
            test=Side.from_dict(data["test"]),
            provenance=Provenance.from_dict(data["provenance"]),
            correspondences=tuple(
                Correspondence.from_dict(item) for item in data.get("correspondences", ()) or ()
            ),
            inserted=tuple(
                InsertedEntry.from_dict(item) for item in data.get("inserted", ()) or ()
            ),
            deleted=tuple(DeletedEntry.from_dict(item) for item in data.get("deleted", ()) or ()),
            splits=tuple(SplitEntry.from_dict(item) for item in data.get("splits", ()) or ()),
            merges=tuple(MergeEntry.from_dict(item) for item in data.get("merges", ()) or ()),
            unscored=tuple(
                UnscoredRegion.from_dict(item) for item in data.get("unscored", ()) or ()
            ),
            review=Review.from_dict(data["review"]) if data.get("review") is not None else None,
            move_verdicts=tuple(
                MoveVerdict.from_dict(item) for item in data.get("move_verdicts", ()) or ()
            ),
        )


# --------------------------------------------------------------------------
# Validation, loading and the canonical dumper
# --------------------------------------------------------------------------

_SCHEMA_CACHE: dict[str, Any] | None = None


def _schema() -> dict[str, Any]:
    global _SCHEMA_CACHE
    if _SCHEMA_CACHE is None:
        _SCHEMA_CACHE = json.loads(label_schema_text())
    return _SCHEMA_CACHE


def labels_from_mapping(mapping: Mapping[str, Any]) -> LabelFile:
    """Validate a plain mapping against `labels/schema.json` and build a `LabelFile`.

    :raises LabelError: with every schema violation found, not just the first.
    """
    if not isinstance(mapping, Mapping):
        raise LabelError([f"a label file must be a mapping, got {type(mapping).__name__}"])
    validator = jsonschema.Draft7Validator(_schema())
    errors = sorted(validator.iter_errors(mapping), key=lambda e: list(e.path))
    if errors:
        messages = [
            f"{'/'.join(str(p) for p in error.path) or '(top level)'}: {error.message}"
            for error in errors
        ]
        raise LabelError(messages)
    return LabelFile.from_dict(mapping)


def labels_from_yaml(text: str) -> LabelFile:
    """Parse YAML text into a validated `LabelFile`."""
    try:
        mapping = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise LabelError([f"invalid YAML: {exc}"]) from exc
    if mapping is None:
        mapping = {}
    return labels_from_mapping(mapping)


def load_labels(path: str | Path) -> LabelFile:
    """Load and validate a ``labels.yaml`` file from disk."""
    text = Path(path).read_text(encoding="utf-8")
    return labels_from_yaml(text)


def to_mapping(labels: LabelFile) -> dict[str, Any]:
    """Return `labels` as a plain dict, keys always in the schema's own order.

    Optional, empty collections (``splits``, ``merges``, ``unscored``,
    ``move_verdicts``) are always present, even when empty, so two files
    that differ only in whether they bothered to write ``splits: []``
    serialise identically. ``review`` is omitted when absent -- a pair with
    no review yet is not the same as a pair reviewed and found empty.
    """
    data: dict[str, Any] = {
        "schema": labels.schema,
        "pair": labels.pair,
        "source": labels.source.to_dict(),
        "test": labels.test.to_dict(),
        "provenance": labels.provenance.to_dict(),
        "correspondences": [c.to_dict() for c in labels.correspondences],
        "inserted": [i.to_dict() for i in labels.inserted],
        "deleted": [d.to_dict() for d in labels.deleted],
        "splits": [s.to_dict() for s in labels.splits],
        "merges": [m.to_dict() for m in labels.merges],
        "unscored": [u.to_dict() for u in labels.unscored],
    }
    if labels.review is not None:
        data["review"] = labels.review.to_dict()
    data["move_verdicts"] = [v.to_dict() for v in labels.move_verdicts]
    return data


def dump_labels(labels: LabelFile) -> str:
    """Return `labels` as canonical YAML text.

    Canonical: keys always in `to_mapping`'s order (never alphabetised),
    never flow style, never line-wrapped -- so two label files with the same
    content dump to identical bytes, and a PR diff shows exactly the rows a
    labeller changed, and nothing else.
    """
    return yaml.safe_dump(
        to_mapping(labels),
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
        width=1_000_000,
    )


def save_labels(labels: LabelFile, path: str | Path) -> None:
    """Write `labels` to ``path`` as canonical YAML (`dump_labels`)."""
    Path(path).write_text(dump_labels(labels), encoding="utf-8")


# --------------------------------------------------------------------------
# Digest verification and the totality check
# --------------------------------------------------------------------------


def _current_digest(tree: BlockTree, path: str) -> str | None:
    """Return the current digest at `path` in `tree`, or ``None`` if nothing is there."""
    try:
        return digest_for(tree.block_at(path))
    except (KeyError, ValueError):
        return None


def verify_digests(labels: LabelFile, *, source_tree: BlockTree, test_tree: BlockTree) -> None:
    """Re-derive every recorded digest against the trees given and fail loudly on drift.

    An address is a position (ADR-0029), not an identity, so a reader change
    shifts every following ``section[n]`` and a label file that only checked
    addresses would silently score the wrong blocks. This walks every row
    ADR-0034 anchors by digest and compares.

    :raises StaleDigestError: naming every address whose recorded digest no
        longer matches what is at that address in the tree given (including
        an address the tree no longer has at all).
    """
    mismatches: list[str] = []

    def check(side: str, address: str, recorded: str, tree: BlockTree) -> None:
        current = _current_digest(tree, address)
        if current != recorded:
            found = current if current is not None else "no block there"
            mismatches.append(f"{side} {address}: recorded {recorded}, found {found}")

    for row in labels.correspondences:
        check("source", row.source, row.source_digest, source_tree)
        check("test", row.test, row.test_digest, test_tree)
    for entry in labels.inserted:
        check("test", entry.test, entry.test_digest, test_tree)
    for deleted_entry in labels.deleted:
        check("source", deleted_entry.source, deleted_entry.source_digest, source_tree)
    for split in labels.splits:
        check("source", split.source, split.source_digest, source_tree)
        for test_addr, test_digest in zip(split.tests, split.test_digests):
            check("test", test_addr, test_digest, test_tree)
    for merge in labels.merges:
        check("test", merge.test, merge.test_digest, test_tree)
        for source_addr, source_digest in zip(merge.sources, merge.source_digests):
            check("source", source_addr, source_digest, source_tree)

    if mismatches:
        raise StaleDigestError(mismatches)


def check_totality(labels: LabelFile, *, source_tree: BlockTree, test_tree: BlockTree) -> None:
    """Assert every labelled block on each side appears exactly once in `labels`.

    "Exactly once" across ``correspondences``, ``inserted``, ``deleted``,
    ``splits``, ``merges`` and ``unscored`` combined (ADR-0034). Without
    this, recall is meaningless -- a half-labelled file scores 1.0 by never
    being asked about the blocks it left out.

    :raises TotalityError: naming every labelled address that is missing or
        that appears more than once, on either side.
    """
    expected_source = set(labelled_addresses(source_tree))
    expected_test = set(labelled_addresses(test_tree))

    seen_source: list[str] = []
    seen_test: list[str] = []

    for row in labels.correspondences:
        seen_source.append(row.source)
        seen_test.append(row.test)
    for entry in labels.inserted:
        seen_test.append(entry.test)
    for deleted_entry in labels.deleted:
        seen_source.append(deleted_entry.source)
    for split in labels.splits:
        seen_source.append(split.source)
        seen_test.extend(split.tests)
    for merge in labels.merges:
        seen_source.extend(merge.sources)
        seen_test.append(merge.test)
    for region in labels.unscored:
        # An unscored region may name an address on either side (or neither,
        # if it is a prose description); count it on whichever side(s) it
        # matches so a labelled block covered only by `unscored` is not
        # flagged as missing.
        if region.region in expected_source:
            seen_source.append(region.region)
        if region.region in expected_test:
            seen_test.append(region.region)

    problems: list[str] = []
    problems.extend(_totality_problems("source", expected_source, seen_source))
    problems.extend(_totality_problems("test", expected_test, seen_test))
    if problems:
        raise TotalityError(problems)


def _totality_problems(
    side: str, expected: set[str], seen: Sequence[str]
) -> list[str]:
    counts = Counter(seen)
    problems: list[str] = []
    missing = sorted(expected - counts.keys())
    problems.extend(f"{side} {address}: missing from every list" for address in missing)
    extra = sorted(counts.keys() - expected)
    problems.extend(
        f"{side} {address}: labelled but not a labelled-kind block (or unknown address)"
        for address in extra
    )
    duplicated = sorted(
        address for address, count in counts.items() if address in expected and count > 1
    )
    problems.extend(
        f"{side} {address}: appears {counts[address]} times, expected exactly once"
        for address in duplicated
    )
    return problems


def override_rate(labels: LabelFile) -> float | None:
    """Return the fraction of status-bearing rows marked ``corrected``.

    ADR-0034's anti-self-marking symptom: a suspiciously low rate across
    pairs is the visible sign that seeding labels from the engine biased the
    labeller rather than merely saving them typing. ``None`` when the file
    carries no status-bearing rows at all (an empty pair).
    """
    statuses: list[str] = [row.status for row in labels.correspondences]
    statuses.extend(entry.status for entry in labels.inserted)
    statuses.extend(entry.status for entry in labels.deleted)
    statuses.extend(split.status for split in labels.splits)
    statuses.extend(merge.status for merge in labels.merges)
    if not statuses:
        return None
    corrected = sum(1 for status in statuses if status == "corrected")
    return corrected / len(statuses)
