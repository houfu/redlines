"""Repair label addresses after a reader change, by digest -- never by guessing (ADR-0034).

An address is a position, not an identity (ADR-0029): a reader or profile change that adds, drops
or reorders a block shifts every following ``section[n]``, and a label file that stored only
addresses would silently start scoring the wrong blocks. `benchmark.labels.verify_digests` is what
notices; this module is what fixes it, by finding, for every recorded digest, the block that now
carries it and rewriting the address to match.

**Three outcomes for every row**, and only one of them rewrites anything:

- **exactly one block** in the tree has the recorded digest -- the address is updated to it. This is
  the ordinary case: nothing about the block changed, only its position, so the recorded digest is
  still the right thing to have anchored on.
- **no block** has it -- the block that produced this digest is genuinely gone (its text or label
  changed, or it was removed), and reanchoring cannot invent a new correspondence. Reported, not
  guessed.
- **more than one block** has it -- the digest is ambiguous (duplicate text), and the address was the
  only thing disambiguating it. Silently picking one would be a coin flip dressed up as a fact.
  Reported, not guessed.

**A `status: corrected` row is not silently rewritten even in the first case**, unless the caller
passes ``force_corrected=True``. A corrected row is a human's considered judgement, not the engine's
proposal; quietly moving it to wherever its digest happens to sit now — even when that address is
almost certainly right — removes the second look a corrected fact deserves. Pass
``force_corrected=True`` only after checking the reported changes by eye; that is what "refusing to
silently change a corrected row" means here, and it is a deliberate reading of ADR-0034, which asks
for the refusal without prescribing its exact mechanism.

This module never writes a file itself: `reanchor` returns a `ReanchorReport` carrying the updated
`LabelFile` (with every rewritable row rewritten) plus what changed and what needs a human, and it is
the caller's job -- ``benchmark/label.py``'s eventual ``reanchor`` verb, or a one-off script -- to
call `benchmark.labels.save_labels` once it is happy with the report.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from redlines.blocks import BlockTree

from .labels import (
    Correspondence,
    DeletedEntry,
    InsertedEntry,
    LabelFile,
    digest_for,
    labelled_blocks,
)

__all__ = ["AddressChange", "ReanchorReport", "ReanchorError", "reanchor"]


class ReanchorError(ValueError):
    """A row's digest matched zero or more than one block, and could not be repaired.

    Carries every such row, not just the first, so a human fixing the corpus
    (re-labelling a genuinely changed block, or disambiguating a duplicate)
    can see the whole list in one pass.
    """

    def __init__(self, problems: list[str]):
        self.problems = problems
        detail = "\n".join(f"  - {message}" for message in problems)
        super().__init__(f"Cannot reanchor:\n{detail}")


@dataclass(frozen=True, slots=True)
class AddressChange:
    """One address `reanchor` moved, or refused to move."""

    side: str  # "source" | "test"
    digest: str
    old_address: str
    new_address: str
    refused: bool = False
    """``True`` when the row is ``status: corrected`` and ``force_corrected`` was not set."""


@dataclass(frozen=True, slots=True)
class ReanchorReport:
    """The result of `reanchor`: the repaired labels, and what happened to get there."""

    labels: LabelFile
    changes: tuple[AddressChange, ...]
    """Every address that actually moved (``refused=False``), old to new."""
    refused: tuple[AddressChange, ...]
    """Every ``corrected`` row whose digest matched a new address but was left untouched."""


def _digest_index(tree: BlockTree) -> dict[str, list[str]]:
    """Map every labelled block's digest to the addresses that currently carry it."""
    index: dict[str, list[str]] = defaultdict(list)
    for block in labelled_blocks(tree):
        index[digest_for(block)].append(block.path)
    return dict(index)


def _resolve(
    *,
    side: str,
    old_address: str,
    digest: str,
    index: dict[str, list[str]],
    corrected: bool,
    force_corrected: bool,
    problems: list[str],
) -> tuple[str, AddressChange | None]:
    """Return the address a row should use, and the change record if one applies.

    :return: the resolved address (unchanged from ``old_address`` if nothing
        should move) and an `AddressChange` to record, or ``None`` if the
        address did not need one (it already matched, or the row's problem
        was appended to ``problems`` instead).
    """
    candidates = index.get(digest, [])
    if len(candidates) == 0:
        problems.append(f"{side} {old_address} (digest {digest}): no block has this digest now")
        return old_address, None
    if len(candidates) > 1:
        problems.append(
            f"{side} {old_address} (digest {digest}): ambiguous, "
            f"{len(candidates)} blocks share this digest now ({', '.join(sorted(candidates))})"
        )
        return old_address, None
    new_address = candidates[0]
    if new_address == old_address:
        return old_address, None
    if corrected and not force_corrected:
        return old_address, AddressChange(
            side=side,
            digest=digest,
            old_address=old_address,
            new_address=new_address,
            refused=True,
        )
    return new_address, AddressChange(
        side=side, digest=digest, old_address=old_address, new_address=new_address
    )


def reanchor(
    labels: LabelFile,
    *,
    source_tree: BlockTree,
    test_tree: BlockTree,
    force_corrected: bool = False,
) -> ReanchorReport:
    """Recompute every address in `labels` from its recorded digest.

    :param labels: the label file to repair. Not mutated; the report carries
        a new `LabelFile`.
    :param source_tree: the current source tree to reanchor against.
    :param test_tree: the current test tree to reanchor against.
    :param force_corrected: when ``True``, a ``status: corrected`` row whose
        digest resolves to exactly one new address is rewritten like any
        other row. Leave this ``False`` (the default) for an automated run;
        set it only after a human has read the report's ``refused`` list and
        agreed with every one of them.
    :return: a `ReanchorReport` carrying the repaired `LabelFile`, every
        address that moved, and every ``corrected`` row left untouched
        pending that second look.
    :raises ReanchorError: if any row's digest matches zero or more than one
        block on the side it names. `splits`/`merges`/`unscored` rows and
        `move_verdicts` (which have no digest to anchor on) are passed
        through unchanged and never raise here.
    """
    source_index = _digest_index(source_tree)
    test_index = _digest_index(test_tree)

    problems: list[str] = []
    changes: list[AddressChange] = []
    refused: list[AddressChange] = []

    new_correspondences: list[Correspondence] = []
    for row in labels.correspondences:
        new_source, source_change = _resolve(
            side="source",
            old_address=row.source,
            digest=row.source_digest,
            index=source_index,
            corrected=row.status == "corrected",
            force_corrected=force_corrected,
            problems=problems,
        )
        new_test, test_change = _resolve(
            side="test",
            old_address=row.test,
            digest=row.test_digest,
            index=test_index,
            corrected=row.status == "corrected",
            force_corrected=force_corrected,
            problems=problems,
        )
        for change in (source_change, test_change):
            if change is None:
                continue
            (refused if change.refused else changes).append(change)
        new_correspondences.append(replace(row, source=new_source, test=new_test))

    new_inserted: list[InsertedEntry] = []
    for entry in labels.inserted:
        new_test, change = _resolve(
            side="test",
            old_address=entry.test,
            digest=entry.test_digest,
            index=test_index,
            corrected=entry.status == "corrected",
            force_corrected=force_corrected,
            problems=problems,
        )
        if change is not None:
            (refused if change.refused else changes).append(change)
        new_inserted.append(replace(entry, test=new_test))

    new_deleted: list[DeletedEntry] = []
    for deleted_entry in labels.deleted:
        new_source, change = _resolve(
            side="source",
            old_address=deleted_entry.source,
            digest=deleted_entry.source_digest,
            index=source_index,
            corrected=deleted_entry.status == "corrected",
            force_corrected=force_corrected,
            problems=problems,
        )
        if change is not None:
            (refused if change.refused else changes).append(change)
        new_deleted.append(replace(deleted_entry, source=new_source))

    if problems:
        raise ReanchorError(problems)

    updated = replace(
        labels,
        correspondences=tuple(new_correspondences),
        inserted=tuple(new_inserted),
        deleted=tuple(new_deleted),
    )
    return ReanchorReport(labels=updated, changes=tuple(changes), refused=tuple(refused))
