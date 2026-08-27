# ADR-0021: Make alignment quality measurable with our own benchmark

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The structural thesis (ADR-0001) rests entirely on alignment quality. If blocks are matched wrongly, every downstream claim — moves, renumbering, semantic summaries, verify — is wrong with confidence, which is worse than a flat diff that is merely coarse.

One public benchmark exists, `neurotic_docx_bench` (AGPL-3.0, by Jandira Technologies, who also make the closed jubarte engine it tops). It takes 763 `base.docx`/`next.docx` pairs, asks each tool for a tracked-changes DOCX, renders candidate and Word's own output to PDF through LibreOffice, and scores pixel similarity. It has already measured redlines 0.6.1 via a third-party adapter at 45.9 mean with 18 failures — bottom of the table, which is exactly what a text-only differ should score on a pixel metric.

That benchmark cannot measure what we care about. A tool could find every correspondence perfectly and still score badly for dropping formatting; a tool could align nothing and score well by preserving the document. **No alignment metric exists in this field.**

## Decision

Build one, and build it *before* tuning alignment, not after.

Two corpora. A **synthetic-mutation** corpus: take real documents and apply known moves, splits, renumberings and edits programmatically, keeping the labels — ground truth for free, at any volume. And a small **hand-labelled** set of ten real before/after pairs, where the mutations are whatever really happened.

Metrics: block correspondence precision and recall, move detection recall, renumbering recall. Baselines: flat redlines 0.6 as the floor, and python-redlines as a comparator once DOCX reading exists.

Semantic role and span precision is reported on a hand-labelled sample but not gated in 1.0.

The move gate from ADR-0009 is enforced here. The benchmark report is published with the release and linked from the README.

## Alternatives considered

**Reuse the visual benchmark only.** Rejected: it measures a different thing, and optimising for it would push the project toward OOXML fidelity, against ADR-0001.

**Tune first, measure later.** Rejected as the standard way to end up with thresholds that fit whatever documents were on hand.

## Consequences

Positive: the structural claims become checkable rather than rhetorical. It gives the ADR-0008 review gate its evidence, and it is itself a contribution — an alignment metric and corpus that others could adopt is the kind of thing that gets cited.

Negative: real cost, mostly human. Hand-labelling ten pairs is tedious and the synthetic generator is a small project of its own. There is also a self-marking risk: a benchmark we design could flatter us. Mitigations are publishing the generator and the labels, reporting the 0.6 baseline honestly, and keeping the hand-labelled set separate from the synthetic one.

`neurotic_docx_bench`'s 763 pairs are a useful text source for the corpus (AGPL, so usable for evaluation, not for bundling), and running our text through its adapter path would give a like-for-like comparison with the published 0.6.1 numbers.

## Revisit when

Expand the hand-labelled set continuously. If someone else publishes a credible alignment benchmark, adopt theirs and stop maintaining ours.

## Related

ADR-0001, ADR-0008, ADR-0009, ADR-0019.
