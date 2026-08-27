# ADR-0022: Keep the name redlines

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The name collides. `python-redlines` on PyPI is a different, actively maintained project doing DOCX comparison. `redlines.opensource.legal` is its demo. `redlines.free` is jubarte's commercial site. Searching for "redlines" surfaces all of them.

A rename before a 1.0 rewrite would be the cheapest moment to do it.

## Decision

Keep the name. `redlines` stays the package, the repository and the project.

## Rationale

The name carries the distribution: 3.7M downloads, the course material, existing notebooks and blog posts, and whatever search authority the project has. A rename would forfeit all of it to solve a marketing nuisance rather than a product problem — nobody has ever installed the wrong package and been unable to tell.

The demo site's domain is a separate and much cheaper decision, and can differentiate without touching the package.

## Alternatives considered

**Rename to escape the collision.** Rejected for the reasons above. If a rename ever becomes necessary, the moment is a 2.0 with a transitional meta-package, not a quiet swap.

## Consequences

Positive: continuity, and no migration work.

Negative: ongoing confusion in search results and in conversation, particularly with python-redlines, whose maintainer is a plausible collaborator (ADR-0014) — which makes clear positioning in the README more important than usual. Both projects should probably say what the other is.

## Revisit when

If a legal conflict arises, or if the collision demonstrably costs adoption (measurable as people arriving at the wrong project and saying so).

## Related

ADR-0014, ADR-0019.
