# ADR-0008: Align blocks in explainable passes

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Block alignment is the heart of the structural engine and the thing that makes or breaks ADR-0001. Given two block trees, decide which block in the source corresponds to which block in the test, before diffing any text.

Prior art: Open-XML-PowerTools' WmlComparer hashes block content and runs LCS. Docxodus adds move detection by post-hoc word-level Jaccard similarity (threshold 0.8, minimum three words) and, in its newer `docxdiff` engine, paragraph split/merge detection. adeu aligns paragraphs and falls back to whole-block replacement below a 0.35 similarity ratio. The academic line is tree edit distance — Zhang-Shasha, Chawathe, GumTree.

Documents also carry a signal none of those exploit systematically: the labels themselves. Clause `7.2` in one version is overwhelmingly likely to correspond to clause `7.2` in the other, even when its text changed substantially.

## Decision

Alignment runs in ordered passes: exact content match; then label match; then fuzzy similarity above a configurable threshold; then positional fill-in for what remains. Similarity uses difflib's ratio in core and rapidfuzz when installed (ADR-0004). Every matched pair records **which pass matched it**, and that record is exposed in the output.

Unmatched blocks become inserts and deletes. A deleted block that fuzzy-matches an inserted block elsewhere is a move (ADR-0009). Matched content with differing labels is a renumbering.

This is deliberately more machinery than a single global LCS. The agreed disposition is to build it as designed and pare it back if performance or odd results demand — with the pass record as the evidence for what to cut.

## Alternatives considered

**Single global LCS over block hashes.** Simpler and proven in WmlComparer, but it cannot use labels, handles moves only as delete-plus-insert, and gives no explanation of why two blocks were considered the same.

**Embedding similarity.** Rejected: it would introduce a model dependency (ADR-0007), make results non-deterministic across versions, and be unexplainable.

**Tree edit distance.** Rejected for 1.0: the general algorithms are expensive and their edit scripts do not map cleanly onto the change vocabulary users want (move, renumber, split). Worth revisiting if the pass approach plateaus.

## Consequences

Positive: deterministic, explainable and tunable. "Matched by label 7.2" is an answer a user can argue with. Passes can be individually disabled or reordered per profile.

Negative: more parameters to get wrong; thresholds that suit contracts may misfire on prose or on tables of near-identical rows. Worst case is quadratic in block count, so early exit on exact matches matters. Behaviour differs subtly with and without rapidfuzz.

## Revisit when

There is an explicit review gate after the benchmark (ADR-0021) exists: if a pass contributes few matches or many wrong ones, cut it. Revisit tree edit distance if split/merge detection (ADR-0009) proves unmanageable in the pass framework.

## Related

ADR-0004, ADR-0005, ADR-0009, ADR-0021.
