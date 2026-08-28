## This directory

The documentation site for the `redlines` Python library: Astro + Starlight,
deployed to GitHub Pages at `https://houfu.github.io/redlines/`.

- The site is served from a `/redlines` base. Internal links written by hand
  must carry it; Starlight's own link handling does not.
- `public/api/` is **generated** — `npm run api` runs pdoc over the Python
  package, and `predev`/`prebuild` run it for you. Never edit anything there;
  edit the docstrings in `../redlines/`.
- The boundary is the point (ADR-0026, PRD R50): nothing here is imported by
  the wheel, nothing in the wheel depends on this building, and a broken build
  here must never block a release. Do not wire this project into the Python
  workflows.
- `src/content/docs/project/` is **generated** by `scripts/sync-docs.mjs` from
  the repository's own documents (ADRs, PRD, roadmap, CONTRIBUTING). Edit the
  source files, not the copies.
- Decisions that govern this directory: `../docs/adr/0026-*` (platform),
  `../docs/adr/0027-*` (what the agent-facing pages are), `../docs/adr/0019-*`
  (the demo route, arriving in M6).

## Development

When starting the dev server, use background mode:

```
astro dev --background
```

Manage the background server with `astro dev stop`, `astro dev status`, and `astro dev logs`.

## Documentation

Full documentation: https://docs.astro.build

Consult these guides before working on related tasks:

- [Adding pages, dynamic routes, or middleware](https://docs.astro.build/en/guides/routing/)
- [Working with Astro components](https://docs.astro.build/en/basics/astro-components/)
- [Using React, Vue, Svelte, or other framework components](https://docs.astro.build/en/guides/framework-components/)
- [Adding or managing content](https://docs.astro.build/en/guides/content-collections/)
- [Adding styles or using Tailwind](https://docs.astro.build/en/guides/styling/)
- [Supporting multiple languages](https://docs.astro.build/en/guides/internationalization/)
