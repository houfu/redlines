# ADR-0016: Implement the summary renderer in core, deliver it with MCP

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

A deterministic, plain-text summary of changes — one line per block change with its address, role and inline detail, plus section totals — is the output most likely to be copied into a prompt or a review email.

It is also commercially validated. Draftable shipped exactly this in February–March 2026 as "AI-Ready Redline Export", a portable text format for pasting into ChatGPT, Claude, Harvey or Legora.

Two questions: when to build it, and where the code lives. The review's steer was that it belongs with the MCP deliverable, since that is where a model consumes it.

## Decision

The summary renderer is **built during the MCP milestone**, but **implemented in the core library**, not in the MCP package. The CLI (`redlines summary`) and the site use the same implementation.

Output is stable-ordered and deterministic, so it can be golden-tested and diffed between runs.

## Alternatives considered

**Build it with the other renderers, before MCP.** Rejected on timing: its shape should be driven by what a model actually needs, which is clearest while building the tools that feed it.

**Implement it inside the MCP package.** Rejected: it would mean CLI and site users either lose the feature or get a second, divergent implementation. There is a standing principle that no comparison or rendering logic lives outside the core, so that behaviour seen on the site is reproducible from Python with the same inputs.

## Consequences

Positive: one summary format everywhere; the MCP server stays a thin skin; the format is designed against a real consumer.

Negative: a small sequencing awkwardness — a core feature is built during a milestone named after a different package — which should be noted in the roadmap so it is not mistaken for scope creep in the MCP work.

## Revisit when

If the summary format needs to differ materially between an MCP client and a human reader, that is two renderers with two names, not one renderer with a mode flag.

## Related

ADR-0011, ADR-0017, ADR-0018, ADR-0025.
