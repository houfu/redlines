# ADR-0023: Keep Python 3.10+ and strict typing

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

redlines 0.6 supports Python 3.10 through 3.14, having dropped 3.8 and 3.9, and runs strict mypy with a `py.typed` marker. adeu, a comparable project, requires 3.12+.

A rewrite is the natural moment to raise the floor and use newer syntax.

## Decision

Keep the 3.10 floor. Keep strict mypy and `py.typed`. Use frozen dataclasses for the block and change models.

## Rationale

Nothing in the design needs 3.11 or 3.12 syntax. Notebook environments, managed platforms and corporate installations lag, and the primary persona (ADR-0002) works in exactly those places. Raising the floor would cost users to buy nothing.

Strict typing matters more than usual here because the block and change models are the public interface (ADR-0011); a typed model is self-documenting for both humans and the agents that will consume it.

Frozen dataclasses give cheap structural sharing and make it hard to mutate a tree accidentally during alignment.

## Alternatives considered

**Raise to 3.12.** Rejected: no need, real cost.

**Runtime validation with pydantic.** Considered: it would give schema generation for free (ADR-0011). Rejected for core under ADR-0004 — a dependency for something the stdlib plus a hand-maintained JSON Schema can do. Reasonable to revisit if schema maintenance becomes a chore.

## Consequences

Positive: the widest install base, self-documenting models, no accidental mutation.

Negative: `nupunkt` requires 3.11+, so that extra is unavailable to a slice of supported users — already true today. The JSON Schema must be maintained by hand and kept in step with the dataclasses, which needs a test that generates one from the other and compares.

## Revisit when

When 3.10 reaches end of life, or if hand-maintaining the schema proves error-prone.

## Related

ADR-0002, ADR-0004, ADR-0011.
