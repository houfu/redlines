# ADR-0029: Spell block addresses as XPath-style kind paths, with the label and breadcrumb alongside

**Status:** Accepted
**Date:** 2026-09-03
**Deciders:** houfu

## Context

[ADR-0012](0012-html-like-addresses.md) decided *that* a block carries three coexisting addressing schemes — a DOM-like path, the document's own label, and character offsets within the block — and deliberately left one thing open: "an XPath-style `/body/section[7]/clause[2]`, or a CSS-style equivalent — the exact spelling is a design task". M1 is where that task comes due, because the reader interface (R7), the change tree (M2), verify's scope arguments (R24) and the MCP tools all quote addresses at each other, and a syntax changed after any of those ship is a wire-format break.

Three things about the block model narrow the choice. `kind` is a closed set of nine names (R1, [ADR-0005](0005-minimal-core-open-semantic-layer.md)), so a path step can name a kind without inventing a vocabulary. A block's `label` is not unique across a document — "1.1" appears again inside every schedule — so a label cannot *be* the address. And a tree has exactly one root, which every path shares.

## Decision

An address is an XPath-style path of `kind[index]` steps, from the document root, separated by `/`:

```
/                                the document root
/section[7]/list_item[2]
/table[1]/row[2]/cell[3]
```

- The step name is the block's `kind`, spelled exactly as the closed set spells it. `list_item` and `row` are steps; a profile's role name never is.
- The index is **1-based among same-kind siblings**, so a section's second `paragraph` is `paragraph[2]` however many `heading` blocks sit between them. XPath's own convention, and the one that survives a reader inserting a heading.
- The index is never omitted, not even for an only child. `/section[1]` and `/section` meaning the same thing would be two spellings of one address, and consumers would compare them as strings.
- The root's path is `/`, and its own kind does not appear in its children's paths: the first section is `/section[1]`, not `/document[1]/section[1]`. Every path in a tree shares the root, so naming it in every address buys nothing.
- The `label` and a **heading breadcrumb** are carried alongside the path as their own fields, never encoded into it. The breadcrumb is derived from position — walking down to a block, each step contributes the nearest `heading` preceding it, plus an ancestor heading's own text where a reader nests blocks under headings — so it costs a reader nothing and cannot disagree with the tree.

`redlines.blocks.assign_paths` is the one implementation: it walks a path-less tree and returns a copy with every `path` filled in, and `BlockTree.build` calls it, so a reader gets addressing for free and no two readers can spell an address differently. `block_at` resolves an address back to a block by counting siblings rather than by string-matching stored paths, so it works on a tree that has not been addressed yet.

## Alternatives considered

**CSS-style selectors** (`section:nth-of-type(7) > list_item:nth-of-type(2)`), the other candidate ADR-0012 named. Rejected: three times the characters for the same information, a spelling (`nth-of-type`) that has to be looked up, and a syntax whose descendant/child combinators invite selector *matching* — a query language — when what is needed is one canonical address per block. XPath's bracket form is the more familiar of the two for a path that identifies exactly one node, which is ADR-0012's own "familiarity beats novelty" test.

**Indexing among all siblings rather than same-kind siblings** (`/section[7]/child[2]`, or `/section[7]/[2]`). Simpler to compute, and stable under a same-kind insertion in exactly the same way. Rejected because the kind carries real information in the address itself — `/table[1]/row[2]/cell[3]` is readable in a log line, a commit message or an LLM's output in a way `/1/2/3` is not — and because dropping the kind would make the address unverifiable: with the kind in the step, resolving an address against the wrong tree fails loudly instead of landing on some unrelated block.

**Label-based addresses** (`/clause/7.2`). Rejected in ADR-0012 already: unlabelled blocks have no address at all, and labels repeat across schedules. The label is carried alongside precisely so that the human-recognisable name and the unique address can both exist without either pretending to be the other.

**Encoding the breadcrumb into the path** (`/section[7]{Termination}/list_item[2]`). Rejected: it makes the address change when a heading is retitled, which is exactly the instability the path exists to avoid, and it makes an address unparseable without escaping rules for whatever a heading might contain.

**Numbering from 0.** Rejected: XPath, CSS and the documents themselves all count from 1, and an address is read by people at least as often as by code.

## Consequences

Positive: an address is short, canonical, and recognisable on sight to anyone who has used XPath; it round-trips through JSON as a plain string with no escaping; and because indices are per-kind, the common structural edits (inserting a heading, adding a note) leave sibling addresses of other kinds alone. One function assigns them, so the syntax cannot drift between readers.

Negative: a path is a position, not an identity — inserting a section above shifts every following `section[n]`, and that is by design (ADR-0012: "An address is a position, not an identity"). Alignment is what tracks a block across versions; the label is what a person recognises. Consumers that want to diff two documents' addresses directly will get noise from renumbering, and the change tree carries both addresses of a moved block for that reason.

Two smaller costs. Because the root's kind is absent from the path, a bare `/` is a valid address that resolves to the whole document, and consumers must handle it rather than assuming at least one step. And a reader that produces a block whose kind is `unknown` gets addresses reading `/unknown[3]`, which is ugly on purpose: it is a visible reminder that something was not recognised, in the same spirit as `matched_by: fallback` ([ADR-0030](0030-matched-by-and-confidence.md)).

## Revisit when

If a 1.1 reader needs a step this syntax cannot express — a DOCX table with merged cells spanning rows, say, or an Akoma Ntoso element with a stable XML id — that is the signal to extend the step grammar rather than bend the tree to fit. Prefer an additional field over a change to the path syntax; ADR-0012's revisit condition already reserves block identity for its own ADR.

If verify or the MCP tools grow a need to *match* a set of blocks rather than name one — "every `list_item` under `/section[7]`" — that is a query language, and it should be added as one (a prefix match is already enough for scope), not by making addresses ambiguous.

## Related

ADR-0005, ADR-0011, ADR-0012, ADR-0015, ADR-0030.
