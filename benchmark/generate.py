"""Turn a committed mutation plan into the committed synthetic corpus (#141, ADR-0021).

`benchmark/plans/synthetic.yaml` names the source documents, the named mutation plans and the
pairs to build from them. This module reads that file, derives a seed per pair, runs
:mod:`benchmark.mutate` over each source document, and writes
``benchmark/corpus/synthetic/<pair>/{source,test}.{md,txt}`` plus the ``labels.yaml`` that
:mod:`benchmark.labels` validates and the metric (#143) scores against.

**Why the corpus is committed and regenerated in a test rather than generated in CI.** ADR-0034
puts the synthetic tier in the repository, documents and labels together, and has a test re-run
the generator and byte-compare -- the repository's existing golden discipline applied to a corpus.
A corpus generated afresh in each run would let a careless change to an operator silently move
every published number; a committed corpus makes that change a diff a reviewer reads.

**Seeding.** The seed for a pair is derived, not counted::

    seed = int.from_bytes(
        blake2b(f"{GENERATOR_VERSION}\\x00{document}\\x00{plan}".encode(), digest_size=8).digest(),
        "big",
    )

so adding a document or a plan changes no other pair's mutations. Counting seeds off a running
index would mean every growth of the corpus invalidated every number already published from it.
`GENERATOR_VERSION` lives here, is bumped deliberately, and lands in every pair's
``provenance.generator_version`` and in the report -- it is the one dial that is *meant* to move
the whole corpus at once.

**Determinism.** blake2b, `random.Random.randrange` and explicit list ordering only: no ``hash()``,
no ``set`` iteration in anything that reaches the output, no timestamps, and no locale-dependent
formatting. ``tests/test_benchmark_corpus.py`` regenerates the whole tier into a temporary
directory and byte-compares it, and re-runs the generator under several ``PYTHONHASHSEED``
values in a subprocess, so a draw that is stable only by luck fails the build.

Run it by hand with::

    uv run python -m benchmark.generate --check     # regenerate and report any drift
    uv run python -m benchmark.generate             # rewrite the committed tier
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from redlines.blocks import Block, BlockKind, BlockTree

from benchmark.labels import (
    Correspondence,
    DeletedEntry,
    InsertedEntry,
    LabelFile,
    MergeEntry,
    Provenance,
    Side,
    SplitEntry,
    check_totality,
    digest_for,
    dump_labels,
    verify_digests,
)
from benchmark.mutate import Document, Merge, MutationError, Split, Step, mutate, normalise

__all__ = [
    "GENERATOR_VERSION",
    "GENERATOR",
    "PLAN_PATH",
    "CORPUS_DIR",
    "DocumentSpec",
    "PlanSpec",
    "PairSpec",
    "Plan",
    "GeneratedPair",
    "seed_for",
    "repository_root",
    "load_plan",
    "generate_pair",
    "generate_corpus",
    "write_corpus",
    "main",
]

#: The generator's own version. Bumped deliberately, never as a side effect: every pair's
#: seed is derived from it, so changing it regenerates the whole tier and moves every number
#: computed from it (ADR-0034).
GENERATOR_VERSION = 1

GENERATOR = "benchmark/generate.py"

#: Where the committed plan and the committed corpus live, relative to the repository root.
PLAN_PATH = Path("benchmark") / "plans" / "synthetic.yaml"
CORPUS_DIR = Path("benchmark") / "corpus" / "synthetic"

#: The file extension each reader format's documents are written under.
_EXTENSIONS: dict[str, str] = {"markdown": "md", "text": "txt"}


def repository_root() -> Path:
    """Return the repository root, which is this unpackaged directory's parent."""
    return Path(__file__).resolve().parent.parent


def seed_for(document: str, plan: str, *, version: int = GENERATOR_VERSION) -> int:
    """Derive this pair's seed from the generator version, the document id and the plan id.

    Derived rather than counted so that adding a document or a plan leaves every other pair's
    mutations, and therefore every number already published from them, untouched.
    """
    material = f"{version}\x00{document}\x00{plan}".encode()
    return int.from_bytes(hashlib.blake2b(material, digest_size=8).digest(), "big")


# --------------------------------------------------------------------------
# The plan file
# --------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class DocumentSpec:
    """One source document the corpus mutates."""

    id: str
    path: str
    format: str
    profile: str
    origin: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentSpec:
        _reject_unknown(data, {"id", "path", "format", "profile", "origin"}, "a document")
        return cls(
            id=str(data["id"]),
            path=str(data["path"]),
            format=str(data["format"]),
            profile=str(data["profile"]),
            origin=str(data.get("origin", data["path"])),
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class PlanSpec:
    """One named mutation plan: a difficulty profile, as an ordered list of steps."""

    id: str
    description: str
    steps: tuple[Step, ...]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlanSpec:
        _reject_unknown(data, {"id", "description", "steps"}, "a plan")
        return cls(
            id=str(data["id"]),
            description=str(data.get("description", "")),
            steps=tuple(Step.from_dict(step) for step in data.get("steps", ())),
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class PairSpec:
    """One pair to build: a document, run under a plan."""

    document: str
    plan: str

    @property
    def pair_id(self) -> str:
        return f"{self.document}-{self.plan}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PairSpec:
        _reject_unknown(data, {"document", "plan"}, "a pair")
        return cls(document=str(data["document"]), plan=str(data["plan"]))


@dataclass(frozen=True, kw_only=True, slots=True)
class Plan:
    """The whole committed plan file."""

    documents: tuple[DocumentSpec, ...]
    plans: tuple[PlanSpec, ...]
    pairs: tuple[PairSpec, ...]

    def document(self, document_id: str) -> DocumentSpec:
        for spec in self.documents:
            if spec.id == document_id:
                return spec
        raise MutationError(f"the plan names no document {document_id!r}")

    def plan(self, plan_id: str) -> PlanSpec:
        for spec in self.plans:
            if spec.id == plan_id:
                return spec
        raise MutationError(f"the plan names no mutation plan {plan_id!r}")


def _reject_unknown(data: dict[str, Any], known: set[str], what: str) -> None:
    unknown = sorted(set(data) - known)
    if unknown:
        raise MutationError(f"unknown keys on {what}: {', '.join(unknown)}")


def load_plan(path: str | Path) -> Plan:
    """Load and validate ``benchmark/plans/synthetic.yaml``."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise MutationError(f"{path} is not a mapping")
    _reject_unknown(data, {"documents", "plans", "pairs"}, "the plan file")
    plan = Plan(
        documents=tuple(DocumentSpec.from_dict(item) for item in data.get("documents", ())),
        plans=tuple(PlanSpec.from_dict(item) for item in data.get("plans", ())),
        pairs=tuple(PairSpec.from_dict(item) for item in data.get("pairs", ())),
    )
    seen: set[str] = set()
    for pair in plan.pairs:
        plan.document(pair.document)
        plan.plan(pair.plan)
        if pair.pair_id in seen:
            raise MutationError(f"the plan names the pair {pair.pair_id!r} twice")
        seen.add(pair.pair_id)
    return plan


# --------------------------------------------------------------------------
# Generating one pair
# --------------------------------------------------------------------------


@dataclass(frozen=True, kw_only=True, slots=True)
class GeneratedPair:
    """One generated pair, as the exact files it is committed as."""

    pair_id: str
    files: tuple[tuple[str, str], ...]
    operations: tuple[str, ...]

    def write(self, directory: Path) -> None:
        """Write this pair's files into `directory`, creating it if it does not exist."""
        directory.mkdir(parents=True, exist_ok=True)
        for name, text in self.files:
            (directory / name).write_text(text, encoding="utf-8", newline="\n")


def _cells(block: Block) -> tuple[Block, ...]:
    return tuple(child for child in block.children if child.kind is BlockKind.CELL)


def _correspondence(
    source: Block, test: Block, kind: str, *, status: str = "confirmed"
) -> Correspondence:
    return Correspondence(
        source=source.path,
        test=test.path,
        kind=kind,
        source_label=source.label,
        test_label=test.label,
        source_digest=digest_for(source),
        test_digest=digest_for(test),
        status=status,
    )


def _paired_rows(source: Block, test: Block, kind: str) -> tuple[
    list[Correspondence], list[InsertedEntry], list[DeletedEntry]
]:
    """Rows for one matched block, plus its cells when it is a table row.

    Cells pair by sibling index, which is the rule #134 settles for tables: the markdown reader
    pads ragged rows, so a cell's position *is* its column, and a row whose cell count changed
    reports the surplus as an insertion or a deletion of individual cells rather than failing to
    match at all.
    """
    correspondences = [_correspondence(source, test, kind)]
    inserted: list[InsertedEntry] = []
    deleted: list[DeletedEntry] = []
    if source.kind is not BlockKind.ROW:
        return correspondences, inserted, deleted
    source_cells, test_cells = _cells(source), _cells(test)
    shared = min(len(source_cells), len(test_cells))
    for index in range(shared):
        correspondences.append(_correspondence(source_cells[index], test_cells[index], "same"))
    for cell in test_cells[shared:]:
        inserted.append(
            InsertedEntry(test=cell.path, test_digest=digest_for(cell), status="confirmed")
        )
    for cell in source_cells[shared:]:
        deleted.append(
            DeletedEntry(source=cell.path, source_digest=digest_for(cell), status="confirmed")
        )
    return correspondences, inserted, deleted


def _inserted_rows(block: Block) -> list[InsertedEntry]:
    blocks = [block, *_cells(block)]
    return [
        InsertedEntry(test=item.path, test_digest=digest_for(item), status="confirmed")
        for item in blocks
    ]


def _deleted_rows(block: Block) -> list[DeletedEntry]:
    blocks = [block, *_cells(block)]
    return [
        DeletedEntry(source=item.path, source_digest=digest_for(item), status="confirmed")
        for item in blocks
    ]


def _check_alignment(mutated: Document, reread: Document, pair_id: str) -> None:
    """Assert the re-read test document has the units the mutation says it has.

    The mutation works on lines; the labels are addresses in the tree those lines read as. If a
    mutation changed how the reader groups the text -- a merge the reader split back apart, an
    inserted clause it read as two blocks -- then unit *i* is no longer block *i* and every label
    after it would name the wrong address. This is the check that turns that into a build failure.
    """
    if len(mutated.units) != len(reread.units):
        raise MutationError(
            f"{pair_id}: the mutated text has {len(mutated.units)} units but reads as "
            f"{len(reread.units)} blocks; an operator changed how the reader groups the text"
        )
    for index, (expected, actual) in enumerate(zip(mutated.units, reread.units)):
        if normalise(expected.text) != normalise(actual.text):
            raise MutationError(
                f"{pair_id}: unit {index} was written as {normalise(expected.text)[:60]!r} "
                f"but reads back as {normalise(actual.text)[:60]!r}"
            )


def generate_pair(pair: PairSpec, plan: Plan, *, root: Path | None = None) -> GeneratedPair:
    """Build one pair: the copied source, the mutated test, and the labels for both.

    :param pair: which document to mutate under which plan.
    :param plan: the loaded plan file, for the document and plan specifications.
    :param root: the repository root, for resolving the document's path. Defaults to this
        directory's parent.
    :return: the pair's files, ready to write.
    :raises MutationError: if the document does not fit the line model, if a mutation changed
        how the reader groups the text, or if the labels it produced are not total.
    """
    root = root or repository_root()
    document_spec = plan.document(pair.document)
    plan_spec = plan.plan(pair.plan)
    source_text = (root / document_spec.path).read_text(encoding="utf-8")
    source_document = Document.from_text(
        source_text, format=document_spec.format, profile=document_spec.profile
    )
    seed = seed_for(document_spec.id, plan_spec.id)
    mutation = mutate(source_document, plan_spec.steps, seed)
    test_text = mutation.document.render()
    test_document = Document.from_text(
        test_text, format=document_spec.format, profile=document_spec.profile
    )
    _check_alignment(mutation.document, test_document, pair.pair_id)

    source_tree = source_document.tree()
    test_tree = test_document.tree()
    labels = _label_file(
        pair=pair,
        document_spec=document_spec,
        plan_spec=plan_spec,
        seed=seed,
        source_text=source_text,
        test_text=test_text,
        source_document=source_document,
        mutation_units=mutation.document.units,
        test_document=test_document,
        source_tree=source_tree,
        test_tree=test_tree,
        moved=mutation.moved,
        inserted=mutation.inserted,
        deleted=mutation.deleted,
        splits=mutation.splits,
        merges=mutation.merges,
    )
    verify_digests(labels, source_tree=source_tree, test_tree=test_tree)
    check_totality(labels, source_tree=source_tree, test_tree=test_tree)

    extension = _EXTENSIONS.get(document_spec.format, "txt")
    return GeneratedPair(
        pair_id=pair.pair_id,
        files=(
            (f"source.{extension}", source_text),
            (f"test.{extension}", test_text),
            ("labels.yaml", dump_labels(labels)),
        ),
        operations=mutation.operations,
    )


def _label_file(
    *,
    pair: PairSpec,
    document_spec: DocumentSpec,
    plan_spec: PlanSpec,
    seed: int,
    source_text: str,
    test_text: str,
    source_document: Document,
    mutation_units: tuple[Any, ...],
    test_document: Document,
    source_tree: BlockTree,
    test_tree: BlockTree,
    moved: frozenset[str],
    inserted: frozenset[str],
    deleted: tuple[str, ...],
    splits: tuple[Split, ...],
    merges: tuple[Merge, ...],
) -> LabelFile:
    """Turn the mutation's ground truth into a `benchmark.labels.LabelFile`.

    Every labelled block on each side lands in exactly one list, because every block belongs to
    exactly one unit and every unit is in exactly one category: matched to a source unit,
    inserted, deleted, or a product of a split or a merge. `benchmark.labels.check_totality`
    then verifies that against the trees, so the claim is checked and not merely intended.
    """
    source_units = {unit.uid: unit for unit in source_document.units}
    test_address = {
        mutated.uid: read.address
        for mutated, read in zip(mutation_units, test_document.units)
    }
    split_products = {uid: split for split in splits for uid in split.tests}
    merge_products = {merge.test: merge for merge in merges}

    correspondences: list[Correspondence] = []
    inserted_rows: list[InsertedEntry] = []
    deleted_rows: list[DeletedEntry] = []
    split_rows: list[SplitEntry] = []
    merge_rows: list[MergeEntry] = []

    for unit in mutation_units:
        if unit.uid in split_products or unit.uid in merge_products:
            continue
        test_block = test_tree.block_at(test_address[unit.uid])
        if unit.uid in inserted or unit.origin is None:
            inserted_rows.extend(_inserted_rows(test_block))
            continue
        source_block = source_tree.block_at(source_units[unit.origin].address)
        if unit.uid in moved:
            kind = "move"
        elif source_block.label != test_block.label:
            kind = "renumber"
        else:
            kind = "same"
        paired, extra_inserted, extra_deleted = _paired_rows(source_block, test_block, kind)
        correspondences.extend(paired)
        inserted_rows.extend(extra_inserted)
        deleted_rows.extend(extra_deleted)

    for uid in deleted:
        deleted_rows.extend(_deleted_rows(source_tree.block_at(source_units[uid].address)))

    for split in splits:
        source_block = source_tree.block_at(source_units[split.source].address)
        test_blocks = [test_tree.block_at(test_address[uid]) for uid in split.tests]
        split_rows.append(
            SplitEntry(
                source=source_block.path,
                tests=tuple(block.path for block in test_blocks),
                source_digest=digest_for(source_block),
                test_digests=tuple(digest_for(block) for block in test_blocks),
                status="confirmed",
            )
        )

    for merge in merges:
        source_blocks = [
            source_tree.block_at(source_units[uid].address) for uid in merge.sources
        ]
        test_block = test_tree.block_at(test_address[merge.test])
        merge_rows.append(
            MergeEntry(
                sources=tuple(block.path for block in source_blocks),
                test=test_block.path,
                source_digests=tuple(digest_for(block) for block in source_blocks),
                test_digest=digest_for(test_block),
                status="confirmed",
            )
        )

    extension = _EXTENSIONS.get(document_spec.format, "txt")
    return LabelFile(
        pair=pair.pair_id,
        source=Side(
            file=f"source.{extension}",
            format=document_spec.format,
            profile=document_spec.profile,
            sha256=hashlib.sha256(source_text.encode("utf-8")).hexdigest(),
        ),
        test=Side(
            file=f"test.{extension}",
            format=document_spec.format,
            profile=document_spec.profile,
            sha256=hashlib.sha256(test_text.encode("utf-8")).hexdigest(),
        ),
        provenance=Provenance(
            kind="synthetic",
            origin=f"{document_spec.origin} + plan:{plan_spec.id}",
            generator=GENERATOR,
            generator_version=GENERATOR_VERSION,
            seed=seed,
            plan=plan_spec.id,
        ),
        correspondences=tuple(correspondences),
        inserted=tuple(inserted_rows),
        deleted=tuple(deleted_rows),
        splits=tuple(split_rows),
        merges=tuple(merge_rows),
    )


# --------------------------------------------------------------------------
# Generating and writing the whole tier
# --------------------------------------------------------------------------


def generate_corpus(plan: Plan, *, root: Path | None = None) -> tuple[GeneratedPair, ...]:
    """Generate every pair the plan names, in the plan's own order."""
    root = root or repository_root()
    return tuple(generate_pair(pair, plan, root=root) for pair in plan.pairs)


def write_corpus(
    pairs: tuple[GeneratedPair, ...], directory: Path, *, prune: bool = True
) -> None:
    """Write every pair into `directory`, one sub-directory per pair.

    :param prune: remove sub-directories the plan no longer names, so a pair dropped from the
        plan leaves the corpus rather than lingering with stale labels.
    """
    directory.mkdir(parents=True, exist_ok=True)
    for pair in pairs:
        pair.write(directory / pair.pair_id)
    if not prune:
        return
    wanted = {pair.pair_id for pair in pairs}
    for child in sorted(directory.iterdir()):
        if child.is_dir() and child.name not in wanted:
            shutil.rmtree(child)


def main(argv: list[str] | None = None) -> int:
    """Regenerate the committed synthetic tier, or check it for drift."""
    parser = argparse.ArgumentParser(description=__doc__ or "", add_help=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="do not write; report any file that would change and exit non-zero",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write into this directory instead of benchmark/corpus/synthetic",
    )
    parser.add_argument("--plan", type=Path, default=None, help="a plan file to use instead")
    arguments = parser.parse_args(argv)

    root = repository_root()
    plan = load_plan(arguments.plan or (root / PLAN_PATH))
    pairs = generate_corpus(plan, root=root)
    destination = arguments.out or (root / CORPUS_DIR)

    if arguments.check:
        drifted = [
            f"{pair.pair_id}/{name}"
            for pair in pairs
            for name, text in pair.files
            if not (destination / pair.pair_id / name).is_file()
            or (destination / pair.pair_id / name).read_text(encoding="utf-8") != text
        ]
        if drifted:
            print(f"{len(drifted)} file(s) differ from the committed corpus:", file=sys.stderr)
            for name in drifted:
                print(f"  {name}", file=sys.stderr)
            return 1
        print(f"{len(pairs)} pairs match the committed corpus")
        return 0

    write_corpus(pairs, destination)
    for pair in pairs:
        print(f"  {pair.pair_id}: {len(pair.operations)} mutation(s)")
    print(f"wrote {len(pairs)} pairs into {destination}")
    return 0


if __name__ == "__main__":  # pragma: no cover - a script entry point
    raise SystemExit(main())
