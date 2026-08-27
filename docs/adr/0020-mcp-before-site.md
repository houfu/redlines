# ADR-0020: Ship the MCP server before the site

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Both end deliverables sit on the same core. The order in which they are built is a real choice, because whichever comes first shapes the contracts the other inherits.

## Decision

The MCP server ships first, within days of the 1.0 core. The site follows, once the renderers are stable.

## Rationale

The server is thin over the core, so it reaches the primary persona (ADR-0002) at the lowest cost. More importantly, building it first *forces the contracts to be right*: the change-tree JSON, the summary format, verify's inputs and outputs, and the profile format all get exercised by a demanding consumer before any UI depends on them. A schema frozen against a real client is a better schema than one frozen against a design document.

Building the site first would mean doing UI work against contracts that are still moving, and UI is the most expensive thing to redo.

## Alternatives considered

**Site first** — visible, shareable, and it would test the readers against real uploads early. Rejected for the contract-churn risk. The sample pair (ADR-0013) covers the "something to show" need in the meantime.

**Both in lockstep.** Rejected: slower to any release, and it splits attention during the phase when the schema most needs a single demanding consumer.

## Consequences

Positive: contracts settle early against a real client; the persona is served first; the site inherits stable outputs.

Negative: the visible, shareable artefact arrives last, so there is a period with a released library and no public demo. The sample pair and the benchmark report partly fill that gap.

## Revisit when

If an opportunity makes a public demo urgent (a talk, a launch, a course), the order can be flipped — accepting the churn cost knowingly.

## Related

ADR-0002, ADR-0013, ADR-0017, ADR-0019.
