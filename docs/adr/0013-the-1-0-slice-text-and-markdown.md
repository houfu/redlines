# ADR-0013: Limit 1.0 to plain text and markdown

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

An earlier draft of the plan had 1.0 reading txt, markdown, DOCX, PDF and HTML, so the demo site could promise "upload anything".

The concern raised on review: the top requirements are semantic (roles, clause structure, cross-references), and PDF and DOCX threaten to drag OCR and LLM requirements in behind them, bulking up a release whose point is to demonstrate a thesis.

That concern is well founded for PDF and partly founded for DOCX. Semantic roles come from heuristics over clean text (ADR-0006). Plain text and markdown supply clean text directly. PDF does not: extracted text loses heading structure and list nesting, page furniture interleaves with content, and scanned documents have no text at all — which is where OCR pressure comes from. DOCX needs neither OCR nor a model, and its styles would actually *help* the semantic pass, but it does add a dependency, a reader to maintain, and a set of format edge cases.

## Decision

1.0 reads plain text and markdown only. HTML, DOCX and PDF move to 1.1, in that order of cost. The demo site's promise changes from "upload anything" to "drop text or markdown", stated plainly, with a specific "coming in 1.1" message for other types.

The markdown reader is the small stdlib-regex one — ATX headings, nested lists, numbered clause patterns, pipe tables, fenced code — not a markdown-it dependency. Markdown is what LLMs emit, so it is the primary persona's most common input and cannot be deferred.

To keep the release demonstrable without uploads, a single sample pair is defined and becomes the site's default state: a short services agreement in markdown and an amended version containing exactly one of each detectable change — a modified definition, a moved clause, a renumbering, an updated cross-reference, a deleted sub-clause, an inserted table row, a whitespace-only non-change, and an edit inside a repetitive schedule that the flat 0.6 engine gets wrong. Its expected change tree is a golden file: the first test written and the last allowed to fail.

## Alternatives considered

**All five formats in 1.0.** Rejected: scope, and the risk that the weakest reader (PDF) becomes how people judge the engine.

**Defer markdown too, treating it as plain text.** Considered and rejected: markdown is nearly free given the shared label-detection and continuation logic, and deferring it would leave the primary persona's own inputs unparsed.

**Keep DOCX in 1.0 and defer only PDF.** This was the standing recommendation before the review, on the grounds that DOCX is where most real version pairs live. Overruled in favour of a smaller slice; the reader is first in the 1.1 queue after HTML.

## Consequences

Positive: 1.0 stays a demonstrable slice with no OCR question, no model question, and no heavy dependency. The Pyodide build (ADR-0019) needs no extras at all.

Negative: a lawyer arriving at the site with a .docx is turned away, which is a real first-impression cost. Mitigations: the sample pair is the default state so capability is visible before any upload, the deferral message is specific, and DOCX is early in 1.1.

## Revisit when

If inbound demand is dominated by DOCX before 1.0 ships, pull the reader forward — it is a contained piece of work, and this ADR's reasoning does not argue that DOCX is hard, only that it is not needed to prove the thesis.

## Related

ADR-0002, ADR-0006, ADR-0007, ADR-0014, ADR-0019.
