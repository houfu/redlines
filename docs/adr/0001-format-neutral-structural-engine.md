# ADR-0001: Build a format-neutral structural comparison engine

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

redlines was written in 2023 on a design that flattens a document into one token stream, marks paragraph boundaries with a `¶` token, runs one `difflib.SequenceMatcher`, and renders the opcodes. That design succeeded on its own terms — roughly 3.7M PyPI downloads, adoption by the DeepLearning.AI prompt engineering course — and has not changed materially since.

By 2026 the field around it has moved. Two camps have formed. *Comparers* take two DOCX files and emit a DOCX with native Word tracked changes: python-redlines/Docxodus, SuperDoc's Document Engine, stemma, safe-docx, folio, jubarte, and commercially Litera and Draftable. *Appliers* take edits an LLM has decided on and project them into a DOCX as `w:ins`/`w:del`: adeu, superdoc-redlines, docx-mcp, Anthropic's docx skill.

Three observations about that field matter. Every one of them is bound to OOXML — the input is always a .docx. All of them treat the diff algorithm as a commodity, using diff-match-patch or Myers over words. And none of them exposes a change model above the level of "these words changed in paragraph 37"; SuperDoc's own documentation calls its diff payload "opaque and intended for replay, not semantic inspection", and python-redlines returns a byte blob and a one-line revision count.

Meanwhile the flat spine has cliffs that show what it costs to encode structure as a character in a token stream: `autojunk=True` silently reports an entire 1,050-token repetitive schedule as replaced when two words change; adjacent edits separated by punctuation count as two changes; sentence mode discards paragraph structure entirely.

## Decision

redlines 1.0 becomes a **format-neutral structural comparison engine**. Documents are parsed into trees of blocks; blocks are aligned before the text inside them is diffed; the result is a change tree with addresses. DOCX input and tracked-changes output are borrowed from other projects rather than built (see ADR-0013 and ADR-0014).

## Alternatives considered

**A DOCX-first structural redliner** — own the whole OOXML pipeline, parser and writer, and compete head-on with Docxodus, stemma and safe-docx. Rejected: those are funded or full-time efforts with a two-year head start on OOXML fidelity, and fidelity is measured on a pixel benchmark where a text-neutral engine cannot win. It would also mean competing on the axis where redlines has no advantage while abandoning the one where it has a large one.

**An incremental fix to the flat spine** — patch autojunk, add semantic cleanup, add a DOCX reader as a `Document` subclass, enrich the JSON. Rejected: it fixes the symptoms without addressing the cause, and leaves redlines a slightly better version of a 2023 design in a field that has moved. It would not let anyone ask about clause 7.2, distinguish a move from a delete-plus-insert, or verify the scope of an edit.

## Consequences

Positive: it occupies an unoccupied slot. Nothing open-source does format-neutral hierarchical document comparison with an inspectable change model. It keeps the property that made redlines popular — anything that can be turned into text can be compared — and adds the structure that makes the output meaningful. It positions redlines as the comparison engine *in the middle* of the new stack, fed by readers and consumed by appliers, rather than as a rival at either end.

Negative: it is a large rewrite of the core, with a compatibility burden (ADR-0003). It requires solving block alignment, which is genuinely hard and which nobody in the open-source field has solved well. And it means accepting a poor score on the one public benchmark that exists (`neurotic_docx_bench` measured redlines 0.6.1 at 45.9 mean, bottom of the table), because that benchmark measures visual fidelity to Word's markup — which is not what this engine is for.

## Revisit when

If block alignment quality (ADR-0021) cannot reach the targets on real documents after honest effort, the structural thesis is wrong and the incremental path becomes the better one. If a well-funded project ships format-neutral structural diffing with an open change model before 1.0, reconsider whether to build or to contribute.

## Related

ADR-0002, ADR-0005, ADR-0013, ADR-0014, ADR-0021. Evidence: `docs/competitive-landscape-2026-08.md`.
