# redlines documentation site

Astro + Starlight. Serves the hand-written documentation and, under `/api/`, the
pdoc reference generated from docstrings. The Pyodide demo becomes a route here
in M6.

```bash
npm install
npm run dev      # runs pdoc first, then the dev server
```

`npm run api` regenerates the pdoc output on its own. It writes to
`public/api/`, which is generated and not committed, so it needs the Python
development environment (`uv sync --all-extras --dev`) available in the
repository root.

Nothing in this directory is imported by the `redlines` wheel, nothing in the
wheel depends on this building, and a broken build here must never block a
release. See [ADR-0026](../docs/adr/0026-docs-site-on-astro-starlight.md) and
[ADR-0027](../docs/adr/0027-agent-docs-machine-surface.md).
