# ADR-0004: Keep a stdlib core with optional extras

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

Part of redlines' identity is that `pip install redlines` is instant and works anywhere — a notebook, a Lambda, a CI job, a WASM runtime. Its current dependencies are click, click-default-group, rich-click and rich; nupunkt and Levenshtein are already optional extras.

The competition sits at the other end. python-redlines extracts a self-contained .NET executable from a platform wheel to a cache directory and invokes it by subprocess. superdoc-redlines needs Node 18, jsdom and an AGPL-licensed editor. adeu needs Python 3.12+.

Meanwhile the structural engine has real reasons to want dependencies: rapidfuzz for alignment similarity, python-docx for DOCX, pypdf for PDF, a markdown parser, pydantic for schemas.

## Decision

The core stays on the standard library plus click and rich. Everything else is an optional extra that degrades gracefully when absent: `[fuzzy]` (rapidfuzz), `[nupunkt]`, `[levenshtein]`, and later `[docx]`, `[pdf]`. Nothing in the core may import an extra unconditionally.

## Alternatives considered

**Stdlib only, always** — no third-party dependencies even as extras. Rejected: alignment quality plausibly improves with rapidfuzz, and refusing a *optional* dependency is dogma rather than design. The zero-install property is about the default install, not about purity.

**Take dependencies freely** — rapidfuzz, python-docx, a markdown library and pydantic in core. Rejected: it is the simplest engineering and the worst positioning. It would cost the property that most distinguishes redlines from every competitor, and it would break the browser deployment (ADR-0019).

## Consequences

Positive: the default install stays small and portable; the browser build is possible at all; users install only what their formats need.

Negative: every capability that touches an extra needs a graceful-absence path and a test for it, which is ongoing tax. Alignment behaves differently with and without rapidfuzz — meaning results differ between a tuned local run and the browser, where rapidfuzz has no build. That divergence must be measured (ADR-0021) and, if large, either closed or disclosed.

## Revisit when

If the difflib-ratio fallback proves materially worse than rapidfuzz on the benchmark, consider vendoring a small pure-Python similarity implementation into core so behaviour is uniform everywhere.

## Related

ADR-0008, ADR-0019, ADR-0021.
