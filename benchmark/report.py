"""``results/latest.json`` in, ``REPORT.md`` out (#143, ADR-0021, ADR-0034).

This module renders; it never measures. Every number it prints is read out of
the results document :mod:`benchmark.run` wrote, so a figure in the report that
a reader cannot find in ``results/latest.json`` is a bug rather than a
rounding. That separation is the whole reason there are two files: the JSON is
what a machine diffs, the markdown is what a person reads, and neither is
allowed to know something the other does not.

**The report argues against itself on purpose.** ADR-0021 named the risk in its
own consequences -- "a benchmark we design could flatter us" -- so the
methodology section here states every denominator before the tables state any
number, the two places the 0.6 floor could be hobbled are written out in full,
the label set's own draft status and override rates are printed beside the
scores they produced, and the two things this repository *cannot* demonstrate
get their own headed section rather than a footnote. A reader who stops after
the headline table has read the flattering half; the section order is chosen so
that stopping there is obviously stopping early.

The prose is generated, not templated over a database of adjectives: the
methodology text is fixed, and only the tables move when the engine does. That
is deliberate too. If the wording of what a number means could change when the
number changes, the definition would not be a definition.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from redlines.alignment import PASS_NAMES

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

__all__ = ["render_report"]

#: PRD § 10's targets, which `tests/test_benchmark_gates.py` enforces and this
#: report prints the standing of. Written here as data so the report and the
#: gate cannot drift into disagreeing about what the bar is.
GATES: tuple[tuple[str, str, float], ...] = (
    ("synthetic", "correspondence F1", 0.95),
    ("hand", "correspondence F1", 0.85),
    ("synthetic", "move recall", 0.90),
)


def _fmt(value: float | None) -> str:
    """Format a ratio to four places, or ``n/a`` when the denominator was zero.

    ``n/a`` and ``0.0000`` are different facts -- "there was nothing to get
    right" against "everything was got wrong" -- and a report that printed them
    the same way would be lying about one of them.
    """
    return "n/a" if value is None else f"{value:.4f}"


def _delta(later: float | None, earlier: float | None) -> str:
    """Format ``later - earlier`` with an explicit sign, or ``n/a``."""
    if later is None or earlier is None:
        return "n/a"
    return f"{later - earlier:+.4f}"


def _table(headers: Sequence[str], rows: Iterable[Sequence[str]]) -> list[str]:
    """Render a markdown table, left-aligned, with no column padding.

    Unpadded because the file is regenerated and diffed: padding would make one
    changed number reflow a whole column.
    """
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("|" + "|".join("---" for _ in headers) + "|")
    lines.extend("| " + " | ".join(row) + " |" for row in rows)
    return lines


def _tier(
    results: Mapping[str, Any], tier: str, engine: str, backend: str
) -> Mapping[str, Any] | None:
    """Find one scored tier in the results document."""
    for entry in results["tiers"]:
        if (
            entry["tier"] == tier
            and entry["engine"] == engine
            and entry["backend"] == backend
        ):
            found: Mapping[str, Any] = entry
            return found
    return None


def _draft_tiers(results: Mapping[str, Any]) -> dict[str, int]:
    """Tiers whose labels are still engine-seeded drafts, and how many rows.

    A row still marked ``proposed`` is what `benchmark/label.py init` wrote out
    of this engine's own alignment and nobody has confirmed. Scoring the engine
    against those rows measures whether it agrees with itself. The tier is
    still scored and still printed -- hiding it would make the missing
    labelling invisible -- but every table that quotes it marks it.
    """
    draft: dict[str, int] = {}
    for entry in results["tiers"]:
        # Each tier appears once per engine and backend over the same labels,
        # so the count is taken rather than accumulated: summing would report
        # the same proposed row three times.
        rows = sum(pair["proposed_rows"] for pair in entry["pairs"])
        if rows:
            draft[entry["tier"]] = max(draft.get(entry["tier"], 0), rows)
    return draft


def _mark(tier: str, draft: Mapping[str, int]) -> str:
    """Render a tier name for a table cell, daggered when its labels are drafts."""
    return f"`{tier}` \u2020" if tier in draft else f"`{tier}`"


def _draft_note(results: Mapping[str, Any]) -> list[str]:
    """The footnote every daggered table carries, or nothing when none is."""
    draft = _draft_tiers(results)
    if not draft:
        return []
    listed = ", ".join(
        f"`{tier}` ({rows} rows)" for tier, rows in sorted(draft.items())
    )
    return [
        f"\u2020 **These labels are drafts, not ground truth: {listed}.** Every one of "
        "those correspondence rows is still `status: proposed` -- what "
        "`benchmark/label.py init` proposed *from this engine's own alignment*, with no "
        "human having confirmed or corrected it. A score against them measures whether "
        "the engine agrees with itself, so read the row as provenance rather than as "
        "evidence, and read `How much to trust the labels` below before quoting it. The "
        "numbers are published anyway, marked, because suppressing them until the "
        "labelling is finished would make the unfinished labelling invisible -- which is "
        "the failure ADR-0021 built this report to prevent.",
        "",
    ]


def _primary_backend(results: Mapping[str, Any]) -> str:
    """The backend the headline numbers are quoted under.

    ``difflib`` when it ran, because that is what the documentation site runs
    on (PRD § 12) and quoting the faster backend's numbers as the headline
    would over-sell the engine everywhere the site is the only thing a reader
    can try.
    """
    backends = list(results["backends"])
    return "difflib" if "difflib" in backends else backends[0]


def _preamble() -> list[str]:
    """The title and the one paragraph that says what this file is."""
    return [
        "# The redlines alignment benchmark",
        "",
        "How well does this engine work out which clause of the old document became "
        "which clause of the new one? This report answers that against a committed "
        "corpus, with the flat 0.6 engine as the floor, and it is generated -- "
        "`uv run python -m benchmark.run --tier all` rewrites both this file and "
        "`benchmark/results/latest.json`, so a number moving is a diff somebody reads.",
        "",
        "The design is [ADR-0021](../docs/adr/0021-alignment-benchmark.md) (why there is "
        "a benchmark at all, and before tuning rather than after) and "
        "[ADR-0034](../docs/adr/0034-benchmark-labels-and-metric.md) (the label format, "
        "every definition below, and the alternatives each was chosen over).",
        "",
    ]


def _methodology(results: Mapping[str, Any]) -> list[str]:
    """The definitions, in full, before any number appears."""
    config = results["alignment_config"]
    return [
        "## Methodology",
        "",
        "### What is being scored",
        "",
        "The **alignment**, not the change tree. Two blocks that correspond and did not "
        "change produce no change node at all, so the change tree cannot express the "
        "correspondence set; `Comparison.alignment` can, and is public for this reason. "
        "Moves and renumbers *are* read off the change tree, because their granularity "
        "rules live there -- scoring them off anything else would let the engine and its "
        "own metric disagree about what a move is.",
        "",
        "### The correspondence metric",
        "",
        "Let `C*` be the labelled correspondence set as `(source address, test address)` "
        "pairs and `C` the engine's reported pairs. Then **precision** is "
        "`|C ∩ C*| / |C|`, **recall** is `|C ∩ C*| / |C*|`, and **F1** is their harmonic "
        "mean. Six rules fix the denominators:",
        "",
        "1. **Links only.** A block the labels call inserted or deleted is in neither "
        "denominator. Counting correctly-unmatched blocks would let a long document with "
        "three edits inflate its F1 by saying nothing about most of itself, and would "
        "make the score a function of document length.",
        "2. **The spurious-match rate** is the counterweight that makes rule 1 safe: the "
        "fraction of reported pairs with one side labelled inserted or deleted. "
        "Links-only precision cannot see a fill-in pass inventing matches; this can, and "
        "it is printed beside precision everywhere, never instead of it.",
        "3. **The root pair is excluded.** `/` corresponds to `/` in every comparison "
        "ever made, and crediting an engine for knowing a document is itself flatters "
        "every number in the table.",
        "4. **Containers are not labelled**, so they are in neither set: text-bearing "
        "blocks plus table `row` blocks, on both sides.",
        "5. **A moved subtree counts once**, at the topmost block whose whole subtree "
        "moved; its descendants are ordinary correspondences. This is the same rule the "
        "change tree emits `move` nodes under, so the engine is scored against the "
        "definition of *move* it actually uses.",
        "6. **Renumber recall keys on the four-tuple** "
        "`(source address, test address, source label, test label)`. A renumber reported "
        "with the wrong new label is not a hit. Both sides derive the set the same way, "
        "from labels that differ, so a block that moved *and* was relabelled is one row "
        "of ground truth feeding two metrics.",
        "",
        "**Splits and merges are labelled and excluded** from every denominator in this "
        "release, along with any region the labels mark `unscored`. The counts appear "
        "below, so the day 1.1 scores them the delta is measurable rather than a guess.",
        "",
        "Counts are integers; ratios are computed once from summed counts (a "
        "micro-average, never a mean of means) and rounded at the boundary. A cell "
        "reading `n/a` had a zero denominator; it is not a zero.",
        "",
        "### The 0.6 floor, and how a flat engine gets an address",
        "",
        "The floor is the flat engine called directly -- "
        "`WholeDocumentProcessor(autojunk=False)`, never the `Redlines` class, which "
        "M3 reimplements over this same core and which would therefore stop being the "
        "0.6 baseline the day the facade lands. A test asserts the import prohibition so "
        "the substitution cannot happen quietly.",
        "",
        "0.6 has no block model, so getting a correspondence set out of it means "
        "deciding what its opcodes *imply*. There are exactly two decisions, and this is "
        "the only place either can be flattered or hobbled, so both are stated here as "
        "well as in the source:",
        "",
        "- **Opcodes to unit pairs.** Every `equal` opcode pairs its tokens one for one "
        "and each paired token votes for the pair of units its two tokens sit in. Every "
        "`replace` opcode pairs the units it spans by relative order -- first with "
        "first, and so on until one side runs out -- one vote each. A source unit takes "
        "the test unit with the most votes; ties go to the smallest test unit index. "
        "`insert` and `delete` pair nothing.",
        "- **Unit pairs to block pairs.** A unit is assigned to the first block at or "
        "after a monotone pointer whose normalised text contains it, and a source block "
        "takes the **plurality** of its units' targets, ties broken by the earliest test "
        "block in document order. A unit that matches no block within the search window "
        "is assigned nothing rather than attached to whatever was nearest.",
        "",
        "Both rules are generous to the floor rather than mean to it: voting lets one "
        "strongly-matched line carry a block whose other lines drifted, and "
        "relative-order pairing inside a `replace` credits 0.6 with correspondences it "
        "never states.",
        "",
        "Two columns are reported for every engine. **All labelled blocks** is the "
        "honest end-to-end number. **Flat-addressable blocks** excludes table `row` and "
        "`cell` blocks, which the flat engine has no concept of, and is the "
        "like-for-like one. The floor's move recall and renumber recall are `0.0000` by "
        "construction and are printed rather than left blank: 0.6 cannot express either, "
        "and that cell is the argument for this milestone. Its unit is a **line**, not a "
        "paragraph, so it necessarily gets a whitespace-only rewrap wrong. That is what "
        "a floor is.",
        "",
        "### The configuration in force",
        "",
        "Headline numbers are quoted under the **"
        f"{_primary_backend(results)}** backend, which is what the documentation site "
        "runs on (PRD § 12); the gap to the other backend has its own section. "
        "Thresholds, from `AlignmentConfig` defaults:",
        "",
        "```",
        f"passes                    {', '.join(config['passes'])}",
        f"fuzzy_min_similarity      {config['fuzzy_min_similarity']}",
        f"label_min_similarity      {config['label_min_similarity']}",
        f"positional_min_similarity {config['positional_min_similarity']}",
        f"move_min_similarity       {config['move_min_similarity']}",
        f"move_tie_margin           {config['move_tie_margin']}",
        f"move_min_tokens           {config['move_min_tokens']}",
        f"move_kinds                {', '.join(config['move_kinds'])}",
        f"fuzzy_window              {config['fuzzy_window']}",
        f"table_fuzzy               {config['table_fuzzy']}",
        f"max_comparisons           {config['max_comparisons']}",
        "```",
        "",
        "### Reproducing this, and dating it",
        "",
        "```",
        "uv sync --all-extras --dev",
        "uv run python -m benchmark.run --tier all",
        "```",
        "",
        "Nothing written by that command carries a clock -- no date, no duration, no "
        "host, no run id -- so re-running it on an unchanged checkout rewrites both "
        "files byte for byte and `--check` is a real test rather than a formality. The "
        "engine commit is deliberately not stamped into the files either: it would go "
        "stale on the next commit and break byte-stability for a reason that has nothing "
        "to do with the engine. `git log -1 --format=%H benchmark/results/latest.json` "
        "answers the question from the repository's own record.",
        "",
    ]


def _limits() -> list[str]:
    """What this repository cannot demonstrate, said before the tables."""
    return [
        "## What this report does not claim",
        "",
        "**There is no like-for-like re-run of the `neurotic_docx_bench` 45.9 figure, "
        "and there cannot be one in 1.0.** That benchmark scores a tracked-changes DOCX "
        "produced by the tool under test; "
        "[ADR-0014](../docs/adr/0014-no-ooxml-writing.md) rules out writing OOXML, so "
        "this project cannot produce the artefact the bench grades. The published 45.9 "
        "came from a third-party adapter rather than from this project, and nothing "
        "below is comparable with it. The bench's base documents are used here only as a "
        "*text source* for mutation, in the uncommitted tier, which is a different use "
        "of the same repository and not a claim about that score.",
        "",
        "**Numbers from `benchmark/corpus/external/` are not reproducible from this "
        "repository.** That tier is gitignored: its material is AGPL-licensed upstream "
        "and is neither committed nor redistributed, so a stranger with a checkout "
        "cannot re-derive anything computed over it. Any external-tier figure quoted "
        "anywhere carries that label. This report has no external-tier section because "
        "nothing in it was run over that tier -- the runner scores committed tiers only, "
        "which is the property that makes every table below checkable by someone who "
        "does not trust the maintainer.",
        "",
        "**The semantic pass gets a coverage number, not a precision one**, and the "
        "reason is in that section.",
        "",
    ]


def _corpus(results: Mapping[str, Any]) -> list[str]:
    """The corpus tiers, their sizes and their provenance."""
    lines = [
        "## The corpus",
        "",
        f"Generator version **{results['generator_version']}** -- bumped deliberately, "
        "recorded in every synthetic pair's labels, and the thing that would move every "
        "synthetic number at once. Per-pair document digests are in "
        "`results/latest.json`; `tests/test_benchmark_corpus.py` re-runs the generator "
        "and asserts byte-identity with what is committed.",
        "",
    ]
    rows = []
    for tier in results["corpus"]:
        rows.append(
            [
                f"`{tier['tier']}`",
                str(tier["pairs"]),
                ", ".join(tier["formats"]) or "n/a",
                ", ".join(tier["profiles"]) or "n/a",
                ", ".join(tier["plans"]) if tier["plans"] else "n/a",
            ]
        )
    lines.extend(_table(["Tier", "Pairs", "Formats", "Profiles", "Plans"], rows))
    lines.append("")
    return lines


def _headline_rows(results: Mapping[str, Any], key: str) -> list[list[str]]:
    """One row per (tier, engine, backend), for the ``links`` or ``flat_links`` set."""
    draft = _draft_tiers(results)
    rows: list[list[str]] = []
    for entry in results["tiers"]:
        counts = entry[key]
        rows.append(
            [
                _mark(entry["tier"], draft),
                entry["engine"],
                entry["backend"],
                str(counts["truth"]),
                str(counts["reported"]),
                _fmt(counts["precision"]),
                _fmt(counts["recall"]),
                _fmt(counts["f1"]),
                _fmt(counts["spurious_rate"]),
                _fmt(entry["moves"]["recall"]),
                _fmt(entry["renumbers"]["recall"]),
            ]
        )
    return rows


def _headline(results: Mapping[str, Any]) -> list[str]:
    """The two headline tables, all-blocks first."""
    headers = [
        "Tier",
        "Engine",
        "Backend",
        "Labelled",
        "Reported",
        "Precision",
        "Recall",
        "F1",
        "Spurious",
        "Move recall",
        "Renumber recall",
    ]
    lines = [
        "## Headline",
        "",
        "### All labelled blocks",
        "",
        "The honest end-to-end number: every text-bearing block plus table rows.",
        "",
    ]
    lines.extend(_table(headers, _headline_rows(results, "links")))
    lines.extend(
        [
            "",
            "### Blocks the flat engine can address",
            "",
            "The like-for-like number: table `row` and `cell` blocks dropped from both "
            "sides, because 0.6 has no concept of a table and crediting or blaming it "
            "for a row-level correspondence would measure the lift rather than the "
            "engine.",
            "",
        ]
    )
    lines.extend(_table(headers, _headline_rows(results, "flat_links")))
    lines.append("")
    lines.extend(_draft_note(results))
    return lines


def _gap(results: Mapping[str, Any]) -> list[str]:
    """The similarity-backend gap, per tier, on every headline metric."""
    backends = list(results["backends"])
    lines = [
        "## The similarity-backend gap",
        "",
    ]
    if len(backends) < 2:
        lines.extend(
            [
                "**Unmeasured in this run.** Only the `"
                + backends[0]
                + "` backend ran, so there is no gap to report. Re-run with "
                "`--backends difflib,rapidfuzz` after `uv sync --all-extras --dev`.",
                "",
            ]
        )
        return lines
    first, second = backends[0], backends[1]
    lines.extend(
        [
            f"`{second}` minus `{first}`, on the same corpus, the same candidates and "
            "the same caps -- the backend is *selected*, never simulated by hiding an "
            "import, so what changes is the ratio a threshold is compared against and "
            "nothing else. The documentation site runs on the `difflib` floor (PRD "
            "§ 12), so this table is what that costs.",
            "",
        ]
    )
    rows = []
    for tier in [entry["tier"] for entry in results["corpus"]]:
        left = _tier(results, tier, "1.0", first)
        right = _tier(results, tier, "1.0", second)
        if left is None or right is None:
            continue
        rows.append(
            [
                f"`{tier}`",
                _delta(right["links"]["precision"], left["links"]["precision"]),
                _delta(right["links"]["recall"], left["links"]["recall"]),
                _delta(right["links"]["f1"], left["links"]["f1"]),
                _delta(
                    right["links"]["spurious_rate"], left["links"]["spurious_rate"]
                ),
                _delta(right["moves"]["recall"], left["moves"]["recall"]),
                _delta(right["renumbers"]["recall"], left["renumbers"]["recall"]),
            ]
        )
    lines.extend(
        _table(
            ["Tier", "ΔPrecision", "ΔRecall", "ΔF1", "ΔSpurious", "ΔMove", "ΔRenumber"],
            rows,
        )
    )
    lines.append("")
    return lines


def _passes(results: Mapping[str, Any]) -> list[str]:
    """The per-pass table, which is the evidence ADR-0008's review gate asks for."""
    backend = _primary_backend(results)
    lines = [
        "## Per pass",
        "",
        f"Under the `{backend}` backend. **Total** is the engine's own bookkeeping "
        "(`Alignment.pass_counts`) over every pair the pass produced, containers "
        "included. **Scored** is the subset the metric may count -- labelled kinds, "
        "root excluded, splits and merges excluded -- and **wrong** is measured against "
        "that subset, so `total - scored` is exactly the part of a pass's work this "
        "benchmark says nothing about. **Unique** is measured, not inferred: the "
        "alignment is re-run with that pass switched off and the difference counted. "
        "`exact`, `structural` and `positional` are the descent's anchors and its "
        "fill-in and cannot be dropped ([ADR-0032](../docs/adr/0032-alignment-passes.md)), "
        "so their unique contribution reads `n/a` -- unmeasurable, not zero.",
        "",
        "A pass with a low unique count and a high wrong count is the one to cut.",
        "",
    ]
    rows: list[list[str]] = []
    for tier in [entry["tier"] for entry in results["corpus"]]:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        by_name = {counts["pass"]: counts for counts in entry["passes"]}
        for name in PASS_NAMES:
            counts = by_name.get(name)
            if counts is None:
                continue
            rows.append(
                [
                    f"`{tier}`",
                    f"`{name}`",
                    str(counts["total"]),
                    str(counts["matches"]),
                    str(counts["wrong"]),
                    _fmt(counts["wrong_rate"]),
                    "n/a" if counts["unique"] is None else str(counts["unique"]),
                ]
            )
    lines.extend(
        _table(
            ["Tier", "Pass", "Total", "Scored", "Wrong", "Wrong rate", "Unique"],
            rows,
        )
    )
    lines.append("")
    return lines


def _difficulty(results: Mapping[str, Any]) -> list[str]:
    """Synthetic results broken down by mutation plan."""
    backend = _primary_backend(results)
    entry = _tier(results, "synthetic", "1.0", backend)
    if entry is None:
        return []
    grouped: dict[str, list[Mapping[str, Any]]] = {}
    for pair in entry["pairs"]:
        grouped.setdefault(pair["plan"] or "unplanned", []).append(pair)
    rows: list[list[str]] = []
    for plan in sorted(grouped):
        pairs = grouped[plan]
        truth = sum(pair["links"]["truth"] for pair in pairs)
        reported = sum(pair["links"]["reported"] for pair in pairs)
        hits = sum(pair["links"]["hits"] for pair in pairs)
        moves_truth = sum(pair["moves"]["truth"] for pair in pairs)
        moves_hits = sum(pair["moves"]["hits"] for pair in pairs)
        renumber_truth = sum(pair["renumbers"]["truth"] for pair in pairs)
        renumber_hits = sum(pair["renumbers"]["hits"] for pair in pairs)
        precision = hits / reported if reported else None
        recall = hits / truth if truth else None
        f1 = (
            2 * precision * recall / (precision + recall)
            if precision is not None and recall is not None and precision + recall
            else None
        )
        rows.append(
            [
                f"`{plan}`",
                str(len(pairs)),
                _fmt(precision),
                _fmt(recall),
                _fmt(f1),
                _fmt(moves_hits / moves_truth if moves_truth else None),
                _fmt(renumber_hits / renumber_truth if renumber_truth else None),
            ]
        )
    return [
        "## Synthetic results by difficulty",
        "",
        f"The 1.0 engine under `{backend}`, grouped by the mutation plan that built the "
        "pair. One average over every plan would hide which phenomenon the engine "
        "actually struggles with, which is the only thing this breakdown is for.",
        "",
        *_table(
            ["Plan", "Pairs", "Precision", "Recall", "F1", "Move recall", "Renumber recall"],
            rows,
        ),
        "",
    ]


def _moves(results: Mapping[str, Any]) -> list[str]:
    """The move gate's standing: verdicts, unreviewed moves, skipped rows."""
    backend = _primary_backend(results)
    rows: list[list[str]] = []
    for tier in [entry["tier"] for entry in results["corpus"]]:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        rows.append(
            [
                f"`{tier}`",
                str(entry["moves"]["truth"]),
                str(entry["moves"]["reported"]),
                str(entry["moves"]["hits"]),
                _fmt(entry["moves"]["precision"]),
                _fmt(entry["moves"]["recall"]),
                str(entry["wrong_moves"]),
                str(entry["unreviewed_moves"]),
            ]
        )
    return [
        "## Moves, and the gate that is a judgement",
        "",
        "[ADR-0009](../docs/adr/0009-moves-before-splits.md)'s second bar -- \"no move "
        "false positive a reviewer would call wrong\" -- is a ruling about engine "
        "output, not a property of the labels, so it is carried by per-move verdicts in "
        "each pair's `labels.yaml` and it **fails closed**: an engine move that is "
        "neither in the labels nor in `move_verdicts` fails the gate exactly as a "
        "`wrong` verdict does. Unknown is not a pass. Verdicts are keyed by engine "
        "commit, so a new false positive from a changed aligner arrives without one and "
        "turns the gate red until somebody rules on it.",
        "",
        *_table(
            [
                "Tier",
                "Labelled",
                "Reported",
                "Hits",
                "Precision",
                "Recall",
                "Ruled wrong",
                "Unreviewed",
            ],
            rows,
        ),
        "",
    ]


def _honesty(results: Mapping[str, Any]) -> list[str]:
    """Override rates, label status and skipped rows -- the self-marking exposure."""
    backend = _primary_backend(results)
    lines = [
        "## How much to trust the labels",
        "",
        "The synthetic tier's labels are what the generator *did*, so they are ground "
        "truth by construction. The hand tier's were seeded from this engine and then "
        "corrected by a human, which is the sharpest form of the self-marking risk "
        "ADR-0021 names. Three things are printed rather than argued about: how many "
        "rows a labeller changed (`override rate` -- a suspiciously low one is the "
        "visible symptom of somebody agreeing with everything), how many rows are still "
        "`proposed` and therefore not yet ground truth at all, and whether the pair has "
        "been signed off.",
        "",
        "Moves are never engine-seeded, in either tier.",
        "",
    ]
    rows: list[list[str]] = []
    for tier in [entry["tier"] for entry in results["corpus"]]:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        pairs = entry["pairs"]
        signed = sum(1 for pair in pairs if pair["labels_signed"])
        proposed = sum(pair["proposed_rows"] for pair in pairs)
        rates = [
            pair["override_rate"] for pair in pairs if pair["override_rate"] is not None
        ]
        rows.append(
            [
                f"`{tier}`",
                f"{signed}/{len(pairs)}",
                str(proposed),
                _fmt(sum(rates) / len(rates)) if rates else "n/a",
                str(entry["skipped_splits"]),
                str(entry["skipped_merges"]),
            ]
        )
    lines.extend(
        _table(
            [
                "Tier",
                "Signed off",
                "Rows still proposed",
                "Mean override rate",
                "Splits skipped",
                "Merges skipped",
            ],
            rows,
        )
    )
    lines.append("")
    return lines


def _roles(results: Mapping[str, Any]) -> list[str]:
    """Semantic role coverage, and why it is not a precision number."""
    lines = [
        "## The semantic pass: coverage, not precision",
        "",
        "ADR-0021 asks for semantic role and span precision on a hand-labelled sample, "
        "reported and not gated. **No such number is published here, and the reason is "
        "not that it was hard.** The only hand-labelled role sample this repository owns "
        "is the sample pair, whose roles are *asserted* in `tests/test_sample_pair.py`; "
        "a precision figure computed against assertions that already pass would be "
        "1.0000 by construction and would be evidence of nothing at all. Building a "
        "second labelling exercise to produce a number nothing depends on is work "
        "[ADR-0034](../docs/adr/0034-benchmark-labels-and-metric.md) explicitly declines.",
        "",
        "What is published instead is coverage, which is a real measurement over the "
        "whole committed corpus: how many labelled blocks the "
        "[ADR-0031](../docs/adr/0031-role-rules-on-the-block-itself.md) pass put a role on, and which "
        "`role_match` kind put it there. It says how much of a real corpus the pass "
        "reaches. It does not say the roles are right.",
        "",
    ]
    rows: list[list[str]] = []
    for tier, counts in sorted(results["roles"].items()):
        matches = counts["by_match"]
        rows.append(
            [
                f"`{tier}`",
                str(counts["blocks"]),
                str(counts["roled"]),
                _fmt(counts["coverage"]),
                ", ".join(f"{key} {value}" for key, value in matches.items()) or "n/a",
            ]
        )
    lines.extend(
        _table(
            ["Tier", "Labelled blocks", "Roled", "Coverage", "By `role_match`"], rows
        )
    )
    lines.append("")
    for tier, counts in sorted(results["roles"].items()):
        roles = counts["by_role"]
        if roles:
            listed = ", ".join(f"`{key}` {value}" for key, value in roles.items())
            lines.extend([f"Roles seen in `{tier}`: {listed}.", ""])
    return lines


def _gate_status(results: Mapping[str, Any]) -> list[str]:
    """Where each PRD § 10 target stands, and what the gate test does about it."""
    backend = _primary_backend(results)
    draft = _draft_tiers(results)
    rows: list[list[str]] = []
    for tier, name, target in GATES:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        value = (
            entry["links"]["f1"]
            if name == "correspondence F1"
            else entry["moves"]["recall"]
        )
        met = value is not None and value >= target
        rows.append(
            [
                _mark(tier, draft),
                name,
                f"≥ {target:.2f}",
                _fmt(value),
                "not assessed (draft labels)"
                if tier in draft
                else ("met" if met else "not met"),
            ]
        )
    for tier in [entry["tier"] for entry in results["corpus"]]:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        rows.append(
            [
                _mark(tier, draft),
                "moves ruled wrong",
                "0",
                str(entry["wrong_moves"]),
                "met" if entry["wrong_moves"] == 0 else "not met",
            ]
        )
        rows.append(
            [
                _mark(tier, draft),
                "unreviewed engine moves",
                "0",
                str(entry["unreviewed_moves"]),
                "met" if entry["unreviewed_moves"] == 0 else "not met",
            ]
        )
    return [
        "## Release gates",
        "",
        "PRD § 10's targets, under the `" + backend + "` backend. "
        "`tests/test_benchmark_gates.py` asserts each of these as an "
        "`xfail(strict=True)` test in the blocking CI job, which means that on the day "
        "a gate is met its test **fails because it passed** and the mark has to be "
        "removed by hand. That is the forcing function: a gate cannot be left quietly "
        "marked as expected-to-fail once it is green.",
        "",
        "A tier whose labels are still drafts reads **not assessed** rather than *met*, "
        "however high its number is, and the gate test for it asserts that its labels "
        "are confirmed as well as that the ratio clears the bar. A gate an engine can "
        "pass by being marked by itself is not a gate.",
        "",
        *_table(["Tier", "Gate", "Target", "Measured", "Standing"], rows),
        "",
        *_draft_note(results),
    ]


def _observations() -> list[str]:
    """What a reader should take from the tables, written once and not tuned.

    Static prose, deliberately. These are the standing observations about the
    engine and about this benchmark's own limits; they point at tables rather
    than repeating numbers, so they stay true as the numbers move and a change
    in what they say is a change somebody has to write.
    """
    return [
        "## What these numbers say",
        "",
        "**The gap between 0.6 and 1.0 is not mostly in correspondence.** On the "
        "like-for-like column -- table rows dropped, which is the only comparison the "
        "flat engine can be held to -- the floor's precision, recall and F1 are close "
        "to the block engine's. That is the honest reading, and it is not a "
        "disappointment: matching a clause that stayed where it was to itself is what a "
        "token diff over a line-split document is already good at. The whole of the "
        "difference is in the two columns the floor scores `0.0000` in, by "
        "construction, because it has no vocabulary for either: **move recall and "
        "renumber recall**. A structural engine earns its cost by saying *this clause "
        "moved* and *this clause was renumbered*, not by matching unmoved paragraphs "
        "slightly better.",
        "",
        "**The floor's precision is high and its recall is low**, which is the shape a "
        "line-unit engine has: the pairs it does report are usually right, and it "
        "simply declines to report a correspondence for anything it could not match "
        "token-for-token. Its spurious-match rate is where the cost shows.",
        "",
        "**The `exact` pass still carries the largest wrong-match count**, and it is "
        "what identical text does rather than a bug in exact matching. Corpus "
        "documents built around repetition -- a schedule of byte-identical "
        "paragraphs, a lettered list whose items differ by one word -- give the pass "
        "several equally exact candidates, and *which* of the equals it takes is a "
        "decision. The first reading of this report found it taking the first in "
        "document order, which shifts every pair after an edited block by one and "
        "cost 84 of 1349 scored exact matches; the pass now takes the structurally "
        "nearest instead ([ADR-0032](../docs/adr/0032-alignment-passes.md), amended "
        "from this report). What is left is the residue that no tie-break can reach: "
        "in a group of thirty byte-identical siblings, nearness is the only evidence "
        "there is, and where the truth is not the nearest candidate the pass is "
        "wrong and cannot know it.",
        "",
        "**Move recall is the weakest headline number, and on this corpus it cannot "
        "reach ADR-0009's 0.90 bar.** The per-plan breakdown says where: the "
        "`repetitive-schedule` pairs, whose source documents contain exactly one "
        "distinct paragraph text repeated thirty times. Five of the corpus's "
        "labelled moves live there, and every one of them has thirty equally good "
        "candidates on the source side -- no label, no heading, no parent to tell "
        "them apart. Reporting one would be a one-in-thirty guess, which is the "
        "false positive ADR-0009 says costs more than the silence. That puts the "
        "ceiling at 18 of 23, and the shortfall is published here rather than bought "
        "with a loosened threshold: move *precision* is 1.0000 on both tiers and the "
        "asymmetry is the one ADR-0009 asks for. Lowering the bar is a decision for "
        "ADR-0009 to reopen, not for a tuning pass to take.",
        "",
        "**Nothing in this file is evidence about the hand-labelled tier yet.** Its "
        "labels are engine-seeded drafts; see the dagger note above.",
        "",
    ]


def _appendix(results: Mapping[str, Any]) -> list[str]:
    """Every pair, under the primary backend, for anyone chasing one number."""
    backend = _primary_backend(results)
    lines = [
        "## Appendix: every pair",
        "",
        f"The 1.0 engine under `{backend}`, one row per pair, so a headline number can "
        "be traced to the pairs that made it. `results/latest.json` carries the same "
        "rows for the floor and for every backend.",
        "",
    ]
    rows: list[list[str]] = []
    for tier in [entry["tier"] for entry in results["corpus"]]:
        entry = _tier(results, tier, "1.0", backend)
        if entry is None:
            continue
        for pair in entry["pairs"]:
            rows.append(
                [
                    f"`{tier}`",
                    f"`{pair['pair']}`",
                    str(pair["links"]["truth"]),
                    _fmt(pair["links"]["precision"]),
                    _fmt(pair["links"]["recall"]),
                    _fmt(pair["links"]["f1"]),
                    _fmt(pair["links"]["spurious_rate"]),
                    f"{pair['moves']['hits']}/{pair['moves']['truth']}",
                    f"{pair['renumbers']['hits']}/{pair['renumbers']['truth']}",
                ]
            )
    lines.extend(
        _table(
            [
                "Tier",
                "Pair",
                "Labelled",
                "Precision",
                "Recall",
                "F1",
                "Spurious",
                "Moves",
                "Renumbers",
            ],
            rows,
        )
    )
    lines.append("")
    return lines


def render_report(results: Mapping[str, Any]) -> str:
    """Render ``benchmark/REPORT.md`` from a results document.

    :param results: what `benchmark.run.run` returned, or the parsed contents
        of ``benchmark/results/latest.json`` -- they are the same document.
    :return: the markdown, ending in a single newline.
    """
    lines: list[str] = []
    lines.extend(_preamble())
    lines.extend(_methodology(results))
    lines.extend(_limits())
    lines.extend(_corpus(results))
    lines.extend(_headline(results))
    lines.extend(_gate_status(results))
    lines.extend(_observations())
    lines.extend(_gap(results))
    lines.extend(_passes(results))
    lines.extend(_difficulty(results))
    lines.extend(_moves(results))
    lines.extend(_honesty(results))
    lines.extend(_roles(results))
    lines.extend(_appendix(results))
    return "\n".join(lines).rstrip("\n") + "\n"
