# ADR-0007: No OCR and no LLM calls inside the library

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Once the model carries semantic roles (ADR-0005) and structure is inferred by heuristics (ADR-0006), there is a standing temptation to improve both with a model call: ask an LLM which blocks are definitions, or run OCR so scanned PDFs can be compared. Both would raise measured accuracy on hard inputs.

The concern raised during review was precisely this: that supporting PDF and DOCX would drag OCR and LLM requirements into a library whose top requirements are semantic.

## Decision

The library never calls an OCR engine and never calls an LLM. The semantic pass is deterministic heuristics over text, always. The PDF reader, when it arrives, extracts embedded text only and flags the resulting structure as inferred; a scanned PDF with no text layer is reported as unreadable, not OCR'd.

Both the semantic pass and the reader interface are pluggable, so anyone who wants a model-backed pass can write one *outside* the library and register it.

## Alternatives considered

**An optional LLM-backed semantic pass shipped in the library, off by default.** Rejected: "off by default" erodes. Once it exists it becomes the recommended path, then the tested path, and the deterministic path rots. It would also put an API key, a network call and a bill inside a library people run in notebooks and CI.

**Optional OCR via an extra.** Rejected for the same reason plus a practical one: OCR quality dominates every downstream result, so the library's measured behaviour would become a measure of the OCR engine.

## Consequences

Positive: results are reproducible, testable and free. The same inputs give the same output today and in a year, which is what makes verify mode (ADR-0015) trustworthy and golden-file tests possible. It keeps the browser deployment viable (no network). And it draws a clean line for contributors about what belongs inside.

Negative: accuracy on messy inputs is capped by what heuristics can do, and we will lose comparisons against tools that do use models. Scanned documents are simply out of scope. We accept both; the benchmark (ADR-0021) exists so the ceiling is known rather than felt.

## Revisit when

Not lightly. If a model-backed pass becomes essential, the right shape is a separate companion package that produces profiles or annotations the library consumes — never a call from inside.

## Related

ADR-0005, ADR-0006, ADR-0013, ADR-0015, ADR-0019.
