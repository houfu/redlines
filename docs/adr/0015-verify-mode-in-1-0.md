# ADR-0015: Ship verify mode in 1.0

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Agent pipelines that edit documents have a question no tool answers: *did the model change only what it was told to change?* Today the answer is a human reading a diff.

The pattern is visible in the field. Anthropic's docx skill ships a `validators/redlining.py` that strips one author's revisions from both documents and text-compares them to check that the tracked changes faithfully represent the intended edit — a diff used as a validator. Microsoft's Legal Agent in Word is described as using a "deterministic resolution layer" rather than trusting regenerated text. The need is recognised; nobody has generalised it.

A structural engine can answer much more than "is the text the same": it can say whether anything outside the permitted scope changed, whether blocks moved, whether numbering shifted, and whether the change density outside the target area is non-zero. With the semantic layer (ADR-0005), scope can be expressed in the document's own terms — "only the definitions section and clause 7".

## Decision

Verify ships in 1.0 as a headline feature, not as a follow-on. Inputs: the original document, the edited document, and an allowed scope expressed as block addresses, labels or roles. Output: pass or fail, the list of out-of-scope changes, and the structural side effects (moves, renumbering).

It is deterministic. The library does not accept a natural-language instruction and derive the scope from it; deriving scope from an instruction is the caller's job — and on the MCP surface, the model's.

Whitespace-only and label-only changes are configurable exemptions.

Text-anchor scoping ("only the paragraph containing this phrase") is deferred to 1.1, because it imports the ambiguity problem adeu is fighting.

## Alternatives considered

**Ship compare first, verify later.** Rejected: verify is a thin layer over the change tree, and it is the single clearest reason for the primary persona to adopt the library. Deferring it would make 1.0 a better diff rather than a new capability.

**Accept an instruction and use an LLM to derive scope.** Rejected under ADR-0007. It would also make verification results non-reproducible, which defeats the purpose of a validator.

## Consequences

Positive: a feature no competitor has, aimed squarely at the primary persona, at low marginal cost. It also gives the MCP server (ADR-0018) something to do beyond producing diffs, and it makes the deterministic-semantics rule pay for itself: a validator that gives different answers on different runs is worthless.

Negative: it invites the question "how do I know my scope was right?", which is a real usability problem — a wrong scope produces a confident pass. Mitigation: `read_blocks` and `preview_structure` exist so a caller can inspect addresses before scoping, and verify reports what it considered in scope.

## Revisit when

If users consistently want instruction-derived scope, build it as an example or a companion, not inside the library.

## Related

ADR-0005, ADR-0007, ADR-0012, ADR-0018.
