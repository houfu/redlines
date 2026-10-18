# ADR-0003: Ship 1.0 with a compatibility facade, not a clean break

**Status:** Accepted
**Date:** 2026-08-26
**Amended:** 2026-10-18 -- the facade replays 0.6's own opcodes, and deprecation follows a schedule ([ADR-0036](0036-redlines-facade.md)). See *Amendment* below.
**Deciders:** houfu

## Context

The 0.6 public API is small and very widely used: `Redlines(source, test).output_markdown`, `compare()`, `output_json()`, `changes`, `get_changes()`, `stats()`, `opcodes`, the processor classes, `Document` and `PlainTextFile`. The single most-copied line in the ecosystem is the course example, which asserts an exact output string.

The structural engine (ADR-0001) needs a different shape: readers, profiles, a comparison object, a change tree. Bolting that onto the existing class would distort both.

## Decision

redlines 1.0 introduces a new top-level API for the structural engine, and keeps the entire 0.6 surface working unchanged, reimplemented over the new core as a facade that builds a one-block-per-paragraph tree. Deprecation warnings where something is superseded; no removals in 1.0.

## Amendment, 2026-10-18: the facade replays 0.6's own opcodes

The mechanism in the Decision, "a facade that builds a one-block-per-paragraph tree", is superseded by [ADR-0036](0036-redlines-facade.md), because it cannot meet this ADR's own criterion. 0.6 diffs the whole document as one token stream. On the 54 realistic pairs in the repository, 130 of its 735 non-equal opcodes straddle a paragraph boundary, in 39 of the pairs, and a paragraph pair cannot hold such an opcode. Built as written, the facade fails 32 of the 237 runnable tests in the v0.6.2 test tree. With every 0.6 quirk faked in, it is byte-identical on only 16 of the 54 realistic pairs, and `test_repetitive_schedule_reproduces_autojunk_pathology` cannot pass at all.

The facade keeps 0.6's own code for every 0.6 output, over the processor's own opcodes, and derives a one-block change tree from the same opcodes through the core's `build_change_tree`, on demand. That passes 237 of 237 and is byte-identical on all 576 measured comparisons. The design constraint in Consequences holds in its degenerate form: the core expresses a whole document as one block, and builds its change tree from 0.6's opcodes.

The revisit clause's per-case note list is **empty**. No style needs a note, and the criterion is not relaxed. "Byte-identical" means identical to 0.6.2, whose bytes the M0 goldens are; the mitigation in Consequences was carried out in M0, and those goldens are now pinned by SHA-256.

The deprecation sentence is narrowed, not reversed. Nothing is removed in 1.0, and nothing warns in 1.0 either: 1.0 ships the mechanism, a test tripwire and a schedule. Pending-deprecation warnings on `changes`, `redlines` and `get_changes` start in 1.1, deprecation warnings in 1.2, and removal waits for 2.0 at the earliest, as the revisit clause already says.

## Alternatives considered

**Strictly additive** — no new top-level API, everything hangs off the existing `Redlines` class and processor pattern. Rejected: the class is built around a source-and-test pair and a flat opcode list; expressing readers, profiles, block trees and verify through it would produce a worse API for the new work and a confusing one for the old.

**Clean break** — 1.0 is a new API, 0.6.x stays on PyPI as the legacy line. Rejected: notebooks and course material do not get updated. A clean break turns 3.7M downloads of goodwill into a support burden and a fork of the documentation.

## Consequences

Positive: existing users upgrade without noticing. The 0.6 test suite becomes the compatibility contract, and passing it unmodified is a hard release criterion. It also forces the new core to be general enough to express the degenerate flat case, which is a useful design constraint.

Negative: the facade is real work (roughly a week) and real risk — re-implementing `output_markdown` over a tree can change whitespace or paragraph handling in edge cases the current tests do not cover. Mitigation: generate golden files from 0.6 across the README, course and issue examples *before* writing the facade. The package also carries two conceptual models for at least one major version, which costs documentation clarity.

## Revisit when

At 2.0, when deprecated surfaces may be removed. If the golden-file work reveals that byte-identical output is impossible for some style, that specific case should get its own note rather than a blanket relaxation of the criterion.

## Related

ADR-0001, ADR-0010.
