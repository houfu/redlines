# ADR-0019: Run the demo site entirely in the browser

**Status:** Accepted
**Date:** 2026-08-26
**Deciders:** houfu

## Context

The second end deliverable is a website where someone drops two documents and sees the changes — a usable tool, not a screenshot. Three ways to build it: client-side Python compiled to WebAssembly (Pyodide) on static hosting; a server-hosted Python app; or Streamlit, as with PLUS Explorer.

The documents in question are contracts. "Your documents never leave your machine" is the claim every competitor demo makes — python-redlines' demo runs Docxodus as WASM client-side, jubarte's site says the same — and it is the first thing a legal user checks.

## Decision

The site is static and runs the published redlines wheel in Pyodide inside a web worker. No backend, no upload endpoint, no analytics on document content, and a plain statement to that effect on the page. Hosted on GitHub Pages, source in the main repository under `site/` so the wheel and the site version together.

A corollary becomes a standing constraint: **the core and every 1.0 reader must import under Pyodide**, checked by a CI job that builds the wheel and imports it in a browser runtime. Extras that are unavailable degrade gracefully.

Checked on 26 August 2026 against Pyodide 0.28: lxml, rich, click and pydantic are built in; python-docx and pypdf are pure-Python wheels installable with micropip; **rapidfuzz and python-Levenshtein are C extensions with no Pyodide build**. Since 1.0 reads only text and markdown (ADR-0013), 1.0 needs no extras at all in the browser.

The site shows: two inputs (drop, upload or paste), the sample pair loaded by default, a block-change list with roles and addresses expandable to inline redlines, the annotated document, the summary, and the JSON with a copy button, plus a `dropped` notice per file and a profile selector.

## Alternatives considered

**Server-hosted app.** Simplest engineering, any dependency, could add model-backed features. Rejected: uploaded contracts would touch our server — a real objection for the intended audience — and it costs money to run unattended.

**Streamlit.** Fast to build and familiar. Rejected: server-side uploads again, limited control over the diff UI, and it reads as a demo rather than a tool.

## Consequences

Positive: zero hosting cost, a privacy claim that is true by construction, and a forcing function that keeps the library light. It also proves the dependency discipline in public.

Negative: a 10–15 MB initial runtime load; no model-backed features on the site ever (which is consistent with ADR-0007 but means the site cannot answer questions about a diff); and **alignment in the browser runs on the difflib-ratio fallback rather than rapidfuzz**, so if tuned and untuned quality diverge noticeably, the site will under-sell the engine. That divergence must be measured (ADR-0021) and either closed or disclosed.

There is also a scope risk: a site that works well invites requests for accounts, history and DOCX download. Anything needing a server is out of scope by construction, and that is the answer.

## Revisit when

If the Pyodide load time or the difflib/rapidfuzz gap makes the site unrepresentative, consider a pure-Python similarity implementation in core (see ADR-0004) rather than a server.

## Related

ADR-0004, ADR-0007, ADR-0013, ADR-0020, ADR-0021.
