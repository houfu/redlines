# ADR-0006: Drive readers with declarative structure profiles

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Turning plain text into a block tree means detecting labels, inferring hierarchy from them, attaching continuations, and recognising headings; then a semantic pass assigns roles and spans (ADR-0005). All of that is pattern matching, and the patterns differ by document family.

A Singapore statute numbers sections `4.—(1)`. A US contract uses `Section 4.1`. An EU regulation uses `Article 4(1)(a)`. An internal policy uses `4.1.2` with bold headings. A markdown draft from an LLM uses `##` and `1.` list items. Alpha and roman labels are ambiguous in isolation — `(i)` after `(h)` is alphabetic, after `7.2` it is roman — and are only resolvable from the surrounding numbering context, which is itself family-specific. Headings that reset numbering (Schedule, Annex, Part) are what make labels unambiguous again after a boundary, and which headings do that varies too.

Hard-coding one family's patterns means being wrong for every other family, and being wrong silently.

The observation that settled this, raised during review: at some level it is the *user* who declares what structure they care about. The library's job is to apply that declaration faithfully, not to guess.

## Decision

Readers are driven by a declarative **structure profile**: label patterns and their nesting precedence; which headings reset numbering; heading recognition rules; role assignment rules; span extractors.

Built-in profiles ship for `generic` (paragraphs only), `contract` and `markdown`, with `legislation` following. A profile is selected explicitly or, later, auto-selected by scoring a sample of the document, with the winner and confidence reported. Profiles can be loaded from a file or passed as a mapping, from Python, the CLI (`--profile`), the MCP tools and the site, so a profile written once is reusable everywhere.

The profile format is a design requirement, not just a documentation concern: it must be flat, plainly named and schema-published, such that a model given the schema and one worked example can write a valid profile for a new family in a single turn.

Every block records how it was recognised (`matched_by`) and a confidence; the tree reports how many blocks fell through to plain paragraphs. When nothing matches, the reader degrades to one block per paragraph and alignment still works.

## Alternatives considered

**Hard-coded legal heuristics.** Rejected: right for one family, silently wrong for the rest, and every new family needs a release.

**Roles only from syntax that already carries them** (markdown headings, DOCX styles). Rejected: it gives up on plain text entirely, and plain text is what LLMs and PDFs produce.

**A model-backed structure pass.** Rejected, and forbidden by ADR-0007. It would make structure non-deterministic and uninspectable — the two properties that make this design defensible.

## Consequences

Positive: semantic understanding becomes *declared* — inspectable, portable, versionable, improvable by users without a release. It gives the MCP server something unique to do (ADR-0018): a model can author a profile in a loop without any model call inside the library. And it is a defensible position against both the OOXML-first tools, which have no notion of a clause, and any future LLM-heavy competitor, whose structure cannot be inspected.

Negative: the profile format is now on the critical path and is a genuine design task — get it wrong and every reader is awkward. Auto-selection is extra machinery. Users with unusual documents must write a profile, which is a real barrier even if a model can help. And a wrong profile produces a confidently wrong tree, which is why `matched_by`, confidence and fallback counts are mandatory rather than nice to have.

## Revisit when

If in practice everyone uses the built-in profiles unmodified, the format is over-engineered and could be simplified. If profiles proliferate and diverge, consider a shared community registry.

## Related

ADR-0005, ADR-0007, ADR-0013, ADR-0018.
