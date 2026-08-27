# ADR-0002: Optimise for LLM and agent pipeline developers

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Two plausible audiences exist for a structural redliner. Legal engineers comparing two versions of a contract, who want clause-level diffs and Word-compatible output. And developers building LLM and agent pipelines, who need to know what a model changed, where, and whether that was all it was supposed to change.

The download curve says which audience redlines already has. Roughly 3.7M lifetime PyPI downloads against ~158 GitHub stars is the signature of course-and-notebook usage, not of a tool people build products on; the README itself cites the DeepLearning.AI course lesson that drove it. Only two dependent packages are registered on libraries.io, so almost all use is direct.

The legal-comparison audience is well served by incumbents with a decade of OOXML fidelity work behind them, and by a 2026 cohort of Rust and TypeScript tools built specifically for it.

Separately, an incumbent has validated the agent-facing format: Draftable shipped an "AI-Ready Redline Export" in its February–March 2026 release, a deterministic plain-text change summary designed to be pasted into ChatGPT, Claude, Harvey or Legora. That is redlines' natural output, sold as a feature.

## Decision

The primary user is the **LLM/agent pipeline developer**. Feature sequencing, output formats, documentation and the MCP surface are designed for that person first. The document engineer is a secondary user who drives the block model and alignment requirements but does not drive OOXML fidelity work.

## Alternatives considered

**Legal engineers first.** Rejected: it points the roadmap at DOCX fidelity, where the competition is strongest and redlines is weakest, and it abandons the existing user base.

**Both equally.** Rejected as a non-decision. Serving both equally in practice means DOCX work competes with agent work for the same hours, and DOCX work always looks more urgent because it is more concrete.

## Consequences

Positive: it makes several later decisions easy. JSON and a deterministic summary are first-class; verify mode (ADR-0015) becomes a headline feature; the MCP server (ADR-0017, ADR-0018) is a deliverable rather than an afterthought; DOCX can be deferred without guilt.

Negative: the demo site cannot accept a Word file at 1.0 (ADR-0013), which is the first thing a lawyer will try. Some legal users will bounce. We accept that in exchange for a coherent 1.0.

## Revisit when

If the MCP server and agent-facing outputs fail to find users within two quarters of release while inbound requests are dominated by "can it read my Word documents", the persona choice was wrong and the roadmap should be re-ordered around DOCX.

## Related

ADR-0013, ADR-0015, ADR-0017, ADR-0018.
