# ADR-0003: Ship 1.0 with a compatibility facade, not a clean break

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The 0.6 public API is small and very widely used: `Redlines(source, test).output_markdown`, `compare()`, `output_json()`, `changes`, `get_changes()`, `stats()`, `opcodes`, the processor classes, `Document` and `PlainTextFile`. The single most-copied line in the ecosystem is the course example, which asserts an exact output string.

The structural engine (ADR-0001) needs a different shape: readers, profiles, a comparison object, a change tree. Bolting that onto the existing class would distort both.

## Decision

redlines 1.0 introduces a new top-level API for the structural engine, and keeps the entire 0.6 surface working unchanged, reimplemented over the new core as a facade that builds a one-block-per-paragraph tree. Deprecation warnings where something is superseded; no removals in 1.0.

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
