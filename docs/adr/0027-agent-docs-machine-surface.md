# ADR-0027: Agent-facing documentation is a machine surface and a contract page, not a guide

**Status:** Accepted
**Date:** 2026-08-28
**Deciders:** houfu

## Context

ADR-0002 makes LLM and agent pipeline developers the primary persona. The artefact that serves them today is `AGENT_GUIDE.md`: 1,056 lines, last stamped 2025-10-22 against "Version 0.6.0+". N6 and the M4 roadmap row both say it is to be "rewritten" for 1.0, which assumes the answer to a bad guide is a better guide. Before writing it twice — first for pdoc, now for the Starlight site of ADR-0026 — it is worth asking whether a guide is the right shape at all.

Three problems with the one we have.

**It serves two readers at once.** An assistant *writing integration code* wants prose, patterns and worked examples, and has context to spend on them. An agent *calling redlines at runtime* wants one thing: invocation form, output shape, exit codes, failure modes, size limits. The guide interleaves both, so neither is crisp; its Quick Reference Card is the second document trying to escape the first. At roughly 12–15k tokens, loading it costs the primary persona a meaningful slice of a working budget for content that is mostly justification.

**Nothing in it is machine-addressable.** Its "JSON Schema Reference" section is prose describing fields. It cannot be fetched, validated against, or diffed between versions. R19 and ADR-0011 already commit to a JSON schema with `schema_version`; R48 commits to publishing it and the profile schema. Once those exist as files at stable URLs, most of that section is a link.

**It restates generated surfaces, so it drifts.** It duplicates `--help`, docstrings, and — from M5 — the MCP tool descriptions and skill text, which is what a runtime agent actually reads. The drift has already started: the footer names 0.6.0 against a 0.6.1 package, and the header claims "All examples are copy-paste ready and tested" while nothing under `tests/` executes either the guide's snippets or `examples/`. M0's `autojunk` change and the punctuation-merge cleanup will alter reported change counts in those snippets, and no test will say which.

Meanwhile 1.0 adds surfaces that do the runtime job better than prose can: MCP tool descriptions and skill text (R32, R32c), the change-tree schema (R19), the profile schema (R1d, R48).

## Decision

**Agent-facing documentation is three tiers, not one document.**

**Tier 0 — the machine surface.** No prose written by hand, nothing to keep in sync: `llms.txt` and a per-page markdown export at the site root; the change-tree and profile schemas as fetchable files at stable URLs; the pdoc API reference under `/api/`; and the MCP skill text of R32c hosted rather than paraphrased. Docstrings remain the source of truth for the API reference, exactly as ADR-0026 has it.

**Tier 1 — one contract page**, short enough to be read whole in a single fetch. The verbs (`compare`, `summary`, `annotate`, `verify`), the invocation forms of the shared argument layer, the output shape linking to the schema rather than restating it, exit codes, failure modes and size limits. Everything else is a link out.

**Tier 2 — task pages for integrators.** CI check, pre-commit, batch comparison, profile authoring: today's Integration Examples, kept but demoted. These pages **include their code from `examples/`** rather than pasting it, and `examples/` becomes executed by CI, so "tested" is a fact rather than a claim.

**Sequencing.** M0 stands up the Tier 0 mechanics and migrates `AGENT_GUIDE.md` to the site whole, as one page marked as the 0.6 guide with its date visible. M4's "agent guide rewritten" becomes the decomposition into Tier 1 and Tier 2 described here.

## Rationale

The contract belongs where the caller already is. A runtime agent reads a tool description, a `--help` output or a schema; it does not read a document unless something tells it to. Every sentence of contract that lives only in prose is a sentence the caller may never see, and one more thing to keep true.

A document that duplicates a generated surface drifts, and here the evidence is not hypothetical — the version stamp and the tested-examples claim are both already wrong. Tiering does not merely shorten the prose; it removes the duplication that causes the drift.

Splitting the existing guide into pages now would be churn ahead of a rewrite that M4 already owns, and would not fix machine-addressability, which is the actual defect. Migrating it whole in M0 and decomposing it in M4 writes each page once, which is the same argument ADR-0026 used to put the site before the 1.0 documentation.

Including Tier 2 code from `examples/` costs one test and repays it every release: the snippets an integrator copies are the snippets CI runs.

## Alternatives considered

**Rewrite the long guide for 1.0**, the plain reading of N6. Rejected: it preserves both the two-audience conflation and the duplication that produces drift, and it spends M4 effort on prose that MCP tool descriptions and the schemas will serve better.

**Split it into six pages during M0.** Rejected: churn ahead of the M4 rewrite, and a six-page guide is still unfetchable, unvalidatable prose.

**Drop the prose entirely and rely on MCP plus schemas.** Tempting, and it is where a pure runtime story ends. Rejected because it strands everyone who arrives from PyPI or GitHub and integrates the CLI or the library directly, which on current install numbers is most of the user base.

**Use `AGENTS.md` as the vehicle.** Rejected on scope: `AGENTS.md` addresses agents working inside this repository, not agents consuming the library. It may be worth adding for contributors, but it is a different document with a different reader.

## Consequences

Positive: the contract exists in exactly one place per surface; N6 becomes checkable rather than aspirational; M4's documentation work shrinks to writing one short page and demoting the rest; and `examples/` stops being decorative.

Negative: Tier 0 is build machinery living in `site/` — an `llms.txt` generator and a markdown export — which is more of precisely the JavaScript dependency surface ADR-0026 already named as its real cost. If those plugins go unmaintained we own a small generator. The boundary of R50 still applies: none of it may block a release.

Operationally, the guide's URL moves. `AGENT_GUIDE.md` at the repository root becomes a stub pointing at the site, and the "Agent Guide" entry in `[project.urls]` repoints there, so PyPI does not keep sending readers to a frozen blob.

There is also a standing judgement call this decision creates rather than settles: for each new piece of prose, whether it is contract (Tier 1) or task (Tier 2). That is a discipline, not a mechanism, and it will be got wrong occasionally.

## Revisit when

If `llms.txt` fails to become something agents actually fetch, Tier 0 loses a limb and the contract page carries more. If MCP becomes the only way anyone integrates, Tier 1 collapses into the skill text of R32c and this ADR is superseded by one that says so. And if the contract page grows past what can be read in a single fetch, that is the signal that contract has leaked back into prose and needs pushing down into schemas and tool descriptions.

## Related

ADR-0002, ADR-0011, ADR-0018, ADR-0025, ADR-0026. Requirements N6, R19, R32, R32c, R48.
