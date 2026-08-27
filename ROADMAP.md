# Roadmap to redlines 1.0

**Status:** candidate curation for houfu to review, 26 August 2026
**Relationship to the other documents:** the `PRD` reference in each row is a requirement number (R*) or a decision number (D*). Decisions now live as ADRs in [`docs/adr/`](docs/adr/README.md); PRD section 6 maps every old D-number onto its ADR.

**Relationship to the PRD:** [`docs/PRD.md`](docs/PRD.md) says what each feature is and why it exists. This file says which release it is in. Where the two disagree, this file wins on release assignment, and the PRD should be updated to match once you have curated it.

## How to read this

Sizes are rough, for one experienced developer working with an agent: **S** is a day or two, **M** is up to a week, **L** is one to three weeks. They are for ranking, not estimating. Each feature cites its PRD requirement so you can look up the detail. Section 5 lists the places where I trimmed 1.0 below what the PRD currently says; those are the decisions this file exists to surface.

## 1. Releases at a glance

| Release | What it proves | Contents in one line |
|---|---|---|
| **0.6.x** (hygiene) | The flat engine is trustworthy while 1.0 is built | autojunk off, cleanup pass, sentence mode keeps paragraphs, regression corpus, benchmark failure investigation |
| **1.0** (the slice) | Structural, semantic, format-neutral comparison works end to end on text and markdown | block model + semantic layer + profiles; text and markdown readers; alignment with moves and renumbering; change tree and JSON schema; annotated, summary, markdown, rich and HTML renderers; verify; CLI; compatibility layer; benchmark |
| **redlines-mcp 0.1** (with 1.0) | Agents can compare, verify and author profiles | tools, prompts, resources, skill, golden tests; stdio transport |
| **Site 1.0** (after MCP) | A visitor sees the thesis in one click | Pyodide, text and markdown inputs, sample pair by default, block-change list, annotated view, summary, JSON |
| **1.1** | More inputs and more detection, same core | HTML, DOCX and PDF readers; split/merge; applier export; profile auto-selection; `legislation` profile; MCP HTTP transport; side-by-side view |
| **Later** | Only with demand in hand | formatting changes, comments and footnotes, XML renderer, permalinks, batch API, Akoma Ntoso reader |

## 2. The 1.0 feature list, by milestone

### M0 — 0.6.x hygiene release

| Feature | PRD | Size | Notes |
|---|---|---|---|
| `autojunk=False` on the SequenceMatcher, exposed as an option | D8 | S | One argument; measure speed on the 1,050-token repetitive case |
| Cleanup pass merging adjacent ops split only by punctuation or whitespace | D8, R15 | S | Fixes "thirty (30)" → two changes |
| Sentence mode preserves paragraph boundaries | D9, R16 | S | |
| Regression corpus including a repetitive schedule and the course examples as golden files | section 12 (compatibility risk) | S | These golden files are reused by M4 |
| Investigate the 18 `neurotic_docx_bench` failures | step 1 | S | Read-only investigation; fix only if trivial |

**Exit:** 0.6.x on PyPI; existing test suite green; the repetitive-schedule case reports a two-token change.

### M1 — Block model, semantic layer, profiles, readers

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Block model dataclasses: kind, text, label, level, path, children, attrs | R1 | S | Frozen dataclasses; no behaviour yet |
| Semantic fields: `role` on blocks, `spans` in blocks, open vocabulary with a recommended set | R1a, D5 | S | Vocabulary documented, not enforced |
| Profile format: flat, commented, schema-validated; loadable from file or mapping | R1d, R1e, R1f, D30 | M | The first design task; must satisfy R1f legibility |
| Built-in profiles: `generic`, `contract`, `markdown` | D30 | M | `legislation` moved to 1.1, see section 5 |
| Plain-text reader: normalise, segment, re-join wraps, detect labels, infer hierarchy, attach continuations, score headings | R4, D17, section 6b | L | The hard part is hierarchy inference; hard cases from 6b in the test set from day one |
| Markdown reader: ATX headings, lists with nesting, numbered clause patterns, pipe tables, fenced code, paragraphs; stdlib regex | R5, D16 | M | Reuses label detection and continuation logic from the text reader |
| Semantic pass: definitions, definition blocks with defined-term spans, schedules, cross-references carrying the referenced label, parties, dates, amounts | R1b, R1c | M | Rule-driven from the profile |
| Reader interface with a worked third-party example | R7 | S | |
| `dropped` reporting and per-block `matched_by` plus confidence; tree-level fallback count | R3, R1d | S | |
| Format detection for txt and md; unknown types reported, not guessed | R8b | S | |
| Section 3a sample pair and its expected block trees | section 3a | S | The change-tree golden comes in M2 |
| Pyodide import check in CI | D28, N5 | S | Do it here so nothing later depends on a dependency the browser cannot load |

**Exit:** the sample pair parses into the expected trees under `contract` and `markdown`; every 6b hard case has a test, passing or explicitly xfail; the wheel imports in Pyodide.

### M2 — Alignment, change tree, benchmark

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Multi-pass alignment: exact, label, fuzzy (difflib ratio; rapidfuzz if installed), positional; configurable thresholds; `matched_by` per pair | R9, D6 | L | |
| Move detection | R10, D7 | M | Release gate: move recall ≥ 0.9 on synthetic mutations, no reviewer-rejected false positive on the hand-labelled set |
| Renumbering detection | R11, D7 | S | Falls out of label-vs-content matching |
| Table alignment for markdown pipe tables: row insert/delete, cell-level inline diff; no column operations | R14 | M | Minimal, see section 5 |
| Determinism guarantee and test | R13, N1 | S | |
| Change tree: block ops insert, delete, modify, move, renumber; inline ops under modify; role and span types carried on change nodes | R18, R1c | M | |
| JSON serialisation with published schema and `schema_version` | R19, D10 | M | The integration point for MCP and the site; freeze early |
| Filters by kind, address prefix, label, role, minimum size | R23 | S | |
| Per-block and per-section statistics; change density by section | R22 | S | |
| R27a: inline changes recoverable as (address, old, new, context) | R27a | S | Design constraint, tested |
| Synthetic-mutation corpus generator: apply known moves, splits, renumberings, edits to real documents and keep the labels | D19 | M | Ground truth for free |
| Alignment metric: correspondence precision/recall, move recall, renumber recall; baselines flat 0.6 and, on DOCX pairs later, python-redlines | D19, section 10 | M | Report published with the release |
| Small hand-labelled set: ten real pairs | D19 | M | Labelling is the cost, not code |

**Exit:** the section 3a golden change tree passes; move gate met; benchmark report exists with numbers for 0.6 and 1.0 on the same corpus; JSON schema frozen.

### M3 — Renderers and compatibility

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Markdown renderer over the tree, all six existing styles | R20 | M | Byte-identical to 0.6 on the golden files from M0 |
| Rich terminal renderer over the tree | R20 | S | |
| HTML renderer: block list with roles and addresses, expandable inline redlines | R20 | M | Minimal; the site builds on it, see section 5 |
| Annotated-document renderer: CriticMarkup for text and markdown, tag variant for HTML | R21a, D10 | M | Promoted to 1.0 Must, see section 5 |
| `Redlines` facade: existing class reimplemented as one-block-per-paragraph over the new core | R45, D3 | M | 0.6 suite passes unmodified |
| Deprecation warnings, no removals | R46 | S | |

**Exit:** 0.6 test suite green unmodified; README and course example strings byte-identical; annotated view of the sample pair reads correctly.

### M4 — Verify, CLI, docs: the 1.0 release

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Verify: original, edited, allowed scope by address, label or role; pass/fail with out-of-scope changes and structural side effects | R24, D14 | M | Text-anchor scope moved to 1.1, see section 5 |
| Verify exemptions: whitespace-only, label-only | R25 | S | |
| Shared argument layer: path, stdin, inline; format hint; profile; size limit | R30a, D29 | S | Reused by the MCP package |
| CLI subcommands `compare`, `summary`, `annotate`, `verify`; `--profile`, `--format` | R28, R29 | S | About a day in total |
| Existing subcommands and command-less default unchanged | R30 | S | |
| Agent guide rewritten for compare, annotate, summary, verify, profiles | N6 | M | |
| JSON schema and profile schema published in the docs | N6 | S | |
| Performance check: 2,000-block markdown pair under five seconds native | N2 | S | |

**Exit:** 1.0 on PyPI; agent guide live; benchmark report linked from the README.

### M5 — `redlines-mcp` 0.1

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Package skeleton depending on a compatible `redlines` range; console entry point; stdio transport | R31, D18 | S | HTTP transport moved to 1.1, see section 5 |
| Tools: `compare`, `summary`, `annotate`, `verify`, `read_blocks`, `preview_structure`, `validate_profile` | R32, D26 | M | Thin over the shared argument layer |
| Prompts: `draft_profile`, `refine_profile` | R32a | M | The profile-authoring loop; `explain_changes` moved to 1.1, see section 5 |
| Resources: profile schema, built-in profiles, change-tree schema, skill text | R32b | S | |
| Summary renderer, implemented in core, surfaced here | R21, D15 | M | |
| Skill text with the canonical loop and a worked transcript against the sample pair | R32c, R33 | M | |
| Size guards and truncation with continuation hints | R34 | S | |
| Golden tests over stdio for every tool and a replayed profile-authoring loop | R36, R32c | M | |
| Registry listings and one-line installs for Claude Code, Claude Desktop, Cursor | R35 | S | Marketing, not code; do it on release day |

**Exit:** a fresh Claude Code session can install the server, run the sample comparison, author a profile for a new document in the loop, and verify an edit, with no human intervention beyond the prompt.

### M6 — Site 1.0

| Feature | PRD | Size | Notes |
|---|---|---|---|
| Static site, Pyodide in a web worker, loads the published wheel | R37, D23 | M | |
| Two inputs: drop or upload txt/md, or paste; sample pair loaded by default; friendly "coming in 1.1" for other types | R38 | M | |
| Views: block-change list with roles and addresses, expandable inline redlines; annotated document; summary; JSON with copy; `dropped` notice | R39 | M | Density view moved to 1.1, see section 5 |
| Profile selector with the built-ins and a paste box for a custom profile | R1e | S | |
| Progress state; 2,000-block pair under ten seconds after load | R40 | S | |
| Privacy statement; no upload endpoint; no content analytics | R41 | S | |
| Browser matrix and a clear failure message when Pyodide cannot load | R42 | S | |
| Source lives in the main repo under `site/`, built by CI | section 13 | S | |

**Exit:** site live on GitHub Pages; sample pair renders on first load; a pasted 100-page markdown contract completes within budget on a mid-range laptop.

## 3. 1.1

| Feature | PRD | Size | Why not 1.0 |
|---|---|---|---|
| HTML reader (stdlib parser) | R8 | M | Cheapest new reader; first in the queue |
| DOCX reader as `[docx]` extra on python-docx | R6, D12 | M | Your deferral; styles will improve the semantic pass, so early in 1.1 |
| PDF text reader as `[pdf]` extra on pypdf, structure flagged inferred, never OCR | R8a | M | Weakest path; after DOCX |
| Split and merge detection | R12, D7 | L | The main alignment feature after moves |
| Applier export: adeu edit batch, then superdoc-redlines edits file; round-trip convenience | R26, R27, D13 | M | Your deferral; R27a keeps the door open |
| Profile auto-selection with confidence | D30 | M | Trimmed from 1.0, see section 5 |
| `legislation` built-in profile | D30 | M | Trimmed from 1.0, see section 5 |
| Verify scope by text anchor | R24 | S | Trimmed from 1.0, see section 5 |
| MCP streamable HTTP transport | R31, D26 | S | Trimmed from 1.0, see section 5 |
| MCP `explain_changes` prompt | R32a | S | Trimmed from 1.0, see section 5 |
| Site side-by-side view with synchronised scrolling | R43 | M | Every competitor has it; the block list is what is different |
| Site per-section density view | R39 | S | Trimmed from 1.0, see section 5 |
| `[fuzzy]` threshold tuning from benchmark results | D6 review gate | M | Needs the benchmark to exist first |
| markdown-it based reader | D16 | M | Only if the regex reader proves insufficient |
| Expand hand-labelled benchmark set | D19 | M | Ongoing |

## 4. Later, only with demand

Inline formatting change detection (D22). Comments, footnotes, headers and footers as parts. XML renderer over the change tree (6a). Site permalinks encoding inputs in the URL fragment (R44). Batch comparison API. Akoma Ntoso and other structured-XML readers via the reader interface. Native OOXML revision writer (D13, and probably never). Three-way merge. Any OCR or in-library LLM call (never, per section 3 non-goals; a model-backed semantic pass belongs outside the library).

## 5. Calls I made that trim 1.0 below the PRD — please accept or overturn

1. **`legislation` profile to 1.1.** The demo scenario is a contract and the primary persona's inputs are contracts and LLM drafts. But PLUS Explorer and your own work are legislation, so if you want a statute in the demo, pull it back and budget an extra M in M1.
2. **Profile auto-selection to 1.1.** 1.0 defaults to `contract` for plain text and `markdown` for `.md`, with `--profile` to override. Auto-selection is nice on the site but is scoring logic that can wait until there are more than three profiles.
3. **Verify text-anchor scope to 1.1.** Addresses, labels and roles cover the agent use case; free-text anchors bring the ambiguity problem adeu is fighting.
4. **MCP HTTP transport to 1.1.** Claude Code, Claude Desktop and Cursor all use stdio. HTTP matters for hosted agents, which are not the first audience.
5. **MCP `explain_changes` prompt to 1.1.** Useful, but the profile loop is the distinctive thing and the summary tool already gives a model what it needs.
6. **Annotated renderer promoted to 1.0 Must.** The PRD hedged; the MCP `summary` and `annotate` tools need it, so it is in M3.
7. **HTML renderer kept minimal in 1.0.** Block list plus expandable redlines; the site adds interaction on top rather than a second renderer.
8. **Table alignment kept minimal in 1.0.** Row insert/delete and cell inline diff for markdown pipe tables; no column operations, no merged cells. Enough for the sample pair's inserted row.
9. **Site density view to 1.1.** The stats exist in the JSON from M2; drawing them is UI work that does not prove anything new.
10. **Hand-labelled benchmark set capped at ten pairs for 1.0.** Enough to catch a wrong move; expansion is ongoing work.

If you overturn any of these, the size lands in the milestone named in the PRD reference and the exit criteria above should be re-read.

## 6. What is deliberately not sized here

The profile format design (M1) and the JSON schema (M2) are design tasks whose cost is thinking rather than typing; they are marked M but could be a week of argument each. The benchmark labelling (M2) is human time. Registry listings and the agent guide are writing. None of these should be squeezed to hit a date; they are the parts a fast implementation cannot make up for.
