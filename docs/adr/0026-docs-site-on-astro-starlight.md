# ADR-0026: Publish the documentation with Astro Starlight, in the same site as the demo

**Status:** Accepted
**Date:** 2026-08-27
**Deciders:** houfu

## Context

Documentation today is `pdoc` run over the package on release, deployed to GitHub Pages. It renders docstrings and nothing else: there is no way to publish a hand-written page.

1.0 needs hand-written pages. N6 requires the JSON v2 schema and the profile schema published with examples, and the agent guide rewritten for compare, summary, annotate and verify. ADR-0021 produces a benchmark report meant to be an external quality signal, which has to be readable somewhere. ADR-0006 makes profiles a user-authored artefact, so profile authoring needs a guide. The ADRs themselves are worth publishing. None of that is a docstring, so M4's exit criterion — "agent guide live" — currently has nowhere to land.

Separately, ADR-0019 commits to a client-side demo site under `site/`, built by CI and served from GitHub Pages. Left alone, that is two static sites, two build systems and two deployments on one domain, and PRD section 13 still carries "where the site lives" as an open question.

## Decision

**Astro Starlight is the documentation platform**, replacing pdoc as the publishing surface, in **one Astro project under `site/`** that serves both the documentation and the demo.

- The demo of ADR-0019 becomes a route in that project, with the Pyodide worker as an island. One build, one deploy, one domain. This resolves PRD section 13's open question in favour of the main repository.
- **pdoc is kept as the API-reference generator.** Its HTML is built into the site and served under `/api/`. Docstrings remain the source of truth for the API reference, so CONTRIBUTING's instruction to edit documentation in the source files still holds.
- The migration happens in the **0.6.x hygiene release**, before any 1.0 documentation is written, so that no page is written twice — first for pdoc, then again for the new site.

## Rationale

The deciding argument is that the demo needs a JavaScript build regardless. ADR-0019 already commits to a Pyodide UI with a web worker, file drop, expandable change lists and a profile selector, which is a front-end application whatever hosts it. Given that a JS toolchain is arriving anyway, running one of them is cheaper than running a Python docs generator beside it, and it collapses two deployments into one.

Starlight in particular: it is a documentation theme rather than a framework to be assembled, so the default output is a sidebar, search and dark mode with no design work; MDX lets the schema pages embed a real worked example instead of a code fence copied by hand; and an Astro route sitting next to the docs is exactly the shape the demo needs.

There is a second-order benefit. The demo is the best documentation this project has — a visitor who can paste two clauses and see a change tree understands the thesis faster than any prose. Putting it inside the docs site rather than beside it means every documentation page is one click from a live example.

## Alternatives considered

**Keep pdoc alone.** Free and already working. Rejected: it cannot publish a hand-written page at all, which is the entire requirement.

**MkDocs Material.** The conventional choice for a Python project, and a strong one: `mkdocstrings` gives a better API reference than pdoc, it stays inside the Python toolchain, and contributors would need no Node. Rejected on the demo. The Pyodide UI needs a bundler and a component model either way, so choosing MkDocs means maintaining a Python docs build *and* a JS app build, and deploying two artefacts to one Pages site. If ADR-0019 were ever reversed and the demo dropped, MkDocs Material would be the right answer and this decision should be revisited.

**Sphinx.** The most capable of the three and the standard for large Python projects. Rejected as disproportionate: RST or MyST plus autodoc ceremony is a lot of machinery for a library with six source files, and it has the same two-toolchain problem as MkDocs.

**Docusaurus.** Same JS-toolchain argument as Starlight, but a heavier React application for the same result, and its own routing conventions to work around for the demo.

**Docs and demo as separate builds.** Keeps the demo's 10–15 MB Pyodide payload fully isolated from the documentation. Rejected: the isolation is already achieved by the worker and by route-level code splitting, and two builds means two deploy workflows, two dependency sets and a broken link between them the first time a path moves.

## Consequences

Positive: a home for everything 1.0 has to publish; the ADRs and the benchmark report become readable artefacts rather than repository files; M6 shrinks from "build and deploy a site" to "add a route"; and one deployment can never drift from the other.

Negative, and this is the real cost: **a Python repository acquires a Node toolchain**. A package manifest and lockfile, a `node_modules` in contributor checkouts, a Node step in CI, and a JavaScript dependency surface to keep patched — on a project whose central discipline (ADR-0004) is a dependency-free core. The mitigation is a boundary, not a promise: nothing in `site/` is imported by the wheel, nothing in the wheel depends on the site building, and a broken site build must never be able to block a release.

The API reference also becomes a two-step build — pdoc, then Astro — rather than one command, which is a sharper edge for a contributor previewing documentation locally than the single `uv run pdoc` it replaces.

## Revisit when

If the demo is ever dropped or moved out of the repository, the JS toolchain loses its justification and MkDocs Material becomes the better answer. Revisit also if keeping the Node dependencies patched turns into recurring maintenance out of proportion to a documentation site, or if the demo's payload turns out to degrade documentation page loads despite code splitting.

## Related

ADR-0004, ADR-0006, ADR-0019, ADR-0020, ADR-0021.
