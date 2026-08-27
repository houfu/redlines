# ADR-0005: Minimal structural core with an open semantic layer

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

A structural engine needs a document model. The obvious failure mode is to build a superset that DOCX, markdown and Akoma Ntoso all map into; such models grow OOXML-shaped, because OOXML is the most detailed of the three, and then every reader has to fill in fields it does not have.

The opposite failure is a model so thin that the output is no better than a flat diff with paragraph numbers. "Paragraph 14 was modified" is not meaningfully more useful to an LLM than a token span.

The insight that resolves this, raised during review: what makes the output valuable to a model is not *structure* but *meaning*. "The definition of Confidential Information was modified" and "a cross-reference to clause 7.2 was inserted" are statements a model can act on. Structure is how you find them; semantics is what you report.

## Decision

The block model has two layers.

A **minimal structural core**, with a closed vocabulary: `kind` (document, section, heading, paragraph, list_item, table, row, cell, unknown), `text`, `label`, `level`, `path`, `children`. Format-specific detail lives in a free-form `attrs` and never in the core schema.

An **open semantic layer**, entirely optional: a `role` on blocks (title, recital, definition, clause, sub_clause, schedule, signature, note, quote, code, boilerplate) and `spans` inside them (emphasis, defined_term, cross_reference, party, date, amount, citation). The vocabulary is recommended, not enforced. Roles and spans are assigned by a pluggable pass driven by a structure profile (ADR-0006).

Alignment and diffing operate on text only. Roles may break ties between otherwise equal fuzzy candidates, and nothing more. Change nodes carry the role of the block they affect and the span types touched, so summaries can speak semantically.

## Alternatives considered

**Structural-only core.** Rejected on review: it would make redlines a better diff but not a different one, and semantics is the thing no competitor has.

**A format superset.** Rejected for the reasons above.

**Semantics driving alignment.** Rejected for 1.0: matching on roles as well as text makes alignment failures much harder to explain, and explainability is the point of ADR-0008. The tie-break is the one exception, and it is bounded.

## Consequences

Positive: readers stay cheap to write, because a reader that knows nothing semantic still produces a valid tree. The JSON schema stays stable while the semantic vocabulary evolves. And the output can say what changed in the document's own terms.

Negative: an open vocabulary means two profiles can use different role names for the same thing, so downstream consumers cannot rely on a fixed set. We accept that; a recommended list plus documentation is the mitigation, and enforcing a closed vocabulary would defeat the purpose.

## Revisit when

If consumers (our own renderers included) start needing guarantees about which roles exist, promote a small subset — probably `definition`, `clause`, `schedule` — to a documented guaranteed set while leaving the rest open.

## Related

ADR-0006, ADR-0007, ADR-0008, ADR-0011.
