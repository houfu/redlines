"""The labelling tool: ``init`` / ``check`` / ``sign`` for one pair's ``labels.yaml`` (#142).

This is the second half of the tooling Section 3.3 of the M2 research document asks for --
"so the human only does judgement". It never labels moves, and it never signs: those are the
two things ADR-0034 keeps as a human's job (D-10, and the anti-self-marking mitigation in
§1.11.5), and this module's ``init`` deliberately leaves both undone.

- **``init <pair-dir>``** runs :func:`redlines.compare` over the pair's prepared
  ``source``/``test`` files (read via `benchmark.prepare`'s manifest, so it reads them under the
  same format and profile they were prepared for) and writes:

  - a **draft** ``labels.yaml``, every correspondence, insertion and deletion carrying
    ``status: proposed``. **No row is ever written with ``kind: move``.** A pair the engine
    reports as moved is written as an ordinary ``same``/``renumber`` correspondence instead --
    conservative, not a claim -- because ADR-0034 requires the move gate to be labelled
    independently of the engine that gate is checking; seeding it from the engine is exactly
    the self-marking risk ADR-0021 exists to catch. Its address pair is still recorded exactly
    once (the totality check does not care which ``kind`` it was proposed under), and
    `worksheet.md` flags it with ``?`` so the fact that the engine proposed a move is not lost,
    only kept out of the one number the move gate can never take on faith.
  - **``worksheet.md``**: every source block in document order, its proposed test counterpart
    (or none, if the engine reports it deleted), and a ``?`` flag on anything worth a close
    look -- see `_needs_attention` for the exact rule.
  - **``move_worksheet.md``**: the two clause lists side by side, in document order, address and
    label only -- **no engine proposal anywhere in it**. This is what a human actually labels
    moves from; the worksheet above exists so the engine's own guess is visible for context, but
    the move labelling itself starts from a blank slate, on purpose (§1.11.5, §3.3).

- **``check <pair-dir>``** validates schema, re-derives every digest against the committed
  files, and checks totality (`benchmark.labels.verify_digests` / `check_totality`). It does
  **not** object to a file left entirely ``proposed`` -- a draft is expected to be exactly that
  until a human has been through it.
- **``sign <pair-dir> --as NAME --role labeller|reviewer``** stamps ``review:`` with the name,
  the date and a digest of the label content, and **refuses if any row is still ``proposed``**:
  signing asserts a human looked at every row, which a freshly-``init``ed file has, by
  construction, not yet had.

Every hand-labelled pair this repository ships stays at the ``init`` stage -- ``status:
proposed`` throughout, no ``review:`` block -- until a maintainer has actually done the reading
`sign` refuses to let a machine skip.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

from redlines import compare
from redlines.blocks import Block, BlockTree

from benchmark.labels import (
    LABELLED_KINDS,
    Correspondence,
    DeletedEntry,
    InsertedEntry,
    LabelFile,
    Provenance,
    Review,
    Side,
    check_totality,
    digest_for,
    dump_labels,
    labelled_addresses,
    load_labels,
    override_rate,
    save_labels,
    verify_digests,
)

_MANIFEST_NAME = "prepare_manifest.json"
_TEXT_PREVIEW_CHARS = 80


class LabelToolError(RuntimeError):
    """``init``/``check``/``sign`` refused to proceed; the message says why."""


def load_manifest(pair_dir: Path) -> dict[str, Any]:
    """Read the ``prepare_manifest.json`` `benchmark.prepare` wrote for this pair.

    :raises LabelToolError: if the manifest is missing -- ``init`` has nothing to work from
        without it, since it is where the format, the profile and the provenance come from.
    """
    manifest_path = pair_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        raise LabelToolError(
            f"{pair_dir}: no {_MANIFEST_NAME} -- run benchmark/prepare.py for this pair first"
        )
    data: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    return data


def _preview(text: str) -> str:
    """The first `_TEXT_PREVIEW_CHARS` characters of a block's normalised text, one line."""
    collapsed = " ".join(text.split())
    if len(collapsed) <= _TEXT_PREVIEW_CHARS:
        return collapsed
    return collapsed[: _TEXT_PREVIEW_CHARS - 1] + "…"


# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_draft_labels(pair_dir: Path) -> tuple[LabelFile, BlockTree, BlockTree, Any]:
    """Run `redlines.compare` over one prepared pair and build its draft `LabelFile`.

    :return: the draft label file, the source and test trees `compare` built (so callers do
        not have to read and re-parse the documents a second time for the worksheet), and the
        `redlines.comparison.Comparison`'s alignment.
    """
    manifest = load_manifest(pair_dir)
    pair_id = manifest["pair"]
    source_path = pair_dir / manifest["source_file"]
    test_path = pair_dir / manifest["test_file"]
    source_text = source_path.read_text(encoding="utf-8")
    test_text = test_path.read_text(encoding="utf-8")

    result = compare(
        source_text,
        test_text,
        format=manifest["format"],
        profile=manifest["profile"],
    )
    source_tree = result.source
    test_tree = result.test
    alignment = result.alignment

    def is_labelled(tree: BlockTree, address: str) -> bool:
        try:
            return tree.block_at(address).kind in LABELLED_KINDS
        except (KeyError, ValueError):
            return False

    correspondences: list[Correspondence] = []
    for pair in alignment.pairs:
        if pair.matched_by == "root":
            continue  # D-10: the root pair is never part of the labelled set.
        if not (
            is_labelled(source_tree, pair.source_path)
            and is_labelled(test_tree, pair.test_path)
        ):
            continue
        source_block = source_tree.block_at(pair.source_path)
        test_block = test_tree.block_at(pair.test_path)
        # Never propose "move": see the module docstring. A block the engine also
        # thinks was renumbered still gets that recorded -- only the move claim itself
        # is withheld, and `worksheet.md`'s ``?`` flag keeps it visible.
        kind = "renumber" if pair.renumbered else "same"
        correspondences.append(
            Correspondence(
                source=pair.source_path,
                test=pair.test_path,
                kind=kind,
                source_label=source_block.label,
                test_label=test_block.label,
                source_digest=digest_for(source_block),
                test_digest=digest_for(test_block),
                status="proposed",
            )
        )

    inserted = [
        InsertedEntry(test=address, test_digest=digest_for(test_tree.block_at(address)), status="proposed")
        for address in alignment.inserted
        if is_labelled(test_tree, address)
    ]
    deleted = [
        DeletedEntry(
            source=address, source_digest=digest_for(source_tree.block_at(address)), status="proposed"
        )
        for address in alignment.deleted
        if is_labelled(source_tree, address)
    ]

    provenance = Provenance(
        kind=manifest["kind"],
        origin=manifest["origin"],
        licence=manifest.get("licence") or None,
        attribution=manifest.get("attribution") or None,
        prepared_by=manifest.get("prepared_by"),
        normalisations=tuple(manifest.get("normalisations", ())),
    )
    labels = LabelFile(
        pair=pair_id,
        source=Side(
            file=manifest["source_file"],
            format=manifest["format"],
            profile=manifest["profile"],
            sha256=_sha256_file(source_path),
        ),
        test=Side(
            file=manifest["test_file"],
            format=manifest["format"],
            profile=manifest["profile"],
            sha256=_sha256_file(test_path),
        ),
        provenance=provenance,
        correspondences=tuple(
            sorted(correspondences, key=lambda row: _address_sort_key(row.source))
        ),
        inserted=tuple(sorted(inserted, key=lambda row: _address_sort_key(row.test))),
        deleted=tuple(sorted(deleted, key=lambda row: _address_sort_key(row.source))),
    )
    return labels, source_tree, test_tree, alignment


_INDEX_RE = re.compile(r"\[(\d+)\]")


def _address_sort_key(address: str) -> tuple[int, ...]:
    """Sort addresses in document order: by each ``[n]`` index, not lexicographically."""
    return tuple(int(part) for part in _INDEX_RE.findall(address))


def _needs_attention(
    *, matched_by: str | None, confidence: float | None, moved: bool, fuzzy_floor: float
) -> bool:
    """Whether `worksheet.md` should flag this row ``?`` for a human's attention.

    Three reasons, per §1.11.5: matched by the ``positional`` pass (the weakest evidence
    the descent has), scored below the fuzzy floor even though some other pass accepted it
    (label and structural passes have their own, usually looser floors), or part of a move the
    engine proposed and this tool deliberately did not write into `labels.yaml`.
    """
    if moved:
        return True
    if matched_by == "positional":
        return True
    if confidence is not None and confidence < fuzzy_floor:
        return True
    return False


def write_worksheet(
    pair_dir: Path,
    *,
    source_tree: BlockTree,
    test_tree: BlockTree,
    alignment: Any,
) -> None:
    """Write the human-facing ``worksheet.md`` (§1.11.5, §3.3)."""
    fuzzy_floor = alignment.config.fuzzy_min_similarity
    pairs_by_source = {pair.source_path: pair for pair in alignment.pairs}

    lines = [
        f"# Worksheet: {pair_dir.name}",
        "",
        "Generated by `benchmark/label.py init` from the current alignment engine. Every row "
        "is a **proposal** in `labels.yaml`, not a decision -- confirm it (`status: confirmed`) "
        "or fix it (`status: corrected`). A row flagged `?` is where a human's attention "
        "belongs: matched by the weakest (`positional`) pass, scored below the fuzzy floor "
        f"({fuzzy_floor:.2f}), or part of a move the engine proposed -- moves are **never** "
        "written into `labels.yaml` from here; see `move_worksheet.md` instead, and label "
        "moves from that blank sheet, not from this column.",
        "",
        "| source | label | text | → | test | label | text | pass | confidence | ? |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]

    for source_address in labelled_addresses(source_tree):
        source_block = source_tree.block_at(source_address)
        pair = pairs_by_source.get(source_address)
        if pair is None:
            lines.append(
                f"| `{source_address}` | {source_block.label or ''} | "
                f"{_preview(source_block.text)} | → | *(deleted)* | | | | | |"
            )
            continue
        test_block = test_tree.block_at(pair.test_path)
        flag = "?" if _needs_attention(
            matched_by=pair.matched_by,
            confidence=pair.confidence,
            moved=pair.moved,
            fuzzy_floor=fuzzy_floor,
        ) else ""
        lines.append(
            f"| `{source_address}` | {source_block.label or ''} | "
            f"{_preview(source_block.text)} | → | `{pair.test_path}` | "
            f"{test_block.label or ''} | {_preview(test_block.text)} | "
            f"{pair.matched_by} | {pair.confidence:.2f} | {flag} |"
        )

    matched_test_addresses = {pair.test_path for pair in alignment.pairs}
    inserted_rows = [
        address
        for address in labelled_addresses(test_tree)
        if address not in matched_test_addresses
    ]
    if inserted_rows:
        lines += ["", "## Inserted in test, no source counterpart", ""]
        lines += ["| test | label | text |", "|---|---|---|"]
        for address in inserted_rows:
            block = test_tree.block_at(address)
            lines.append(f"| `{address}` | {block.label or ''} | {_preview(block.text)} |")

    (pair_dir / "worksheet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_move_worksheet(pair_dir: Path, *, source_tree: BlockTree, test_tree: BlockTree) -> None:
    """Write ``move_worksheet.md``: two clause lists, side by side, no engine proposals.

    Deliberately built from `labelled_addresses` alone -- never from `alignment.pairs` -- so
    nothing here carries a hint of which pass matched what. A human labels a move by reading
    both columns and noticing a clause on one side that reads like a clause elsewhere on the
    other, exactly as if the engine did not exist yet (§1.11.5, §3.3).
    """
    source_rows = [
        (address, block.label or "", _preview(block.text))
        for address in labelled_addresses(source_tree)
        for block in (source_tree.block_at(address),)
    ]
    test_rows = [
        (address, block.label or "", _preview(block.text))
        for address in labelled_addresses(test_tree)
        for block in (test_tree.block_at(address),)
    ]

    lines = [
        f"# Move worksheet: {pair_dir.name}",
        "",
        "Two clause lists, in document order, address and label only -- **no engine proposal "
        "anywhere on this page**. Read both columns fresh and note any clause that moved to a "
        "different position in the structure (not merely renumbered in place); write each one "
        "found as a `kind: move` row in `labels.yaml`, with `status: confirmed` or "
        "`corrected`. This is the one part of the labelling pass ADR-0034 requires to start "
        "from a blank sheet, never from the engine's own guess.",
        "",
        "| source | test |",
        "|---|---|",
    ]
    for index in range(max(len(source_rows), len(test_rows))):
        left = (
            f"`{source_rows[index][0]}` {source_rows[index][1]} -- {source_rows[index][2]}"
            if index < len(source_rows)
            else ""
        )
        right = (
            f"`{test_rows[index][0]}` {test_rows[index][1]} -- {test_rows[index][2]}"
            if index < len(test_rows)
            else ""
        )
        lines.append(f"| {left} | {right} |")

    (pair_dir / "move_worksheet.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def init_pair(pair_dir: Path) -> None:
    """Run `init` for one pair directory: writes ``labels.yaml``, both worksheets."""
    labels, source_tree, test_tree, alignment = build_draft_labels(pair_dir)
    save_labels(labels, pair_dir / "labels.yaml")
    write_worksheet(pair_dir, source_tree=source_tree, test_tree=test_tree, alignment=alignment)
    write_move_worksheet(pair_dir, source_tree=source_tree, test_tree=test_tree)


# --------------------------------------------------------------------------
# check
# --------------------------------------------------------------------------


def check_pair(pair_dir: Path) -> None:
    """Run `check` for one pair directory: schema, digests, totality.

    :raises benchmark.labels.LabelError: on a schema violation.
    :raises benchmark.labels.StaleDigestError: if a digest no longer matches its block.
    :raises benchmark.labels.TotalityError: if a labelled block is missing or duplicated.
    """
    from redlines.pipeline import read_document

    manifest = load_manifest(pair_dir)
    labels = load_labels(pair_dir / "labels.yaml")
    source_tree = read_document(
        (pair_dir / manifest["source_file"]).read_text(encoding="utf-8"),
        format=manifest["format"],
        profile=manifest["profile"],
    )
    test_tree = read_document(
        (pair_dir / manifest["test_file"]).read_text(encoding="utf-8"),
        format=manifest["format"],
        profile=manifest["profile"],
    )
    verify_digests(labels, source_tree=source_tree, test_tree=test_tree)
    check_totality(labels, source_tree=source_tree, test_tree=test_tree)


# --------------------------------------------------------------------------
# sign
# --------------------------------------------------------------------------


def _all_statuses(labels: LabelFile) -> list[str]:
    statuses = [row.status for row in labels.correspondences]
    statuses += [row.status for row in labels.inserted]
    statuses += [row.status for row in labels.deleted]
    statuses += [row.status for row in labels.splits]
    statuses += [row.status for row in labels.merges]
    return statuses


def sign_pair(
    pair_dir: Path,
    *,
    as_name: str,
    role: str,
    date: str | None = None,
    decision: str | None = None,
) -> None:
    """Run `sign` for one pair directory.

    :param role: ``"labeller"`` stamps ``labelled_by``/``labelled_at`` (and, since this is the
        first signature a fresh review acquires, computes ``override_rate``). ``"reviewer"``
        stamps ``reviewed_by``/``reviewed_at``/``decision`` onto an existing review -- it
        requires the pair to have been labelled first.
    :raises LabelToolError: if any row is still ``status: proposed``, or if ``role`` is
        ``"reviewer"`` and the pair has not been labelled yet.
    """
    path = pair_dir / "labels.yaml"
    labels = load_labels(path)
    remaining = [status for status in _all_statuses(labels) if status == "proposed"]
    if remaining:
        raise LabelToolError(
            f"{pair_dir}: {len(remaining)} row(s) still `status: proposed` -- "
            "confirm or correct every row before signing"
        )

    today = date or datetime.date.today().isoformat()
    if role == "labeller":
        review = Review(
            labelled_by=as_name,
            labelled_at=today,
            reviewed_by=labels.review.reviewed_by if labels.review else None,
            reviewed_at=labels.review.reviewed_at if labels.review else None,
            decision=labels.review.decision if labels.review else None,
            override_rate=override_rate(labels),
        )
    elif role == "reviewer":
        if labels.review is None:
            raise LabelToolError(f"{pair_dir}: no labeller signature yet -- run `sign --role labeller` first")
        review = Review(
            labelled_by=labels.review.labelled_by,
            labelled_at=labels.review.labelled_at,
            reviewed_by=as_name,
            reviewed_at=today,
            decision=decision,
            override_rate=labels.review.override_rate,
        )
    else:
        raise LabelToolError(f"unknown role {role!r}; expected 'labeller' or 'reviewer'")

    unsigned = LabelFile(
        pair=labels.pair,
        source=labels.source,
        test=labels.test,
        provenance=labels.provenance,
        correspondences=labels.correspondences,
        inserted=labels.inserted,
        deleted=labels.deleted,
        splits=labels.splits,
        merges=labels.merges,
        unscored=labels.unscored,
        review=review,
        move_verdicts=labels.move_verdicts,
    )
    signature = hashlib.sha256(dump_labels(unsigned).encode("utf-8")).hexdigest()
    signed_review = Review(
        labelled_by=review.labelled_by,
        labelled_at=review.labelled_at,
        reviewed_by=review.reviewed_by,
        reviewed_at=review.reviewed_at,
        decision=review.decision,
        override_rate=review.override_rate,
        signature=signature,
    )
    signed = LabelFile(
        pair=labels.pair,
        source=labels.source,
        test=labels.test,
        provenance=labels.provenance,
        correspondences=labels.correspondences,
        inserted=labels.inserted,
        deleted=labels.deleted,
        splits=labels.splits,
        merges=labels.merges,
        unscored=labels.unscored,
        review=signed_review,
        move_verdicts=labels.move_verdicts,
    )
    save_labels(signed, path)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Draft, check and sign a hand-labelled pair.")
    sub = parser.add_subparsers(dest="command", required=True)

    init_parser = sub.add_parser("init", help="run compare() and write a draft labels.yaml")
    init_parser.add_argument("pair_dir", type=Path)

    check_parser = sub.add_parser("check", help="validate schema, digests and totality")
    check_parser.add_argument("pair_dir", type=Path)

    sign_parser = sub.add_parser("sign", help="stamp review:, refusing while any row is proposed")
    sign_parser.add_argument("pair_dir", type=Path)
    sign_parser.add_argument("--as", dest="as_name", required=True)
    sign_parser.add_argument("--role", choices=("labeller", "reviewer"), required=True)
    sign_parser.add_argument("--date", default=None, help="ISO date; default today")
    sign_parser.add_argument("--decision", default=None, help="reviewer role only")

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            init_pair(args.pair_dir)
        elif args.command == "check":
            check_pair(args.pair_dir)
        elif args.command == "sign":
            sign_pair(
                args.pair_dir,
                as_name=args.as_name,
                role=args.role,
                date=args.date,
                decision=args.decision,
            )
    except LabelToolError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
