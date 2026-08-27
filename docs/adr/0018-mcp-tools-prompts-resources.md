# ADR-0018: Use MCP tools, prompts and resources so models can author profiles

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The first sketch of the MCP server was a set of tools — compare, summary, verify, read_blocks — which would have made it the CLI over a socket, adding reach but nothing new.

The observation that changed it, raised during review: the MCP server is the only surface where a **model can write a structure profile**. The CLI cannot hold that conversation and the site has no model in it at all.

That matters because profiles (ADR-0006) are how semantic understanding enters the system, and writing one for an unfamiliar document family is exactly the kind of pattern-spotting work a model is good at and a user finds tedious.

MCP has three primitives, not one. **Tools** are model-invoked. **Prompts** are user-invoked templates the server fills with its own context. **Resources** are documents a client can read directly. A tools-only server uses a third of the protocol.

## Decision

The server uses all three.

**Tools:** `compare`, `summary`, `annotate`, `verify`, `read_blocks`, plus `preview_structure` (apply a profile to one document and return the block tree with `matched_by`, confidence and fallback count) and `validate_profile` (schema and pattern errors with line references). Each accepts a file path or inline content, plus an optional profile by path or inline.

**Prompts:** `draft_profile` (hands the model the profile schema, a built-in profile as a worked example, and a sample of the user's document), `refine_profile` (the current profile plus `preview_structure` output plus what looks wrong), and later `explain_changes`.

**Resources:** the profile schema, every built-in profile, the change-tree schema, the skill text.

Together these close a loop with no human in the middle and no model call inside the library: draft a profile, apply it with `preview_structure`, read the confidence and fallback counts, see that schedules did not reset numbering or that `(i)` was mis-nested, refine, repeat, then `compare`. That loop is documented as the canonical workflow in the skill text, with a worked transcript against the sample pair, and a golden test replays it with a fixed draft.

Transport is stdio in 0.1 — what Claude Code, Claude Desktop and Cursor use. Streamable HTTP follows in 1.1 for hosted agents.

## Alternatives considered

**Tools only.** Rejected: it wastes the protocol's most distinctive capability and reduces the server to a transport.

**One omnibus tool with a mode flag.** Rejected: models call several narrow, well-described tools more reliably than one wide one.

## Consequences

Positive: the server becomes the place where semantic understanding is *created*, not just consumed — a genuinely differentiated reason to install it. It also makes the no-LLM-in-core rule (ADR-0007) work in our favour: the model uses the library rather than the library using a model.

Negative: it imposes a hard constraint on the profile format — a model given the schema and one example must be able to produce a valid profile in a single turn, which rules out anything deeply nested or clever. It is also more surface to document, test and keep current as the MCP specification evolves. And profiles authored in a chat must be savable as files, or the loop produces work that evaporates.

## Revisit when

If clients in practice ignore prompts and resources, shrink to tools plus a resource for the schema. If the profile format cannot be made legible enough for single-turn authoring, this loop is not viable and the profile design needs to change, not the server.

## Related

ADR-0006, ADR-0007, ADR-0016, ADR-0017.
