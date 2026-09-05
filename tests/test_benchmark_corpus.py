"""The synthetic corpus and the generator that writes it (#141, ADR-0021, ADR-0034).

`benchmark/corpus/synthetic/` is committed -- documents *and* labels -- and this module is what
makes that commitment mean something. Three things are checked, in rising order of how badly a
failure would matter:

1. **The committed tier is exactly what the generator writes today.** Every pair is regenerated
   into a temporary directory and compared byte for byte, which is the repository's existing
   golden discipline (``tests/corpus/regenerate_goldens.py`` plus ``tests/test_corpus.py``)
   applied to a corpus. Without it, a careless edit to an operator would silently move every
   number published from these pairs and nothing would say so.
2. **Every label file is loadable, anchored and total.** ADR-0034's own two checks -- every
   digest still matches the block it names, and every labelled block on each side appears exactly
   once -- run over the committed tier here, so a reader change that rots the addresses is a red
   test rather than a quiet drop in recall.
3. **The generator is deterministic in the ways it claims to be.** Seeds are derived, not
   counted, so adding a document or a plan leaves every other pair alone; and generation does not
   depend on ``PYTHONHASHSEED``, checked by running it in a subprocess under several values,
   because the corpus has to come out identical on all five Python versions in CI.

The negative control gets its own test: a block the ``whitespace_only`` operator touched must
come back as ``kind: same`` with an *identical* digest on both sides. An engine that reports a
change there has lost precision, and this is what makes the labels say so.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from redlines.blocks import BlockTree
from redlines.pipeline import read_document

from benchmark.generate import (
    CORPUS_DIR,
    GENERATOR_VERSION,
    PLAN_PATH,
    generate_corpus,
    generate_pair,
    load_plan,
    repository_root,
    seed_for,
)
from benchmark.labels import (
    LabelFile,
    check_totality,
    digest_for,
    labelled_addresses,
    load_labels,
    verify_digests,
)
from benchmark.mutate import EDIT_STYLES, OPERATORS, Document, MutationError, Step, mutate

ROOT = repository_root()
CORPUS = ROOT / CORPUS_DIR
PLAN = load_plan(ROOT / PLAN_PATH)

#: Every pair id the plan names, so a failure says which pair rather than which index.
PAIR_IDS: tuple[str, ...] = tuple(pair.pair_id for pair in PLAN.pairs)

#: The corpus is committed, so it competes with everything else in a checkout for the reader's
#: patience and for the repository's size. ADR-0034 targets 30-40 pairs; this is the ceiling that
#: keeps "commit the documents" affordable.
MAX_CORPUS_BYTES = 2 * 1024 * 1024


def _trees(directory: Path, labels: LabelFile) -> tuple[BlockTree, BlockTree]:
    source = (directory / labels.source.file).read_text(encoding="utf-8")
    test = (directory / labels.test.file).read_text(encoding="utf-8")
    return (
        read_document(source, format=labels.source.format, profile=labels.source.profile),
        read_document(test, format=labels.test.format, profile=labels.test.profile),
    )


# --------------------------------------------------------------------------
# The committed tier is what the generator writes
# --------------------------------------------------------------------------


def test_the_plan_names_between_thirty_and_fifty_pairs() -> None:
    assert 30 <= len(PLAN.pairs) <= 50
    assert len(PLAN.documents) >= 8


def test_every_pair_the_plan_names_is_committed() -> None:
    committed = {child.name for child in CORPUS.iterdir() if child.is_dir()}
    assert committed == set(PAIR_IDS)


@pytest.mark.parametrize("pair_id", PAIR_IDS)
def test_regenerating_a_pair_reproduces_the_committed_bytes(pair_id: str, tmp_path: Path) -> None:
    """The committed corpus is exactly what today's generator writes, file by file."""
    spec = next(pair for pair in PLAN.pairs if pair.pair_id == pair_id)
    generated = generate_pair(spec, PLAN, root=ROOT)
    generated.write(tmp_path)
    committed = CORPUS / pair_id
    for name, _ in generated.files:
        assert (committed / name).read_bytes() == (tmp_path / name).read_bytes(), (
            f"{pair_id}/{name} differs from the committed corpus; "
            "re-run `uv run python -m benchmark.generate` and commit the result"
        )


def test_the_whole_corpus_regenerates_byte_for_byte(tmp_path: Path) -> None:
    """The same check as above, taken over the whole tier at once, including file names."""
    for pair in generate_corpus(PLAN, root=ROOT):
        directory = tmp_path / pair.pair_id
        pair.write(directory)
        committed = CORPUS / pair.pair_id
        assert sorted(path.name for path in directory.iterdir()) == sorted(
            path.name for path in committed.iterdir()
        )
    assert sorted(path.name for path in tmp_path.iterdir()) == sorted(PAIR_IDS)


def test_the_committed_corpus_stays_small() -> None:
    total = sum(path.stat().st_size for path in CORPUS.rglob("*") if path.is_file())
    assert total <= MAX_CORPUS_BYTES, f"the synthetic corpus is {total / 1024:.0f} KB"


# --------------------------------------------------------------------------
# Every label file loads, is anchored, and is total
# --------------------------------------------------------------------------


@pytest.mark.parametrize("pair_id", PAIR_IDS)
def test_every_labels_file_loads_and_validates(pair_id: str) -> None:
    labels = load_labels(CORPUS / pair_id / "labels.yaml")
    assert labels.pair == pair_id
    assert labels.provenance.kind == "synthetic"
    assert labels.provenance.generator_version == GENERATOR_VERSION
    assert all(row.status == "confirmed" for row in labels.correspondences)


@pytest.mark.parametrize("pair_id", PAIR_IDS)
def test_every_labels_file_is_anchored_and_total(pair_id: str) -> None:
    """ADR-0034's two load-time checks, over the committed tier."""
    directory = CORPUS / pair_id
    labels = load_labels(directory / "labels.yaml")
    source_tree, test_tree = _trees(directory, labels)
    verify_digests(labels, source_tree=source_tree, test_tree=test_tree)
    check_totality(labels, source_tree=source_tree, test_tree=test_tree)


@pytest.mark.parametrize("pair_id", PAIR_IDS)
def test_the_committed_documents_are_the_ones_the_labels_name(pair_id: str) -> None:
    """A label file names a specific, checkable document; here the sha256 is checked."""
    directory = CORPUS / pair_id
    labels = load_labels(directory / "labels.yaml")
    for side in (labels.source, labels.test):
        digest = hashlib.sha256((directory / side.file).read_bytes()).hexdigest()
        assert digest == side.sha256, f"{pair_id}/{side.file} is not the file the labels name"


def test_every_labelled_block_is_covered_exactly_once_on_both_sides() -> None:
    """The totality claim, restated as counts, so a failure says how many rather than which."""
    for pair_id in PAIR_IDS:
        directory = CORPUS / pair_id
        labels = load_labels(directory / "labels.yaml")
        source_tree, test_tree = _trees(directory, labels)
        rows = (
            len(labels.correspondences)
            + len(labels.deleted)
            + len(labels.splits)
            + sum(len(merge.sources) for merge in labels.merges)
        )
        assert rows == len(labelled_addresses(source_tree)), pair_id
        rows = (
            len(labels.correspondences)
            + len(labels.inserted)
            + sum(len(split.tests) for split in labels.splits)
            + len(labels.merges)
        )
        assert rows == len(labelled_addresses(test_tree)), pair_id


def test_the_corpus_exercises_every_correspondence_kind() -> None:
    """Moves, renumberings, insertions, deletions, splits and merges all actually occur.

    A corpus of nothing but ``same`` rows would pass every other test in this module and measure
    nothing, so the shape of the ground truth is asserted rather than assumed.
    """
    kinds: dict[str, int] = {"same": 0, "move": 0, "renumber": 0}
    inserted = deleted = splits = merges = 0
    for pair_id in PAIR_IDS:
        labels = load_labels(CORPUS / pair_id / "labels.yaml")
        for row in labels.correspondences:
            kinds[row.kind] += 1
        inserted += len(labels.inserted)
        deleted += len(labels.deleted)
        splits += len(labels.splits)
        merges += len(labels.merges)
    assert kinds["move"] >= 10
    assert kinds["renumber"] >= 20
    assert kinds["same"] >= 500
    assert inserted >= 10
    assert deleted >= 10
    assert splits >= 1
    assert merges >= 1


# --------------------------------------------------------------------------
# The negative control
# --------------------------------------------------------------------------


def test_whitespace_only_changes_leave_the_labels_alone() -> None:
    """A re-wrapped or re-spaced block is ``same`` with an identical digest on both sides.

    Built here rather than read out of the committed tier because the labels do not record which
    operator touched which block: the plan below applies nothing *but* the negative control, so
    every row in the result is a statement about it.
    """
    spec = next(pair for pair in PLAN.pairs if pair.document == "msa-markdown")
    document = PLAN.document(spec.document)
    text = (ROOT / document.path).read_text(encoding="utf-8")
    source = Document.from_text(text, format=document.format, profile=document.profile)
    mutation = mutate(source, (Step(op="whitespace_only", count=6),), seed_for("noise", "control"))

    assert mutation.operations, "the negative control applied nothing at all"
    assert not mutation.moved and not mutation.inserted and not mutation.deleted
    assert mutation.document.render() != text, "the whitespace was not actually changed"

    mutated = mutation.document.render()
    before = read_document(text, format=document.format, profile=document.profile)
    after = read_document(mutated, format=document.format, profile=document.profile)
    assert labelled_addresses(before) == labelled_addresses(after)
    for address in labelled_addresses(before):
        assert digest_for(before.block_at(address)) == digest_for(after.block_at(address)), address


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------


def test_seeds_are_derived_from_the_document_and_the_plan() -> None:
    """Adding a document or a plan must not move any other pair's mutations."""
    assert seed_for("msa-markdown", "light") == seed_for("msa-markdown", "light")
    assert seed_for("msa-markdown", "light") != seed_for("msa-markdown", "heavy")
    assert seed_for("msa-markdown", "light") != seed_for("msa-text", "light")
    assert seed_for("msa-markdown", "light") != seed_for(
        "msa-markdown", "light", version=GENERATOR_VERSION + 1
    )


def test_the_seed_derivation_is_a_fixed_function() -> None:
    """Pinned so that a refactor of `seed_for` cannot quietly regenerate the whole corpus."""
    assert seed_for("msa-markdown", "light", version=1) == 5217621202816455685


def test_every_pair_records_the_seed_it_was_generated_with() -> None:
    for pair in PLAN.pairs:
        labels = load_labels(CORPUS / pair.pair_id / "labels.yaml")
        assert labels.provenance.seed == seed_for(pair.document, pair.plan)
        assert labels.provenance.plan == pair.plan


def test_generation_does_not_depend_on_the_hash_seed(tmp_path: Path) -> None:
    """Run the generator in a subprocess under several ``PYTHONHASHSEED`` values and compare.

    ``set`` iteration order and ``hash()`` are the classic ways a generator ends up stable on one
    machine and not another. The committed corpus has to be identical on five Python versions, so
    this is checked by actually varying the thing rather than by grepping for ``set``.
    """
    subset = tmp_path / "subset.yaml"
    subset.write_text(_subset_plan(), encoding="utf-8")
    outputs: list[dict[str, str]] = []
    for hash_seed in ("0", "1", "12345"):
        destination = tmp_path / f"out-{hash_seed}"
        environment = dict(os.environ, PYTHONHASHSEED=hash_seed)
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "benchmark.generate",
                "--plan",
                str(subset),
                "--out",
                str(destination),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        outputs.append(
            {
                str(path.relative_to(destination)): path.read_text(encoding="utf-8")
                for path in sorted(destination.rglob("*"))
                if path.is_file()
            }
        )
    assert outputs[0], "the subset plan generated nothing"
    assert outputs[0] == outputs[1] == outputs[2]


def _subset_plan() -> str:
    """A three-pair plan, so the hash-seed matrix costs three short subprocesses, not three runs."""
    text = (ROOT / PLAN_PATH).read_text(encoding="utf-8")
    head = text[: text.index("pairs:\n")]
    return head + "pairs:\n" + "\n".join(
        f"  - {{document: {document}, plan: {plan}}}"
        for document, plan in (
            ("msa-markdown", "mixed"),
            ("msa-text", "renumber-storm"),
            ("alpha-roman", "structure"),
        )
    ) + "\n"


# --------------------------------------------------------------------------
# The plan file and the operators
# --------------------------------------------------------------------------


def test_the_plan_exercises_every_operator_on_every_document() -> None:
    """"Every operator on every source" is what the `mixed` plan is for.

    An operator with nothing to work on in a given document -- a table edit where there is no
    table -- is a no-op, not a failure, so this asserts that every document is *offered* every
    operator rather than that every operator fired everywhere, which no single corpus could
    honestly claim.
    """
    mixed = PLAN.plan("mixed")
    assert {step.op for step in mixed.steps} == set(OPERATORS)
    assert {step.style for step in mixed.steps if step.op == "edit_text"} == set(EDIT_STYLES)
    documents_with_mixed = {pair.document for pair in PLAN.pairs if pair.plan == "mixed"}
    assert documents_with_mixed == {document.id for document in PLAN.documents}


def test_every_plan_and_document_the_file_declares_is_used() -> None:
    used_documents = {pair.document for pair in PLAN.pairs}
    used_plans = {pair.plan for pair in PLAN.pairs}
    assert used_documents == {document.id for document in PLAN.documents}
    assert used_plans == {plan.id for plan in PLAN.plans}


def test_an_unknown_operator_is_rejected_by_name() -> None:
    with pytest.raises(MutationError, match="unknown operator 'teleport'"):
        Step.from_dict({"op": "teleport"})


def test_an_unknown_plan_key_is_rejected() -> None:
    with pytest.raises(MutationError, match="unknown plan step keys: repeat"):
        Step.from_dict({"op": "edit_text", "repeat": 2})


@pytest.mark.parametrize("document_id", [document.id for document in PLAN.documents])
def test_every_source_document_round_trips_through_the_unit_model(document_id: str) -> None:
    """`Document.from_text` must reproduce its input exactly, or the labels describe nothing."""
    spec = PLAN.document(document_id)
    text = (ROOT / spec.path).read_text(encoding="utf-8")
    document = Document.from_text(text, format=spec.format, profile=spec.profile)
    assert document.render() == text
    assert len(document.units) == len(labelled_addresses(document.tree())) - sum(
        len(block.children)
        for block in document.tree().walk()
        if block.kind.value == "row"
    )


# --------------------------------------------------------------------------
# The dev-only fetch script's one safety property
# --------------------------------------------------------------------------


def test_the_fetch_script_refuses_to_write_outside_the_gitignored_directory(
    tmp_path: Path,
) -> None:
    """AGPL-derived text never leaves ``benchmark/corpus/external/``, and this is what enforces it.

    No network, no clone, no python-docx: the guard is a path check, and the whole licence story
    of `benchmark.fetch_neurotic` rests on it holding for a destination somebody passed by
    mistake rather than on every caller being careful.
    """
    from benchmark.fetch_neurotic import FetchError, extract_document, external_root

    assert external_root(ROOT) == ROOT / "benchmark" / "corpus" / "external"
    with pytest.raises(FetchError, match="refusing to write"):
        extract_document(tmp_path / "base.docx", ROOT / "benchmark" / "corpus" / "leaked.txt", ROOT)
    with pytest.raises(FetchError, match="refusing to write"):
        extract_document(tmp_path / "base.docx", tmp_path / "elsewhere.txt", ROOT)


def test_the_external_tier_is_gitignored() -> None:
    ignore = (ROOT / "benchmark" / "corpus" / ".gitignore").read_text(encoding="utf-8")
    assert "external/" in ignore.splitlines()
