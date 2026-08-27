# ADR-0012: Address blocks with HTML-like paths and document labels

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Every change needs an address: something verify (ADR-0015) can be scoped to, an MCP client can point at, a user can recognise, and a renderer can display. The 0.6 engine has only global token offsets, which mean nothing to a reader and shift whenever anything earlier in the document changes.

Three candidate schemes: positional paths, document labels ("7.2", "(a)", "Schedule 2"), and character offsets.

## Decision

Carry all three, in a syntax borrowed from HTML rather than invented: a DOM-like path (an XPath-style `/body/section[7]/clause[2]`, or a CSS-style equivalent — the exact spelling is a design task), the document's own label where one exists, a heading breadcrumb where available, and character offsets *within* the block. Global offsets survive only in the v1 output for compatibility.

Priority note: this is a required feature but a lower-priority one than the semantic layer. Get roles right first.

## Alternatives considered

**Global offsets only.** Rejected: unreadable and unstable.

**Labels only.** Rejected: many blocks have no label (preamble, recitals, unlabelled paragraphs, table cells), and labels are not unique across schedules.

**A bespoke path syntax.** Rejected on the reasoning that familiarity beats novelty: if it looks like something people already read in HTML and XML tooling, both humans and models need no explanation.

## Consequences

Positive: addresses are stable under edits elsewhere in the document, human-recognisable where labels exist, and machine-usable everywhere. Scoping verify by label ("clause 7") or by path both work.

Negative: three coexisting addressing schemes is more surface than one, and paths do shift when a block is inserted above — which is exactly why labels are carried alongside. An address is a position, not an identity; stable block identity across versions is the alignment's job, not the address's, and conflating the two would be a design error.

## Revisit when

If consumers need identity rather than position — for example to store review comments against blocks across versions — that is a separate concept (a block id) and a separate ADR.

## Related

ADR-0005, ADR-0011, ADR-0015.
