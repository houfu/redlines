# ADR-0014: Never write OOXML; delegate tracked changes to appliers

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The obvious "complete" version of a redlining library produces a Word document with native tracked changes. That is what python-redlines, Docxodus, stemma, safe-docx, folio, jubarte, SuperDoc, adeu and superdoc-redlines all do, and it is what the one public benchmark measures.

It is also a deep well. Writing `w:ins`/`w:del` that Word accepts, rejects and filters correctly means handling numbering, styles, tables, footnotes, headers, content controls and fields. python-redlines documents a bug where move markup produces a file Word refuses to open. The original Open-XML-PowerTools engine is described as crashing on documents with minor format issues. Every serious implementation in this space is a multi-year effort by a team.

Meanwhile at least four open-source OOXML patchers already exist and are actively maintained, and two of them (adeu, superdoc-redlines) are explicitly designed to accept an edit batch from an external decision-maker.

## Decision

redlines does not write OOXML — not in 1.0, not on the current roadmap. When DOCX output is wanted, the change tree is exported as an edit batch for an existing applier (adeu primary, superdoc-redlines secondary), which does the writing. That export is 1.1, deferred alongside DOCX reading.

One design constraint applies from 1.0: every inline change must be recoverable as (block address, old text, new text) with enough surrounding context to anchor a text search. That keeps the door open without building anything now.

## Alternatives considered

**A native `w:ins`/`w:del` writer.** Rejected: it is where the competition is strongest and redlines has no edge, and it would consume the whole roadmap.

**No DOCX output at all, ever.** Rejected as unnecessarily absolute; delegation costs little and turns a rival into a back end.

## Consequences

Positive: it keeps the project's scope honest and makes redlines a complement rather than a competitor to adeu and Docxodus — a joint story ("redlines computes the structural diff, adeu writes the tracked changes") is coherent and worth proposing to those maintainers once the JSON schema is drafted, since the schema is the integration point.

Negative: our DOCX story depends on someone else's addressing model. adeu targets edits by `target_text` search, which its own issues (#28, #29) admit is ambiguous on repeated text. Mitigation when the export is built: emit strict match mode with enough context, fall back to block-level replacement, and report ambiguities rather than guessing. There is also a positioning cost — "does it produce Word redlines?" will be answered "through another tool", which some evaluators will score as a no.

## Revisit when

If every applier stalls or disappears, or if a paying use case requires a single-dependency path to a tracked-changes DOCX, reconsider — but the first response should be to contribute to an applier, not to start a fifth one.

## Related

ADR-0001, ADR-0013.
