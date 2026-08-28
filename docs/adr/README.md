# Architecture decision records

This directory records the decisions behind redlines 1.0 — the reasoning, the alternatives that were considered and rejected, and the conditions under which each decision should be revisited.

## Why these exist

[`docs/PRD.md`](../PRD.md) says what the product is. [`ROADMAP.md`](../../ROADMAP.md) says which release each feature is in. Neither is a good place to keep *why* a choice was made, because both get rewritten as the product changes, and rewriting erases the reasoning. An ADR is written once, is never edited except to change its status, and is superseded rather than updated. In a year, when someone (including us) asks "why doesn't redlines write DOCX?", the answer should be a file, not a memory.

## Conventions

- One decision per file, numbered in the order they were taken: `NNNN-short-title.md`.
- **Status** is one of: Proposed (recommended, not yet agreed), Accepted, Superseded by ADR-NNNN, or Deprecated.
- An accepted ADR is not edited when we change our minds. A new ADR is written that supersedes it, and the old one's status is changed to point at the new one. The trail of superseded decisions is the point.
- Each ADR ends with **Revisit when**: the concrete signal that should make us reopen it. A decision with no revisit condition is usually a decision that was never really made.

## Index

| ADR | Title | Status |
|---|---|---|
| [0001](0001-format-neutral-structural-engine.md) | Build a format-neutral structural comparison engine | Accepted |
| [0002](0002-primary-persona-agent-developers.md) | Optimise for LLM and agent pipeline developers | Accepted |
| [0003](0003-compatibility-facade.md) | Ship 1.0 with a compatibility facade, not a clean break | Accepted |
| [0004](0004-stdlib-core-optional-extras.md) | Keep a stdlib core with optional extras | Accepted |
| [0005](0005-minimal-core-open-semantic-layer.md) | Minimal structural core with an open semantic layer | Accepted |
| [0006](0006-structure-profiles.md) | Drive readers with declarative structure profiles | Accepted |
| [0007](0007-no-ocr-no-llm-in-library.md) | No OCR and no LLM calls inside the library | Accepted |
| [0008](0008-multi-pass-block-alignment.md) | Align blocks in explainable passes | Accepted |
| [0009](0009-moves-before-splits.md) | Detect moves and renumbering in 1.0; splits and merges later | Accepted |
| [0010](0010-keep-difflib-for-leaf-diffs.md) | Keep difflib as the leaf differ | Accepted |
| [0011](0011-json-canonical-annotated-renderer.md) | JSON as the canonical change format, with an annotated renderer | Accepted |
| [0012](0012-html-like-addresses.md) | Address blocks with HTML-like paths and document labels | Accepted |
| [0013](0013-the-1-0-slice-text-and-markdown.md) | Limit 1.0 to plain text and markdown | Accepted |
| [0014](0014-no-ooxml-writing.md) | Never write OOXML; delegate tracked changes to appliers | Accepted |
| [0015](0015-verify-mode-in-1-0.md) | Ship verify mode in 1.0 | Accepted |
| [0016](0016-summary-renderer-in-core.md) | Implement the summary renderer in core, deliver it with MCP | Accepted |
| [0017](0017-separate-mcp-package.md) | Publish the MCP server as a separate package | Accepted |
| [0018](0018-mcp-tools-prompts-resources.md) | Use MCP tools, prompts and resources so models can author profiles | Accepted |
| [0019](0019-client-side-demo-site.md) | Run the demo site entirely in the browser | Accepted |
| [0020](0020-mcp-before-site.md) | Ship the MCP server before the site | Accepted |
| [0021](0021-alignment-benchmark.md) | Make alignment quality measurable with our own benchmark | Accepted |
| [0022](0022-keep-the-name.md) | Keep the name redlines | Accepted |
| [0023](0023-python-support-and-typing.md) | Keep Python 3.10+ and strict typing | Accepted |
| [0024](0024-no-formatting-change-detection.md) | No inline formatting change detection in 1.0 | Accepted |
| [0025](0025-cli-as-thin-skin.md) | Treat the CLI and the MCP server as two skins over one function table | Accepted |
| [0026](0026-docs-site-on-astro-starlight.md) | Publish the documentation with Astro Starlight, in the same site as the demo | Accepted |
| [0027](0027-agent-docs-machine-surface.md) | Serve agents with a machine surface and a contract page, not a guide | Accepted |
| [0028](0028-api-reference-from-griffe.md) | Generate the API reference from griffe as native site pages | Proposed |

## Evidence base

Most of these decisions rest on a survey of the 2026 redlining landscape: [competitive-landscape-2026-08.md](../competitive-landscape-2026-08.md). Where an ADR cites a competitor's behaviour, that file has the source.
