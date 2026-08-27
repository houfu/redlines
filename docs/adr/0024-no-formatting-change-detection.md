# ADR-0024: No inline formatting change detection in 1.0

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

"Text unchanged, but it became bold" is a change class that Word reports (`w:rPrChange`) and that python-redlines/Docxodus detects at run, paragraph and section level. An earlier plan for redlines made "rich tokens" carrying bold, italic and underline the foundational first phase of the whole rewrite, with formatting-change detection as a headline capability.

Two things argue against that ordering. Formatting changes are a DOCX-shaped concern, and redlines' own users — notebook and agent developers comparing text and markdown — have not asked for them; the change classes they care about are content, structure and meaning. And making inline formatting foundational imposes a cost on *every* reader and on the token model, in service of a capability only one deferred format can supply.

There is also a design trap: naive implementations create a token per formatting run rather than per word, so the diff algorithm matches badly and "text unchanged, formatting changed" gets reported as a delete plus an insert — the opposite of the intent.

## Decision

No formatting-change category in 1.0. `attrs` may carry run-level formatting from readers that have it, and the semantic layer has an `emphasis` span type (ADR-0005) for readers where emphasis is meaningful, such as markdown. But formatting does not participate in alignment or diffing and is not reported as a change kind.

The block model, not an inline token model, is the foundation.

## Alternatives considered

**Rich tokens with formatting as phase one.** The earlier plan. Rejected on priority: it front-loads cost for a deferred format's benefit and delays the block model, which is what everything else depends on.

## Consequences

Positive: readers stay cheap; no token-explosion trap; the foundational phase is the one that carries the thesis.

Negative: when the DOCX reader arrives (1.1), redlines will report content and structure changes but not "this clause became bold", which python-redlines does. For contract review that is a real gap, and it should be stated plainly rather than discovered.

## Revisit when

After the DOCX reader ships, if users ask for it. The clean way to add it later is as a separate change category computed from `attrs` on aligned pairs — which the current design permits, since aligned pairs already carry both blocks' attributes.

## Related

ADR-0005, ADR-0013, ADR-0014.
