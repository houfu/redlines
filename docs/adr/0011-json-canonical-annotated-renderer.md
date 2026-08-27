# ADR-0011: JSON as the canonical change format, with an annotated renderer

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The change tree is the product (ADR-0001), so its wire format is the most important interface decision in the project. Three consumers matter: Python callers, MCP clients (which are LLMs), and the browser.

The question raised during review was whether XML would be a more stable long-lived interface than JSON.

The survey shows a clear split in what the field does, and it is not JSON-versus-XML for the same data. Every agent-facing tool speaks JSON: MCP tool results are JSON by protocol; Draftable's change-details API is JSON; Docxodus exposes `GetEditScriptJson`; adeu's edit batches and diff hunks are JSON. The XML-based representations in the field are all *documents with changes inline* — OOXML's `w:ins`/`w:del`, Akoma Ntoso's amendment markup, and the plain-text cousin CriticMarkup that adeu projects revisions into. So the real distinction is **change list as data** versus **annotated document**.

On stability: XML offers namespaces and XSD; JSON Schema plus an explicit version field gives equivalent validation and versioning. The practical difference is tooling. JSON round-trips to Python dicts with the stdlib, is native in the browser, and is what every MCP client already parses. XML would mean ElementTree or lxml on the producing side and hand-written mapping on the consuming side, for no gain in the delivery path.

On what actually helps a model: Anthropic's guidance favouring XML tags is about *delimiting sections in a prompt*, not about wire formats; structured outputs and tool calls are JSON. Where markup genuinely helps is in place — a model reading `within {--thirty (30)--}{++sixty (60)++} days` reasons about the clause better than one reading a change object with two offsets.

## Decision

JSON is the canonical serialisation, with a published JSON Schema, a top-level `schema_version`, and a stated compatibility policy: additive changes bump the minor, breaking changes bump the major and the previous version stays producible.

Alongside it, an **annotated-document renderer** is a first-class output: the source document with changes marked in place, using CriticMarkup for text and markdown and a tag variant (`<ins>`, `<del>`, `<moved from="…">`) for HTML. This is what the MCP summary and annotate tools lean on when a model needs surrounding context.

The v1 flat JSON stays unchanged and remains what `output_json()` produces, per ADR-0003.

## Alternatives considered

**XML as the canonical format.** Rejected: nothing in the delivery path consumes it natively, and its real advantage is expressible as a renderer.

**JSON only, no annotated view.** Rejected: it would leave the genuinely useful idea behind XML-based standards on the table, and the MCP server would be weaker for it.

## Consequences

Positive: one canonical format that every consumer already parses, plus a second representation tuned for reading. An XML renderer over the same tree remains about a day's work if an enterprise integration ever needs one, and it would not disturb the canonical format.

Negative: two representations to keep consistent, and the annotated renderer needs a defined escaping story for documents that already contain CriticMarkup-like syntax. Schema versioning is a commitment: once published, breaking it is expensive.

## Revisit when

If a real consumer requires XML, add the renderer. If the schema needs a breaking change, that is a new ADR, not an edit to this one.

## Related

ADR-0003, ADR-0012, ADR-0016, ADR-0018.
