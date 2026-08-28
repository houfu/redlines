# ADR-0028: Generate the API reference from griffe as native site pages, not pdoc HTML

**Status:** Proposed
**Date:** 2026-08-28
**Deciders:** houfu

## Context

ADR-0026 kept pdoc as the API-reference generator: its HTML is built into the site and served under `/api/`, with docstrings as the source of truth. That was the right call given what it knew — a Python documentation generator running beside a JavaScript site, with no obvious way to make an API reference out of docstrings inside Astro.

Building it surfaced three seams that the decision did not anticipate.

**The reference is a foreign body on its own site.** pdoc's pages carry their own layout, their own light theme against Starlight's dark, and their own search box beside Pagefind's. The link into it broke on the first attempt, because Starlight's sidebar formatter strips a `.html` extension and pdoc's output is files; the fix was to delete pdoc's index stub and give Astro the route. Each of those is small. They are all the same seam.

**It is the least machine-readable part of the machine surface.** ADR-0027 lists the pdoc reference in Tier 0, alongside `llms.txt`, the per-page markdown and the schemas. But pdoc emits HTML only, so `llms-full.txt` contains every prose page and no API reference at all, and `llms.txt` carries it as an optional link. An agent that fetches the machine surface gets the guides and then has to scrape HTML for the actual API. ADR-0027 created that gap; it did not exist before the machine surface was promised.

**pdoc is not rendering our docstrings.** They are reST, and `:param source:` / `:type source:` / `:return:` appear as literal text on the published pages — six of them in `redlines.processor` alone.

Since ADR-0026 was written, `starlight-pydocs` was published: a Starlight plugin that reads a package with **griffe** — static analysis, nothing imported — and renders it as native Starlight pages. griffe is the engine under `mkdocstrings`, so this is the same extraction the Python ecosystem already relies on, with an Astro renderer in front of it instead of a MkDocs one.

## Decision

**Proposed, not agreed.** Replace pdoc with `starlight-pydocs` as the API-reference generator, amending ADR-0026's second decision bullet. Docstrings remain the source of truth, which is the part of ADR-0026 that matters and does not change.

If accepted, this also rewrites PRD R47 ("built with pdoc and served under `/api/`"), the Tier 0 sentence in ADR-0027, CONTRIBUTING's documentation section, and the `api` script in `site/package.json`. pdoc leaves the development dependencies.

## Evidence

This was trialled on the real package, on branch `claude/trial-starlight-pydocs`, with the reference mounted beside pdoc's rather than over it. It built on the first attempt and produced: one page per module with a sidebar tree and class summary tables; a symbol search over a 30 KB `symbols.json`, alongside rather than instead of Pagefind; `.md` and `.md.txt` for every page; `llms.txt` and `objects.inv` per package; inherited members labelled with the class they came from; and source links pinned to the commit SHA.

Two things needed configuring, and both are facts about our code rather than defects in the tool.

- **`docstringStyle: 'sphinx'`.** Without it the reST markers render as text, exactly as they do under pdoc today. With it they become proper Parameters and Returns sections — the one place where switching demonstrably improves the published page rather than merely relocating it.
- **`members: { exclude: ['redlines.cli.*'] }`.** `redlines/cli.py` marks nine members `@private`, which is a pdoc docstring pragma. griffe has never heard of it, so all nine appeared, each with a literal `@private` line in its body. Excluding them by glob restores what pdoc published, which was nothing at all for that module.

That second point deserves a decision of its own rather than a silent reproduction: static analysis renders the click commands with their real signatures, where pdoc showed nothing. A CLI reference page may be worth more than the hole pdoc leaves.

One cosmetic loss: instance attributes render as their assignment, `autojunk = autojunk`, rather than an inferred type. That is inherent to static analysis and is the clearest thing pdoc's dynamic introspection does better.

## The risk, stated plainly

`starlight-pydocs` was created on 12 August 2026 and last released on the 14th, at 0.2.1. Five stars. Twenty-six downloads in the last week — against 46,000 for `starlight-typedoc` and 75,000 for `starlight-llms-txt`, which this site already depends on. It has no open issues because nobody is filing any. It is three weeks old and essentially unused, and it would be doing a job that is currently done by a mature tool.

Three things bound that risk, which is why this is proposed rather than refused:

- PRD R50 already says the site cannot block a release. The worst failure is a stale reference, not a blocked ship.
- MIT, no runtime dependencies, and its peer range matches what the site already runs.
- It reads a pre-generated griffe JSON dump as an alternative to extracting at build time. If the plugin is abandoned, the dump is still ours, and rendering it is the approach `codellm-devkit` already runs in production — an IBM Research project that migrated MkDocs to Starlight and generates its reference pages with a one-file griffe script.

## Alternatives considered

**Keep pdoc under `/api/`,** which is ADR-0026 as written. It works, it is mature, and it costs nothing to leave alone. Rejected in this proposal on the three seams above, none of which pdoc can close: it cannot emit markdown for the machine surface, it cannot share the site's search or theme without a template rewrite, and it renders our reST docstrings as literal text.

**Write our own griffe-to-markdown generator,** as `codellm-devkit` does. Same extraction, no npm dependency, full control, and it is the fallback if the plugin dies. Rejected as the first move because it means owning signature rendering, cross-references, inherited-member merging and a symbol index — the work `mkdocstrings` has a large template suite for — to reach a worse version of what the plugin already produces.

**MkDocs Material with `mkdocstrings`.** ADR-0026 rejected this on the two-builds argument, and the argument still holds while the demo needs a JavaScript build. Noted only because it is what this proposal would otherwise be reinventing.

## What would settle this

Accept if the trial output reads well enough on `redlines.redlines` and `redlines.processor` to be the published reference, and if the CLI question is answered deliberately — hidden as pdoc had it, or published with real signatures.

Reject if the dependency risk outweighs three seams that are, honestly, tolerable: the reference works today, and 1.0 has engine work that matters more.

Defer if the answer is "yes, but not while the API is being rebuilt". M1 through M3 replace most of what the reference documents, and regenerating from griffe at 1.0 costs the same as regenerating now.

## Revisit when

If accepted: revisit if `starlight-pydocs` goes unmaintained — the escape hatch is the griffe dump plus our own renderer, and the trigger is a release of Astro or Starlight it does not follow. Revisit also if static analysis proves unable to describe the 1.0 API, which is the one thing pdoc's dynamic introspection does better.

If rejected: revisit when the API reference is expected to be complete in `llms-full.txt`, which is the seam that cannot be closed by leaving things alone.

## Related

ADR-0026 (which this amends if accepted), ADR-0027, ADR-0004. Requirements R47, N6.
