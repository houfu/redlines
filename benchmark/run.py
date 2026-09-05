"""The runner: corpus in, ``results/latest.json`` and ``REPORT.md`` out (#143).

```
uv run python -m benchmark.run --tier all
uv run python -m benchmark.run --tier hand --backends difflib
uv run python -m benchmark.run --check          # regenerate into memory and diff
```

Everything the benchmark publishes comes out of this one entry point, and it
is the only place the pieces are wired together: :mod:`benchmark.labels` loads
and *verifies* the ground truth, `redlines.comparison.compare` produces the
engine's answer, :mod:`benchmark.baselines` produces the 0.6 floor's,
:mod:`benchmark.score` turns both into counts, and :mod:`benchmark.report`
turns the counts into prose. A number that appears in ``REPORT.md`` and not in
``results/latest.json`` would be a number nobody could re-derive, so the report
reads the results file and nothing else.

**Committed output must be a reviewable diff, so it carries no clock.** There
is no date, no duration, no host and no run id anywhere in what this writes.
Re-running on an unchanged checkout rewrites both files byte for byte, which is
what makes ``--check`` a test rather than a formality: if the numbers moved,
the engine moved, and the diff says by how much.

The one identifier a reader will want and will not find in the file is the
engine commit. It is deliberately absent: stamping ``git rev-parse HEAD`` into
a committed artefact makes it stale the moment the next commit lands, and the
byte-stability check would then fail for a reason that has nothing to do with
the engine. ``git log -1 --format=%H benchmark/results/latest.json`` answers
the question exactly, from the repository's own record. (Move verdicts are the
exception and *do* record a commit -- they are a human's ruling about one
engine's output at one moment, written by hand into ``labels.yaml``.)

**Both backends, every time.** ADR-0034 asks for the suite run twice, once per
similarity backend, *selected* rather than simulated by hiding an import, so
the report can state the gap the site's difflib floor pays. Requesting
``rapidfuzz`` without the ``[fuzzy]`` extra installed is an error rather than a
silent single-backend run: a results file that quietly dropped a column would
be worse than one that refused to be written. The 0.6 floor is computed once
per tier, not once per backend -- it has no similarity backend to vary.

**Digests are verified, not trusted.** Every pair's labels are checked against
the committed documents before it is scored, and a stale digest aborts the run
naming the pair. Scoring against rotted addresses would produce numbers that
look fine and mean nothing, which is the failure mode ADR-0034 built digest
anchoring to make loud.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from redlines.alignment import AlignmentConfig
from redlines.comparison import compare
from redlines.similarity import RAPIDFUZZ_AVAILABLE

from .baselines import baseline_pairs
from .generate import GENERATOR_VERSION, repository_root
from .labels import load_labels, verify_digests
from .report import render_report
from .score import (
    PairScore,
    RoleCounts,
    TierScore,
    aggregate,
    pass_table,
    role_counts,
    score_baseline_pair,
    score_engine_pair,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from redlines.comparison import Comparison

__all__ = [
    "RESULTS_SCHEMA",
    "TIERS",
    "BACKENDS",
    "PairInput",
    "corpus_dir",
    "discover",
    "run",
    "write",
    "main",
]

#: The results file's own format identifier, so a later change to its shape is
#: a version bump rather than a reader guessing.
RESULTS_SCHEMA = "redlines/benchmark-results/1"

#: The committed tiers, in report order. ``external`` is deliberately absent:
#: it is gitignored, it cannot be reproduced from a checkout, and the report
#: says so rather than printing an empty column.
TIERS: tuple[str, ...] = ("synthetic", "hand")

#: The similarity backends the suite runs under, in report order. ``difflib``
#: is first because it is the floor the documentation site runs on (PRD § 12).
BACKENDS: tuple[str, ...] = ("difflib", "rapidfuzz")


class PairInput:
    """One pair's committed inputs, loaded once and scored under each backend.

    :param directory: the pair directory, whose name is the pair id.
    :param tier: ``synthetic`` or ``hand``.
    """

    def __init__(self, directory: Path, tier: str) -> None:
        self.directory = directory
        self.tier = tier
        self.pair = directory.name
        self.labels = load_labels(directory / "labels.yaml")
        self.source_text = (directory / self.labels.source.file).read_text(
            encoding="utf-8"
        )
        self.test_text = (directory / self.labels.test.file).read_text(encoding="utf-8")

    def compare(self, config: AlignmentConfig) -> Comparison:
        """Run the 1.0 engine over this pair under ``config``.

        :param config: the alignment configuration, backend included.
        :return: the `redlines.comparison.Comparison`.
        """
        return compare(
            self.source_text,
            self.test_text,
            format=self.labels.source.format,
            profile=self.labels.source.profile,
            alignment=config,
        )


def corpus_dir(tier: str, *, root: Path | None = None) -> Path:
    """Return a tier's corpus directory.

    :param tier: the tier name.
    :param root: the repository root; derived when omitted.
    :return: the directory, which may not exist.
    """
    return (root or repository_root()) / "benchmark" / "corpus" / tier


def discover(tier: str, *, root: Path | None = None) -> tuple[PairInput, ...]:
    """Load every committed pair of one tier, in sorted pair order.

    :param tier: the tier name.
    :param root: the repository root; derived when omitted.
    :return: the pairs, sorted by directory name so the run order -- and every
        sum taken over it -- is the same on every machine.
    :raises FileNotFoundError: if the tier directory does not exist.
    """
    directory = corpus_dir(tier, root=root)
    if not directory.is_dir():
        raise FileNotFoundError(f"no corpus tier at {directory}")
    return tuple(
        PairInput(child, tier)
        for child in sorted(directory.iterdir(), key=lambda path: path.name)
        if (child / "labels.yaml").is_file()
    )


def _score_tier_engine(
    pairs: Sequence[PairInput], *, tier: str, backend: str
) -> TierScore:
    """Score one tier under the 1.0 engine and one similarity backend."""
    config = AlignmentConfig(similarity=backend)
    scores: list[PairScore] = []
    resolved = backend
    for entry in pairs:
        comparison = entry.compare(config)
        verify_digests(
            entry.labels,
            source_tree=comparison.source,
            test_tree=comparison.test,
        )
        resolved = comparison.config.similarity
        scores.append(
            score_engine_pair(
                pair=entry.pair,
                tier=tier,
                labels=entry.labels,
                comparison=comparison,
                source_tree=comparison.source,
                test_tree=comparison.test,
                passes=pass_table(
                    comparison,
                    labels=entry.labels,
                    source_tree=comparison.source,
                    test_tree=comparison.test,
                    config=config,
                ),
            )
        )
    return aggregate(scores, tier=tier, engine="1.0", backend=resolved)


def _score_tier_baseline(pairs: Sequence[PairInput], *, tier: str) -> TierScore:
    """Score one tier under the flat 0.6 floor.

    The floor has no similarity backend of its own -- it is one
    `difflib.SequenceMatcher` over a token list -- so it is computed once and
    reported once, under the backend name ``none``.
    """
    scores: list[PairScore] = []
    for entry in pairs:
        comparison = entry.compare(AlignmentConfig(similarity="difflib"))
        reported = baseline_pairs(
            entry.source_text,
            entry.test_text,
            source_tree=comparison.source,
            test_tree=comparison.test,
        )
        scores.append(
            score_baseline_pair(
                pair=entry.pair,
                tier=tier,
                labels=entry.labels,
                reported=reported,
                source_tree=comparison.source,
                test_tree=comparison.test,
            )
        )
    return aggregate(scores, tier=tier, engine="0.6", backend="none")


def _tier_roles(pairs: Sequence[PairInput]) -> RoleCounts:
    """Count the semantic pass's role coverage over a tier, both sides."""
    counts = RoleCounts()
    for entry in pairs:
        comparison = entry.compare(AlignmentConfig(similarity="difflib"))
        counts = counts + role_counts(comparison.source, comparison.test)
    return counts


def _corpus_summary(tier: str, pairs: Sequence[PairInput]) -> dict[str, Any]:
    """Describe a tier: how many pairs, which documents, which formats."""
    plans = sorted(
        {entry.labels.provenance.plan for entry in pairs if entry.labels.provenance.plan}
    )
    return {
        "tier": tier,
        "pairs": len(pairs),
        "formats": sorted({entry.labels.source.format for entry in pairs}),
        "profiles": sorted({entry.labels.source.profile for entry in pairs}),
        "plans": plans,
        "documents": [
            {
                "pair": entry.pair,
                "source_sha256": entry.labels.source.sha256,
                "test_sha256": entry.labels.test.sha256,
            }
            for entry in pairs
        ],
    }


def run(
    *,
    tiers: Sequence[str] = TIERS,
    backends: Sequence[str] = BACKENDS,
    root: Path | None = None,
) -> dict[str, Any]:
    """Run the whole benchmark and return the results document.

    :param tiers: which committed tiers to score, in report order.
    :param backends: which similarity backends the 1.0 engine runs under.
    :param root: the repository root; derived when omitted.
    :return: the results document, exactly as ``results/latest.json`` holds it.
    :raises RuntimeError: if ``rapidfuzz`` is asked for and is not installed.
    :raises benchmark.labels.StaleDigestError: if any pair's labels have rotted
        against the committed documents.
    """
    if "rapidfuzz" in backends and not RAPIDFUZZ_AVAILABLE:
        raise RuntimeError(
            "the rapidfuzz backend was requested but the [fuzzy] extra is not "
            "installed; run `uv sync --all-extras --dev`, or pass "
            "`--backends difflib` and expect the report to say the gap is "
            "unmeasured"
        )

    corpus: list[dict[str, Any]] = []
    tier_scores: list[TierScore] = []
    roles: dict[str, Any] = {}
    for tier in tiers:
        pairs = discover(tier, root=root)
        corpus.append(_corpus_summary(tier, pairs))
        roles[tier] = _tier_roles(pairs).to_dict()
        for backend in backends:
            tier_scores.append(_score_tier_engine(pairs, tier=tier, backend=backend))
        tier_scores.append(_score_tier_baseline(pairs, tier=tier))

    return {
        "schema": RESULTS_SCHEMA,
        "generator_version": GENERATOR_VERSION,
        "backends": list(backends),
        "alignment_config": AlignmentConfig().to_dict(),
        "corpus": corpus,
        "roles": roles,
        "tiers": [score.to_dict() for score in tier_scores],
    }


def results_text(results: dict[str, Any]) -> str:
    """Render the results document as the bytes the committed file holds.

    :param results: what `run` returned.
    :return: pretty-printed JSON with a trailing newline -- indented and
        key-ordered as authored, so a moved number is one changed line in a
        diff rather than a reflowed paragraph.
    """
    return json.dumps(results, indent=2, ensure_ascii=False) + "\n"


def write(results: dict[str, Any], *, root: Path | None = None) -> tuple[Path, Path]:
    """Write ``results/latest.json`` and ``REPORT.md``.

    :param results: what `run` returned.
    :param root: the repository root; derived when omitted.
    :return: the two paths written, results file first.
    """
    base = (root or repository_root()) / "benchmark"
    results_path = base / "results" / "latest.json"
    report_path = base / "REPORT.md"
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(results_text(results), encoding="utf-8")
    report_path.write_text(render_report(results), encoding="utf-8")
    return results_path, report_path


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark from the command line.

    :param argv: the arguments, ``sys.argv[1:]`` when omitted.
    :return: ``0`` on success, ``1`` when ``--check`` found a difference.
    """
    parser = argparse.ArgumentParser(
        description="Run the alignment benchmark and write REPORT.md.",
    )
    parser.add_argument(
        "--tier",
        choices=(*TIERS, "all"),
        default="all",
        help="which committed tier to score (default: all)",
    )
    parser.add_argument(
        "--backends",
        default=",".join(BACKENDS),
        help="comma-separated similarity backends for the 1.0 engine",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory and compare with what is committed, writing nothing",
    )
    args = parser.parse_args(argv)

    tiers = TIERS if args.tier == "all" else (args.tier,)
    backends = tuple(name.strip() for name in args.backends.split(",") if name.strip())
    results = run(tiers=tiers, backends=backends)

    if args.check:
        base = repository_root() / "benchmark"
        differences: list[str] = []
        for path, wanted in (
            (base / "results" / "latest.json", results_text(results)),
            (base / "REPORT.md", render_report(results)),
        ):
            found = path.read_text(encoding="utf-8") if path.exists() else ""
            if found != wanted:
                differences.append(str(path.relative_to(repository_root())))
        if differences:
            print(
                "stale: " + ", ".join(differences) + "\n"
                "run `uv run python -m benchmark.run --tier all` and commit the diff",
                file=sys.stderr,
            )
            return 1
        print("up to date")
        return 0

    for path in write(results):
        print(f"wrote {path.relative_to(repository_root())}")
    return 0


if __name__ == "__main__":  # pragma: no cover - a script entry point
    raise SystemExit(main())
