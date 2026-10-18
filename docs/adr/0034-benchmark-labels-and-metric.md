# ADR-0034: The alignment label format and metric definitions

**Status:** Accepted
**Date:** 2026-09-05
**Deciders:** houfu

## Context

[ADR-0021](0021-alignment-benchmark.md) decided to build an alignment benchmark, and to build it *before* tuning alignment rather than after. It named two corpora — synthetic mutations of real documents, and ten hand-labelled real pairs — and four metrics: block correspondence precision and recall, move detection recall, renumbering recall, with flat redlines 0.6 as the floor. It also named the risk in its own consequences: "a benchmark we design could flatter us", mitigated by publishing the generator and the labels, reporting the baseline honestly, and keeping the two corpora separate.

None of that is enough to build from, and the gaps are the parts that decide whether the numbers mean anything.

**There is nothing to plug into.** No `benchmark/`, no `bench/`, no top-level `scripts/`. `tests/corpus/` holds ten case directories and the sample pair. `neurotic_docx_bench` appears only in prose. Every decision here is a first one.

**A metric definition cannot be revised after publication.** [ADR-0009](0009-moves-before-splits.md) makes move detection a release gate — recall ≥ 0.9 on synthetic mutations, and no move false positive on the hand-labelled set that a reviewer would call wrong — and a gate whose denominator can be renegotiated is not a gate. Two specific questions decide whether a number is comparable at all: whether correctly-unmatched blocks count toward correspondence recall, and whether a moved subtree of thirty blocks is one move or thirty.

**Labels rot silently.** An address is a position, not an identity ([ADR-0029](0029-address-syntax.md)), so a reader change shifts every following `section[n]` and a label file that stores only addresses starts scoring the wrong blocks with no error anywhere.

**Seeding labels from the engine is the sharpest form of the self-marking risk**, and hand-labelling ten pairs without any seeding is a week nobody has. The compromise has to be recorded, not improvised.

**And the second half of ADR-0009's gate is a judgement, not a measurement.** "A move a reviewer would call wrong" is a ruling about engine output. Nothing in a label file expresses it, and with one maintainer there is no second reviewer to appeal to.

## Decision

### Where the benchmark lives

A **top-level `benchmark/` directory, not packaged in the wheel**, invoked as `uv run python -m benchmark.run --tier all`. That keeps the wheel and the blocking Pyodide job untouched, lets the generator use dev-only libraries freely, and makes ADR-0021's "publish the generator alongside the labels" a visible root directory rather than something buried in the test suite. Promoting it to `redlines.bench` later is a move, not a redesign.

Two tiers, and the distinction is **committed versus not**, not synthetic versus hand:

- **Committed**: `benchmark/corpus/synthetic/**` (target 30–40 pairs from 8–12 documents) and `benchmark/corpus/hand/**` (ten pairs). Documents *and* labels in the repository. This is what the gate runs on, what CI runs, and what a stranger can reproduce.
- **Uncommitted**: `benchmark/corpus/external/**`, gitignored — the neurotic-derived text and any wide sweep, run by the maintainer for one column of the report and labelled *not reproducible from this repository*.

The synthetic tier is not regenerated in CI; it is committed, and a test **re-runs the generator and asserts byte-identity** with what is committed, which is the repository's existing golden discipline applied to a corpus. That catches an accidental generator change that would otherwise silently move every published number.

**The gates are `pytest.mark.xfail(strict=True)` tests in the blocking CI job**, written now with issue-citing reasons, which is house style already. `tests/test_benchmark_gates.py` asserts synthetic correspondence F1 ≥ 0.95, hand-labelled ≥ 0.85, move recall ≥ 0.9, zero `wrong` move verdicts and zero unreviewed engine moves. `strict=True` means that on the day a gate is met the test **fails because it passed**, so the mark cannot be left on by accident — the forcing function ADR-0009 asks for. Two faster modules sit beside it: label schema, digest and totality checks, and generator determinism. The external sweep is never in CI.

### The label file

One YAML file per pair, `benchmark/corpus/<tier>/<pair>/labels.yaml`, validated against a published `benchmark/labels/schema.json`. YAML because PyYAML is already a runtime dependency, because it mirrors the [ADR-0028](0028-profile-file-format.md) precedent, because it is legible enough to satisfy "publish the labels", and because one correspondence per line diffs cleanly in a pull request — which matters, since **the pull request is the reviewer's sign-off surface**.

The same format serves the machine-written synthetic labels and the hand-corrected ones, and is what the scorer reads. Four properties carry the weight:

1. **`kind` is one of `same | move | renumber`.** A block can be moved *and* relabelled; then it is `kind: move` with differing labels, and the scorer derives the renumber from the labels — two metrics from one row.
2. **Every row is anchored by address *and* digest.** `source_digest` is a sha256 of the block's normalised text (whitespace collapsed, label re-prefixed) truncated to 16 hex characters. Digests are verified **on load**, and a mismatch **fails loudly** — "labels stale for /section[3]/list_item[4]; run `benchmark/reanchor.py`" — rather than scoring garbage. `reanchor.py` re-maps addresses by digest and rewrites the file, so the repair shows up in a diff.
3. **Totality is checked, not assumed.** Every text-bearing block on each side must appear exactly once across `correspondences`, `inserted`, `deleted`, `splits`, `merges` and `unscored`. Without this, recall is meaningless: a half-labelled file scores 1.0.
4. **Containers are not labelled.** Only blocks that own text, plus `row` blocks for tables. `document`, `section` and `table` are excluded. The rule is stated in the schema because the denominator depends on it.

Each row carries `status: proposed | confirmed | corrected`. A `provenance` block records the origin, licence, attribution, the preparation script and every normalisation applied, plus the generator, version, seed and plan for synthetic pairs. A `review` block records who labelled, who reviewed, on what dates, the decision, and `override_rate`. A `move_verdicts` block records rulings on engine moves. Review and verdicts live in the **same file** as the labels, not in a sidecar: they are part of the evidence for a number, and splitting them makes it possible for one to be updated without the other.

### The metric

Let `C*` be the labelled correspondence set as `(source_address, test_address)` pairs and `C` the engine's reported pairs restricted to labelled block kinds.

- **precision** = |C ∩ C*| / |C|, **recall** = |C ∩ C*| / |C*|, **F1** the harmonic mean. **Links only**: `inserted` and `deleted` blocks are not in the denominator. Including them as "correctly unmatched" would let a long document with few changes inflate F1 by correctly saying nothing about most of it, and would make the score depend on document length.
- **spurious-match rate** = the fraction of reported pairs with one side labelled inserted or deleted. This is the honest counterweight to links-only scoring — it is the number that catches a positional fill-in pass inventing matches, which links-only precision alone would not punish.
- **move recall** = |M ∩ M*| / |M*| over ordered `(source, test)` pairs, with **move precision** reported alongside; the gate itself is the reviewer verdict, but the number belongs in the report.
- **A moved subtree counts once**, credited at the highest block whose entire subtree moved; its descendants are ordinary correspondences. Without this rule a section move is either 1 or 30 depending on who is counting. This is **the same rule the change tree uses to emit move nodes** ([ADR-0033](0033-change-tree-wire-format.md)), so engine and scorer agree by construction.
- **renumber recall** keys on the four-tuple `(source_address, test_address, source_label, test_label)`: a renumber reported with the wrong new label is not a hit.
- **Splits and merges are labelled and excluded from every 1.0 denominator**, and the report prints how many were present and skipped, so the 1.1 delta is measurable rather than a guess.
- **The root pair is excluded** from the correspondence set: scoring the engine for knowing a document is itself would flatter every number.
- A **per-pass table** reports, for each pass, its match count, its wrong-match count and how many pairs no earlier pass would have found. That is the evidence ADR-0008's review gate asks for, and the direct answer to "which pass should we cut?".
- The suite runs **twice, once per similarity backend**, selected rather than simulated by hiding an import, and the report gives Δ on every headline metric.

Scoring uses exact counts and formats at the edge; pairs are iterated in sorted path order; `benchmark/results/latest.json` is committed and must be byte-stable for identical inputs, so a number changing is a reviewable diff.

### The 0.6 baseline

The floor is computed by calling the flat engine directly — `WholeDocumentProcessor(autojunk=False)` — and **never `Redlines`**. [ADR-0003](0003-compatibility-facade.md) has M3 reimplement that class over the new core, so a baseline that called it would silently stop being the 0.6 baseline the day the facade lands, and the report would compare the new engine with itself. **A test asserts that `benchmark/baselines.py` does not import `redlines.Redlines`**, so the substitution cannot happen quietly.

Flat token pairs are lifted into unit pairs, then units into the label address space: each flat unit maps to the block whose normalised text contains it, a block's correspondence is the **plurality** of its units' targets, and ties break to the earliest test block in document order. Both the pairing rule and the tie-break are stated in the report, because they are the only places the baseline can be flattered or hobbled.

Two columns are reported: **all labelled blocks**, the honest end-to-end number, and **blocks the flat engine can address**, excluding table rows and cells it has no concept of — the like-for-like one. Move recall and renumber recall are `0.0` by construction, and the report prints `0.0` rather than a blank: that cell is the thesis. One more thing is stated plainly rather than hidden: the flat engine's unit is a **line**, so it necessarily gets the sample pair's whitespace-only change wrong. That is what the floor is, and showing it is the point.

### The hand-labelled sources

Ten pairs, from two public sources, **prepared and committed**:

- **Common Paper**'s standard agreements — CSA, Design Partner Agreement, SLA, DPA, PSA, Partnership and Pilot agreements — in markdown, git-tagged, explicitly **CC BY 4.0**. About twelve candidate version pairs, more than the ten needed. Committed with a per-pair `NOTICE.md` and a licence line in the corpus README.
- **Two or three US bill version pairs** from govinfo — plain text, public domain under 17 U.S.C. § 105 — for shape diversity: introduced → reported → engrossed are real amendment pairs and they exercise the text reader and the `contract` profile rather than the markdown one.

**A preparation step is mandatory, not optional.** The older Common Paper files carry literal labels in the text; the newer ones use markdown ordered lists with the label only in an HTML attribute, so the label pass would see `1.` for every clause. `benchmark/prepare.py` strips inline HTML and promotes those attributes into literal label prefixes, deterministically, records every transformation in `provenance.normalisations`, and the **prepared** text is what is committed — never re-derived at score time, because a normalisation change would then invalidate every digest.

Excluded, with reasons: **Wikipedia revisions** (CC BY-SA share-alike, in an MIT repository), **anything from a customer** (nobody else could check the work — exactly ADR-0021's self-marking risk), and **the repository's own documents** as hand-labelled pairs (labelling one's own edits is the softest possible test; they earn their place in the synthetic tier's source list instead, where the mutations are what is being scored).

### Labelling, and the move gate

`benchmark/label.py` has three verbs. `init` runs `compare()` and writes a draft `labels.yaml` with every row `status: proposed`, carrying the pass that proposed it, plus a human-facing worksheet: source blocks in document order with address, label, first 80 characters, the proposed counterpart, and a `?` on anything matched positionally, below the fuzzy threshold, or involved in a proposed move. `check` verifies schema, digests, totality and that no row is still `proposed`. `sign --as <name> --role labeller|reviewer` stamps the review block with a digest of the label content, so a later edit invalidates the signature.

Seeding from the engine biases the labels toward the engine. Three mitigations, all cheap and all visible:

- every row records `proposed`, `confirmed` or `corrected`;
- **`override_rate` (corrected ÷ total) is computed per pair and printed in the report** — a suspiciously low override rate is the visible symptom of a labeller who agreed with everything;
- **moves are labelled independently and are never engine-seeded.** There are only a handful per pair, and reading the two clause lists side by side takes minutes. The move gate is the one number that must not come from the thing it is measuring.

**The move gate is enforced by per-move verdicts, fail-closed.** Every move the engine reports that is not in `correspondences` needs a `move_verdicts` entry: `verdict: wrong | acceptable`, a reason, the reviewer, the date, and the engine commit. The gate test fails on `wrong` **and on an unrecorded move** — unknown is not a pass. Verdicts are keyed by engine commit, so when alignment changes and produces a new false positive, that one has no verdict and the gate goes red until someone rules on it; old verdicts stay as a record.

With one maintainer, **labelling and reviewing are separate passes on separate days, recorded as such**, and the pull request adding or changing a verdict is the sign-off artefact: the reason is written in the file and read in the diff. `reviewed_by` carries a second reviewer if one ever exists.

### `neurotic_docx_bench`, and what cannot be claimed

Two things ADR-0021 mentions in one breath are separated here.

Its 763 base documents are a useful **text source for mutation**, and that is achievable: `benchmark/fetch_neurotic.py` clones the AGPL repository into gitignored `external/`, extracts paragraph text, and writes plain text. It is **dev-only, never gated on, and nothing it produces is ever bundled** — python-docx is not added to the project in any form, the script names its own `uv run --with` invocation in its docstring, and it refuses to write anywhere but `external/`. Extraction is known to fail on 18 of the 763; skips are logged, not crashed on. Published *numbers* are not derivative works.

Re-running redlines through that bench's adapter for a like-for-like comparison against the published 45.9 figure is **not achievable in 1.0, and the report must say so in as many words**. That benchmark demands a tracked-changes DOCX, and [ADR-0014](0014-no-ooxml-writing.md) rules out writing OOXML; the 45.9 came from a third-party adapter, not from us. Leaving it implied sets up a promise 1.0 cannot keep.

### The section 3a golden

**Two goldens**, `change_tree.contract.json` and `change_tree.markdown.json`, matching the existing per-profile convention and dumped exactly as the block-tree goldens are. Two, not one, because the twins genuinely diverge at the table and that divergence is a stated property of the pair.

`tests/test_sample_pair_change_tree.py` composes the comparison itself rather than calling the regeneration script, so a drift in how `compare()` wires its stages is a failure rather than a silently regenerated golden. Alongside the whole-tree tests sit **eight named tests, one per row of the pair's own CHANGES.md**, so a failure names the promise instead of printing a 100 KB diff.

**Those eight assert kind, both addresses, both labels, `span_types` and inline ops — and *not* `matched_by`**, except in the two places where the pass *is* the point: the move itself, and the renumber run, which must be `exact` to prove that pass order works. Which pass a given `modify` lands on is emergent, and a named test asserting a guessed pass name would be a false failure on day one. The whole-tree golden records whatever the engine actually says.

Three phases, and the mechanism enforces the flip. The eight named tests are written **first**, before the change tree exists, as `xfail(strict=True)` — they are the specification. The goldens are generated when the schema is frozen, read against CHANGES.md by eye, committed, and their whole-tree tests added, also strict-xfail. When the last piece lands, `strict=True` makes them fail *because they passed*, and removing the marks is the milestone exit. **The golden JSON is never hand-written**: the eight assertions are the hand-written specification.

## Alternatives considered

**A `redlines.bench` subpackage with a `redlines bench` CLI command.** The strongest version of ADR-0021's contribution claim — anyone could run the metric over their own documents. Rejected for 1.0: it grows the packaged surface and the CLI that ADR-0025 wants thin, it would have to stay stdlib-only and Pyodide-importable, and it becomes API that cannot change after 1.0.

**Dev-only scripts under `tests/`.** Zero new plumbing, and it matches the existing regeneration script. Rejected: it buries a published artefact inside the test suite and makes its provenance awkward to explain.

**JSON labels, addresses only.** Byte-stable for free and stdlib-only. Rejected: hand-editing 120 rows of JSON across ten pairs is miserable, comments are impossible so a reviewer's reasons have nowhere to live, and without digests a reader change rots every label silently.

**TSV labels with a YAML sidecar.** The most diffable and the fastest to hand-edit. Rejected: two files per pair, no schema validation, and nowhere for the review block or unscored regions.

**Labels committed but documents regenerated on demand.** Smallest repository. Rejected: labels and documents can drift with nothing to catch it, and a reviewer reading a pull request cannot see what actually changed in the corpus.

**Nothing committed; the benchmark as a maintainer-run script.** Rejected: the release gate stops being mechanically checkable and ADR-0021's anti-self-marking mitigation collapses into a promise.

**Including inserted and deleted blocks in the correspondence denominator** as correctly-unmatched. One number covering everything, and it rewards restraint. Rejected: it inflates with document length and makes the 0.6-versus-1.0 gap look smaller than it is. The spurious-match rate is what covers restraint instead.

**Crediting a moved subtree at every block in it.** Trivially computed. Rejected: move recall would then depend on subtree size and the numbers would not be comparable between corpora — or between the metric and the change tree.

**Running a pinned `redlines==0.6.2` in a separate environment as the baseline.** Unarguably the 0.6 engine. Rejected: a second environment in CI and in every checkout, and the unit-to-block lifting problem is identical anyway.

**Using the M3 `Redlines` facade as the baseline.** Zero new code, and it is literally one block per paragraph. Rejected: it is the new engine in flat clothing, so the floor would move whenever the facade improved.

**A fetch script with nothing committed for the hand set.** No foreign licence in the repository. Rejected: the gate stops being reproducible offline, upstream can retag, and digests would fail against re-derived text whenever a normalisation changed.

**Maintainer-supplied private pairs.** By far the most realistic material. Rejected: nobody can check the work.

**Gating on the external tier.** The widest evidence. Rejected: the gate would require an AGPL fetch and a network to reproduce.

**Pull-request review alone for the move gate**, and **a numeric move-precision threshold instead of verdicts.** The first makes the gate a habit rather than a check; the second quietly permits some wrong moves, which is exactly the bar ADR-0009 says not to lower silently.

**One golden for the markdown pair only**, and **hand-writing the golden JSON up front.** The first leaves the text reader's change tree with no frozen shape, contradicting the twins' agreement as a stated corpus property; the second is hours of error-prone work the eight named assertions already achieve.

## Consequences

Positive: every published number has a definition written down before it was measured, a corpus a stranger can check out and re-run, and a generator published beside the labels. Digest anchoring and the totality check turn the two silent failure modes — rotted addresses and half-labelled files — into loud ones. The subtree-move rule is shared with the change tree, so the engine cannot be scored against a definition of "move" it does not itself use. The move gate is fail-closed, which is the only reading of ADR-0009's asymmetric bar that survives contact with a single maintainer. And `override_rate` puts the self-marking risk on the face of the report rather than in an ADR's consequences section.

Negative: the labelling is a day and a half of human work that nothing can remove, and it recurs whenever the corpus grows. Seeding labels from the engine is a real bias, mitigated and measured but not eliminated; the override rate is a symptom, not a proof. One maintainer labelling and reviewing on separate days is a convention, not a control. Committing CC BY 4.0 documents into an MIT repository means per-pair NOTICE files that must be maintained by hand. The prepared Common Paper text is not the upstream text, so a reader of the corpus has to trust `provenance.normalisations` to know what changed. Links-only scoring means a system that matches nothing is not punished by precision or recall at all, which is why the spurious-match rate has to be read alongside them rather than instead of them. And the external tier's numbers cannot be reproduced by anyone but the maintainer, which is stated in the report and is a genuine hole in the evidence.

## Revisit when

Expand the hand-labelled set continuously, as ADR-0021 says; ten is a floor, not a target. If someone publishes a credible alignment benchmark, adopt theirs and stop maintaining this one. If splits and merges ship in 1.1, the labelled-but-skipped rows already in the files become the 1.1 denominator, and the printed skip count is what says whether that is enough data to score against. If the override rate stays implausibly low across pairs, the seeded-labelling compromise has failed and the next hand-labelled pairs should be labelled cold, at whatever cost. If the move gate is still red after the thresholds in ADR-0032 have been set from real evidence, ADR-0009's own escape applies — ship moves behind a flag, off by default, with the numbers published — and not a quietly lowered bar. If OOXML writing is ever reconsidered, the like-for-like re-run this ADR rules out becomes possible and the report's statement about it needs rewriting rather than deleting. And if the benchmark becomes something others want to run, that is the signal to revisit the `redlines.bench` packaging question, which was rejected on 1.0 scope rather than on merit.

## Related

ADR-0009, ADR-0014, ADR-0021, ADR-0028, ADR-0030. Issues [#141](https://github.com/houfu/redlines/issues/141), [#142](https://github.com/houfu/redlines/issues/142), [#143](https://github.com/houfu/redlines/issues/143), [#144](https://github.com/houfu/redlines/issues/144).
