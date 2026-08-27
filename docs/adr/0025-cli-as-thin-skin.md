# ADR-0025: Treat the CLI and the MCP server as two skins over one function table

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

redlines has a click-based CLI with `text`, `markdown`, `stats` and `json` subcommands and a command-less default that emits JSON — deliberately agent-friendly. The new capabilities (structural compare, annotate, summary, verify, profiles) need surfacing there too, and the question of what that costs came up during planning.

## Decision

The existing CLI is preserved unchanged, including the command-less default. Three or four new subcommands are added — `compare`, `summary`, `annotate`, `verify` — with `--profile` and `--format` options.

CLI and MCP share **one argument-normalisation layer**: resolving a path, stdin or inline content; applying a format hint; loading a profile from a path or inline; enforcing size limits. The CLI and the MCP tools are two thin skins over the same function table, and they are written together.

Estimated cost: about a day including tests, because all the logic lives in core.

## Rationale

Two benefits beyond the obvious. Shared normalisation means the two surfaces cannot drift in how they interpret inputs, which is the usual way a CLI and a server develop subtly different behaviour. And the CLI is the fastest harness for exercising the core — it exists before the MCP package does, so it is how the new capabilities get their first real use.

## Alternatives considered

**Rebuild the CLI around the new model.** Rejected under ADR-0003.

**Skip new subcommands; rely on the MCP server and the Python API.** Rejected: the CLI is nearly free given the shared layer, it is how many users first meet the tool, and giving it up would remove the cheapest testing surface.

## Consequences

Positive: negligible marginal cost, guaranteed consistency between surfaces, an early test harness.

Negative: the shared layer is a small piece of infrastructure that must be designed before either skin, so it cannot be deferred to whichever surface is built second. The CLI also grows to eight or nine subcommands, which needs care in `--help` organisation so the old and new models do not read as one confusing whole.

## Revisit when

If the CLI surface becomes unwieldy, group the legacy subcommands under a namespace with aliases preserved — a documentation change more than a code one.

## Related

ADR-0003, ADR-0016, ADR-0017, ADR-0018.
