"""The ten hand-labelled pairs: every pair loads, is fresh, and stays draft-honest (#142).

`benchmark/corpus/hand/` is committed by `benchmark/prepare.py` and `benchmark/label.py`, not
generated at test time -- unlike the synthetic tier's byte-identity test
(`tests/test_benchmark_corpus.py`), there is no generator to re-run against real, licensed
upstream text (ADR-0034 D-9 explicitly rules out re-fetching at score time). What this module
checks instead is that what is committed is internally consistent and honest about its own
state:

- every pair's `labels.yaml` parses and validates against the published schema;
- every recorded digest still matches the committed `source`/`test` file it was computed
  from, and every labelled block on both sides is accounted for exactly once (totality);
- every pair carries a `NOTICE.md` naming its licence;
- and, the one invariant `benchmark/label.py`'s docstring calls load-bearing: no
  correspondence row anywhere has `kind: move` while still `status: proposed` -- a move is
  never engine-seeded, so a `move` row can only exist once a human has confirmed or corrected
  it (ADR-0034 D-10, ADR-0021's anti-self-marking mitigation).

Every pair committed today is, in fact, entirely `status: proposed` with no `move` rows at
all and no `review:` block -- these are drafts awaiting a maintainer's labelling pass and a
separate review pass, exactly as the PR that added them says. The fourth test above is written
to the durable invariant, not to today's snapshot, so it keeps meaning something once a human
has been through a worksheet and some rows have become `confirmed`, `corrected`, or genuinely
`move`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from benchmark.label import load_manifest
from benchmark.labels import check_totality, load_labels, verify_digests
from redlines.pipeline import read_document

HAND_CORPUS = Path(__file__).parent.parent / "benchmark" / "corpus" / "hand"

PAIR_DIRS: tuple[Path, ...] = tuple(
    sorted(path for path in HAND_CORPUS.iterdir() if path.is_dir())
)

# Guard against a future change silently shrinking the ten pairs #142 asks for, or this
# module's own glob finding nothing because the corpus moved.
EXPECTED_PAIR_COUNT = 10


def test_ten_pairs_are_committed() -> None:
    assert len(PAIR_DIRS) == EXPECTED_PAIR_COUNT, sorted(p.name for p in PAIR_DIRS)


@pytest.mark.parametrize("pair_dir", PAIR_DIRS, ids=lambda path: path.name)
class TestHandLabelledPair:
    """Every check below runs once per pair directory under `benchmark/corpus/hand/`."""

    def test_pair_loads(self, pair_dir: Path) -> None:
        """`labels.yaml` parses and validates against `benchmark/labels/schema.json`."""
        labels = load_labels(pair_dir / "labels.yaml")
        assert labels.pair == pair_dir.name
        # A pair with nothing to say about either side would be a broken fetch, not a pair.
        assert labels.correspondences or labels.inserted or labels.deleted

    def test_digests_are_fresh(self, pair_dir: Path) -> None:
        """Every recorded digest matches the committed files, and totality holds.

        Rebuilds both trees independently, via `redlines.pipeline.read_document` under the
        format and profile `benchmark/prepare.py` recorded, rather than reusing whatever
        `benchmark/label.py init` last wrote -- exactly what a stale-digest bug would need
        this test to actually catch.
        """
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

    def test_notice_is_present(self, pair_dir: Path) -> None:
        """`NOTICE.md` exists, is non-empty, and names the pair's own licence terms."""
        notice_path = pair_dir / "NOTICE.md"
        assert notice_path.exists(), f"{pair_dir.name} has no NOTICE.md"
        text = notice_path.read_text(encoding="utf-8")
        assert text.strip()
        manifest = load_manifest(pair_dir)
        if manifest["licence"] == "CC-BY-4.0":
            assert "CC BY 4.0" in text
            assert "creativecommons.org/licenses/by/4.0" in text
        else:
            assert "public domain" in text.lower()
            assert "17 U.S.C" in text

    def test_no_move_row_carries_a_proposing_pass(self, pair_dir: Path) -> None:
        """No `kind: move` correspondence is ever `status: proposed`.

        `benchmark/label.py init` never writes `kind: move` at all -- a move the engine
        proposes is written conservatively as `same`/`renumber` and only flagged for a human
        in `worksheet.md` -- so a `proposed` row can never legitimately be a move. The only
        way a `move` row exists is a human having added or upgraded it from
        `move_worksheet.md`, which requires `status: confirmed` or `status: corrected`. This
        is the ADR-0034 D-10 / §1.11.5 invariant that keeps the move gate from ever being
        seeded by the thing it is meant to check.
        """
        labels = load_labels(pair_dir / "labels.yaml")
        offending = [
            row
            for row in labels.correspondences
            if row.kind == "move" and row.status == "proposed"
        ]
        assert not offending, [
            (row.source, row.test) for row in offending
        ]


def test_no_pair_directory_is_missing_from_the_corpus_glob() -> None:
    """`PAIR_DIRS` is not empty -- a moved or renamed corpus fails loudly, not silently."""
    assert PAIR_DIRS, f"no pair directories found under {HAND_CORPUS}"
