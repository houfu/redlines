# ADR-0009: Detect moves and renumbering in 1.0; splits and merges later

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Beyond insert, delete and modify, four structural change kinds matter in real documents: a block **moved** elsewhere; blocks **renumbered** because something was inserted above them; one block **split** into two; two blocks **merged** into one.

These are what a flat diff cannot express. A moved clause appears as a large deletion and an unrelated large insertion. A renumbering makes every label look edited. Both are the changes users most often complain about in Word's own Compare output.

They differ sharply in cost. Moves and renumbering fall almost directly out of the alignment passes in ADR-0008: a move is an unmatched delete that fuzzy-matches an unmatched insert; a renumbering is matched content with a different label. Splits and merges need concatenation matching — testing whether one block's content corresponds to two consecutive blocks' content combined — which is a different and more expensive search.

## Decision

Moves and renumbering ship in 1.0. Splits and merges are 1.1.

Move detection is a **release gate**, not a feature: 1.0 does not ship with move recall below 0.9 on the synthetic-mutation corpus, or with any move false positive on the hand-labelled set that a reviewer would call wrong.

## Alternatives considered

**All four in 1.0.** Rejected: split/merge is the larger piece of alignment work and would delay everything behind it, including both end deliverables.

**None in 1.0** — ship structural comparison with insert/delete/modify only. Rejected: moves are the single most visible thing that distinguishes a structural redliner from a flat one. Shipping without them would make 1.0 hard to tell apart from a good flat diff in a demo.

## Consequences

Positive: a demo can show a moved clause reported as a move, which is the clearest possible illustration of the thesis in one screen. The gate also forces the benchmark to exist and to be honest before release.

Negative: a false-positive move is worse than a missed one — telling a lawyer a clause moved when it did not damages trust more than silence. Hence the asymmetric gate (recall threshold plus zero tolerated bad false positives). Splits and merges absent in 1.0 means a paragraph broken in two still shows as a delete and two inserts, which will be noticed.

## Revisit when

If the false-positive constraint proves impossible to meet at useful recall, consider shipping moves behind a flag, off by default, with the benchmark numbers published — but not silently lowering the bar.

## Related

ADR-0008, ADR-0021.
