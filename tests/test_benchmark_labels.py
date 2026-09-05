"""Tests for the benchmark label format: schema, dataclasses, digests, totality (D-7, ADR-0034).

Two hand-written fixture pairs live under ``tests/corpus/benchmark_labels/``: ``simple/`` (an
insertion, a deletion, and two in-place edits, no move or renumber) and ``renumber/`` (an insertion
at the top pushes every following clause's label up by one, tested as a run of ``kind: renumber``
rows). Both are read through `redlines.pipeline.read_document`, exactly as a real pair would be, so
these tests exercise the label format against real `redlines.blocks.BlockTree` output rather than a
hand-built tree that might not look like one.

This module tests the *format* -- schema validation, the dataclasses, the canonical dumper, digest
computation, the totality check and `benchmark.reanchor.reanchor` -- not the metric or the generator,
which are separate tracks (#141, #143) landing on other branches.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from redlines.blocks import BlockTree
from redlines.pipeline import read_document

from benchmark.labels import (
    LABELLED_KINDS,
    LabelError,
    LabelFile,
    StaleDigestError,
    TotalityError,
    check_totality,
    digest_for,
    dump_labels,
    label_schema_text,
    labelled_addresses,
    labels_from_mapping,
    labels_from_yaml,
    load_labels,
    normalise_text,
    override_rate,
    save_labels,
    to_mapping,
    verify_digests,
)
from benchmark.reanchor import ReanchorError, reanchor

CASE_DIR = Path(__file__).parent / "corpus" / "benchmark_labels"


def _tree(path: Path) -> BlockTree:
    return read_document(path.read_text(encoding="utf-8"), format="text", profile="contract")


@pytest.fixture
def simple_trees() -> tuple[BlockTree, BlockTree]:
    directory = CASE_DIR / "simple"
    return _tree(directory / "source.txt"), _tree(directory / "test.txt")


@pytest.fixture
def simple_labels() -> LabelFile:
    return load_labels(CASE_DIR / "simple" / "labels.yaml")


@pytest.fixture
def renumber_trees() -> tuple[BlockTree, BlockTree]:
    directory = CASE_DIR / "renumber"
    return _tree(directory / "source.txt"), _tree(directory / "test.txt")


@pytest.fixture
def renumber_labels() -> LabelFile:
    return load_labels(CASE_DIR / "renumber" / "labels.yaml")


# --------------------------------------------------------------------------
# The schema itself
# --------------------------------------------------------------------------


def test_schema_text_is_valid_json_and_draft_07() -> None:
    import json

    schema = json.loads(label_schema_text())
    assert schema["$schema"] == "http://json-schema.org/draft-07/schema#"
    assert schema["type"] == "object"
    assert "correspondences" in schema["properties"]


def test_labelled_kinds_excludes_only_the_three_containers() -> None:
    from redlines.blocks import BlockKind

    excluded = frozenset(BlockKind) - LABELLED_KINDS
    assert excluded == {BlockKind.DOCUMENT, BlockKind.SECTION, BlockKind.TABLE}


# --------------------------------------------------------------------------
# Loading and validating a well-formed file
# --------------------------------------------------------------------------


def test_load_labels_reads_the_simple_fixture(simple_labels: LabelFile) -> None:
    assert simple_labels.pair == "simple-fixture"
    assert simple_labels.provenance.kind == "hand"
    assert len(simple_labels.correspondences) == 8
    assert len(simple_labels.inserted) == 1
    assert len(simple_labels.deleted) == 1
    assert simple_labels.review is not None
    assert simple_labels.review.labelled_by == "houfu"


def test_load_labels_reads_the_renumber_fixture(renumber_labels: LabelFile) -> None:
    kinds = {row.kind for row in renumber_labels.correspondences}
    assert kinds == {"renumber"}
    assert renumber_labels.correspondences[0].source_label == "1"
    assert renumber_labels.correspondences[0].test_label == "2"
    assert len(renumber_labels.move_verdicts) == 1
    assert renumber_labels.move_verdicts[0].verdict == "acceptable"


def test_missing_required_key_raises_label_error() -> None:
    mapping = {
        "schema": "redlines/alignment-labels/1",
        "pair": "broken",
        # "source" missing entirely
        "test": {"file": "t.txt", "format": "text", "profile": "contract", "sha256": "a" * 64},
        "provenance": {"kind": "hand", "origin": "nowhere"},
        "correspondences": [],
        "inserted": [],
        "deleted": [],
    }
    with pytest.raises(LabelError) as excinfo:
        labels_from_mapping(mapping)
    assert excinfo.value.errors  # at least one message, naming the problem


def test_unknown_top_level_key_is_rejected(simple_labels: LabelFile) -> None:
    mapping = to_mapping(simple_labels)
    mapping["not_a_real_field"] = True
    with pytest.raises(LabelError):
        labels_from_mapping(mapping)


def test_bad_kind_enum_value_is_rejected(simple_labels: LabelFile) -> None:
    mapping = to_mapping(simple_labels)
    mapping["correspondences"][0]["kind"] = "teleported"
    with pytest.raises(LabelError):
        labels_from_mapping(mapping)


def test_malformed_yaml_raises_label_error() -> None:
    with pytest.raises(LabelError):
        labels_from_yaml("pair: [unterminated")


def test_wrong_schema_version_is_rejected(simple_labels: LabelFile) -> None:
    mapping = to_mapping(simple_labels)
    mapping["schema"] = "redlines/alignment-labels/2"
    with pytest.raises(LabelError):
        labels_from_mapping(mapping)


# --------------------------------------------------------------------------
# The canonical dumper
# --------------------------------------------------------------------------


def test_dump_labels_round_trips(simple_labels: LabelFile) -> None:
    dumped = dump_labels(simple_labels)
    reloaded = labels_from_yaml(dumped)
    assert to_mapping(reloaded) == to_mapping(simple_labels)


def test_dump_labels_is_deterministic(simple_labels: LabelFile) -> None:
    assert dump_labels(simple_labels) == dump_labels(simple_labels)


def test_dump_labels_key_order_matches_schema(simple_labels: LabelFile) -> None:
    dumped = dump_labels(simple_labels)
    mapping = yaml.safe_load(dumped)
    assert list(mapping.keys()) == [
        "schema",
        "pair",
        "source",
        "test",
        "provenance",
        "correspondences",
        "inserted",
        "deleted",
        "splits",
        "merges",
        "unscored",
        "review",
        "move_verdicts",
    ]


def test_dump_labels_omits_review_when_absent(simple_labels: LabelFile) -> None:
    from dataclasses import replace

    stripped = replace(simple_labels, review=None)
    mapping = yaml.safe_load(dump_labels(stripped))
    assert "review" not in mapping


def test_save_labels_writes_the_dump(tmp_path: Path, simple_labels: LabelFile) -> None:
    out = tmp_path / "labels.yaml"
    save_labels(simple_labels, out)
    assert out.read_text(encoding="utf-8") == dump_labels(simple_labels)


# --------------------------------------------------------------------------
# Digest computation
# --------------------------------------------------------------------------


def test_normalise_text_collapses_whitespace_but_not_case() -> None:
    assert normalise_text("  a   b\n\tc  ") == "a b c"
    assert normalise_text("Case Stays") == "Case Stays"


def test_digest_for_matches_the_fixture(simple_trees: tuple[BlockTree, BlockTree]) -> None:
    source_tree, _ = simple_trees
    heading = source_tree.block_at("/section[1]/heading[1]")
    assert digest_for(heading) == "2dff10f6a8b7e698"


def test_digest_for_is_sixteen_lowercase_hex_chars(
    simple_trees: tuple[BlockTree, BlockTree],
) -> None:
    source_tree, _ = simple_trees
    for block in source_tree.walk():
        digest = digest_for(block)
        assert len(digest) == 16
        assert digest == digest.lower()
        int(digest, 16)  # raises if not hex


def test_digest_depends_on_label(simple_trees: tuple[BlockTree, BlockTree]) -> None:
    source_tree, _ = simple_trees
    labelled = source_tree.block_at("/section[1]/section[1]/list_item[1]")
    from dataclasses import replace

    relabelled = replace(labelled, label="9.9")
    assert digest_for(labelled) != digest_for(relabelled)


def test_digest_for_a_row_hashes_its_cells() -> None:
    from redlines.blocks import Block, BlockKind, BlockTree as BT

    row = Block(
        kind=BlockKind.ROW,
        children=(
            Block(kind=BlockKind.CELL, text="Left"),
            Block(kind=BlockKind.CELL, text="Right"),
        ),
    )
    other_row_same_cells = Block(
        kind=BlockKind.ROW,
        children=(
            Block(kind=BlockKind.CELL, text="Left"),
            Block(kind=BlockKind.CELL, text="Right"),
        ),
    )
    different_row = Block(
        kind=BlockKind.ROW,
        children=(
            Block(kind=BlockKind.CELL, text="Left"),
            Block(kind=BlockKind.CELL, text="Different"),
        ),
    )
    assert digest_for(row) == digest_for(other_row_same_cells)
    assert digest_for(row) != digest_for(different_row)
    # Sanity: BT is importable and unused beyond typing context in this test.
    assert BT is BlockTree


# --------------------------------------------------------------------------
# labelled_addresses
# --------------------------------------------------------------------------


def test_labelled_addresses_excludes_containers(simple_trees: tuple[BlockTree, BlockTree]) -> None:
    source_tree, _ = simple_trees
    addresses = labelled_addresses(source_tree)
    assert "/" not in addresses
    assert "/section[1]" not in addresses
    assert "/section[1]/heading[1]" in addresses
    assert "/section[1]/section[1]/list_item[1]" in addresses


# --------------------------------------------------------------------------
# verify_digests
# --------------------------------------------------------------------------


def test_verify_digests_passes_for_matching_fixture(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    source_tree, test_tree = simple_trees
    verify_digests(simple_labels, source_tree=source_tree, test_tree=test_tree)  # no raise


def test_verify_digests_raises_on_stale_digest(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    source_tree, test_tree = simple_trees
    stale = replace(
        simple_labels,
        correspondences=(
            replace(simple_labels.correspondences[0], source_digest="0000000000000000"),
        )
        + simple_labels.correspondences[1:],
    )
    with pytest.raises(StaleDigestError) as excinfo:
        verify_digests(stale, source_tree=source_tree, test_tree=test_tree)
    assert any("/section[1]/heading[1]" in message for message in excinfo.value.mismatches)


def test_verify_digests_raises_when_address_no_longer_exists(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    source_tree, test_tree = simple_trees
    moved_off_tree = replace(
        simple_labels,
        deleted=(replace(simple_labels.deleted[0], source="/section[1]/section[9]/list_item[9]"),),
    )
    with pytest.raises(StaleDigestError):
        verify_digests(moved_off_tree, source_tree=source_tree, test_tree=test_tree)


def test_verify_digests_passes_for_renumber_fixture(
    renumber_labels: LabelFile, renumber_trees: tuple[BlockTree, BlockTree]
) -> None:
    source_tree, test_tree = renumber_trees
    verify_digests(renumber_labels, source_tree=source_tree, test_tree=test_tree)


# --------------------------------------------------------------------------
# check_totality
# --------------------------------------------------------------------------


def test_check_totality_passes_for_matching_fixture(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    source_tree, test_tree = simple_trees
    check_totality(simple_labels, source_tree=source_tree, test_tree=test_tree)  # no raise


def test_check_totality_passes_for_renumber_fixture(
    renumber_labels: LabelFile, renumber_trees: tuple[BlockTree, BlockTree]
) -> None:
    source_tree, test_tree = renumber_trees
    check_totality(renumber_labels, source_tree=source_tree, test_tree=test_tree)


def test_check_totality_raises_on_missing_block(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    source_tree, test_tree = simple_trees
    half_labelled = replace(simple_labels, correspondences=simple_labels.correspondences[1:])
    with pytest.raises(TotalityError) as excinfo:
        check_totality(half_labelled, source_tree=source_tree, test_tree=test_tree)
    assert any("missing" in problem for problem in excinfo.value.problems)


def test_check_totality_raises_on_duplicate_address(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    source_tree, test_tree = simple_trees
    duplicated = replace(
        simple_labels,
        correspondences=simple_labels.correspondences + (simple_labels.correspondences[0],),
    )
    with pytest.raises(TotalityError) as excinfo:
        check_totality(duplicated, source_tree=source_tree, test_tree=test_tree)
    assert any("appears" in problem for problem in excinfo.value.problems)


def test_check_totality_unscored_source_does_not_excuse_test(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    """An `unscored` entry naming only the source side must not also excuse
    the test side, even though position-based addresses make the two
    identical strings for an unchanged block."""
    from dataclasses import replace

    from benchmark.labels import UnscoredRegion

    source_tree, test_tree = simple_trees
    dropped = simple_labels.correspondences[0]
    assert dropped.source == dropped.test  # same address on both sides
    without_it = replace(
        simple_labels,
        correspondences=simple_labels.correspondences[1:],
        unscored=(UnscoredRegion(region=dropped.source, side="source", reason="fixture test"),),
    )
    with pytest.raises(TotalityError) as excinfo:
        check_totality(without_it, source_tree=source_tree, test_tree=test_tree)
    assert not any(
        problem.startswith(f"source {dropped.source}:") for problem in excinfo.value.problems
    )
    assert any(problem.startswith(f"test {dropped.test}:") for problem in excinfo.value.problems)


def test_check_totality_accepts_an_unscored_region(
    renumber_labels: LabelFile, renumber_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    from benchmark.labels import UnscoredRegion

    source_tree, test_tree = renumber_trees
    # Drop one correspondence (source and test addresses genuinely differ
    # here) but cover its source side via `unscored`.
    dropped = renumber_labels.correspondences[0]
    assert dropped.source != dropped.test
    without_it = replace(
        renumber_labels,
        correspondences=renumber_labels.correspondences[1:],
        unscored=(UnscoredRegion(region=dropped.source, side="source", reason="fixture test"),),
    )
    # The source side is covered by `unscored`; the test side is still missing.
    with pytest.raises(TotalityError) as excinfo:
        check_totality(without_it, source_tree=source_tree, test_tree=test_tree)
    assert not any(
        problem.startswith(f"source {dropped.source}:") for problem in excinfo.value.problems
    )
    assert any(problem.startswith(f"test {dropped.test}:") for problem in excinfo.value.problems)


# --------------------------------------------------------------------------
# override_rate
# --------------------------------------------------------------------------


def test_override_rate_all_confirmed_is_zero(simple_labels: LabelFile) -> None:
    assert override_rate(simple_labels) == 0.0


def test_override_rate_counts_corrected_rows(simple_labels: LabelFile) -> None:
    from dataclasses import replace

    one_corrected = replace(
        simple_labels,
        correspondences=(replace(simple_labels.correspondences[0], status="corrected"),)
        + simple_labels.correspondences[1:],
    )
    # 8 correspondences + 1 inserted + 1 deleted = 10 status-bearing rows, 1 corrected.
    assert override_rate(one_corrected) == pytest.approx(0.1)


def test_override_rate_is_none_when_no_status_rows() -> None:
    from benchmark.labels import Provenance, Side

    empty = LabelFile(
        pair="empty",
        source=Side(file="s.txt", format="text", profile="contract", sha256="a" * 64),
        test=Side(file="t.txt", format="text", profile="contract", sha256="b" * 64),
        provenance=Provenance(kind="hand", origin="nowhere"),
    )
    assert override_rate(empty) is None


# --------------------------------------------------------------------------
# reanchor
# --------------------------------------------------------------------------


def test_reanchor_is_a_no_op_when_nothing_moved(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    source_tree, test_tree = simple_trees
    report = reanchor(simple_labels, source_tree=source_tree, test_tree=test_tree)
    assert report.changes == ()
    assert report.refused == ()
    assert to_mapping(report.labels) == to_mapping(simple_labels)


def test_reanchor_updates_a_shifted_address() -> None:
    # Simulate a reader change: the source tree now has an extra leading
    # heading, shifting every following address down by one -- but every
    # block's digest (label-prefixed text) is unchanged.
    from dataclasses import replace

    directory = CASE_DIR / "simple"
    original_source = _tree(directory / "source.txt")
    shifted_text = "Preface\n\n" + (directory / "source.txt").read_text(encoding="utf-8")
    shifted_source = read_document(shifted_text, format="text", profile="contract")
    test_tree = _tree(directory / "test.txt")
    labels = load_labels(directory / "labels.yaml")

    # Sanity: the shift really did move the heading we are about to check.
    assert original_source.block_at("/section[1]/heading[1]").text == "Agreement"
    moved_heading = shifted_source.block_at("/section[2]/heading[1]")
    assert moved_heading.text == "Agreement"

    report = reanchor(labels, source_tree=shifted_source, test_tree=test_tree)
    changed = {c.old_address: c.new_address for c in report.changes if c.side == "source"}
    assert changed.get("/section[1]/heading[1]") == "/section[2]/heading[1]"
    # The rewritten label file's row for this heading now names the new address.
    rewritten_row = next(
        row for row in report.labels.correspondences if row.source_digest == "2dff10f6a8b7e698"
    )
    assert rewritten_row.source == "/section[2]/heading[1]"


def test_reanchor_refuses_to_move_a_corrected_row_by_default(
    simple_labels: LabelFile,
) -> None:
    from dataclasses import replace

    directory = CASE_DIR / "simple"
    shifted_text = "Preface\n\n" + (directory / "source.txt").read_text(encoding="utf-8")
    shifted_source = read_document(shifted_text, format="text", profile="contract")
    test_tree = _tree(directory / "test.txt")

    corrected = replace(
        simple_labels,
        correspondences=(replace(simple_labels.correspondences[0], status="corrected"),)
        + simple_labels.correspondences[1:],
    )
    report = reanchor(corrected, source_tree=shifted_source, test_tree=test_tree)
    assert any(
        change.old_address == "/section[1]/heading[1]" and change.refused
        for change in report.refused
    )
    # Left untouched in the returned labels.
    untouched_row = next(
        row for row in report.labels.correspondences if row.source_digest == "2dff10f6a8b7e698"
    )
    assert untouched_row.source == "/section[1]/heading[1]"


def test_reanchor_force_corrected_allows_the_move(simple_labels: LabelFile) -> None:
    from dataclasses import replace

    directory = CASE_DIR / "simple"
    shifted_text = "Preface\n\n" + (directory / "source.txt").read_text(encoding="utf-8")
    shifted_source = read_document(shifted_text, format="text", profile="contract")
    test_tree = _tree(directory / "test.txt")

    corrected = replace(
        simple_labels,
        correspondences=(replace(simple_labels.correspondences[0], status="corrected"),)
        + simple_labels.correspondences[1:],
    )
    report = reanchor(
        corrected, source_tree=shifted_source, test_tree=test_tree, force_corrected=True
    )
    assert report.refused == ()
    moved_row = next(
        row for row in report.labels.correspondences if row.source_digest == "2dff10f6a8b7e698"
    )
    assert moved_row.source == "/section[2]/heading[1]"


def test_reanchor_raises_when_a_digest_has_no_match(
    simple_labels: LabelFile, simple_trees: tuple[BlockTree, BlockTree]
) -> None:
    from dataclasses import replace

    source_tree, test_tree = simple_trees
    broken = replace(
        simple_labels,
        deleted=(replace(simple_labels.deleted[0], source_digest="ffffffffffffffff"),),
    )
    with pytest.raises(ReanchorError) as excinfo:
        reanchor(broken, source_tree=source_tree, test_tree=test_tree)
    assert any("no block" in problem for problem in excinfo.value.problems)


def test_reanchor_raises_on_ambiguous_digest(simple_labels: LabelFile) -> None:
    from dataclasses import replace

    # A tree with two identical paragraphs makes one digest ambiguous.
    text = (
        "Agreement\n\n1. Heading\n\n"
        "Intentionally omitted.\n\nIntentionally omitted.\n"
    )
    ambiguous_tree = read_document(text, format="text", profile="contract")
    labels = replace(
        simple_labels,
        deleted=(
            replace(
                simple_labels.deleted[0],
                source="/section[1]/section[1]/paragraph[1]",
                source_digest=digest_for(ambiguous_tree.block_at("/section[1]/section[1]/paragraph[1]")),
            ),
        ),
        correspondences=(),
        inserted=(),
    )
    test_tree = read_document("Agreement\n\n1. Heading\n\nSomething else entirely.\n", format="text", profile="contract")
    with pytest.raises(ReanchorError) as excinfo:
        reanchor(labels, source_tree=ambiguous_tree, test_tree=test_tree)
    assert any("ambiguous" in problem for problem in excinfo.value.problems)
