# The redlines alignment benchmark

How well does this engine work out which clause of the old document became which clause of the new one? This report answers that against a committed corpus, with the flat 0.6 engine as the floor, and it is generated -- `uv run python -m benchmark.run --tier all` rewrites both this file and `benchmark/results/latest.json`, so a number moving is a diff somebody reads.

The design is [ADR-0021](../docs/adr/0021-alignment-benchmark.md) (why there is a benchmark at all, and before tuning rather than after) and [ADR-0034](../docs/adr/0034-benchmark-labels-and-metric.md) (the label format, every definition below, and the alternatives each was chosen over).

## Methodology

### What is being scored

The **alignment**, not the change tree. Two blocks that correspond and did not change produce no change node at all, so the change tree cannot express the correspondence set; `Comparison.alignment` can, and is public for this reason. Moves and renumbers *are* read off the change tree, because their granularity rules live there -- scoring them off anything else would let the engine and its own metric disagree about what a move is.

### The correspondence metric

Let `C*` be the labelled correspondence set as `(source address, test address)` pairs and `C` the engine's reported pairs. Then **precision** is `|C ∩ C*| / |C|`, **recall** is `|C ∩ C*| / |C*|`, and **F1** is their harmonic mean. Six rules fix the denominators:

1. **Links only.** A block the labels call inserted or deleted is in neither denominator. Counting correctly-unmatched blocks would let a long document with three edits inflate its F1 by saying nothing about most of itself, and would make the score a function of document length.
2. **The spurious-match rate** is the counterweight that makes rule 1 safe: the fraction of reported pairs with one side labelled inserted or deleted. Links-only precision cannot see a fill-in pass inventing matches; this can, and it is printed beside precision everywhere, never instead of it.
3. **The root pair is excluded.** `/` corresponds to `/` in every comparison ever made, and crediting an engine for knowing a document is itself flatters every number in the table.
4. **Containers are not labelled**, so they are in neither set: text-bearing blocks plus table `row` blocks, on both sides.
5. **A moved subtree counts once**, at the topmost block whose whole subtree moved; its descendants are ordinary correspondences. This is the same rule the change tree emits `move` nodes under, so the engine is scored against the definition of *move* it actually uses.
6. **Renumber recall keys on the four-tuple** `(source address, test address, source label, test label)`. A renumber reported with the wrong new label is not a hit. Both sides derive the set the same way, from labels that differ, so a block that moved *and* was relabelled is one row of ground truth feeding two metrics.

**Splits and merges are labelled and excluded** from every denominator in this release, along with any region the labels mark `unscored`. The counts appear below, so the day 1.1 scores them the delta is measurable rather than a guess.

Counts are integers; ratios are computed once from summed counts (a micro-average, never a mean of means) and rounded at the boundary. A cell reading `n/a` had a zero denominator; it is not a zero.

### The 0.6 floor, and how a flat engine gets an address

The floor is the flat engine called directly -- `WholeDocumentProcessor(autojunk=False)`, never the `Redlines` class, which M3 reimplements over this same core and which would therefore stop being the 0.6 baseline the day the facade lands. A test asserts the import prohibition so the substitution cannot happen quietly.

0.6 has no block model, so getting a correspondence set out of it means deciding what its opcodes *imply*. There are exactly two decisions, and this is the only place either can be flattered or hobbled, so both are stated here as well as in the source:

- **Opcodes to unit pairs.** Every `equal` opcode pairs its tokens one for one and each paired token votes for the pair of units its two tokens sit in. Every `replace` opcode pairs the units it spans by relative order -- first with first, and so on until one side runs out -- one vote each. A source unit takes the test unit with the most votes; ties go to the smallest test unit index. `insert` and `delete` pair nothing.
- **Unit pairs to block pairs.** A unit is assigned to the first block at or after a monotone pointer whose normalised text contains it, and a source block takes the **plurality** of its units' targets, ties broken by the earliest test block in document order. A unit that matches no block within the search window is assigned nothing rather than attached to whatever was nearest.

Both rules are generous to the floor rather than mean to it: voting lets one strongly-matched line carry a block whose other lines drifted, and relative-order pairing inside a `replace` credits 0.6 with correspondences it never states.

Two columns are reported for every engine. **All labelled blocks** is the honest end-to-end number. **Flat-addressable blocks** excludes table `row` and `cell` blocks, which the flat engine has no concept of, and is the like-for-like one. The floor's move recall and renumber recall are `0.0000` by construction and are printed rather than left blank: 0.6 cannot express either, and that cell is the argument for this milestone. Its unit is a **line**, not a paragraph, so it necessarily gets a whitespace-only rewrap wrong. That is what a floor is.

### The configuration in force

Headline numbers are quoted under the **difflib** backend, which is what the documentation site runs on (PRD § 12); the gap to the other backend has its own section. Thresholds, from `AlignmentConfig` defaults:

```
passes                    exact, label, structural, fuzzy, move, positional
fuzzy_min_similarity      0.6
label_min_similarity      0.5
positional_min_similarity 0.35
move_min_similarity       0.8
move_tie_margin           0.1
move_min_tokens           8
move_kinds                paragraph, list_item, heading
fuzzy_window              25
table_fuzzy               False
max_comparisons           2000000
```

### Reproducing this, and dating it

```
uv sync --all-extras --dev
uv run python -m benchmark.run --tier all
```

Nothing written by that command carries a clock -- no date, no duration, no host, no run id -- so re-running it on an unchanged checkout rewrites both files byte for byte and `--check` is a real test rather than a formality. The engine commit is deliberately not stamped into the files either: it would go stale on the next commit and break byte-stability for a reason that has nothing to do with the engine. `git log -1 --format=%H benchmark/results/latest.json` answers the question from the repository's own record.

## What this report does not claim

**There is no like-for-like re-run of the `neurotic_docx_bench` 45.9 figure, and there cannot be one in 1.0.** That benchmark scores a tracked-changes DOCX produced by the tool under test; [ADR-0014](../docs/adr/0014-no-ooxml-writing.md) rules out writing OOXML, so this project cannot produce the artefact the bench grades. The published 45.9 came from a third-party adapter rather than from this project, and nothing below is comparable with it. The bench's base documents are used here only as a *text source* for mutation, in the uncommitted tier, which is a different use of the same repository and not a claim about that score.

**Numbers from `benchmark/corpus/external/` are not reproducible from this repository.** That tier is gitignored: its material is AGPL-licensed upstream and is neither committed nor redistributed, so a stranger with a checkout cannot re-derive anything computed over it. Any external-tier figure quoted anywhere carries that label. This report has no external-tier section because nothing in it was run over that tier -- the runner scores committed tiers only, which is the property that makes every table below checkable by someone who does not trust the maintainer.

**The semantic pass gets a coverage number, not a precision one**, and the reason is in that section.

## The corpus

Generator version **1** -- bumped deliberately, recorded in every synthetic pair's labels, and the thing that would move every synthetic number at once. Per-pair document digests are in `results/latest.json`; `tests/test_benchmark_corpus.py` re-runs the generator and asserts byte-identity with what is committed.

| Tier | Pairs | Formats | Profiles | Plans |
|---|---|---|---|---|
| `synthetic` | 40 | markdown, text | contract, markdown | heavy, light, mixed, move-heavy, renumber-storm, structure, table |
| `hand` | 10 | markdown, text | contract, markdown | n/a |

## Headline

### All labelled blocks

The honest end-to-end number: every text-bearing block plus table rows.

| Tier | Engine | Backend | Labelled | Reported | Precision | Recall | F1 | Spurious | Move recall | Renumber recall |
|---|---|---|---|---|---|---|---|---|---|---|
| `synthetic` | 1.0 | difflib | 1580 | 1579 | 0.9753 | 0.9747 | 0.9750 | 0.0000 | 0.7826 | 0.9932 |
| `synthetic` | 1.0 | rapidfuzz | 1580 | 1579 | 0.9753 | 0.9747 | 0.9750 | 0.0000 | 0.7826 | 0.9932 |
| `synthetic` | 0.6 | none | 1580 | 1327 | 0.9789 | 0.8222 | 0.8937 | 0.0121 | 0.0000 | 0.0000 |
| `hand` † | 1.0 | difflib | 644 | 644 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | n/a | 1.0000 |
| `hand` † | 1.0 | rapidfuzz | 644 | 644 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | n/a | 1.0000 |
| `hand` † | 0.6 | none | 644 | 653 | 0.9648 | 0.9783 | 0.9715 | 0.0337 | n/a | 0.0000 |

### Blocks the flat engine can address

The like-for-like number: table `row` and `cell` blocks dropped from both sides, because 0.6 has no concept of a table and crediting or blaming it for a row-level correspondence would measure the lift rather than the engine.

| Tier | Engine | Backend | Labelled | Reported | Precision | Recall | F1 | Spurious | Move recall | Renumber recall |
|---|---|---|---|---|---|---|---|---|---|---|
| `synthetic` | 1.0 | difflib | 1444 | 1443 | 0.9730 | 0.9723 | 0.9726 | 0.0000 | 0.7826 | 0.9932 |
| `synthetic` | 1.0 | rapidfuzz | 1444 | 1443 | 0.9730 | 0.9723 | 0.9726 | 0.0000 | 0.7826 | 0.9932 |
| `synthetic` | 0.6 | none | 1444 | 1327 | 0.9789 | 0.8996 | 0.9376 | 0.0121 | 0.0000 | 0.0000 |
| `hand` † | 1.0 | difflib | 644 | 644 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | n/a | 1.0000 |
| `hand` † | 1.0 | rapidfuzz | 644 | 644 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | n/a | 1.0000 |
| `hand` † | 0.6 | none | 644 | 653 | 0.9648 | 0.9783 | 0.9715 | 0.0337 | n/a | 0.0000 |

† **These labels are drafts, not ground truth: `hand` (644 rows).** Every one of those correspondence rows is still `status: proposed` -- what `benchmark/label.py init` proposed *from this engine's own alignment*, with no human having confirmed or corrected it. A score against them measures whether the engine agrees with itself, so read the row as provenance rather than as evidence, and read `How much to trust the labels` below before quoting it. The numbers are published anyway, marked, because suppressing them until the labelling is finished would make the unfinished labelling invisible -- which is the failure ADR-0021 built this report to prevent.

## Release gates

PRD § 10's targets, under the `difflib` backend. `tests/test_benchmark_gates.py` asserts each of these as an `xfail(strict=True)` test in the blocking CI job, which means that on the day a gate is met its test **fails because it passed** and the mark has to be removed by hand. That is the forcing function: a gate cannot be left quietly marked as expected-to-fail once it is green.

A tier whose labels are still drafts reads **not assessed** rather than *met*, however high its number is, and the gate test for it asserts that its labels are confirmed as well as that the ratio clears the bar. A gate an engine can pass by being marked by itself is not a gate.

| Tier | Gate | Target | Measured | Standing |
|---|---|---|---|---|
| `synthetic` | correspondence F1 | ≥ 0.95 | 0.9750 | met |
| `hand` † | correspondence F1 | ≥ 0.85 | 1.0000 | not assessed (draft labels) |
| `synthetic` | move recall | ≥ 0.90 | 0.7826 | not met |
| `synthetic` | moves ruled wrong | 0 | 0 | met |
| `synthetic` | unreviewed engine moves | 0 | 0 | met |
| `hand` † | moves ruled wrong | 0 | 0 | met |
| `hand` † | unreviewed engine moves | 0 | 3 | not met |

† **These labels are drafts, not ground truth: `hand` (644 rows).** Every one of those correspondence rows is still `status: proposed` -- what `benchmark/label.py init` proposed *from this engine's own alignment*, with no human having confirmed or corrected it. A score against them measures whether the engine agrees with itself, so read the row as provenance rather than as evidence, and read `How much to trust the labels` below before quoting it. The numbers are published anyway, marked, because suppressing them until the labelling is finished would make the unfinished labelling invisible -- which is the failure ADR-0021 built this report to prevent.

## What these numbers say

**The gap between 0.6 and 1.0 is not mostly in correspondence.** On the like-for-like column -- table rows dropped, which is the only comparison the flat engine can be held to -- the floor's precision, recall and F1 are close to the block engine's. That is the honest reading, and it is not a disappointment: matching a clause that stayed where it was to itself is what a token diff over a line-split document is already good at. The whole of the difference is in the two columns the floor scores `0.0000` in, by construction, because it has no vocabulary for either: **move recall and renumber recall**. A structural engine earns its cost by saying *this clause moved* and *this clause was renumbered*, not by matching unmoved paragraphs slightly better.

**The floor's precision is high and its recall is low**, which is the shape a line-unit engine has: the pairs it does report are usually right, and it simply declines to report a correspondence for anything it could not match token-for-token. Its spurious-match rate is where the cost shows.

**The `exact` pass still carries the largest wrong-match count**, and it is what identical text does rather than a bug in exact matching. Corpus documents built around repetition -- a schedule of byte-identical paragraphs, a lettered list whose items differ by one word -- give the pass several equally exact candidates, and *which* of the equals it takes is a decision. The first reading of this report found it taking the first in document order, which shifts every pair after an edited block by one and cost 84 of 1349 scored exact matches; the pass now takes the structurally nearest instead ([ADR-0032](../docs/adr/0032-alignment-passes.md), amended from this report). What is left is the residue that no tie-break can reach: in a group of thirty byte-identical siblings, nearness is the only evidence there is, and where the truth is not the nearest candidate the pass is wrong and cannot know it.

**Move recall is the weakest headline number, and on this corpus it cannot reach ADR-0009's 0.90 bar.** The per-plan breakdown says where: the `repetitive-schedule` pairs, whose source documents contain exactly one distinct paragraph text repeated thirty times. Five of the corpus's labelled moves live there, and every one of them has thirty equally good candidates on the source side -- no label, no heading, no parent to tell them apart. Reporting one would be a one-in-thirty guess, which is the false positive ADR-0009 says costs more than the silence. That puts the ceiling at 18 of 23, and the shortfall is published here rather than bought with a loosened threshold: move *precision* is 1.0000 on both tiers and the asymmetry is the one ADR-0009 asks for. Lowering the bar is a decision for ADR-0009 to reopen, not for a tuning pass to take.

**Nothing in this file is evidence about the hand-labelled tier yet.** Its labels are engine-seeded drafts; see the dagger note above.

## The similarity-backend gap

`rapidfuzz` minus `difflib`, on the same corpus, the same candidates and the same caps -- the backend is *selected*, never simulated by hiding an import, so what changes is the ratio a threshold is compared against and nothing else. The documentation site runs on the `difflib` floor (PRD § 12), so this table is what that costs.

| Tier | ΔPrecision | ΔRecall | ΔF1 | ΔSpurious | ΔMove | ΔRenumber |
|---|---|---|---|---|---|---|
| `synthetic` | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 | +0.0000 |
| `hand` | +0.0000 | +0.0000 | +0.0000 | +0.0000 | n/a | +0.0000 |

## Per pass

Under the `difflib` backend. **Total** is the engine's own bookkeeping (`Alignment.pass_counts`) over every pair the pass produced, containers included. **Scored** is the subset the metric may count -- labelled kinds, root excluded, splits and merges excluded -- and **wrong** is measured against that subset, so `total - scored` is exactly the part of a pass's work this benchmark says nothing about. **Unique** is measured, not inferred: the alignment is re-run with that pass switched off and the difference counted. `exact`, `structural` and `positional` are the descent's anchors and its fill-in and cannot be dropped ([ADR-0032](../docs/adr/0032-alignment-passes.md)), so their unique contribution reads `n/a` -- unmeasurable, not zero.

A pass with a low unique count and a high wrong count is the one to cut.

| Tier | Pass | Total | Scored | Wrong | Wrong rate | Unique |
|---|---|---|---|---|---|---|
| `synthetic` | `exact` | 1617 | 1349 | 37 | 0.0274 | n/a |
| `synthetic` | `label` | 85 | 69 | 0 | 0.0000 | 0 |
| `synthetic` | `structural` | 7 | 0 | 0 | n/a | n/a |
| `synthetic` | `fuzzy` | 42 | 39 | 2 | 0.0513 | 2 |
| `synthetic` | `move` | 18 | 18 | 0 | 0.0000 | 18 |
| `synthetic` | `positional` | 104 | 104 | 0 | 0.0000 | n/a |
| `hand` | `exact` | 588 | 564 | 0 | 0.0000 | n/a |
| `hand` | `label` | 14 | 14 | 0 | 0.0000 | 0 |
| `hand` | `structural` | 6 | 0 | 0 | n/a | n/a |
| `hand` | `fuzzy` | 59 | 59 | 0 | 0.0000 | 4 |
| `hand` | `move` | 3 | 3 | 0 | 0.0000 | 3 |
| `hand` | `positional` | 4 | 4 | 0 | 0.0000 | n/a |

## Synthetic results by difficulty

The 1.0 engine under `difflib`, grouped by the mutation plan that built the pair. One average over every plan would hide which phenomenon the engine actually struggles with, which is the only thing this breakdown is for.

| Plan | Pairs | Precision | Recall | F1 | Move recall | Renumber recall |
|---|---|---|---|---|---|---|
| `heavy` | 7 | 1.0000 | 1.0000 | 1.0000 | n/a | 1.0000 |
| `light` | 9 | 1.0000 | 1.0000 | 1.0000 | n/a | n/a |
| `mixed` | 10 | 0.9474 | 0.9474 | 0.9474 | 0.8571 | 1.0000 |
| `move-heavy` | 6 | 0.9094 | 0.9094 | 0.9094 | 0.7500 | 1.0000 |
| `renumber-storm` | 4 | 1.0000 | 1.0000 | 1.0000 | n/a | 1.0000 |
| `structure` | 3 | 1.0000 | 0.9947 | 0.9973 | n/a | 0.9600 |
| `table` | 1 | 1.0000 | 1.0000 | 1.0000 | n/a | n/a |

## Moves, and the gate that is a judgement

[ADR-0009](../docs/adr/0009-moves-before-splits.md)'s second bar -- "no move false positive a reviewer would call wrong" -- is a ruling about engine output, not a property of the labels, so it is carried by per-move verdicts in each pair's `labels.yaml` and it **fails closed**: an engine move that is neither in the labels nor in `move_verdicts` fails the gate exactly as a `wrong` verdict does. Unknown is not a pass. Verdicts are keyed by engine commit, so a new false positive from a changed aligner arrives without one and turns the gate red until somebody rules on it.

| Tier | Labelled | Reported | Hits | Precision | Recall | Ruled wrong | Unreviewed |
|---|---|---|---|---|---|---|---|
| `synthetic` | 23 | 18 | 18 | 1.0000 | 0.7826 | 0 | 0 |
| `hand` | 0 | 3 | 0 | 0.0000 | n/a | 0 | 3 |

## How much to trust the labels

The synthetic tier's labels are what the generator *did*, so they are ground truth by construction. The hand tier's were seeded from this engine and then corrected by a human, which is the sharpest form of the self-marking risk ADR-0021 names. Three things are printed rather than argued about: how many rows a labeller changed (`override rate` -- a suspiciously low one is the visible symptom of somebody agreeing with everything), how many rows are still `proposed` and therefore not yet ground truth at all, and whether the pair has been signed off.

Moves are never engine-seeded, in either tier.

| Tier | Signed off | Rows still proposed | Mean override rate | Splits skipped | Merges skipped |
|---|---|---|---|---|---|
| `synthetic` | 0/40 | 0 | 0.0000 | 6 | 12 |
| `hand` | 0/10 | 644 | 0.0000 | 0 | 0 |

## The semantic pass: coverage, not precision

ADR-0021 asks for semantic role and span precision on a hand-labelled sample, reported and not gated. **No such number is published here, and the reason is not that it was hard.** The only hand-labelled role sample this repository owns is the sample pair, whose roles are *asserted* in `tests/test_sample_pair.py`; a precision figure computed against assertions that already pass would be 1.0000 by construction and would be evidence of nothing at all. Building a second labelling exercise to produce a number nothing depends on is work [ADR-0034](../docs/adr/0034-benchmark-labels-and-metric.md) explicitly declines.

What is published instead is coverage, which is a real measurement over the whole committed corpus: how many labelled blocks the [ADR-0031](../docs/adr/0031-role-rules-on-the-block-itself.md) pass put a role on, and which `role_match` kind put it there. It says how much of a real corpus the pass reaches. It does not say the roles are right.

| Tier | Labelled blocks | Roled | Coverage | By `role_match` |
|---|---|---|---|---|
| `hand` | 1385 | 1221 | 0.8816 | label 1221 |
| `synthetic` | 3278 | 2535 | 0.7733 | ancestor_heading 842, heading 156, label 1324, parent_role 213 |

Roles seen in `hand`: `clause` 1061, `sub_clause` 160.

Roles seen in `synthetic`: `clause` 1084, `definition` 213, `definitions` 26, `recital` 104, `schedule` 788, `signature` 80, `sub_clause` 240.

## Appendix: every pair

The 1.0 engine under `difflib`, one row per pair, so a headline number can be traced to the pairs that made it. `results/latest.json` carries the same rows for the floor and for every backend.

| Tier | Pair | Labelled | Precision | Recall | F1 | Spurious | Moves | Renumbers |
|---|---|---|---|---|---|---|---|---|
| `synthetic` | `adr-moves-mixed` | 21 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 0/0 |
| `synthetic` | `adr-moves-move-heavy` | 21 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 4/4 | 0/0 |
| `synthetic` | `alpha-roman-heavy` | 14 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 1/1 |
| `synthetic` | `alpha-roman-light` | 16 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `alpha-roman-mixed` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 8/8 |
| `synthetic` | `alpha-roman-renumber-storm` | 15 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 3/3 |
| `synthetic` | `alpha-roman-structure` | 12 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 3/3 |
| `synthetic` | `cross-references-heavy` | 3 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `cross-references-light` | 5 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `cross-references-mixed` | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 3/3 |
| `synthetic` | `cross-references-renumber-storm` | 4 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 3/3 |
| `synthetic` | `mixed-labels-light` | 8 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `mixed-labels-mixed` | 5 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `msa-markdown-heavy` | 100 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 10/10 |
| `synthetic` | `msa-markdown-light` | 102 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `msa-markdown-mixed` | 98 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 17/17 |
| `synthetic` | `msa-markdown-move-heavy` | 102 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 4/4 | 15/15 |
| `synthetic` | `msa-markdown-renumber-storm` | 101 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 10/10 |
| `synthetic` | `msa-markdown-structure` | 96 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 14/14 |
| `synthetic` | `msa-markdown-table` | 98 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `msa-text-heavy` | 84 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 10/10 |
| `synthetic` | `msa-text-light` | 86 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `msa-text-mixed` | 82 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 20/20 |
| `synthetic` | `msa-text-move-heavy` | 86 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 4/4 | 10/10 |
| `synthetic` | `msa-text-renumber-storm` | 85 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 5/5 |
| `synthetic` | `msa-text-structure` | 80 | 1.0000 | 0.9875 | 0.9937 | 0.0000 | 0/0 | 7/8 |
| `synthetic` | `repetitive-schedule-heavy` | 30 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `repetitive-schedule-light` | 30 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `repetitive-schedule-mixed` | 30 | 0.5000 | 0.5000 | 0.5000 | 0.0000 | 0/1 | 0/0 |
| `synthetic` | `repetitive-schedule-move-heavy` | 30 | 0.2000 | 0.2000 | 0.2000 | 0.0000 | 0/4 | 0/0 |
| `synthetic` | `schedule-restart-heavy` | 11 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `schedule-restart-light` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `schedule-restart-mixed` | 12 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 3/3 |
| `synthetic` | `twin-markdown-heavy` | 11 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `twin-markdown-light` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `twin-markdown-mixed` | 10 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `twin-markdown-move-heavy` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `twin-text-light` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `synthetic` | `twin-text-mixed` | 10 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1/1 | 3/3 |
| `synthetic` | `twin-text-move-heavy` | 13 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `csa-1.0-to-1.1` | 113 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `csa-1.1-to-2.0` | 97 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 91/91 |
| `hand` | `design-partner-agreement-1.0-to-1.1` | 48 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `dpa-1.0-to-1.1` | 76 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `govinfo-hr4668-ih-to-rh` | 29 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `govinfo-hr7385-ih-to-eh` | 11 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `partnership-agreement-1.0-to-1.1` | 85 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `pilot-agreement-1.0-to-1.1` | 68 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `psa-1.0-to-1.1` | 103 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 0/0 |
| `hand` | `sla-1.0-to-2.0` | 14 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 0/0 | 10/10 |
