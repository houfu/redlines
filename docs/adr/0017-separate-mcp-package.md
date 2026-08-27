# ADR-0017: Publish the MCP server as a separate package

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

An MCP server is one of the two end deliverables. It could be an extra on the main package (`redlines[mcp]`, adding a `redlines serve` command) or its own distribution (`redlines-mcp`) depending on the core.

The recommendation on the table was the extra, on discoverability grounds. The decision went the other way.

## Decision

`redlines-mcp` is a separate package depending on a compatible range of `redlines`. The CLI stays in the core.

## Rationale

Three reasons. It keeps fastmcp and its transitive dependencies entirely out of the core repository, which matters more than usual here because of ADR-0004 and because the core must remain importable in a browser runtime (ADR-0019) — an MCP dependency in the tree, even an optional one, is a maintenance and audit surface for a library whose selling point is that it installs anywhere. It lets the server iterate on its own cadence, which matters while the MCP protocol itself is still moving. And it keeps two audiences' issue trackers apart.

## Alternatives considered

**`redlines[mcp]` extra.** The standing recommendation. Better discoverability (one package, one README), one version to reason about, no synchronisation problem. Overruled for the reasons above.

**No MCP server.** Not seriously considered given ADR-0002.

## Consequences

Positive: a clean core; independent releases; the server can depend on fast-moving MCP tooling without imposing it.

Negative: two packages can drift, and a core release can break the server. Mitigations: pin a compatible core range; run the MCP golden tests against the core's main branch inside the core's CI; cut releases of the two together. Discoverability splits, so both READMEs must cross-link prominently, and the registry listings matter more.

## Revisit when

If keeping the two in sync becomes a recurring source of breakage, merging into an extra is a reversible decision — the code boundary would be unchanged.

## Related

ADR-0002, ADR-0004, ADR-0018, ADR-0019, ADR-0025.
